# -*- coding: utf-8 -*-
"""
backfill_book_titles.py — 存量 book 卡标题回填（v1.3）
旧 prompt 生成的泛化标题（"先问原因再提建议"）→ 场景+方法标题（"同事抢功时先问原因再提建议"）

流程：
1. 从 SQLite 取所有 source_type=book 的卡（title + content + tags）
2. 并发调 DeepSeek 重写标题（≤25字，含场景+行动）
3. 更新 SQLite title（断点续跑：只处理标题长度<6 或调用失败重试的）
4. 抽样打印验证

用法: python backfill_book_titles.py [--limit N] [--dry-run]
"""
import argparse
import json
import os
import sys
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI

MODEL = "deepseek-chat"
TEMPERATURE = 0.3
MAX_TOKENS = 100
CONCURRENCY = 8
RETRY = 2

PROMPT = """你是卡片标题重写器。给定一张知识卡片（原标题+内容+场景标签），重写标题。

要求：
- 标题必须含「具体触发场景 + 行动」，如"同事抢功时先沉默后补位"、"领导画大饼时先要资源兑现时间表"
- ≤25字，反文学化，不用"如何/怎样"开头
- 保留原卡片的核心方法，只加场景前缀
- 禁止纯方法论抽象标题（如"先问原因再提建议"、"以关系和谐为决策锚点"）

只输出新标题，不要其他文字。"""


def rewrite_title(client, card):
    """调 DeepSeek 重写标题，返回 (note_id, new_title) 或 (note_id, None)"""
    title = card["title"]
    content = (card["content"] or "")[:200]
    tags = card["tags"] or ""
    for attempt in range(RETRY + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": f"原标题: {title}\n内容: {content}\n场景标签: {tags}"},
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
            new_title = resp.choices[0].message.content.strip().strip('"').strip()
            if new_title and len(new_title) <= 35:
                return (card["id"], new_title)
        except Exception as e:
            if attempt < RETRY:
                time.sleep(1)
    return (card["id"], None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前N张（测试用）")
    ap.add_argument("--dry-run", action="store_true", help="只生成标题不写库")
    args = ap.parse_args()

    from db import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, content, tags, frontmatter FROM learning_notes "
        "WHERE deleted_at IS NULL AND frontmatter LIKE '%\"source_type\": \"book\"%'"
    ).fetchall()
    cards = [dict(r) for r in rows]
    if args.limit:
        cards = cards[:args.limit]
    print(f"待回填 book 卡: {len(cards)} 张")

    # 断点续跑：已回填的（标题含场景词特征"时/后/前/中"且长度>=8）跳过
    todo = []
    for c in cards:
        t = c["title"] or ""
        if len(t) >= 8 and any(k in t for k in ("时", "后", "前", "中")):
            continue  # 已是场景化标题
        todo.append(c)
    print(f"需重写: {len(todo)} 张（{len(cards)-len(todo)} 张已是场景化）")

    if not todo:
        print("无需回填"); return

    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    results = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futures = {ex.submit(rewrite_title, client, c): c["id"] for c in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            nid, new_title = fut.result()
            if new_title:
                results[nid] = new_title
            if i % 100 == 0:
                print(f"  进度: {i}/{len(todo)} 已重写 {len(results)}")
    print(f"重写完成: {len(results)}/{len(todo)}，耗时 {time.time()-t0:.0f}s")

    # 抽样
    print("\n抽样（前10张）:")
    for c in todo[:10]:
        nid = c["id"]
        if nid in results:
            print(f"  [{c['title'][:20]}] → [{results[nid][:25]}]")
        else:
            print(f"  [{c['title'][:20]}] → ⚠️ 失败")

    if args.dry_run:
        print("\n[dry-run] 未写库"); return

    # 写库
    conn = get_conn()
    updated = 0
    for nid, new_title in results.items():
        conn.execute("UPDATE learning_notes SET title=? WHERE id=?", (new_title, nid))
        updated += 1
    conn.commit()
    print(f"\n已更新 SQLite: {updated} 张")

    # 写入待重建标记（向量需全量重建）
    with open("/tmp/book_title_backfill_done.json", "w", encoding="utf-8") as f:
        json.dump({"updated": updated, "at": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False)
    print("标记文件: /tmp/book_title_backfill_done.json → 下一步全量重建向量")


if __name__ == "__main__":
    main()
