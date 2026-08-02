"""监控反馈环 — Q&A日志 + 反馈收集 + Bad Case分析"""
import json
import logging
from fastapi import APIRouter, Request
from db import get_conn

router = APIRouter()
logger = logging.getLogger(__name__)


# ── 初始化监控表（幂等）──
def _init_monitor():
    c = get_conn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS qa_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT DEFAULT '',
            question TEXT NOT NULL,
            answer TEXT,
            retrieved_chunks TEXT DEFAULT '[]',
            model TEXT DEFAULT 'deepseek-v4-pro',
            latency_ms INTEGER DEFAULT 0,
            feedback INTEGER DEFAULT NULL,
            feedback_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.commit()
    c.close()


_init_monitor()


# ═══════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════

@router.post("/monitor/log")
async def log_qa(request: Request):
    """记录一次问答（前端在收到完整回答后调用）"""
    body = await request.json()
    c = get_conn()
    cur = c.execute(
        """INSERT INTO qa_logs 
           (session_id, question, answer, retrieved_chunks, model, latency_ms) 
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            body.get("session_id", ""),
            body["question"],
            body.get("answer", ""),
            json.dumps(body.get("retrieved_chunks", []), ensure_ascii=False),
            body.get("model", "deepseek-v4-pro"),
            body.get("latency_ms", 0),
        ),
    )
    log_id = cur.lastrowid
    c.commit()
    c.close()
    return {"ok": True, "id": log_id}


@router.post("/monitor/feedback")
async def submit_feedback(request: Request):
    """提交反馈：1=有帮助，-1=没帮助"""
    body = await request.json()
    c = get_conn()
    c.execute(
        "UPDATE qa_logs SET feedback = ?, feedback_at = CURRENT_TIMESTAMP WHERE id = ?",
        (body["feedback"], body["id"]),
    )
    c.commit()
    c.close()
    return {"ok": True}


@router.get("/monitor/bad-cases")
async def bad_cases(limit: int = 20):
    """列出所有「没帮助」的问答（按时间倒序）"""
    c = get_conn()
    rows = c.execute(
        """SELECT id, question, answer, feedback, latency_ms, created_at 
           FROM qa_logs WHERE feedback = -1 
           ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    c.close()
    return {"ok": True, "data": [dict(r) for r in rows]}


@router.get("/monitor/stats")
async def monitor_stats():
    """监控面板统计数据"""
    c = get_conn()
    total = c.execute("SELECT COUNT(*) FROM qa_logs").fetchone()[0]
    helpful = c.execute("SELECT COUNT(*) FROM qa_logs WHERE feedback = 1").fetchone()[0]
    not_helpful = c.execute("SELECT COUNT(*) FROM qa_logs WHERE feedback = -1").fetchone()[0]
    avg_latency = c.execute("SELECT AVG(latency_ms) FROM qa_logs WHERE latency_ms > 0").fetchone()[0] or 0
    c.close()
    return {
        "ok": True,
        "data": {
            "total": total,
            "helpful": helpful,
            "not_helpful": not_helpful,
            "avg_latency_ms": round(avg_latency, 1),
            "no_feedback": total - helpful - not_helpful,
        },
    }
