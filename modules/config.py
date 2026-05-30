"""
配置管理模块

集中管理系统配置、环境变量和常量定义
"""

import os
import json
import socket
import logging
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class Config:
    """配置管理类"""

    # 登录配置
    LOGIN_USERNAME = os.getenv('LOGIN_USERNAME')
    LOGIN_PASSWORD = os.getenv('LOGIN_PASSWORD')
    LOGIN_USERNAME2 = os.getenv('LOGIN_USERNAME2')
    LOGIN_PASSWORD2 = os.getenv('LOGIN_PASSWORD2')
    LOGIN_URL = os.getenv('LOGIN_URL')

    # Telegram配置
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

    # 邮件配置
    EMAIL_SENDER = os.getenv('EMAIL_SENDER', '')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
    EMAIL_SMTP_SERVER = os.getenv('EMAIL_SMTP_SERVER', 'smtp.qq.com')
    EMAIL_SMTP_PORT = int(os.getenv('EMAIL_SMTP_PORT', '465'))
    EMAIL_RECIPIENTS = os.getenv('EMAIL_RECIPIENTS', '').split(',') if os.getenv('EMAIL_RECIPIENTS') else []

    # Tesseract配置
    TESSERACT_PATH = os.getenv('TESSERACT_PATH', r'C:\Program Files\Tesseract-OCR\tesseract.exe')

    # 工作时间配置
    WORK_START_TIME = os.getenv('WORK_START_TIME', "09:00")
    WORK_END_TIME = os.getenv('WORK_END_TIME', "17:30")
    LATE_THRESHOLD = int(os.getenv('LATE_THRESHOLD', "15"))  # 分钟
    EARLY_LEAVE_THRESHOLD = int(os.getenv('EARLY_LEAVE_THRESHOLD', "15"))  # 分钟
    DAILY_STATUS_TIME = os.getenv('DAILY_STATUS_TIME', "08:20")

    # 系统配置
    MAX_RETRIES = 3
    RETRY_INTERVAL = 5  # 秒
    HEARTBEAT_INTERVAL = 300  # 5分钟
    MAX_HEARTBEAT_MISS = 3
    ERROR_RESET_INTERVAL = 3600  # 1小时
    MAX_ERRORS = 5

    # 看门狗配置
    WATCHDOG_MAX_RESTARTS = 5
    WATCHDOG_RESTART_INTERVAL = 3600  # 1小时

    # 文件路径配置
    LOGS_DIR = 'logs'
    PUNCH_RECORDS_DIR = 'punch_records'
    SCREENSHOTS_DIR = 'screenshots'
    TEMPLATES_DIR = 'templates'

    # 模板文件路径
    SAFE_PLACE_PATH = 'templates/safe_place.png'
    SAFE_PLACE_PATH2 = 'templates/safe_place2.png'
    USERNAME_FIELD_PATH = 'templates/username_field.png'
    PASSWORD_FIELD_PATH = 'templates/password_field.png'
    LOGIN_BUTTON_PATH = 'templates/login_button.png'
    PUNCH_BUTTON_PATH = 'templates/punch_button.png'


    # Telegram连接配置
    CONNECTION_POOL_SIZE = 20
    CONNECTION_TIMEOUT = 20
    POOL_TIMEOUT = 20
    READ_TIMEOUT = 20
    WRITE_TIMEOUT = 20
    UPDATE_TIMEOUT = 600  # 10分钟
    MAX_CONNECTION_ERRORS = 10

    # Telegram代理配置（按顺序探测，第一个可连通的端口被采用；都不通则直连）
    TELEGRAM_PROXY_HOST = os.getenv('TELEGRAM_PROXY_HOST', '127.0.0.1')
    TELEGRAM_PROXY_PORTS = [
        int(p.strip()) for p in os.getenv('TELEGRAM_PROXY_PORTS', '7897,7890').split(',')
        if p.strip().isdigit()
    ]
    TELEGRAM_PROXY_SCHEME = os.getenv('TELEGRAM_PROXY_SCHEME', 'http')
    TELEGRAM_PROXY_PROBE_TIMEOUT = float(os.getenv('TELEGRAM_PROXY_PROBE_TIMEOUT', '1.0'))

    # 图像识别配置
    MATCH_THRESHOLD = 0.8
    OCR_CONFIG = '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789:'
    
    # 动态配置文件路径
    DYNAMIC_CONFIG_FILE = 'dynamic_config.json'
    
    # Selenium配置 - 支持动态配置
    _dynamic_config = None
    
    @classmethod
    def _load_dynamic_config(cls):
        """加载动态配置"""
        if cls._dynamic_config is None:
            if os.path.exists(cls.DYNAMIC_CONFIG_FILE):
                try:
                    with open(cls.DYNAMIC_CONFIG_FILE, 'r', encoding='utf-8') as f:
                        cls._dynamic_config = json.load(f)
                except Exception as e:
                    print(f"加载动态配置失败: {e}")
                    cls._dynamic_config = {}
            else:
                cls._dynamic_config = {}
        return cls._dynamic_config
    
    @classmethod
    def _save_dynamic_config(cls):
        """保存动态配置"""
        try:
            with open(cls.DYNAMIC_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cls._dynamic_config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存动态配置失败: {e}")
    
    @classmethod
    def get_selenium_config(cls, key, default_value):
        """获取Selenium配置，优先使用动态配置"""
        dynamic_config = cls._load_dynamic_config()
        if key in dynamic_config:
            return dynamic_config[key]
        # 回退到环境变量
        env_value = os.getenv(key, str(default_value)).lower()
        return env_value == 'true' if isinstance(default_value, bool) else env_value
    
    @classmethod
    def set_selenium_config(cls, key, value):
        """设置Selenium配置"""
        dynamic_config = cls._load_dynamic_config()
        dynamic_config[key] = value
        cls._save_dynamic_config()
    
    @classmethod
    def get_use_selenium_login(cls):
        """是否使用Selenium登录"""
        return cls.get_selenium_config('USE_SELENIUM_LOGIN', False)
    
    @classmethod
    def get_selenium_headless(cls):
        """是否使用无头模式"""
        return cls.get_selenium_config('SELENIUM_HEADLESS', False)

    @classmethod
    def get_telegram_proxy(cls):
        """按顺序探测 TELEGRAM_PROXY_PORTS，返回首个可连通的代理 URL；都不通则返回 None。"""
        host = cls.TELEGRAM_PROXY_HOST
        scheme = cls.TELEGRAM_PROXY_SCHEME
        timeout = cls.TELEGRAM_PROXY_PROBE_TIMEOUT
        for port in cls.TELEGRAM_PROXY_PORTS:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    proxy_url = f"{scheme}://{host}:{port}"
                    logging.info(f"Telegram代理探测成功，使用: {proxy_url}")
                    return proxy_url
            except (OSError, socket.timeout):
                continue
        logging.warning(
            f"Telegram代理探测失败（已尝试端口 {cls.TELEGRAM_PROXY_PORTS}），将走直连"
        )
        return None

    @classmethod
    def get_user_configs(cls):
        """获取多用户配置"""
        return [
            {
                'username': cls.LOGIN_USERNAME,
                'password': cls.LOGIN_PASSWORD,
                'punch_records': {
                    'punch_in_time': None,
                    'punch_out_time': None
                }
            },
            {
                'username': cls.LOGIN_USERNAME2,
                'password': cls.LOGIN_PASSWORD2,
                'punch_records': {
                    'punch_in_time': None,
                    'punch_out_time': None
                }
            }
        ]

    @classmethod
    def ensure_directories(cls):
        """确保必要的目录存在"""
        directories = [
            cls.LOGS_DIR,
            cls.PUNCH_RECORDS_DIR,
            cls.SCREENSHOTS_DIR,
            cls.TEMPLATES_DIR
        ]

        for directory in directories:
            os.makedirs(directory, exist_ok=True)


# 全局配置实例
config = Config()
