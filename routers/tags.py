"""标签路由"""
from fastapi import APIRouter, Form
from repositories import tag_repo

router = APIRouter(prefix="/db/tags", tags=["标签"])


@router.get("")
async def list_tags():
    return {"ok": True, "data": tag_repo.list_all()}


@router.put("/{tag_id}")
async def rename_tag(tag_id: int, name: str = Form(...)):
    try:
        tag_repo.rename(tag_id, name)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.delete("/{tag_id}")
async def delete_tag(tag_id: int):
    try:
        tag_repo.delete(tag_id)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
