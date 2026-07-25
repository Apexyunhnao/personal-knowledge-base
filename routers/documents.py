"""附件路由"""
from fastapi import APIRouter, UploadFile, File, Form
from repositories import doc_repo

router = APIRouter(prefix="/db", tags=["附件"])


@router.post("/{table}/{item_id}/documents")
async def upload(table: str, item_id: int, file: UploadFile = File(...), doc_type: str = Form("其他")):
    try:
        content = await file.read()
        doc_id = doc_repo.upload(table, item_id, doc_type, file.filename, content)
        return {"ok": True, "id": doc_id, "filename": file.filename}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/{table}/{item_id}/documents")
async def list_docs(table: str, item_id: int):
    return {"ok": True, "data": doc_repo.list_for(table, item_id)}


@router.delete("/documents/{doc_id}")
async def delete_doc(doc_id: int):
    try:
        doc_repo.delete(doc_id)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
