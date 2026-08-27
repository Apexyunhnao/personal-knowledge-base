# -*- coding: utf-8 -*-
"""
对抗性评估集 v1 — 三 AI（DeepSeek 20条/豆包 15条/千问 15条）合并去重后 26 条
用法: python eval_adversarial.py [--collect-only] [--judge-only]
  --collect-only  只跑检索落盘(不调 LLM)
  --judge-only    只做判定(读已有检索结果)
验收决策树（DeepSeek 版）: ≥75% 完胜 / 60-74% 需配额保底 / <60% 改 novel 权重
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
COLLECT_FILE = os.path.join(EVAL_DIR, "adversarial_collected.json")
JUDGE_FILE = os.path.join(EVAL_DIR, "adversarial_judged.json")

# (query, 板块) — 合并三份 AI 对抗集，去重保留覆盖最全
QUERIES = [
    # 投资/金融心态
    ("炒股一直亏，晚上睡不着觉，要不要彻底清仓认输？", "投资心态"),
    ("基金跌了30%，越补仓跌得越多，现在该不该割肉？", "投资心态"),
    ("看到别人牛市赚钱，自己一进去就被套，怎么克服这种赌徒心理？", "投资心态"),
    ("做短线总是追涨杀跌，管不住手，有什么办法强制止损？", "投资心态"),
    ("投资亏了钱不想认赔，总觉得会涨回来，怎么克服这种心态？", "投资心态"),
    ("加杠杆炒股真的能赚更多吗？", "投资心态"),
    # 职场/职业焦虑
    ("民办本科投了100份简历没人理，是不是这辈子就这样了？", "职场焦虑"),
    ("现在的工作学不到东西，想跳槽又怕空窗期，怎么破局？", "职场焦虑"),
    ("领导PUA打压我，天天让我打杂，该忍还是该撕破脸走人？", "职场焦虑"),
    ("35岁被裁员，投递简历全被已读不回，还能干点什么？", "职场焦虑"),
    ("经济不好，普通人怎么保住自己的工作？", "职场焦虑"),
    # 沟通/人际博弈
    ("跟同事合作项目，他划水摸鱼，最后汇报全抢我功劳，怎么办？", "人际博弈"),
    ("面试官问'你为什么从上家公司离职'，怎么回答既真实又不得罪人？", "人际博弈"),
    ("跟老板提涨薪被画大饼，下次怎么谈才能让他没法拒绝？", "人际博弈"),
    ("朋友老是找我借钱，不想伤感情又想拒绝，话术怎么搞？", "人际博弈"),
    # 人生规划/模糊迷茫
    ("都快30岁了，要房没房要车没车，感觉人生好失败，怎么调整？", "人生规划"),
    ("每天上班像上坟，提不起劲，怎么找回工作的动力？", "人生规划"),
    ("想转行做AI产品经理，但零基础，不知道怎么迈出第一步。", "人生规划"),
    ("30岁了还没明确的职业方向，晚不晚？", "人生规划"),
    # 执行力/自我管理
    ("定好的计划总是坚持不过三天，是不是我意志力太差了？", "执行力"),
    ("工作堆成山，不知道先干哪个，每天加班还挨骂，怎么安排优先级？", "执行力"),
    ("看了很多书，当时觉得很对，过两天全忘光了，怎么变成自己的？", "执行力"),
    ("遇到一点挫折就想放弃，怎么让自己变得皮实一点？", "执行力"),
    # 认知/鉴别
    ("怎么判断一个人说的话靠不靠谱？", "认知鉴别"),
    ("为什么越是老实人越容易被欺负？", "认知鉴别"),
    ("老板画大饼怎么办？怎么判断公司是在真发展还是忽悠？", "认知鉴别"),
]


def collect():
    os.makedirs(EVAL_DIR, exist_ok=True)
    data = []
    for i, (q, cat) in enumerate(QUERIES, 1):
        t0 = time.time()
        try:
            results = hybrid_search(q, top_k=10, include_low_confidence=True)
            items = [{
                "id": r["id"],
                "title": r["title"],
                "score": r["score"],
                "source": r["source"],
                "source_type": r.get("source_type", ""),
                "confidence": r.get("confidence", 0),
                "is_low_confidence": r["is_low_confidence"],
                "tags": r["tags"],
            } for r in results]
        except Exception as e:
            items = [{"error": str(e)}]
        data.append({"query": q, "category": cat, "results": items})
        print(f"[{i}/{len(QUERIES)}] {q[:28]} -> {len(items)} 条 ({time.time()-t0:.1f}s)")
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

    SYSTEM = "你是检索质量评估器。给定一个查询和知识库返回的结果列表，逐条判断相关性：\n- relevant: 内容直接回答查询主题，强相关\n- partial: 沾边但未完全命中，或只覆盖查询的一个方面\n- irrelevant: 与查询无关\n只输出 JSON 数组，格式 [{\"id\": 数字, \"label\": \"relevant|partial|irrelevant\"}]\n严格按输入 id 逐条输出，数量必须一致，不要加解释。"

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

        labels = []
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
        judged.append({"query": q, "category": item["category"], "results": item["results"]})
        n_rel = sum(1 for r in item["results"] if r.get("label") == "relevant")
        print(f"[{i}/{len(data)}] {q[:28]} -> relevant {n_rel}/10")
        time.sleep(0.3)

    with open(JUDGE_FILE, "w", encoding="utf-8") as f:
        json.dump(judged, f, ensure_ascii=False, indent=1)

    # ── 指标 ──
    print("\n=== 对抗集指标 ===")
    total_rel = total_partial = total_irrel = total_all = 0
    p5s, p10s = [], []
    by_cat = {}
    for item in judged:
        rs = [r for r in item["results"] if "error" not in r]
        if not rs:
            continue
        rel = sum(1 for r in rs if r["label"] == "relevant")
        part = sum(1 for r in rs if r["label"] == "partial")
        irr = sum(1 for r in rs if r["label"] == "irrelevant")
        total_all += len(rs); total_rel += rel; total_partial += part; total_irrel += irr
        if len(rs) >= 5:
            p5s.append(sum(1 for r in rs[:5] if r["label"] == "relevant") / 5)
        if len(rs) >= 10:
            p10s.append(sum(1 for r in rs[:10] if r["label"] == "relevant") / 10)
        cat = item["category"]
        by_cat.setdefault(cat, {"rel": 0, "part": 0, "total": 0})
        by_cat[cat]["rel"] += rel; by_cat[cat]["part"] += part; by_cat[cat]["total"] += len(rs)

    n = len(judged)
    print(f"query 数: {n}")
    rp = total_rel + total_partial
    print(f"总条数: {total_all}  相关: {total_rel} ({total_rel/total_all*100:.1f}%)  "
          f"部分: {total_partial} ({total_partial/total_all*100:.1f}%)  "
          f"不相关: {total_irrel} ({total_irrel/total_all*100:.1f}%)")
    print(f"**对抗集召回率(相关+部分): {rp/total_all*100:.1f}%**")
    print(f"Precision@5: {sum(p5s)/len(p5s)*100:.1f}%  (n={len(p5s)})")
    print(f"Precision@10: {sum(p10s)/len(p10s)*100:.1f}%  (n={len(p10s)})")
    print("\n=== 按板块 ===")
    for cat, v in by_cat.items():
        rp_cat = v["rel"] + v["part"]
        print(f"  {cat}: {rp_cat}/{v['total']} ({rp_cat/v['total']*100:.1f}%)  rel={v['rel']} part={v['part']}")


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
