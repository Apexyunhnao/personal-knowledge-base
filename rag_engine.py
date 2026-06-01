"""RAG引擎模块 — 支持多会话隔离"""
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from dotenv import load_dotenv
import os
from typing import List

load_dotenv()

# ── 中文语义Embedding ──
class ChineseEmbedding(EmbeddingFunction):
    def __init__(self):
        self.model = SentenceTransformer("shibing624/text2vec-base-chinese")
    
    def __call__(self, texts: Documents) -> Embeddings:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


class RAGEngine:
    """RAG问答引擎 — 每个session_id对应独立的向量库，会话间数据隔离"""
    
    def __init__(self, db_dir: str = "./chroma_db", chunk_size: int = 300, chunk_overlap: int = 150):
        self.db_dir = db_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        # LLM
        self.llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com"
        )
        
        # 向量库客户端（不预加载任何collection）
        self.client = chromadb.PersistentClient(path=db_dir)
    
    def _collection_name(self, session_id: str) -> str:
        """会话对应的collection名"""
        return f"docs_{session_id}"
    
    def _get_collection(self, session_id: str):
        """获取会话的collection，不存在则创建"""
        name = self._collection_name(session_id)
        try:
            return self.client.get_collection(
                name=name,
                embedding_function=ChineseEmbedding()
            )
        except Exception:
            return self.client.create_collection(
                name=name,
                embedding_function=ChineseEmbedding()
            )
    
    def load_document(self, path: str) -> str:
        """加载文档（支持PDF/MD/TXT）"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"文件不存在: {path}")
        
        if path.endswith(".pdf"):
            doc = pymupdf.open(path)
            return "\n".join([page.get_text() for page in doc])
        else:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    
    def ingest(self, session_id: str, path: str) -> int:
        """摄入文档到指定会话：解析 → 切片 → 向量化 → 入库"""
        text = self.load_document(path)
        if not text.strip():
            raise ValueError("文档内容为空")
        
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", ".", " "],
        )
        chunks = splitter.split_text(text)
        
        # 清除该会话旧数据
        name = self._collection_name(session_id)
        try:
            self.client.delete_collection(name)
        except Exception:
            pass
        
        col = self._get_collection(session_id)
        col.add(
            documents=chunks,
            ids=[f"chunk_{i}" for i in range(len(chunks))]
        )
        
        return len(chunks)
    
    def document_count(self, session_id: str) -> int:
        """指定会话的文档块数量"""
        try:
            col = self._get_collection(session_id)
            return col.count()
        except Exception:
            return 0
    
    def ask(self, session_id: str, question: str, top_k: int = 5) -> str:
        """RAG问答（按会话隔离）"""
        col = self._get_collection(session_id)
        
        # 判断是否为非文档类问题
        greetings = ["你好", "嗨", "hello", "hi", "你是谁", "你能做什么", "有什么功能", "功能", "能干什么", "可以做什么", "会什么", "自我介绍", "介绍自己", "你是什么"]
        is_greeting = any(g in question for g in greetings)
        
        if is_greeting:
            prompt = question
        else:
            if col.count() == 0:
                return "请先上传文档"
            
            # 检索（≤20块时全量检索）
            if col.count() <= 20:
                top_k = col.count()
            results = col.query(query_texts=[question], n_results=top_k)
            retrieved = results["documents"][0]
            
            context = "\n\n---\n\n".join(retrieved)
            prompt = f"""根据以下文档内容，用你自己的话整理回答，不要照搬原文。

文档内容：
{context}

问题：{question}

要求：
- 用自己的话重新组织，像跟人介绍一样自然
- 如果问多项内容，全部列出不遗漏
- 文档没有的信息如实说"未提及"
"""
        
        resp = self.llm.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是文档问答助手。回答简洁专业。严格禁止使用任何markdown符号：禁止**加粗**、禁止-列表、禁止#标题、禁止`代码块`、禁止*斜体*。回答必须是纯文本，用换行和空格分隔。\n- 自我介绍：一句话\n- 评价简历：只列优缺点各3条，不要复述简历全文\n- 查具体信息：要点式，每条一句话\n- 文档没提到的说未提及"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
        )
        
        return resp.choices[0].message.content
