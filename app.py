"""个人资料库 — FastAPI 入口（DeepSeek 直连版）"""
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

# ── 路由模块 ──
from routers.database import router as db_router
from routers.tags import router as tags_router
from routers.trash import router as trash_router
from routers.documents import router as docs_router
from routers.backup import router as backup_router
from routers.notes_md import router as notes_md_router
from routers.links import router as links_router
from routers.chat import router as chat_router
from routers.monitor import router as monitor_router
from routers.vision import router as vision_router
from routers.voice import router as voice_router

app = FastAPI(title="个人资料库")

# ── CORS — 本地使用，宽松配置 ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 路由（具体路径必须在泛型 /db/{table} 之前）──
app.include_router(tags_router)       # /db/tags
app.include_router(trash_router)      # /db/trash
app.include_router(backup_router)     # /db/backup, /db/backups
app.include_router(notes_md_router)   # /db/notes/{id}/export
app.include_router(links_router)      # /db/graph, /db/{table}/{id}/backlinks
app.include_router(docs_router)       # /db/{table}/{id}/documents
app.include_router(db_router)         # /db/stats, /db/search, /db/{table}...（最后）
app.include_router(chat_router)       # /chat — DeepSeek 直连
app.include_router(monitor_router)   # /monitor — 监控反馈环
app.include_router(vision_router)   # /vision-search — AR 视觉搜索
app.include_router(voice_router)    # /voice/recognize, /voice/note — 语音识别


@app.on_event("startup")
async def startup_build_embeddings():
    """启动时全量重建向量索引"""
    try:
        from hybrid_search import build_all_embeddings
        build_all_embeddings()
    except Exception:
        pass  # 首次启动chroma_db为空，静默跳过


# ── Web 页面 ──
@app.get("/", response_class=HTMLResponse)
async def index():
    import os as _os
    template_path = _os.path.join(_os.path.dirname(__file__), "templates", "index.html")
    if _os.path.exists(template_path):
        with open(template_path) as f:
            return f.read()
    return "<h1>个人资料库</h1><p>模板文件缺失</p>"


@app.get("/graph", response_class=HTMLResponse)
async def graph_page():
    """知识图谱可视化页面"""
    import os as _os
    template_path = _os.path.join(_os.path.dirname(__file__), "templates", "graph.html")
    if _os.path.exists(template_path):
        with open(template_path) as f:
            return f.read()
    return "<h1>知识图谱</h1><p>模板文件缺失</p>"


@app.get("/ar", response_class=HTMLResponse)
async def ar_demo():
    """AR 知识助手 Demo"""
    import os as _os
    template_path = _os.path.join(_os.path.dirname(__file__), "templates", "ar-demo.html")
    if _os.path.exists(template_path):
        with open(template_path) as f:
            return f.read()
    return "<h1>AR 知识助手</h1><p>模板文件缺失</p>"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
