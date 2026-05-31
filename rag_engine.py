"""RAG引擎模块 — 可被Web服务import"""
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from dotenv import load_dotenv
import os, shutil
from typing import List

load_dotenv()

# ── 中文语义Embedding ──
class ChineseEmbedding(EmbeddingFunction):
    def __init__(self):
        self.model = SentenceTransformer("shibing624/text2vec-base-chinese")
    
    def __call__(self, texts: Documents) -> Embeddings:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


class RAGEngine:
    """RAG问答引擎"""
    
    def __init__(self, db_dir: str = "./chroma_db", chunk_size: int = 500, chunk_overlap: int = 100):
        self.db_dir = db_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        # LLM
        self.llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com"
        )
        
        # 向量库
        self.client = chromadb.PersistentClient(path=db_dir)
        self.collection = None
        self._init_collection()
    
    def _init_collection(self):
        """初始化或加载collection"""
        try:
            self.collection = self.client.get_collection(
                name="documents",
                embedding_function=ChineseEmbedding()
            )
        except Exception:
            self.collection = self.client.create_collection(
                name="documents",
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
    
    def ingest(self, path: str) -> int:
        """摄入文档：解析 → 切片 → 向量化 → 入库"""
        text = self.load_document(path)
        if not text.strip():
            raise ValueError("文档内容为空")
        
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", ".", " "],
        )
        chunks = splitter.split_text(text)
        
        # 清除旧数据
        self.client.delete_collection("documents")
        self._init_collection()
        
        self.collection.add(
            documents=chunks,
            ids=[f"chunk_{i}" for i in range(len(chunks))]
        )
        
        return len(chunks)
    
    def ask(self, question: str, top_k: int = 3) -> str:
        """RAG问答"""
        if self.collection.count() == 0:
            return "请先摄入文档（ingest）"
        
        # 1. 检索
        results = self.collection.query(query_texts=[question], n_results=top_k)
        retrieved = results["documents"][0]
        
        # 2. 拼Prompt
        context = "\n\n---\n\n".join(retrieved)
        prompt = f"""根据以下文档内容回答问题。

文档内容：
{context}

问题：{question}
请直接回答，文档中没有的信息就说"未提及"。不要编造。
"""
        
        # 3. LLM回答
        resp = self.llm.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        
        return resp.choices[0].message.content
    
    def search(self, query: str, top_k: int = 3) -> List[str]:
        """纯检索（不含LLM回答）"""
        if self.collection.count() == 0:
            return []
        results = self.collection.query(query_texts=[query], n_results=top_k)
        return results["documents"][0]
    
    @property
    def document_count(self) -> int:
        return self.collection.count() if self.collection else 0


# ── 命令行测试 ──
if __name__ == "__main__":
    engine = RAGEngine()
    
    # 摄入文档
    path = "/home/her91/简历_黄文浩_修改版.md"
    count = engine.ingest(path)
    print(f"📄 摄入: {path} → {count}个文本块")
    
    # 测试问答
    for q in ["参加过什么竞赛？", "会什么编程语言？", "有什么证书？", "实习经历是什么？"]:
        answer = engine.ask(q)
        print(f"\n❓ {q}")
        print(f"💬 {answer}")
