# 项目目录结构说明

```
项目根/
├── main.py                     # 主程序入口（--gui 启动 GUI 后端）
├── start.py                    # 统一启动器（直接/看门狗/GUI 模式选择）
├── watchdog.py                 # 看门狗：监控 main.py 并自动重启（控制台模式用）
├── main.spec                   # PyInstaller 打包配置
├── build_python.bat            # 一键打包后端
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量样例（彩云天气凭据）
├── 点我启动.vbs                # 启动打包后的桌面端
│
├── modules/                    # Python 后端模块
│   ├── app_core.py             # 应用核心：日志、定时任务注册、状态快照、退出清理
│   ├── web_server.py           # GUI 后端：Flask REST + WebSocket 推送 + token 鉴权
│   ├── config.py               # 配置管理：.env + dynamic_config.json + 代理配置
│   ├── schedule_manager.py     # 定时任务驱动循环（schedule.run_pending）
│   ├── proxy_manager.py        # 内置网络加速：mihomo 子进程管理/订阅/节点切换/健康巡检
│   ├── exchange_rate_service.py# 汇率服务（Yahoo Finance，带缓存与代理回退）— 参考实现
│   ├── calendar_info_service.py# 日历服务（chinese-calendar 节假日/调休）— 参考实现
│   ├── safe_calendar.py        # chinese_calendar 安全包装（数据超期降级为周末判断）
│   ├── wechat_bark_listener.py # 微信通知 Bark 转发监听核心（仅 macOS 生效，可命令行独立运行）
│   ├── wechat_bark_service.py  # 微信 Bark 服务层：配置/监听线程/日志环/测试与时段判定
│   └── services/
│       └── log_service.py      # 错误日志解析/分页（GUI 日志页用）
│
├── gui/desktop/                # Electron + React + TS 桌面前端
│   ├── electron/               # 主进程（窗口/托盘/后端进程管理）与 preload 桥
│   ├── src/
│   │   ├── screens/            # 页面：Dashboard / Weather / WechatBark / Proxy / Logs / Settings / About
│   │   ├── components/         # 组件：天气面板、汇率面板、服务控制、横幅、Toast 等
│   │   ├── store/              # 状态：weather / exchangeRate / proxy / logs / system 等
│   │   └── lib/                # api.ts(REST) / ws.ts(WebSocket) / backend.ts / types.ts
│   └── electron-builder.yml    # 桌面端打包配置
│
├── scripts/
│   ├── fetch-mihomo.ps1        # 下载 mihomo 内核到 bin/（Windows，打包前执行）
│   ├── fetch-mihomo.sh         # 同上（macOS 版，darwin-amd64/arm64 自动判别）
│   └── build-mac.sh            # macOS 一键构建（npm run dist:mac 调用）
│
├── tests/
│   ├── test_service_proxy_fallback.py  # 本地代理失败回退/熔断测试
│   └── test_wechat_bark_schedule.py    # 微信转发时段判定测试
│
└── 运行期生成（不入库）：
    logs/（含 app.log 与 .gui_token）、dynamic_config.json、wechat_bark_config.json、
    exchange_rate_cache.json、proxy_runtime/、bin/、release/
```

## 数据流

```
Electron 渲染进程 (React)
   │  REST (fetch + Bearer token)          WebSocket (实时推送)
   ▼                                        ▼
web_server.py (Flask/waitress 线程)  ←→  EventBus (asyncio)
   │ bridge.call / 直接调用                 ▲ publish_threadsafe
   ▼                                        │
web_server 路由直接调用：calendar_info_service / 彩云天气 helpers / exchange_rate_service
app_core.py（状态快照/定时任务）── schedule_manager.run_schedule 驱动
   │
   ├── exchange_rate_service（周期刷新 + 缓存）
   └── proxy_manager（mihomo 子进程，境外请求经本地端口）
```
