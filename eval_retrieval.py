# -*- coding: utf-8 -*-
"""
检索评估集 v1 — 建集 + LLM 判定 + 指标
用法: python eval_retrieval.py [--collect-only] [--judge-only]
  --collect-only  只跑检索落盘(不调 LLM)
  --judge-only    只做判定(读已有检索结果)
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from dotenv import load_dotenv
load_dotenv()

from hybrid_search import hybrid_search
from openai import OpenAI

EVAL_DIR = "evaluation"
COLLECT_FILE = os.path.join(EVAL_DIR, "retrieval_collected.json")
JUDGE_FILE = os.path.join(EVAL_DIR, "retrieval_judged.json")

# 27 个 query：覆盖场景TOP6(谈判/危机/投资/风险管理/商业谈判/领导力) + 边界
QUERIES = [
    # 谈判类
    "谈判 合同 陷阱",
    "谈判 筹码 主动权",
    "谈判 底线 原则",
    "谈判 让步 交换",
    "谈判 破裂 挽回",
    # 危机类
    "危机 决策 冷静",
    "危机 现金流 生存",
    "危机 沟通 信任",
    "危机 银行 挤兑",
    # 投资决策类
    "投资 止损 割肉",
    "投资 抄底 时机",
    "资金 杠杆 风险",
    "市场 恐慌 机会",
    # 风险管理类
    "风险管理 仓位 建仓",
    "爆仓 风险控制",
    "债务 危机 处理",
    # 商业/博弈类
    "商业 博弈 对手 心理",
    "信息不对称 决策",
    "权力 站队 博弈",
    # 领导力/管理类
    "领导力 团队 管理",
    "压力 决策 时间",
    "情绪 控制 交易",
    # 通用决策类
    "决策 信息 收集",
    "复盘 自我审计",
    # 边界/负面（预期低相关）
    "玄幻 修仙 功法",
    "恋爱 感情 分手",
    "美食 菜谱 做饭",
]

def collect():
    os.makedirs(EVAL_DIR, exist_ok=True)
    data = []
    for i, q in enumerate(QUERIES, 1):
        t0 = time.time()
        try:
            results = hybrid_search(q, top_k=10)
            items = [{
                "id": r["id"],
                "title": r["title"],
                "score": r["score"],
                "source": r["source"],
                "is_low_confidence": r["is_low_confidence"],
                "tags": r["tags"],
            } for r in results]
        except Exception as e:
            items = [{"error": str(e)}]
        data.append({"query": q, "results": items})
        print(f"[{i}/{len(QUERIES)}] {q} -> {len(items)} 条 ({time.time()-t0:.1f}s)")
        time.sleep(0.1)
    with open(COLLECT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"落盘: {COLLECT_FILE}")

def judge():
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY 未设置"); sys.exit(1)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    with open(COLLECT_FILE, encoding="utf-8") as f:
        data = json.load(f)

    # 为每条结果补充 content 摘要(判定依据)
    import sqlite3
    conn = sqlite3.connect("personal.db")
    conn.row_factory = sqlite3.Row
    for item in data:
        for r in item["results"]:
            if "error" in r:
                continue
            row = conn.execute(
                "SELECT content FROM learning_notes WHERE id=?", (r["id"],)
            ).fetchone()
            r["content_excerpt"] = (row["content"] or "")[:120] if row else ""

    SYSTEM = """你是检索质量评估器。给定一个查询和知识库返回的结果列表，逐条判断相关性：
- relevant: 内容直接回答查询主题，强相关
- partial: 沾边但未完全命中，或只覆盖查询的一个方面
- irrelevant: 与查询无关
只输出 JSON 数组，格式 [{"id": 数字, "label": "relevant|partial|irrelevant"}]
严格按输入 id 逐条输出，数量必须一致，不要加解释。"""

    judged = []
    for i, item in enumerate(data, 1):
        q = item["query"]
        lines = []
        for r in item["results"]:
            if "error" in r:
                lines.append(f"- id:{r['id']} (error)")
                continue
            lines.append(f"- id:{r['id']} | 标题: {r['title'][:60]} | 内容: {r.get('content_excerpt','')}")
        user = f"查询: {q}\n结果:\n" + "\n".join(lines)

        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    temperature=0,
                    max_tokens=500,
                )
                raw = resp.choices[0].message.content.strip()
                # 提取 JSON 数组
                start = raw.find("[")
                end = raw.rfind("]") + 1
                labels = json.loads(raw[start:end]) if start >= 0 and end > start else []
                break
            except Exception as e:
                print(f"  判定失败(重试{attempt+1}): {e}")
                labels = []
                time.sleep(2)

        id2label = {l["id"]: l["label"] for l in labels if isinstance(l, dict)}
        for r in item["results"]:
            if "error" not in r:
                r["label"] = id2label.get(r["id"], "unknown")
        judged.append({"query": q, "results": item["results"]})
        n_rel = sum(1 for r in item["results"] if r.get("label") == "relevant")
        print(f"[{i}/{len(data)}] {q} -> relevant {n_rel}/{[len(x['results']) for x in data if x['query']==q][0]}")
        time.sleep(0.3)

    with open(JUDGE_FILE, "w", encoding="utf-8") as f:
        json.dump(judged, f, ensure_ascii=False, indent=1)

    # ── 指标 ──
    print("\n=== 指标 ===")
    total_rel = total_partial = total_irrel = total_all = 0
    p5s, p10s = [], []
    for item in judged:
        rs = item["results"]
        rs = [r for r in rs if "error" not in r]
        if not rs:
            continue
        rel = sum(1 for r in rs if r["label"] == "relevant")
        part = sum(1 for r in rs if r["label"] == "partial")
        irr = sum(1 for r in rs if r["label"] == "irrelevant")
        total_all += len(rs); total_rel += rel; total_partial += part; total_irrel += irr
        if len(rs) >= 5:
            p5 = sum(1 for r in rs[:5] if r["label"] == "relevant") / 5
            p5s.append(p5)
        if len(rs) >= 10:
            p10 = sum(1 for r in rs[:10] if r["label"] == "relevant") / 10
            p10s.append(p10)
    n = len(judged)
    print(f"query 数: {n}")
    print(f"总条数: {total_all}  相关: {total_rel} ({total_rel/total_all*100:.1f}%)  "
          f"部分: {total_partial} ({total_partial/total_all*100:.1f}%)  "
          f"不相关: {total_irrel} ({total_irrel/total_all*100:.1f}%)")
    print(f"Precision@5: {sum(p5s)/len(p5s)*100:.1f}%  (n={len(p5s)})")
    print(f"Precision@10: {sum(p10s)/len(p10s)*100:.1f}%  (n={len(p10s)})")
    # 边界query单独看
    print("\n=== 边界query(预期低相关) ===")
    for item in judged:
        if item["query"] in ("玄幻 修仙 功法", "恋爱 感情 分手", "美食 菜谱 做饭"):
            rs = [r for r in item["results"] if "error" not in r]
            rel = sum(1 for r in rs if r["label"] == "relevant")
            print(f"  {item['query']}: relevant {rel}/{len(rs)}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect-only", action="store_true")
    ap.add_argument("--judge-only", action="store_true")
    args = ap.parse_args()
    if args.judge_only:
        judge()
    elif args.collect_only:
        collect()
    else:
        collect()
        judge()
