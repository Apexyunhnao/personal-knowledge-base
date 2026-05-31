# RAG智能文档问答系统

基于检索增强生成（RAG）的文档问答系统，支持上传PDF/Markdown文档后进行智能问答。

## 技术栈

- **LLM**: DeepSeek API
- **Embedding**: text2vec-base-chinese（中文语义模型）
- **向量库**: ChromaDB
- **文档解析**: PyMuPDF（PDF）+ 原生（Markdown/TXT）
- **框架**: LangChain（文本切片） + FastAPI（Web接口）

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置API Key
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 3. 命令行问答
python step3_rag_qa.py

# 4. 启动Web服务
python app.py
# 浏览器打开 http://localhost:8000
```

## 项目结构

```
rag-qa-project/
├── rag_engine.py         # RAG核心引擎（可复用模块）
├── app.py                # FastAPI Web服务 + Web界面
├── step1_pdf_chunk.py    # 学习用：PDF解析 + 切片
├── step2_embedding.py    # 学习用：向量化 + 检索
├── step3_rag_qa.py       # 学习用：完整RAG链路
├── chroma_db/            # 向量数据库（自动生成）
├── .env                  # API Key配置
└── requirements.txt      # Python依赖
```

## 工作原理

```
PDF/MD → 文本切片 → 向量化 → ChromaDB
                                ↓
用户提问 → 语义检索 → 拼Prompt → DeepSeek → 回答
```

## License

MIT
