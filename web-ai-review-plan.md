# 网页版三AI自动化 — 探路记录（2026-08-28 14:00）

## 目标
流程「项目计划 → 网页各大AI分析 → 执行 → 验证 → 网页各大AI锐评 → 迭代 → 再锐评」中，
羔丸直接操作网页版 AI（DeepSeek / 千问 / 豆包），用户不用手动搬运文档。
用户明确：三家都走网页版（免费），不用 API key。

## 现状（已探明）
- DeepSeek API key ✅ 在手（sk-d229...）——但用户选择网页版
- 千问 DashScope key ✅ 在手（sk-4b67...）——但用户选择网页版
- 豆包：无火山方舟 key，网页版免费 ✅

## 豆包网页版探路结论（Playwright 实测）
1. https://www.doubao.com/chat/ 能打开，未登录也能看到输入框
2. **未登录发消息会被拦截**：URL 变 `?from_logout=1`，消息不发出，弹登录框
3. 登录弹窗有「打开 豆包/飞书 App 扫码登录」选项 → 点后会出二维码（截图 doubao-login-qr.png 存在 playwright-mcp 目录）
4. **需要用户手机扫码登录一次**，登录态（cookie）存 Playwright 浏览器 profile，之后羔丸可复用

## 待办（用户 18:00 回家后）
**路线已锁定：CDP 连 Edge 复用登录态（用户确认豆包/千问/DeepSeek 在 Edge 都登录过）**

1. 用户保存 Edge 标签页 → 关掉 Edge
2. 用命令重启 Edge 带调试端口（保留用户 profile，登录态全在）：
   ```
   cmd.exe /c "start msedge --remote-debugging-port=9222 --user-data-dir=C:\Users\31619\AppData\Local\Microsoft\Edge\User Data"
   ```
   ⚠️ 必须在 Edge 完全关闭后执行，否则新实例合并进现有进程、调试端口失效
3. 验证 CDP：`curl http://127.0.0.1:9222/json/version` → 从 WSL 连进去
4. 打开豆包 → 验证已登录 → 发测试消息确认能对话
5. 同样验证千问（tongyi.aliyun.com / chat.qwen.ai）和 DeepSeek（chat.deepseek.com）
6. 三家齐后写「三AI锐评自动化」脚本：
   - 输入：任意文档路径（如桌面《个人知识库项目文档.md》）
   - 动作：CDP 控制 Edge → 逐个打开三家 → 新建对话 → 粘贴文档+锐评 prompt → 等流式回复完成 → 抓取回复存文件
   - 输出：桌面《XX项目各大ai锐评.md》格式（参考现有文件）
7. 锐评 prompt 参考现有：让 AI 审架构/数据/评估方法，给改进优先级

## 风险（网页版风控）
- 登录态可能过期（隔几天要重扫）；频繁操作可能触发验证码
- 长文档粘贴：输入框有长度限制，超长文档要分段发（或先发摘要）
- 流式回复抓取：要轮询等回复完成（参考微信读书 canvas 轮询经验）
- 三AI锐评输入文档可能很大（项目文档 30KB+），粘贴要拆
- CDP 端口 9222 无认证：只在 127.0.0.1 监听，用完关掉 Edge 即失效

## 备选（如果网页版风控太狠）
- DeepSeek/千问退回 API（key 在手，自动化稳定），豆包保持网页版手动
- 用户拍板
