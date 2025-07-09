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
├── 📁 flet_gui/               # Flet现代化界面
│   ├── adapters/              # 业务逻辑适配器
│   ├── components/            # 可复用UI组件
│   ├── pages/                 # 页面组件
│   ├── utils/                 # 工具函数
│   └── main.py               # Flet主入口
│
├── 📁 gui_client/             # 原Tkinter界面（保留）
│   ├── widgets/               # GUI组件
│   ├── utils/                 # GUI工具
│   └── main_gui.py           # Tkinter主入口
│
├── 📁 scripts/                # 启动脚本
│   ├── run_flet_gui.py       # Flet GUI启动器
│   ├── run_gui.py            # Tkinter GUI启动器
│   ├── run_gui_selector.py   # GUI选择器
│   └── flet_web_test.py      # Web版本测试
│
├── 📁 tools/                  # 开发工具
│   ├── pack_pyinstaller.py   # PyInstaller打包
│   └── 快速打包.bat           # 打包批处理
│
├── 📁 docs/                   # 项目文档
│   ├── FLET_GUI_README.md     # Flet GUI使用指南
│   ├── PACKAGING_GUIDE.md     # 打包部署指南
│   └── 项目迁移完成总结.md     # 项目总结
│
├── 📁 templates/              # 模板图片
├── 📁 logs/                   # 日志文件
├── 📁 punch_records/          # 打卡记录
├── 📁 screenshots/            # 截图文件
├── 📁 dist/                   # 打包输出
│
├── 📄 main.py                 # 主程序入口
├── 📄 requirements.txt        # 依赖配置
├── 📄 .env                    # 环境配置
├── 📄 CLAUDE.md              # 开发指南
├── 📄 README.md              # 项目说明
│
└── 🚀 便捷启动脚本
    ├── 启动GUI选择器.py        # GUI选择器快捷方式
    ├── 启动Flet界面.py         # Flet界面快捷方式
    └── 一键打包.bat            # 打包快捷方式
```

## 🚀 快速使用

### 运行程序
```bash
# 方式1: 选择GUI界面类型
python 启动GUI选择器.py

# 方式2: 直接启动Flet现代化界面
python 启动Flet界面.py

# 方式3: 运行原有主程序
python main.py
```

### 打包程序
```bash
# Windows一键打包
双击运行: 一键打包.bat
```

## 📋 核心模块说明

### core/ - 核心业务模块
- **browser_automation.py**: 浏览器控制和页面操作
- **email_service.py**: 邮件发送和通知服务
- **image_recognition.py**: OCR识别和图像处理
- **punch_records.py**: 打卡记录的存储和管理
- **tasks.py**: 定时任务的调度和执行
- **watchdog.py**: 系统监控和自动重启

### flet_gui/ - 现代化界面
- **main.py**: Flet应用主入口
- **adapters/**: 连接业务逻辑和UI的适配器
- **components/**: 可复用的UI组件库
- **pages/**: 各功能页面（仪表板、打卡、任务、设置）
- **utils/**: 状态管理和主题管理工具

### scripts/ - 启动脚本
- **run_gui_selector.py**: 让用户选择GUI类型
- **run_flet_gui.py**: 启动Flet现代化界面
- **flet_web_test.py**: Web版本测试和演示

### tools/ - 开发工具
- **pack_pyinstaller.py**: 完整的Windows打包解决方案
- **快速打包.bat**: Windows一键打包批处理

## 🔄 依赖关系

```
main.py
├── core.tasks (TaskManager)
├── core.punch_records (PunchRecordManager)
├── core.email_service (email_service)
├── core.browser_automation (browser_controller)
└── core.image_recognition (image_recognizer)

flet_gui/main.py
├── adapters.system_adapter (SystemAdapter)
├── utils.state_manager (app_state)
├── utils.theme_manager (ThemeManager)
└── pages.* (各页面组件)
```

## 🎯 使用建议

### 新用户
1. 运行 `启动GUI选择器.py`
2. 选择 "Flet现代化界面"
3. 配置 `.env` 文件
4. 开始使用

### 开发者
1. 核心业务逻辑在 `core/` 目录
2. UI界面代码在 `flet_gui/` 目录
3. 使用 `tools/pack_pyinstaller.py` 打包
4. 参考 `docs/` 目录中的文档

### 部署用户
1. 运行 `一键打包.bat` 创建exe文件
2. 将 `dist/` 目录复制到目标电脑
3. 配置 `.env` 文件
4. 双击exe文件运行

## 📝 文件维护说明

- **请勿直接修改**: `dist/`, `logs/`, `__pycache__/`
- **核心配置**: `.env`, `requirements.txt`
- **用户数据**: `punch_records/`, `screenshots/`
- **开发文档**: `docs/` 目录中的所有文件

---

这种目录结构使项目更加清晰、易于维护，并且便于新用户快速上手使用。