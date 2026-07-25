# 个人资料库

基于 DeepSeek 的 AI 知识管理系统。支持聊天式知识存入、混合检索（全文+语义）、自动整理归纳。

## 核心能力

- **聊天式知识管理**：通过对话让 AI 帮你整理、存储、检索个人知识
- **智能存/不存判断**：自动判断内容是否值得存入（消化过的理解存，API 文档/新闻不存）
- **自动合并整理**：同主题内容自动合并到已有笔记，避免碎片化
- **混合检索**：FTS5 全文搜索 + ChromaDB 语义搜索
- **文件支持**：上传 PDF/Markdown/TXT/图片，自动提取文字

## 技术栈

- **LLM**：DeepSeek（Function Calling）
- **Embedding**：text2vec-base-chinese
- **向量库**：ChromaDB
- **全文搜索**：SQLite FTS5
- **框架**：FastAPI + 原生 SQLite
- **图片识别**：Qwen-VL（DashScope）

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
export DEEPSEEK_API_KEY=your_key
export DASHSCOPE_API_KEY=your_key  # 图片识别用，可选

# 3. 启动服务
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000

# 4. 浏览器打开 http://localhost:8000
```

## 项目结构

```
├── app.py                  # FastAPI 入口（路由挂载）
├── rag_engine.py           # RAG 核心：嵌入 + 检索 + 生成
├── hybrid_search.py         # 混合检索：FTS5 + ChromaDB + RRF 融合
├── models.py                # 数据模型
├── db.py                    # 数据库连接
├── personal_db.py           # 个人知识库管理
├── mcp_server.py            # MCP 服务（供 Hermes 调用）
├── routers/                 # API 路由
│   ├── chat.py              #   聊天端点（核心）
│   ├── database.py          #   数据库 CRUD
│   ├── tags.py              #   标签管理
│   ├── trash.py             #   回收站
│   ├── documents.py         #   文档上传
│   ├── backup.py            #   备份恢复
│   ├── notes_md.py          #   笔记导出
│   └── links.py             #   知识图谱
├── repositories/            # 数据访问层
├── templates/               # 前端页面
└── tests/                   # 测试
```

## 工作原理

```
用户输入 → DeepSeek 判断「存/不存」
              ↓ 值得存
         FTS5 + ChromaDB 混合搜索
              ↓
         合并到已有笔记 / 新建笔记
              ↓
         向量化 → ChromaDB 索引
```

聊天查询时：

```
提问 → FTS5 关键词 + ChromaDB 语义 → RRF 融合排序 → DeepSeek 基于结果回答
```

## License

MIT
