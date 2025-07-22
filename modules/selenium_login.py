"""
Selenium登录控制器

用于替代PyAutoGUI图像识别的登录方式，提供更精确和可靠的浏览器自动化操作
"""

import asyncio
import logging
import time
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
    ElementNotInteractableException
)
from webdriver_manager.microsoft import EdgeChromiumDriverManager


class SeleniumLoginController:
    """Selenium登录控制器"""
    
    def __init__(self, login_url: str, headless: bool = False, notification_callback=None, browser_type: str = "edge"):
        """
        初始化登录控制器
        
        Args:
            login_url: 登录页面URL
            headless: 是否使用无头模式
            notification_callback: 通知回调函数，用于发送状态消息
            browser_type: 浏览器类型 ("edge" 或 "chrome")
        """
        self.login_url = login_url
        self.headless = headless
        self.notification_callback = notification_callback
        self.browser_type = browser_type.lower()
        self.logger = logging.getLogger(__name__)
        self.driver = None
        self.wait = None
        
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
    
    async def start_browser(self) -> bool:
        """启动浏览器并导航到登录页面"""
        browsers_to_try = ["edge", "chrome"] if self.browser_type == "edge" else ["chrome", "edge"]
        
        for browser in browsers_to_try:
            try:
                browser_name = "Chrome" if browser == "chrome" else "Edge"
                await self.send_notification("Selenium登录", f"正在尝试启动{browser_name}浏览器...")
                
                # 创建WebDriver实例
                if browser == "chrome":
                    chrome_options = self._setup_chrome_options()
                    self.driver = webdriver.Chrome(options=chrome_options)
                else:
                    # Edge WebDriver - 直接使用项目目录中的WebDriver
                    edge_options = self._setup_edge_options()
                    import os
                    project_driver_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'msedgedriver.exe')
                    service = Service(project_driver_path)
                    await self.send_notification("Selenium登录", f"使用项目目录WebDriver: {project_driver_path}")
                    self.driver = webdriver.Edge(service=service, options=edge_options)
                
                await self.send_notification("Selenium登录", f"{browser_name} WebDriver实例创建成功")
                self.wait = WebDriverWait(self.driver, 10)
                
                await self.send_notification("Selenium登录", f"正在访问登录页面: {self.login_url}")
                
                # 导航到登录页面
                self.driver.get(self.login_url)
                await self.send_notification("Selenium登录", "页面导航请求已发送")
                
                # 等待页面加载完成
                await self.send_notification("Selenium登录", "等待页面加载...")
                try:
                    # 使用5秒超时时间
                    wait_short = WebDriverWait(self.driver, 5)
                    wait_short.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                    await self.send_notification("Selenium登录", "页面body元素已加载")
                except TimeoutException:
                    # 如果body加载失败，尝试检查是否有任何元素
                    await self.send_notification("Selenium登录", "body加载超时，检查页面状态...")
                    current_url = self.driver.current_url
                    page_title = self.driver.title
                    await self.send_notification("Selenium登录", f"当前URL: {current_url}, 页面标题: {page_title}")
                    
                    # 尝试查找任何元素来确认页面是否加载
                    try:
                        self.driver.find_element(By.TAG_NAME, "html")
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
        return False
    
    async def handle_security_warnings(self) -> bool:
        """处理安全警告弹窗"""
        try:
            await self.send_notification("安全警告", "检查是否存在安全警告弹窗...")
            
            # 处理SSL证书警告
            try:
                # Chrome/Edge的高级选项按钮
                advanced_button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.ID, "details-button"))
                )
                await self.send_notification("安全警告", "发现SSL证书警告，点击高级选项...")
                advanced_button.click()
                await asyncio.sleep(1)
                
                # 点击继续访问链接
                proceed_link = self.driver.find_element(By.ID, "proceed-link")
                await self.send_notification("安全警告", "点击继续访问链接...")
                proceed_link.click()
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
                    element = WebDriverWait(self.driver, 2).until(
                        EC.element_to_be_clickable((by, selector))
                    )
                    await self.send_notification("安全警告", f"发现警告元素，点击处理: {selector}")
                    element.click()
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
        """使用多种选择器策略查找元素"""
        for by, selector in selectors:
            try:
                element = self.wait.until(EC.presence_of_element_located((by, selector)))
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
                self.driver.switch_to.frame("mainFrame")
                
                # 等待login.jsp页面加载
                await asyncio.sleep(2)
                
                # 验证是否成功切换到登录页面
                await self.send_notification("登录流程", "检查登录frame内容...")
                try:
                    # 查找登录表单元素
                    login_inputs = self.driver.find_elements(By.TAG_NAME, "input")
                    await self.send_notification("登录流程", f"在登录frame中发现{len(login_inputs)}个input元素")
                    
                    # 检查是否有预期的登录字段
                    found_loginname = False
                    found_password2 = False
                    for input_elem in login_inputs:
                        input_name = input_elem.get_attribute('name') or ''
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
            username_element = self._find_element_by_multiple_selectors(
                self.username_selectors, "用户名"
            )
            
            if not username_element:
                return False, "无法找到用户名输入框"
            
            if not self._validate_input_element(username_element, "username"):
                await self.send_notification("登录流程", "用户名输入框验证失败，尝试继续...")
            
            await self.send_notification("登录流程", f"开始输入用户名: {username}")
            username_element.clear()
            username_element.send_keys(username)
            
            # 验证输入是否成功
            input_value = username_element.get_attribute('value')
            if input_value != username:
                return False, f"用户名输入验证失败，期望: {username}, 实际: {input_value}"
            
            await self.send_notification("登录流程", "用户名输入完成")
            await asyncio.sleep(0.5)
            
            # 4. 查找并填写密码
            await self.send_notification("登录流程", "正在定位密码输入框...")
            password_element = self._find_element_by_multiple_selectors(
                self.password_selectors, "密码"
            )
            
            if not password_element:
                return False, "无法找到密码输入框"
            
            if not self._validate_input_element(password_element, "password"):
                await self.send_notification("登录流程", "密码输入框验证失败，尝试继续...")
            
            await self.send_notification("登录流程", "开始输入密码")
            password_element.clear()
            password_element.send_keys(password)
            
            await self.send_notification("登录流程", "密码输入完成")
            await asyncio.sleep(0.5)
            
            # 5. 查找并点击登录按钮
            await self.send_notification("登录流程", "正在定位登录按钮...")
            login_button = self._find_element_by_multiple_selectors(
                self.login_button_selectors, "登录按钮"
            )
            
            if not login_button:
                return False, "无法找到登录按钮"
            
            await self.send_notification("登录流程", "点击登录按钮...")
            current_url = self.driver.current_url
            login_button.click()
            
            # 6. 等待登录结果
            await self.send_notification("登录流程", "等待登录结果...")
            await asyncio.sleep(3)
            
            # 检查URL是否发生变化（登录成功的常见标志）
            try:
                WebDriverWait(self.driver, 7).until(
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
            
            for by, selector in error_selectors:
                try:
                    error_element = self.driver.find_element(by, selector)
                    if error_element.is_displayed():
                        error_text = error_element.text
                        return False, f"登录失败: {error_text}"
                except NoSuchElementException:
                    continue
            
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
    
    def close(self):
        """关闭浏览器"""
        if self.driver:
            try:
                self.driver.quit()
                self.logger.info("浏览器已关闭")
            except Exception as e:
                self.logger.error(f"关闭浏览器时发生错误: {e}")
            finally:
                self.driver = None
                self.wait = None
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()


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