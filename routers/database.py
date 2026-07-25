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
async def db_search_hybrid(keyword: str, top_k: int = 10):
    """混合检索：FTS5关键词 + ChromaDB语义 双路RRF融合"""
    from hybrid_search import hybrid_search
    results = hybrid_search(keyword, top_k)
    return {"ok": True, "keyword": keyword, "count": len(results), "data": results}


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
