# 自动打卡系统

这是一个基于图像识别的自动打卡系统，可以帮助你实现自动登录和打卡操作。

## 功能特点

- 自动登录系统
- 定时上下班打卡
- 基于图像识别的界面操作
- 异常处理和日志记录

## 环境要求

- Python 3.8+
- Tesseract OCR
- Chrome/Firefox 浏览器

## 安装步骤

1. 安装 Tesseract OCR

   - 从[官方网站](https://github.com/UB-Mannheim/tesseract/wiki)下载并安装
   - 确保将安装路径添加到系统环境变量

2. 安装 Python 依赖

   ```bash
   pip install -r requirements.txt
   ```

3. 配置环境变量

   - 复制 `.env.example` 文件并重命名为 `.env`
   - 修改 `.env` 文件中的配置信息

4. 准备模板图片
   - 在 `templates` 目录下添加以下截图：
     - username_field.png (用户名输入框)
     - password_field.png (密码输入框)
     - login_button.png (登录按钮)
     - punch_button.png (打卡按钮)

## 使用方法

1. 运行程序

   ```bash
   python main.py
   ```

2. 程序会在工作日的以下时间自动执行打卡：
   - 上班打卡：09:00
   - 下班打卡：18:00

## 注意事项

1. 确保电脑在打卡时间段保持开机状态
2. 不要遮挡或最小化打卡系统界面
3. 建议先手动测试确保配置正确
4. 定期检查日志确保系统正常运行

## 常见问题

1. 如果出现识别失败，请检查：

   - 模板图片是否清晰
   - 屏幕分辨率是否发生变化
   - 网络连接是否正常

2. 如果打卡失败，请检查：
   - 环境变量配置是否正确
   - 系统登录信息是否有效
   - Tesseract OCR 是否正确安装
