"""
混合检索模块 — FTS5关键词 + ChromaDB语义向量 双路融合

使用 RRF（Reciprocal Rank Fusion）合并两路结果：
  RRF_score = Σ 1/(k + rank_i)
  其中 k=60（经典参数），rank 从 1 开始
"""
import os
import json
import logging

# 国内 HuggingFace 镜像
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")
NOTES_COLLECTION = "notes_knowledge"


class ChineseEmbedding(EmbeddingFunction):
    """中文语义向量模型（与 rag_engine.py 共用同一模型类）"""
    def __init__(self):
        self.model = SentenceTransformer("shibing624/text2vec-base-chinese")

    def __call__(self, texts: Documents) -> Embeddings:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


# 全局单例
_embedding_fn = None
_chroma_client = None


def _get_embedding_fn():
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = ChineseEmbedding()
    return _embedding_fn


def _get_chroma():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _chroma_client


def _get_notes_collection():
    """获取笔记向量集合（不存在则创建）"""
    client = _get_chroma()
    try:
        return client.get_collection(name=NOTES_COLLECTION, embedding_function=_get_embedding_fn())
    except Exception:
        logger.info(f"创建向量集合: {NOTES_COLLECTION}")
        return client.create_collection(name=NOTES_COLLECTION, embedding_function=_get_embedding_fn())


def sync_note_embedding(note_id: int, title: str, content: str):
    """
    同步笔记到向量库（创建或更新）。
    从 ChromaDB 删除旧向量后重新插入。
    """
    try:
        col = _get_notes_collection()
        # 删除旧向量
        col.delete(ids=[str(note_id)])
        # 插入新向量：标题+内容拼接
        text = f"{title}\n{content}" if content else title
        col.add(
            ids=[str(note_id)],
            documents=[text],
            metadatas=[{"title": title, "note_id": note_id}],
        )
        logger.debug(f"向量同步: note#{note_id} '{title[:30]}'")
    except Exception as e:
        logger.warning(f"向量同步失败 note#{note_id}: {e}")


def remove_note_embedding(note_id: int):
    """从向量库删除笔记"""
    try:
        col = _get_notes_collection()
        col.delete(ids=[str(note_id)])
    except Exception as e:
        logger.warning(f"向量删除失败 note#{note_id}: {e}")


def build_all_embeddings():
    """全量重建所有笔记的向量索引"""
    import sqlite3
    from db import get_conn

    conn = get_conn()
    notes = conn.execute(
        "SELECT id, title, COALESCE(content,'') as content FROM learning_notes WHERE deleted_at IS NULL"
    ).fetchall()

    col = _get_notes_collection()
    # 清空重建
    try:
        client = _get_chroma()
        client.delete_collection(NOTES_COLLECTION)
    except Exception:
        pass

    col = _get_notes_collection()
    ids = []; docs = []; metas = []
    for n in notes:
        ids.append(str(n["id"]))
        docs.append(f"{n['title']}\n{n['content']}")
        metas.append({"title": n["title"], "note_id": n["id"]})

    if ids:
        col.add(ids=ids, documents=docs, metadatas=metas)
        logger.info(f"全量向量化完成: {len(ids)} 条笔记")


def hybrid_search(query: str, top_k: int = 10) -> list[dict]:
    """
    混合检索：FTS5 + ChromaDB 双路 → RRF 融合。

    返回: [{"id": int, "title": str, "score": float, "source": "fts5"|"vector"|"both"}, ...]
    """
    import sqlite3
    from db import get_conn

    # ── 路1: FTS5 关键词检索 ──
    fts_scores = {}  # note_id -> rank (1-based)
    try:
        conn = get_conn()
        rows = conn.execute(
            "SELECT learning_notes.id, learning_notes.title "
            "FROM notes_fts "
            "JOIN learning_notes ON notes_fts.rowid = learning_notes.rowid "
            "WHERE notes_fts MATCH ? AND learning_notes.deleted_at IS NULL "
            "LIMIT ?",
            (query, top_k)
        ).fetchall()
        for rank, row in enumerate(rows, 1):
            fts_scores[row["id"]] = rank
    except Exception as e:
        logger.warning(f"FTS5检索失败: {e}")

    # ── 路2: ChromaDB 语义检索 ──
    vec_scores = {}  # note_id -> rank (1-based)
    try:
        col = _get_notes_collection()
        if col.count() > 0:
            results = col.query(query_texts=[query], n_results=top_k)
            if results["ids"] and results["ids"][0]:
                for rank, note_id_str in enumerate(results["ids"][0], 1):
                    vec_scores[int(note_id_str)] = rank
    except Exception as e:
        logger.warning(f"向量检索失败: {e}")

    # ── RRF 融合 ──
    k = 60
    all_ids = set(fts_scores.keys()) | set(vec_scores.keys())
    rrf = {}
    for nid in all_ids:
        score = 0.0
        if nid in fts_scores:
            score += 1.0 / (k + fts_scores[nid])
        if nid in vec_scores:
            score += 1.0 / (k + vec_scores[nid])
        rrf[nid] = score

    # 排序
    sorted_ids = sorted(rrf.keys(), key=lambda x: rrf[x], reverse=True)[:top_k]

    # 获取标题
    conn = get_conn()
    result = []
    for nid in sorted_ids:
        row = conn.execute(
            "SELECT id, title, topic, tags FROM learning_notes WHERE id=?", (nid,)
        ).fetchone()
        if row:
            sources = []
            if nid in fts_scores: sources.append("fts5")
            if nid in vec_scores: sources.append("vector")
            result.append({
                "id": row["id"],
                "title": row["title"],
                "topic": row["topic"],
                "tags": row["tags"],
                "score": round(rrf[nid], 5),
                "source": "+".join(sources),
            })

    return result
