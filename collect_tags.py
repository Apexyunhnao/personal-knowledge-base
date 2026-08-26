# -*- coding: utf-8 -*-
"""收集全部核心标签 + 计数，落盘供聚类"""
import sqlite3, json, os
from collections import Counter

DB = "/mnt/e/Projects/rag-qa-project/personal.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT tags FROM learning_notes WHERE deleted_at IS NULL").fetchall()

core_counter = Counter()
ext_counter = Counter()
for r in rows:
    tags = [t.strip() for t in r["tags"].split(",") if t.strip()]
    # 跳过固定标签（书签/来源标记）
    fixed = {"小说萃取", "从做空次贷危机开始收割世界", "天涯神贴精选", "打破你的学生思维"}
    tags = [t for t in tags if t not in fixed]
    for t in tags:
        core_counter[t] += 1

out = {
    "total_notes": len(rows),
    "core_tag_count": len(core_counter),
    "ext_tag_count": len(ext_counter),
    "core_tags": [{"tag": t, "count": c} for t, c in core_counter.most_common()],
    "ext_tags": [{"tag": t, "count": c} for t, c in ext_counter.most_common()],
}
os.makedirs("/mnt/e/Projects/rag-qa-project/evaluation", exist_ok=True)
with open("/mnt/e/Projects/rag-qa-project/evaluation/tags_all.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

# 分布统计
n = len(core_counter)
counts = sorted(core_counter.values(), reverse=True)
print(f"笔记数: {len(rows)}, 核心标签种类: {n}, 扩展标签种类: {len(ext_counter)}")
print(f"计数≥10: {sum(1 for c in counts if c>=10)} 种")
print(f"计数≥5: {sum(1 for c in counts if c>=5)} 种")
print(f"计数≥3: {sum(1 for c in counts if c>=3)} 种")
print(f"计数1-2: {sum(1 for c in counts if c<=2)} 种 (低频)")
top10 = core_counter.most_common(10)
print("TOP10:", top10)
# TOP100 覆盖
top100 = sum(c for _, c in core_counter.most_common(100))
total = sum(counts)
print(f"TOP100 标签覆盖卡次: {top100}/{total} = {top100/total*100:.1f}%")
