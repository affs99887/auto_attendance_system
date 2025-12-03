"""
主程序入口

自动打卡系统的主启动文件，负责初始化和协调各个模块
"""

import asyncio
import logging
import sys
import time
from datetime import datetime

# 导入colorama支持Windows ANSI颜色
import colorama
from colorama import init

# 初始化colorama以支持Windows上的ANSI转义序列
init()

# 导入重构后的模块
from modules.config import config
from modules.attendance_system import AttendanceSystem
from modules.schedule_manager import run_schedule


# 全局变量
attendance_system_global = None


def print_welcome():
    """显示欢迎界面"""
    welcome_art = f"""\033[34m╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║      \033[38;5;39m██████╗ \033[38;5;45m██╗   ██╗\033[38;5;51m████████╗\033[38;5;87m ██████╗ \033[38;5;123m   ██████╗ \033[38;5;159m██╗   ██╗\033[38;5;195m███╗   ██╗\033[34m     ║
║      \033[38;5;39m██╔══██╗\033[38;5;45m██║   ██║\033[38;5;51m╚══██╔══╝\033[38;5;87m██╔═══██╗\033[38;5;123m   ██╔══██╗\033[38;5;159m██║   ██║\033[38;5;195m████╗  ██║\033[34m     ║
║      \033[38;5;39m███████║\033[38;5;45m██║   ██║\033[38;5;51m   ██║   \033[38;5;87m██║   ██║\033[38;5;123m   ██████╔╝\033[38;5;159m██║   ██║\033[38;5;195m██╔██╗ ██║\033[34m     ║
║      \033[38;5;39m██╔══██║\033[38;5;45m██║   ██║\033[38;5;51m   ██║   \033[38;5;87m██║   ██║\033[38;5;123m   ██╔══██╗\033[38;5;159m██║   ██║\033[38;5;195m██║╚██╗██║\033[34m     ║
║      \033[38;5;39m██║  ██║\033[38;5;45m╚██████╔╝\033[38;5;51m   ██║   \033[38;5;87m╚██████╔╝\033[38;5;123m   ██║  ██║\033[38;5;159m╚██████╔╝\033[38;5;195m██║ ╚████║\033[34m     ║
║      \033[38;5;39m╚═╝  ╚═╝\033[38;5;45m ╚═════╝ \033[38;5;51m   ╚═╝   \033[38;5;87m ╚═════╝ \033[38;5;123m   ╚═╝  ╚═╝\033[38;5;159m ╚═════╝ \033[38;5;195m╚═╝  ╚═══╝\033[34m     ║
║                                                                              ║
║                        \033[38;5;39m自\033[38;5;45m动\033[38;5;51m打\033[38;5;87m卡\033[38;5;123m系\033[38;5;159m统\033[38;5;39m \033[38;5;45mv\033[38;5;51m2\033[38;5;87m.\033[38;5;123m0\033[34m                            ║
║                     \033[38;5;39mA\033[38;5;45mu\033[38;5;51mt\033[38;5;87mo\033[38;5;123m \033[38;5;159mA\033[38;5;39mt\033[38;5;45mt\033[38;5;51me\033[38;5;87mn\033[38;5;123md\033[38;5;159ma\033[38;5;39mn\033[38;5;45mc\033[38;5;51me\033[38;5;87m \033[38;5;123mS\033[38;5;159my\033[38;5;39ms\033[38;5;45mt\033[38;5;51me\033[38;5;87mm\033[34m                      ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝\033[0m
    """
    
    # 清屏
    print("\033[2J\033[H", end="")
    
    # 打印欢迎界面（已经包含了颜色）
    print(welcome_art)
    
    # 系统信息 - 也添加渐变色效果
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\033[38;5;39m┌─ \033[38;5;45m系\033[38;5;51m统\033[38;5;87m信\033[38;5;123m息\033[38;5;159m ─────────────────────────────────────────────────────────────────┐\033[0m")
    print(f"\033[38;5;39m│ * \033[38;5;45m启动时间: \033[38;5;51m{current_time:<54} \033[38;5;39m│\033[0m")
    print(f"\033[38;5;39m│ * \033[38;5;45mPython版本: \033[38;5;51m{sys.version.split()[0]:<52} \033[38;5;39m│\033[0m")
    print(f"\033[38;5;39m│ * \033[38;5;45m运行模式: \033[38;5;51m生产环境{'':<52} \033[38;5;39m│\033[0m")
    print(f"\033[38;5;39m└────────────────────────────────────────────────────────────────────────────┘\033[0m")
    print()


def print_progress(step_num, total_steps, description, is_final=False):
    """在同一行刷新进度信息"""
    # 计算进度百分比
    progress_percent = (step_num / total_steps) * 100
    
    # 创建进度条（使用20个字符长度）
    filled_count = int(progress_percent / 5)  # 每5%一个字符
    progress_bar = "█" * filled_count + "░" * (20 - filled_count)
    
    # 根据状态选择图标和颜色
    if is_final:
        icon = "[OK]"
        color = "\033[32m"  # 绿色
    else:
        icon = "[>>]"
        color = "\033[33m"  # 黄色
    
    # 构建显示内容
    line_content = f"{color}{icon} [{progress_bar}] {progress_percent:5.1f}% {description}\033[0m"
    
    # 清除整行并重新输出（解决残留字符问题）
    print(f"\r{' ' * 120}\r{line_content}", end="", flush=True)
    
    if is_final:
        # 最终步骤完成时换行
        print()


def print_completion():
    """显示启动完成信息"""
    completion_art = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║      >> 系统启动完成！All Services Running Successfully! <<                ║
║                                                                              ║
║  [*] Telegram Bot: 已连接并监听命令                                        ║
║  [*] 邮件服务: 连接正常                                                     ║
║  [*] 定时任务: 已加载并运行                                                 ║
║  [*] 状态监控: 已启动                                                       ║
║                                                                              ║
║  [!] 使用说明:                                                               ║
║     发送 /help 到Telegram获取命令帮助                                       ║
║     发送 /status 查看系统状态                                               ║
║     发送 /punch_in 执行上班打卡                                             ║
║     发送 /punch_out 执行下班打卡                                            ║
║                                                                              ║
║  按 Ctrl+C 停止程序                                                         ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """
    print("\033[32m" + completion_art + "\033[0m")


async def initialize_system():
    """初始化系统，带进度显示"""
    total_steps = 10
    current_step = 0
    
    print(f"\033[34m[INIT] 开始初始化系统组件...\033[0m")
    print()
    
    # 定义所有步骤
    steps = [
        ("初始化配置模块", lambda: config.ensure_directories()),
        ("创建打卡系统实例", None),  # 特殊处理
        ("初始化核心系统组件", None),  # 占位步骤
        ("加载用户配置和系统参数", None),  # 占位步骤
        ("初始化Telegram机器人", None),  # 特殊处理
        ("连接Telegram API服务", None),  # 占位步骤
        ("验证SMTP服务器连接", None),  # 特殊处理
        ("启动定时任务调度器", None),  # 特殊处理
        ("启动机器人应用", None),  # 特殊处理
        ("启动连接监控", None),  # 特殊处理
    ]
    
    attendance_system = None
    schedule_task = None
    monitor_task = None
    
    for i, (step_name, step_func) in enumerate(steps):
        current_step = i + 1
        is_final = (current_step == total_steps)
        
        # 显示当前步骤
        print_progress(current_step, total_steps, step_name, is_final=False)
        
        try:
            if current_step == 1:  # 初始化配置模块
                await asyncio.sleep(0.3)  # 显示进度
                config.ensure_directories()
                await asyncio.sleep(0.5)
            elif current_step == 2:  # 创建打卡系统实例
                await asyncio.sleep(0.3)  # 显示进度
                attendance_system = AttendanceSystem()
                await asyncio.sleep(0.4)
            elif current_step == 3:  # 初始化核心系统组件
                await asyncio.sleep(0.6)
            elif current_step == 4:  # 加载用户配置和系统参数
                await asyncio.sleep(0.5)
            elif current_step == 5:  # 初始化Telegram机器人
                await asyncio.sleep(0.3)  # 显示进度
                await attendance_system.bot._ensure_app_initialized()
                if not attendance_system.bot.app:
                    raise Exception("Telegram Bot 初始化失败")
                await asyncio.sleep(0.4)
            elif current_step == 6:  # 连接Telegram API服务
                await asyncio.sleep(0.7)
            elif current_step == 7:  # 验证SMTP服务器连接
                await asyncio.sleep(0.3)  # 显示进度
                await attendance_system.check_email_connection()
                await asyncio.sleep(0.4)
            elif current_step == 8:  # 启动定时任务调度器
                await asyncio.sleep(0.3)  # 显示进度
                schedule_task = asyncio.create_task(run_schedule())
                await asyncio.sleep(0.5)
            elif current_step == 9:  # 启动机器人应用
                await asyncio.sleep(0.3)  # 显示进度
                await attendance_system.bot.app.start()
                await asyncio.sleep(0.4)
            elif current_step == 10:  # 启动连接监控
                await asyncio.sleep(0.3)  # 显示进度
                await attendance_system.bot.start_polling()
                monitor_task = asyncio.create_task(attendance_system.bot.monitor_connection())
                await asyncio.sleep(0.3)
        
        except Exception as e:
            # 显示错误状态
            progress_percent = (current_step / total_steps) * 100
            filled_count = int(progress_percent / 5)
            progress_bar = "█" * filled_count + "░" * (20 - filled_count)
            error_content = f"\033[31m[ERROR] [{progress_bar}] {progress_percent:5.1f}% {step_name} - 失败: {str(e)}\033[0m"
            print(f"\r{' ' * 120}\r{error_content}")
            logging.error(f"初始化步骤 {current_step} 失败: {e}")
            raise
    
    # 显示最终完成状态
    print_progress(total_steps, total_steps, "所有组件初始化完成", is_final=True)
    
    print()
    print_completion()
    
    return attendance_system, schedule_task, monitor_task


async def main():
    """主函数 - 系统启动入口"""
    global attendance_system_global
    
    try:
        # 显示欢迎界面
        print_welcome()
        
        # 等待一秒让用户看到欢迎界面
        await asyncio.sleep(1)
        
        # 初始化系统
        attendance_system, schedule_task, monitor_task = await initialize_system()
        
        # 设置全局变量，供调度器使用
        attendance_system_global = attendance_system
        
        # 等待5秒后验证8:15提醒任务设置
        await asyncio.sleep(5)
        logging.info("验证8:15提醒任务设置...")
        reminder_status = attendance_system.bot.verify_daily_reminder_setup()
        if reminder_status:
            logging.info("✅ 8:15提醒任务验证成功")
        else:
            logging.warning("⚠️ 8:15提醒任务验证失败，可能需要手动检查")
        
        logging.info("所有服务已启动，系统运行中...")

        try:
            # 保持程序运行
            await asyncio.gather(
                asyncio.Event().wait(),
                monitor_task,
                return_exceptions=True
            )
        finally:
            # 清理资源
            print("\n[>>] 正在关闭系统...")
            schedule_task.cancel()
            await attendance_system.bot.stop_polling()
            if attendance_system.bot.app:
                await attendance_system.bot.app.stop()
                await attendance_system.bot.app.shutdown()
            print("[OK] 系统已安全关闭")
                
    except Exception as e:
        print(f"\n[ERROR] 系统启动失败: {str(e)}")
        logging.critical(f"程序启动失败: {str(e)}")
        if 'attendance_system' in locals():
            await attendance_system.handle_error(e, "程序启动")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n[EXIT] 程序已停止，感谢使用！")
    except Exception as e:
        print(f"\n[FATAL] 程序异常退出: {e}")
        logging.critical(f"程序异常退出: {e}")