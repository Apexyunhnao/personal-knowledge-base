# -*- coding: utf-8 -*-
"""
小说章节萃取管道 — 番茄小说txt → 方法论卡片 → 存入个人知识库(rag-qa)

用法:
  python extract_pipeline.py <txt路径> [--book 书名] [--dry-run]

流程:
  1. 读txt(自动检测utf-8/gbk) → 清洗(去空行/广告/章节标题)
  2. 按章节+语义段落分块(每块约800字, 最多15块)
  3. 每块调DeepSeek四步法萃取 → JSON卡片
  4. 汇总 → 写入 learning_notes → 同步向量库
"""
import argparse
import json
import os
import re
import sys
import time

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

# ── 配置 ──
MODEL = "deepseek-chat"          # 省钱: chat=flash, 质量不够再换 deepseek-v4-pro
MAX_CHUNKS = 15                  # 单次最多萃取的块数(防token爆炸)
CHUNK_TARGET = 800               # 目标块字数(中文)
TEMPERATURE = 0.3
MAX_TOKENS = 2000

BOOK_TAG = "小说萃取"            # 统一标签, 方便检索/清理
FAKE_FLAG = "虚构文本·作者观察非实践记录"

SYSTEM_PROMPT = """你是对话智慧萃取引擎。从小说/叙事文本中提取可迁移到现实场景的经验方法论。

严格按四步推理:
1. 困境定义: 这段对话解决什么两难问题? 约束条件是什么(信息差/资源短缺/时间压力)?
2. 方法拆解: 说话者具体做了哪几步破局? 归纳为通用流程(Step 1/2/3)。
3. 锚点识别: 决策时依据的隐性标准是什么?
4. 原理映射: 对应哪条底层规律?(可选, 只有明显对应才写, 禁止硬贴标签)

铁律:
- 反文学化: 严禁分析人物弧光、叙事节奏、修辞手法。只输出逻辑模型。
- 反常识化: 剔除"做人要诚实"这类公理, 只保留反直觉洞察或含具体操作步骤的内容。
- 普适化: 人名地名一律替换为角色标签(决策者/执行者/施压方/旁观者)。
- 原文锚点: 每个卡片必须带 source_ref(原文关键句), 禁止脑补原文没说的话。
- 来源标注: 这是虚构文本, 所有卡片 confidence 上限 0.7, 且必须标注为作者观察。

输出严格JSON(不要任何其他文字):
{
  "dilemma": "两难困境描述(去情节化)",
  "method_steps": ["步骤1", "步骤2", "步骤3"],
  "judgment_basis": "决策锚点",
  "core_principle": "底层规律名称(可为空字符串)",
  "cards": [
    {
      "node_type": "methodology | judgment | principle | pitfall",
      "title": "场景+方法标题(≤25字, 必须含具体触发场景+行动, 如: 同事抢功时先沉默后补位; 如: 领导画大饼时先要资源兑现时间表; 禁止纯方法论抽象标题如'先问原因再提建议')",
      "content": "去情节化的可执行描述(50-150字)",
      "scenario_tags": ["职场谈判", "家庭沟通"],
      "confidence": 0.6,
      "source_ref": "原文关键句"
    }
  ]
}
如果这段文本没有任何可迁移的方法论, cards 返回空数组 []。"""


# ── 文本读取与清洗 ──

def read_text(path: str) -> str:
    """读取txt, 自动检测编码"""
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法识别文件编码: {path}")


def clean_text(text: str) -> str:
    """清洗: 去空行/广告/多余空白"""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 常见网文广告行
        if re.search(r"(本章未完|请记住本站|加入书签|最新网址|免费阅读|QQ群|微信公众号|搜索.*关注|番茄小说|最新章节|手机用户请浏览)", line):
            continue
        lines.append(line)
    return "\n".join(lines)


# ── 分块 ──

CHAPTER_RE = re.compile(r"^(第[一二三四五六七八九十百千万0-9]+[章回节卷]|楔子|序章|番外|尾声)")


def split_chunks(text: str) -> list[dict]:
    """按章节 + 语义段落分块。返回 [{"chapter": "第X章...", "content": "..."}]"""
    lines = text.split("\n")
    chunks = []
    current_chapter = "正文"
    current_lines = []

    def flush():
        nonlocal current_lines
        if current_lines:
            chunks.append({"chapter": current_chapter, "content": "\n".join(current_lines)})
            current_lines = []

    for line in lines:
        if CHAPTER_RE.match(line):
            flush()
            current_chapter = line
            continue
        current_lines.append(line)

    flush()

    # 段落合并: 按空行语义边界, 目标 CHUNK_TARGET 字
    merged = []
    for ch in chunks:
        paras = [p for p in ch["content"].split("\n") if p.strip()]
        buf = ""
        for p in paras:
            if len(buf) + len(p) > CHUNK_TARGET and buf:
                merged.append({"chapter": ch["chapter"], "content": buf})
                buf = p
            else:
                buf = (buf + "\n" + p).strip()
        if buf:
            merged.append({"chapter": ch["chapter"], "content": buf})

    return merged


# ── DeepSeek 萃取 ──

def extract_block(client: OpenAI, block: dict, index: int, total: int) -> dict:
    """单块萃取, 返回 {"ok": bool, "data": dict|None, "raw": str}"""
    prompt = f"""以下是小说的一个片段(第{index}/{total}块), 请按系统要求萃取:

---BEGIN---
{block['content']}
---END---

请输出JSON。"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
        raw = resp.choices[0].message.content.strip()
        # 去掉可能的 ```json 包裹
        raw = re.sub(r"^```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
        data = json.loads(raw)
        return {"ok": True, "data": data, "raw": raw}
    except Exception as e:
        return {"ok": False, "data": None, "raw": str(e)}


# ── 写入知识库 ──

def save_to_kb(book: str, chapter: str, result: dict) -> int:
    """写入 learning_notes + 同步向量。返回 note_id"""
    from personal_db import _create
    from hybrid_search import sync_note_embedding

    dilemma = result.get("dilemma", "")
    steps = result.get("method_steps", [])
    basis = result.get("judgment_basis", "")
    principle = result.get("core_principle", "")
    cards = result.get("cards", [])

    # 组装 markdown 内容
    md = []
    md.append(f"> {FAKE_FLAG}\n")
    if dilemma:
        md.append(f"## 困境\n{dilemma}\n")
    if steps:
        md.append("## 方法\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)) + "\n")
    if basis:
        md.append(f"## 判断锚点\n{basis}\n")
    if principle:
        md.append(f"## 底层规律\n{principle}\n")
    if cards:
        md.append("## 卡片")
        for c in cards:
            nt = c.get("node_type", "methodology")
            conf = c.get("confidence", 0)
            tags = "、".join(c.get("scenario_tags", []))
            md.append(f"- [{nt}] {c.get('content', '')} (场景: {tags} | 置信度: {conf})")
            if c.get("source_ref"):
                md.append(f"  > 原文: {c['source_ref']}")
        md.append("")

    content = "\n".join(md)
    title = f"{book}·{chapter}" if chapter and chapter != "正文" else book

    # 标签: 书名 + 统一标记 + 场景标签
    tag_set = [BOOK_TAG]
    if book:
        tag_set.append(book)
    for c in cards:
        for t in c.get("scenario_tags", []):
            if t not in tag_set:
                tag_set.append(t)
    tags = ", ".join(tag_set)

    note_id = _create("notes", {
        "title": title,
        "topic": "其他",
        "tags": tags,
        "content": content,
        "source": book,
        "format": "markdown",
    })
    sync_note_embedding(note_id, title, content)
    return note_id


# ── 主流程 ──

def main():
    parser = argparse.ArgumentParser(description="小说章节萃取 → 存入rag-qa知识库")
    parser.add_argument("txt", help="txt文件路径")
    parser.add_argument("--book", default="", help="书名(默认取文件名)")
    parser.add_argument("--dry-run", action="store_true", help="只清洗分块, 不调API不写库")
    args = parser.parse_args()

    if not os.path.exists(args.txt):
        print(f"文件不存在: {args.txt}")
        sys.exit(1)

    book = args.book or os.path.splitext(os.path.basename(args.txt))[0]

    print(f"[1/4] 读取文件: {args.txt}")
    raw = read_text(args.txt)
    print(f"  原始 {len(raw)} 字符")

    print("[2/4] 清洗+分块")
    text = clean_text(raw)
    chunks = split_chunks(text)
    if not chunks:
        print("  错误: 清洗后没有内容")
        sys.exit(1)
    print(f"  {len(chunks)} 块")
    if len(chunks) > MAX_CHUNKS:
        print(f"  警告: {len(chunks)}块超过上限{MAX_CHUNKS}, 只处理前{MAX_CHUNKS}块")
        chunks = chunks[:MAX_CHUNKS]

    if args.dry_run:
        for i, c in enumerate(chunks, 1):
            print(f"\n--- 块{i} [{c['chapter']}] ({len(c['content'])}字) ---")
            print(c["content"][:300])
            if len(c["content"]) > 300:
                print("...(截断)")
        print(f"\n[dry-run] 共{len(chunks)}块, 未调用API")
        return

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("错误: 未找到 DEEPSEEK_API_KEY (.env)")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    print("[3/4] 逐块萃取 (DeepSeek)")
    all_cards = []
    merged_result = {"dilemma": "", "method_steps": [], "judgment_basis": "", "core_principle": "", "cards": []}
    failures = []

    for i, chunk in enumerate(chunks, 1):
        print(f"  块{i}/{len(chunks)} [{chunk['chapter']}] ...", flush=True)
        r = extract_block(client, chunk, i, len(chunks))
        if not r["ok"]:
            print(f"    失败: {r['raw'][:120]}")
            failures.append({"chapter": chunk["chapter"], "error": r["raw"]})
            time.sleep(1)
            continue
        data = r["data"]
        # 合并: 章节级困境/方法取第一块有内容的
        if not merged_result["dilemma"] and data.get("dilemma"):
            merged_result["dilemma"] = data["dilemma"]
        if not merged_result["method_steps"] and data.get("method_steps"):
            merged_result["method_steps"] = data["method_steps"]
        if not merged_result["judgment_basis"] and data.get("judgment_basis"):
            merged_result["judgment_basis"] = data["judgment_basis"]
        if not merged_result["core_principle"] and data.get("core_principle"):
            merged_result["core_principle"] = data["core_principle"]
        for c in data.get("cards", []):
            c["chapter"] = chunk["chapter"]
            all_cards.append(c)
        time.sleep(0.5)

    merged_result["cards"] = all_cards
    print(f"  共萃取 {len(all_cards)} 张卡片, 失败 {len(failures)} 块")

    if failures:
        print("  失败详情:")
        for f in failures:
            print(f"    {f['chapter']}: {f['error'][:80]}")

    if not all_cards:
        print("  没有萃取出任何卡片, 不写入")
        return

    print("[4/4] 写入知识库")
    note_id = save_to_kb(book, chunks[0]["chapter"], merged_result)
    print(f"  完成! note#{note_id} 已存入, 卡片 {len(all_cards)} 张")

    # 预览前3张
    print("\n预览:")
    for c in all_cards[:3]:
        print(f"  [{c.get('node_type')}] {c.get('content','')[:80]}")


if __name__ == "__main__":
    main()
