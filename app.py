"""RAG文档问答 — FastAPI Web服务"""
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import StreamingResponse, HTMLResponse
from rag_engine import RAGEngine
import tempfile, os, shutil

app = FastAPI(title="RAG文档问答系统")
engine = RAGEngine()

# ── API ──

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """上传文档并摄入"""
    # 保存临时文件
    suffix = os.path.splitext(file.filename)[1] or ".txt"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(file.file, tmp)
        tmp.close()
        count = engine.ingest(tmp.name)
        return {"ok": True, "filename": file.filename, "chunks": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        os.unlink(tmp.name)


@app.post("/ask")
async def ask(question: str = Form(...)):
    """提问"""
    try:
        answer = engine.ask(question)
        return {"ok": True, "answer": answer}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/ask/stream")
async def ask_stream(question: str):
    """流式提问（SSE）"""
    from openai import OpenAI
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    async def generate():
        if engine.document_count == 0:
            yield "data: 请先上传文档\n\n"
            yield "data: [DONE]\n\n"
            return
        
        # 检索
        results = engine.collection.query(query_texts=[question], n_results=3)
        context = "\n\n---\n\n".join(results["documents"][0])
        
        prompt = f"""根据以下文档内容回答问题。

文档内容：
{context}

问题：{question}
请直接回答，文档中没有的信息就说"未提及"。不要编造。
"""
        
        llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com"
        )
        
        stream = llm.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            stream=True,
        )
        
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield f"data: {chunk.choices[0].delta.content}\n\n"
        
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/status")
async def status():
    """查看当前状态"""
    return {"documents": engine.document_count}


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
.msg.q { color: #4f46e5; }
.msg.a { color: #333; }
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
let docCount = 0;

async function uploadFile(input) {
    const file = input.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
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
    
    // 流式输出
    const eventSource = new EventSource(`/ask/stream?question=${encodeURIComponent(q)}`);
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
    document.getElementById("status").textContent = `已加载 ${docCount} 个文本块`;
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
