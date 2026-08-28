# -*- coding: utf-8 -*-
"""探查豆包/千问/DeepSeek 页面上的模型/模式选择按钮"""
import json
import urllib.request
from playwright.sync_api import sync_playwright

def get_cdp_endpoint():
    with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=5) as r:
        d = json.loads(r.read().decode("utf-8"))
        return d["webSocketDebuggerUrl"]

SITES = {
    "豆包": "https://www.doubao.com/chat/",
    "千问": "https://chat.qwen.ai/",
    "DeepSeek": "https://chat.deepseek.com/",
}

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp(get_cdp_endpoint())
    ctx = browser.contexts[0]
    for name, url in SITES.items():
        print(f"\n{'='*40}\n[{name}] {url}")
        # 找已有 tab
        page = None
        for p in ctx.pages:
            if name in ("豆包",) and "doubao" in p.url:
                page = p; break
            if name == "千问" and ("qwen" in p.url or "tongyi" in p.url):
                page = p; break
            if name == "DeepSeek" and "deepseek" in p.url:
                page = p; break
        if not page:
            page = ctx.new_page()
            page.goto(url, timeout=45000)
            page.wait_for_timeout(5000)
        # 收集可见的按钮/可点击元素文本（前 30）
        try:
            btns = page.locator("button, [role='button'], [class*='model'], [class*='Model']").all_inner_texts()
            seen = []
            for b in btns:
                b = b.strip().replace("\n", " ")
                if b and b not in seen and len(b) < 40:
                    seen.append(b)
            print("按钮/模型元素:", seen[:30])
        except Exception as e:
            print("收集失败:", str(e)[:80])
        # 找输入框
        try:
            t = page.locator("textarea").count()
            ce = page.locator("[contenteditable='true']").count()
            print(f"输入框: textarea={t} contenteditable={ce}")
        except Exception:
            pass
        if page not in ctx.pages:
            page.close()
    browser.close()
