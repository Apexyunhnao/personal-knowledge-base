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


def collect_file(ver: str) -> str:
    return os.path.join(EVAL_DIR, f"adversarial_collected_v{ver}.json")


def judge_file(ver: str) -> str:
    return os.path.join(EVAL_DIR, f"adversarial_judged_v{ver}.json")


def report_file(ver: str) -> str:
    return os.path.join(EVAL_DIR, f"report_v{ver}.md")

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
    # ===== v1.3 扩容（2026-08-27，26→53）：羔丸手写场景 query，口语化不预查库 =====
    # 投资/金融心态 +2
    ("身边人都说牛市来了，我该不该把存款全投进去？", "投资心态"),
    ("中概股跌成这样，是抄底机会还是接飞刀？", "投资心态"),
    # 职场/职业焦虑 +3
    ("被公司边缘化了，工位挪到角落，是不是该主动辞职？", "职场焦虑"),
    ("应届生第一份工作，进小公司好还是大厂外包好？", "职场焦虑"),
    ("领导让我背锅，出了事要我写检讨，怎么自保？", "职场焦虑"),
    # 沟通/人际博弈 +3
    ("过年回家亲戚总问我工资和对象，怎么不伤和气地岔开？", "人际博弈"),
    ("同事总让我帮他干活，拒绝又怕得罪人，怎么办？", "人际博弈"),
    ("女朋友生气的时候讲道理有用吗？怎么哄才对？", "人际博弈"),
    # 人生规划/模糊迷茫 +3
    ("每天下班就躺平刷手机，想改变又动不起来，是不是废了？", "人生规划"),
    ("考公还是考研还是直接工作，三选一怎么选？", "人生规划"),
    ("一个人在大城市漂着，要不要回老家发展？", "人生规划"),
    # 执行力/自我管理 +3
    ("早上起不来，闹钟响了按掉继续睡，怎么养成早起习惯？", "执行力"),
    ("做事情总是拖到最后一刻才动，怎么治拖延症？", "执行力"),
    ("报了很多课买了书，就是看不进去，钱白花了怎么办？", "执行力"),
    # 认知/鉴别 +4
    ("网上那些'七天学会炒股'的课程是骗子吗？", "认知鉴别"),
    ("怎么分辨一个人是真心帮我还是想利用我？", "认知鉴别"),
    ("朋友圈晒的收入截图能信吗？", "认知鉴别"),
    ("为什么我妈总信养生谣言，怎么劝都不听？", "认知鉴别"),
    # 金融/危机（小说主题补盲区，novel 卡主场）
    ("金融危机来了，普通人应该囤现金还是囤黄金？", "金融危机"),
    ("怎么在别人恐慌抛售的时候找到便宜货？", "金融危机"),
    ("做空是怎么操作的？普通人能玩吗？", "金融危机"),
    ("听说日本汇率崩了，对普通中国人有什么影响？", "金融危机"),
    # ===== v1.6 扩容（2026-08-29）：求职生活板块（用户真实场景）=====
    ("去深圳实习，第一次租房怎么防止押金被扣？", "求职生活"),
    ("试用期被公司延长/劝退，法律上怎么办？", "求职生活"),
    ("第一份工作做不下去，要不要走？", "求职生活"),
    ("广州和深圳，去哪个城市发展更好？", "求职生活"),
    # 负样本（无答案/无关 query，测系统是否胡编；单独统计不混入召回率）
    ("明天双色球开奖号码是多少？", "负样本"),
    ("我家的猫为什么突然不理我了？", "负样本"),
    ("外星人什么时候来地球？", "负样本"),
    ("怎么在三天内从零学会编程然后月薪三万？", "负样本"),
    ("量子力学能不能解释命运？", "负样本"),
]


def collect(ver: str = "16"):
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
    out = collect_file(ver)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"落盘: {out}")


def judge(ver: str = "16"):
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY 未设置"); sys.exit(1)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    with open(collect_file(ver), encoding="utf-8") as f:
        data = json.load(f)

    import sqlite3
    from db import get_conn
    conn = get_conn()  # 用统一连接（不依赖 cwd 相对路径，支持测试时重定向 DB_PATH）
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

    out = judge_file(ver)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(judged, f, ensure_ascii=False, indent=1)

    # ── 指标 ──
    print("\n=== 对抗集指标 ===")
    total_rel = total_partial = total_irrel = total_all = 0
    p5s, p10s = [], []
    by_cat = {}
    neg_all = neg_irrel = 0  # 负样本单独统计（测胡编，不混入召回率）
    hit5 = hit10 = 0
    n_pos_q = 0
    mrrs = []
    for item in judged:
        rs = [r for r in item["results"] if "error" not in r]
        if not rs:
            continue
        rel = sum(1 for r in rs if r["label"] == "relevant")
        part = sum(1 for r in rs if r["label"] == "partial")
        irr = sum(1 for r in rs if r["label"] == "irrelevant")
        if item["category"] == "负样本":
            neg_all += len(rs); neg_irrel += irr
            continue  # 负样本不计入召回率/P@5
        n_pos_q += 1
        total_all += len(rs); total_rel += rel; total_partial += part; total_irrel += irr
        if len(rs) >= 5:
            p5s.append(sum(1 for r in rs[:5] if r["label"] == "relevant") / 5)
        if len(rs) >= 10:
            p10s.append(sum(1 for r in rs[:10] if r["label"] == "relevant") / 10)
        # hit@K / MRR（基于 relevant）
        rel_idx = next((i for i, r in enumerate(rs) if r["label"] == "relevant"), None)
        if rel_idx is not None:
            hit10 += 1
            mrrs.append(1.0 / (rel_idx + 1))
            if rel_idx < 5:
                hit5 += 1
        cat = item["category"]
        by_cat.setdefault(cat, {"rel": 0, "part": 0, "total": 0})
        by_cat[cat]["rel"] += rel; by_cat[cat]["part"] += part; by_cat[cat]["total"] += len(rs)

    n = n_pos_q
    print(f"query 数: {n}（不含负样本，负样本 {len(judged)-n} 条）")
    rp = total_rel + total_partial
    print(f"总条数: {total_all}  相关: {total_rel} ({total_rel/total_all*100:.1f}%)  "
          f"部分: {total_partial} ({total_partial/total_all*100:.1f}%)  "
          f"不相关: {total_irrel} ({total_irrel/total_all*100:.1f}%)")
    print(f"**对抗集召回率(相关+部分): {rp/total_all*100:.1f}%**")
    print(f"Precision@5: {sum(p5s)/len(p5s)*100:.1f}%  (n={len(p5s)})")
    print(f"Precision@10: {sum(p10s)/len(p10s)*100:.1f}%  (n={len(p10s)})")
    print(f"Hit@5: {hit5}/{n} = {hit5/n*100:.1f}%   Hit@10: {hit10}/{n} = {hit10/n*100:.1f}%")
    print(f"MRR: {sum(mrrs)/len(mrrs):.3f}  (n={len(mrrs)})")
    if neg_all:
        print(f"负样本正确拒绝率(irrelevant占比): {neg_irrel/neg_all*100:.1f}%  ({neg_irrel}/{neg_all})  ← 越高越好，低说明系统胡编")
    print("\n=== 按板块（负样本单独）===")
    for cat, v in sorted(by_cat.items()):
        rp_cat = v["rel"] + v["part"]
        print(f"  {cat}: {rp_cat}/{v['total']} ({rp_cat/v['total']*100:.1f}%)  rel={v['rel']} part={v['part']}")

    # ── 写报告 ──
    lines = [f"# 对抗集评估报告 v{ver}", ""]
    lines.append(f"- 时间: {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- query 数: {n}（正样本）+ {len(judged)-n}（负样本）")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 召回率(相关+部分) | {rp/total_all*100:.1f}% |")
    lines.append(f"| 严格相关率 | {total_rel/total_all*100:.1f}% |")
    lines.append(f"| Precision@5 | {sum(p5s)/len(p5s)*100:.1f}% |")
    lines.append(f"| Precision@10 | {sum(p10s)/len(p10s)*100:.1f}% |")
    lines.append(f"| Hit@5 | {hit5}/{n} = {hit5/n*100:.1f}% |")
    lines.append(f"| Hit@10 | {hit10}/{n} = {hit10/n*100:.1f}% |")
    lines.append(f"| MRR | {sum(mrrs)/len(mrrs):.3f} |")
    lines.append(f"| 负样本拒绝率 | {neg_irrel/neg_all*100:.1f}% |" if neg_all else "")
    lines.append("")
    lines.append("## 按板块")
    lines.append("| 板块 | 可用率 | rel | part |")
    lines.append("|---|---|---|---|")
    for cat, v in sorted(by_cat.items()):
        rp_cat = v["rel"] + v["part"]
        lines.append(f"| {cat} | {rp_cat}/{v['total']} ({rp_cat/v['total']*100:.1f}%) | {v['rel']} | {v['part']} |")
    rep = report_file(ver)
    with open(rep, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告: {rep}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect-only", action="store_true")
    ap.add_argument("--judge-only", action="store_true")
    ap.add_argument("--version", default="16", help="版本号，默认 16")
    args = ap.parse_args()
    if args.judge_only:
        judge(args.version)
    elif args.collect_only:
        collect(args.version)
    else:
        collect(args.version)
        judge(args.version)
