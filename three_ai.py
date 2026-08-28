# -*- coding: utf-8 -*-
"""
三AI工作流驱动脚本 v2（豆包/千问/DeepSeek 网页版）
- 复用已有标签页（不每问开新页）
- 支持模型/深度模式选择
用法:
  python3 three_ai.py --prompt "问题"
  python3 three_ai.py --prompt-file 文档.md
  python3 three_ai.py --prompt-file 文档.md --deep --out out.md
  python3 three_ai.py --prompt-file 文档.md --site deepseek --out out.md

前提: Edge 以 edge-cdp-profile 启动（--remote-debugging-port=9222 --remote-allow-origins=*），三家已登录。
"""
import argparse
import json
import time
import urllib.request

from playwright.sync_api import sync_playwright

SITES = {
    "doubao": {"name": "豆包", "url": "https://www.doubao.com/chat/", "domain": "doubao"},
    "qwen": {"name": "千问", "url": "https://chat.qwen.ai/", "domain": "qwen"},
    "deepseek": {"name": "DeepSeek", "url": "https://chat.deepseek.com/", "domain": "deepseek"},
}


def get_cdp_endpoint():
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
            if d.get("webSocketDebuggerUrl"):
                return d["webSocketDebuggerUrl"]
    except Exception:
        pass
    for p in [r"C:\Users\31619\edge-cdp-profile\DevToolsActivePort",
              r"C:\Users\31619\AppData\Local\Microsoft\Edge\User Data\DevToolsActivePort"]:
        try:
            with open(p, encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            if len(lines) >= 2:
                return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
        except Exception:
            continue
    raise RuntimeError("无法获取 CDP 端点，Edge 调试端口没开")


def get_or_new_page(ctx, site_key):
    """复用已有标签页，找不到才新建"""
    dom = SITES[site_key]["domain"]
    for p in ctx.pages:
        if dom in p.url and p.url.startswith("http"):
            return p
    p = ctx.new_page()
    p.goto(SITES[site_key]["url"], timeout=45000)
    p.wait_for_timeout(4000)
    return p


def find_input(page):
    for sel in ["textarea", "div[contenteditable='true']", "div[contenteditable='plaintext-only']"]:
        loc = page.locator(sel)
        if loc.count():
            return loc.nth(loc.count() - 1)
    return None


def select_model(page, site_key):
    """各家模型/深度模式选择"""
    name = SITES[site_key]["name"]
    if site_key == "deepseek":
        # 2026-08-28 修复：深度思考是 div.ds-toggle-button 开关（非 button），
        # 用 text= 匹配可能点到历史残留且不生效。精确点 toggle 并验证 active class。
        try:
            loc = page.locator("div.ds-toggle-button:has-text('深度思考')").first
            loc.wait_for(state="visible", timeout=8000)
            # 若已激活则跳过（激活 class 是 ds-toggle-button--selected，实测 2026-08-28）
            cls = loc.get_attribute("class") or ""
            if "selected" in cls or "is-active" in cls or "active" in cls or "checked" in cls:
                print(f"  [{name}] ✓ 深度思考 已开启（原本就激活）")
                return
            loc.click(timeout=5000)
            page.wait_for_timeout(1000)
            cls2 = loc.get_attribute("class") or ""
            if "selected" in cls2 or "is-active" in cls2 or "active" in cls2 or "checked" in cls2:
                print(f"  [{name}] ✓ 深度思考 已开启")
            else:
                print(f"  [{name}] ⚠️ 已点击但未检测到激活（class={cls2[:50]}）")
        except Exception as e:
            print(f"  [{name}] 未找到深度思考按钮: {str(e)[:60]}")
    elif site_key == "doubao":
        # 已选 2.1 Turbo 则跳过（模型按钮文本会变成新模型名）
        try:
            if page.locator("text=豆包 2.1 Turbo").first.count() > 0:
                print(f"  [{name}] ✓ 已是 豆包 2.1 Turbo")
                return
        except Exception:
            pass
        try:
            # 点模型按钮（当前模型名，可能"豆包 快速"或其他）
            for cur in ["豆包 快速", "豆包 快速版", "豆包 2.1 Turbo"]:
                try:
                    loc = page.locator(f"text={cur}").first
                    if loc.count():
                        loc.click(timeout=3000)
                        break
                except Exception:
                    continue
            page.wait_for_timeout(2000)
            # 选 2.1 Turbo（用户指定专家模式）——等元素出现再点
            for opt in ["豆包 2.1 Turbo", "2.1 Turbo"]:
                try:
                    loc = page.locator(f"text={opt}").first
                    loc.wait_for(state="visible", timeout=3000)
                    loc.click(timeout=2000)
                    page.wait_for_timeout(800)
                    print(f"  [{name}] ✓ 已选 {opt}")
                    return
                except Exception:
                    continue
            print(f"  [{name}] 未找到 2.1 Turbo 选项")
        except Exception as e:
            print(f"  [{name}] 模型选择失败: {str(e)[:60]}")
    elif site_key == "qwen":
        # 已选 Qwen3.8-Max 则跳过
        try:
            if page.locator("text=Qwen3.8-Max").first.count() > 0:
                print(f"  [{name}] ✓ 已是 Qwen3.8-Max")
                return
        except Exception:
            pass
        try:
            # 点当前模型按钮（如 Qwen3.7-Plus）
            page.locator("text=Qwen3.7-Plus").first.click(timeout=4000)
            page.wait_for_timeout(2000)
            for opt in ["Qwen3.8-Max", "Qwen-Max", "qwen-max"]:
                try:
                    loc = page.locator(f"text={opt}").first
                    loc.wait_for(state="visible", timeout=3000)
                    loc.click(timeout=2000)
                    page.wait_for_timeout(800)
                    print(f"  [{name}] ✓ 已选 {opt}")
                    return
                except Exception:
                    continue
            print(f"  [{name}] 未找到 Qwen3.8-Max 选项")
        except Exception as e:
            print(f"  [{name}] 模型选择失败: {str(e)[:60]}")


def wait_reply_stable(page, stable_rounds=4, timeout=240):
    last_text = ""
    stable = 0
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            msgs = page.locator("[class*='message'], [class*='Message'], [class*='chat-item'], [class*='ChatItem'], [class*='reply'], [class*='Response']").all_inner_texts()
        except Exception:
            msgs = []
        full = "\n".join(msgs)
        if full == last_text and len(full) > 0:
            stable += 1
            if stable >= stable_rounds:
                return full
        else:
            stable = 0
            last_text = full
        time.sleep(3)
    return last_text


def ask_one(pw, site_key, prompt_text, out_lines, deep=False, page_cache=None):
    site = SITES[site_key]
    name = site["name"]
    out_lines.append(f"\n## {name} 回复\n")
    print(f"[{name}] 开始...")
    browser = pw.chromium.connect_over_cdp(get_cdp_endpoint())
    try:
        ctx = browser.contexts[0]
        page = get_or_new_page(ctx, site_key)
        if page_cache is not None:
            page_cache[site_key] = page
        # 登录态检查
        if "doubao" in page.url and "from_logout" in page.url:
            out_lines.append("（未登录，被踢到 from_logout）")
            print(f"[{name}] ✗ 未登录")
            return
        if deep:
            select_model(page, site_key)
        inp = find_input(page)
        if not inp:
            out_lines.append("（找不到输入框）")
            print(f"[{name}] ✗ 找不到输入框")
            return
        inp.click()
        page.wait_for_timeout(500)
        if len(prompt_text) <= 20000:
            inp.fill(prompt_text)
        else:
            inp.fill(prompt_text[:20000])
            print(f"[{name}] ⚠ 提示词超 20000 字，截断")
        page.wait_for_timeout(600)
        page.keyboard.press("Enter")
        print(f"[{name}] 已发送，等待回复...")
        full = wait_reply_stable(page)
        text = full[-4000:] if len(full) > 4000 else full
        out_lines.append(text.strip() if text.strip() else "（空回复）")
        print(f"[{name}] ✓ 抓取到 {len(text)} 字")
    except Exception as e:
        out_lines.append(f"（异常: {type(e).__name__}: {str(e)[:100]}）")
        print(f"[{name}] ✗ 异常: {str(e)[:100]}")
    finally:
        try:
            browser.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="")
    ap.add_argument("--prompt-file", default="")
    ap.add_argument("--site", default="all", choices=["all", "doubao", "qwen", "deepseek"])
    ap.add_argument("--out", default="")
    ap.add_argument("--deep", action="store_true", help="选专家/深度模型")
    args = ap.parse_args()

    prompt_text = args.prompt.strip()
    if args.prompt_file:
        with open(args.prompt_file, encoding="utf-8") as f:
            prompt_text = f.read().strip()
    if not prompt_text:
        print("需要 --prompt 或 --prompt-file"); return

    keys = list(SITES.keys()) if args.site == "all" else [args.site]
    out_lines = [f"# 三AI分析\n\n> 提示词: {prompt_text[:150]}{'...' if len(prompt_text) > 150 else ''}\n"]
    page_cache = {}
    with sync_playwright() as pw:
        for k in keys:
            ask_one(pw, k, prompt_text, out_lines, deep=args.deep, page_cache=page_cache)

    result = "\n".join(out_lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"\n已保存: {args.out}")
    else:
        print("\n" + "=" * 30 + "\n" + result)


if __name__ == "__main__":
    main()
