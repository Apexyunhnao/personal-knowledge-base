"""MCP Server — 让 AI Agent 直接操作个人资料库

实现 Model Context Protocol 的 tools/list 和 tools/call 接口。
暴露知识库的搜索、创建、查询等能力给 Claude/Cursor 等 AI 工具。
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from repositories import (
    project_repo, application_repo, note_repo,
    tag_repo, search_repo, stats_repo, backup_repo, trash_repo
)
from personal_db import get_graph_data, get_backlinks
import json

mcp_app = FastAPI(title="个人资料库 MCP Server")

# ── 工具定义 ──

TOOLS = [
    {
        "name": "search_knowledge",
        "description": "全文搜索个人资料库（项目、求职、笔记）。支持中文。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "create_note",
        "description": "创建一条学习笔记",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "笔记标题"},
                "content": {"type": "string", "description": "笔记内容（支持 Markdown 和 [[WikiLink]]）"},
                "topic": {"type": "string", "description": "主题：数据库/Python/前端/AI/ML/面试/系统设计/工具/其他"},
                "tags": {"type": "string", "description": "标签，逗号分隔"}
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "get_note",
        "description": "获取单条笔记的完整内容",
        "inputSchema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "笔记ID"}
            },
            "required": ["note_id"]
        }
    },
    {
        "name": "list_notes",
        "description": "列出最近的学习笔记",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量，默认20"},
                "topic": {"type": "string", "description": "按主题过滤"}
            }
        }
    },
    {
        "name": "create_project",
        "description": "添加项目经历",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "项目名称"},
                "tech_stack": {"type": "string", "description": "技术栈"},
                "description": {"type": "string", "description": "项目描述"},
                "github_url": {"type": "string", "description": "GitHub地址"},
                "category": {"type": "string", "description": "分类：个人项目/实习项目/课程项目/开源贡献"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "query_jobs",
        "description": "查询求职记录",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "按状态过滤：已投递/筛选中/面试/笔试/offer/已拒/已接受"},
                "limit": {"type": "integer", "description": "返回数量，默认20"}
            }
        }
    },
    {
        "name": "get_stats",
        "description": "获取资料库统计信息",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_graph",
        "description": "获取知识图谱数据（节点和边），用于可视化知识关联",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_backlinks",
        "description": "获取某条笔记的反向链接（哪些笔记引用了它）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "笔记ID"}
            },
            "required": ["note_id"]
        }
    },
]


# ── MCP 协议端点 ──

@mcp_app.get("/")
async def mcp_info():
    return {
        "protocol": "mcp",
        "version": "1.0",
        "name": "个人资料库",
        "tools_count": len(TOOLS),
        "endpoints": {
            "tools/list": "GET /tools/list",
            "tools/call": "POST /tools/call",
        }
    }


@mcp_app.get("/tools/list")
async def tools_list():
    return {"tools": TOOLS}


@mcp_app.post("/tools/call")
async def tools_call(request: Request):
    """调用工具"""
    body = await request.json()
    tool_name = body.get("name", "")
    arguments = body.get("arguments", {})
    
    try:
        result = _execute_tool(tool_name, arguments)
        return {
            "content": [
                {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
            ]
        }
    except Exception as e:
        return {
            "content": [
                {"type": "text", "text": f"错误: {str(e)}"}
            ],
            "isError": True
        }


def _execute_tool(name: str, args: dict):
    """执行具体工具"""
    if name == "search_knowledge":
        return search_repo.search(args["query"])
    
    elif name == "create_note":
        note_id = note_repo.create({
            "title": args["title"],
            "content": args.get("content", ""),
            "topic": args.get("topic", ""),
            "tags": args.get("tags", ""),
            "format": "markdown",
        })
        return {"id": note_id, "title": args["title"]}
    
    elif name == "get_note":
        note = note_repo.get(args["note_id"])
        return note if note else {"error": "笔记不存在"}
    
    elif name == "list_notes":
        return note_repo.list(limit=args.get("limit", 20))
    
    elif name == "create_project":
        pid = project_repo.create({
            "name": args["name"],
            "tech_stack": args.get("tech_stack", ""),
            "description": args.get("description", ""),
            "github_url": args.get("github_url", ""),
            "category": args.get("category", "个人项目"),
        })
        return {"id": pid, "name": args["name"]}
    
    elif name == "query_jobs":
        jobs = application_repo.list(limit=args.get("limit", 20))
        if args.get("status"):
            jobs = [j for j in jobs if j.get("status") == args["status"]]
        return jobs
    
    elif name == "get_stats":
        return stats_repo.get()
    
    elif name == "get_graph":
        return get_graph_data()
    
    elif name == "get_backlinks":
        note = note_repo.get(args["note_id"])
        if note:
            return {
                "note": note["title"],
                "backlinks": get_backlinks("learning_notes", args["note_id"])
            }
        return {"error": "笔记不存在"}
    
    else:
        raise ValueError(f"未知工具: {name}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(mcp_app, host="0.0.0.0", port=8001)
