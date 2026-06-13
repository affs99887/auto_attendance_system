import os
import sys
import time
import psutil
import logging
from logging.handlers import RotatingFileHandler
import subprocess
from datetime import datetime

# 看门狗所在目录即项目根目录，所有路径锚定于此，避免依赖启动目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# 本项目主程序绝对路径（归一化后用于进程归属校验）
MAIN_SCRIPT_PATH = os.path.normcase(os.path.normpath(os.path.join(PROJECT_ROOT, 'main.py')))


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


def python_subprocess_env():
    """子进程继承当前输出编码，并替换无法编码的字符。"""
    env = os.environ.copy()
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        env['PYTHONIOENCODING'] = f'{encoding}:replace'
    # [M37 修复] 标记子进程运行在看门狗监管之下：main.py 内 restart_program 据此改用 sys.exit
    # 让看门狗拉起新实例，而非进程内 os.execl 自重启（后者会与看门狗的重启逻辑撞车产生双实例）。
    env['AAS_SUPERVISED'] = '1'
    return env


configure_console_encoding()

def setup_logging():
    """配置日志记录"""
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # 配置文件处理器（日志固定写到项目根目录，不随启动目录漂移）
    file_handler = RotatingFileHandler(
        os.path.join(PROJECT_ROOT, 'watchdog.log'),
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3
    )
    file_handler.setFormatter(log_formatter)
    
    # 配置控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    
    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

def is_process_running():
    """检查本项目主程序(main.py)是否在运行

    同时校验三点，避免跨平台/绝对路径漏检与无关进程误检：
    1. 进程可执行文件名以 'python' 开头（兼容 Windows 的 python.exe）；
    2. cmdline 中存在某个参数，其归一化绝对路径正好是本项目根目录下的 main.py
       （绝对路径/相对路径启动均可命中，且排除其他项目的同名 main.py）；
    3. 排除看门狗自身 PID，避免自匹配恒为 True。

    [M89 补全] 额外把"任意 main.py --gui 进程"视为系统已在运行而直接返回 True：
    watchdog 与 GUI 互斥（GUI 模式下崩溃重启由 Electron 接管，见 start.py）。
    打包态 GUI 的 main.py 位于 resources\\backend\\main.py，与源码树 watchdog 锚定的
    MAIN_SCRIPT_PATH 是不同绝对路径，仅按路径相等判断会漏检 → watchdog 误判"未运行"
    再拉起一份无 GUI 后端的 headless main.py，造成双 Telegram bot polling 冲突 +
    共享文件竞争。故对带 '--gui' 的 main.py 放宽为仅按 basename 命中即认定在运行，
    避免看门狗与已运行的 GUI 后端撞车产生双实例。
    """
    self_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['pid'] == self_pid:
                continue
            name = (proc.info['name'] or '').lower()
            if not name.startswith('python'):
                continue
            cmdline = proc.info['cmdline'] or []
            # 该进程是否为 main.py（按 basename 命中，路径归属在下方再细判）
            has_main_py = any(
                arg and os.path.basename(arg).lower() == 'main.py'
                for arg in cmdline
            )
            if not has_main_py:
                continue
            # GUI 模式的 main.py：不论绝对路径是否等于本项目（打包态路径不同），
            # 都视为系统已运行，避免 watchdog 再拉起一份 headless 实例造成双实例。
            if '--gui' in cmdline:
                return True
            for arg in cmdline:
                if not arg or os.path.basename(arg).lower() != 'main.py':
                    continue
                # 相对路径参数按本项目根目录解析，再归一化比对，确保归属本项目
                arg_path = os.path.normcase(os.path.normpath(
                    os.path.join(PROJECT_ROOT, arg) if not os.path.isabs(arg) else arg
                ))
                if arg_path == MAIN_SCRIPT_PATH:
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def start_main_program():
    """启动主程序（headless CLI 变体，不带 --gui）

    [M89 补全说明] 看门狗刻意只拉起不带 --gui 的 main.py：
    看门狗模式与 GUI 模式互斥——GUI 模式下后端由 Electron 直接 spawn 并负责崩溃重启
    （见 start.py / main.cjs），不需要也不应由看门狗再拉起 GUI 后端。
    为防止与已运行的 GUI 后端撞车，进入此函数前会先 is_process_running() 拦截：
    该函数已把"任意 main.py --gui 进程"识别为系统在运行（含打包态不同绝对路径），
    故看门狗不会在 GUI 后端已起时再拉起一份 headless 实例。
    """
    try:
        # 双重保险：若此刻已有 GUI 后端在运行，绝不再拉起 headless 实例，
        # 避免双 Telegram bot polling 冲突 + 共享文件竞争（打包态路径不同时尤为关键）。
        if is_process_running():
            logging.info("检测到主程序(含 GUI 后端)已在运行，跳过本次启动以避免双实例")
            return True
        # 使用 Python 解释器启动主程序：用绝对路径并指定 cwd，消除对启动目录的依赖
        subprocess.Popen(
            [sys.executable, MAIN_SCRIPT_PATH],
            cwd=PROJECT_ROOT,
            env=python_subprocess_env()
        )
        logging.info("主程序已启动")
        return True
    except Exception as e:
        logging.error(f"启动主程序失败: {str(e)}")
        return False


def send_watchdog_alert(message):
    """看门狗自身告警：直接调用 Telegram sendMessage 通知用户。

    凭据从 .env 读取（与 config 一致），不引入额外依赖。
    任何失败都仅记日志，避免影响看门狗主流程。
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
    except Exception:
        pass

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        logging.error("未配置 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID，无法发送看门狗告警")
        return False
    try:
        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={'chat_id': chat_id, 'text': message},
            timeout=10
        )
        if resp.status_code == 200:
            logging.info("看门狗告警已通过 Telegram 发送")
            return True
        logging.error(f"看门狗告警发送失败，HTTP {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        logging.error(f"看门狗告警发送异常: {str(e)}")
        return False

def main():
    setup_logging()
    logging.info("看门狗进程已启动")
    
    restart_count = 0
    max_restarts = 5
    restart_interval = 3600  # 1小时
    last_restart = datetime.now()
    
    while True:
        try:
            current_time = datetime.now()
            time_diff = (current_time - last_restart).total_seconds()
            
            # 重置重启计数
            if time_diff > restart_interval:
                restart_count = 0
                last_restart = current_time
            
            # 检查主程序是否在运行
            if not is_process_running():
                logging.warning("主程序未运行，尝试重启...")
                
                if restart_count < max_restarts:
                    restart_count += 1
                    if start_main_program():
                        logging.info(f"主程序重启成功 ({restart_count}/{max_restarts})")
                    else:
                        logging.error("主程序重启失败")
                else:
                    logging.critical(f"重启次数过多 ({restart_count}/{max_restarts})，停止重试")
                    # 监控链即将退出，发出 Telegram 告警避免静默死亡导致漏打卡
                    send_watchdog_alert(
                        f"[看门狗告警] 主程序 1 小时内重启已达 {restart_count}/{max_restarts} 次，"
                        f"看门狗停止重试并退出，请尽快人工检查（存在漏打卡风险）。"
                    )
                    break
            
            # 检查系统资源使用情况
            memory_percent = psutil.virtual_memory().percent
            cpu_percent = psutil.cpu_percent()
            
            if memory_percent > 90 or cpu_percent > 90:
                logging.warning(f"系统资源使用率过高 (内存: {memory_percent}%, CPU: {cpu_percent}%)")
            
            time.sleep(60)  # 每分钟检查一次
            
        except Exception as e:
            logging.error(f"看门狗进程发生错误: {str(e)}")
            time.sleep(5)

if __name__ == "__main__":
    main() 
