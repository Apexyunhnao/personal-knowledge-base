# -*- coding: utf-8 -*-
"""存量卡去重合并（方案D 存量版）：
  向量粗筛相似对 → >0.95 直接合并 / 0.85-0.95 LLM 精判 → 合并执行

用法:
  python merge_duplicates.py --dry-run   # 只统计候选对
  python merge_duplicates.py             # 执行合并（默认先 dry-run 摘要）
"""
import argparse
import json
import os
import sys
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI

import sqlite3
from hybrid_search import _get_notes_collection, sync_note_embedding, remove_note_embedding

SIM_DIRECT = 0.99   # 预留(不用, 全部走 LLM 判定)
SIM_CAND = 0.97     # LLM 判定候选阈值(实测 text2vec 相似度虚高, 0.95 以下全是模板混叠区)
MAX_GROUP = 5       # 合并组上限(防链式误合: A~B同 B~C同 但 A~C不同)
MODEL = "deepseek-chat"

JUDGE_SYSTEM = """你是知识库去重判定员。给定两条知识卡片内容，判断它们是否表达"同一套可迁移方法论"：
- 同：同一套操作流程 / 同一判断标准的同义替换（换个说法但本质相同）
- 否：不同场景的不同方法 / 对同一场景的相反观点 / 互补的不同角度
- 不确定：难以判断
只输出 JSON: {"same": true|false|null, "reason": "一句话理由"}
true=同, false=否, null=不确定。"""


def load_cards():
    conn = sqlite3.connect("personal.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, content, tags, frontmatter FROM learning_notes "
        "WHERE tags LIKE '%小说萃取%' AND deleted_at IS NULL"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def find_candidates(cards):
    """逐卡向量查 top6, 收集相似对 (id_a, id_b, sim), 去重"""
    col = _get_notes_collection()
    pairs = {}
    for i, c in enumerate(cards, 1):
        try:
            results = col.query(query_texts=[c["content"]], n_results=6)
            ids = results["ids"][0]
            dists = results["distances"][0]
            for nid_str, dist in zip(ids, dists):
                nid = int(nid_str)
                if nid == c["id"]:
                    continue
                sim = max(0.0, 1.0 - (dist * dist) / 2.0)
                if sim > SIM_CAND:
                    key = tuple(sorted((c["id"], nid)))
                    if key not in pairs or sim > pairs[key]:
                        pairs[key] = sim
        except Exception as e:
            print(f"  卡{c['id']} 向量查询失败: {e}")
        if i % 500 == 0:
            print(f"  向量查重 {i}/{len(cards)}")
        time.sleep(0.02)
    return pairs


def judge_pairs(client, pairs_to_judge, id2content):
    """LLM 批量判定 (每批5对), 返回 {pair_key: same_bool}"""
    results = {}
    pair_list = list(pairs_to_judge.items())
    for i in range(0, len(pair_list), 5):
        batch = pair_list[i:i+5]
        lines = []
        for idx, ((a, b), sim) in enumerate(batch, 1):
            lines.append(f"[对{idx}] A: {id2content[a][:120]}")
            lines.append(f"     B: {id2content[b][:120]}")
        user = "判断以下每对是否同一方法论：\n" + "\n".join(lines) + \
               "\n\n输出 JSON 数组: [{\"idx\": 1, \"same\": true, \"reason\": \"...\"}, ...]"
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": JUDGE_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    temperature=0,
                    max_tokens=2000,
                )
                raw = resp.choices[0].message.content.strip()
                start = raw.find("[")
                end = raw.rfind("]") + 1
                arr = json.loads(raw[start:end]) if start >= 0 and end > start else []
                for item in arr:
                    idx = item.get("idx")
                    if 1 <= idx <= len(batch):
                        (a, b), _ = batch[idx-1]
                        results[(a, b)] = item.get("same")
                break
            except Exception as e:
                print(f"  判定批失败(重试{attempt+1}): {e}")
                time.sleep(2)
        time.sleep(0.3)
        if (i // 5 + 1) % 20 == 0:
            print(f"  已判定 {i+len(batch)}/{len(pair_list)} 对")
    return results


def do_merge(merge_groups):
    """执行合并: 每组 [主卡id, 被合并ids...]。主卡=最小id, sources/tags 合并, 删被合并卡"""
    conn = sqlite3.connect("personal.db", timeout=30)
    conn.row_factory = sqlite3.Row
    stats = {"merged": 0, "kept": 0}
    for main_id, victims in merge_groups:
        main = conn.execute("SELECT frontmatter, tags FROM learning_notes WHERE id=?", (main_id,)).fetchone()
        if not main:
            continue
        try:
            fm = json.loads(main["frontmatter"] or "{}")
        except Exception:
            fm = {}
        main_tags = [t.strip() for t in (main["tags"] or "").split(",") if t.strip()]
        for vid in victims:
            vrow = conn.execute("SELECT frontmatter, tags FROM learning_notes WHERE id=?", (vid,)).fetchone()
            if not vrow:
                continue
            try:
                vfm = json.loads(vrow["frontmatter"] or "{}")
            except Exception:
                vfm = {}
            # 合并 sources
            fm.setdefault("sources", []).extend(vfm.get("sources", []))
            fm.setdefault("merged_from", []).append(str(vid))
            # 合并 tags
            for t in [x.strip() for x in (vrow["tags"] or "").split(",") if x.strip()]:
                if t not in main_tags:
                    main_tags.append(t)
            # 删除被合并卡
            conn.execute("DELETE FROM learning_notes WHERE id=?", (vid,))
            remove_note_embedding(vid)
            stats["merged"] += 1
        conn.execute(
            "UPDATE learning_notes SET frontmatter=?, tags=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(fm, ensure_ascii=False), ", ".join(main_tags), main_id),
        )
        stats["kept"] += 1
    conn.commit()
    conn.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只统计候选对, 不合并")
    args = ap.parse_args()

    print("[1/4] 加载卡片...")
    cards = load_cards()
    print(f"  {len(cards)} 张小说卡")
    id2content = {c["id"]: c["content"] for c in cards}

    print("[2/4] 向量查重...")
    pairs = find_candidates(cards)
    print(f"  相似度>{SIM_CAND} 的候选对: {len(pairs)}")
    judge = pairs  # 全部走 LLM 判定(向量阈值不可靠, 不直接合并)
    print(f"  LLM 判定候选: {len(judge)} 对 (预估成本 1-3 元)")

    if args.dry_run:
        print(f"\n[dry-run] 候选对 {len(judge)} 对, 全部需 LLM 判定。执行将: 判定→合并(组上限{MAX_GROUP})")
        return

    # LLM 判定
    print("[3/4] LLM 判定候选对...")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY 未设置"); sys.exit(1)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    judge_results = judge_pairs(client, judge, id2content)
    same_pairs = [k for k, v in judge_results.items() if v is True]
    print(f"  判定为'同'的对: {len(same_pairs)}")

    # 合并组构建 (并查集 + 组大小上限防链式误合)
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for (a, b) in same_pairs:
        union(a, b)
    groups = {}
    for c in cards:
        groups.setdefault(find(c["id"]), []).append(c["id"])
    # 组大小上限: 超过 MAX_GROUP 的组保留前 MAX_GROUP 张, 其余不合并
    merge_groups = []
    for root, v in groups.items():
        if len(v) > 1:
            v = sorted(v)
            if len(v) > MAX_GROUP:
                v = v[:MAX_GROUP]
            merge_groups.append((v[0], [x for x in v[1:]]))
    total_victims = sum(len(v) for _, v in merge_groups)

    if not merge_groups:
        print("没有可合并的组")
        return

    print(f"\n[4/4] 执行合并: {len(merge_groups)} 组, 将删除 {total_victims} 张卡")
    stats = do_merge(merge_groups)
    print(f"完成: 合并组 {stats['kept']}, 删除 {stats['merged']} 张卡")
    # 最终统计
    conn = sqlite3.connect("personal.db")
    n = conn.execute("SELECT COUNT(*) c FROM learning_notes WHERE deleted_at IS NULL").fetchone()[0]
    print(f"库内剩余笔记: {n}")


if __name__ == "__main__":
    main()
