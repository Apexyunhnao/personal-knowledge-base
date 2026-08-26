#!/usr/bin/env python3
"""
知识库 MCP Server — rag-qa 外部大脑接入 Hermes
暴露工具: kb_search / kb_get / kb_save / kb_stats / kb_random

坑位备忘（详见 skill building-mcp-servers）:
- protocolVersion 原样返回客户端请求的版本
- 通知消息（无 id）不响应
- id 不能为 None
- inputSchema 必须含 type:object
- 日志走 stderr，stdout 只走 JSON-RPC 协议
"""
import sys
import os
import json
import logging

# 保证从任意 cwd 启动都能 import 项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("kb-mcp")

import personal_db
from hybrid_search import hybrid_search

NOTE_TOPICS = personal_db.NOTE_TOPICS


def _err(msg):
    return {"error": str(msg)}


def tool_search(args):
    query = (args.get("query") or "").strip()
    if not query:
        return _err("query 不能为空")
    top_k = int(args.get("top_k", 10))
    top_k = max(1, min(top_k, 50))
    include_low = bool(args.get("include_low_confidence", False))
    try:
        results = hybrid_search(query, top_k=top_k, include_low_confidence=include_low)
        return {"count": len(results), "results": results}
    except Exception as e:
        logger.exception("kb_search 失败")
        return _err(f"检索失败: {e}")


def tool_get(args):
    note_id = args.get("note_id")
    if note_id is None:
        return _err("note_id 必填")
    try:
        note = personal_db._get("notes", int(note_id))
        if note is None:
            return _err(f"笔记 #{note_id} 不存在")
        return note
    except Exception as e:
        logger.exception("kb_get 失败")
        return _err(f"读取失败: {e}")


def tool_save(args):
    title = (args.get("title") or "").strip()
    content = args.get("content") or ""
    if not title:
        return _err("title 必填")
    # tags 兼容字符串("a,b")和数组(["a","b"])
    tags = args.get("tags") or ""
    if isinstance(tags, list):
        tags = ",".join(str(t) for t in tags)
    tags = str(tags).strip()
    topic = (args.get("topic") or "其他").strip()
    if topic not in NOTE_TOPICS:
        return _err(f"topic 必须是 {NOTE_TOPICS} 之一，当前是: {topic}")
    data = {"title": title, "content": content, "tags": tags, "topic": topic}
    for k in ("source", "format", "frontmatter"):
        v = args.get(k)
        if v is not None:
            data[k] = v
    try:
        note_id = personal_db._create("notes", data)
        return {"id": note_id, "title": title, "topic": topic}
    except Exception as e:
        logger.exception("kb_save 失败")
        return _err(f"保存失败: {e}")


def tool_stats(args):
    try:
        from db import get_conn
        conn = get_conn()
        total = conn.execute(
            "SELECT COUNT(*) c FROM learning_notes WHERE deleted_at IS NULL"
        ).fetchone()["c"]
        topics = {
            r["topic"]: r["c"]
            for r in conn.execute(
                "SELECT topic, COUNT(*) c FROM learning_notes WHERE deleted_at IS NULL "
                "GROUP BY topic ORDER BY c DESC"
            ).fetchall()
        }
        tag_count = conn.execute("SELECT COUNT(*) c FROM tags").fetchone()["c"]
        deleted = conn.execute(
            "SELECT COUNT(*) c FROM learning_notes WHERE deleted_at IS NOT NULL"
        ).fetchone()["c"]
        vec_count = 0
        try:
            from hybrid_search import _get_notes_collection
            vec_count = _get_notes_collection().count()
        except Exception:
            pass
        return {
            "total_notes": total,
            "deleted": deleted,
            "by_topic": topics,
            "total_tags": tag_count,
            "vector_count": vec_count,
            "note_topics": NOTE_TOPICS,
        }
    except Exception as e:
        logger.exception("kb_stats 失败")
        return _err(f"统计失败: {e}")


def tool_random(args):
    limit = int(args.get("limit", 3))
    limit = max(1, min(limit, 10))
    try:
        from db import get_conn
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, title, topic FROM learning_notes WHERE deleted_at IS NULL "
            "ORDER BY RANDOM() LIMIT ?",
            (limit,),
        ).fetchall()
        return {"notes": [dict(r) for r in rows]}
    except Exception as e:
        logger.exception("kb_random 失败")
        return _err(f"随机读取失败: {e}")


TOOLS = [
    {
        "name": "kb_search",
        "description": (
            "混合检索知识库（FTS5关键词+语义向量双路RRF融合，含标签加权）。"
            "返回笔记 id/title/topic/tags/score/source，不含正文；要读正文用 kb_get。"
            "用前可先 kb_stats 看库规模。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词或问题"},
                "top_k": {"type": "integer", "description": "返回条数，默认10，最大50"},
                "include_low_confidence": {
                    "type": "boolean",
                    "description": "是否包含低置信度笔记（小说萃取卡默认过滤），默认false",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "kb_get",
        "description": "按 id 读取笔记完整内容（含正文 content、标签 tag_list、frontmatter、反向链接 backlinks）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "笔记 id（kb_search/kb_random 返回的 id）"}
            },
            "required": ["note_id"],
        },
    },
    {
        "name": "kb_save",
        "description": (
            "写入新笔记到知识库（自动同步向量索引，保存后即可被检索）。"
            "tags 传逗号分隔字符串或数组；topic 必须是合法枚举之一（见 kb_stats 的 note_topics）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "笔记标题"},
                "content": {"type": "string", "description": "笔记正文（Markdown）"},
                "tags": {"type": "string", "description": "逗号分隔标签，如 'AI,面试'"},
                "topic": {"type": "string", "description": "主题分类，默认'其他'，枚举见 kb_stats"},
                "source": {"type": "string", "description": "来源（可选）"},
                "format": {"type": "string", "description": "格式（可选）"},
                "frontmatter": {"type": "string", "description": "前置元数据 YAML（可选）"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "kb_stats",
        "description": "知识库统计：总笔记数、按主题分布、标签数、向量数、合法 topic 枚举。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_random",
        "description": "随机抽 N 条笔记（id+title+topic），用于复习/回顾。要读正文用 kb_get。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "抽取条数，默认3，最大10"}
            },
        },
    },
]


def handle(method, params):
    if method == "initialize":
        return {
            "protocolVersion": (params or {}).get("protocolVersion", "2024-11-05"),
            "serverInfo": {"name": "kb", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        handler = {
            "kb_search": tool_search,
            "kb_get": tool_get,
            "kb_save": tool_save,
            "kb_stats": tool_stats,
            "kb_random": tool_random,
        }.get(name)
        if handler is None:
            return {
                "content": [{"type": "text", "text": json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)}],
                "isError": True,
            }
        result = handler(args)
        is_err = isinstance(result, dict) and "error" in result
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": is_err,
        }
    if method == "notifications/initialized":
        return None  # 通知不响应（外层已拦截无 id 的消息，这里兜底）
    return {"error": f"未知方法: {method}"}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            logger.error("JSON 解析失败: %s", e)
            continue
        if "id" not in req:
            # 通知消息（如 notifications/initialized），不响应
            continue
        rid = req.get("id", "")
        try:
            result = handle(req.get("method", ""), req.get("params", {}))
            if result is None:
                continue
            resp = {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as e:
            logger.exception("处理 %s 异常", req.get("method"))
            resp = {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32603, "message": str(e)},
            }
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
