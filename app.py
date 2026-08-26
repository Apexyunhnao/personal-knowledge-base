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
    """启动时校验向量索引；不一致才重建（幂等启动）。

    原来无条件全量重建 19000+ 条，text2vec CPU 计算要 10-30 分钟，每次重启都白等。
    向量数 == 笔记数时跳过；不匹配（新增/删库/半截重建）才重建。
    """
    try:
        from hybrid_search import build_all_embeddings, _get_notes_collection
        import sqlite3
        from db import get_conn
        conn = get_conn()
        note_count = conn.execute(
            "SELECT COUNT(*) FROM learning_notes WHERE deleted_at IS NULL"
        ).fetchone()[0]
        vec_count = _get_notes_collection().count()
        if vec_count == note_count:
            print(f"✅ 向量索引一致 ({vec_count} == {note_count})，跳过重建")
            return
        print(f"⚠️ 向量数({vec_count}) != 笔记数({note_count})，开始重建...")
        build_all_embeddings()
    except Exception as e:
        # 首次启动 chroma_db 为空时静默；其他错误必须暴露
        import os
        if os.path.exists("chroma_db") and os.listdir("chroma_db"):
            print(f"⚠️ 向量重建失败: {e}")
        else:
            pass


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


@app.get("/vision", response_class=HTMLResponse)
async def vision_demo():
    """视觉识别 — 拍照 → Qwen-VL 识别 → 知识库检索"""
    import os as _os
    template_path = _os.path.join(_os.path.dirname(__file__), "templates", "vision-demo.html")
    if _os.path.exists(template_path):
        with open(template_path) as f:
            return f.read()
    return "<h1>视觉识别</h1><p>模板文件缺失</p>"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
