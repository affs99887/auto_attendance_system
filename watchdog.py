import os
import sys
import time
import psutil
import logging
from logging.handlers import RotatingFileHandler
import subprocess
from datetime import datetime

def setup_logging():
    """配置日志记录"""
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # 配置文件处理器
    file_handler = RotatingFileHandler(
        'watchdog.log',
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

def is_process_running(process_name="python"):
    """检查指定进程是否在运行"""
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            if proc.info['name'] == process_name or \
               (proc.info['cmdline'] and 'main.py' in proc.info['cmdline']):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def start_main_program():
    """启动主程序"""
    try:
        # 使用 Python 解释器启动主程序
        subprocess.Popen([sys.executable, 'main.py'])
        logging.info("主程序已启动")
        return True
    except Exception as e:
        logging.error(f"启动主程序失败: {str(e)}")
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