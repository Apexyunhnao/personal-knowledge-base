"""
语音识别 — 录音 → qwen3-asr-flash 识别 → 搜索框文字 / 整理存笔记
POST /voice/recognize  (JSON: {audio_base64: "data:audio/webm;base64,..."})
POST /voice/note      (JSON: {audio_base64: ...})
"""
import json, logging, os, base64
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from openai import OpenAI
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()
router = APIRouter()

qwen = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

deepseek = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")

ASR_MODEL = "qwen3-asr-flash"


def recognize_audio(audio_b64: str) -> str:
    """把 base64 音频转成文字（支持 webm/opus/wav/mp3 等）"""
    # 去掉可能的 data:audio/...;base64, 前缀
    if "," in audio_b64 and audio_b64.startswith("data:"):
        audio_b64 = audio_b64.split(",", 1)[1]
    data_uri = f"data:audio/webm;base64,{audio_b64}"
    try:
        r = qwen.chat.completions.create(
            model=ASR_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "input_audio", "input_audio": {"data": data_uri}}
            ]}],
            stream=False,
            extra_body={"asr_options": {"enable_itn": False}},
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        # 可能是 mime 类型问题，尝试不带前缀的 base64 再试一次
        logger.warning(f"ASR 首次调用失败({e})，尝试兜底")
        r = qwen.chat.completions.create(
            model=ASR_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "input_audio", "input_audio": {"data": f"data:audio/wav;base64,{audio_b64}"}}
            ]}],
            stream=False,
            extra_body={"asr_options": {"enable_itn": False}},
        )
        return r.choices[0].message.content.strip()


@router.post("/voice/recognize")
async def voice_recognize(request: Request):
    """语音 → 文字（进搜索框/提问框）"""
    try:
        body = await request.json()
        audio_b64 = body.get("audio_base64", "")
        if not audio_b64:
            return JSONResponse({"ok": False, "error": "缺少 audio_base64"}, status_code=400)
        text = recognize_audio(audio_b64)
        if not text:
            return JSONResponse({"ok": False, "error": "未识别到语音内容"}, status_code=422)
        return JSONResponse({"ok": True, "data": {"text": text}})
    except Exception as e:
        logger.error(f"voice/recognize error: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/voice/note")
async def voice_note(request: Request):
    """语音/文字 → 整理归纳 → 存笔记。支持 {audio_base64} 或 {text}"""
    try:
        body = await request.json()
        audio_b64 = body.get("audio_base64", "")
        text = (body.get("text", "") or "").strip()

        if audio_b64:
            text = recognize_audio(audio_b64)
        if not text:
            return JSONResponse({"ok": False, "error": "没有可整理的语音或文字内容"}, status_code=400)

        # DeepSeek 整理归纳（带知识库目录，避免重复建条目）
        from routers.chat import build_catalog_prompt
        system_prompt = build_catalog_prompt()
        # 强制 JSON 输出，直接拿结构化笔记
        task = (
            "用户语音说了一段话，请整理成一条知识笔记。\n\n"
            "语音内容：\n" + text + "\n\n"
            "要求：\n"
            "1. 先判断是否值得存：如果是闲聊、一次性问答、纯事实查询，返回 {\"save\": false, \"reason\": \"原因\"}\n"
            "2. 如果值得存：检查上面的知识库目录，同一主题合并到已有条目（返回 {\"save\": \"merge\", \"item_id\": N, \"changes\": {...}}）\n"
            "3. 新建则返回 {\"save\": true, \"note\": {\"title\": \"精炼标题5-15字\", \"content\": \"结构化内容\", \"topic\": \"Python|数据库|前端|AI/ML|系统设计|工具|面试|其他\", \"tags\": \"逗号分隔\"}}\n"
            "4. content 要提炼要点、结构化，不要照搬原话。只返回 JSON，不要其他文字。"
        )
        r = deepseek.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ],
            temperature=0.3,
            max_tokens=1500,
        )
        raw = r.choices[0].message.content.strip()
        # 去掉可能的 ```json 包裹
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"): raw = raw[4:]
        result = json.loads(raw)

        from repositories import note_repo

        if result.get("save") is False:
            return JSONResponse({"ok": True, "data": {"text": text, "saved": False, "reason": result.get("reason", "")}})

        if result.get("save") == "merge":
            changes = result.get("changes", {})
            nid = changes.pop("item_id", result.get("item_id"))
            note_repo.update(nid, changes)
            return JSONResponse({"ok": True, "data": {"text": text, "saved": True, "merged": True, "id": nid, "title": changes.get("title", "")}})

        note = result.get("note", {})
        nid = note_repo.create({
            "title": note.get("title", "语音笔记"),
            "content": note.get("content", text),
            "topic": note.get("topic", "其他"),
            "tags": note.get("tags", ""),
            "format": "markdown",
        })
        return JSONResponse({"ok": True, "data": {"text": text, "saved": True, "id": nid, "title": note.get("title", "")}})

    except Exception as e:
        logger.error(f"voice/note error: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
