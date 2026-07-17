## Project Overview

这是一个 GUI 定制开发底座：Electron + React 前端、Python(Flask + WebSocket) 后端，用于给客户做定制开发。自带天气、汇率、日历三个业务模块作为参考实现，以及内置网络加速（mihomo）、日志、设置等基础设施。

## Architecture

### 顶层脚本
- **main.py** — 主入口；`--gui` 启动 GUI 后端（HTTP 8765 / WS 8766）；带单实例锁
- **start.py** — 统一启动器（直接 / 看门狗 / GUI 模式）
- **watchdog.py** — 进程监控自动重启（仅控制台模式；GUI 模式崩溃重启由 Electron 接管，两者互斥）

### 后端模块（modules/）
- **app_core.py** — `AppCore`：日志初始化、定时任务注册（`init_schedule_tasks`）、状态快照（`get_status_snapshot`，供 `/api/v1/status`）、退出时停 mihomo
- **web_server.py** — Flask REST + WebSocket；Bearer token 鉴权（logs/.gui_token）；EventBus 推送；仅监听 127.0.0.1；含彩云天气 helpers 与 IP 定位接口（/api/v1/geolocate，天气"当前位置"用，多提供商直连+缓存）
- **config.py** — `.env`（load_dotenv）+ `dynamic_config.json`（含代理 PROXY 子对象，线程安全读写）
- **schedule_manager.py** — `run_schedule()`：全局 schedule 单例的驱动循环，所有周期任务靠它触发
- **proxy_manager.py** — 内置网络加速：mihomo 子进程管理、订阅/粘贴配置、节点切换、健康巡检 watchdog、`request_get_with_local_proxy_fallback`（本地代理失败即回退直连 + 熔断）
- **exchange_rate_service.py** / **calendar_info_service.py** — 业务参考实现（缓存 + TTL + 代理回退的标准写法）
- **safe_calendar.py** — chinese_calendar 包装，数据超期降级为周末判断
- **services/log_service.py** — 错误日志解析分页
- **wechat_bark_listener.py** — 微信通知 Bark 转发监听核心（仅 macOS 生效；轮询通知中心数据库 + 时段/节假日过滤 + Bark 推送；可命令行独立运行）
- **wechat_bark_service.py** — 上者的服务包装：配置读写（wechat_bark_config.json）、监听线程生命周期、600 行日志环、测试推送/时段判定/通知来源

### 前端（gui/desktop/）
- **electron/main.cjs** — 壳：窗口/托盘/spawn Python 后端/崩溃重启；preload.cjs 暴露 AAS_* 桥
- **src/screens/** — Dashboard（天气+汇率+微信转发卡）、Weather、WechatBark、Proxy、Logs、Settings、About
- **src/lib/api.ts** — REST 封装；**src/lib/ws.ts** — WebSocket 客户端；**src/store/** — 各功能状态

### 关键机制
- **REST↔asyncio**：Flask 跑在 waitress 线程，需要进主循环的调用走 `AsyncioBridge.call`（超时会 `fut.cancel()` 防幽灵操作）
- **实时推送**：后端 `event_bus.publish_threadsafe(channel, data)` → 前端 `wsClient.subscribe(channel, cb)`；现有频道：`log:stream`、`proxy:status`、`exchange_rate:update`、`wechat_bark:status`、`wechat_bark:log`、`system:restart_requested`
- **周期任务**：在 `app_core.init_schedule_tasks` 用 `schedule.every(...).do(...).tag('任务名')` 注册；阻塞请求放 `run_in_executor`
- **.env 写入**：PATCH `/api/v1/config` 只接受 `web_server.ENV_WRITE_WHITELIST` 里的字段；新业务的环境变量要先登记白名单

## Common Development Commands

```bash
# 后端
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
python main.py --gui          # GUI 后端
python start.py               # 控制台（watchdog）

# 前端（gui/desktop/）
npm install
npm run electron:dev          # 开发
npm run build                 # tsc + vite 构建
npm run dist:dir              # electron-builder 打包 Windows → release/
npm run dist:mac              # macOS 打包（mac 上执行，见 scripts/build-mac.sh）

# 后端打包
build_python.bat              # PyInstaller → dist/main/
```

## Configuration

- `.env`：`CAIYUN_WEATHER_APP_KEY` / `CAIYUN_WEATHER_APP_SECRET` / `CAIYUN_WEATHER_TOKEN`（彩云天气）
- `dynamic_config.json`：运行期配置（代理 PROXY 子对象等），自动生成不入库
- `wechat_bark_config.json`：微信 Bark 转发配置（含 Device Key），自动生成不入库
- 日志：`logs/app.log`（后端，5MB 滚动×3）、`watchdog.log`

## Important Coding Guidelines

- 当我提和重构相关的需求的时候，需要严格基于原本的代码以及功能进行重构，避免节外生枝

## Memory Notes

- 始终使用中文回复
