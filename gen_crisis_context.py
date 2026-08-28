# -*- coding: utf-8 -*-
"""生成金融危机补卡项目的详细上下文文档（从库拉真实数据）"""
import json
import sqlite3

DB = r"E:\Projects\rag-qa-project\personal.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

lines = []
lines.append("# 知识库金融危机板块补卡——详细上下文文档")
lines.append("")
lines.append("> 本文档由羔丸从知识库真实数据生成，供网页版 AI 分析使用。")
lines.append("")

# 1. 库概况
total = conn.execute("SELECT COUNT(*) FROM learning_notes WHERE deleted_at IS NULL").fetchone()[0]
lines.append(f"## 一、库概况")
lines.append(f"- 总卡片: {total}")
lines.append("- 表: learning_notes(id, title, topic, tags, content, source, format, frontmatter, created_at)")
lines.append("")
lines.append("### 来源分布 (source 前 20)")
for r in conn.execute("SELECT source, COUNT(*) n FROM learning_notes WHERE deleted_at IS NULL GROUP BY source ORDER BY n DESC LIMIT 20"):
    lines.append(f"- {str(r['source'])[:60]}: {r['n']}")
lines.append("")
lines.append("### 标签分布 (tags 列含关键词的卡片数)")
for kw in ["金融危机", "汇率", "黄金", "做空", "投资", "理财", "风险", "负债", "通胀", "资产"]:
    n = conn.execute("SELECT COUNT(*) FROM learning_notes WHERE deleted_at IS NULL AND tags LIKE ?", (f"%{kw}%",)).fetchone()[0]
    lines.append(f"- 含「{kw}」标签: {n} 卡")

# 2. 检索逻辑
lines.append("")
lines.append("## 二、检索逻辑")
lines.append("- 混合检索 hybrid_search: FTS5 全文 + 向量(text2vec) + 标签召回，RRF 融合")
lines.append("- 来源加权: book 1.3 / note 1.2 / forum 0.85 / novel 0.6")
lines.append("- 置信度下限过滤，低置信度可选包含")
lines.append("")

# 3. 评估集
with open(r"E:\Projects\rag-qa-project\evaluation\adversarial_judged.json", encoding="utf-8") as f:
    judged = json.load(f)
lines.append("## 三、对抗评估集（53 条，按板块）")
by_cat = {}
for item in judged:
    cat = item["category"]
    by_cat.setdefault(cat, []).append(item["query"])
for cat, qs in by_cat.items():
    lines.append(f"### {cat} ({len(qs)} 条)")
    for q in qs:
        lines.append(f"- {q}")
lines.append("")
lines.append("### 整体结果（最近一次 judge）")
lines.append("- 召回率(相关+部分): 79.4%")
lines.append("- 金融危机: 55.0% (22/40) —— 唯一弱项")

# 4. 金融危机板块检索样例（当前库实际返回）
lines.append("")
lines.append("## 四、金融危机相关卡片样例（SQLite 关键词检索，真实数据）")
fin_kws = ["金融危机", "囤现金", "黄金", "做空", "汇率", "日元"]
for kw in fin_kws:
    lines.append(f"### 含「{kw}」的卡片（标题，前 10）")
    try:
        rows = conn.execute(
            "SELECT title, source, tags FROM learning_notes WHERE deleted_at IS NULL AND (title LIKE ? OR content LIKE ?) LIMIT 10",
            (f"%{kw}%", f"%{kw}%"),
        ).fetchall()
        if not rows:
            lines.append("（无卡片命中）")
        for r in rows:
            lines.append(f"- {str(r['title'])[:45]} | 来源: {str(r['source'])[:20]} | tags: {str(r['tags'])[:30]}")
    except Exception as e:
        lines.append(f"（异常: {e}）")
    lines.append("")

# 5. 已有书单
lines.append("## 五、已入库书籍/内容")
books = [
    ("《金钱心理学》", 544, "已入库"),
    ("《原子习惯》", 580, "已入库"),
    ("《自控力》", 734, "已入库"),
    ("《非暴力沟通》", 477, "已入库"),
    ("《学会提问》", 613, "已入库"),
    ("《人性的弱点》", "?", "已入库"),
    ("《这就是人性》", "?", "已入库"),
    ("《打破你的学生思维》", 836, "已入库"),
    ("天涯神贴精选", "13000+", "已入库"),
    ("小说《从做空次贷危机开始收割世界》", 4982, "已入库(做空次贷)"),
    ("穷查理宝典", 0, "导出失败，无权限，放弃"),
]
for b, n, s in books:
    lines.append(f"- {b}: {n} 卡 {s}")
lines.append("")

# 6. 要问的问题
lines.append("## 六、请分析的问题")
lines.append("1. 金融危机板块为什么弱？结合上面的检索结果样例（哪些 query 返回了什么）给根因")
lines.append("2. 补哪些书/内容最快提升？(考虑微信读书可获取性、萃取成本)")
lines.append("3. 检索层还有什么优化空间？(标签、权重、embedding、查询改写等)")
lines.append("4. 给 1-2 周可执行的优先级行动方案")
lines.append("")
lines.append("要求：直接给可执行建议，不要泛泛而谈。中文回答。")

doc = "\n".join(lines)
out = r"E:\Projects\rag-qa-project\outputs\金融危机补卡_详细上下文.md"
with open(out, "w", encoding="utf-8") as f:
    f.write(doc)
print(f"已生成: {out}  ({len(doc)} 字)")
