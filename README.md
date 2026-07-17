# GUI 定制开发底座

Electron + React 前端、Python(Flask + WebSocket) 后端的桌面应用底座，用于给客户做定制开发。
自带天气、汇率、日历三个业务模块作为参考实现，以及内置网络加速（mihomo）、日志、设置等基础设施。

## 内置功能

- 微信 Bark 转发（macOS）：监听系统通知中心里的微信通知，按"时段 + 中国节假日"规则转发到 iPhone 的 Bark App；含独立配置页和仪表盘状态卡
- 仪表盘：彩云天气卡片 + CNY→JPY 汇率卡片（示例业务，可照此扩展）
- 日历接口：法定节假日/调休判断（chinese-calendar），供业务参考
- 内置网络加速：内嵌 mihomo 内核，支持订阅/粘贴配置、节点切换、延迟测试
- 系统日志：实时日志流（WebSocket）+ 错误日志分页
- 设置页：.env 配置读写（带白名单和敏感字段遮罩）
- 进程守护：watchdog 进程监控（控制台模式）/ Electron 崩溃重启（GUI 模式）
- 跨平台：Windows 与 macOS（mac 下有系统红绿灯标题栏、Dock/菜单栏适配）

## 环境要求

- Python 3.10+
- Node.js 18+（构建前端）

## 快速开始

```bash
# 后端依赖
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt

# 前端依赖与构建
cd gui/desktop
npm install
npm run dev                   # 终端1：Vite 开发服务器
npm run electron:dev          # 终端2：Electron 壳（连接 Vite）
```

后端也可以单独启动：

```bash
python main.py --gui          # GUI 后端：HTTP 127.0.0.1:8765 + WS 127.0.0.1:8766
python start.py               # 控制台模式（watchdog 守护）
```

## 配置

复制 `.env.example` 为 `.env`：

- `CAIYUN_WEATHER_APP_KEY` / `CAIYUN_WEATHER_APP_SECRET` / `CAIYUN_WEATHER_TOKEN` — 彩云天气凭据（天气卡片用）

代理等运行期配置存放在 `dynamic_config.json`（自动生成，不入库）。

## 打包

```bash
# Windows
build_python.bat              # PyInstaller 打包后端 → dist/main/
npm run dist:dir              # electron-builder 打包桌面端 → release/

# macOS（在 mac 上执行；先跑 scripts/fetch-mihomo.sh 准备内核）
npm run dist:mac              # 见 scripts/build-mac.sh，产物 dmg+zip → release/
```

## 目录结构

见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。

## 给客户加新功能的套路

1. 后端：在 `modules/` 新建服务模块（参考 `exchange_rate_service.py` 的缓存+代理回退写法），在 `modules/web_server.py` 加路由；周期刷新任务在 `modules/app_core.py` 的 `init_schedule_tasks` 里注册。
2. 前端：在 `gui/desktop/src/screens/` 加页面、`src/lib/api.ts` 加接口调用、`App.tsx` 加导航。
3. 实时推送：后端 `_event_bus.publish_threadsafe('频道名', 数据)`，前端 `wsClient.subscribe('频道名', ...)`。
