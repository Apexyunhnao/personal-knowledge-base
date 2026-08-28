# -*- coding: utf-8 -*-
"""
批量萃取 — 遍历 inputs/<书>/ 下所有章节txt, 逐章萃取, 结果落盘 outputs/<书>/

用法:
  python batch_extract.py [--limit N] [--skip N]   # 只处理前N章 / 跳过前N章
  python batch_extract.py --all                     # 全部
"""
import argparse
import json
import os
import sys
import time

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_pipeline as ep

# 2026-08-27: 三本微信读书实体书轮换萃取（18:00 后半价）：
#   1. 别人不说，你一定要懂的人情世故（37章）✅ 完成 186卡
#   2. 人性的弱点（40章）✅ 完成 166卡
#   3. 这就是人性（85章）← 当前
# 每次换书改这一行即可（outputs/ 按书名隔离）
BOOK = "自控力"
INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inputs", BOOK)
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", BOOK)

SLEEP_BETWEEN = 0.3  # 块间限速


def extract_chapter(client, title: str, text: str) -> dict:
    """单章萃取, 返回合并结果"""
    clean = ep.clean_text(text)
    chunks = ep.split_chunks(clean)
    merged = {"dilemma": "", "method_steps": [], "judgment_basis": "", "core_principle": "", "cards": [], "chapters": []}
    failures = 0
    for i, chunk in enumerate(chunks, 1):
        r = ep.extract_block(client, chunk, i, len(chunks))
        if not r["ok"]:
            failures += 1
            continue
        data = r["data"]
        if not merged["dilemma"] and data.get("dilemma"):
            merged["dilemma"] = data["dilemma"]
        if not merged["method_steps"] and data.get("method_steps"):
            merged["method_steps"] = data["method_steps"]
        if not merged["judgment_basis"] and data.get("judgment_basis"):
            merged["judgment_basis"] = data["judgment_basis"]
        if not merged["core_principle"] and data.get("core_principle"):
            merged["core_principle"] = data["core_principle"]
        for c in data.get("cards", []):
            c["chapter"] = chunk["chapter"]
            merged["cards"].append(c)
        time.sleep(SLEEP_BETWEEN)
    merged["_failures"] = failures
    return merged


def save_result(fname_base: str, title: str, result: dict):
    """落盘 JSON + markdown"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(OUTPUT_DIR, fname_base + ".json")
    md_path = os.path.join(OUTPUT_DIR, fname_base + ".md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"title": title, "result": result}, f, ensure_ascii=False, indent=2)

    md = [f"# {title}", f"> 虚构文本·作者观察非实践记录", ""]
    if result.get("dilemma"):
        md += ["## 困境", result["dilemma"], ""]
    if result.get("method_steps"):
        md += ["## 方法"] + [f"{i+1}. {s}" for i, s in enumerate(result["method_steps"])] + [""]
    if result.get("judgment_basis"):
        md += ["## 判断锚点", result["judgment_basis"], ""]
    if result.get("core_principle"):
        md += ["## 底层规律", result["core_principle"], ""]
    md += ["## 卡片", ""]
    for c in result.get("cards", []):
        md.append(f"- [{c.get('node_type','')}] {c.get('content','')} "
                  f"(场景:{'、'.join(c.get('scenario_tags',[]))} 置信度:{c.get('confidence',0)})")
        if c.get("source_ref"):
            md.append(f"  > 原文: {c['source_ref']}")
    md.append("")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="处理全部")
    parser.add_argument("--limit", type=int, default=0, help="只处理前N章")
    parser.add_argument("--skip", type=int, default=0, help="跳过前N章")
    args = parser.parse_args()

    if not os.path.isdir(INPUT_DIR):
        print(f"输入目录不存在: {INPUT_DIR}")
        sys.exit(1)

    files = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith(".txt"))
    print(f"找到 {len(files)} 章")

    # 跳过已处理的
    done = set(os.path.splitext(f)[0] for f in os.listdir(OUTPUT_DIR)) if os.path.isdir(OUTPUT_DIR) else set()
    todo = [f for f in files if os.path.splitext(f)[0] not in done]
    print(f"未处理: {len(todo)} 章")

    if not args.all:
        if args.skip:
            todo = todo[args.skip:]
        if args.limit:
            todo = todo[:args.limit]
    print(f"本次处理: {len(todo)} 章")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("错误: 未找到 DEEPSEEK_API_KEY")
        sys.exit(1)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    total_cards = 0
    fail_list = []
    for i, fname in enumerate(todo, 1):
        fpath = os.path.join(INPUT_DIR, fname)
        try:
            raw = ep.read_text(fpath)
        except Exception as e:
            print(f"[{i}/{len(todo)}] 读取失败 {fname}: {e}")
            fail_list.append(fname)
            continue
        title = raw.split("\n", 1)[0].strip()
        # 清洗标题装饰符号(网站可能在章节名加 ◈ 等), 避免 outputs 文件名/入库幂等键漂移
        import re
        title = re.sub(r"[◈◆■□●○]\s*", "", title).strip()
        result = extract_chapter(client, title, raw)
        n = len(result["cards"])
        total_cards += n
        base = os.path.splitext(fname)[0]
        save_result(base, title, result)
        flag = f"失败{result['_failures']}块" if result["_failures"] else "OK"
        print(f"[{i}/{len(todo)}] {base} 卡片{n} {flag}")
        time.sleep(0.5)

    print(f"\n完成: {len(todo)-len(fail_list)}/{len(todo)} 章, 共{total_cards}张卡片, 失败{len(fail_list)}")
    if fail_list:
        print("失败:", fail_list)
    print(f"输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
