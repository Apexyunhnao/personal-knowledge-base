"""
视觉搜索 — 拍照 → qwen-vl-plus 识别 → 知识库检索
POST /vision-search  (JSON: {image_base64, prompt?})
"""
import json, logging, os, base64
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from openai import OpenAI

# ChromaDB 嵌入模型已本地缓存
os.environ.setdefault("HF_HUB_OFFLINE", "1")

logger = logging.getLogger(__name__)
router = APIRouter()

# 复用 chat.py 的 qwen 客户端初始化方式
qwen = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

SYSTEM_PROMPT = """你是一个视觉识别助手。看到图片后，用中文描述图片中的关键内容。
聚焦于：文字、书名、物品名称、品牌、人物、场景。描述简洁，30字以内。只返回描述文字，不要加任何前缀。"""


@router.post("/vision-search")
async def vision_search(request: Request):
    """接收图片 base64 → qwen-vl-plus 识别 → 搜索知识库"""
    try:
        body = await request.json()
        image_b64 = body.get("image_base64", "")
        custom_prompt = body.get("prompt", "")

        if not image_b64:
            return JSONResponse({"ok": False, "error": "缺少 image_base64"}, status_code=400)

        # 去掉可能的 data:image/...;base64, 前缀
        if "," in image_b64 and image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]

        # 1. 调用视觉模型识别——要求返回关键词
        user_prompt = custom_prompt or "图片中的文字内容是什么？只返回图中的文字，不要加任何描述。如果没有文字，描述图中的物品。控制在20字以内。"
        vision_response = qwen.chat.completions.create(
            model="qwen-vl-plus",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text", "text": user_prompt},
                ]
            }],
            max_tokens=100,
        )
        description = vision_response.choices[0].message.content.strip()
        logger.info(f"视觉识别结果: {description}")

        # 2. DeepSeek 提取搜索关键词
        deepseek = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )
        kw_response = deepseek.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": "你是搜索助手。根据用户输入，提取1-3个搜索关键词（用空格分隔），只返回关键词，不要其他内容。"},
                {"role": "user", "content": description}
            ],
            max_tokens=50,
        )
        search_query = kw_response.choices[0].message.content.strip()
        logger.info(f"DeepSeek 提取的搜索词: {search_query}")

        # 3. 搜索知识库（ChromaDB + 兜底）
        from db import get_conn
        conn = get_conn()
        all_results = []
        seen_ids = set()

        try:
            from hybrid_search import _get_notes_collection
            collection = _get_notes_collection()
            # 用原始描述 + 提取的关键词分别搜
            for q in [description, search_query]:
                if len(all_results) >= 5:
                    break
                chroma_results = collection.query(query_texts=[q], n_results=5)
                if chroma_results and chroma_results.get('ids') and chroma_results['ids'][0]:
                    for doc_id in chroma_results['ids'][0]:
                        try:
                            nid = int(doc_id)
                            row = conn.execute("SELECT id, title, content, topic FROM learning_notes WHERE id=? AND deleted_at IS NULL", (nid,)).fetchone()
                            if row and row[0] not in seen_ids:
                                seen_ids.add(row[0])
                                all_results.append({"id": row[0], "title": row[1], "preview": row[2][:200] if row[2] else "", "topic": row[3] or ""})
                        except ValueError:
                            pass
        except Exception as e:
            logger.warning(f"ChromaDB 搜索失败: {e}")

        # 兜底
        if not all_results:
            import re
            for kw in search_query.split()[:5]:
                like_q = f"%{kw}%"
                for row in conn.execute("SELECT id, title, content, topic FROM learning_notes WHERE deleted_at IS NULL AND (title LIKE ? COLLATE NOCASE OR content LIKE ? COLLATE NOCASE) LIMIT 3", (like_q, like_q)).fetchall():
                    if row[0] not in seen_ids:
                        seen_ids.add(row[0])
                        all_results.append({"id": row[0], "title": row[1], "preview": row[2][:200] if row[2] else "", "topic": row[3] or ""})

        # 4. DeepSeek 读笔记 + 回答
        if all_results:
            full_contents = []
            for r in all_results:
                row = conn.execute("SELECT content FROM learning_notes WHERE id=?", (r["id"],)).fetchone()
                if row:
                    full_contents.append(f"【{r['title']}】\n{row[0]}")
            context = "\n\n---\n\n".join(full_contents)[:8000]

            rag_response = deepseek.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[
                    {"role": "system", "content": "你是知识助手。直接回答用户的问题，不要提'基于笔记'或'知识库'，除非用户主动问来源。不要用 Markdown 格式（星号、井号），用纯文本。3-5句话，给要点。"},
                    {"role": "user", "content": f"用户说：{description}\n\n知识库相关笔记：\n\n{context}\n\n请回答用户。"}
                ],
                max_tokens=1000,
            )
            answer = rag_response.choices[0].message.content.strip()
        else:
            answer = None

        return JSONResponse({
            "ok": True,
            "data": {
                "description": description,
                "answer": answer,
                "sources": [{"id": r["id"], "title": r["title"]} for r in all_results[:3]],
                "count": len(all_results),
            }
        })

    except Exception as e:
        logger.error(f"vision-search error: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/vision-chat")
async def vision_chat(request: Request):
    """追问端点 — 接收对话历史 + 知识库上下文 → DeepSeek 回答"""
    try:
        body = await request.json()
        messages = body.get("messages", [])  # [{role, content}, ...]
        context = body.get("context", "")    # 知识库笔记内容

        if not messages:
            return JSONResponse({"ok": False, "error": "缺少 messages"}, status_code=400)

        deepseek = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )

        system_msg = "你是知识助手。直接回答追问，不要提'基于笔记'或'知识库'，不要用 Markdown（星号、井号），纯文本。3-5句话，给要点。"
        if context:
            system_msg += f"\n\n知识库相关笔记：\n\n{context[:6000]}"

        api_messages = [{"role": "system", "content": system_msg}]
        for m in messages[-10:]:  # 最近10轮
            api_messages.append({"role": m["role"], "content": m["content"]})

        rag_response = deepseek.chat.completions.create(
            model="deepseek-v4-pro",
            messages=api_messages,
            max_tokens=1000,
        )
        answer = rag_response.choices[0].message.content.strip()

        return JSONResponse({"ok": True, "data": {"answer": answer}})

    except Exception as e:
        logger.error(f"vision-chat error: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
