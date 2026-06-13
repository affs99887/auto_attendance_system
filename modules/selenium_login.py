"""
Selenium登录控制器

用于替代PyAutoGUI图像识别的登录方式，提供更精确和可靠的浏览器自动化操作
"""

import asyncio
import logging
import threading
import time
import json
import os
from datetime import datetime
from typing import Tuple, Optional, List, Dict

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    ElementNotInteractableException,
    SessionNotCreatedException
)
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from webdriver_manager.chrome import ChromeDriverManager


class SeleniumRecordManager:
    """Selenium打卡记录管理器（使用统一的punch_records存储）"""
    
    def __init__(self, username: str = "default"):
        """
        初始化记录管理器
        
        Args:
            username: 用户名，用于多用户数据隔离
        """
        self.username = username
        # 使用统一的punch_records存储系统
        self.base_dir = "punch_records"
        # 对于多用户支持，使用子目录隔离数据
        if username and username != "default":
            self.user_dir = os.path.join(self.base_dir, self.username)
        else:
            # 默认用户直接使用punch_records根目录，与传统记录管理器兼容
            self.user_dir = self.base_dir
        self._ensure_directories()
        
    def _ensure_directories(self):
        """确保必要的目录存在"""
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)
        if self.user_dir != self.base_dir and not os.path.exists(self.user_dir):
            os.makedirs(self.user_dir)
    
    def _get_month_file_path(self, year: int = None, month: int = None) -> str:
        """获取指定月份的数据文件路径"""
        if year is None or month is None:
            now = datetime.now()
            year, month = now.year, now.month
        return os.path.join(self.user_dir, f"{year}_{month:02d}.json")
    
    def load_month_records(self, year: int = None, month: int = None) -> dict:
        """加载指定月份的记录"""
        file_path = self._get_month_file_path(year, month)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"加载Selenium打卡记录失败: {str(e)}")
                return {}
        return {}
    
    def save_month_records(self, records: dict, year: int = None, month: int = None):
        """保存指定月份的记录"""
        file_path = self._get_month_file_path(year, month)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"保存Selenium打卡记录失败: {str(e)}")
    
    def get_today_record(self) -> dict:
        """获取今日打卡记录（兼容传统格式）"""
        today = datetime.now()
        records = self.load_month_records()
        date_str = today.strftime('%Y-%m-%d')
        return records.get(date_str, {
            'punch_in_time': None,
            'punch_out_time': None
        })
    
    def update_punch_record(self, punch_type: str, time_str: str = None, 
                          status_data: dict = None, additional_info: dict = None):
        """
        更新打卡记录
        
        Args:
            punch_type: 'punch_in' 或 'punch_out'
            time_str: 打卡时间字符串，如果为None则使用当前时间
            status_data: 考勤状态数据
            additional_info: 额外信息（如工作时间、预计下班时间等）
        """
        if time_str is None:
            time_str = datetime.now().strftime('%H:%M:%S')
        
        today = datetime.now()
        records = self.load_month_records()
        date_str = today.strftime('%Y-%m-%d')
        
        # 初始化当日记录（兼容传统格式）
        if date_str not in records:
            records[date_str] = {
                'punch_in_time': None,
                'punch_out_time': None
            }
        
        # 更新打卡时间
        if punch_type == 'punch_in':
            records[date_str]['punch_in_time'] = time_str
        elif punch_type == 'punch_out':
            records[date_str]['punch_out_time'] = time_str
        
        # 如果有额外的Selenium特定数据，可以存储但保持兼容性
        if status_data or additional_info:
            # 只在需要时添加额外字段，保持与传统格式的兼容性
            if status_data:
                records[date_str]['selenium_status'] = status_data
            if additional_info:
                records[date_str]['selenium_info'] = additional_info
        
        # 保存记录
        self.save_month_records(records)
        
        logging.info(f"统一打卡记录已更新: {punch_type} at {time_str} for {self.username} (存储路径: {self.user_dir})")
    
    def get_today_punch_in_time(self) -> Optional[str]:
        """获取今日上班打卡时间"""
        today_record = self.get_today_record()
        return today_record.get('punch_in_time')
    
    def calculate_worked_minutes_from_history(self) -> Optional[int]:
        """
        从历史记录计算已工作分钟数
        
        Returns:
            int: 已工作的分钟数，如果无法计算则返回None
        """
        punch_in_time_str = self.get_today_punch_in_time()
        logging.info(f"[DEBUG] 查询今日上班时间: {punch_in_time_str} (用户: {self.username}, 存储路径: {self.user_dir})")
        
        if not punch_in_time_str:
            logging.info(f"[DEBUG] 未找到今日打卡记录")
            return None
        
        try:
            # 解析上班时间
            punch_in_time = datetime.strptime(punch_in_time_str, '%H:%M:%S').time()
            
            # 获取当前时间
            now = datetime.now()
            current_time = now.time()
            
            # 计算工作时间（分钟）
            punch_in_datetime = datetime.combine(now.date(), punch_in_time)
            current_datetime = datetime.combine(now.date(), current_time)
            
            worked_duration = current_datetime - punch_in_datetime
            worked_minutes = int(worked_duration.total_seconds() / 60)
            
            logging.info(f"从历史数据计算工作时间: {worked_minutes}分钟 (上班时间: {punch_in_time_str})")
            return worked_minutes
            
        except Exception as e:
            logging.error(f"从历史数据计算工作时间失败: {str(e)}")
            return None


class SeleniumLoginController:
    """Selenium登录控制器"""

    # 后台驱动更新的类级去重标志：控制器每次打卡新建实例，双用户并行时
    # 避免重复下载 / 多个 Timer 同时写 ~/.wdm 缓存冲突。
    _bg_update_lock = threading.Lock()
    _bg_update_pending = False

    def __init__(self, login_url: str, headless: bool = False, notification_callback=None, browser_type: str = "edge", username: str = "default"):
        """
        初始化登录控制器
        
        Args:
            login_url: 登录页面URL
            headless: 是否使用无头模式
            notification_callback: 通知回调函数，用于发送状态消息
            browser_type: 浏览器类型 ("edge" 或 "chrome")
            username: 用户名，用于数据管理
        """
        self.login_url = login_url
        self.headless = headless
        self.notification_callback = notification_callback
        self.browser_type = browser_type.lower()
        self.username = username
        self.logger = logging.getLogger(__name__)
        self.driver = None
        self.wait = None
        self.service = None  # selenium Service 实例，便于 close() 兜底关 msedgedriver 进程
        # [M55] 记录 driver 拉起的浏览器(msedge.exe)进程 PID：close() 中 driver.quit() 失败时，
        # 仅停 msedgedriver(service)不保证回收其子浏览器进程树，headless 下这些孤儿不可见且长期累积占用内存，
        # 故记录该 pid 以便 quit 失败时按进程树兜底终止整个 msedgedriver + msedge 子树。
        self.browser_pid = None

        # 初始化记录管理器
        self.record_manager = SeleniumRecordManager(username=username)
        
        # 配置选项
        if self.browser_type == "chrome":
            self.browser_options = self._setup_chrome_options()
        else:
            self.browser_options = self._setup_edge_options()
        
        # 元素定位策略配置
        self.username_selectors = [
            (By.NAME, "loginname"),  # 根据实际HTML代码
            (By.ID, "username"),
            (By.NAME, "username"),
            (By.NAME, "user"),
            (By.CSS_SELECTOR, "input[placeholder*='用户']"),
            (By.CSS_SELECTOR, "input[placeholder*='账号']"),
            (By.CSS_SELECTOR, "input[placeholder*='用户名']"),
            (By.CSS_SELECTOR, "input[type='text'][name*='user']"),
            (By.XPATH, "//input[@type='text'][1]"),  # 第一个文本输入框
        ]
        
        self.password_selectors = [
            (By.NAME, "password2"),  # 根据实际HTML代码
            (By.ID, "password"),
            (By.NAME, "password"),
            (By.NAME, "pass"),
            (By.CSS_SELECTOR, "input[type='password']"),
            (By.CSS_SELECTOR, "input[placeholder*='密码']"),
            (By.XPATH, "//input[@type='password'][1]"),  # 第一个密码输入框
        ]
        
        self.login_button_selectors = [
            (By.XPATH, "//input[@value='登录']"),  # 根据实际HTML代码
            (By.CSS_SELECTOR, "input[value='登录']"),
            (By.NAME, "Submit"),  # 根据实际HTML代码
            (By.ID, "login"),
            (By.ID, "loginBtn"),
            (By.NAME, "login"),
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.CSS_SELECTOR, "input[type='submit']"),
            (By.XPATH, "//button[contains(text(),'登录')]"),
            (By.XPATH, "//button[contains(text(),'登陆')]"),
            (By.XPATH, "//input[contains(@value,'登录')]"),
            (By.XPATH, "//input[contains(@value,'登陆')]"),
            (By.CSS_SELECTOR, ".login-btn"),
            (By.CSS_SELECTOR, ".btn-login"),
        ]
    
    def _setup_edge_options(self) -> Options:
        """设置Edge浏览器选项"""
        options = Options()
        
        if self.headless:
            options.add_argument("--headless")
        
        # 最小化配置，只保留必要选项
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # 窗口配置
        options.add_argument("--window-size=1920,1080")
        
        # 增强SSL和安全配置
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")
        options.add_argument("--ignore-certificate-errors-spki-list")
        options.add_argument("--ignore-certificate-errors-sp-list")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--accept-insecure-certs")
        options.add_argument("--test-type")
        
        return options
    
    def _setup_chrome_options(self) -> ChromeOptions:
        """设置Chrome浏览器选项"""
        options = ChromeOptions()
        
        if self.headless:
            options.add_argument("--headless")
        
        # 基础配置
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # 窗口配置
        options.add_argument("--window-size=1920,1080")
        
        # 增强SSL和安全配置
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")
        options.add_argument("--ignore-certificate-errors-spki-list")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--disable-web-security")
        options.add_argument("--accept-insecure-certs")
        options.add_argument("--test-type")
        
        return options
    
    async def send_notification(self, context: str, message: str):
        """发送通知消息"""
        if self.notification_callback:
            await self.notification_callback(context, message)
        self.logger.info(f"[{context}] {message}")

    async def _run_blocking(self, func, *args, **kwargs):
        """[M34] 将一个阻塞的同步调用放到工作线程执行，避免卡死 asyncio 主事件循环。

        SeleniumLoginController 的 WebDriver 操作（driver.get / WebDriverWait.until /
        element.click / 创建 driver 等）都是同步阻塞调用：打卡期间（含联网下载驱动、
        30s 页面加载超时、45s 命令 read-timeout + urllib3 重试）会把整个事件循环卡住，
        导致 schedule 定时任务延迟、Telegram 轮询/命令无响应、WS 推送停摆、Flask bridge.call 干等超时，
        所谓 3 并发并行打卡也在每个阻塞调用处退化为串行。
        这里用 asyncio.to_thread 把单个阻塞步骤丢进线程池（Python 3.9+），
        协程层只做编排/等待，事件循环在阻塞期间仍可继续处理其它任务。
        注意：driver 实例只在自己的串行流程内被一个线程使用，不存在并发访问同一 driver 的问题。
        """
        return await asyncio.to_thread(func, *args, **kwargs)

    async def start_browser(self) -> bool:
        """启动浏览器并导航到登录页面"""
        # 仅允许 Edge 登录：禁用 Chrome 回退（Chrome 会抢占默认用户数据目录，与用户已开的 Chrome 冲突）
        browsers_to_try = ["edge"]
        
        for browser in browsers_to_try:
            try:
                browser_name = "Chrome" if browser == "chrome" else "Edge"
                await self.send_notification("Selenium登录", f"正在尝试启动{browser_name}浏览器...")
                
                # 创建WebDriver实例（保存 service 到 self.service，便于 close() 兜底清理 service 进程）
                if browser == "chrome":
                    chrome_options = self._setup_chrome_options()
                    try:
                        # 优先用 webdriver-manager 自动下载匹配本地 Chrome 版本的 driver
                        # [M34] 联网下载 + 创建 driver 均为阻塞调用，放线程执行避免卡事件循环
                        driver_path = await self._run_blocking(ChromeDriverManager().install)
                        await self.send_notification("Selenium登录", f"使用 webdriver-manager 管理的Chrome驱动: {driver_path}")
                        self.service = ChromeService(driver_path)
                        self.driver = await self._run_blocking(
                            lambda: webdriver.Chrome(service=self.service, options=chrome_options)
                        )
                    except Exception as wdm_err:
                        # 兜底：回退到系统 PATH 中的 chromedriver
                        await self.send_notification("Selenium登录", f"webdriver-manager 获取 Chrome 驱动失败({str(wdm_err)[:80]})，回退到系统PATH")
                        self.service = None  # 走 PATH 自动模式时 selenium 内部管理 service，无需保存
                        self.driver = await self._run_blocking(
                            lambda: webdriver.Chrome(options=chrome_options)
                        )
                else:
                    edge_options = self._setup_edge_options()
                    import os
                    project_driver_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'msedgedriver.exe')
                    # 打卡路径不联网下载驱动：先用本地已有驱动(优先 webdriver-manager 缓存里版本最高者，
                    # 否则项目自带的 msedgedriver.exe)立即启动。即便本地驱动版本低于当前 Edge 也先用旧的，
                    # 避免每次打卡前白等十几秒下载、且离线时也能照常打卡。
                    # 真正的驱动更新放到打卡执行完毕(close)后、延迟 10 分钟在后台进行(见 _run_bg_driver_update)。
                    local_driver_path = self._resolve_local_edge_driver(project_driver_path)
                    if not local_driver_path:
                        # 本地完全没有驱动(首次部署且未随程序打包驱动)→ 只能在打卡路径上同步联网下载一次兜底
                        await self.send_notification("Selenium登录", "本地无可用Edge驱动，正在联网下载...")
                        # [M34] 联网下载驱动为阻塞调用，放线程执行避免卡事件循环
                        local_driver_path = await self._run_blocking(
                            EdgeChromiumDriverManager(
                                url="https://msedgedriver.microsoft.com",
                                latest_release_url="https://msedgedriver.microsoft.com/LATEST_RELEASE",
                            ).install
                        )
                    await self.send_notification("Selenium登录", f"使用本地Edge驱动启动: {local_driver_path}")
                    try:
                        self.service = Service(local_driver_path)
                        # [M34] 创建 driver（启动 msedgedriver 进程 + 建会话）为阻塞调用，放线程执行
                        self.driver = await self._run_blocking(
                            lambda: webdriver.Edge(service=self.service, options=edge_options)
                        )
                    except Exception as drv_err:
                        # 自愈：Windows 约每 4 周后台升级 Edge 主版本，本地旧 msedgedriver 主版本不匹配时
                        # webdriver.Edge() 必抛 SessionNotCreatedException("This version of MSEdgeDriver only supports MSEdge version X")。
                        # 原逻辑只在“本地完全无驱动”时才联网，启动失败又永不触发后台更新 → 形成“更新依赖成功、成功依赖更新”的死锁，
                        # 必须人工删 ~/.wdm 缓存才能恢复。故这里在判定为版本不匹配时，同步联网下载一次匹配当前 Edge 的新驱动并重试启动一次。
                        err_text = str(drv_err).lower()
                        is_version_mismatch = isinstance(drv_err, SessionNotCreatedException) or \
                            "session not created" in err_text or "only supports" in err_text
                        if not is_version_mismatch:
                            raise
                        # 先清理本次失败残留的 service 进程，避免下载重试期间 msedgedriver.exe 泄漏
                        try:
                            failed_service = getattr(self, 'service', None)
                            if failed_service is not None:
                                failed_proc = getattr(failed_service, 'process', None)
                                if failed_proc is not None and failed_proc.poll() is None:
                                    failed_service.stop()
                        except Exception:
                            pass
                        await self.send_notification(
                            "Selenium登录",
                            f"本地Edge驱动版本与浏览器不匹配({str(drv_err)[:80]})，正在联网下载匹配的新驱动并重试..."
                        )
                        # [M34] 联网下载驱动 + 重试创建 driver 均为阻塞调用，放线程执行
                        local_driver_path = await self._run_blocking(
                            EdgeChromiumDriverManager(
                                url="https://msedgedriver.microsoft.com",
                                latest_release_url="https://msedgedriver.microsoft.com/LATEST_RELEASE",
                            ).install
                        )
                        await self.send_notification("Selenium登录", f"使用新下载的Edge驱动重试启动: {local_driver_path}")
                        self.service = Service(local_driver_path)
                        self.driver = await self._run_blocking(
                            lambda: webdriver.Edge(service=self.service, options=edge_options)
                        )
                
                await self.send_notification("Selenium登录", f"{browser_name} WebDriver实例创建成功")
                self.wait = WebDriverWait(self.driver, 10)

                # [M55] 记录浏览器进程 PID：driver 创建成功后从 capabilities 取浏览器自身的 processID
                # (Edge/Chrome 在 caps 的 'msedge'/'chrome' 字段下提供)。后续 close() 中若 driver.quit() 失败，
                # 据此连同 service(msedgedriver) 一并按进程树终止，回收 headless 下不可见的孤儿浏览器进程。
                try:
                    caps = getattr(self.driver, 'capabilities', None) or {}
                    browser_caps = caps.get('msedge') or caps.get('chrome') or {}
                    self.browser_pid = browser_caps.get('processID')
                    if self.browser_pid:
                        self.logger.debug(f"[Selenium登录] 记录浏览器进程PID: {self.browser_pid}")
                except Exception as pid_err:
                    self.logger.debug(f"[Selenium登录] 读取浏览器进程PID失败(忽略): {pid_err}")

                # 设置页面加载 / 底层命令超时：登录页不可达(离线或不在公司内网)时，
                # 避免 driver.get() 无限阻塞，以及 WebDriver 命令默认 120s read-timeout +
                # urllib3 三次重试导致单次登录卡死十几分钟、进而阻塞事件循环拖垮 Telegram 轮询
                try:
                    self.driver.set_page_load_timeout(30)
                except Exception as to_err:
                    self.logger.warning(f"[Selenium登录] 设置页面加载超时失败: {to_err}")
                try:
                    self.driver.command_executor.set_timeout(45)
                except Exception as ce_err:
                    self.logger.warning(f"[Selenium登录] 设置命令执行超时失败: {ce_err}")

                await self.send_notification("Selenium登录", f"正在访问登录页面: {self.login_url}")

                # 导航到登录页面
                # [M34] driver.get 受 30s 页面加载超时约束，是最长的阻塞步骤之一，放线程执行避免卡事件循环
                await self._run_blocking(self.driver.get, self.login_url)
                await self.send_notification("Selenium登录", "页面导航请求已发送")

                # 等待页面加载完成
                await self.send_notification("Selenium登录", "等待页面加载...")
                try:
                    # 使用5秒超时时间
                    wait_short = WebDriverWait(self.driver, 5)
                    # [M34] WebDriverWait.until 内部轮询阻塞，放线程执行
                    await self._run_blocking(
                        wait_short.until, EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                    await self.send_notification("Selenium登录", "页面body元素已加载")
                except TimeoutException:
                    # 如果body加载失败，尝试检查是否有任何元素
                    await self.send_notification("Selenium登录", "body加载超时，检查页面状态...")
                    # [M34] current_url/title 读取是同步往返（命令超时退化时最长约 45s），放线程执行避免卡事件循环
                    current_url, page_title = await self._run_blocking(
                        lambda: (self.driver.current_url, self.driver.title)
                    )
                    await self.send_notification("Selenium登录", f"当前URL: {current_url}, 页面标题: {page_title}")

                    # 尝试查找任何元素来确认页面是否加载（[M34] find_element 同步往返，放线程执行）
                    try:
                        await self._run_blocking(self.driver.find_element, By.TAG_NAME, "html")
                        await self.send_notification("Selenium登录", "页面HTML已加载，继续处理...")
                    except:
                        raise TimeoutException("页面完全无法加载")
                
                await self.send_notification("Selenium登录", f"{browser_name}浏览器启动成功，页面已加载")
                self.browser_type = browser  # 更新成功的浏览器类型
                return True
                
            except Exception as e:
                await self.send_notification("Selenium登录", f"{browser_name}失败: {str(e)[:100]}")
                # 尝试清理资源
                if hasattr(self, 'driver') and self.driver:
                    try:
                        self.driver.quit()
                    except:
                        pass
                    self.driver = None
                
                # 如果不是最后一个浏览器，继续尝试下一个
                if browser != browsers_to_try[-1]:
                    await self.send_notification("Selenium登录", f"尝试下一个浏览器...")
                    continue
        
        await self.send_notification("Selenium登录", "所有浏览器都无法启动")
        # 兜底打破死锁：启动失败时 close() 里 self.driver 为 None，原本永不调度后台驱动更新，
        # 导致下次 _resolve_local_edge_driver 仍选同一旧驱动而持续失败。这里在启动失败路径上
        # 立即(delay=0)安排一次后台驱动更新，使下次启动能用到匹配当前 Edge 的新驱动而自愈。
        self._schedule_delayed_driver_update(delay=0)
        return False

    async def handle_security_warnings(self) -> bool:
        """处理安全警告弹窗"""
        try:
            await self.send_notification("安全警告", "检查是否存在安全警告弹窗...")
            
            # 处理SSL证书警告
            try:
                # Chrome/Edge的高级选项按钮（[M34] WebDriverWait.until 最长阻塞3s，放线程执行）
                advanced_button = await self._run_blocking(
                    WebDriverWait(self.driver, 3).until,
                    EC.element_to_be_clickable((By.ID, "details-button"))
                )
                await self.send_notification("安全警告", "发现SSL证书警告，点击高级选项...")
                await self._run_blocking(advanced_button.click)
                await asyncio.sleep(1)

                # 点击继续访问链接（[M34] find_element + click 均为同步往返/阻塞命令，放线程执行）
                proceed_link = await self._run_blocking(self.driver.find_element, By.ID, "proceed-link")
                await self.send_notification("安全警告", "点击继续访问链接...")
                await self._run_blocking(proceed_link.click)
                await asyncio.sleep(2)

                await self.send_notification("安全警告", "SSL证书警告已处理")
                return True

            except TimeoutException:
                # 没有SSL警告，继续检查其他类型的警告
                pass

            # 处理其他可能的安全警告（根据实际页面调整）
            warning_selectors = [
                (By.XPATH, "//button[contains(text(),'更多')]"),
                (By.XPATH, "//button[contains(text(),'继续')]"),
                (By.XPATH, "//a[contains(text(),'继续')]"),
                (By.CSS_SELECTOR, ".warning-proceed"),
            ]

            for by, selector in warning_selectors:
                try:
                    # [M34] WebDriverWait.until 最长阻塞2s/选择器，放线程执行
                    element = await self._run_blocking(
                        WebDriverWait(self.driver, 2).until,
                        EC.element_to_be_clickable((by, selector))
                    )
                    await self.send_notification("安全警告", f"发现警告元素，点击处理: {selector}")
                    await self._run_blocking(element.click)
                    await asyncio.sleep(1)
                    return True
                except TimeoutException:
                    continue
            
            await self.send_notification("安全警告", "未发现需要处理的安全警告")
            return True
            
        except Exception as e:
            await self.send_notification("安全警告", f"处理安全警告时发生错误: {str(e)}")
            return True  # 即使处理失败也继续，可能页面本身没有警告
    
    def _find_element_by_multiple_selectors(self, selectors: list, element_name: str) -> Optional[object]:
        """使用多种选择器策略查找元素

        [M54] 阶梯式超时：只对“首选择器”用长超时(self.wait=10s)等待页面元素渲染完成，
        其余回退选择器用 1.5s 短超时快速试探。原实现每个选择器都用固定 10s 超时，
        当页面改版/元素全失配时：username 9 个最长阻塞约 90s、login_button 14 个最长约 140s，
        即便已用 _run_blocking 放到线程执行(不再冻结事件循环)，单次打卡仍要分钟级才返回，
        会拖慢调度/并行打卡的整体节奏并长时间占用线程池。改为阶梯超时后，最坏阻塞从分钟级
        降到秒级(10s + (N-1)*1.5s)，同时保留“多选择器全量尝试”的原有兜底能力。
        """
        # 回退选择器短超时，避免全失配时累计成分钟级阻塞
        short_wait = WebDriverWait(self.driver, 1.5) if self.driver else None
        for index, (by, selector) in enumerate(selectors):
            # 首选择器用长超时(self.wait)，其余用短超时(short_wait)；short_wait 不可用时回退到 self.wait
            wait = self.wait if index == 0 else (short_wait or self.wait)
            try:
                element = wait.until(EC.presence_of_element_located((by, selector)))
                self.logger.info(f"成功找到{element_name}元素: {by}='{selector}'")
                return element
            except TimeoutException:
                continue

        self.logger.warning(f"所有策略都无法找到{element_name}元素")
        return None
    
    async def _perform_login_in_current_frame(self, username: str, password: str) -> Tuple[bool, str]:
        """在当前frame中执行登录操作"""
        try:
            await self.send_notification("登录流程", "在iframe中执行登录...")
            
            # 查找用户名输入框
            username_element = self._find_element_by_multiple_selectors(
                self.username_selectors, "用户名"
            )
            if not username_element:
                return False, "在iframe中无法找到用户名输入框"
            
            # 填写用户名
            await self.send_notification("登录流程", f"在iframe中输入用户名: {username}")
            username_element.clear()
            username_element.send_keys(username)
            
            # 查找密码输入框
            password_element = self._find_element_by_multiple_selectors(
                self.password_selectors, "密码"
            )
            if not password_element:
                return False, "在iframe中无法找到密码输入框"
            
            # 填写密码
            await self.send_notification("登录流程", "在iframe中输入密码")
            password_element.clear()
            password_element.send_keys(password)
            
            # 查找登录按钮
            login_button = self._find_element_by_multiple_selectors(
                self.login_button_selectors, "登录按钮"
            )
            if not login_button:
                return False, "在iframe中无法找到登录按钮"
            
            # 点击登录
            await self.send_notification("登录流程", "在iframe中点击登录按钮")
            login_button.click()
            
            # 等待登录结果
            await asyncio.sleep(3)
            await self.send_notification("登录流程", "iframe登录操作完成")
            return True, "iframe登录成功"
            
        except Exception as e:
            return False, f"iframe登录失败: {str(e)}"
    
    def _validate_input_element(self, element, element_type: str) -> bool:
        """验证输入元素是否正确"""
        try:
            # 检查元素是否可见和可交互
            if not element.is_displayed() or not element.is_enabled():
                return False
            
            # 检查元素属性
            tag_name = element.tag_name.lower()
            input_type = element.get_attribute('type') or ''
            placeholder = (element.get_attribute('placeholder') or '').lower()
            name = (element.get_attribute('name') or '').lower()
            element_id = (element.get_attribute('id') or '').lower()
            
            if element_type == "username":
                # 用户名相关关键词
                keywords = ['username', 'user', '用户', '账号', 'account']
                if tag_name == 'input' and input_type in ['text', '']:
                    for keyword in keywords:
                        if keyword in placeholder or keyword in name or keyword in element_id:
                            return True
            
            elif element_type == "password":
                # 密码相关验证
                if tag_name == 'input' and input_type == 'password':
                    return True
                keywords = ['password', 'pass', '密码']
                for keyword in keywords:
                    if keyword in placeholder or keyword in name or keyword in element_id:
                        return True
            
            return False
            
        except Exception:
            return False
    
    async def login(self, username: str, password: str) -> Tuple[bool, str]:
        """
        执行登录操作
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            # 1. 启动浏览器
            if not await self.start_browser():
                return False, "浏览器启动失败"
            
            # 2. 处理安全警告
            if not await self.handle_security_warnings():
                return False, "处理安全警告失败"
            
            # 3. 处理传统frameset结构
            await self.send_notification("登录流程", "检测到frameset页面，切换到登录frame...")
            try:
                # 切换到 mainFrame (包含login.jsp)
                await self.send_notification("登录流程", "切换到mainFrame...")
                # [M34] frame 切换是同步 WebDriver 往返，frame 上下文失效/命令超时时最长可阻塞 45s，放线程执行避免卡事件循环
                await self._run_blocking(self.driver.switch_to.frame, "mainFrame")

                # 等待login.jsp页面加载
                await asyncio.sleep(2)

                # 验证是否成功切换到登录页面
                await self.send_notification("登录流程", "检查登录frame内容...")
                try:
                    # 查找登录表单元素（[M34] find_elements 同步往返，放线程执行）
                    login_inputs = await self._run_blocking(self.driver.find_elements, By.TAG_NAME, "input")
                    await self.send_notification("登录流程", f"在登录frame中发现{len(login_inputs)}个input元素")
                    
                    # 检查是否有预期的登录字段
                    # [M34] 逐个 element.get_attribute('name') 都是同步 WebDriver 往返，
                    # 集中在一个工作线程里一次性读完所有 name，避免逐次往返阻塞事件循环；
                    # 读出纯字符串列表后再在协程层做判断/通知，保持原有逻辑与通知不变。
                    input_names = await self._run_blocking(
                        lambda elems: [(e.get_attribute('name') or '') for e in elems], login_inputs
                    )
                    found_loginname = False
                    found_password2 = False
                    for input_name in input_names:
                        if input_name == 'loginname':
                            found_loginname = True
                            await self.send_notification("登录流程", "找到loginname输入框")
                        elif input_name == 'password2':
                            found_password2 = True  
                            await self.send_notification("登录流程", "找到password2输入框")
                    
                    if found_loginname and found_password2:
                        await self.send_notification("登录流程", "成功定位到登录表单，开始登录...")
                        # 现在在正确的frame中，继续执行登录
                    else:
                        await self.send_notification("登录流程", f"未找到预期的登录字段 - loginname: {found_loginname}, password2: {found_password2}")
                        return False, "未在登录frame中找到预期的登录字段"
                        
                except Exception as frame_error:
                    await self.send_notification("登录流程", f"检查登录frame失败: {str(frame_error)}")
                    return False, "无法访问登录frame内容"
                    
            except Exception as e:
                await self.send_notification("登录流程", f"切换到登录frame失败: {str(e)}")
                return False, "无法切换到登录frame"
            
            # 4. 查找并填写用户名
            await self.send_notification("登录流程", "正在定位用户名输入框...")
            # [M34] 多选择器查找内部用 WebDriverWait.until 轮询(每选择器最长10s)，放线程执行避免卡事件循环
            username_element = await self._run_blocking(
                self._find_element_by_multiple_selectors, self.username_selectors, "用户名"
            )

            if not username_element:
                return False, "无法找到用户名输入框"

            if not self._validate_input_element(username_element, "username"):
                await self.send_notification("登录流程", "用户名输入框验证失败，尝试继续...")

            await self.send_notification("登录流程", f"开始输入用户名: {username}")
            # [M34] clear/send_keys 为阻塞 WebDriver 命令，放线程执行
            await self._run_blocking(username_element.clear)
            await self._run_blocking(username_element.send_keys, username)

            # 验证输入是否成功（[M34] get_attribute 同步往返，放线程执行避免卡事件循环）
            input_value = await self._run_blocking(username_element.get_attribute, 'value')
            if input_value != username:
                return False, f"用户名输入验证失败，期望: {username}, 实际: {input_value}"

            await self.send_notification("登录流程", "用户名输入完成")
            await asyncio.sleep(0.5)

            # 4. 查找并填写密码
            await self.send_notification("登录流程", "正在定位密码输入框...")
            password_element = await self._run_blocking(
                self._find_element_by_multiple_selectors, self.password_selectors, "密码"
            )

            if not password_element:
                return False, "无法找到密码输入框"

            if not self._validate_input_element(password_element, "password"):
                await self.send_notification("登录流程", "密码输入框验证失败，尝试继续...")

            await self.send_notification("登录流程", "开始输入密码")
            await self._run_blocking(password_element.clear)
            await self._run_blocking(password_element.send_keys, password)

            await self.send_notification("登录流程", "密码输入完成")
            await asyncio.sleep(0.5)

            # 5. 查找并点击登录按钮
            await self.send_notification("登录流程", "正在定位登录按钮...")
            login_button = await self._run_blocking(
                self._find_element_by_multiple_selectors, self.login_button_selectors, "登录按钮"
            )

            if not login_button:
                return False, "无法找到登录按钮"

            await self.send_notification("登录流程", "点击登录按钮...")
            # [M34] current_url 读取是同步往返，放线程执行避免卡事件循环
            current_url = await self._run_blocking(lambda: self.driver.current_url)
            # [M34] 点击登录触发表单提交+页面跳转，是阻塞命令，放线程执行
            await self._run_blocking(login_button.click)

            # 6. 等待登录结果
            await self.send_notification("登录流程", "等待登录结果...")
            await asyncio.sleep(3)

            # 检查URL是否发生变化（登录成功的常见标志）
            try:
                # [M34] WebDriverWait.until(最长7s)轮询阻塞，放线程执行
                await self._run_blocking(
                    WebDriverWait(self.driver, 7).until,
                    lambda driver: driver.current_url != current_url
                )
                await self.send_notification("登录流程", "检测到页面跳转，登录可能成功")
            except TimeoutException:
                await self.send_notification("登录流程", "未检测到页面跳转，检查登录结果...")
            
            # 检查是否有错误提示
            error_selectors = [
                (By.CSS_SELECTOR, ".error"),
                (By.CSS_SELECTOR, ".alert-error"),
                (By.CSS_SELECTOR, ".login-error"),
                (By.XPATH, "//div[contains(@class,'error')]"),
                (By.XPATH, "//span[contains(text(),'错误')]"),
                (By.XPATH, "//div[contains(text(),'失败')]"),
            ]
            
            # [M34] 错误提示探测涉及多次 find_element/is_displayed/.text 同步往返，
            # 集中在一个工作线程里跑完，避免逐次往返在主事件循环上排队阻塞；
            # 内部仍按原选择器顺序与 NoSuchElementException 跳过逻辑，命中即返回错误文本。
            def _detect_login_error():
                for by, selector in error_selectors:
                    try:
                        error_element = self.driver.find_element(by, selector)
                        if error_element.is_displayed():
                            return error_element.text
                    except NoSuchElementException:
                        continue
                return None

            error_text = await self._run_blocking(_detect_login_error)
            if error_text is not None:
                return False, f"登录失败: {error_text}"

            await self.send_notification("登录流程", "登录流程完成")
            return True, "登录成功"
            
        except Exception as e:
            error_msg = f"登录过程发生错误: {str(e)}"
            await self.send_notification("登录流程", error_msg)
            self.logger.exception("登录过程异常")
            return False, error_msg
    
    def take_screenshot(self, filepath: str = None) -> bytes:
        """截取当前页面截图"""
        if not self.driver:
            return None
        
        try:
            if filepath:
                self.driver.save_screenshot(filepath)
                return True
            else:
                return self.driver.get_screenshot_as_png()
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            return None
    
    def _resolve_local_edge_driver(self, project_driver_path):
        """返回本地可用的 Edge 驱动路径（不联网）。

        优先选 webdriver-manager 缓存(~/.wdm/drivers/edgedriver)里版本号最高的，
        其次项目目录自带的 msedgedriver.exe；都没有则返回 None(由调用方决定是否联网兜底)。
        """
        import os, re
        candidates = []
        wdm_dir = os.path.join(os.path.expanduser("~"), ".wdm", "drivers", "edgedriver")
        if os.path.isdir(wdm_dir):
            for root, _dirs, files in os.walk(wdm_dir):
                for f in files:
                    if f.lower() == "msedgedriver.exe":
                        candidates.append(os.path.join(root, f))

        def _ver_key(p):
            m = re.search(r'(\d+(?:\.\d+)*)', os.path.basename(os.path.dirname(p)))
            return tuple(int(x) for x in m.group(1).split('.')) if m else (0,)

        if candidates:
            candidates.sort(key=_ver_key, reverse=True)
            return candidates[0]
        if project_driver_path and os.path.exists(project_driver_path):
            return project_driver_path
        return None

    @classmethod
    def _schedule_delayed_driver_update(cls, delay: int = 600):
        """打卡执行完毕后，延迟 delay 秒(默认10分钟)在后台线程把 Edge 驱动更新到 ~/.wdm 缓存，
        供下次启动使用。下载全程不阻塞打卡；类级去重确保同一时间只有一个待执行/进行中的更新。
        """
        with cls._bg_update_lock:
            if cls._bg_update_pending:
                return
            cls._bg_update_pending = True
        timer = threading.Timer(delay, cls._run_bg_driver_update)
        timer.daemon = True
        timer.start()
        logging.getLogger(__name__).info(
            f"[Selenium登录] 已安排 {delay} 秒后在后台更新 Edge 驱动(不影响打卡)"
        )

    @classmethod
    def _run_bg_driver_update(cls):
        """后台下载/更新匹配当前 Edge 的最新驱动（在独立线程中执行，不阻塞主流程）。"""
        logger = logging.getLogger(__name__)
        try:
            path = EdgeChromiumDriverManager(
                url="https://msedgedriver.microsoft.com",
                latest_release_url="https://msedgedriver.microsoft.com/LATEST_RELEASE",
            ).install()
            logger.info(f"[Selenium登录] 后台驱动更新完成，下次启动将优先使用: {path}")
        except Exception as e:
            logger.warning(f"[Selenium登录] 后台驱动更新失败(不影响打卡，下次仍用本地驱动): {str(e)[:120]}")
        finally:
            with cls._bg_update_lock:
                cls._bg_update_pending = False

    def _kill_process_tree(self, pid):
        """[M55] 按 pid 终止整个进程子树（先终止子进程再终止父进程），用于 quit() 失败后的兜底回收。

        msedgedriver 被 stop/kill 并不保证回收它拉起的 msedge.exe 浏览器进程树——headless 模式下
        这些孤儿浏览器不可见，长期累积占用内存(与项目既往“孤儿进程泄漏导致 GUI 卡死”排查方向一致)。
        故此处用 psutil 枚举该 pid 的全部子孙进程一并终止，确保不留孤儿。pid 无效/进程已退出均安全跳过。
        """
        if not pid:
            return
        try:
            import psutil
        except Exception:
            # 极端情况下 psutil 不可用：放弃树清理（service.stop 仍会尽力收尾），仅记 debug
            self.logger.debug("[Selenium登录] psutil 不可用，跳过进程树兜底清理")
            return
        try:
            parent = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        except Exception as e:
            self.logger.debug(f"[Selenium登录] 获取进程 {pid} 失败(忽略): {e}")
            return
        # 先收集子孙进程，连同父进程一起 kill；逐个吞掉“已退出/无权限”异常，保证尽力清完
        procs = []
        try:
            procs = parent.children(recursive=True)
        except Exception:
            procs = []
        procs.append(parent)
        for p in procs:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
        self.logger.info(f"[Selenium登录] 已按进程树兜底终止 pid={pid} 及其 {len(procs) - 1} 个子进程")

    def close(self):
        """关闭浏览器 + 兜底清理 Service 进程"""
        # 正常路径：driver.quit() 会自动停 service
        quit_failed = False  # [M55] 标记 quit() 是否失败，失败时需按进程树兜底回收浏览器孤儿进程
        if self.driver:
            try:
                self.driver.quit()
                self.logger.info("浏览器已关闭")
            except Exception as e:
                self.logger.error(f"关闭浏览器时发生错误: {e}")
                quit_failed = True
            finally:
                self.driver = None
                self.wait = None
            # 浏览器确实启动过并已关闭(=本次打卡执行完毕)：延迟 10 分钟在后台更新驱动，供下次启动使用
            self._schedule_delayed_driver_update()

        # [M55] quit() 失败兜底：driver 挂死/命令 45s 超时/msedgedriver 已崩溃时，driver.quit() 抛异常，
        # 仅 service.stop() 停掉 msedgedriver 并不能回收其拉起的 msedge.exe 浏览器进程树(headless 下不可见、
        # 长期累积占内存)。故 quit 失败时按进程树兜底：终止启动时记录的浏览器 PID 子树 + msedgedriver service PID 子树。
        if quit_failed:
            self._kill_process_tree(self.browser_pid)
            service = getattr(self, 'service', None)
            service_proc = getattr(service, 'process', None) if service is not None else None
            service_pid = getattr(service_proc, 'pid', None) if service_proc is not None else None
            self._kill_process_tree(service_pid)
        self.browser_pid = None

        # 兜底：driver 创建失败但 Service 已启动（msedgedriver.exe 进程仍在），显式 stop。
        # 注意：driver.quit() 成功时已停掉 service，此处会重复 stop —— selenium 4.x 的
        # Service.stop() 在进程已停止/未真正启动时访问 self.process 会抛 AttributeError（良性）。
        # 故仅在进程确实存活时才 stop，并把异常降级为 debug，避免刷 ERROR 噪声。
        service = getattr(self, 'service', None)
        if service is not None:
            try:
                proc = getattr(service, 'process', None)
                if proc is not None and proc.poll() is None:
                    service.stop()
                    self.logger.info("Selenium Service 进程已停止")
            except Exception as e:
                self.logger.debug(f"停止 Selenium Service 跳过（多为已停止）: {e}")
            finally:
                self.service = None
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
    
    async def _switch_to_main_frame(self) -> bool:
        """切换到mainFrame进行打卡操作"""
        try:
            await self.send_notification("Frame切换", "正在切换到mainFrame...")
            
            # 先切换到默认内容（根frame）（[M34] frame 切换是同步往返，放线程执行避免卡事件循环）
            await self._run_blocking(self.driver.switch_to.default_content)

            # 切换到mainFrame（[M34] frame 切换是同步往返，放线程执行）
            await self._run_blocking(self.driver.switch_to.frame, "mainFrame")

            await self.send_notification("Frame切换", "成功切换到mainFrame")

            # 等待页面加载
            await asyncio.sleep(1)

            # 验证是否在正确的frame中（检查是否有打卡按钮）
            try:
                # [M34] find_elements 同步往返，放线程执行
                punch_buttons = await self._run_blocking(self.driver.find_elements, By.NAME, "gotowork")
                if punch_buttons:
                    await self.send_notification("Frame切换", "在mainFrame中找到打卡按钮")
                    return True
                else:
                    await self.send_notification("Frame切换", "警告：未在mainFrame中找到打卡按钮")
                    return True  # 继续尝试，可能页面还在加载
            except Exception as e:
                await self.send_notification("Frame切换", f"验证mainFrame内容时出错: {str(e)}")
                return True  # 继续尝试
                
        except Exception as e:
            await self.send_notification("Frame切换", f"切换到mainFrame失败: {str(e)}")
            return False
    
    async def _check_punch_button_status(self) -> Dict[str, Optional[bool]]:
        """检查打卡按钮状态

        [M20] 三态语义：每个按钮的值为
        - True ：确认“可用”（可点击 → 尚未打卡）
        - False：确认“不可用/已禁用”（已打过卡）
        - None ：检查失败/状态未知（如 frame 上下文短暂失效、driver 命令超时、
                 NoSuchElementException 之外的 WebDriverException 等）
        原实现把所有异常一律吞成 False（=按钮不可用=已打卡），上层据此误判“打卡成功”，
        抑制了重试机制造成静默漏打卡。这里区分“确认禁用”与“检查失败”，把未知显式表达为 None，
        由调用方在 None 时拒绝判定成功、改走重试/二次确认。
        """
        # 初始为 None（未知），仅在成功读取到状态时才落 True/False
        button_status: Dict[str, Optional[bool]] = {
            "gotowork": None,    # 上班按钮是否可用
            "offwork": None,     # 下班按钮是否可用
            "goout": None,       # 外出按钮是否可用
            "comeback": None     # 回来按钮是否可用
        }
        try:
            await self.send_notification("按钮状态检查", "正在检查打卡按钮状态...")

            # 检查各个打卡按钮的状态
            button_names = ["gotowork", "offwork", "goout", "comeback"]
            button_labels = ["上班", "下班", "外出", "回来"]

            # [M34] 每个按钮的 find_element/is_displayed/is_enabled/get_attribute 共 4 次同步往返，
            # 集中到一个工作线程里一次性读完三态，避免 16 次往返逐个在主事件循环上排队阻塞
            # （frame 上下文失效/命令超时退化时单次往返最长约 45s）。NoSuchElementException 等异常
            # 由线程内原样抛出、透传回协程层，保持下方 except 分支的三态语义不变。
            def _read_button_state(name):
                button_element = self.driver.find_element(By.NAME, name)
                _is_displayed = button_element.is_displayed()
                _is_enabled = button_element.is_enabled()
                _disabled_attr = button_element.get_attribute("disabled")
                return _is_displayed, _is_enabled, (_disabled_attr is not None)

            for button_name, label in zip(button_names, button_labels):
                try:
                    # 查找按钮元素并读取可见/可交互/disabled 三态（同步往返已放线程执行）
                    is_displayed, is_enabled, is_disabled = await self._run_blocking(
                        _read_button_state, button_name
                    )

                    # 按钮可用条件：显示、启用且未被disabled
                    button_available = is_displayed and is_enabled and not is_disabled
                    button_status[button_name] = button_available

                    status_text = "可用" if button_available else "不可用"
                    await self.send_notification(
                        "按钮状态检查",
                        f"{label}按钮: {status_text} (displayed: {is_displayed}, enabled: {is_enabled}, disabled: {is_disabled})"
                    )

                except NoSuchElementException:
                    # 元素确实不存在：属于“确认不可用”，保持 False 语义（页面已无该按钮）
                    await self.send_notification("按钮状态检查", f"未找到{label}按钮")
                    button_status[button_name] = False
                except Exception as e:
                    # 其它异常（WebDriverException/超时/上下文失效等）→ 状态未知，置 None 不再当作“不可用”
                    await self.send_notification("按钮状态检查", f"检查{label}按钮状态时出错(状态未知): {str(e)}")
                    button_status[button_name] = None

            # 汇总状态（仅统计明确可用=True 的按钮）
            available_buttons = [label for button_name, label in zip(button_names, button_labels) if button_status[button_name] is True]
            if available_buttons:
                await self.send_notification("按钮状态检查", f"当前可用按钮: {', '.join(available_buttons)}")
            else:
                await self.send_notification("按钮状态检查", "当前没有可用的打卡按钮")

            return button_status

        except Exception as e:
            # 整体异常：全部置 None（未知），让调用方据此拒绝误报成功
            await self.send_notification("按钮状态检查", f"检查按钮状态时发生错误(状态未知): {str(e)}")
            return {"gotowork": None, "offwork": None, "goout": None, "comeback": None}
    
    async def punch_in(self, skip_frame_switch: bool = False, skip_button_check: bool = False) -> Tuple[bool, str]:
        """
        执行上班打卡操作
        
        Args:
            skip_frame_switch: 跳过frame切换（当已经在mainFrame时）
            skip_button_check: 跳过按钮状态检查（当已经检查过时）
        """
        try:
            await self.send_notification("上班打卡", "开始执行上班打卡...")
            
            # 1. 切换到mainFrame（可选）
            if not skip_frame_switch:
                if not await self._switch_to_main_frame():
                    return False, "切换到mainFrame失败"
            
            # 2. 检查按钮状态（可选）
            if not skip_button_check:
                button_status = await self._check_punch_button_status()
                gotowork_state = button_status.get("gotowork")
                if gotowork_state is None:
                    # [M20] 状态未知（检查失败）不可当作“已打卡”，明确返回需重试，避免误报成功抑制重试
                    return False, "无法确认上班按钮状态，需重试/人工确认"
                if gotowork_state is not True:
                    return False, "上班按钮不可用，可能已经打过卡或系统不允许当前操作"

            # 3. 查找上班按钮（[M34] find_element 同步往返，放线程执行避免卡事件循环）
            try:
                gotowork_button = await self._run_blocking(self.driver.find_element, By.NAME, "gotowork")
                await self.send_notification("上班打卡", "找到上班按钮，准备点击...")
            except NoSuchElementException:
                return False, "无法找到上班按钮"
            
            # 4. 点击上班按钮
            await self.send_notification("上班打卡", "点击上班按钮...")
            # [M34] 点击打卡按钮触发提交+弹窗，是阻塞命令，放线程执行避免卡事件循环
            await self._run_blocking(gotowork_button.click)

            # 5. 处理确认对话框
            try:
                await self.send_notification("上班打卡", "等待确认对话框...")
                # 等待alert出现（[M34] WebDriverWait.until 最长阻塞5s，放线程执行）
                alert = await self._run_blocking(
                    WebDriverWait(self.driver, 5).until, EC.alert_is_present()
                )
                alert_text = alert.text
                await self.send_notification("上班打卡", f"确认对话框内容: {alert_text}")

                # 点击确认（[M34] alert.accept 触发页面重载，是阻塞命令，放线程执行）
                await self._run_blocking(alert.accept)
                await self.send_notification("上班打卡", "已确认打卡操作")
                
            except TimeoutException:
                await self.send_notification("上班打卡", "未检测到确认对话框，可能直接提交了")
            except Exception as e:
                await self.send_notification("上班打卡", f"处理确认对话框时出错: {str(e)}")
                return False, f"处理确认对话框失败: {str(e)}"
            
            # 6. 等待操作完成
            await asyncio.sleep(2)
            
            # 7. 验证打卡结果
            await self.send_notification("上班打卡", "验证打卡结果...")
            try:
                # 重新检查按钮状态，上班成功后上班按钮应该变为disabled
                updated_button_status = await self._check_punch_button_status()
                gotowork_state = updated_button_status.get("gotowork")
                if gotowork_state is False:
                    # 确认按钮已禁用 → 打卡成功
                    await self.send_notification("上班打卡", "上班按钮已变为不可用状态，打卡可能成功")
                    return True, "上班打卡成功"
                elif gotowork_state is True:
                    # 确认按钮仍可用 → 打卡未生效
                    await self.send_notification("上班打卡", "警告：上班按钮仍可用，打卡可能未成功")
                    return False, "打卡操作可能未成功，按钮状态未改变"
                else:
                    # [M20] 按钮状态未知（gotowork_state is None）：不再默认判成功，
                    # 改从页面打卡时间二次确认——能识别出今日上班时间才算成功，否则需重试
                    await self.send_notification("上班打卡", "按钮状态未知，尝试从页面打卡时间二次确认...")
                    times = await self.get_today_punch_times_from_page(skip_frame_switch=True)
                    if times.get("punch_in_time"):
                        return True, f"上班打卡成功(页面已记录上班时间 {times['punch_in_time']})"
                    return False, "无法验证上班打卡结果，需重试/人工确认"

            except Exception as e:
                await self.send_notification("上班打卡", f"验证打卡结果时出错: {str(e)}")
                # [M20] 验证块自身抛异常不再默认判成功（原会误报成功抑制重试），
                # 尝试二次确认页面打卡时间，仍无法确认则返回失败交由上层重试
                try:
                    times = await self.get_today_punch_times_from_page(skip_frame_switch=True)
                    if times.get("punch_in_time"):
                        return True, f"上班打卡成功(页面已记录上班时间 {times['punch_in_time']})"
                except Exception as verify_err:
                    await self.send_notification("上班打卡", f"二次确认页面打卡时间失败: {str(verify_err)}")
                return False, "上班打卡结果无法验证，需重试/人工确认"
            
        except Exception as e:
            error_msg = f"上班打卡过程发生错误: {str(e)}"
            await self.send_notification("上班打卡", error_msg)
            return False, error_msg
    
    async def punch_out(self, skip_frame_switch: bool = False, skip_button_check: bool = False) -> Tuple[bool, str]:
        """
        执行下班打卡操作
        
        Args:
            skip_frame_switch: 跳过frame切换（当已经在mainFrame时）
            skip_button_check: 跳过按钮状态检查（当已经检查过时）
        """
        try:
            await self.send_notification("下班打卡", "开始执行下班打卡...")
            
            # 1. 切换到mainFrame（可选）
            if not skip_frame_switch:
                if not await self._switch_to_main_frame():
                    return False, "切换到mainFrame失败"
            
            # 2. 检查按钮状态（可选）
            if not skip_button_check:
                button_status = await self._check_punch_button_status()
                offwork_state = button_status.get("offwork")
                if offwork_state is None:
                    # [M20] 状态未知（检查失败）不可当作“按钮不可用”，明确返回需重试
                    return False, "无法确认下班按钮状态，需重试/人工确认"
                if offwork_state is not True:
                    return False, "下班按钮不可用，可能还未上班打卡或系统不允许当前操作"

            # 3. 查找下班按钮（[M34] find_element 同步往返，放线程执行避免卡事件循环）
            try:
                offwork_button = await self._run_blocking(self.driver.find_element, By.NAME, "offwork")
                await self.send_notification("下班打卡", "找到下班按钮，准备点击...")
            except NoSuchElementException:
                return False, "无法找到下班按钮"
            
            # 4. 点击下班按钮
            await self.send_notification("下班打卡", "点击下班按钮...")
            # [M34] 点击下班按钮触发提交+页面变化，是阻塞命令，放线程执行避免卡事件循环
            await self._run_blocking(offwork_button.click)

            # 5. 点击后直接等待页面变化，不存在确认对话框
            await self.send_notification("下班打卡", "打卡操作已提交，等待页面变化...")
            
            # 6. 等待操作完成
            await asyncio.sleep(2)
            
            # 7. 验证打卡结果：检查是否出现“返回”按钮
            await self.send_notification("下班打卡", "验证打卡结果...")
            try:
                # 检查是否出现“返回”按钮，如果出现说明未到下班时间
                # [M34] find_element + is_displayed 同步往返，放线程一次性读完；
                # NoSuchElementException 原样抛出透传回协程层，保持下方 except 逻辑不变。
                try:
                    return_button_displayed = await self._run_blocking(
                        lambda: self.driver.find_element(By.NAME, "return").is_displayed()
                    )
                    if return_button_displayed:
                        await self.send_notification("下班打卡", "检测到'返回'按钮，未到下班时间或工作时间不足")
                        return False, "未到下班时间或工作时间不足"
                except NoSuchElementException:
                    # 没有返回按钮，说明正常打卡
                    pass
                
                # 检查下班按钮状态是否变化
                updated_button_status = await self._check_punch_button_status()
                offwork_state = updated_button_status.get("offwork")
                if offwork_state is False:
                    # 确认按钮已禁用 → 打卡成功
                    await self.send_notification("下班打卡", "下班按钮已变为不可用状态，打卡成功")
                    return True, "下班打卡成功"
                elif offwork_state is True:
                    # 确认按钮仍可用且无返回按钮：状态不明，从页面打卡时间二次确认
                    await self.send_notification("下班打卡", "警告：下班按钮仍可用，但未检测到返回按钮，尝试从页面打卡时间二次确认...")
                    times = await self.get_today_punch_times_from_page(skip_frame_switch=True)
                    if times.get("punch_out_time"):
                        return True, f"下班打卡成功(页面已记录下班时间 {times['punch_out_time']})"
                    # [M20] 原实现此处直接判成功，会把“没打上的卡”报为成功而抑制定时重试；
                    # 二次确认仍无下班时间则返回失败，让上层调度重试
                    return False, "下班打卡结果无法验证（按钮仍可用且页面无下班时间），需重试/人工确认"
                else:
                    # [M20] 按钮状态未知（offwork_state is None）：不再默认判成功，改从页面打卡时间二次确认
                    await self.send_notification("下班打卡", "按钮状态未知，尝试从页面打卡时间二次确认...")
                    times = await self.get_today_punch_times_from_page(skip_frame_switch=True)
                    if times.get("punch_out_time"):
                        return True, f"下班打卡成功(页面已记录下班时间 {times['punch_out_time']})"
                    return False, "无法验证下班打卡结果，需重试/人工确认"

            except Exception as e:
                await self.send_notification("下班打卡", f"验证打卡结果时出错: {str(e)}")
                # [M20] 验证块自身抛异常不再默认判成功，尝试二次确认页面打卡时间，仍无法确认则返回失败交由上层重试
                try:
                    times = await self.get_today_punch_times_from_page(skip_frame_switch=True)
                    if times.get("punch_out_time"):
                        return True, f"下班打卡成功(页面已记录下班时间 {times['punch_out_time']})"
                except Exception as verify_err:
                    await self.send_notification("下班打卡", f"二次确认页面打卡时间失败: {str(verify_err)}")
                return False, "下班打卡结果无法验证，需重试/人工确认"
            
        except Exception as e:
            error_msg = f"下班打卡过程发生错误: {str(e)}"
            await self.send_notification("下班打卡", error_msg)
            return False, error_msg
    
    async def get_attendance_status(self, skip_frame_switch: bool = False) -> Dict[str, str]:
        """
        获取今日和昨日的考勤状态信息
        
        Args:
            skip_frame_switch: 跳过frame切换（当已经在mainFrame时）
        """
        try:
            await self.send_notification("状态解析", "开始获取考勤状态信息...")
            
            # 1. 切换到mainFrame（可选）
            if not skip_frame_switch:
                if not await self._switch_to_main_frame():
                    return {"error": "切换到mainFrame失败"}
            
            status_info = {
                "today": "",
                "yesterday": "",
                "today_raw": "",
                "yesterday_raw": ""
            }
            
            # 2. 解析今日状态
            try:
                await self.send_notification("状态解析", "解析今日状态...")
                # 查找今日状态表格
                today_xpath = "//td[contains(@class,'border1')][contains(text(),'上班') or contains(text(),'下班') or contains(text(),'还未')]"
                # [M34] find_elements + 取第一个元素 get_attribute('innerHTML') 同步往返，
                # 集中到一个工作线程一次性读完，避免在主事件循环上排队阻塞（命令超时退化时最长约 45s）。
                def _read_today_html():
                    elems = self.driver.find_elements(By.XPATH, today_xpath)
                    if not elems:
                        return None
                    return elems[0].get_attribute('innerHTML')

                today_text = await self._run_blocking(_read_today_html)

                if today_text is not None:
                    status_info["today_raw"] = today_text

                    # 解析HTML内容
                    import re
                    # 移除HTML标签，保留文本
                    clean_text = re.sub(r'<[^>]+>', '', today_text)
                    status_info["today"] = clean_text.strip()
                    
                    await self.send_notification("状态解析", f"今日状态: {status_info['today']}")
                else:
                    await self.send_notification("状态解析", "未找到今日状态信息")
                    status_info["today"] = "未找到今日状态"
                    
            except Exception as e:
                await self.send_notification("状态解析", f"解析今日状态时出错: {str(e)}")
                status_info["today"] = f"解析错误: {str(e)}"
            
            # 3. 解析昨日状态
            try:
                await self.send_notification("状态解析", "解析昨日状态...")
                # 查找昨日状态表格 - 通常是第二个包含时间信息的元素
                yesterday_xpath = "//td[contains(@class,'border1')][contains(text(),'上班') and contains(text(),'下班')]"
                # [M34] find_elements + 逐个 element.get_attribute('innerHTML') 同步往返，
                # 集中到一个工作线程一次性读完所有 innerHTML（纯字符串列表），后续 break/回退逻辑在协程层基于字符串处理，
                # 避免逐次往返在主事件循环上排队阻塞。
                yesterday_html_list = await self._run_blocking(
                    lambda: [e.get_attribute('innerHTML') for e in self.driver.find_elements(By.XPATH, yesterday_xpath)]
                )

                if yesterday_html_list:
                    # 查找包含昨日日期的元素
                    for element_text in yesterday_html_list:
                        # 检查是否包含昨日日期模式
                        if '2025-07-21' in element_text or len(yesterday_html_list) > 1:
                            status_info["yesterday_raw"] = element_text

                            # 解析HTML内容
                            import re
                            clean_text = re.sub(r'<[^>]+>', '', element_text)
                            status_info["yesterday"] = clean_text.strip()
                            break

                    if not status_info["yesterday"]:
                        # 如果没找到特定昨日信息，使用最后一个元素
                        yesterday_text = yesterday_html_list[-1]
                        status_info["yesterday_raw"] = yesterday_text

                        import re
                        clean_text = re.sub(r'<[^>]+>', '', yesterday_text)
                        status_info["yesterday"] = clean_text.strip()
                    
                    await self.send_notification("状态解析", f"昨日状态: {status_info['yesterday']}")
                else:
                    await self.send_notification("状态解析", "未找到昨日状态信息")
                    status_info["yesterday"] = "未找到昨日状态"
                    
            except Exception as e:
                await self.send_notification("状态解析", f"解析昨日状态时出错: {str(e)}")
                status_info["yesterday"] = f"解析错误: {str(e)}"
            
            # 4. 尝试更通用的状态信息提取
            try:
                await self.send_notification("状态解析", "尝试通用状态信息提取...")
                # 查找所有包含"今日状态"和"昨日状态"的表格
                # [M34] 表格 find_elements + 每个表格 get_attribute('outerHTML') + find_elements(td) + 逐个 cell.text
                # 都是同步往返，集中到一个工作线程一次性读完为纯数据（每个表格: (html长度, [单元格文本...])），
                # 后续判断/通知在协程层基于这些字符串处理，避免大量往返在主事件循环上排队阻塞。
                def _read_status_tables():
                    tables = self.driver.find_elements(
                        By.XPATH, "//table[.//font[contains(text(),'今日状态') or contains(text(),'昨日状态')]]"
                    )
                    collected = []
                    for table in tables:
                        table_html = table.get_attribute('outerHTML')
                        cell_texts = [cell.text for cell in table.find_elements(By.TAG_NAME, "td")]
                        collected.append((len(table_html or ''), cell_texts))
                    return collected

                status_tables_data = await self._run_blocking(_read_status_tables)

                for table_html_len, cell_texts in status_tables_data:
                    await self.send_notification("状态解析", f"找到状态表格，长度: {table_html_len}")

                    # 查找表格中的具体状态信息
                    for cell_text in cell_texts:
                        if '上班' in cell_text and '2025-' in cell_text:
                            if '还未' in cell_text or '未' in cell_text:
                                if not status_info["today"] or status_info["today"] == "未找到今日状态":
                                    status_info["today"] = cell_text.strip()
                                    await self.send_notification("状态解析", f"通用方法找到今日状态: {cell_text}")
                            else:
                                if not status_info["yesterday"] or status_info["yesterday"] == "未找到昨日状态":
                                    status_info["yesterday"] = cell_text.strip()
                                    await self.send_notification("状态解析", f"通用方法找到昨日状态: {cell_text}")
                
            except Exception as e:
                await self.send_notification("状态解析", f"通用状态解析时出错: {str(e)}")
            
            # 5. 汇总结果
            if status_info["today"] and status_info["yesterday"]:
                await self.send_notification("状态解析", "状态信息获取完成")
            else:
                await self.send_notification("状态解析", "部分状态信息获取失败")
            
            return status_info
            
        except Exception as e:
            error_msg = f"获取考勤状态时发生错误: {str(e)}"
            await self.send_notification("状态解析", error_msg)
            return {"error": error_msg}

    async def get_today_punch_times_from_page(self, skip_frame_switch: bool = False) -> Dict[str, Optional[str]]:
        """从页面 DOM 解析今日上班/下班打卡时间（Selenium 版，对应传统模式 OCR get_punch_records_from_page）

        复用 get_attendance_status 抓取的今日状态文本，用与 OCR 版一致的正则提取 HH:MM，
        统一标准化为 HH:MM:SS 返回，供 attendance_system 在 selenium 模式下回写本地记录。

        Args:
            skip_frame_switch: 已在 mainFrame 时跳过 frame 切换

        Returns:
            dict: {'punch_in_time': 'HH:MM:SS'|None, 'punch_out_time': 'HH:MM:SS'|None}
        """
        result = {'punch_in_time': None, 'punch_out_time': None}
        try:
            status = await self.get_attendance_status(skip_frame_switch=skip_frame_switch)
            today_text = (status or {}).get('today', '') or ''
            today_raw = (status or {}).get('today_raw', '') or ''

            import re
            # 时间必须紧邻"上班/下班"关键字，避免命中 HTML 中无关的带冒号数字
            patterns = {
                'punch_in_time': [r'(\d{1,2}[:：]\d{2})\s*上班', r'上班\s*[:：]?\s*(\d{1,2}[:：]\d{2})'],
                'punch_out_time': [r'(\d{1,2}[:：]\d{2})\s*下班', r'下班\s*[:：]?\s*(\d{1,2}[:：]\d{2})'],
            }
            for key, pats in patterns.items():
                # 优先在清洗后的纯文本匹配，未命中再回退原始 HTML，降低误判
                for source in (today_text, today_raw):
                    matched = None
                    for pat in pats:
                        m = re.search(pat, source)
                        if m:
                            matched = m.group(1).replace('：', ':')
                            break
                    if matched:
                        if matched.count(':') == 1:
                            matched += ':00'  # 标准化为 HH:MM:SS
                        result[key] = matched
                        break

            await self.send_notification(
                "页面识别",
                f"页面解析今日打卡: 上班={result['punch_in_time'] or '未识别'} "
                f"下班={result['punch_out_time'] or '未识别'}"
            )
        except Exception as e:
            self.logger.error(f"Selenium 页面解析今日打卡时间失败: {str(e)}")
        return result

    async def complete_punch_in_flow(self, username: str, password: str) -> Tuple[bool, str, Dict]:
        """
        完整的上班打卡流程
        
        包括：登录 -> 检查按钮状态 -> 执行打卡或跳过 -> 记录状态
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            Tuple[bool, str, Dict]: (是否成功, 消息, 状态数据)
        """
        try:
            await self.send_notification("完整上班流程", "开始执行完整上班打卡流程...")
            
            # 1. 执行登录（包含启动浏览器、安全警告处理和登录）
            await self.send_notification("完整上班流程", "步骤1: 执行登录...")
            login_success, login_message = await self.login(username, password)
            if not login_success:
                return False, f"登录失败: {login_message}", {}
            
            await self.send_notification("完整上班流程", f"登录成功: {login_message}")
            
            # 2. 切换到mainFrame并检查按钮状态
            await self.send_notification("完整上班流程", "步骤2: 切换到mainFrame...")
            if not await self._switch_to_main_frame():
                return False, "切换到mainFrame失败", {}
            
            await self.send_notification("完整上班流程", "步骤3: 检查上班按钮状态...")
            button_status = await self._check_punch_button_status()
            
            # 3. 根据按钮状态决定是否打卡
            punch_result = {"punched": False, "message": "", "already_punched": False}

            gotowork_state = button_status.get("gotowork")
            if gotowork_state is False:
                # 确认上班按钮不可用，说明已经打过卡了
                await self.send_notification("完整上班流程", "上班按钮不可用，可能已经打过卡")
                punch_result["already_punched"] = True
                punch_result["message"] = "上班按钮不可用，可能已经打过卡"

                # 尝试从页面状态获取已打卡的上班时间并保存
                try:
                    # 如果能从 attendance_status 中获取上班时间，则保存
                    # 这里先等待后面获取 attendance_status 再处理
                    pass
                except Exception as e:
                    await self.send_notification(
                        "完整上班流程",
                        f"处理已打卡状态异常: {str(e)}"
                    )
            else:
                # [M20] gotowork_state 为 True（确认可用）或 None（状态未知）都尝试打卡：
                # 状态未知时不再默认“已打卡”而误报成功，交给 punch_in 内部重新检查+二次确认，
                # 由其返回真实成功/失败，避免静默漏打卡。
                if gotowork_state is None:
                    await self.send_notification("完整上班流程", "步骤4: 上班按钮状态未知，仍尝试执行上班打卡...")
                else:
                    await self.send_notification("完整上班流程", "步骤4: 执行上班打卡...")
                punch_success, punch_message = await self.punch_in(skip_frame_switch=True, skip_button_check=True)
                punch_result["punched"] = punch_success
                punch_result["message"] = punch_message
                
                if punch_success:
                    await self.send_notification("完整上班流程", f"上班打卡成功: {punch_message}")
                    
                    # 自动保存上班打卡时间到记录管理器
                    try:
                        current_time = datetime.now().strftime('%H:%M:%S')
                        self.record_manager.update_punch_record(
                            punch_type="punch_in",
                            time_str=current_time,
                            additional_info={
                                "method": "selenium",
                                "message": punch_message,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }
                        )
                        await self.send_notification(
                            "完整上班流程", 
                            f"上班打卡记录已保存: {current_time}"
                        )
                    except Exception as record_error:
                        await self.send_notification(
                            "完整上班流程", 
                            f"保存打卡记录失败: {str(record_error)}"
                        )
                        # 不影响主流程，继续执行
                else:
                    await self.send_notification("完整上班流程", f"上班打卡失败: {punch_message}")
            
            # 4. 检查今日状态，记录打卡数据（跳过重复的frame切换）
            await self.send_notification("完整上班流程", "步骤5: 获取今日考勤状态...")
            attendance_status = await self.get_attendance_status(skip_frame_switch=True)
            
            # 如果是已打卡情况，尝试从 attendance_status 中获取上班时间并保存
            if punch_result["already_punched"] and attendance_status:
                try:
                    # 尝试从 attendance_status 中提取上班时间
                    punch_in_time = None
                    
                    # 检查不同可能的字段名称
                    for field in ['punch_in', 'gotowork_time', 'in_time', '上班时间']:
                        if field in attendance_status and attendance_status[field]:
                            punch_in_time = attendance_status[field]
                            break
                    
                    if punch_in_time:
                        # 保存到记录管理器
                        self.record_manager.update_punch_record(
                            punch_type="punch_in",
                            time_str=punch_in_time,
                            additional_info={
                                "method": "selenium",
                                "message": "从页面状态获取的已打卡时间",
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "source": "attendance_status"
                            }
                        )
                        await self.send_notification(
                            "完整上班流程", 
                            f"已保存从状态获取的上班时间: {punch_in_time}"
                        )
                    else:
                        await self.send_notification(
                            "完整上班流程", 
                            "无法从页面状态中获取上班时间"
                        )
                        
                except Exception as status_error:
                    await self.send_notification(
                        "完整上班流程", 
                        f"处理已打卡状态失败: {str(status_error)}"
                    )
            
            # 5. 汇总结果
            flow_result = {
                "login_success": True,
                "login_message": login_message,
                "button_status": button_status,
                "punch_result": punch_result,
                "attendance_status": attendance_status,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            if punch_result["punched"]:
                overall_message = f"完整上班流程成功完成 - 已执行打卡"
            elif punch_result["already_punched"]:
                overall_message = f"完整上班流程成功完成 - 之前已打卡"
            else:
                overall_message = f"完整上班流程部分完成 - 打卡未成功: {punch_result['message']}"
            
            await self.send_notification("完整上班流程", overall_message)
            
            # 根据是否成功打卡或已打卡来确定整体成功状态
            overall_success = punch_result["punched"] or punch_result["already_punched"]
            
            return overall_success, overall_message, flow_result
            
        except Exception as e:
            error_msg = f"完整上班流程执行异常: {str(e)}"
            await self.send_notification("完整上班流程", error_msg)
            self.logger.exception("完整上班流程异常")
            return False, error_msg, {}
    
    async def _detect_mainframe_changes(self) -> Dict[str, any]:
        """
        检测mainFrame是否出现变化（时间不足提示）
        
        Returns:
            Dict: {
                "has_time_warning": bool,  # 是否有时间警告
                "time_text": str,          # 时间相关文本
                "warning_content": str,    # 完整警告内容
                "buttons_still_exist": bool # 打卡按钮是否仍然存在
            }
        """
        try:
            await self.send_notification("Frame变化检测", "开始检测mainFrame变化...")
            
            result = {
                "has_time_warning": False,
                "time_text": "",
                "warning_content": "",
                "buttons_still_exist": True
            }
            
            # 1. 检查是否仍有打卡按钮（判断页面是否发生变化）
            # [M34] 两次 find_element 同步往返，放线程一次性查完；任一缺失抛 NoSuchElementException
            # 原样透传回协程层，保持下方 except 逻辑不变。
            def _both_punch_buttons_exist():
                self.driver.find_element(By.NAME, "gotowork")
                self.driver.find_element(By.NAME, "offwork")
                return True
            try:
                await self._run_blocking(_both_punch_buttons_exist)
                result["buttons_still_exist"] = True
                await self.send_notification("Frame变化检测", "检测到打卡按钮仍存在，页面未发生重大变化")
            except NoSuchElementException:
                result["buttons_still_exist"] = False
                await self.send_notification("Frame变化检测", "未检测到打卡按钮，页面可能发生了变化")
            
            # 2. 查找时间不足相关的警告文本
            time_warning_patterns = [
                r"未到下班时间.*?或您今日的工作时间未满",
                r"工作时间未满",
                r"未到下班时间",
                r"仅仅.*?小时.*?分钟"
            ]
            
            # 获取页面所有文本内容
            # [M34] page_source（整页 HTML，可能很大）与 body.text 都是同步往返，
            # 放线程一次性读完，避免在主事件循环上排队阻塞（命令超时退化时最长约 45s）。
            try:
                page_source, body_text = await self._run_blocking(
                    lambda: (self.driver.page_source, self.driver.find_element(By.TAG_NAME, "body").text)
                )

                import re
                for pattern in time_warning_patterns:
                    matches = re.search(pattern, body_text, re.IGNORECASE | re.DOTALL)
                    if matches:
                        result["has_time_warning"] = True
                        result["warning_content"] = matches.group(0)
                        await self.send_notification("Frame变化检测", f"检测到时间警告: {matches.group(0)[:50]}...")
                        break
                
                # 3. 专门查找"仅仅X小时Y分钟"格式的文本
                time_text_pattern = r"仅仅\s*(\d+)\s*小时\s*(\d+)\s*分钟"
                time_matches = re.search(time_text_pattern, body_text)
                if time_matches:
                    result["time_text"] = time_matches.group(0)
                    await self.send_notification("Frame变化检测", f"找到工作时间文本: {result['time_text']}")
                else:
                    # 尝试更宽松的匹配
                    loose_time_pattern = r"(\d+)\s*小时\s*(\d+)\s*分钟"
                    loose_matches = re.findall(loose_time_pattern, body_text)
                    if loose_matches:
                        # 取最后一个匹配（通常是最相关的）
                        hours, minutes = loose_matches[-1]
                        result["time_text"] = f"仅仅{hours}小时{minutes}分钟"
                        await self.send_notification("Frame变化检测", f"使用宽松匹配找到时间文本: {result['time_text']}")
                
            except Exception as e:
                await self.send_notification("Frame变化检测", f"获取页面内容时出错: {str(e)}")
            
            # 4. 查找特定的时间警告元素
            warning_selectors = [
                (By.XPATH, "//td[contains(text(),'未到下班时间')]"),
                (By.XPATH, "//td[contains(text(),'工作时间未满')]"),
                (By.XPATH, "//div[contains(text(),'仅仅')]"),
                (By.XPATH, "//span[contains(text(),'小时') and contains(text(),'分钟')]"),
                (By.CSS_SELECTOR, "td.border1")
            ]
            
            # [M34] 逐个 selector 的 find_elements + 逐个 element.text 都是同步往返，
            # 集中到一个工作线程一次性读出每个 selector 命中的纯文本列表（保留 selector 顺序、
            # 单个 selector 失败则该项为空列表以等价原 except: continue），
            # 后续关键字匹配/通知在协程层处理，避免大量往返在主事件循环上排队阻塞。
            def _read_warning_texts():
                collected = []
                for by, selector in warning_selectors:
                    try:
                        collected.append([el.text for el in self.driver.find_elements(by, selector)])
                    except Exception:
                        collected.append([])
                return collected

            warning_texts_by_selector = await self._run_blocking(_read_warning_texts)

            for element_texts in warning_texts_by_selector:
                for element_text in element_texts:
                    if any(keyword in element_text for keyword in ["未到下班时间", "工作时间未满", "仅仅", "小时", "分钟"]):
                        result["has_time_warning"] = True
                        if not result["warning_content"]:
                            result["warning_content"] = element_text

                        # 尝试从元素中提取时间信息
                        import re
                        time_match = re.search(r"仅仅\s*(\d+)\s*小时\s*(\d+)\s*分钟", element_text)
                        if time_match and not result["time_text"]:
                            result["time_text"] = time_match.group(0)

                        await self.send_notification("Frame变化检测", f"通过元素检测找到警告: {element_text[:30]}...")
                        break
            
            # 5. 汇总检测结果
            if result["has_time_warning"]:
                await self.send_notification(
                    "Frame变化检测", 
                    f"检测完成 - 发现时间警告，时间文本: '{result['time_text']}'"
                )
            else:
                await self.send_notification("Frame变化检测", "检测完成 - 未发现时间警告")
            
            return result
            
        except Exception as e:
            error_msg = f"Frame变化检测异常: {str(e)}"
            await self.send_notification("Frame变化检测", error_msg)
            return {
                "has_time_warning": False,
                "time_text": "",
                "warning_content": "",
                "buttons_still_exist": True,
                "error": error_msg
            }
    
    async def _parse_work_time_text(self, time_text: str) -> Dict[str, any]:
        """
        解析工作时间文本，提取小时和分钟
        
        支持格式：
        - "仅仅2小时13分钟"
        - "2小时13分钟"
        - "仅仅 2 小时 13 分钟"
        
        Args:
            time_text: 包含时间信息的文本
            
        Returns:
            Dict: {
                "success": bool,
                "hours": int,
                "minutes": int,  
                "total_minutes": int,
                "original_text": str,
                "error": str (如果失败)
            }
        """
        try:
            await self.send_notification("时间解析", f"[DEBUG] 开始解析时间文本: '{time_text}'")
            
            import re
            
            # 支持多种时间格式的正则表达式
            patterns = [
                r"仅仅\s*(\d+)\s*小时\s*(\d+)\s*分钟",      # "仅仅2小时13分钟"
                r"(\d+)\s*小时\s*(\d+)\s*分钟",            # "2小时13分钟"
                r"仅仅.*?(\d+).*?小时.*?(\d+).*?分钟",     # 宽松匹配 "仅仅...2...小时...13...分钟"
                r"工作.*?(\d+).*?小时.*?(\d+).*?分钟"      # "工作2小时13分钟"
            ]
            
            result = {
                "success": False,
                "hours": 0,
                "minutes": 0,
                "total_minutes": 0,
                "original_text": time_text,
                "error": ""
            }
            
            # 尝试各种模式
            for i, pattern in enumerate(patterns):
                await self.send_notification("时间解析", f"[DEBUG] 尝试模式{i+1}: {pattern}")
                match = re.search(pattern, time_text)
                if match:
                    try:
                        hours = int(match.group(1))
                        minutes = int(match.group(2))
                        
                        await self.send_notification("时间解析", f"[DEBUG] 模式{i+1}匹配成功: {hours}小时{minutes}分钟")
                        
                        # 验证时间的合理性
                        if 0 <= hours <= 24 and 0 <= minutes <= 59:
                            result["success"] = True
                            result["hours"] = hours
                            result["minutes"] = minutes
                            result["total_minutes"] = hours * 60 + minutes
                            
                            await self.send_notification(
                                "时间解析", 
                                f"[DEBUG] 解析成功 - {hours}小时{minutes}分钟，总计{result['total_minutes']}分钟 (计算: {hours}*60+{minutes}={result['total_minutes']})"
                            )
                            return result
                        else:
                            await self.send_notification("时间解析", f"[DEBUG] 时间值不合理: {hours}小时{minutes}分钟")
                            
                    except ValueError as e:
                        await self.send_notification("时间解析", f"[DEBUG] 数字转换失败: {str(e)}")
                        continue
                else:
                    await self.send_notification("时间解析", f"[DEBUG] 模式{i+1}未匹配")
            
            # 如果所有模式都失败了，尝试更宽松的数字提取
            await self.send_notification("时间解析", f"[DEBUG] 所有精确模式均失败，尝试宽松数字提取")
            numbers = re.findall(r'\d+', time_text)
            await self.send_notification("时间解析", f"[DEBUG] 提取到的数字: {numbers}")
            if len(numbers) >= 2:
                try:
                    # 假设前两个数字分别是小时和分钟
                    hours = int(numbers[0])
                    minutes = int(numbers[1])
                    
                    await self.send_notification("时间解析", f"[DEBUG] 宽松模式解析: {hours}小时{minutes}分钟")
                    
                    if 0 <= hours <= 24 and 0 <= minutes <= 59:
                        result["success"] = True
                        result["hours"] = hours
                        result["minutes"] = minutes
                        result["total_minutes"] = hours * 60 + minutes
                        
                        await self.send_notification(
                            "时间解析", 
                            f"[DEBUG] 宽松解析成功 - {hours}小时{minutes}分钟，总计{result['total_minutes']}分钟 (计算: {hours}*60+{minutes}={result['total_minutes']})"
                        )
                        return result
                        
                except ValueError as e:
                    await self.send_notification("时间解析", f"[DEBUG] 宽松模式数字转换失败: {str(e)}")
            
            # 完全失败
            result["error"] = f"无法从文本中解析出有效的时间信息: '{time_text}'"
            await self.send_notification("时间解析", f"[DEBUG] {result['error']}")
            return result
            
        except Exception as e:
            error_msg = f"时间解析异常: {str(e)}"
            await self.send_notification("时间解析", f"[DEBUG] {error_msg}")
            return {
                "success": False,
                "hours": 0,
                "minutes": 0,
                "total_minutes": 0,
                "original_text": time_text,
                "error": error_msg
            }
    
    async def _calculate_remaining_time(self, worked_minutes: int) -> Dict[str, any]:
        """
        计算剩余工作时间
        
        标准工作时间：8小时16分钟 = 496分钟
        
        Args:
            worked_minutes: 已工作的分钟数
            
        Returns:
            Dict: {
                "standard_minutes": int,      # 标准工作时间（分钟）
                "worked_minutes": int,        # 已工作时间（分钟）
                "remaining_minutes": int,     # 剩余工作时间（分钟）
                "remaining_hours": int,       # 剩余工作时间（小时部分）
                "remaining_mins": int,        # 剩余工作时间（分钟部分）
                "is_overtime": bool,          # 是否已超时
                "completion_percentage": float # 完成百分比
            }
        """
        try:
            await self.send_notification("时间计算", f"[DEBUG] 开始计算剩余时间，已工作: {worked_minutes}分钟")
            
            # 标准工作时间：8小时16分钟
            standard_minutes = 8 * 60 + 16  # 496分钟
            
            await self.send_notification("时间计算", f"[DEBUG] 标准工作时间: {standard_minutes}分钟 (8*60+16={8*60}+16={standard_minutes})")
            
            remaining_minutes = standard_minutes - worked_minutes
            
            await self.send_notification("时间计算", f"[DEBUG] 剩余时间计算: {standard_minutes}-{worked_minutes}={remaining_minutes}分钟")
            is_overtime = remaining_minutes < 0
            
            # 如果已经超时，剩余时间为0
            if is_overtime:
                remaining_minutes = 0
            
            # 计算剩余时间的小时和分钟
            remaining_hours = remaining_minutes // 60
            remaining_mins = remaining_minutes % 60
            
            # 计算完成百分比
            completion_percentage = (worked_minutes / standard_minutes) * 100
            if completion_percentage > 100:
                completion_percentage = 100
            
            result = {
                "standard_minutes": standard_minutes,
                "worked_minutes": worked_minutes,
                "remaining_minutes": remaining_minutes,
                "remaining_hours": remaining_hours,
                "remaining_mins": remaining_mins,
                "is_overtime": is_overtime,
                "completion_percentage": round(completion_percentage, 2)
            }
            
            if is_overtime:
                await self.send_notification(
                    "时间计算", 
                    f"[DEBUG] 已超时工作，完成度: {completion_percentage:.1f}%"
                )
            else:
                await self.send_notification(
                    "时间计算", 
                    f"[DEBUG] 还需工作: {remaining_hours}小时{remaining_mins}分钟，完成度: {completion_percentage:.1f}% (分解: {remaining_minutes}//{60}={remaining_hours}, {remaining_minutes}%60={remaining_mins})"
                )
            
            return result
            
        except Exception as e:
            error_msg = f"时间计算异常: {str(e)}"
            await self.send_notification("时间计算", f"[DEBUG] {error_msg}")
            return {
                "standard_minutes": 496,
                "worked_minutes": worked_minutes,
                "remaining_minutes": 0,
                "remaining_hours": 0,
                "remaining_mins": 0,
                "is_overtime": False,
                "completion_percentage": 0,
                "error": error_msg
            }
    
    async def _estimate_off_work_time(self, remaining_minutes: int) -> str:
        """
        推算预计下班时间
        
        Args:
            remaining_minutes: 剩余工作时间（分钟）
            
        Returns:
            str: 预计下班时间 (格式: "HH:MM")
        """
        try:
            await self.send_notification("时间推算", f"[DEBUG] 开始推算下班时间，剩余: {remaining_minutes}分钟")
            
            from datetime import datetime, timedelta
            
            # 获取当前时间
            current_time = datetime.now()
            
            await self.send_notification("时间推算", f"[DEBUG] 当前时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 计算预计下班时间
            estimated_off_time = current_time + timedelta(minutes=remaining_minutes)
            
            await self.send_notification("时间推算", f"[DEBUG] 时间加法: {current_time.strftime('%H:%M')} + {remaining_minutes}分钟 = {estimated_off_time.strftime('%H:%M')}")
            
            # 格式化为HH:MM字符串
            estimated_time_str = estimated_off_time.strftime("%H:%M")
            
            await self.send_notification(
                "时间推算", 
                f"[DEBUG] 最终结果 - 当前时间: {current_time.strftime('%H:%M')}, 预计下班时间: {estimated_time_str}"
            )
            
            return estimated_time_str
            
        except Exception as e:
            error_msg = f"时间推算异常: {str(e)}"
            await self.send_notification("时间推算", f"[DEBUG] {error_msg}")
            return "计算失败"
    
    async def complete_punch_out_flow(self, username: str, password: str) -> Tuple[bool, str, Dict]:
        """
        完整的下班打卡流程
        
        包括：登录 -> 检查按钮状态 -> 执行打卡 -> 处理时间不足提示 -> 记录状态
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            Tuple[bool, str, Dict]: (是否成功, 消息, 状态数据)
        """
        try:
            await self.send_notification("完整下班流程", "开始执行完整下班打卡流程...")
            
            # 1. 执行登录（包含启动浏览器、安全警告处理和登录）
            await self.send_notification("完整下班流程", "步骤1: 执行登录...")
            login_success, login_message = await self.login(username, password)
            if not login_success:
                return False, f"登录失败: {login_message}", {}
            
            await self.send_notification("完整下班流程", f"登录成功: {login_message}")
            
            # 2. 切换到mainFrame并检查按钮状态
            await self.send_notification("完整下班流程", "步骤2: 切换到mainFrame...")
            if not await self._switch_to_main_frame():
                return False, "切换到mainFrame失败", {}
            
            await self.send_notification("完整下班流程", "步骤3: 检查下班按钮状态...")
            button_status = await self._check_punch_button_status()
            
            # 3. 根据按钮状态决定是否打卡
            punch_result = {"punched": False, "message": "", "already_punched": False}

            offwork_state = button_status.get("offwork")
            if offwork_state is False:
                # 确认下班按钮不可用：需区分"已完成上下班"与"今日尚未上班打卡"——后者下班按钮同样禁用。
                if button_status.get("gotowork") is True:
                    # 上班按钮仍可用，说明今日尚未上班打卡，应判为失败而非"已打过下班卡"，
                    # 避免掩盖"没上班、下班也没打成"的真实异常，让上层落入既有失败分支。
                    await self.send_notification("完整下班流程", "下班按钮不可用且上班按钮仍可用，疑似今日尚未上班打卡")
                    punch_result["message"] = "下班按钮不可用且上班按钮仍可用，疑似今日尚未上班打卡"
                else:
                    # 上班按钮也不可用，确为今日已完成上下班打卡
                    await self.send_notification("完整下班流程", "下班按钮不可用，今日应已打过下班卡")
                    punch_result["already_punched"] = True
                    punch_result["message"] = "下班按钮不可用，今日应已打过下班卡"
            else:
                # [M20] offwork_state 为 True（确认可用）或 None（状态未知）都尝试打卡：
                # 状态未知时不再默认“已打过下班卡”而误报成功，交给 punch_out 内部重新检查+二次确认，
                # 由其返回真实成功/失败，避免下班卡静默漏打。
                if offwork_state is None:
                    await self.send_notification("完整下班流程", "步骤4: 下班按钮状态未知，仍尝试执行下班打卡...")
                else:
                    await self.send_notification("完整下班流程", "步骤4: 执行下班打卡...")
                punch_success, punch_message = await self.punch_out(skip_frame_switch=True, skip_button_check=True)
                punch_result["punched"] = punch_success
                punch_result["message"] = punch_message
                
                if punch_success:
                    await self.send_notification("完整下班流程", f"下班打卡成功: {punch_message}")

                    # 自动保存下班打卡时间到记录管理器
                    try:
                        current_time = datetime.now().strftime('%H:%M:%S')
                        self.record_manager.update_punch_record(
                            punch_type="punch_out",
                            time_str=current_time,
                            additional_info={
                                "method": "selenium",
                                "message": punch_message,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }
                        )
                        await self.send_notification(
                            "完整下班流程",
                            f"下班打卡记录已保存: {current_time}"
                        )
                    except Exception as record_error:
                        await self.send_notification(
                            "完整下班流程",
                            f"保存打卡记录失败: {str(record_error)}"
                        )
                        # 不影响主流程，继续执行
                else:
                    await self.send_notification("完整下班流程", f"下班打卡失败: {punch_message}")

            # 4. 检查mainFrame是否出现变化（时间不足提示）
            await self.send_notification("完整下班流程", "步骤5: 检查mainFrame变化...")
            frame_changes = await self._detect_mainframe_changes()
            
            time_calculation_result = None
            
            if frame_changes.get("has_time_warning", False):
                await self.send_notification("完整下班流程", "[DEBUG] 检测到工作时间不足提示，开始双路径时间计算...")
                
                # 实现双路径时间计算逻辑
                worked_minutes = None
                calculation_method = None
                
                # 路径检测：检查今日是否有上班打卡记录
                await self.send_notification("完整下班流程", "[DEBUG] 启动双路径计算：检查历史数据")
                history_worked_minutes = self.record_manager.calculate_worked_minutes_from_history()
                await self.send_notification("完整下班流程", f"[DEBUG] 历史数据查询结果: {history_worked_minutes}")
                
                if history_worked_minutes is not None:
                    # 路径B：从历史数据计算工作时间
                    await self.send_notification("完整下班流程", f"[DEBUG] 选择路径B: 从历史数据计算工作时间")
                    worked_minutes = history_worked_minutes
                    calculation_method = "history_data"
                    await self.send_notification(
                        "完整下班流程", 
                        f"[DEBUG] 从历史数据计算得出已工作时间: {worked_minutes}分钟"
                    )
                else:
                    # 路径A：从页面文本解析工作时间
                    await self.send_notification("完整下班流程", f"[DEBUG] 选择路径A: 从页面文本解析工作时间")
                    work_time_text = frame_changes.get("time_text", "")
                    await self.send_notification("完整下班流程", f"[DEBUG] 获取到的页面时间文本: '{work_time_text}'")
                    parsed_time = await self._parse_work_time_text(work_time_text)
                    
                    if parsed_time.get("success", False):
                        worked_minutes = parsed_time["total_minutes"]
                        calculation_method = "page_parsing"
                        await self.send_notification(
                            "完整下班流程", 
                            f"[DEBUG] 从页面文本解析得出已工作时间: {worked_minutes}分钟 (原文: '{work_time_text}')"
                        )
                    else:
                        await self.send_notification("完整下班流程", f"[DEBUG] 路径A失败: {parsed_time.get('error', '未知错误')}")
                
                # 统一时间计算流程
                if worked_minutes is not None:
                    await self.send_notification("完整下班流程", f"[DEBUG] 进入统一时间计算流程，已工作: {worked_minutes}分钟")

                    # 计算剩余工作时间
                    remaining_time = await self._calculate_remaining_time(worked_minutes)

                    # 推算预计下班时间
                    estimated_time = await self._estimate_off_work_time(remaining_time["remaining_minutes"])

                    remaining_minutes = remaining_time["remaining_minutes"]
                    remaining_time_str = f"{remaining_minutes // 60}小时{remaining_minutes % 60}分钟"

                    time_calculation_result = {
                        "worked_minutes": worked_minutes,
                        "remaining_minutes": remaining_minutes,
                        "remaining_time_str": remaining_time_str,
                        "estimated_off_time": estimated_time,
                        "calculation_method": calculation_method,
                        "confirmation_needed": True
                    }
                    
                    await self.send_notification(
                        "完整下班流程", 
                        f"[DEBUG] 双路径时间计算完成 ({calculation_method}) - 已工作: {worked_minutes}分钟, 剩余: {remaining_time['remaining_minutes']}分钟, 预计下班: {estimated_time}"
                    )
                else:
                    await self.send_notification("完整下班流程", "[DEBUG] 双路径时间计算均失败，无法确定工作时间")
                    time_calculation_result = {"error": "双路径时间计算均失败"}
            
            # 5. 获取考勤状态（如果没有时间警告，或者作为补充信息）（跳过重复的frame切换）
            if not frame_changes.get("has_time_warning", False):
                await self.send_notification("完整下班流程", "步骤8: 获取今日考勤状态...")
                attendance_status = await self.get_attendance_status(skip_frame_switch=True)
            else:
                attendance_status = {"note": "因检测到时间警告，跳过状态解析"}
            
            # 6. 汇总结果
            flow_result = {
                "login_success": True,
                "login_message": login_message,
                "button_status": button_status,
                "punch_result": punch_result,
                "frame_changes": frame_changes,
                "time_calculation": time_calculation_result,
                "attendance_status": attendance_status,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # 确定整体结果消息
            if punch_result["punched"]:
                if time_calculation_result and time_calculation_result.get("confirmation_needed"):
                    overall_message = f"下班打卡执行，但工作时间不足，需用户确认自动下班时间"
                else:
                    overall_message = f"完整下班流程成功完成 - 已执行打卡"
            elif punch_result["already_punched"]:
                overall_message = f"完整下班流程成功完成 - 之前已打卡"
            else:
                overall_message = f"完整下班流程部分完成 - 打卡未成功: {punch_result['message']}"
            
            await self.send_notification("完整下班流程", overall_message)
            
            # 根据是否成功打卡或已打卡来确定整体成功状态
            overall_success = punch_result["punched"] or punch_result["already_punched"]
            
            return overall_success, overall_message, flow_result
            
        except Exception as e:
            error_msg = f"完整下班流程执行异常: {str(e)}"
            await self.send_notification("完整下班流程", error_msg)
            self.logger.exception("完整下班流程异常")
            return False, error_msg, {}


class ParallelSeleniumLogin:
    """并行Selenium登录管理器"""
    
    def __init__(self, login_url: str, headless: bool = False, notification_callback=None, browser_type: str = "edge"):
        """
        初始化并行登录管理器
        
        Args:
            login_url: 登录页面URL
            headless: 是否使用无头模式
            notification_callback: 通知回调函数
            browser_type: 浏览器类型
        """
        self.login_url = login_url
        self.headless = headless
        self.notification_callback = notification_callback
        self.browser_type = browser_type
        self.logger = logging.getLogger(__name__)
        self.active_controllers: Dict[str, SeleniumLoginController] = {}
    
    async def parallel_login(self, users: List[Dict[str, str]], max_concurrent: int = 3) -> Dict[str, Tuple[bool, str]]:
        """
        并行执行多用户登录
        
        Args:
            users: 用户列表，每个用户包含 {'username': '', 'password': '', 'user_id': ''}
            max_concurrent: 最大并发数
            
        Returns:
            Dict[str, Tuple[bool, str]]: 每个用户的登录结果 {user_id: (是否成功, 消息)}
        """
        if self.notification_callback:
            await self.notification_callback("并行登录", f"开始并行登录，用户数: {len(users)}, 最大并发: {max_concurrent}")
        
        # 使用信号量控制并发数
        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}
        
        async def login_single_user(user_info: Dict[str, str]) -> Tuple[str, Tuple[bool, str]]:
            """单个用户登录任务"""
            user_id = user_info['user_id']
            username = user_info['username'] 
            password = user_info['password']
            
            async with semaphore:
                # 为每个用户创建独立的登录控制器
                controller = SeleniumLoginController(
                    login_url=self.login_url,
                    headless=self.headless,
                    notification_callback=self._create_user_notification_callback(user_id),
                    browser_type=self.browser_type
                )
                
                self.active_controllers[user_id] = controller
                
                try:
                    result = await controller.login(username, password)
                    if self.notification_callback:
                        await self.notification_callback(
                            f"用户{user_id}登录", 
                            f"登录{'成功' if result[0] else '失败'}: {result[1]}"
                        )
                    return user_id, result
                    
                except Exception as e:
                    error_msg = f"登录异常: {str(e)}"
                    if self.notification_callback:
                        await self.notification_callback(f"用户{user_id}登录", f"登录异常: {error_msg}")
                    return user_id, (False, error_msg)
                    
                finally:
                    # 清理资源
                    if user_id in self.active_controllers:
                        try:
                            controller.close()
                        except:
                            pass
                        del self.active_controllers[user_id]
        
        # 创建所有登录任务
        tasks = [login_single_user(user) for user in users]
        
        # 并行执行所有登录任务
        if self.notification_callback:
            await self.notification_callback("并行登录", "所有登录任务已创建，开始并行执行...")
        
        completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        for task_result in completed_tasks:
            if isinstance(task_result, Exception):
                self.logger.error(f"并行登录任务异常: {task_result}")
                # 为异常任务创建失败结果
                results["unknown"] = (False, f"任务异常: {str(task_result)}")
            else:
                user_id, login_result = task_result
                results[user_id] = login_result
        
        # 汇总结果
        success_count = sum(1 for success, _ in results.values() if success)
        total_count = len(results)
        
        if self.notification_callback:
            await self.notification_callback(
                "并行登录完成", 
                f"总用户数: {total_count}, 成功: {success_count}, 失败: {total_count - success_count}"
            )
        
        return results
    
    def _create_user_notification_callback(self, user_id: str):
        """为特定用户创建通知回调"""
        if not self.notification_callback:
            return None
            
        async def user_notification(context: str, message: str):
            # 在消息前加上用户标识
            await self.notification_callback(f"[{user_id}]{context}", message)
            
        return user_notification
    
    async def get_login_status(self) -> Dict[str, str]:
        """获取当前所有活跃登录会话的状态"""
        status = {}
        for user_id, controller in self.active_controllers.items():
            try:
                if controller.driver:
                    current_url = controller.driver.current_url
                    page_title = controller.driver.title
                    status[user_id] = f"活跃 - URL: {current_url}, 标题: {page_title}"
                else:
                    status[user_id] = "无活跃会话"
            except Exception as e:
                status[user_id] = f"状态检查失败: {str(e)}"
        
        return status
    
    def close_all(self):
        """关闭所有活跃的登录会话"""
        for user_id, controller in self.active_controllers.items():
            try:
                controller.close()
                self.logger.info(f"用户{user_id}的登录会话已关闭")
            except Exception as e:
                self.logger.error(f"关闭用户{user_id}会话时出错: {e}")
        
        self.active_controllers.clear()
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close_all()