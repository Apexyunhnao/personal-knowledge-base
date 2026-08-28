# -*- coding: utf-8 -*-
"""cdp_test.py — 测试 CDP 连接 Edge + 打开豆包对话"""
import asyncio, sys
from playwright.async_api import async_playwright

CDP_URL = "http://172.27.144.1:9223"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        print("已连接 CDP, browser:", browser)
        # 看现有标签页
        ctxs = browser.contexts
        print("contexts:", len(ctxs))
        if ctxs:
            pages = ctxs[0].pages
            print("现有 tabs:", [pg.url[:60] for pg in pages])
        # 新开豆包
        page = await browser.new_page()
        await page.goto("https://www.doubao.com/chat/", timeout=30000)
        await page.wait_for_timeout(4000)
        title = await page.title()
        print("页面标题:", title)
        # 检查是否已登录（有没有登录按钮）
        login_btn = await page.locator("button:has-text('登录')").count()
        print("登录按钮数量:", login_btn)
        # 找输入框
        textbox = page.get_by_role("textbox")
        print("textbox 数量:", await textbox.count())
        if await textbox.count() > 0:
            await textbox.first.fill("你好，一句话介绍自己")
            await textbox.first.press("Enter")
            print("已发送消息")
            await page.wait_for_timeout(8000)
            # 抓取回复
            body_text = await page.inner_text("body")
            # 提取最后一段非空文本
            lines = [l.strip() for l in body_text.split("\n") if l.strip()]
            print("页面文本末尾:", " | ".join(lines[-5:])[:300])
        await page.screenshot(path="/tmp/cdp_doubao_test.png")
        print("截图已存 /tmp/cdp_doubao_test.png")
        await browser.close()

asyncio.run(main())
