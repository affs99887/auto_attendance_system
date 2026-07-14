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

# 单实例锁文件句柄（全局持有，进程存活期间不释放；进程退出由 OS 自动释放）
_instance_lock_handle = None


def acquire_single_instance_lock():
    """获取单实例独占锁，防止重复启动 main.py。

    重复启动会导致两个进程用同一 bot token 同时 getUpdates（Telegram 409 互踢），
    且定时打卡任务在两份进程里各跑一遍、对同一账号重复打卡。这里用锁文件 + PID 校验：
    - 取到独占锁：写入当前 PID，返回 True；
    - 取不到（已有实例持锁）：读出占用 PID 提示后返回 False，由调用方退出；
    - 若锁文件残留但持有者已不在（旧进程崩溃未释放），OS 层独占锁本就不会拦截，可正常抢占。

    [M70] 锁必须锚定到“真正被争用的资源”——Telegram bot token 本身，而非脚本目录、也不是 CWD。
    config.py 现已显式从 AAS_DATA_DIR（回退 CWD）加载 .env，保证 OTA/内置/源码模式读取同一数据根；
    但锁仍直接用最终加载到的 token 派生系统级命名互斥，避免未来启动目录或数据目录配置变化重新引入
    “同一 token 双实例”。锁文件放在
    系统临时目录（对同一用户、与 CWD/脚本位置无关地稳定一致），文件名带 token 哈希。这样任何最终
    用到同一 token 的实例——无论从哪个目录、哪份副本启动——都竞争同一把锁，409 与重复打卡被根除。
    未配置 token 时退回固定通用名，保持“同机仅一份 main.py”的原有单实例语义。
    """
    global _instance_lock_handle
    import hashlib
    import tempfile
    # 用最终加载到的 bot token 派生锁名（token 才是被争用的真实资源）；
    # 锁文件落在系统临时目录——它对同一用户稳定、且与 CWD/脚本目录无关，
    # 任何加载同一 token 的实例都会指向同一把锁。
    _token = getattr(config, 'TELEGRAM_BOT_TOKEN', None)
    if _token:
        _token_sig = hashlib.sha1(_token.encode('utf-8', 'ignore')).hexdigest()[:16]
        lock_name = f'aas-main-{_token_sig}.lock'
    else:
        # 未配置 token：无 409 风险，但仍保持单实例语义，退回固定通用名
        lock_name = 'aas-main-no-token.lock'
    lock_path = os.path.join(tempfile.gettempdir(), lock_name)
    try:
        # 以读写方式打开（不截断），便于失败时读取占用方 PID
        handle = open(lock_path, 'a+')
        try:
            if sys.platform == 'win32':
                import msvcrt
                # 非阻塞独占锁定首字节；已被占用立即抛 OSError
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # 已有实例持锁：尝试读出其 PID 给出更友好的提示
            try:
                handle.seek(0)
                holder = handle.read().strip()
            except Exception:
                holder = ''
            handle.close()
            holder_hint = f"（已有实例 PID={holder}）" if holder else "（已有实例正在运行）"
            print(f"\n[ERROR] 检测到自动打卡系统已在运行 {holder_hint}，本次启动已终止。")
            logging.error(f"单实例锁获取失败，已有实例在运行 {holder_hint}")
            return False

        # 抢锁成功：写入当前 PID 供他人提示参考
        try:
            handle.seek(0)
            handle.truncate(0)
            handle.write(str(os.getpid()))
            handle.flush()
        except Exception:
            pass
        # 句柄必须全局持有，关闭即释放锁
        _instance_lock_handle = handle
        return True
    except Exception as e:
        # 锁文件本身无法创建/打开（权限等）时不阻断启动，仅记录告警，保持原有可用性
        logging.warning(f"单实例锁初始化异常，跳过互斥保护: {e!r}")
        return True


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
    bot_started = False
    
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
                # GUI 模式（fast_boot）：bot 初始化必须走代理，而 _ensure_app_initialized 内部对代理
                # 启动窗口期最多做 4 次退避重试（可阻塞数十秒）。若在此同步等待，会把随后启动的 GUI
                # HTTP server（token 下发）一起拖住，表现为「GUI 卡在正在启动后端」。故 GUI 模式将 bot
                # 的初始化推迟到 GUI 后端就绪之后，由 _start_bot_deferred 后台并发执行（step9/step10 因
                # bot.app 仍为 None 会被其 `if app is not None` 守卫自动跳过）。控制台/watchdog 模式
                # （fast_boot=False）保持原同步初始化 + 失败降级语义不变。
                if not fast_boot:
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
                # GUI 模式由 _start_bot_deferred 接管；控制台模式即使 app.start()/轮询失败
                # 也只降级 Telegram，不让异常中断 AI、调度器等主启动链。
                if not fast_boot and attendance_system.bot.app is not None:
                    bot_started = await _activate_initialized_bot(attendance_system)
                await _tick(0.4)
            elif current_step == 10:  # 启动连接监控
                await _tick(0.3)  # 显示进度
                # 轮询已由统一激活函数启动；仅成功时挂连接监控。
                if bot_started:
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


async def _activate_initialized_bot(attendance_system):
    """完整激活 Telegram；任何失败只标记降级，不向主启动链抛出。"""
    bot = attendance_system.bot
    # 与 GUI 手动重连、后台监控共用同一生命周期锁；锁顺序保持
    # _reconnect_lock -> _initialization_lock，避免并发 stop/shutdown/start_polling。
    async with bot._reconnect_lock:
        try:
            await bot._ensure_app_initialized()
            if bot.app is None:
                raise RuntimeError("Telegram Bot 初始化失败：应用未创建")
            await bot.app.start()
            await bot.start_polling()
        except Exception as exc:
            attendance_system.bot_available = False
            attendance_system.bot_error = str(exc)[:500]
            logging.warning("Telegram Bot 激活失败，主程序继续降级运行: %r", exc)

            app = bot.app
            if app is not None:
                try:
                    await bot.stop_polling()
                except Exception:
                    pass
                try:
                    await app.stop()
                except Exception:
                    pass
                try:
                    await app.shutdown()
                except Exception:
                    pass
            bot.is_polling = False
            bot._is_initialized = False
            bot.app = None
            return False

        attendance_system.bot_available = True
        attendance_system.bot_error = None
        return True


async def _bot_recovery_loop(attendance_system):
    """bot 初始化降级后的后台自动恢复（指数退避重连）。

    背景：控制台/watchdog 模式没有 GUI 重连端点，若启动时代理未就绪导致 bot 初始化失败，
    进程会"活着但远程命令/提醒/通知全失效"，而 watchdog 只看进程存在性永远不会修复。
    这里在降级时挂一个后台任务，不断尝试 bot.reconnect()（与 GUI 端点共用 _reconnect_lock，
    不会并发冲突）；成功后回写 bot_available=True 并启动连接监控，使后续抖动也能自愈。
    """
    backoff_seq = [30, 60, 120, 300]  # 退避秒数，封顶 5 分钟
    attempt = 0
    while True:
        delay = backoff_seq[min(attempt, len(backoff_seq) - 1)]
        await asyncio.sleep(delay)
        attempt += 1
        try:
            ok, msg = await attendance_system.bot.reconnect(force=False)
        except Exception as e:
            logging.warning(f"bot 后台恢复第 {attempt} 次重连异常，稍后重试: {e!r}")
            continue
        if ok:
            attendance_system.bot_available = True
            attendance_system.bot_error = None
            logging.info(f"Telegram Bot 后台自动恢复成功（第 {attempt} 次尝试）")
            # 恢复后补启动连接监控，使之后的连接抖动同样可自愈
            try:
                asyncio.create_task(attendance_system.bot.monitor_connection())
            except Exception:
                logging.exception("恢复后启动连接监控失败")
            return
        else:
            attendance_system.bot_error = str(msg)[:500]
            logging.warning(f"bot 后台恢复第 {attempt} 次重连失败，{backoff_seq[min(attempt, len(backoff_seq) - 1)]} 秒后重试: {msg}")


async def _start_bot_deferred(attendance_system):
    """GUI 模式：GUI 后端就绪后，后台并发完成 Telegram Bot 的初始化 / 启动 / 轮询 / 监控。

    背景：bot 初始化必须走代理，而代理（mihomo）启动初期常有「端口在听但隧道未通」的窗口期，
    _ensure_app_initialized 内部最多 4 次退避重试会阻塞数十秒。若放在启动主链路同步等待，会把
    GUI HTTP server 的启动（token 下发）一起拖住，表现为「GUI 卡在正在启动后端」。这里把 bot 的
    初始化（原 initialize_system step5）与启动 / 轮询 / 连接监控（原 step9 / step10），连同 main()
    里的 8:15 提醒验证，整体搬到 GUI 后端 await 启动之后由本协程后台执行——GUI 秒级就绪，bot 在后台
    按原有重试 / 降级 / 恢复语义连接，互不阻塞。仅 GUI 模式调用；控制台 / watchdog 模式仍走原同步链路。
    """
    if not await _activate_initialized_bot(attendance_system):
        # 初始化、app.start 或轮询任一步失败都进入同一后台恢复路径。
        await _bot_recovery_loop(attendance_system)
        return

    # 对应原 main() 中的 8:15 提醒任务验证（bot 就绪后才有意义）
    try:
        if attendance_system.bot.verify_daily_reminder_setup():
            logging.info("✅ 8:15提醒任务验证成功")
        else:
            logging.warning("⚠️ 8:15提醒任务验证失败，可能需要手动检查")
    except Exception:
        logging.exception("验证 8:15 提醒任务失败")

    # 保持连接监控长期运行（对应原 monitor_task）；本协程作为后台任务被持有，监控随之常驻
    await attendance_system.bot.monitor_connection()


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
    bot_deferred_task = None  # GUI 模式：web_server 就绪后后台初始化 bot 的任务句柄（持有防 GC + 退出时取消）

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
            # GUI 后端已（尝试）就绪：现在才后台并发初始化 Telegram Bot，避免 bot 初始化的代理重试
            # 拖住 GUI token 下发。bot 的初始化 / 启动 / 轮询 / 监控 / 降级恢复全部由 _start_bot_deferred
            # 接管，故下面的 bot 降级恢复块与 8:15 验证块在 GUI 模式跳过（改由该协程内处理）。
            bot_deferred_task = asyncio.create_task(_start_bot_deferred(attendance_system))

        # [M41] 启动 mihomo 健康巡检后台任务：进程死亡时限频自动重启，
        # 否则 config.get_telegram_proxy() 始终返回死端口、Telegram 全链路永久不可用。
        proxy_watchdog_task = None
        _pm_for_watch = getattr(attendance_system, 'proxy_manager', None)
        if _pm_for_watch is not None:
            try:
                proxy_watchdog_task = asyncio.create_task(_pm_for_watch.watchdog())
            except Exception:
                logging.exception("启动内置网络加速健康巡检失败")

        # [M68] bot 初始化降级（bot_available=False）时挂起后台自动恢复任务。
        # 控制台/watchdog 模式没有 GUI 重连端点，否则进程会"活着但 Telegram 全失效"，
        # 而 watchdog 只看进程存在性永不修复。_bot_recovery_loop 指数退避调用
        # bot.reconnect()（内部已串接 start_polling），成功后回写 bot_available 并补启动连接监控。
        # GUI 模式的 bot 降级恢复由 _start_bot_deferred 内部接管，这里只管控制台 / watchdog 模式。
        bot_recovery_task = None
        if not args.gui and not getattr(attendance_system, 'bot_available', True):
            try:
                bot_recovery_task = asyncio.create_task(_bot_recovery_loop(attendance_system))
                logging.warning("Telegram Bot 处于降级状态，已启动后台自动恢复任务（指数退避重连）")
            except Exception:
                logging.exception("启动 Telegram Bot 后台恢复任务失败")

        # 等待5秒后验证8:15提醒任务设置（bot 降级时跳过，避免对未初始化的 app 操作）。
        # GUI 模式：bot 在后台初始化（见 _start_bot_deferred），验证已移入该协程在 bot 就绪后执行，
        # 此处跳过，避免对尚未初始化的 app 误操作、并让 GUI 主流程立即进入运行态。
        if not args.gui:
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
            # [M68] 关停时取消 bot 后台恢复任务，避免它在退出过程中又拉起轮询
            if bot_recovery_task is not None:
                bot_recovery_task.cancel()
            # GUI 模式：取消后台 bot 初始化 / 监控任务，避免它在退出过程中又拉起轮询
            if bot_deferred_task is not None:
                bot_deferred_task.cancel()
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
                # [M41] 先让巡检协程优雅退出，避免它在关停过程中又把刚停的 mihomo 拉起来
                _pm._watchdog_stop = True
                if proxy_watchdog_task is not None:
                    proxy_watchdog_task.cancel()
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
    # 启动早期获取单实例锁；已有实例在运行则直接退出，避免双轮询 409 与重复打卡
    if not acquire_single_instance_lock():
        sys.exit(1)
    try:
        asyncio.run(main(cli_args))
    except KeyboardInterrupt:
        print("\n\n[EXIT] 程序已停止，感谢使用！")
    except Exception as e:
        print(f"\n[FATAL] 程序异常退出: {e}")
        logging.critical(f"程序异常退出: {e}")
