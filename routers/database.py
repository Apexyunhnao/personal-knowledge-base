"""资料库 CRUD 路由"""
from fastapi import APIRouter, Body
from repositories import project_repo, application_repo, note_repo

router = APIRouter(prefix="/db", tags=["资料库"])

TABLES = {
    "projects": project_repo,
    "applications": application_repo,
    "notes": note_repo,
}
TABLE_NAMES = {"projects": "项目经历", "applications": "求职记录", "notes": "学习笔记"}


@router.get("/stats")
async def db_stats():
    from repositories import stats_repo
    return stats_repo.get()


@router.get("/search")
async def db_search(keyword: str):
    from repositories import search_repo
    return search_repo.search(keyword)


@router.get("/search-hybrid")
async def db_search_hybrid(keyword: str, top_k: int = 10, include_low_confidence: bool = False):
    """混合检索：FTS5关键词 + ChromaDB语义 双路RRF融合。
    include_low_confidence=True 时包含低置信度小说卡（默认过滤）"""
    from hybrid_search import hybrid_search
    results = hybrid_search(keyword, top_k, include_low_confidence)
    return {"ok": True, "keyword": keyword, "count": len(results), "data": results}


@router.post("/notes/{note_id}/feedback")
async def note_feedback(note_id: int, vote: int = Body(..., embed=True, ge=-1, le=1)):
    """质量反馈：vote=+1 有用 / -1 无用 / 0 重置。±0.05/票，cap ±0.15，只影响排序。
    仅小说萃取笔记有效；普通笔记返回 ok 但 user_feedback 保持 0。"""
    from hybrid_search import add_user_feedback
    try:
        val = add_user_feedback(note_id, vote)
        return {"ok": True, "id": note_id, "user_feedback": val}
    except KeyError as e:
        return {"ok": False, "error": str(e)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@router.get("/tags/stats")
async def db_tags_stats(limit: int = 30):
    """核心标签分布（小说萃取卡）：[{tag, count}] 按计数降序"""
    import sqlite3
    from db import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT tags FROM learning_notes WHERE tags LIKE '%小说萃取%' AND deleted_at IS NULL"
    ).fetchall()
    from collections import Counter
    counter = Counter()
    for r in rows:
        tags = [t.strip() for t in (r["tags"] or "").split(",") if t.strip()]
        if len(tags) >= 3:
            for t in tags[2:5]:
                counter[t] += 1
    return {"ok": True, "data": [{"tag": t, "count": c} for t, c in counter.most_common(limit)]}


@router.get("/tags/{tag}/notes")
async def db_tags_notes(tag: str, limit: int = 50):
    """按核心标签查卡：返回该标签下的笔记（id/title/source/tags）"""
    import sqlite3
    from db import get_conn
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, source, tags FROM learning_notes "
        "WHERE tags LIKE ? AND deleted_at IS NULL ORDER BY id DESC LIMIT ?",
        (f"%{tag}%", limit),
    ).fetchall()
    return {"ok": True, "tag": tag, "data": [dict(r) for r in rows]}


@router.get("/random-notes")
async def db_random_notes(limit: int = 3):
    """随机取 N 张小说卡（每日回顾用）"""
    import sqlite3
    from db import get_conn
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, tags, source FROM learning_notes "
        "WHERE tags LIKE '%小说萃取%' AND deleted_at IS NULL "
        "AND frontmatter NOT LIKE '%is_low_confidence\\\": true%' "
        "ORDER BY RANDOM() LIMIT ?",
        (limit,),
    ).fetchall()
    return {"ok": True, "data": [dict(r) for r in rows]}


@router.get("/{table}")
async def db_list(table: str, limit: int = 50, offset: int = 0):
    if table not in TABLES:
        return {"ok": False, "error": f"不支持的表: {table}"}
    return {"ok": True, "data": TABLES[table].list(limit, offset)}


@router.get("/{table}/{item_id}")
async def db_get(table: str, item_id: int):
    if table not in TABLES:
        return {"ok": False, "error": f"不支持的表: {table}"}
    item = TABLES[table].get(item_id)
    if not item:
        return {"ok": False, "error": "不存在"}
    return {"ok": True, "data": item}


@router.post("/{table}")
async def db_create(table: str, data: dict = Body(...)):
    if table not in TABLES:
        return {"ok": False, "error": f"不支持的表: {table}"}
    try:
        item_id = TABLES[table].create(data)
        return {"ok": True, "id": item_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.put("/{table}/{item_id}")
async def db_update(table: str, item_id: int, data: dict = Body(...)):
    if table not in TABLES:
        return {"ok": False, "error": f"不支持的表: {table}"}
    try:
        TABLES[table].update(item_id, data)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.delete("/{table}/{item_id}")
async def db_delete(table: str, item_id: int):
    if table not in TABLES:
        return {"ok": False, "error": f"不支持的表: {table}"}
    try:
        TABLES[table].delete(item_id)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
