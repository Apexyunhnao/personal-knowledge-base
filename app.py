"""RAG文档问答 — FastAPI Web服务（多会话隔离）"""
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import StreamingResponse, HTMLResponse
from rag_engine import RAGEngine
import tempfile, os

app = FastAPI(title="RAG文档问答系统")
engine = RAGEngine()

# 清理旧版单collection残留数据
try:
    engine.client.delete_collection("documents")
except Exception:
    pass

# ── API ──

@app.post("/upload")
async def upload(session_id: str = Form(...), file: UploadFile = File(...)):
    """上传文档并摄入到指定会话"""
    suffix = os.path.splitext(file.filename)[1] or ".txt"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.file.write(file.file.read())
        tmp.close()
        count = engine.ingest(session_id, tmp.name)
        return {"ok": True, "filename": file.filename, "chunks": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        os.unlink(tmp.name)


@app.post("/ask")
async def ask(session_id: str = Form(...), question: str = Form(...)):
    """提问"""
    # 非文档问题直接答
    greetings = ["你好", "嗨", "hello", "hi", "你是谁", "你能做什么", "有什么功能", "功能", "能干什么", "可以做什么", "会什么", "自我介绍", "介绍自己", "你是什么"]
    if any(g in question for g in greetings):
        try:
            answer = engine.ask(session_id, question)
            return {"ok": True, "answer": answer}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    if engine.document_count(session_id) == 0:
        return {"ok": False, "error": "请先上传文档"}
    try:
        answer = engine.ask(session_id, question)
        return {"ok": True, "answer": answer}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/ask/stream")
async def ask_stream(session_id: str, question: str):
    """流式提问（SSE）"""
    from openai import OpenAI
    from dotenv import load_dotenv
    load_dotenv()
    
    async def generate():
        # 判断是否为非文档类问题
        greetings = ["你好", "嗨", "hello", "hi", "你是谁", "你能做什么", "有什么功能", "功能", "能干什么", "可以做什么", "会什么", "自我介绍", "介绍自己", "你是什么"]
        is_greeting = any(g in question for g in greetings)
        
        if is_greeting:
            prompt = question
        elif engine.document_count(session_id) == 0:
            yield "data: 请先上传文档，然后我可以帮你分析内容。\n\n"
            yield "data: [DONE]\n\n"
            return
        else:
            # RAG检索
            col = engine._get_collection(session_id)
            doc_count = col.count()
            top_k = doc_count if doc_count <= 20 else 5
            results = col.query(query_texts=[question], n_results=top_k)
            context = "\n\n---\n\n".join(results["documents"][0])
            
            prompt = f"""根据以下文档内容，用你自己的话整理回答，不要照搬原文。

文档内容：
{context}

问题：{question}

要求：
- 用自己的话重新组织，像跟人介绍一样自然
- 如果问多项内容，全部列出不遗漏
- 文档没有的信息如实说"未提及"
"""
        
        llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com"
        )
        
        stream = llm.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是文档问答助手。回答简洁专业。严格禁止使用任何markdown符号：禁止**加粗**、禁止-列表、禁止#标题、禁止`代码块`、禁止*斜体*。回答必须是纯文本，用换行和空格分隔。\n- 自我介绍：一句话\n- 评价简历：只列优缺点各3条，不要复述简历全文\n- 查具体信息：要点式，每条一句话\n- 文档没提到的说未提及"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            stream=True,
        )
        
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield f"data: {chunk.choices[0].delta.content}\n\n"
        
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/status")
async def status(session_id: str):
    """查看当前会话状态"""
    return {"documents": engine.document_count(session_id)}


# ── Web页面 ──

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RAG文档问答</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, sans-serif; max-width: 700px; margin: 40px auto; padding: 20px; background: #f5f5f5; }
h1 { margin-bottom: 20px; }
.upload-zone { 
    border: 2px dashed #ccc; border-radius: 8px; padding: 30px; text-align: center;
    background: white; margin-bottom: 20px; cursor: pointer;
}
.upload-zone:hover { border-color: #4f46e5; }
#chat { background: white; border-radius: 8px; padding: 20px; min-height: 300px; max-height: 500px; overflow-y: auto; margin-bottom: 20px; }
.input-row { display: flex; gap: 10px; }
input[type="text"] { flex: 1; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 15px; }
button { padding: 12px 24px; background: #4f46e5; color: white; border: none; border-radius: 8px; font-size: 15px; cursor: pointer; }
button:hover { background: #4338ca; }
.msg { margin-bottom: 12px; }
.msg.q { color: #4f46e5; font-weight: bold; }
.msg.a { color: #333; white-space: pre-wrap; }
.info { color: #999; font-size: 13px; text-align: center; margin-top: 10px; }
#fileInput { display: none; }
</style>
</head>
<body>
<h1>📄 RAG文档问答</h1>

<div class="upload-zone" onclick="document.getElementById('fileInput').click()">
    <p>📁 点击上传文档（PDF/MD/TXT）</p>
    <input type="file" id="fileInput" accept=".pdf,.md,.txt" onchange="uploadFile(this)">
</div>

<div id="chat"></div>

<div class="input-row">
    <input type="text" id="question" placeholder="输入问题..." onkeydown="if(event.key==='Enter')ask()">
    <button onclick="ask()">发送</button>
</div>

<p class="info" id="status"></p>

<script>
// 生成或获取会话ID（浏览器localStorage持久化）
function getSessionId() {
    let sid = localStorage.getItem('rag_session_id');
    if (!sid) {
        sid = 'sess_' + Math.random().toString(36).substring(2, 10) + Date.now().toString(36);
        localStorage.setItem('rag_session_id', sid);
    }
    return sid;
}

const SESSION_ID = getSessionId();
let docCount = 0;

async function uploadFile(input) {
    const file = input.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("session_id", SESSION_ID);
    const res = await fetch("/upload", { method: "POST", body: form });
    const data = await res.json();
    if (data.ok) {
        docCount = data.chunks;
        updateStatus();
        addMsg(`✅ 已上传: ${data.filename}（${data.chunks}个文本块）`, "a");
    } else {
        addMsg(`❌ 上传失败: ${data.error}`, "a");
    }
}

async function ask() {
    const q = document.getElementById("question").value.trim();
    if (!q) return;
    addMsg(q, "q");
    document.getElementById("question").value = "";
    
    const eventSource = new EventSource(`/ask/stream?session_id=${SESSION_ID}&question=${encodeURIComponent(q)}`);
    const msgDiv = addMsg("", "a");
    
    eventSource.onmessage = (e) => {
        if (e.data === "[DONE]") {
            eventSource.close();
            return;
        }
        msgDiv.textContent += e.data;
    };
    
    eventSource.onerror = () => {
        eventSource.close();
        if (!msgDiv.textContent) msgDiv.textContent = "请求失败";
    };
}

function addMsg(text, cls) {
    const div = document.createElement("div");
    div.className = "msg " + cls;
    div.textContent = text;
    document.getElementById("chat").appendChild(div);
    document.getElementById("chat").scrollTop = document.getElementById("chat").scrollHeight;
    return div;
}

function updateStatus() {
    document.getElementById("status").textContent = `已加载 ${docCount} 个文本块 (会话: ${SESSION_ID.slice(0,8)}...)`;
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
