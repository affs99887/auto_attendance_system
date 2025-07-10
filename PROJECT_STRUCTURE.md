# 项目目录结构说明

## 📁 目录组织

```
自动打卡系统/
├── 📁 core/                    # 核心业务模块
│   ├── browser_automation.py  # 浏览器自动化
│   ├── email_service.py       # 邮件服务
│   ├── image_recognition.py   # 图像识别
│   ├── punch_records.py       # 打卡记录管理
│   ├── tasks.py               # 任务管理
│   └── watchdog.py            # 看门狗监控
│
├── 📁 docs/                   # 项目文档
│   └── [项目相关文档]
│
├── 📁 templates/              # 模板图片
├── 📁 logs/                   # 日志文件
├── 📁 punch_records/          # 打卡记录
├── 📁 screenshots/            # 截图文件
├── 📁 dist/                   # 打包输出
│
├── 📄 main.py                 # 主程序入口
├── 📄 watchdog.py             # 看门狗监控程序
├── 📄 tasks.py                # 任务管理模块
├── 📄 punch_records.py        # 打卡记录模块
├── 📄 email_service.py        # 邮件服务模块
├── 📄 browser_automation.py   # 浏览器自动化模块
├── 📄 image_recognition.py    # 图像识别模块
├── 📄 requirements.txt        # 依赖配置
├── 📄 .env                    # 环境配置
├── 📄 CLAUDE.md              # 开发指南
├── 📄 README.md              # 项目说明
└── 📄 一键打包.bat            # 打包快捷方式
```

## 🚀 快速使用

### 运行程序
```bash
# 方式1: 直接运行主程序
python main.py

# 方式2: 运行带看门狗监控的程序（推荐）
python watchdog.py
```

### 环境配置
```bash
# 1. 创建虚拟环境
python -m venv venv

# 2. 激活虚拟环境
source venv/bin/activate  # Linux/WSL
# 或
venv\Scripts\activate     # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
# 编辑 .env 文件配置登录信息和Telegram机器人
```

## 📋 核心模块说明

### core/ - 核心业务模块
- **browser_automation.py**: 浏览器控制和页面操作
- **email_service.py**: 邮件发送和通知服务
- **image_recognition.py**: OCR识别和图像处理
- **punch_records.py**: 打卡记录的存储和管理
- **tasks.py**: 定时任务的调度和执行
- **watchdog.py**: 系统监控和自动重启

### 主程序文件
- **main.py**: 应用主入口，包含TelegramBot和AttendanceSystem类
- **watchdog.py**: 看门狗监控程序，负责主程序的监控和重启
- **tasks.py**: 任务管理器，处理定时任务
- **punch_records.py**: 打卡记录管理器
- **email_service.py**: 邮件服务，处理邮件发送
- **browser_automation.py**: 浏览器自动化控制器
- **image_recognition.py**: 图像识别和OCR处理

## 🔄 依赖关系

```
main.py
├── core.tasks (TaskManager)
├── core.punch_records (PunchRecordManager)
├── core.email_service (email_service)
├── core.browser_automation (browser_controller)
└── core.image_recognition (image_recognizer)

watchdog.py
└── main.py (监控并重启)
```

## 🎯 使用建议

### 新用户
1. 配置虚拟环境和依赖
2. 编辑 `.env` 文件配置登录信息
3. 运行 `python main.py` 或 `python watchdog.py`
4. 通过Telegram机器人远程控制

### 开发者
1. 核心业务逻辑在 `core/` 目录
2. 主程序逻辑在根目录的各个模块文件中
3. 使用 `watchdog.py` 进行程序监控
4. 参考 `CLAUDE.md` 了解开发指南

### 部署用户
1. 配置虚拟环境和依赖
2. 将项目复制到目标服务器
3. 配置 `.env` 文件
4. 运行 `python watchdog.py` 作为后台服务

## 📝 文件维护说明

- **请勿直接修改**: `dist/`, `logs/`, `__pycache__/`
- **核心配置**: `.env`, `requirements.txt`
- **用户数据**: `punch_records/`, `screenshots/`
- **开发文档**: `CLAUDE.md`, `README.md`

## 🔧 系统特性

- **自动化**: 基于图像识别的全自动打卡
- **监控**: 看门狗程序确保系统稳定运行
- **远程控制**: 通过Telegram机器人远程管理
- **多用户支持**: 支持多个用户账号的打卡记录
- **任务调度**: 支持定时任务和工作日识别
- **邮件通知**: 打卡结果邮件通知功能

---

这种目录结构使项目更加清晰、易于维护，专注于核心的自动化打卡功能。