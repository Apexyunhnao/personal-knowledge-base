# 检索评估集

## 最新基线：v16（2026-08-29）

- **query 数**：52 正样本 + 5 负样本（57 条，含求职生活板块 4 条）
- **评估脚本**：`eval_adversarial.py --version 16`（collect + judge + 报告一条龙）
- **结果文件**：`adversarial_collected_v16.json`（检索原始结果）/ `adversarial_judged_v16.json`（判定结果）/ `report_v16.md`（指标报告）
- **核心指标**（详见 report_v16.md）：
  - 召回率（relevant+partial）：77.9%
  - Hit@10：94.2%（49/52）
  - Hit@5：92.3%（48/52）
  - MRR：0.728
  - 负样本拒绝率：66.0%（33/50，测系统是否胡编）
  - 最强板块：人生规划 94.3%、执行力 87.1%、投资心态 86.2%
  - 待改进板块：求职生活 65.0%、人际博弈 67.1%、金融危机 57.5%

## 历史版本

| 版本 | 时间 | query 数 | 召回率 | 说明 |
|---|---|---|---|---|
| v15 | 2026-08-28 | 53 | 81.5% | 金融危机补卡收官 |
| v14 | 2026-08-28 | 53 | 81.2% | 周期板块 |
| v13 | 2026-08-27 | 53 | ~80% | 扩容 26→53 |
| v12 | 2026-08-27 | 26 | — | 三AI合并去重 |
| v1 | 2026-08-24 | 27 | 80.4% | 小说萃取检索评估 |

> 历史中间版本文件已从 git 移除（保留在本地 evaluation/ 目录）。每个版本文件命名规则：`adversarial_{collected|judged}_v{ver}_{备注}.json`。
> 用户问题池（新 query 候选）见 `user_questions.md`，对抗集扩容优先从那里选。

## 方法

- **Query 集**：真实场景口语化 query，覆盖投资心态/职场焦虑/人际博弈/人生规划/执行力/认知鉴别/金融危机/求职生活 8 个板块 + 5 条负样本（测系统是否胡编，单独统计不混入召回率）
- **检索**：hybrid_search top_k=10（FTS5 + ChromaDB RRF 融合，低置信度过滤，标签加权生效）
- **判定**：DeepSeek chat 逐条判 relevant / partial / irrelevant（基于 title + content 前 120 字）
- **指标**：召回率（rel+partial 占比）、Precision@5/@10、Hit@5/@10、MRR、负样本拒绝率、分板块可用率

## 常用命令

```bash
# 全量跑（collect + judge + 报告）
python eval_adversarial.py --version 16

# 只跑检索落盘（不调 LLM，不花钱）
python eval_adversarial.py --collect-only --version 16

# 只跑判定（读已有检索结果）
python eval_adversarial.py --judge-only --version 16
```

## 结论

1. **召回可用**：Hit@10 94.2% 说明 10 次检索 9 次能找到相关卡；负样本 66% 拒绝率说明边界 query 基本不会胡编。
2. **严格相关率偏低是判定口径问题**：卡片是去情节化的方法论（决策提醒），对具体查询词天然多为 partial——产品定位如此，不是检索缺陷。
3. **求职生活板块 65.0% 是新板块**：新卡刚入库，覆盖还在爬坡；人际博弈 67.1% 和金融危机 57.5% 是长期弱项，缺操作型（playbook）卡。
