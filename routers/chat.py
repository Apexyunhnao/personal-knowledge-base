"""
DeepSeek 聊天端点 — function calling + 文件上传 + Qwen 图片识别
POST /chat → SSE 流式（支持 JSON 和 FormData）
"""
import json, logging, os, base64, tempfile, pymupdf
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from openai import OpenAI
from dotenv import load_dotenv
from repositories import project_repo, application_repo, note_repo

logger = logging.getLogger(__name__)

load_dotenv()
router = APIRouter()

deepseek = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
qwen = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

TOOLS = [
    {"type":"function","function":{"name":"save_note","description":"整理归纳后存入知识库。需提炼要点、给标题和分类。","parameters":{"type":"object","properties":{"title":{"type":"string","description":"精炼标题，概括核心内容"},"content":{"type":"string","description":"整理后的知识内容：提炼要点、去除冗余、结构化呈现"},"topic":{"type":"string","enum":["Python","数据库","前端","AI/ML","系统设计","工具","面试","其他"],"description":"分类：Python/数据库/前端/AI·ML/系统设计/工具/面试/其他"},"tags":{"type":"string","description":"逗号分隔标签"}},"required":["title","content","topic"]}}},
    {"type":"function","function":{"name":"search_knowledge","description":"搜索知识库（全文+关键词）","parameters":{"type":"object","properties":{"keyword":{"type":"string","description":"搜索关键词"}},"required":["keyword"]}}},
    {"type":"function","function":{"name":"list_items","description":"列出最近的知识条目","parameters":{"type":"object","properties":{"table":{"type":"string","enum":["notes"]},"limit":{"type":"integer"}},"required":["table"]}}},
    {"type":"function","function":{"name":"get_item","description":"查看某条知识的完整内容","parameters":{"type":"object","properties":{"table":{"type":"string","enum":["notes"]},"item_id":{"type":"integer"}},"required":["table","item_id"]}}},
    {"type":"function","function":{"name":"update_item","description":"修改知识条目","parameters":{"type":"object","properties":{"table":{"type":"string","enum":["notes"]},"item_id":{"type":"integer"},"changes":{"type":"object"}},"required":["table","item_id","changes"]}}},
    {"type":"function","function":{"name":"delete_item","description":"删除知识条目（软删除，可恢复）","parameters":{"type":"object","properties":{"table":{"type":"string","enum":["notes"]},"item_id":{"type":"integer"}},"required":["table","item_id"]}}},
    {"type":"function","function":{"name":"get_stats","description":"知识库统计","parameters":{"type":"object","properties":{}}}},
]

SYSTEM_PROMPT = """你是「知识库助手」，帮助用户管理个人知识。

## 核心工作流
1. 用户发来文字 → **先 search_knowledge 检查是否有相关已有知识**：
   - 如果有高度相关的已有条目 → 用 update_item 将新内容合并进去（追加或融合，不覆盖），同时更新 tags
   - 如果没有相关条目 → 新建 save_note
2. 整理归纳：提炼核心观点、去除冗余、结构化呈现
3. 用户提问 → 先搜索知识库 → 基于知识库内容回答
4. 用户可以要求增删改查知识库中的条目

## 合并原则（重要）
- 存新知识前必须先搜索，判断是否和已有知识属于同一主题
- 同一主题的内容应合并为一条结构化文档，标题应概括整体主题
- 合并时用 update_item 追加内容，保持结构清晰（用小标题分隔不同子话题）
- 不要为同一个主题的不同讨论创建多条独立条目

## 整理归纳原则
- 给每条知识一个精炼的标题（5-15字）
- 内容要结构化：用分点、分段呈现，而不是原文照搬
- 给 topic 分类：Python/数据库/前端/AI·ML/系统设计/工具/面试/其他
- 给 tags 标签：逗号分隔的关键词，方便后续检索
- 如果用户内容很短（一两句话），也做整理归纳，给标题

## 回答原则
- 先搜索知识库，基于已有知识回答
- 如果搜索无结果，可以结合常识回答但要说明「知识库中暂无相关内容」
- 回答简洁，引用知识条目的标题

## 操作
存→save_note  搜→search_knowledge  列→list_items(table='notes')
看→get_item(table='notes',item_id=N)  改→update_item  删→delete_item

回复用中文，知识条目中复杂代码片段用 Markdown 代码块。用户上传的文件内容已在消息中。"""

def build_catalog_prompt():
    """动态生成当前知识库目录，注入到 system prompt"""
    try:
        from db import get_conn
        c = get_conn()
        rows = c.execute(
            "SELECT id, title, topic FROM learning_notes WHERE deleted_at IS NULL ORDER BY topic, id"
        ).fetchall()
        if not rows:
            return SYSTEM_PROMPT
        lines = [f"#{r[0]} [{r[2]}] {r[1]}" for r in rows]
        catalog = "\n当前知识库目录：\n" + "\n".join(lines)
        catalog += "\n\n⚠ 存新知识前必须检查上述目录：同一主题的内容合并到已有条目（用 update_item），切勿新建重复条目。\n"
        return SYSTEM_PROMPT + catalog
    except:
        return SYSTEM_PROMPT

REPOS = {"projects":project_repo,"applications":application_repo,"notes":note_repo}
IMAGE_EXT = {'.png','.jpg','.jpeg','.gif','.webp','.bmp'}

# ── 文件处理 ──

def extract_doc(filepath, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.pdf':
        try:
            doc = pymupdf.open(filepath)
            text = "\n".join([p.get_text() for p in doc]); doc.close()
            return text.strip()
        except Exception as e: return f"[PDF解析失败:{e}]"
    try:
        with open(filepath,'r',encoding='utf-8') as f: return f.read().strip()
    except:
        try:
            with open(filepath,'r',encoding='gbk') as f: return f.read().strip()
        except: return f"[无法读取:{ext}]"

def describe_image(filepath):
    try:
        with open(filepath,'rb') as f: b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(filepath)[1].lower().replace('.','')
        mime = f"image/{'jpeg' if ext=='jpg' else ext}"
        r = qwen.chat.completions.create(model="qwen-vl-plus", messages=[{"role":"user","content":[
            {"type":"image_url","image_url":{"url":f"data:{mime};base64,{b64}"}},
            {"type":"text","text":"请详细描述这张图片。文字截图提取文字，图表解释含义，代码解释逻辑。"}
        ]}], max_tokens=2000)
        return r.choices[0].message.content.strip()
    except Exception as e: return f"[图片识别失败:{e}]"

async def process_files(files):
    if not files: return ""
    parts = []
    for f in files:
        suf = os.path.splitext(f.filename)[1] or ".tmp"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
            tmp.write(await f.read()); tmppath = tmp.name
        try:
            fn = f.filename or "unknown"
            if os.path.splitext(fn)[1].lower() in IMAGE_EXT:
                parts.append(f"[图片:{fn}]\nQwen识别:\n{describe_image(tmppath)}")
            else:
                text = extract_doc(tmppath, fn)
                if len(text) > 8000: text = text[:8000] + "\n...(截断)"
                parts.append(f"[文档:{fn}]\n{text}")
        finally:
            try: os.unlink(tmppath)
            except: pass
    return "\n\n---\n\n".join(parts)

# ── 工具执行 ──

def execute_tool(name, args):
    try:
        if name == "save_note":
            nid = note_repo.create({"title":args["title"],"content":args.get("content",""),"topic":args.get("topic"),"tags":args.get("tags",""),"format":"markdown"})
            return json.dumps({"ok":True,"id":nid,"title":args["title"]},ensure_ascii=False)
        elif name == "search_knowledge":
            from hybrid_search import hybrid_search
            kw = args["keyword"]
            results = hybrid_search(kw)
            # 按来源分组（保持与旧格式兼容）
            grouped = {"笔记": [{"id": r["id"], "title": r["title"]} for r in results]}
            return json.dumps({"ok": True, "keyword": kw, "results": grouped, "method": "hybrid"}, ensure_ascii=False)
        elif name == "list_items":
            items = REPOS[args["table"]].list(limit=args.get("limit",20))
            simp = []
            for i in items:
                s = {"id":i["id"]}
                for k in ["title","name","company","topic","tech_stack","position","status","tags"]:
                    if k in i: s[k] = i[k]
                simp.append(s)
            return json.dumps({"ok":True,"table":args["table"],"count":len(simp),"items":simp},ensure_ascii=False)
        elif name == "get_item":
            item = REPOS[args["table"]].get(args["item_id"])
            return json.dumps({"ok":True,"item":item} if item else {"ok":False,"error":"不存在"},ensure_ascii=False)
        elif name == "update_item":
            REPOS[args["table"]].update(args["item_id"],args["changes"])
            return json.dumps({"ok":True,"updated":args["item_id"]})
        elif name == "delete_item":
            REPOS[args["table"]].delete(args["item_id"])
            return json.dumps({"ok":True,"deleted":args["item_id"]})
        elif name == "get_stats":
            from db import get_conn
            c = get_conn(); stats = {}
            for tbl,short in [("projects","projects"),("job_applications","applications"),("learning_notes","notes")]:
                stats[short] = c.execute(f"SELECT COUNT(*) FROM {tbl} WHERE deleted_at IS NULL").fetchone()[0]
            stats["trash"] = c.execute("SELECT COUNT(*) FROM (SELECT id FROM projects WHERE deleted_at IS NOT NULL UNION ALL SELECT id FROM job_applications WHERE deleted_at IS NOT NULL UNION ALL SELECT id FROM learning_notes WHERE deleted_at IS NOT NULL)").fetchone()[0]
            stats["tags"] = c.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
            return json.dumps({"ok":True,"stats":stats},ensure_ascii=False)
        return json.dumps({"ok":False,"error":f"未知:{name}"})
    except Exception as e:
        return json.dumps({"ok":False,"error":str(e)},ensure_ascii=False)

# ── 核心流式 ──

async def _chat_stream(message, history, file_context):
    try:
        async for chunk in _chat_stream_inner(message, history, file_context):
            yield chunk
    except Exception as e:
        err = json.dumps({"type":"text","content":"服务端错误: "+str(e)})
        yield "data: " + err + "\n\n"
        yield "data: " + json.dumps({"type":"done"}) + "\n\n"

async def _chat_stream_inner(message, history, file_context):
    if not message and not file_context:
        yield f"data: {json.dumps({'type':'done'})}\n\n"; return
    if file_context and message:
        fm = f"[用户上传了以下文件]\n\n{file_context}\n\n---\n\n用户消息: {message}"
    elif file_context:
        fm = f"[用户上传了以下文件]\n\n{file_context}\n\n请帮我处理这些文件的内容。"
    else:
        fm = message
    msgs = [{"role":"system","content":build_catalog_prompt()}]
    seen_tool_ids = set()
    for h in history[-20:]:
        m = {"role": h["role"], "content": h.get("content", "")}
        if h.get("tool_call_id"):
            m["tool_call_id"] = h["tool_call_id"]
            seen_tool_ids.add(h["tool_call_id"])
        if h.get("tool_calls"):
            tcs = []
            for tc in h["tool_calls"]:
                tc_copy = dict(tc)
                if "type" not in tc_copy: tc_copy["type"] = "function"
                if tc_copy.get("id"): seen_tool_ids.add(tc_copy["id"])
                tcs.append(tc_copy)
            m["tool_calls"] = tcs
        msgs.append(m)
    # 清理不完整的 assistant tool_calls：如果 assistant 发了 tool_call 但后面没有 tool 响应，删掉该 tool_call
    pending_tool_ids = set()
    cleaned_msgs = []
    for m in reversed(msgs):
        if m["role"] == "tool" and m.get("tool_call_id"):
            pending_tool_ids.add(m["tool_call_id"])
            cleaned_msgs.append(m)
        elif m["role"] == "assistant" and m.get("tool_calls"):
            # 只保留有对应 tool 响应的 tool_call
            valid_tcs = [tc for tc in m["tool_calls"] if tc.get("id") in pending_tool_ids]
            for tc in m["tool_calls"]:
                pending_tool_ids.discard(tc.get("id", ""))
            if valid_tcs:
                m["tool_calls"] = valid_tcs
                cleaned_msgs.append(m)
            # 如果所有 tool_call 都没有对应响应，整条 assistant 消息丢弃
        else:
            cleaned_msgs.append(m)
    msgs = list(reversed(cleaned_msgs))
    msgs.append({"role":"user","content":fm})
    if file_context: yield f"data: {json.dumps({'type':'file_info'})}\n\n"
    for _ in range(5):
        stream = deepseek.chat.completions.create(model="deepseek-chat",messages=msgs,tools=TOOLS,tool_choice="auto",temperature=0.3,stream=True)
        cc = ""; tcs = []
        for chunk in stream:
            d = chunk.choices[0].delta
            if d.content: cc += d.content; yield f"data: {json.dumps({'type':'text','content':d.content})}\n\n"
            if d.tool_calls:
                for tc in d.tool_calls:
                    while len(tcs) <= tc.index: tcs.append({"id":"","type":"function","function":{"name":"","arguments":""}})
                    if tc.id: tcs[tc.index]["id"] = tc.id
                    if tc.function:
                        if tc.function.name: tcs[tc.index]["function"]["name"] = tc.function.name
                        if tc.function.arguments: tcs[tc.index]["function"]["arguments"] += tc.function.arguments
        if not tcs: yield f"data: {json.dumps({'type':'done'})}\n\n"; return
        for tc2 in tcs:
            if tc2["id"] in seen_tool_ids: tc2["id"] = f"{tc2['id']}_{_}"
        msgs.append({"role":"assistant","content":cc,"tool_calls":tcs})
        for tc in tcs:
            fn = tc["function"]["name"]
            try: fa = json.loads(tc["function"]["arguments"])
            except: fa = {}
            yield f"data: {json.dumps({'type':'tool_start','name':fn,'args':fa})}\n\n"
            res = execute_tool(fn, fa)
            yield f"data: {json.dumps({'type':'tool_result','name':fn,'result':res})}\n\n"
            tid = tc["id"]
            if tid in seen_tool_ids: tid = f"{tid}_{_}"
            seen_tool_ids.add(tid)
            msgs.append({"role":"tool","tool_call_id":tid,"content":res})
    yield f"data: {json.dumps({'type':'done'})}\n\n"

# ── 端点 ──

@router.post("/chat")
async def chat(request: Request):
    ct = request.headers.get("content-type","")
    if "application/json" in ct:
        body = await request.json()
        msg = body.get("message","").strip()
        hist = body.get("history",[])
        fc = ""
    else:
        form = await request.form()
        msg = (form.get("message","") or "").strip()
        hs = form.get("history","[]")
        try: hist = json.loads(hs) if isinstance(hs,str) else hs
        except: hist = []
        fc = ""
        flist = form.getlist("files") if hasattr(form,"getlist") else [v for k,v in form.multi_items() if k=="files"]
        if flist: fc = await process_files(flist)
    return StreamingResponse(_chat_stream(msg, hist, fc), media_type="text/event-stream")
