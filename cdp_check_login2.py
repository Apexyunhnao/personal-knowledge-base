# -*- coding: utf-8 -*-
"""cdp_check_login2.py — 用独立 profile 启动的 Edge，验证豆包/千问/DeepSeek 登录态"""
import asyncio, sys
from playwright.async_api import async_playwright

CDP_URL = "http://172.27.144.1:9223"
SITES = [
    ("豆包", "https://www.doubao.com/chat/"),
    ("千问", "https://chat.qwen.ai/"),
    ("DeepSeek", "https://chat.deepseek.com/"),
]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        print("已连接 CDP:", browser.version)
        for name, url in SITES:
            page = await browser.new_page()
            try:
                await page.goto(url, timeout=40000)
                await page.wait_for_timeout(6000)
                title = await page.title()
                login_btn = await page.locator("button:has-text('登录'), a:has-text('登录'), [class*='login']").count()
                await page.screenshot(path=f"/tmp/check2_{name}.png")
                print(f"[{name}] title={title} | 登录元素={login_btn}")
            except Exception as e:
                print(f"[{name}] 错误: {str(e)[:120]}")
            await page.close()
        await browser.close()

asyncio.run(main())
