# -*- coding: utf-8 -*-
"""
入库脚本 — 按项目书 v2.0 3.5 框架实现
  章节级幂等(sha256) + 跨书/跨章合并(向量相似度>0.8) + frontmatter + 存量卡适配

用法:
  python import_to_kb.py --book 从做空次贷危机开始收割世界 [--limit N] [--dry-run]
  --dry-run  只统计不写库(输出: 章节hash状态、相似度分布、预计新建/合并数)
"""
import argparse
import hashlib
import json
import os
import sys
import time

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_pipeline as ep
from hybrid_search import _get_notes_collection, sync_note_embedding, remove_note_embedding

# ── 常量(对应项目书) ──
try:
    from extract_pipeline import EXTRACT_MODE as _EXTRACT_MODE
except Exception:
    _EXTRACT_MODE = "novel"
# 知识模式（科普/案例书）不要"小说萃取"标签——book 卡被当小说处理是历史 Bug
BOOK_TAG = "书籍萃取" if _EXTRACT_MODE == "knowledge" else "小说萃取"
CONF_CAP = 0.9 if _EXTRACT_MODE == "knowledge" else 0.7  # 非虚构来源上限可更高
MERGE_THRESHOLD = 0.93  # 跨书合并阈值(实测: text2vec对决策文本区分度差, 0.8导致93%坍缩, 提到0.93待校准)
LOW_CONF = 0.6          # 低置信度线
QUALITY_FLOOR = 0.5     # 入库质量下限: confidence < 0.5 直接丢弃(不入库不占向量空间)
                        # 依据 2026-08-26 分布统计: 库内最低 0.40(10条), 0.35 门控形同虚设
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "personal.db")

import sqlite3

def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

# ── 章节 hash ──

def chapter_hash(book: str, chapter: str) -> str:
    """对清洗后正文算 sha256(项目书3.5: 章节级幂等键)"""
    txt_path = None
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inputs", book)
    if os.path.isdir(base):
        # 按章节标题匹配: 文件名形如 0002_第2章 必死之局？.txt
        # 2026-08-28 修复: json title 是"二金融危机就要来了", 文件名带"0004_"序号+空格
        # 归一化(去空格/序号前缀/第字)后模糊匹配, 否则 hash 永远取不到→每次全量重入
        chapter_norm = chapter.replace("第", "").replace(" ", "")
        for fn in sorted(os.listdir(base)):
            fn_norm = fn.replace("第", "").replace(" ", "")
            # 去文件名序号前缀(0004_ / 0004- 等)
            import re as _re
            fn_norm = _re.sub(r"^\d+[_\-]", "", fn_norm)
            if chapter_norm in fn_norm or fn_norm in chapter_norm:
                txt_path = os.path.join(base, fn)
                break
    if not txt_path:
        return ""  # 找不到原文, hash 置空(视为未知, 走重入)
    raw = ep.read_text(txt_path)
    clean = ep.clean_text(raw)
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()

# ── 库内笔记查询 ──

def _parse_frontmatter(row) -> dict:
    fm = row["frontmatter"] or "{}"
    try:
        return json.loads(fm)
    except Exception:
        return {}

def find_note_for_source(book: str, chapter: str) -> list[int]:
    """查 frontmatter.sources 里包含 (book, chapter) 的笔记 id 列表"""
    with _conn() as db:
        rows = db.execute(
            "SELECT id, frontmatter FROM learning_notes WHERE deleted_at IS NULL"
        ).fetchall()
    found = []
    for r in rows:
        fm = _parse_frontmatter(r)
        for s in fm.get("sources", []):
            if s.get("book") == book and s.get("chapter") == chapter:
                found.append(r["id"])
                break
    return found

def remove_source_from_note(note_id: int, book: str, chapter: str) -> bool:
    """从笔记 sources 移除 (book, chapter)。返回该笔记是否被清空。"""
    with _conn() as db:
        row = db.execute("SELECT frontmatter FROM learning_notes WHERE id=?", (note_id,)).fetchone()
        if not row:
            return False
        fm = _parse_frontmatter(row)
        before = len(fm.get("sources", []))
        fm["sources"] = [s for s in fm.get("sources", []) if not (s.get("book") == book and s.get("chapter") == chapter)]
        emptied = before > 0 and len(fm["sources"]) == 0
        db.execute("UPDATE learning_notes SET frontmatter=? WHERE id=?", (json.dumps(fm, ensure_ascii=False), note_id))
        db.commit()
        return emptied

def delete_note(note_id: int):
    """物理删除笔记 + 向量(项目书: sources清空→删除)"""
    from personal_db import _permanent_delete
    try:
        _permanent_delete("notes", note_id)
    except Exception:
        with _conn() as db:
            db.execute("DELETE FROM learning_notes WHERE id=?", (note_id,))
            db.commit()
    remove_note_embedding(note_id)

# ── 相似度查重 ──

def find_merge_target(content: str, core_tags: list[str]) -> tuple[int | None, float]:
    """content+核心标签 向量查重, 返回 (note_id, similarity)。无匹配返回 (None, 0)"""
    col = _get_notes_collection()
    if col.count() == 0:
        return None, 0.0
    query_text = content + ("\n" + " ".join(core_tags) if core_tags else "")
    results = col.query(query_texts=[query_text], n_results=1)
    if not results["ids"] or not results["ids"][0]:
        return None, 0.0
    note_id = int(results["ids"][0][0])
    dist = results["distances"][0][0]
    # text2vec normalize + chroma 默认 l2: cos_sim = 1 - dist²/2
    sim = max(0.0, 1.0 - (dist * dist) / 2.0)
    return note_id, sim

# ── 卡片 → 笔记 ──

def adapt_old_card(card: dict) -> dict:
    """存量卡适配(项目书3.5): title取content前20字; 案例拆分; clamp"""
    c = dict(card)
    content = c.get("content", "")
    micro = ""
    if "案例：" in content:
        content, micro = content.split("案例：", 1)
        content = content.strip()
        micro = micro.strip()[:50]
    c["content"] = content
    c["micro_case"] = micro
    c["title"] = (c.get("title") or content[:20]).strip()
    c["confidence"] = min(float(c.get("confidence", 0.6)), CONF_CAP)
    return c

def _source_type_for(book: str) -> str:
    """按书名映射来源类型：网文/微信读书/天涯帖/原创"""
    if "从做空次贷" in book or "小说" in book:
        return "novel"      # 网文萃取
    if any(k in book for k in (
        "学生思维", "微信读书",
        "人情世故", "人性的弱点", "这就是人性",  # 2026-08-27 新增微信读书实体书
        "半小时漫画", "金钱心理学", "原子习惯", "自控力", "非暴力沟通", "学会提问",  # 2026-08-28 微信读书实体书
    )):
        return "book"       # 出版书籍（微信读书）
    if "天涯" in book:
        return "forum"      # 天涯帖子
    return "note"           # 个人笔记

def _below_quality_floor(card: dict) -> bool:
    """质量下限判断: confidence < QUALITY_FLOOR 丢弃（取 clamp 后值，与入库一致）"""
    return adapt_old_card(card)["confidence"] < QUALITY_FLOOR


def _record_discarded(book: str, card: dict):
    """记录被质量下限丢弃的卡到 outputs/<book>/discarded_quality.json（可查可逆）"""
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", book, "discarded_quality.json")
    entry = {
        "title": (card.get("title") or "")[:60],
        "confidence": card.get("confidence"),
        "source_ref": card.get("source_ref", ""),
        "content_preview": (card.get("content") or "")[:100],
    }
    try:
        existing = []
        if os.path.exists(out):
            with open(out, encoding="utf-8") as f:
                existing = json.load(f)
        existing.append(entry)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[警告] 丢弃记录写入失败: {e}")


def build_note_data(card: dict, book: str, chapter: str, ref: str, chapter_hash_val: str) -> dict:
    """组装 learning_notes 字段"""
    # 兼容两种卡片 schema: knowledge 模式用 tags, novel 模式用 scenario_tags
    raw_tags = card.get("tags") or card.get("scenario_tags", [])
    core_tags = raw_tags.get("core", []) if isinstance(raw_tags, dict) else (raw_tags or [])[:3]
    ext_tags = raw_tags.get("ext", []) if isinstance(raw_tags, dict) else []
    if not isinstance(core_tags, list): core_tags = []
    if not isinstance(ext_tags, list): ext_tags = []

    conf = min(float(card.get("confidence", 0.6)), CONF_CAP)
    is_low = conf < LOW_CONF

    fm = {
        "sources": [{"book": book, "chapter": chapter, "ref": ref}],
        "merged_from": [],
        "content_hash": chapter_hash_val,
        "confidence": round(conf, 2),
        "is_low_confidence": is_low,
        "node_type": card.get("node_type", "methodology"),
        "source_type": _source_type_for(book),
        "user_feedback": 0.0,
    }

    # tags: 小说萃取 + 书名 + 核心(≤3) + 扩展(全保留)
    tags = [BOOK_TAG, book] + core_tags[:3] + ext_tags
    # 2026-08-28: forecast 预测/断言卡加"预测"标签，检索时可区分/降权
    if card.get("node_type") == "forecast" and "预测" not in tags:
        tags.append("预测")
    tags = list(dict.fromkeys([t for t in tags if t]))  # 去重保序

    # content: 卡内容 + 微案例(展示用)
    content = card.get("content", "")
    if card.get("micro_case"):
        content += f"\n\n案例：{card['micro_case']}"

    return {
        "title": card.get("title", content[:20]),
        "topic": "其他",
        "tags": ", ".join(tags),
        "content": content,
        "source": f"《{book}》{chapter}",
        "format": "markdown",
        "frontmatter": json.dumps(fm, ensure_ascii=False),
    }

# ── 入库主流程 ──

def import_book(book: str, limit: int = 0, dry_run: bool = False, no_merge: bool = False, prefix: str = "") -> dict:
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", book)
    if not os.path.isdir(out_dir):
        print(f"输出目录不存在: {out_dir}")
        sys.exit(1)

    files = sorted(f for f in os.listdir(out_dir) if f.endswith(".json"))
    if prefix:
        files = [f for f in files if f.startswith(prefix)]
        print(f"前缀过滤 [{prefix}]: {len(files)} 章")
    if limit:
        files = files[:limit]
    print(f"处理 {len(files)} 章")

    stats = {"new": 0, "merged": 0, "skipped": 0, "reenter": 0, "deleted_empty": 0,
             "discarded": 0, "sims": [], "failed": []}

    for i, fn in enumerate(files, 1):
        with open(os.path.join(out_dir, fn), encoding="utf-8") as f:
            j = json.load(f)
        title = j.get("title", os.path.splitext(fn)[0])
        # 章节名从 title 提取(形如 "第2章 必死之局？")
        chapter = title.strip()
        cards = j.get("result", {}).get("cards", [])

        h = chapter_hash(book, chapter)
        existing = find_note_for_source(book, chapter)

        if h and existing:
            # 查库中该章节的 hash
            with _conn() as db:
                row = db.execute("SELECT frontmatter FROM learning_notes WHERE id=?", (existing[0],)).fetchone()
            fm = _parse_frontmatter(row) if row else {}
            stored_hash = fm.get("content_hash", "")
            if stored_hash == h:
                stats["skipped"] += 1
                print(f"[{i}/{len(files)}] 跳过(无变化) {chapter}")
                continue
            # hash 不同 → 整章重入
            stats["reenter"] += 1
            print(f"[{i}/{len(files)}] 重入(正文变化) {chapter}")
            if not dry_run:
                for nid in existing:
                    emptied = remove_source_from_note(nid, book, chapter)
                    if emptied:
                        delete_note(nid)
                        stats["deleted_empty"] += 1

        if dry_run:
            for card in cards:
                if _below_quality_floor(card):
                    stats["discarded"] += 1
                    continue
                if no_merge:
                    stats["new"] += 1
                    continue
                stats["new"] += 1
                adapted = adapt_old_card(card)
                _, sim = find_merge_target(adapted["content"], [])
                if sim > MERGE_THRESHOLD:
                    stats["merged"] += 1
                    stats["new"] -= 1
                stats["sims"].append(round(sim, 3))
            continue

        # 逐卡入库
        for card in cards:
            adapted = adapt_old_card(card)
            if adapted["confidence"] < QUALITY_FLOOR:
                stats["discarded"] += 1
                _record_discarded(book, card)
                continue
            ref = card.get("source_ref", "")
            if not no_merge:
                target_id, sim = find_merge_target(adapted["content"], [])
                if sim > MERGE_THRESHOLD and target_id:
                    # 合并: 追加 sources + 合并标签, title/content 不变
                    stats["merged"] += 1
                    merge_note(target_id, book, chapter, ref, adapted)
                    stats["sims"].append(round(sim, 3))
                    continue
            stats["new"] += 1
            data = build_note_data(adapted, book, chapter, ref, h)
            from personal_db import _create
            note_id = _create("notes", data)
            sync_note_embedding(note_id, data["title"], data["content"], data.get("tags", ""))
        time.sleep(0.1)

    return stats

def merge_note(note_id: int, book: str, chapter: str, ref: str, card: dict):
    """合并: frontmatter.sources 追加 + tags 合并场景。title/content/向量不变"""
    with _conn() as db:
        row = db.execute("SELECT frontmatter, tags FROM learning_notes WHERE id=?", (note_id,)).fetchone()
        if not row:
            return
        fm = _parse_frontmatter(row)
        # sources 按 3.4 语义: 一条记录=一段原文引用, 同章多处引用则多条记录, 不去重
        fm.setdefault("sources", []).append({"book": book, "chapter": chapter, "ref": ref})
        fm.setdefault("merged_from", []).append(f"{book}·{chapter}")
        # tags 合并场景标签
        core_tags = card.get("scenario_tags", {}).get("core", []) if isinstance(card.get("scenario_tags"), dict) else []
        ext_tags = card.get("scenario_tags", {}).get("ext", []) if isinstance(card.get("scenario_tags"), dict) else []
        tag_list = [t.strip() for t in (row["tags"] or "").split(",") if t.strip()]
        for t in list(core_tags[:3]) + list(ext_tags):
            if t and t not in tag_list:
                tag_list.append(t)
        db.execute(
            "UPDATE learning_notes SET frontmatter=?, tags=? WHERE id=?",
            (json.dumps(fm, ensure_ascii=False), ", ".join(tag_list), note_id),
        )
        db.commit()

def main():
    parser = argparse.ArgumentParser(description="入库: 幂等+跨书合并(项目书v2.0 3.5)")
    parser.add_argument("--book", required=True, help="书名(对应 outputs/<书>/)")
    parser.add_argument("--limit", type=int, default=0, help="只处理前N章")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    parser.add_argument("--no-merge", action="store_true", help="不合并, 每张卡独立入库(方案A)")
    parser.add_argument("--prefix", default="", help="只处理 outputs 中文件名前缀匹配的 json (如 '44-社会不教')")
    args = parser.parse_args()

    stats = import_book(args.book, args.limit, args.dry_run, args.no_merge, args.prefix)
    print(f"\n完成: 新建{stats['new']} 合并{stats['merged']} 跳过{stats['skipped']} "
          f"重入{stats['reenter']} 删空{stats['deleted_empty']} 丢弃{stats['discarded']} 失败{len(stats['failed'])}")
    if stats["sims"]:
        sims = sorted(stats["sims"])
        n = len(sims)
        print(f"相似度分布: n={n} min={sims[0]} p25={sims[n//4]} p50={sims[n//2]} "
              f"p75={sims[3*n//4]} max={sims[-1]}")
        over = sum(1 for s in sims if s > 0.8)
        print(f">0.8(合并): {over} ({over/n*100:.1f}%)  0.6-0.8: {sum(1 for s in sims if 0.6 < s <= 0.8)}  <=0.6: {sum(1 for s in sims if s <= 0.6)}")

if __name__ == "__main__":
    main()
