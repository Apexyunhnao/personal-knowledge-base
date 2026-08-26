#!/usr/bin/env python3
"""回填存量 frontmatter：confidence（从 outputs 卡片 JSON 读）+ source_type（按书名映射）

只更新 frontmatter 缺 confidence 或 source_type 不正确的笔记，不碰其他字段。
"""
import json, os, sqlite3, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_to_kb as ikb

BASE = os.path.dirname(os.path.abspath(__file__))
BOOKS = {
    "从做空次贷危机开始收割世界": os.path.join(BASE, "outputs", "从做空次贷危机开始收割世界"),
    "打破你的学生思维": os.path.join(BASE, "outputs", "打破你的学生思维"),
    "天涯神贴精选": os.path.join(BASE, "outputs", "天涯神贴精选"),
}

def load_card_confidence(out_dir):
    """加载 outputs/<书>/ 所有卡片的 confidence: (content前缀) -> confidence
    注：部分旧卡片 title 为空，用 content 前 25 字做匹配键（title 优先，content 兜底）"""
    conf_map = {}
    for fn in os.listdir(out_dir):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(out_dir, fn), encoding="utf-8") as f:
                j = json.load(f)
        except Exception:
            continue
        for c in j.get("result", {}).get("cards", []):
            title = (c.get("title") or "").strip()
            conf = c.get("confidence")
            if conf is None:
                continue
            if title:
                conf_map[("title", title)] = round(float(conf), 2)
            content = (c.get("content") or "").strip()
            if content:
                conf_map[("content", content[:25])] = round(float(conf), 2)
    return conf_map

def main():
    conn = sqlite3.connect(os.path.join(BASE, "personal.db"))
    conn.row_factory = sqlite3.Row

    # 加载所有书卡片的 confidence
    all_conf = {}
    for book, out_dir in BOOKS.items():
        if os.path.isdir(out_dir):
            all_conf.update(load_card_confidence(out_dir))
    print(f"加载卡片 confidence: {len(all_conf)} 条")

    rows = conn.execute(
        "SELECT id, title, content, tags, frontmatter FROM learning_notes WHERE deleted_at IS NULL"
    ).fetchall()

    updated = 0
    for row in rows:
        fm = json.loads(row["frontmatter"] or "{}")
        tags = row["tags"] or ""
        book = ""
        # 从 tags 提取书名（tags[1]）
        parts = [t.strip() for t in tags.split(",") if t.strip()]
        if len(parts) >= 2 and parts[0] == "小说萃取":
            book = parts[1]
        elif len(parts) >= 1 and any(b in parts[0] for b in ["天涯", "学生思维"]):
            book = parts[0]

        changed = False
        # confidence：缺则从卡片 JSON 读（title 匹配失败则用 content 前缀）
        if "confidence" not in fm:
            title = (row["title"] or "").strip()
            conf = all_conf.get(("title", title))
            if conf is None:
                content = (row["content"] or "").strip()
                conf = all_conf.get(("content", content[:25]))
            if conf is not None:
                fm["confidence"] = conf
                changed = True
        # source_type：按书名映射
        if book:
            new_st = ikb._source_type_for(book)
            if fm.get("source_type") != new_st:
                fm["source_type"] = new_st
                changed = True

        if changed:
            conn.execute(
                "UPDATE learning_notes SET frontmatter=? WHERE id=?",
                (json.dumps(fm, ensure_ascii=False), row["id"]),
            )
            updated += 1
            if updated % 2000 == 0:
                print(f"  已更新 {updated} 条")
                conn.commit()

    conn.commit()
    print(f"完成: 更新 {updated} 条 frontmatter")

if __name__ == "__main__":
    main()
