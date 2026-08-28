# -*- coding: utf-8 -*-
"""
backfill_op_tags.py — 天涯金融实战卡操作词标签回填（v1.3.4）
目标：73-两次杠杆做空帖等金融卡，content 含操作词但 tags 没有 → 补操作词标签。
让 FTS5(tags字段)/向量(tags进向量)/标签路(query展开) 三路都能命中"做空怎么操作"这类 query。

用法: python backfill_op_tags.py --dry-run   # 只看统计
      python backfill_op_tags.py             # 执行（更新 tags + 重建向量）
"""
import sys, os, re, json, argparse
sys.path.insert(0, "/mnt/e/Projects/rag-qa-project")
os.chdir("/mnt/e/Projects/rag-qa-project")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from db import get_conn

# 操作词 → 标签。只给 content 含该词的卡加对应标签，避免污染无关卡
OP_WORDS = {
    "做空": "做空",
    "卖空": "做空",
    "杠杆": "杠杆",
    "爆仓": "爆仓",
    "强平": "强平",
    "强制平仓": "强平",
    "止损": "止损",
    "仓位": "仓位",
    "保证金": "保证金",
    "融资": "融资",
    "股灾": "股灾",
    "熊市": "熊市",
    "抄底": "抄底",
    "套牢": "套牢",
    "囤金": "囤金",
    "黄金": "黄金",
    "汇率": "汇率",
}

# 只处理这些天涯金融实战帖
TARGET_BOOKS = ["73-两次杠杆", "15-123个亏钱案例", "5-【经济专栏", "30岁后，我靠投资生活", "62-一个潜水多年"]


def find_target_ids(conn):
    ids = set()
    for book in TARGET_BOOKS:
        rows = conn.execute(
            "SELECT id FROM learning_notes WHERE frontmatter LIKE ? AND deleted_at IS NULL",
            (f"%{book}%",)
        ).fetchall()
        ids.update(r[0] for r in rows)
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只看统计不执行")
    args = ap.parse_args()

    conn = get_conn()
    target_ids = find_target_ids(conn)
    print(f"目标帖卡数: {len(target_ids)}")

    # 逐卡判断：content 含哪些操作词、缺哪些标签
    stats = {}          # 词 -> 补了多少张
    plan = []           # (id, 新标签追加串)
    for nid in sorted(target_ids):
        row = conn.execute(
            "SELECT title, content, tags FROM learning_notes WHERE id=?", (nid,)
        ).fetchone()
        if not row:
            continue
        content = row[1] or ""
        tags = row[2] or ""
        existing = set(t.strip() for t in tags.split(",") if t.strip())
        # 找 content 里命中的操作词
        to_add = []
        for word, label in OP_WORDS.items():
            if word in content and label not in existing:
                to_add.append(label)
        if to_add:
            # 去重保序
            seen = set()
            add = []
            for t in to_add:
                if t not in seen:
                    seen.add(t)
                    add.append(t)
            stats[len(add)] = stats.get(len(add), 0) + 1
            plan.append((nid, ",".join(add)))

    total_add = sum(len(p[1].split(",")) for p in plan)
    print(f"需补标签卡数: {len(plan)}/{len(target_ids)}，共补 {total_add} 个标签")
    print("\n按补标签数量分布:")
    for k in sorted(stats):
        print(f"  +{k}个标签: {stats[k]} 张")
    # 每张卡补了什么标签示例
    print("\n示例(前10张):")
    for nid, add in plan[:10]:
        print(f"  id={nid} +{add}")

    if args.dry_run:
        print("\n[dry-run] 不执行")
        return

    # ── 执行：更新 tags（FTS trigger 自动同步 notes_fts）──
    print("\n▶ 更新 tags...")
    for nid, add in plan:
        conn.execute(
            "UPDATE learning_notes SET tags = CASE WHEN tags='' OR tags IS NULL THEN ? ELSE tags || ', ' || ? END WHERE id=?",
            (add, add, nid)
        )
    conn.commit()
    print(f"已更新 {len(plan)} 张卡 tags")

    # ── 重建这批发卡的向量（tags 进向量）──
    print("▶ 重建向量...")
    from hybrid_search import sync_note_embedding
    ok = 0
    for nid, _ in plan:
        row = conn.execute(
            "SELECT title, content, tags FROM learning_notes WHERE id=?", (nid,)
        ).fetchone()
        if row:
            sync_note_embedding(nid, row[0] or "", row[1] or "", row[2] or "")
            ok += 1
    print(f"重建 {ok} 张卡向量")

    print("\n✅ 完成")


if __name__ == "__main__":
    main()
