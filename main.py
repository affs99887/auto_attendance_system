"""
主程序入口

自动打卡系统的主启动文件，负责初始化和协调各个模块
"""

import asyncio
import logging
from datetime import datetime

# 导入重构后的模块
from modules.config import config
from modules.attendance_system import AttendanceSystem
from modules.schedule_manager import run_schedule


# 全局变量
attendance_system_global = None


async def main():
    """主函数 - 系统启动入口"""
    global attendance_system_global
    
    try:
        # 创建打卡系统实例
        attendance_system = AttendanceSystem()
        
        # 设置全局变量，供调度器使用
        attendance_system_global = attendance_system
        
        # 启动系统
        logging.info("=== 自动打卡系统启动 ===")
        logging.info(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 确保目录存在
        config.ensure_directories()
        
        # 初始化Telegram机器人
        await attendance_system.bot._ensure_app_initialized()
        
        if not attendance_system.bot.app:
            logging.error("Telegram Bot 初始化失败")
            return

        # 检查邮箱连接
        await attendance_system.check_email_connection()

        # 创建调度任务
        schedule_task = asyncio.create_task(run_schedule())

        try:
            # 启动机器人
            await attendance_system.bot.app.start()

            # 启动轮询
            await attendance_system.bot.start_polling()

            # 启动连接监控
            monitor_task = asyncio.create_task(attendance_system.bot.monitor_connection())

            logging.info("所有服务已启动，系统运行中...")

            # 保持程序运行
            await asyncio.gather(
                asyncio.Event().wait(),
                monitor_task,
                return_exceptions=True
            )
        finally:
            # 清理资源
            schedule_task.cancel()
            await attendance_system.bot.stop_polling()
            if attendance_system.bot.app:
                await attendance_system.bot.app.stop()
                await attendance_system.bot.app.shutdown()
                
    except Exception as e:
        logging.critical(f"程序启动失败: {str(e)}")
        if attendance_system:
            await attendance_system.handle_error(e, "程序启动")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已停止")
    except Exception as e:
        print(f"\n程序异常退出: {e}")
        logging.critical(f"程序异常退出: {e}")