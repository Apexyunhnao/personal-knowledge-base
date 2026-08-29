# 个人决策知识库（Personal Decision KB）

一个面向个人决策支持的中文 RAG 系统：2.3 万+ 张方法论卡片（职场/投资/人生规划/认知鉴别等 8 大板块），通过混合检索把「对的卡片」在 top10 里捞出来，帮助用户在真实决策场景中做判断。已接入 Hermes Agent 作为外部记忆（MCP 工具）。

> 定位：**决策提醒卡片库**，不是聊天机器人。核心是检索质量——「让对的卡片出现在 top10」，而不是让 LLM 编一个看起来合理的回答。

## 核心指标（对抗集 v16，2026-08-29）

| 指标 | 值 |
|---|---|
| 卡片数 | 23,858（5664 标签） |
| 对抗集 query | 52 正样本 + 5 负样本（8 大板块） |
| Hit@10 | **94.2%**（49/52） |
| Hit@5 | 92.3% |
| MRR | 0.728 |
| 召回率（relevant+partial） | 77.9% |
| 负样本拒绝率 | 66.0%（测系统是否胡编） |
| 最强板块 | 人生规划 94.3% / 执行力 87.1% / 投资心态 86.2% |
| 待改进 | 求职生活 65.0% / 人际博弈 67.1% / 金融危机 57.5% |

完整评估：`evaluation/report_v16.md`；评估方法论：`evaluation/README.md`。

## 为什么做（场景动机）

个人做重大决策（职场去留、投资心态、人生规划）时，最缺的不是"信息"，而是**经历过类似困境的人留下的方法论**。这个系统把书/经验帖/攻略文萃取成结构化方法论卡片，检索到"对的卡片"帮用户触发决策思考——而不是让 AI 直接给答案。

## 怎么做（技术架构）

```
用户 query
   ↓
混合检索（双路召回）
  ├─ FTS5 全文检索（SQLite，关键词精确匹配）
  └─ 向量检索（ChromaDB + bge-small 中文 embedding，语义匹配）
   ↓
RRF 融合（rank-based 融合，不依赖两路 score 空间对齐）
   ↓
标签加权 + 来源权重（书>笔记>论坛>小说）+ 低置信度过滤
   ↓
top10 卡片 → 展示 / 喂给 LLM 生成回答 / 喂给 Agent 做决策
```

关键设计：
- **RRF 融合**：FTS5 和向量检索的 score 空间不同，直接加权不可靠；RRF 按 rank 融合更鲁棒
- **来源权重**：书（1.3）> 笔记 > 论坛 > 小说，控制内容可信度
- **低置信度过滤**：小说萃取卡置信度低，默认过滤，避免污染召回
- **评估驱动**：53+ 条真实场景 query 对抗集，每轮迭代跑分，有历史基线（v1→v16）

## 数据（卡片从哪来）

- 23,858 张有效卡片，5664 标签，SQLite + ChromaDB 双存储，启动时向量索引一致性校验
- 数据来源：方法论书籍萃取（金融危机/求职/向上管理/自控力等）、经验帖（天涯精选）、网页攻略文（租房/职场避坑）、手写 QA 卡
- 萃取管线：微信读书导出 → DeepSeek 四步法（困境定义→方法拆解→锚点识别→原理映射）→ 方法论卡片 → 入库
- 完整库本地自用；公开仓库不含原始书籍/帖子全文（版权考虑），只含代码和评估数据

## 功能

- **混合检索 API**：`GET /search?q=...`
- **聊天问答**：检索 + LLM 生成（DeepSeek）
- **个人事务维度**：租房记录 / 职场事件表 + CRUD + 聊天录入（"记一条租房信息"）
- **MCP 接入**：`mcp_kb_server.py`，作为 Hermes Agent 外部记忆（kb_search / kb_get / kb_save）
- **Web 前端**：检索、聊天、侧边栏个人事务入口
- **评估闭环**：`eval_adversarial.py --version N` 一条龙跑 collect+judge+报告

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 .env
DEEPSEEK_API_KEY=your_key

# 3. 启动
python -m uvicorn app:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000

# 4. 跑评估（可选）
python eval_adversarial.py --version 16
```

> 需要 bge-small 中文 embedding 模型，首次启动自动下载到 models/（或在 hybrid_search.py 里配置 HF_HUB_OFFLINE）。

## 目录结构

```
├── app.py                  # FastAPI 入口
├── hybrid_search.py        # 混合检索核心（FTS5 + Chroma + RRF + 加权）
├── rag_engine.py           # RAG 问答（检索 + LLM 生成）
├── mcp_kb_server.py        # MCP 服务器（Agent 外部记忆接入）
├── eval_adversarial.py     # 对抗集评估（collect+judge+报告）
├── personal_db.py          # SQLite 数据层（notes/tags/housing/events）
├── routers/                # API 路由（chat/database/tags/backup/monitor...）
├── repositories/           # 数据访问层
├── evaluation/             # 对抗集 query、基线、报告
├── templates/              # 前端
└── tests/                  # 测试
```

## 评估迭代历史

| 版本 | query | Hit@10 | 说明 |
|---|---|---|---|
| v16 | 57 | 94.2% | 新增求职生活板块（2026-08-29） |
| v15 | 53 | 81.1% | 金融危机补卡收官 |
| v14 | 53 | — | 周期板块补充 |
| v13 | 53 | ~80% | 对抗集扩容 26→53 |
| v1 | 27 | — | 首版评估 |

> 指标口径变化：早期版本用"召回率（rel+partial）"，v16 起补充 Hit@K/MRR（更贴近"能否真回答"）。

## License

MIT
