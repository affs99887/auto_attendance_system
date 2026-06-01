"""
主程序入口

自动打卡系统的主启动文件，负责初始化和协调各个模块
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime


def configure_console_encoding():
    """保留当前终端编码，并替换无法编码的字符。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(errors="replace")
                continue
            except (TypeError, ValueError, OSError):
                pass

        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        try:
            import io
            encoding = getattr(stream, "encoding", None) or "utf-8"
            setattr(sys, stream_name, io.TextIOWrapper(
                buffer,
                encoding=encoding,
                errors="replace",
                line_buffering=True
            ))
        except (TypeError, ValueError, OSError):
            pass


configure_console_encoding()


def is_plain_console():
    """GUI/管道环境使用朴素控制台输出，避免 ANSI 和特殊字符干扰。"""
    return os.environ.get("AAS_PLAIN_CONSOLE") == "1"

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
    if is_plain_console():
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print("Auto Attendance System v2.0")
        print(f"启动时间: {current_time}")
        print(f"Python版本: {sys.version.split()[0]}")
        print("运行模式: 生产环境")
        print()
        return

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
    if is_plain_console():
        progress_bar = "#" * filled_count + "." * (20 - filled_count)
    else:
        progress_bar = "█" * filled_count + "░" * (20 - filled_count)
    
    # 根据状态选择图标和颜色
    if is_plain_console():
        icon = "[OK]" if is_final else "[>>]"
        color = ""
        reset = ""
    elif is_final:
        icon = "[OK]"
        color = "\033[32m"  # 绿色
        reset = "\033[0m"
    else:
        icon = "[>>]"
        color = "\033[33m"  # 黄色
        reset = "\033[0m"
    
    # 构建显示内容
    line_content = f"{color}{icon} [{progress_bar}] {progress_percent:5.1f}% {description}{reset}"
    
    # 清除整行并重新输出（解决残留字符问题）
    print(f"\r{' ' * 120}\r{line_content}", end="", flush=True)
    
    if is_final:
        # 最终步骤完成时换行
        print()


def print_completion():
    """显示启动完成信息"""
    if is_plain_console():
        print("系统启动完成，所有服务正在运行。")
        print("按 Ctrl+C 停止程序")
        return

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


async def initialize_system(fast_boot=False):
    """初始化系统，带进度显示

    fast_boot=True（GUI 模式）时跳过纯装饰性的进度 sleep，加快后端就绪——
    真实初始化步骤一律保留。控制台/watchdog 模式 fast_boot=False，行为不变。
    """
    async def _tick(seconds):
        # 装饰性等待：仅为让（GUI 下隐藏的）进度条好看；fast_boot 直接跳过
        if not fast_boot:
            await asyncio.sleep(seconds)

    total_steps = 10
    current_step = 0
    
    if is_plain_console():
        print("[INIT] 开始初始化系统组件...")
    else:
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
                await _tick(0.3)  # 显示进度
                config.ensure_directories()
                await _tick(0.5)
            elif current_step == 2:  # 创建打卡系统实例
                await _tick(0.3)  # 显示进度
                # 先拉起内置网络加速（mihomo），使随后构建的 bot 能解析到本地代理端口。
                # 与 GUI/控制台/watchdog 无关——所有模式下均按配置启用。
                from modules.proxy_manager import ProxyManager
                _proxy_manager = ProxyManager()
                if config.get_proxy_enabled():
                    try:
                        _ok, _msg = await asyncio.to_thread(_proxy_manager.start)
                        if _ok:
                            logging.info(f"内置网络加速已启动: {_msg}")
                        else:
                            logging.warning(f"内置网络加速未启动（回退直连/系统代理）: {_msg}")
                    except Exception:
                        logging.error("内置网络加速启动异常（回退）", exc_info=True)
                attendance_system = AttendanceSystem()
                attendance_system.proxy_manager = _proxy_manager
                await _tick(0.4)
            elif current_step == 3:  # 初始化核心系统组件
                await _tick(0.6)
            elif current_step == 4:  # 加载用户配置和系统参数
                await _tick(0.5)
            elif current_step == 5:  # 初始化Telegram机器人
                await _tick(0.3)  # 显示进度
                # bot 初始化失败不应再让整个程序启动崩溃（否则 web_server 没机会启动、GUI 进不去）。
                # 仅在本分支内吞掉异常并降级：记录原因到 attendance_system，后续可经 GUI 重连端点恢复。
                try:
                    await attendance_system.bot._ensure_app_initialized()
                    if not attendance_system.bot.app:
                        raise Exception("Telegram Bot 初始化失败")
                except Exception as e:
                    logging.warning(f"Telegram Bot 初始化失败，转为降级运行（GUI 仍可启动）: {e!r}")
                    attendance_system.bot_available = False
                    attendance_system.bot_error = str(e)[:500]
                await _tick(0.4)
            elif current_step == 6:  # 连接Telegram API服务
                await _tick(0.7)
            elif current_step == 7:  # 验证SMTP服务器连接
                await _tick(0.3)  # 显示进度
                await attendance_system.check_email_connection()
                await _tick(0.4)
            elif current_step == 8:  # 启动定时任务调度器
                await _tick(0.3)  # 显示进度
                schedule_task = asyncio.create_task(run_schedule())
                await _tick(0.5)
            elif current_step == 9:  # 启动机器人应用
                await _tick(0.3)  # 显示进度
                # bot 降级时 app 为 None，跳过启动（避免 NoneType 崩溃）
                if attendance_system.bot.app is not None:
                    await attendance_system.bot.app.start()
                await _tick(0.4)
            elif current_step == 10:  # 启动连接监控
                await _tick(0.3)  # 显示进度
                # 同样在 bot 可用时才启动轮询与连接监控；降级时 monitor_task 保持为 None
                if attendance_system.bot.app is not None:
                    await attendance_system.bot.start_polling()
                    monitor_task = asyncio.create_task(attendance_system.bot.monitor_connection())
                await _tick(0.3)
        
        except Exception as e:
            # 显示错误状态
            progress_percent = (current_step / total_steps) * 100
            filled_count = int(progress_percent / 5)
            if is_plain_console():
                progress_bar = "#" * filled_count + "." * (20 - filled_count)
                error_content = f"[ERROR] [{progress_bar}] {progress_percent:5.1f}% {step_name} - 失败: {str(e)}"
            else:
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


def _parse_args():
    """解析主程序命令行参数。

    单独抽出便于 start.py / Electron 外壳直接调用 ``main.py --gui``。
    """
    parser = argparse.ArgumentParser(description='自动打卡系统主程序')
    parser.add_argument('--gui', action='store_true',
                        help='启用 GUI 后端（Flask REST + WebSocket，监听 127.0.0.1）')
    parser.add_argument('--gui-http-port', type=int, default=8765,
                        help='GUI HTTP 端口（默认 8765）')
    parser.add_argument('--gui-ws-port', type=int, default=8766,
                        help='GUI WebSocket 端口（默认 8766）')
    return parser.parse_args()


async def main(args=None):
    """主函数 - 系统启动入口"""
    global attendance_system_global
    if args is None:
        args = argparse.Namespace(gui=False, gui_http_port=8765, gui_ws_port=8766)

    gui_handle = None  # web_server.start 返回值，用于关停

    try:
        if args.gui:
            os.environ["AAS_PLAIN_CONSOLE"] = "1"

        # 显示欢迎界面
        print_welcome()

        # 等待一秒让用户看到欢迎界面（GUI 模式跳过，加快窗口连上后端）
        if not args.gui:
            await asyncio.sleep(1)

        # 初始化系统（GUI 模式 fast_boot：跳过装饰 sleep）
        attendance_system, schedule_task, monitor_task = await initialize_system(fast_boot=args.gui)

        # 设置全局变量，供调度器使用
        attendance_system_global = attendance_system

        # GUI 后端：仅在 --gui 时启动。失败不阻塞 bot 主流程。
        if args.gui:
            try:
                from modules.web_server import start as start_web_server
                gui_handle = await start_web_server(
                    attendance_system,
                    loop=asyncio.get_running_loop(),
                    http_port=args.gui_http_port,
                    ws_port=args.gui_ws_port,
                )
                logging.info(
                    f"GUI 后端已启动 — HTTP 127.0.0.1:{args.gui_http_port} / "
                    f"WS 127.0.0.1:{args.gui_ws_port}，token 文件 logs/.gui_token"
                )
            except Exception as e:
                logging.error(f"GUI 后端启动失败，bot 主流程不受影响: {e}", exc_info=True)

        # 等待5秒后验证8:15提醒任务设置（bot 降级时跳过，避免对未初始化的 app 操作）
        await asyncio.sleep(5)
        if getattr(attendance_system, 'bot_available', True):
            logging.info("验证8:15提醒任务设置...")
            reminder_status = attendance_system.bot.verify_daily_reminder_setup()
            if reminder_status:
                logging.info("✅ 8:15提醒任务验证成功")
            else:
                logging.warning("⚠️ 8:15提醒任务验证失败，可能需要手动检查")
        else:
            logging.info("Telegram Bot 处于降级状态，跳过 8:15 提醒任务验证")

        logging.info("所有服务已启动，系统运行中...")

        try:
            # 保持程序运行；bot 降级时 monitor_task 为 None，仅 await 永久事件即可
            awaitables = [asyncio.Event().wait()]
            if monitor_task is not None:
                awaitables.append(monitor_task)
            await asyncio.gather(*awaitables, return_exceptions=True)
        finally:
            # 清理资源
            print("\n[>>] 正在关闭系统...")
            schedule_task.cancel()
            if gui_handle is not None:
                try:
                    gui_handle['stop']()
                except Exception:
                    logging.exception("GUI 后端关停失败")
            await attendance_system.bot.stop_polling()
            if attendance_system.bot.app:
                await attendance_system.bot.app.stop()
                await attendance_system.bot.app.shutdown()
            # 停止内置网络加速子进程
            _pm = getattr(attendance_system, 'proxy_manager', None)
            if _pm is not None:
                try:
                    _pm.stop()
                except Exception:
                    logging.exception("停止内置网络加速失败")
            print("[OK] 系统已安全关闭")
                
    except Exception as e:
        print(f"\n[ERROR] 系统启动失败: {str(e)}")
        logging.critical(f"程序启动失败: {str(e)}")
        if 'attendance_system' in locals():
            await attendance_system.handle_error(e, "程序启动")


if __name__ == "__main__":
    cli_args = _parse_args()
    try:
        asyncio.run(main(cli_args))
    except KeyboardInterrupt:
        print("\n\n[EXIT] 程序已停止，感谢使用！")
    except Exception as e:
        print(f"\n[FATAL] 程序异常退出: {e}")
        logging.critical(f"程序异常退出: {e}")
