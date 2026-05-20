"""
services 子包 — bot 和 GUI Web API 共用的纯业务逻辑模块。

抽取自 modules/telegram_bot.py 中可独立运行的部分（无 telegram update/context 依赖），
让前端 REST/WebSocket 与 Telegram bot 都能调用同一份实现。
"""
