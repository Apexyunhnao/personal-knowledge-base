"""备份路由"""
from fastapi import APIRouter
from repositories import backup_repo

router = APIRouter(prefix="/db", tags=["备份"])


@router.post("/backup")
async def create_backup():
    try:
        result = backup_repo.create()
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/backups")
async def list_backups():
    return {"ok": True, "data": backup_repo.list()}


@router.post("/restore/{filename}")
async def restore_backup(filename: str):
    try:
        backup_repo.restore(filename)
        return {"ok": True, "message": f"已从 {filename} 恢复"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
