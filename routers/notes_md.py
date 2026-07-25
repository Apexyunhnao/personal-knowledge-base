"""Markdown 导入导出路由"""
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import PlainTextResponse
from repositories import note_repo

router = APIRouter(prefix="/db/notes", tags=["Markdown"])


@router.get("/{note_id}/export")
async def export_note(note_id: int):
    md = note_repo.export_markdown(note_id)
    if not md:
        return {"ok": False, "error": "笔记不存在"}
    return PlainTextResponse(md, media_type="text/markdown")


@router.post("/import")
async def import_note(file: UploadFile = File(...)):
    try:
        content = (await file.read()).decode("utf-8")
        data = note_repo.import_markdown(content)
        if not data.get("title"):
            data["title"] = file.filename.replace(".md", "")
        note_id = note_repo.create(data)
        return {"ok": True, "id": note_id, "title": data.get("title")}
    except Exception as e:
        return {"ok": False, "error": str(e)}
