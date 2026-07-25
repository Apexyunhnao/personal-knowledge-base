"""双向链接 + 知识图谱路由"""
from fastapi import APIRouter
from personal_db import get_backlinks, get_forward_links, get_graph_data

router = APIRouter(prefix="/db", tags=["链接"])


@router.get("/{table}/{item_id}/backlinks")
async def item_backlinks(table: str, item_id: int):
    """获取指向当前条目的反向链接"""
    return {"ok": True, "data": get_backlinks(table, item_id)}


@router.get("/{table}/{item_id}/links")
async def item_links(table: str, item_id: int):
    """获取当前条目指向的链接"""
    return {"ok": True, "data": get_forward_links(table, item_id)}


@router.get("/graph")
async def knowledge_graph():
    """知识图谱数据（节点+边）"""
    return {"ok": True, "data": get_graph_data()}
