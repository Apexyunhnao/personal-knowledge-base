"""RAG引擎模块 — 支持多会话隔离 + SHA-256增量索引"""
import hashlib
import json
import logging
import os
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
# 国内镜像 + 强制离线（模型本地缓存；与 hybrid_search.py 保持一致）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Dict

load_dotenv()
logger = logging.getLogger(__name__)

# 与 hybrid_search.py 共用同一模型（2026-08-26 升级 bge-base-zh-v1.5，本地路径）
EMBEDDING_MODEL = os.environ.get(
    "RAG_EMBEDDING_MODEL",
    os.path.join(os.path.dirname(__file__), "models", "bge-base-zh-v1.5"),
)

# ── 中文语义Embedding ──
class ChineseEmbedding(EmbeddingFunction):
    def __init__(self):
        import torch
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = SentenceTransformer(EMBEDDING_MODEL, device=self._device)
    
    def __call__(self, texts: Documents) -> Embeddings:
        batch = 64 if self._device == "cuda" else 32
        return self.model.encode(texts, normalize_embeddings=True, batch_size=batch).tolist()


class RAGEngine:
    """RAG问答引擎 — SHA-256增量索引，支持多文件追加（不重建）"""
    
    def __init__(self, db_dir: str = "./chroma_db", chunk_size: int = 300, chunk_overlap: int = 150):
        self.db_dir = db_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.hash_cache_path = os.path.join(db_dir, "file_hashes.json")
        self._hash_cache: Dict[str, Dict[str, dict]] = self._load_hash_cache()
        
        # LLM
        self.llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com"
        )
        
        # 向量库客户端
        self.client = chromadb.PersistentClient(path=db_dir)
    
    # ── 文件哈希缓存 ──
    
    def _load_hash_cache(self) -> dict:
        """加载文件哈希缓存"""
        if os.path.exists(self.hash_cache_path):
            try:
                with open(self.hash_cache_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    
    def _save_hash_cache(self):
        """持久化哈希缓存"""
        os.makedirs(self.db_dir, exist_ok=True)
        with open(self.hash_cache_path, 'w') as f:
            json.dump(self._hash_cache, f, indent=2)
    
    @staticmethod
    def _compute_hash(filepath: str) -> str:
        """计算文件 SHA-256（分块读取，支持大文件）"""
        sha = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha.update(chunk)
        return sha.hexdigest()
    
    # ── Collection 管理 ──
    
    def _collection_name(self, session_id: str) -> str:
        return f"docs_{session_id}"
    
    def _get_collection(self, session_id: str):
        name = self._collection_name(session_id)
        try:
            return self.client.get_collection(name=name, embedding_function=ChineseEmbedding())
        except Exception:
            return self.client.create_collection(name=name, embedding_function=ChineseEmbedding())
    
    def load_document(self, path: str) -> str:
        """加载文档（PDF/MD/TXT）"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"文件不存在: {path}")
        if path.endswith(".pdf"):
            doc = pymupdf.open(path)
            return "\n".join([page.get_text() for page in doc])
        else:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    
    def ingest(self, session_id: str, path: str) -> dict:
        """摄入文档：SHA-256增量索引 + 追加模式（不重建）
        
        Returns:
            {"chunks": int, "skipped": bool, "total_chunks": int}
        """
        # 1. 计算哈希，检查是否已索引
        file_hash = self._compute_hash(path)
        session_cache = self._hash_cache.get(session_id, {})
        
        if path in session_cache and session_cache[path].get("hash") == file_hash:
            return {
                "chunks": session_cache[path]["chunks"],
                "skipped": True,
                "total_chunks": self.document_count(session_id),
            }
        
        # 2. 加载并切片
        text = self.load_document(path)
        if not text.strip():
            raise ValueError("文档内容为空")
        
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", ".", " "],
        )
        chunks = splitter.split_text(text)
        
        # 3. 如果是更新已有文件，先删除旧chunks
        col = self._get_collection(session_id)
        if path in session_cache:
            old_count = session_cache[path].get("chunks", 0)
            old_ids = [f"{path}_chunk_{i}" for i in range(old_count)]
            try:
                col.delete(ids=old_ids)
            except Exception:
                pass
        
        # 4. 追加新chunks（用文件路径做ID前缀避免冲突）
        chunk_ids = [f"{path}_chunk_{i}" for i in range(len(chunks))]
        col.add(documents=chunks, ids=chunk_ids)
        
        # 5. 更新缓存
        if session_id not in self._hash_cache:
            self._hash_cache[session_id] = {}
        self._hash_cache[session_id][path] = {
            "hash": file_hash,
            "chunks": len(chunks),
        }
        self._save_hash_cache()
        
        return {
            "chunks": len(chunks),
            "skipped": False,
            "total_chunks": col.count(),
        }
    
    def document_count(self, session_id: str) -> int:
        try:
            return self._get_collection(session_id).count()
        except Exception:
            return 0
    
    def session_files(self, session_id: str) -> list:
        """列出会话中已索引的文件"""
        session_cache = self._hash_cache.get(session_id, {})
        return [{"path": p, "chunks": v["chunks"], "hash": v["hash"][:8]}
                for p, v in session_cache.items()]
    
    def clear_session(self, session_id: str):
        """清除会话所有数据"""
        name = self._collection_name(session_id)
        try:
            self.client.delete_collection(name)
        except Exception:
            pass
        self._hash_cache.pop(session_id, None)
        self._save_hash_cache()
    
    def ask(self, session_id: str, question: str, top_k: int = 5) -> str:
        """RAG问答（按会话隔离）"""
        col = self._get_collection(session_id)
        
        greetings = ["你好", "嗨", "hello", "hi", "你是谁", "你能做什么", "有什么功能"]
        is_greeting = any(g in question for g in greetings)
        
        if is_greeting:
            prompt = question
        else:
            if col.count() == 0:
                return "请先上传文档"
            
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
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": "你是文档问答助手。回答简洁专业。禁止markdown符号。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
        )
        
        return resp.choices[0].message.content
