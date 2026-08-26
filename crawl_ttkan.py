# -*- coding: utf-8 -*-
"""
ttkan 全量爬虫 — 拉取《从做空次贷危机开始收割世界》全部章节正文

用法:
  python crawl_ttkan.py            # 全量拉取到 inputs/<书名>/
  python crawl_ttkan.py --dry      # 只列章节清单不下载
"""
import argparse
import os
import re
import sys
import time

import requests

BASE = "https://cn.ttkan.co/novel/pagea/baocangwuqianwanwofanshouzuokonghuaerjiecongzuokongcidaiweijikaishishougeshijie-pipazhedao"
BOOK = "从做空次贷危机开始收割世界"
OUT_DIR = os.path.join(os.path.dirname(__file__), "inputs", BOOK)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://cn.ttkan.co/",
}

CHAPTER_LINK_RE = re.compile(
    r'href="(/novel/pagea/[^"]*pipazhedao_(\d+)\.html)"[^>]*>([^<]{2,60})<')
TITLE_RE = re.compile(r'<div class="title"><h1>(.*?)</h1></div>')
CONTENT_RE = re.compile(r'<div class="content">(.*?)</div>\s*<div', re.S)


def get(url: str, retries: int = 3) -> str:
    """GET + 重试"""
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.text
            print(f"  状态码{r.status_code}: {url}")
        except Exception as e:
            print(f"  第{i+1}次失败: {e}")
        time.sleep(2)
    return ""


def fetch_catalog() -> list[dict]:
    """抓目录页, 返回 [{url, idx, title}], 去重。
    循环抓取 _0/_1/_2/... 直到空页或连续2页无新章节（书可能超300章，写死3页会漏）"""
    seen = {}
    empty_pages = 0
    for page in range(10):  # 上限10页（每页约100章，防死循环）
        html = get(f"{BASE}_{page}.html")
        if not html:
            print(f"  目录页{page}获取失败")
            break
        found = 0
        for m in CHAPTER_LINK_RE.finditer(html):
            url, idx, title = m.group(1), int(m.group(2)), m.group(3).strip()
            if "繁體" in title:
                continue
            # 清洗标题装饰符号(网站可能在章节名加 ◈ 等), 防文件名/幂等键漂移
            title = re.sub(r"[◈◆■□●○]\s*", "", title).strip()
            if idx not in seen:
                seen[idx] = {"url": url, "idx": idx, "title": title}
                found += 1
        if found == 0:
            empty_pages += 1
            if empty_pages >= 2:  # 连续2页无新章节 → 目录到底了
                break
        else:
            empty_pages = 0
        time.sleep(0.3)
    chapters = sorted(seen.values(), key=lambda c: c["idx"])
    print(f"目录: 共{len(chapters)}章")
    return chapters


def fetch_chapter(url: str) -> tuple[str, str]:
    """抓单章正文, 返回 (标题, 正文)"""
    html = get("https://cn.ttkan.co" + url)
    if not html:
        return "", ""
    tm = TITLE_RE.search(html)
    title = tm.group(1).strip() if tm else "未知章节"
    cm = CONTENT_RE.search(html)
    if not cm:
        return title, ""
    # 提取所有 <p> 内容
    paras = re.findall(r'<p>(.*?)</p>', cm.group(1), re.S)
    text = []
    for p in paras:
        t = re.sub(r'<[^>]+>', '', p)
        t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
        t = t.strip()
        if t:
            text.append(t)
    return title, "\n".join(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    chapters = fetch_catalog()
    if args.dry:
        for c in chapters[:10]:
            print(f"  {c['idx']}: {c['title']}")
        print(f"  ...共{len(chapters)}章")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    ok = 0
    failed = []
    for i, c in enumerate(chapters, 1):
        fname = f"{c['idx']:04d}_{c['title']}.txt"
        fpath = os.path.join(OUT_DIR, fname)
        if os.path.exists(fpath) and os.path.getsize(fpath) > 100:
            ok += 1
            continue
        title, text = fetch_chapter(c["url"])
        if not text:
            failed.append(c["idx"])
            print(f"[{i}/{len(chapters)}] 失败 #{c['idx']} {c['title']}")
            continue
        # 清洗标题装饰符号(网站可能在章节名加 ◈ 等), 避免文件名/幂等键漂移
        title = re.sub(r"[◈◆■□●○]\s*", "", title).strip()
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"{title}\n\n{text}")
        ok += 1
        if i % 20 == 0 or i == len(chapters):
            print(f"[{i}/{len(chapters)}] 成功{ok} 失败{len(failed)}")
        time.sleep(0.3)

    print(f"\n完成: 成功{ok}章 失败{len(failed)}章")
    if failed:
        print(f"失败章节: {failed}")
    print(f"输出目录: {OUT_DIR}")


if __name__ == "__main__":
    main()
