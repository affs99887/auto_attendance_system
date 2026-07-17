"""
主程序入口

GUI 定制开发底座的主启动文件，负责初始化和协调各个模块
"""

import argparse
import asyncio
import logging
import os
import sys
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

from modules.config import config
from modules.app_core import AppCore
from modules.schedule_manager import run_schedule


# 单实例锁文件句柄（全局持有，进程存活期间不释放；进程退出由 OS 自动释放）
_instance_lock_handle = None


def acquire_single_instance_lock():
    """获取单实例独占锁，防止重复启动 main.py。

    重复启动会导致定时任务跑两遍、两个后端抢同一 HTTP/WS 端口。这里用锁文件 + PID 校验：
    - 取到独占锁：写入当前 PID，返回 True；
    - 取不到（已有实例持锁）：读出占用 PID 提示后返回 False，由调用方退出；
    - 若锁文件残留但持有者已不在（旧进程崩溃未释放），OS 层独占锁本就不会拦截，可正常抢占。
    锁文件放在系统临时目录：对同一用户稳定、与 CWD/脚本位置无关，
    保证打包副本与仓库手动启动的实例竞争同一把锁。
    """
    global _instance_lock_handle
    import tempfile
    lock_path = os.path.join(tempfile.gettempdir(), 'aas-main.lock')
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
            print(f"\n[ERROR] 检测到程序已在运行 {holder_hint}，本次启动已终止。")
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
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if is_plain_console():
        print("GUI App Base v1.0")
        print(f"启动时间: {current_time}")
        print(f"Python版本: {sys.version.split()[0]}")
        print()
        return

    # 清屏
    print("\033[2J\033[H", end="")

    print("\033[34m" + "═" * 60 + "\033[0m")
    print("\033[38;5;45m  GUI 定制开发底座 · GUI App Base v1.0\033[0m")
    print("\033[34m" + "═" * 60 + "\033[0m")
    print(f"\033[38;5;45m  启动时间: {current_time}\033[0m")
    print(f"\033[38;5;45m  Python版本: {sys.version.split()[0]}\033[0m")
    print("\033[34m" + "═" * 60 + "\033[0m")
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

    print("\033[32m系统启动完成！定时任务与后台服务运行中，按 Ctrl+C 停止程序。\033[0m")


async def initialize_system(fast_boot=False):
    """初始化系统，带进度显示

    fast_boot=True（GUI 模式）时跳过纯装饰性的进度 sleep，加快后端就绪——
    真实初始化步骤一律保留。控制台/watchdog 模式 fast_boot=False，行为不变。
    """
    async def _tick(seconds):
        # 装饰性等待：仅为让（GUI 下隐藏的）进度条好看；fast_boot 直接跳过
        if not fast_boot:
            await asyncio.sleep(seconds)

    total_steps = 3

    if is_plain_console():
        print("[INIT] 开始初始化系统组件...")
    else:
        print(f"\033[34m[INIT] 开始初始化系统组件...\033[0m")
    print()

    steps = [
        "初始化配置模块",
        "启动网络加速并创建应用核心",
        "启动定时任务调度器",
    ]

    app_core = None
    schedule_task = None

    for i, step_name in enumerate(steps):
        current_step = i + 1
        print_progress(current_step, total_steps, step_name, is_final=False)

        try:
            if current_step == 1:  # 初始化配置模块
                await _tick(0.3)
                config.ensure_directories()
                await _tick(0.5)
            elif current_step == 2:  # 启动网络加速并创建应用核心
                await _tick(0.3)
                # 先拉起内置网络加速（mihomo），使随后的网络请求能走本地代理端口。
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
                app_core = AppCore()
                app_core.proxy_manager = _proxy_manager
                await _tick(0.4)
            elif current_step == 3:  # 启动定时任务调度器
                await _tick(0.3)
                schedule_task = asyncio.create_task(run_schedule())
                await _tick(0.5)

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

    return app_core, schedule_task


def _parse_args():
    """解析主程序命令行参数。

    单独抽出便于 start.py / Electron 外壳直接调用 ``main.py --gui``。
    """
    parser = argparse.ArgumentParser(description='GUI 定制开发底座主程序')
    parser.add_argument('--gui', action='store_true',
                        help='启用 GUI 后端（Flask REST + WebSocket，监听 127.0.0.1）')
    parser.add_argument('--gui-http-port', type=int, default=8765,
                        help='GUI HTTP 端口（默认 8765）')
    parser.add_argument('--gui-ws-port', type=int, default=8766,
                        help='GUI WebSocket 端口（默认 8766）')
    return parser.parse_args()


async def main(args=None):
    """主函数 - 系统启动入口"""
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
        app_core, schedule_task = await initialize_system(fast_boot=args.gui)

        # GUI 后端：仅在 --gui 时启动。
        if args.gui:
            try:
                from modules.web_server import start as start_web_server
                gui_handle = await start_web_server(
                    app_core,
                    loop=asyncio.get_running_loop(),
                    http_port=args.gui_http_port,
                    ws_port=args.gui_ws_port,
                )
                logging.info(
                    f"GUI 后端已启动 — HTTP 127.0.0.1:{args.gui_http_port} / "
                    f"WS 127.0.0.1:{args.gui_ws_port}，token 文件 logs/.gui_token"
                )
            except Exception as e:
                logging.error(f"GUI 后端启动失败: {e}", exc_info=True)

        # [M41] 启动 mihomo 健康巡检后台任务：进程死亡时限频自动重启，
        # 否则后台服务的本地代理端口会一直指向死端口。
        proxy_watchdog_task = None
        _pm_for_watch = getattr(app_core, 'proxy_manager', None)
        if _pm_for_watch is not None:
            try:
                proxy_watchdog_task = asyncio.create_task(_pm_for_watch.watchdog())
            except Exception:
                logging.exception("启动内置网络加速健康巡检失败")

        logging.info("所有服务已启动，系统运行中...")

        try:
            # 保持程序运行，直到收到退出信号
            await asyncio.Event().wait()
        finally:
            # 清理资源
            print("\n[>>] 正在关闭系统...")
            schedule_task.cancel()
            if gui_handle is not None:
                try:
                    gui_handle['stop']()
                except Exception:
                    logging.exception("GUI 后端关停失败")
            # 停止内置网络加速子进程
            _pm = getattr(app_core, 'proxy_manager', None)
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
        logging.critical(f"程序启动失败: {str(e)}", exc_info=True)


if __name__ == "__main__":
    cli_args = _parse_args()
    # 启动早期获取单实例锁；已有实例在运行则直接退出，避免定时任务与端口的双实例冲突
    if not acquire_single_instance_lock():
        sys.exit(1)
    try:
        asyncio.run(main(cli_args))
    except KeyboardInterrupt:
        print("\n\n[EXIT] 程序已停止，感谢使用！")
    except Exception as e:
        print(f"\n[FATAL] 程序异常退出: {e}")
        logging.critical(f"程序异常退出: {e}")
