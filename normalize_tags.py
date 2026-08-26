# -*- coding: utf-8 -*-
"""标签归一化：LLM 聚类 1235 种核心标签 → 映射表（分3批防截断）→ 落盘供人工校验

用法: python normalize_tags.py [--apply]    # 默认只生成映射表; --apply 才写库
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, "/mnt/e/Projects/rag-qa-project")
os.chdir("/mnt/e/Projects/rag-qa-project")

from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI

MODEL = "deepseek-chat"
BATCH = 400  # 每批标签数
TOP_N = 200   # 0=全部; >0 只处理前N个高频标签

SYSTEM = """你是中文标签归一化专家。以下是个人知识库中的核心标签列表（格式：标签|出现次数）。
请把语义相同、近义、或属于同一词族的标签归一到同一个规范标签（重要：这是主要任务，要主动合并）：
- 同义词族示例（这些都要归并）：
  * 危机管理/危机应对/危机决策/危机处理/危机管控/危机处置 → 危机管理
  * 职场谈判/谈判策略/谈判技巧/商务谈判/商业谈判/交易谈判/金融谈判 → 商业谈判
  * 风险管理/风险控制/风险防范/风险规避/风险意识 → 风险管理
  * 投资决策/投资策略/投资判断/投资选择 → 投资决策
  * 领导力/领导艺术/管理能力/管理智慧 → 领导力
  * 职场沟通/沟通技巧/沟通策略/沟通能力 → 职场沟通
- 词族归并判定：词根相同（如"危机XX"/"谈判XX"）且语义相近 → 必须归并到词根对应的规范名
- 不同主题的词族（谈判 vs 危机 vs 投资）绝对不合并
- 子维度差异保留：如"危机公关""危机沟通"与"危机管理"是不同方法维度，可保留独立（除非语义几乎相同）
- 出现次数≤2 的冷门标签：若是某词族的同义词则归入该词族，否则原样保留
- 规范标签优先选出现次数最多、最简洁准确的名称（≤6字）
只输出 JSON 对象，格式 {"原标签": "规范标签"}，所有输入标签必须恰好出现一次，不要输出任何其他文字。"""

def build_prompt(items: list[dict]) -> str:
    lines = [f"{t['tag']}|{t['count']}" for t in items]
    return "标签列表（共%d个）：\n%s" % (len(items), "\n".join(lines))

def parse_mapping(raw: str) -> dict:
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start < 0 or end <= start:
        return {}
    return json.loads(raw[start:end])

def cluster(client, items: list[dict]) -> dict:
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": build_prompt(items)},
                ],
                temperature=0,
                max_tokens=4000,
            )
            raw = resp.choices[0].message.content.strip()
            mapping = parse_mapping(raw)
            if mapping:
                return mapping
        except Exception as e:
            print(f"  批失败(重试{attempt+1}): {e}")
            time.sleep(2)
    return {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库替换标签")
    args = ap.parse_args()

    data = json.load(open("evaluation/tags_all.json", encoding="utf-8"))
    core_tags = data["core_tags"]  # [{tag, count}] 已按计数降序
    if TOP_N > 0:
        core_tags = core_tags[:TOP_N]
        print(f"只处理 TOP{TOP_N} 高频标签")

    if os.path.exists("evaluation/tags_mapping.json") and not args.apply:
        mapping = json.load(open("evaluation/tags_mapping.json", encoding="utf-8"))
        print(f"已有映射表: {len(mapping)} 条")
    else:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            print("DEEPSEEK_API_KEY 未设置"); sys.exit(1)
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

        mapping = {}
        for i in range(0, len(core_tags), BATCH):
            batch = core_tags[i:i+BATCH]
            print(f"[{i//BATCH+1}/{(len(core_tags)+BATCH-1)//BATCH}] 聚类 {len(batch)} 个标签...", flush=True)
            m = cluster(client, batch)
            mapping.update(m)
            print(f"  得到 {len(m)} 条映射")
            time.sleep(0.5)

        # 缺失的标签映射到自己
        missing = [t["tag"] for t in core_tags if t["tag"] not in mapping]
        for t in missing:
            mapping[t] = t
        with open("evaluation/tags_mapping.json", "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=1)
        print(f"映射表落盘: {len(mapping)} 条")

    # ── 规范名校正: 每组规范名取组内计数最大的原标签 ──
    count_by_tag = {t["tag"]: t["count"] for t in core_tags}
    rev = {}
    for src, dst in mapping.items():
        rev.setdefault(dst, []).append(src)
    for dst, srcs in rev.items():
        best = max(srcs, key=lambda s: count_by_tag.get(s, 0))
        if best != dst:
            for s in srcs:
                mapping[s] = best
    changed_names = sum(1 for srcs in rev.values() if len(srcs) > 1)
    print(f"规范名校正完成: {changed_names} 组")
    # 校正后写回映射表(否则 --apply 读旧文件)
    with open("evaluation/tags_mapping.json", "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)

    # ── 预览报告 ──
    if not args.apply:
        norm_counts = {}
        for t in core_tags:
            target = mapping.get(t["tag"], t["tag"])
            norm_counts[target] = norm_counts.get(target, 0) + t["count"]
        # 被合并的组
        merged_groups = {}
        for t in core_tags:
            target = mapping.get(t["tag"], t["tag"])
            if target != t["tag"]:
                merged_groups.setdefault(target, []).append(f"{t['tag']}({t['count']})")
        changed = sum(1 for t in core_tags if mapping.get(t["tag"], t["tag"]) != t["tag"])
        print(f"\n=== 归一化预览 ===")
        print(f"被合并(改名)的标签: {changed}/{len(core_tags)}")
        print(f"规范标签数量: {len(norm_counts)}")
        print("\n合并组示例(前25组):")
        for target, srcs in sorted(merged_groups.items(), key=lambda x: -sum(1 for _ in x[1]))[:25]:
            print(f"  {target} ← {', '.join(srcs[:5])}{' ...' if len(srcs)>5 else ''}")
        print(f"\n规范标签 TOP20(按覆盖卡次):")
        for tag, cnt in sorted(norm_counts.items(), key=lambda x: -x[1])[:20]:
            print(f"  {tag}: {cnt}")

    # ── 写库 ──
    if args.apply:
        import sqlite3
        conn = sqlite3.connect("personal.db")
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, tags FROM learning_notes WHERE tags LIKE '%小说萃取%' AND deleted_at IS NULL").fetchall()
        updated = 0
        for r in rows:
            tags = [t.strip() for t in r["tags"].split(",") if t.strip()]
            if len(tags) >= 3:
                new_core = [mapping.get(t, t) for t in tags[2:5]]
                # 去重保序(规范后可能重复)
                seen = set()
                new_core_dedup = []
                for t in new_core:
                    if t not in seen:
                        seen.add(t)
                        new_core_dedup.append(t)
                new_tags = tags[:2] + new_core_dedup + tags[5:]
                new_tags_str = ", ".join(new_tags)
                if new_tags_str != r["tags"]:
                    conn.execute("UPDATE learning_notes SET tags=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_tags_str, r["id"]))
                    updated += 1
        conn.commit()
        print(f"\n写库完成: 更新 {updated}/{len(rows)} 条笔记的标签")

if __name__ == "__main__":
    main()
