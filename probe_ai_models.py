# -*- coding: utf-8 -*-
"""探查豆包/千问 模型选择弹窗内容"""
import json
import urllib.request
from playwright.sync_api import sync_playwright

def get_cdp_endpoint():
    with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=5) as r:
        d = json.loads(r.read().decode("utf-8"))
        return d["webSocketDebuggerUrl"]

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp(get_cdp_endpoint())
    ctx = browser.contexts[0]

    # 豆包
    page = None
    for p in ctx.pages:
        if "doubao" in p.url:
            page = p; break
    if not page:
        page = ctx.new_page()
        page.goto("https://www.doubao.com/chat/", timeout=45000)
        page.wait_for_timeout(5000)
    print("=== 豆包: 点模型按钮 ===")
    try:
        page.locator("text=豆包 快速").first.click(timeout=5000)
        page.wait_for_timeout(1500)
        # dump 弹窗/附近文本
        texts = page.locator("[class*='popover'], [class*='Popover'], [class*='dropdown'], [class*='Dropdown'], [class*='menu'], [class*='Menu']").all_inner_texts()
        merged = []
        for t in texts:
            for line in t.split("\n"):
                line = line.strip()
                if line and line not in merged and len(line) < 60:
                    merged.append(line)
        print("弹窗文本:", merged[:30])
    except Exception as e:
        print("豆包点按钮失败:", str(e)[:100])
    # 关弹窗
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    # 千问
    page2 = None
    for p in ctx.pages:
        if "qwen" in p.url:
            page2 = p; break
    if not page2:
        page2 = ctx.new_page()
        page2.goto("https://chat.qwen.ai/", timeout=45000)
        page2.wait_for_timeout(5000)
    print("\n=== 千问: 点模型按钮 ===")
    try:
        page2.locator("text=Qwen3.7-Plus").first.click(timeout=5000)
        page2.wait_for_timeout(1500)
        texts = page2.locator("[class*='popover'], [class*='Popover'], [class*='dropdown'], [class*='Dropdown'], [class*='menu'], [class*='Menu'], [role='dialog']").all_inner_texts()
        merged = []
        for t in texts:
            for line in t.split("\n"):
                line = line.strip()
                if line and line not in merged and len(line) < 60:
                    merged.append(line)
        print("弹窗文本:", merged[:30])
    except Exception as e:
        print("千问点按钮失败:", str(e)[:100])
    browser.close()
