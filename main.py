import cv2
import pyautogui
import pytesseract
import schedule
import time
from datetime import datetime
from PIL import Image
import os
from dotenv import load_dotenv
import pyperclip
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 加载环境变量
load_dotenv()

class TelegramBot:
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.app = None
        self.attendance_system = None

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/start命令"""
        await update.message.reply_text(
            "欢迎使用打卡机器人！\n"
            "支持的命令：\n"
            "/punch_in - 上班打卡\n"
            "/punch_out - 下班打卡\n"
            "/status - 查看状态"
        )

    async def punch_in_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理上班打卡命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return
        
        await update.message.reply_text("正在执行上班打卡...")
        await self.attendance_system.punch_in()

    async def punch_out_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理下班打卡命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return
        
        await update.message.reply_text("正在执行下班打卡...")
        await self.attendance_system.punch_out()

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理状态查询命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return
        
        next_run = schedule.next_run()
        status_text = (
            "打卡系统状态：\n"
            f"下次计划任务时间：{next_run}\n"
            "自动打卡时间：\n"
            "- 上班：每天 08:55\n"
            "- 下班：每天 17:55"
        )
        await update.message.reply_text(status_text)

    async def send_message(self, title, content):
        """发送Telegram消息"""
        if not self.app:
            return False
            
        try:
            message = f"{title}\n\n{content}"
            await self.app.bot.send_message(chat_id=self.chat_id, text=message)
            print("Telegram消息发送成功")
            return True
        except Exception as e:
            print(f"发送Telegram消息时发生错误：{str(e)}")
            return False

    def run(self, attendance_system):
        """运行Telegram机器人"""
        self.attendance_system = attendance_system
        self.app = Application.builder().token(self.token).build()
        
        # 注册命令处理器
        self.app.add_handler(CommandHandler('start', self.start_command))
        self.app.add_handler(CommandHandler('punch_in', self.punch_in_command))
        self.app.add_handler(CommandHandler('punch_out', self.punch_out_command))
        self.app.add_handler(CommandHandler('status', self.status_command))
        
        # 启动机器人
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

class AttendanceSystem:
    def __init__(self):
        # 设置pytesseract路径
        pytesseract.pytesseract.tesseract_cmd = os.getenv('TESSERACT_PATH', r'C:\Program Files\Tesseract-OCR\tesseract.exe')
        
        # 配置信息
        self.username = os.getenv('LOGIN_USERNAME')
        self.password = os.getenv('LOGIN_PASSWORD')
        self.login_url = os.getenv('LOGIN_URL')
        
        # 创建Telegram机器人实例
        self.bot = TelegramBot()
        
        # 截图保存路径
        self.screenshot_path = 'temp_screenshot.png'
        
        # 添加重试次数配置
        self.max_retries = 3
        self.retry_interval = 5  # 秒
        
        self.safe_place_path = 'templates/safe_place.png'  # 添加安全位置图片路径

    async def send_notification(self, title, content):
        """发送通知"""
        return await self.bot.send_message(title, content)

    def take_screenshot(self):
        """截取屏幕"""
        screenshot = pyautogui.screenshot()
        screenshot.save(self.screenshot_path)
        return cv2.imread(self.screenshot_path)
    
    def find_element_by_image(self, template_path, threshold=0.8):
        """通过图像模板匹配找到元素位置，增加重试机制"""
        for attempt in range(self.max_retries):
            screen = self.take_screenshot()
            template = cv2.imread(template_path)
            
            if template is None:
                raise FileNotFoundError(f"模板图片未找到: {template_path}")
                
            # 获取模板尺寸
            template_height, template_width = template.shape[:2]
            
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            
            if max_val >= threshold:
                # 返回元素中心点坐标
                center_x = max_loc[0] + template_width // 2
                center_y = max_loc[1] + template_height // 2
                return (center_x, center_y)
                
            if attempt < self.max_retries - 1:
                print(f"未找到元素 {template_path}，{attempt + 1} 次重试...")
                time.sleep(self.retry_interval)
                
        return None
    
    def find_element_with_label(self, template_path, label_template_path, threshold=0.8):
        """通过标签和输入框的组合来定位元素"""
        for attempt in range(self.max_retries):
            screen = self.take_screenshot()
            
            # 先找标签位置
            label_template = cv2.imread(label_template_path)
            if label_template is None:
                raise FileNotFoundError(f"标签模板图片未找到: {label_template_path}")
            
            label_result = cv2.matchTemplate(screen, label_template, cv2.TM_CCOEFF_NORMED)
            label_min_val, label_max_val, label_min_loc, label_max_loc = cv2.minMaxLoc(label_result)
            
            if label_max_val >= threshold:
                # 找到标签后，在其右侧区域查找输入框
                input_template = cv2.imread(template_path)
                if input_template is None:
                    raise FileNotFoundError(f"输入框模板图片未找到: {template_path}")
                
                # 获取输入框模板尺寸
                input_height, input_width = input_template.shape[:2]
                
                # 计算查找区域（标签右侧）
                label_width = label_template.shape[1]
                search_region = screen[
                    max(0, label_max_loc[1] - 10):min(screen.shape[0], label_max_loc[1] + input_template.shape[0] + 10),
                    label_max_loc[0] + label_width:min(screen.shape[1], label_max_loc[0] + label_width + 300)
                ]
                
                if search_region.size > 0:
                    result = cv2.matchTemplate(search_region, input_template, cv2.TM_CCOEFF_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                    
                    if max_val >= threshold:
                        # 返回输入框中心点的全局坐标
                        center_x = label_max_loc[0] + label_width + max_loc[0] + input_width // 2
                        center_y = label_max_loc[1] + max_loc[1] + input_height // 2
                        return (center_x, center_y)
            
            if attempt < self.max_retries - 1:
                print(f"未找到元素组合，{attempt + 1} 次重试...")
                time.sleep(self.retry_interval)
        
        return None
    
    def input_text(self, text):
        """使用剪贴板输入文本"""
        pyperclip.copy(text)  # 复制文本到剪贴板
        pyautogui.hotkey('ctrl', 'v')  # 粘贴
        time.sleep(0.5)  # 等待粘贴完成
    
    def click_safe_place(self):
        """点击安全位置"""
        print("查找安全位置...")
        safe_loc = self.find_element_by_image(self.safe_place_path)
        if safe_loc:
            print("找到安全位置，进行点击...")
            pyautogui.click(safe_loc)
            time.sleep(0.5)
            return True
        print("未找到安全位置")
        return False
    
    def login(self):
        """登录系统"""
        try:
            # 使用 Edge 打开新窗口
            os.system('start msedge --new-window "{}"'.format(self.login_url))
            time.sleep(5)  # 等待页面加载
            
            print("开始查找用户名输入框...")
            username_loc = self.find_element_with_label(
                'templates/input_field.png',
                'templates/username_label.png'
            )
            if username_loc:
                print("找到用户名输入框，开始输入...")
                pyautogui.click(username_loc)
                self.input_text(self.username)  # 使用剪贴板输入
                print(f"用户名 {self.username} 输入完成")
            else:
                print("未找到用户名输入框")
                return False
            
            time.sleep(1)
            
            # 点击安全位置
            if not self.click_safe_place():
                print("无法找到安全位置，继续执行...")
            
            print("开始查找登录按钮...")
            login_button_loc = self.find_element_by_image('templates/login_button.png')
            if login_button_loc:
                print("找到登录按钮，点击登录...")
                pyautogui.click(login_button_loc)
                print("登录按钮点击完成")
            else:
                print("未找到登录按钮")
                return False
            
            time.sleep(5)  # 等待登录完成
            return True
            
        except Exception as e:
            print(f"登录过程发生错误: {str(e)}")
            return False

    async def punch_in(self):
        """上班打卡"""
        try:
            print("开始登录流程...")
            if self.login():
                print("登录成功，等待系统加载...")
                time.sleep(3)
                
                print("开始查找打卡按钮...")
                punch_button_loc = self.find_element_by_image('templates/punch_button.png')
                if punch_button_loc:
                    print("找到打卡按钮，开始打卡...")
                    pyautogui.click(punch_button_loc)
                    success_msg = f"上班打卡成功 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    print(success_msg)
                    await self.send_notification("打卡成功", success_msg)
                else:
                    error_msg = "未找到打卡按钮"
                    print(error_msg)
                    await self.send_notification("打卡失败", error_msg)
            else:
                error_msg = "登录失败，无法进行打卡"
                print(error_msg)
                await self.send_notification("打卡失败", error_msg)
        except Exception as e:
            error_msg = f"打卡过程发生错误: {str(e)}"
            print(error_msg)
            await self.send_notification("打卡异常", error_msg)

    async def punch_out(self):
        """下班打卡"""
        try:
            if self.login():
                punch_button_loc = self.find_element_by_image('templates/punch_button.png')
                if punch_button_loc:
                    pyautogui.click(punch_button_loc)
                    success_msg = f"下班打卡成功 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    print(success_msg)
                    await self.send_notification("打卡成功", success_msg)
                else:
                    error_msg = "未找到打卡按钮"
                    print(error_msg)
                    await self.send_notification("打卡失败", error_msg)
            else:
                error_msg = "登录失败，无法进行打卡"
                print(error_msg)
                await self.send_notification("打卡失败", error_msg)
        except Exception as e:
            error_msg = f"下班打卡失败: {str(e)}"
            print(error_msg)
            await self.send_notification("打卡异常", error_msg)

    def cleanup(self):
        """清理临时文件"""
        if os.path.exists(self.screenshot_path):
            try:
                os.remove(self.screenshot_path)
            except Exception as e:
                print(f"清理临时文件失败: {str(e)}")

async def run_schedule():
    """运行定时任务"""
    while True:
        schedule.run_pending()
        await asyncio.sleep(1)

async def main():
    attendance_system = AttendanceSystem()
    
    print("自动打卡系统已启动...")
    print("\n您可以通过Telegram机器人控制打卡：")
    print("/punch_in - 执行上班打卡")
    print("/punch_out - 执行下班打卡")
    print("/status - 查看系统状态")
    
    # 初始化 Telegram 机器人
    app = Application.builder().token(attendance_system.bot.token).build()
    attendance_system.bot.app = app
    attendance_system.bot.attendance_system = attendance_system
    
    # 注册命令处理器
    app.add_handler(CommandHandler('start', attendance_system.bot.start_command))
    app.add_handler(CommandHandler('punch_in', attendance_system.bot.punch_in_command))
    app.add_handler(CommandHandler('punch_out', attendance_system.bot.punch_out_command))
    app.add_handler(CommandHandler('status', attendance_system.bot.status_command))
    
    # 启动机器人
    await app.initialize()
    await app.start()
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.run(main())