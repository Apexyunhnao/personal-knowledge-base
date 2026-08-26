#!/usr/bin/env python3
"""天涯神贴预处理 v2：精选 md → inputs/天涯神贴精选/ 多个 txt
分块策略：纯 800 字语义切分（不依赖 ### 标题，因为标题碎片太多）
每文件 ≤15 块，文件名带序号
"""
import os, re, sys

SRC = "/mnt/e/Projects/rag-qa-project/tmp_tianya/tianya-main"
DST = "/mnt/e/Projects/rag-qa-project/inputs/天涯神贴精选"

SELECTED = [
    "44-社会不教，精英不讲，坎儿还得自己过（揭秘人才成长规律）.md",
    "133-办公室实用暴力美学——用《资治通鉴》的智慧打造职场金饭碗.md",
    "15-123个亏钱案例（第一版）.md",
    "73-两次杠杆做到5000万股灾被强平的投机之路-南侠1987.md",
    "62-一个潜水多年的体制内的生意人来实际谈谈老百姓该怎么办？.md",
    "82-人，应该怎么活？应该怎么赚钱？.md",
    "5-【经济专栏】赚未来十年的钱【已出版】.md",
    "30岁后，我靠投资生活全2册.md",
]

CHUNK_TARGET = 800
MAX_CHUNKS_PER_FILE = 15

# 无意义碎片标题（回帖标记等）
JUNK_TITLE = re.compile(r"^(——|（\d+）|up|评|可循|归自己|全程管理|低级错误|等待具体的东西|$)")
CHAPTER_TITLE = re.compile(r"^[一二三四五六七八九十]+[、.．]")

def clean_line(s):
    s = re.sub(r"[\u200b-\u200d\ufeff\u2060]", "", s)
    if s.startswith("> 来源:"):
        return None
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = s.strip()
    return s or None

def split_chunks(lines):
    """按 800 字语义切分，返回块列表（每块 content 是文本）"""
    # 先按真正章节标题粗切（中文数字+、）
    sections = []
    cur = []
    cur_title = None
    for line in lines:
        if CHAPTER_TITLE.match(line):
            if cur:
                sections.append((cur_title, "\n".join(cur)))
            cur_title = line
            cur = [line]
        else:
            cur.append(line)
    if cur:
        sections.append((cur_title, "\n".join(cur)))

    # 再按 800 字细切
    chunks = []
    for title, content in sections:
        # 按段落切
        paras = content.split("\n")
        buf = ""
        for p in paras:
            if len(buf) + len(p) > CHUNK_TARGET and buf:
                chunks.append({"title": title, "content": buf})
                buf = p
            else:
                buf = (buf + "\n" + p).strip()
        if buf:
            chunks.append({"title": title, "content": buf})
    return chunks

def main():
    os.makedirs(DST, exist_ok=True)
    total_files = 0
    for fn in SELECTED:
        fpath = os.path.join(SRC, fn)
        if not os.path.exists(fpath):
            print(f"⚠️ 缺失: {fn}")
            continue
        raw = open(fpath, encoding="utf-8").read()
        # 清洗成行
        lines = []
        for line in raw.split("\n"):
            s = clean_line(line)
            if s:
                # 剥掉 ### 符号但保留正文（### 碎片标题直接丢弃）
                if re.match(r"^#{1,3}\s+", s):
                    body = re.sub(r"^#{1,3}\s+", "", s).strip()
                    if body and not JUNK_TITLE.match(body):
                        lines.append(body)
                    continue
                lines.append(s)

        chunks = split_chunks(lines)
        if not chunks:
            print(f"  ⚠️ {fn}: 无内容")
            continue

        base = re.sub(r"\.md$", "", fn)
        base = re.sub(r'[<>:"/\\|?*]', "_", base)[:40]
        groups = [chunks[i:i+MAX_CHUNKS_PER_FILE] for i in range(0, len(chunks), MAX_CHUNKS_PER_FILE)]
        for gi, group in enumerate(groups, 1):
            body = "\n\n".join(c["content"] for c in group)
            first_title = next((c["title"] for c in group if c["title"]), base)
            out_fn = f"{base}_p{gi:02d}.txt"
            with open(os.path.join(DST, out_fn), "w", encoding="utf-8") as f:
                f.write(f"# {first_title}\n\n{body}")
            total_files += 1
        print(f"  {base}: {len(chunks)}块 → {len(groups)}个文件")
    print(f"\n完成: {total_files} 个文件 → {DST}")

if __name__ == "__main__":
    main()
