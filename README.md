# 自动打卡系统

这是一个基于 Python 的自动打卡系统，通过图像识别和自动化操作实现自动登录和打卡功能，并集成了 Telegram 机器人进行远程控制和通知。

## 功能特性

- 自动登录系统
- 自动识别并点击打卡按钮
- Telegram 机器人远程控制
- 实时打卡状态通知
- 异常情况自动提醒
- 支持上班和下班打卡

## 环境要求

- Python 3.7+
- Windows 系统
- Microsoft Edge 浏览器
- Tesseract-OCR

## 依赖包

```
python-telegram-bot
opencv-python
pyautogui
pytesseract
schedule
python-dotenv
pyperclip
pillow
```

## 安装步骤

1. 克隆项目到本地
2. 安装所需依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 安装 Tesseract-OCR（默认路径：`C:\Program Files\Tesseract-OCR\tesseract.exe`）
4. 创建 `.env` 文件并配置以下环境变量：
   ```
   TELEGRAM_BOT_TOKEN=你的Telegram机器人token
   TELEGRAM_CHAT_ID=你的Telegram聊天ID
   LOGIN_USERNAME=登录用户名
   LOGIN_PASSWORD=登录密码
   LOGIN_URL=打卡系统登录地址
   TESSERACT_PATH=Tesseract-OCR安装路径（可选）
   ```

## 使用说明

### 启动系统

运行以下命令启动系统：

```bash
python main.py
```

### Telegram 机器人命令

- `/start` - 显示欢迎信息和可用命令
- `/punch_in` - 执行上班打卡
- `/punch_out` - 执行下班打卡
- `/status` - 查看系统状态

### 注意事项

1. 确保系统运行时保持屏幕解锁
2. 需要将模板图片放在 `templates` 目录下：
   - `input_field.png` - 输入框模板
   - `username_label.png` - 用户名标签模板
   - `login_button.png` - 登录按钮模板
   - `punch_button.png` - 打卡按钮模板
   - `safe_place.png` - 安全点击区域模板

## 错误处理

系统会自动重试失败的操作，并通过 Telegram 发送错误通知。如遇到问题：

1. 检查环境变量配置
2. 确认模板图片是否正确
3. 查看控制台输出的错误信息
