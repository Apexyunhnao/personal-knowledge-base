"""回收站路由"""
from fastapi import APIRouter
from repositories import trash_repo, project_repo, application_repo, note_repo

router = APIRouter(prefix="/db/trash", tags=["回收站"])

REPOS = {"projects": project_repo, "applications": application_repo, "notes": note_repo}


@router.get("")
async def trash_list():
    return {"ok": True, "data": trash_repo.list(), "count": trash_repo.count()}


@router.post("/{table}/{item_id}/restore")
async def trash_restore(table: str, item_id: int):
    if table not in REPOS:
        return {"ok": False, "error": f"不支持的表: {table}"}
    try:
        trash_repo.restore(table, item_id)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.delete("/{table}/{item_id}")
async def trash_permanent_delete(table: str, item_id: int):
    if table not in REPOS:
        return {"ok": False, "error": f"不支持的表: {table}"}
    try:
        REPOS[table].permanent_delete(item_id)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/empty")
async def trash_empty():
    try:
        trash_repo.empty()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
