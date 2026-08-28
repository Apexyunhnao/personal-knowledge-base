# -*- coding: utf-8 -*-
"""QA 答案卡直接入库（绕过 import 幂等，因为 QA 文件无对应 txt，hash 恒空会重入）
用法: python import_qa_cards.py <qa_json_path> <book_name>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from import_to_kb import build_note_data, _source_type_for
from personal_db import _create
from hybrid_search import sync_note_embedding


def main():
    qa_path = sys.argv[1]
    book = sys.argv[2]
    with open(qa_path, encoding="utf-8") as f:
        d = json.load(f)
    cards = d.get("result", {}).get("cards", [])
    print(f"QA 卡数: {len(cards)}")
    created = 0
    for card in cards:
        # 幂等: 按 title 查重（QA 卡 title 唯一）
        import sqlite3
        conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "personal.db"))
        dup = conn.execute(
            "SELECT id FROM learning_notes WHERE deleted_at IS NULL AND source LIKE ? AND title=?",
            (f"%{book}%", card.get("title", "")),
        ).fetchone()
        conn.close()
        if dup:
            print(f"  跳过(已存在): {card.get('title','')[:30]}")
            continue
        data = build_note_data(card, book, "QA卡", card.get("source_ref", ""), "")
        data["source"] = f"《{book}》QA手写卡"
        note_id = _create("notes", data)
        sync_note_embedding(note_id, data.get("title", ""), data.get("content", ""), data.get("tags", ""))
        created += 1
        print(f"  新建: {card.get('title','')[:40]}")
    print(f"完成: 新建 {created}")


if __name__ == "__main__":
    main()
