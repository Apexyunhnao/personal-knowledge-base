"""
混合检索模块 — FTS5关键词 + ChromaDB语义向量 双路融合

使用 RRF（Reciprocal Rank Fusion）合并两路结果：
  RRF_score = Σ 1/(k + rank_i)
  其中 k=60（经典参数），rank 从 1 开始
"""
import os
import json
import logging

# 国内 HuggingFace 镜像 + 强制离线(模型已本地缓存, 避免每次加载撞hf-mirror网络)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")
NOTES_COLLECTION = "notes_knowledge"

# 中文语义向量模型（2026-08-26 从 text2vec-base-chinese 升级到 bge-base-zh-v1.5）
# text2vec 对方法论文本区分度差（0.8 阈值 93.4% 误合并），bge 中文榜单领先。
# 默认本地路径（项目 models/ 自包含）；可用环境变量 RAG_EMBEDDING_MODEL 覆盖（回滚/换模型不用改代码）。
EMBEDDING_MODEL = os.environ.get(
    "RAG_EMBEDDING_MODEL",
    os.path.join(os.path.dirname(__file__), "models", "bge-base-zh-v1.5"),
)


class ChineseEmbedding(EmbeddingFunction):
    """中文语义向量模型（bge-base-zh-v1.5，GPU 优先 CPU 兜底）"""
    def __init__(self):
        import torch
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = SentenceTransformer(EMBEDDING_MODEL, device=self._device)

    def __call__(self, texts: Documents) -> Embeddings:
        batch = 64 if self._device == "cuda" else 32
        return self.model.encode(texts, normalize_embeddings=True, batch_size=batch).tolist()


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

    # 分批插入（ChromaDB 批量 add 有批次上限，一次全插会静默截断）
    BATCH = 1000
    inserted = 0
    for i in range(0, len(ids), BATCH):
        col.add(
            ids=ids[i:i+BATCH],
            documents=docs[i:i+BATCH],
            metadatas=metas[i:i+BATCH],
        )
        inserted += len(ids[i:i+BATCH])
        logger.info(f"向量化进度: {inserted}/{len(ids)}")

    # 校验：向量数必须等于笔记数，否则报警
    actual = col.count()
    if actual != len(ids):
        logger.error(f"向量重建不完整: 期望{len(ids)} 实际{actual}")
        raise RuntimeError(f"向量重建不完整: 期望{len(ids)} 实际{actual}")
    logger.info(f"全量向量化完成: {len(ids)} 条笔记")


def hybrid_search(query: str, top_k: int = 10, include_low_confidence: bool = False) -> list[dict]:
    """
    混合检索：FTS5 + ChromaDB 双路 → RRF 融合。

    小说萃取笔记额外规则（项目书 v2.0 3.5，仅 tags 含"小说萃取"生效）：
      - 低置信度过滤：is_low_confidence=true 默认不召回，include_low_confidence=True 才显示。
        实现：双路各召回 2×top_k，过滤后再取前 top_k，避免 top-k 缩水。
      - 标签加权：核心标签×1.5，扩展标签×1.0，书名标签×0.5。
        核心/扩展按入库顺序解析（build_note_data: [小说萃取, 书名] + 核心≤3 + 扩展全保留）。

    返回: [{"id": int, "title": str, "score": float, "source": "fts5"|"vector"|"both",
            "is_low_confidence": bool}, ...]
    """
    import sqlite3
    from db import get_conn

    fetch_k = top_k * 2  # 2×k 召回，过滤后取前 k

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
            (query, fetch_k)
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
            results = col.query(query_texts=[query], n_results=fetch_k)
            if results["ids"] and results["ids"][0]:
                for rank, note_id_str in enumerate(results["ids"][0], 1):
                    vec_scores[int(note_id_str)] = rank
    except Exception as e:
        logger.warning(f"向量检索失败: {e}")

    # ── 路3: 标签召回（标签归一化映射）──
    # query 词 → 规范标签 → tags LIKE 精确匹配，解决"字面不同语义相同"的漏召
    tag_scores = {}  # note_id -> rank (1-based)
    try:
        norm_tags = _normalized_tags_for_query(query)
        if norm_tags:
            sql = "SELECT id FROM learning_notes WHERE deleted_at IS NULL AND (" \
                  + " OR ".join("tags LIKE ?" for _ in norm_tags) + ") LIMIT ?"
            params = [f"%{t}%" for t in norm_tags] + [fetch_k]
            for rank, row in enumerate(conn.execute(sql, params).fetchall(), 1):
                tag_scores[row["id"]] = rank
    except Exception as e:
        logger.warning(f"标签检索失败: {e}")

    # ── RRF 融合 ──
    k = 60
    all_ids = set(fts_scores.keys()) | set(vec_scores.keys()) | set(tag_scores.keys())
    rrf = {}
    for nid in all_ids:
        score = 0.0
        if nid in fts_scores:
            score += 1.0 / (k + fts_scores[nid])
        if nid in vec_scores:
            score += 1.0 / (k + vec_scores[nid])
        if nid in tag_scores:
            score += 0.9 / (k + tag_scores[nid])  # 标签路权重略低
        rrf[nid] = score

    # 排序（先按 RRF，再取全部做过滤+加权）
    sorted_ids = sorted(rrf.keys(), key=lambda x: rrf[x], reverse=True)

    # ── 标签加权 + 低置信度过滤（仅小说萃取笔记） ──
    terms = _query_terms(query)
    conn = get_conn()
    result = []
    for nid in sorted_ids:
        row = conn.execute(
            "SELECT id, title, topic, tags, frontmatter FROM learning_notes WHERE id=?",
            (nid,)
        ).fetchone()
        if not row:
            continue
        tags_str = row["tags"] or ""
        is_novel = _parse_novel_tags(tags_str)["is_novel"]
        low_conf = is_novel and _is_low_confidence(row["frontmatter"])
        if low_conf and not include_low_confidence:
            continue  # 低置信度默认不召回
        feedback = _user_feedback(row["frontmatter"])  # 仅小说萃取笔记有值, 普通笔记 0
        node_type = _node_type(row["frontmatter"])
        confidence = _confidence(row["frontmatter"])
        source_type = _source_type(row["frontmatter"])
        # 排序公式: rrf × 标签加权 × (1 + user_feedback) × 来源权重
        #   feedback cap ±0.15 → 最多 ±15% 调整
        #   source_weight 按来源可信度加权: book>note>forum>novel（AI 优先原则，高可信卡排前面）
        score = round(rrf[nid] * _tag_boost(tags_str, terms) * (1 + feedback) * _source_weight(row["frontmatter"]), 5)
        sources = []
        if nid in fts_scores: sources.append("fts5")
        if nid in vec_scores: sources.append("vector")
        result.append({
            "id": row["id"],
            "title": row["title"],
            "topic": row["topic"],
            "tags": tags_str,
            "score": score,
            "source": "+".join(sources),
            "is_low_confidence": low_conf,
            "user_feedback": feedback,
            "node_type": node_type,
            "confidence": confidence,
            "source_type": source_type,
        })

    # 标签加权后重新排序（加权影响排序，不只改分数显示）
    result.sort(key=lambda x: x["score"], reverse=True)
    return result[:top_k]


def _parse_novel_tags(tags_str: str) -> dict:
    """解析小说笔记 tags：按入库顺序 [小说萃取, 书名] + 核心(≤3) + 扩展(全保留)。

    项目书 v2.0 3.5 标签策略：入库 tags = [小说萃取, 书名] + 核心标签(≤3个) + 扩展标签。
    非小说笔记 is_novel=False，不加权不过滤。
    """
    tags = [t.strip() for t in (tags_str or "").split(",") if t.strip()]
    if not tags or tags[0] != "小说萃取":
        return {"is_novel": False, "book": "", "core": [], "ext": []}
    book = tags[1] if len(tags) > 1 else ""
    return {"is_novel": True, "book": book, "core": tags[2:5], "ext": tags[5:]}


def _query_terms(query: str) -> list[str]:
    """查询切词：按空白/逗号/顿号切分 + 整句。用于标签命中判断。"""
    import re
    parts = re.split(r"[\s,，、]+", query.strip())
    terms = [p for p in parts if p]
    if query.strip() and query.strip() not in terms:
        terms.append(query.strip())
    return terms


def _tag_boost(tags_str: str, terms: list[str]) -> float:
    """标签加权（仅小说萃取）：核心标签命中×1.5，书名标签命中×0.5，扩展×1.0。

    多标签命中取最大权重；非小说笔记返回 1.0 不受影响。
    """
    parsed = _parse_novel_tags(tags_str)
    if not parsed["is_novel"]:
        return 1.0
    core_hit = False
    book_hit = False
    for t in terms:
        for ct in parsed["core"]:
            if ct and (t in ct or ct in t):
                core_hit = True
        book = parsed["book"]
        if book and (t in book or book in t):
            book_hit = True
    if core_hit:
        return 1.5  # 核心提权优先，任何情况下覆盖书名降权
    if book_hit:
        return 0.5  # 仅书名命中 → 降权×0.5
    return 1.0


def _is_low_confidence(frontmatter_str: str | None) -> bool:
    """frontmatter.is_low_confidence（入库时 confidence<0.6 推导）"""
    try:
        fm = json.loads(frontmatter_str or "{}")
        return bool(fm.get("is_low_confidence", False))
    except Exception:
        return False


def _user_feedback(frontmatter_str: str | None) -> float:
    """frontmatter.user_feedback 累计分（-0.15 ~ +0.15，只影响排序）"""
    try:
        fm = json.loads(frontmatter_str or "{}")
        val = float(fm.get("user_feedback", 0.0))
        return max(-0.15, min(0.15, val))
    except Exception:
        return 0.0


def _node_type(frontmatter_str: str | None) -> str:
    """frontmatter.node_type（methodology/judgment/principle/pitfall），默认 methodology"""
    try:
        fm = json.loads(frontmatter_str or "{}")
        return str(fm.get("node_type", "methodology"))
    except Exception:
        return "methodology"


def _confidence(frontmatter_str: str | None) -> float:
    """frontmatter.confidence（卡片原始置信度 0-1），无则按 is_low_confidence 兜底"""
    try:
        fm = json.loads(frontmatter_str or "{}")
        if "confidence" in fm:
            return round(float(fm["confidence"]), 2)
        return 0.4 if fm.get("is_low_confidence") else 0.65
    except Exception:
        return 0.65


def _source_type(frontmatter_str: str | None) -> str:
    """frontmatter.source_type（novel/book/forum/note），默认 novel 兼容旧数据"""
    try:
        fm = json.loads(frontmatter_str or "{}")
        return str(fm.get("source_type", "novel"))
    except Exception:
        return "novel"


# 来源可信度权重（RRF 融合后乘到最终得分；AI 优先原则，高可信来源排前面）
# 系数依据来源可信度区间中值（book 0.775 / note 0.75 / forum 0.6 / novel 0.5）拉开的档位
# v1.2.1: novel 0.7→0.5——bge 语义强后小说卡（占库26%）顶爆 Top10，压权重让低质卡让位
SOURCE_WEIGHTS = {"book": 1.3, "note": 1.2, "forum": 0.85, "novel": 0.5}


def _source_weight(frontmatter_str: str | None) -> float:
    """按 frontmatter.source_type 取来源权重。

    显式枚举查表；source_type 缺失/未知返回 1.0（不惩罚不奖励，兼容旧数据）。
    注意：不能复用 _source_type()——它对缺失默认 'novel' 会把旧卡误当小说降权。
    """
    try:
        fm = json.loads(frontmatter_str or "{}")
        st = fm.get("source_type")
        if isinstance(st, str) and st in SOURCE_WEIGHTS:
            return SOURCE_WEIGHTS[st]
    except Exception:
        pass
    return 1.0


_TAG_MAPPING_CACHE = None
def _tag_mapping() -> dict:
    """加载标签归一化映射表（evaluation/tags_mapping.json），缓存"""
    global _TAG_MAPPING_CACHE
    if _TAG_MAPPING_CACHE is not None:
        return _TAG_MAPPING_CACHE
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, "evaluation", "tags_mapping.json"), encoding="utf-8") as f:
            _TAG_MAPPING_CACHE = json.load(f)
    except Exception:
        _TAG_MAPPING_CACHE = {}
    return _TAG_MAPPING_CACHE


def _normalized_tags_for_query(query: str) -> list[str]:
    """query 词 → 规范标签：命中映射的别名则展开为规范标签，用于标签召回路"""
    import re
    mapping = _tag_mapping()
    if not mapping:
        return []
    # query 拆词（空白/逗号/顿号）
    terms = re.split(r"[\s,，、]+", query.strip())
    terms = [t for t in terms if t]
    norm = set()
    for t in terms:
        # 直接命中别名 → 规范标签
        if t in mapping:
            norm.add(mapping[t])
        # 反向：query 词是规范标签
        elif t in mapping.values():
            norm.add(t)
        # 模糊：query 词是规范标签的子串
        for src, dst in mapping.items():
            if dst == t or (t in dst) or (dst in t):
                norm.add(dst)
    return list(norm)


def add_user_feedback(note_id: int, vote: int) -> float:
    """质量反馈：vote=+1 有用 / -1 无用 / 0 重置。每票 ±0.05，累计 cap ±0.15。

    只写 frontmatter.user_feedback（影响排序），不动 is_low_confidence（影响召回）。
    返回更新后的 user_feedback 值。
    """
    if vote not in (-1, 0, 1):
        raise ValueError("vote 必须是 -1/0/1")
    import sqlite3
    from db import get_conn

    conn = get_conn()
    row = conn.execute(
        "SELECT frontmatter FROM learning_notes WHERE id=? AND deleted_at IS NULL",
        (note_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"笔记不存在: {note_id}")

    fm = {}
    try:
        fm = json.loads(row["frontmatter"] or "{}")
    except Exception:
        pass
    cur = float(fm.get("user_feedback", 0.0))
    new_val = 0.0 if vote == 0 else round(max(-0.15, min(0.15, cur + vote * 0.05)), 2)
    fm["user_feedback"] = new_val
    conn.execute(
        "UPDATE learning_notes SET frontmatter=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (json.dumps(fm, ensure_ascii=False), note_id),
    )
    conn.commit()
    return new_val