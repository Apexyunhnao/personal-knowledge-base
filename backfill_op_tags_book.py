# -*- coding: utf-8 -*-
"""
backfill_op_tags_book.py — 按书名给卡补操作词标签（2026-08-28 通用版）
用法: python backfill_op_tags_book.py --book "投资最重要的事" --dry-run
      python backfill_op_tags_book.py --book "投资最重要的事"
逻辑: content 含操作词 → tags 补对应标签（按词匹配，不整批污染）
      更新 tags 后 FTS trigger 自动同步 notes_fts，再重建这批卡向量（tags 进向量）
"""
import sys, os, re, json, argparse
sys.path.insert(0, r"E:\Projects\rag-qa-project")
os.chdir(r"E:\Projects\rag-qa-project")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from db import get_conn
from hybrid_search import sync_note_embedding

# 操作词 → 标签。只给 content 含该词的卡加对应标签
OP_WORDS = {
    "恐慌抛售": "恐慌抛售",
    "恐慌": "恐慌抛售",
    "抛售": "恐慌抛售",
    "便宜货": "便宜货",
    "逆向投资": "逆向投资",
    "逆向": "逆向投资",
    "抄底": "抄底",
    "接飞刀": "接飞刀",
    "暴跌": "暴跌",
    "做空": "做空",
    "爆仓": "爆仓",
    "强平": "强平",
    "杠杆": "杠杆",
    "现金": "现金避险",
    "黄金": "黄金",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, content, tags FROM learning_notes WHERE deleted_at IS NULL AND tags LIKE ?",
        (f"%{args.book}%",),
    ).fetchall()

    total_added = 0
    touched_ids = []
    for row in rows:
        nid, title, content, tags = row[0], row[1], row[2] or "", row[3] or ""
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        added = []
        for word, label in OP_WORDS.items():
            if word in content and label not in tag_list:
                tag_list.append(label)
                added.append(label)
        if added:
            total_added += len(added)
            touched_ids.append(nid)
            if not args.dry_run:
                conn.execute(
                    "UPDATE learning_notes SET tags=? WHERE id=?",
                    (", ".join(tag_list), nid),
                )
                sync_note_embedding(nid, title, content, ", ".join(tag_list))
                print(f"  +{len(added)} tags: {title[:40]} <- {added}")

    if not args.dry_run:
        conn.commit()
    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}书「{args.book}」: {len(rows)} 卡, "
          f"{len(touched_ids)} 张补 {total_added} 个标签")


if __name__ == "__main__":
    main()
