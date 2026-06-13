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
    """启动主程序"""
    try:
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
