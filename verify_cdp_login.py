# -*- coding: utf-8 -*-
"""验证 Edge CDP 连接 + 三家 AI 登录态（豆包/千问/DeepSeek）
用法: python3 verify_cdp_login.py
"""
import sys
from playwright.sync_api import sync_playwright

ACTIVE_PORT = r"C:\Users\31619\AppData\Local\Microsoft\Edge\User Data\DevToolsActivePort"

def read_endpoint():
    # 优先走 HTTP 端点拿 webSocketDebuggerUrl（命令行方式启动后可用）
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=5) as r:
            import json as _json
            d = _json.loads(r.read().decode("utf-8"))
            ws = d.get("webSocketDebuggerUrl", "")
            if ws:
                return "9222", ws
    except Exception:
        pass
    # 回退：读新 profile 目录的 DevToolsActivePort
    for p in [r"C:\Users\31619\edge-cdp-profile\DevToolsActivePort", ACTIVE_PORT]:
        try:
            with open(p, encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            if len(lines) >= 2:
                return lines[0], f"ws://127.0.0.1:{lines[0]}{lines[1]}"
        except Exception:
            continue
    raise RuntimeError("无法获取 CDP 端点")

def check_login(page, name):
    """打开页面, 简单判定登录态"""
    try:
        page.goto(page.url if False else name["url"], timeout=30000)
        page.wait_for_timeout(6000)
        url = page.url
        title = page.title()
        # 判定逻辑（各家不同）
        hint = ""
        if "doubao" in url:
            if "from_logout" in url:
                hint = "✗ 未登录（被踢到 from_logout）"
            else:
                hint = "✓ 可能已登录（无 from_logout）"
        elif "qwen" in url or "tongyi" in url or "aliyun" in url:
            # 千问: 有输入框/头像即已登录；出现登录按钮则未登录
            login_btns = page.locator("text=登录").count()
            textarea = page.locator("textarea").count()
            hint = f"登录按钮数={login_btns} textarea={textarea} → {'✓ 已登录' if textarea > 0 and login_btns == 0 else '✗ 未登录'}"
        elif "deepseek" in url:
            textarea = page.locator("textarea").count()
            login_btns = page.locator("text=登录").count()
            hint = f"登录按钮数={login_btns} textarea={textarea} → {'✓ 已登录' if textarea > 0 and login_btns == 0 else '✗ 未登录'}"
        print(f"  [{name['name']}] URL={url[:60]} | title={title[:30]} | {hint}")
    except Exception as e:
        print(f"  [{name['name']}] 异常: {type(e).__name__}: {str(e)[:80]}")

def main():
    port, ws_url = read_endpoint()
    print(f"CDP 端点: {ws_url[:70]}")

    sites = [
        {"name": "豆包", "url": "https://www.doubao.com/chat/"},
        {"name": "千问", "url": "https://chat.qwen.ai/"},
        {"name": "DeepSeek", "url": "https://chat.deepseek.com/"},
    ]

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws_url)
        contexts = browser.contexts
        print(f"contexts 数: {len(contexts)}")
        if not contexts:
            print("没有默认 context，无法复用登录态"); return
        ctx = contexts[0]
        print(f"默认 context pages: {len(ctx.pages)}")
        for s in sites:
            pg = ctx.new_page()
            try:
                check_login(pg, s)
            finally:
                pg.close()
        browser.close()

if __name__ == "__main__":
    main()
