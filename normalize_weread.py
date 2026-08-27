#!/usr/bin/env python3
"""归一化：weread 导出的 md → 萃取管线 inputs/<书名>/ 的 txt
- 章节序号+标题 → 0001_章节名.txt
- 去掉 # 标题行、空行压缩、清理残留 md 符号
"""
import os, re, sys, unicodedata, argparse

ap = argparse.ArgumentParser()
ap.add_argument("src", nargs="?", default="/mnt/e/Projects/rag-qa-project/tmp_weread_exporter/weread-exporter-main/output/81232dc0719502df812cbba/chapters")
ap.add_argument("book", nargs="?", default="打破你的学生思维")
args = ap.parse_args()

SRC = args.src
BOOK = args.book
DST = f"/mnt/e/Projects/rag-qa-project/inputs/{BOOK}"

def clean_text(text):
    """清洗：去 md 标记、零宽字符、压缩空白"""
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 去掉零宽字符（\u200b-\u200d \ufeff）
        line = re.sub(r"[\u200b-\u200d\ufeff\u2060]", "", line)
        # 去掉 md 标题行（## 等）
        if re.match(r"^#{1,6}\s", line):
            line = re.sub(r"^#{1,6}\s+", "", line)
        # 去图片语法 ![](...)
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        lines.append(line)
    return "\n".join(lines)

def main():
    os.makedirs(DST, exist_ok=True)
    files = sorted(f for f in os.listdir(SRC) if f.endswith(".md"))
    total_chars = 0
    for i, fn in enumerate(files, 1):
        with open(os.path.join(SRC, fn), encoding="utf-8") as f:
            raw = f.read()
        # 第一行是 # 标题
        title_line = raw.split("\n", 1)[0]
        title = re.sub(r"^#\s*", "", title_line).strip()
        # 清洗
        body = clean_text(raw)
        # 去掉标题行本身（clean 后标题会重复出现在正文里，删第一处）
        body_lines = body.split("\n")
        if body_lines and body_lines[0] == title:
            body_lines = body_lines[1:]
        body = "\n".join(body_lines)
        # 章节标题清理文件名非法字符
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", title)
        out_fn = f"{i:04d}_{safe_title}.txt"
        with open(os.path.join(DST, out_fn), "w", encoding="utf-8") as f:
            f.write(body)
        total_chars += len(body)
        if i <= 3 or i == len(files):
            print(f"  {out_fn}: {len(body)}字")
    print(f"\n完成: {len(files)} 章 → {DST}")
    print(f"总字数: {total_chars}")

if __name__ == "__main__":
    main()
