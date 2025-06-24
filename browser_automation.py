import cv2
import numpy as np
import pyautogui
import win32gui
import win32con
import win32api
import time
import os
from PIL import Image
from typing import Tuple, Optional, List
import logging


class BrowserController:
    """浏览器自动化控制类"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # 设置pyautogui的安全设置
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.5
    
    def get_browser_window(self) -> Optional[int]:
        """获取浏览器窗口句柄
        
        Returns:
            Optional[int]: 窗口句柄，未找到返回None
        """
        def enum_windows_proc(hwnd, lParam):
            if win32gui.IsWindowVisible(hwnd):
                window_title = win32gui.GetWindowText(hwnd)
                if any(browser in window_title.lower() for browser in 
                      ['chrome', 'firefox', 'edge', 'opera', 'safari']):
                    lParam.append(hwnd)
            return True
        
        windows = []
        win32gui.EnumWindows(enum_windows_proc, windows)
        
        if windows:
            hwnd = windows[0]
            self.logger.info(f"找到浏览器窗口: {win32gui.GetWindowText(hwnd)}")
            return hwnd
        
        self.logger.warning("未找到浏览器窗口")
        return None
    
    def take_screenshot(self, save_path: Optional[str] = None) -> Optional[str]:
        """截取浏览器窗口截图
        
        Args:
            save_path: 保存路径（可选）
            
        Returns:
            Optional[str]: 截图文件路径，失败返回None
        """
        try:
            hwnd = self.get_browser_window()
            if not hwnd:
                return None
            
            # 激活并前置窗口
            try:
                win32gui.SetForegroundWindow(hwnd)
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.5)
            except Exception as e:
                self.logger.warning(f"窗口激活失败: {e}")
            
            # 获取窗口位置和大小
            rect = win32gui.GetWindowRect(hwnd)
            x, y, right, bottom = rect
            width = right - x
            height = bottom - y
            
            # 截取窗口
            screenshot = pyautogui.screenshot(region=(x, y, width, height))
            
            # 保存截图
            if save_path is None:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                save_path = f"screenshot_{timestamp}.png"
            
            # 确保目录存在
            os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else '.', exist_ok=True)
            screenshot.save(save_path)
            
            self.logger.info(f"截图已保存: {save_path}")
            return save_path
            
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            return None
    
    def click_position(self, x: int, y: int, method: str = "virtual") -> bool:
        """在指定位置点击
        
        Args:
            x: X坐标
            y: Y坐标
            method: 点击方法 ("virtual" 或 "pyautogui")
            
        Returns:
            bool: 点击成功返回True
        """
        try:
            if method == "virtual":
                return self.virtual_mouse_click(x, y)
            else:
                pyautogui.click(x, y)
                self.logger.info(f"PyAutoGUI点击位置: ({x}, {y})")
                return True
                
        except Exception as e:
            self.logger.error(f"点击失败 ({x}, {y}): {e}")
            return False
    
    def virtual_mouse_click(self, x: int, y: int) -> bool:
        """使用虚拟鼠标点击（更稳定）
        
        Args:
            x: X坐标
            y: Y坐标
            
        Returns:
            bool: 点击成功返回True
        """
        try:
            # 获取浏览器窗口
            hwnd = self.get_browser_window()
            if not hwnd:
                return False
            
            # 激活窗口
            try:
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.2)
            except:
                pass
            
            # 获取窗口相对坐标
            rect = win32gui.GetWindowRect(hwnd)
            relative_x = x - rect[0]
            relative_y = y - rect[1]
            
            # 发送鼠标消息
            lParam = win32api.MAKELONG(relative_x, relative_y)
            
            # 按下鼠标左键
            win32gui.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
            time.sleep(0.1)
            
            # 释放鼠标左键
            win32gui.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)
            
            self.logger.info(f"虚拟鼠标点击位置: ({x}, {y})")
            return True
            
        except Exception as e:
            self.logger.error(f"虚拟鼠标点击失败 ({x}, {y}): {e}")
            return False
    
    def input_text(self, text: str, clear_first: bool = True) -> bool:
        """输入文本
        
        Args:
            text: 要输入的文本
            clear_first: 是否先清空输入框
            
        Returns:
            bool: 输入成功返回True
        """
        try:
            if clear_first:
                # 全选并清空
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.1)
                pyautogui.press('delete')
                time.sleep(0.1)
            
            # 输入文本
            pyautogui.write(text, interval=0.05)
            self.logger.info(f"输入文本: {text[:20]}...")
            return True
            
        except Exception as e:
            self.logger.error(f"文本输入失败: {e}")
            return False
    
    def scroll_page(self, direction: str = "down", clicks: int = 3) -> bool:
        """滚动页面
        
        Args:
            direction: 滚动方向 ("up" 或 "down")
            clicks: 滚动次数
            
        Returns:
            bool: 滚动成功返回True
        """
        try:
            if direction == "down":
                pyautogui.scroll(-clicks)
            else:
                pyautogui.scroll(clicks)
            
            self.logger.info(f"页面滚动: {direction}, {clicks}次")
            return True
            
        except Exception as e:
            self.logger.error(f"页面滚动失败: {e}")
            return False
    
    def press_key(self, key: str) -> bool:
        """按键操作
        
        Args:
            key: 按键名称
            
        Returns:
            bool: 按键成功返回True
        """
        try:
            pyautogui.press(key)
            self.logger.info(f"按键: {key}")
            return True
            
        except Exception as e:
            self.logger.error(f"按键失败 ({key}): {e}")
            return False
    
    def hotkey(self, *keys) -> bool:
        """组合键操作
        
        Args:
            *keys: 按键组合
            
        Returns:
            bool: 组合键成功返回True
        """
        try:
            pyautogui.hotkey(*keys)
            self.logger.info(f"组合键: {'+'.join(keys)}")
            return True
            
        except Exception as e:
            self.logger.error(f"组合键失败 ({'+'.join(keys)}): {e}")
            return False
    
    def wait_for_page_load(self, timeout: int = 10) -> bool:
        """等待页面加载完成
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            bool: 页面加载完成返回True
        """
        try:
            # 简单的等待策略：等待固定时间
            time.sleep(2)
            
            # 可以在这里添加更复杂的页面加载检测逻辑
            # 比如检测特定元素是否出现
            
            self.logger.info("页面加载等待完成")
            return True
            
        except Exception as e:
            self.logger.error(f"页面加载等待失败: {e}")
            return False
    
    def close_browser_tabs(self, keep_count: int = 1) -> bool:
        """关闭多余的浏览器标签页
        
        Args:
            keep_count: 保留的标签页数量
            
        Returns:
            bool: 关闭成功返回True
        """
        try:
            # 尝试关闭多余的标签页
            for _ in range(10):  # 最多关闭10个标签页
                try:
                    pyautogui.hotkey('ctrl', 'w')
                    time.sleep(0.5)
                except:
                    break
            
            self.logger.info("浏览器标签页清理完成")
            return True
            
        except Exception as e:
            self.logger.error(f"浏览器标签页清理失败: {e}")
            return False
    
    def refresh_page(self) -> bool:
        """刷新页面
        
        Returns:
            bool: 刷新成功返回True
        """
        try:
            pyautogui.press('f5')
            time.sleep(2)
            self.logger.info("页面已刷新")
            return True
            
        except Exception as e:
            self.logger.error(f"页面刷新失败: {e}")
            return False
    
    def navigate_to_url(self, url: str) -> bool:
        """导航到指定URL
        
        Args:
            url: 目标URL
            
        Returns:
            bool: 导航成功返回True
        """
        try:
            # 点击地址栏
            pyautogui.hotkey('ctrl', 'l')
            time.sleep(0.5)
            
            # 输入URL
            pyautogui.write(url, interval=0.02)
            time.sleep(0.5)
            
            # 回车
            pyautogui.press('enter')
            
            # 等待页面加载
            self.wait_for_page_load()
            
            self.logger.info(f"导航到URL: {url}")
            return True
            
        except Exception as e:
            self.logger.error(f"URL导航失败 ({url}): {e}")
            return False


# 全局浏览器控制器实例
browser_controller = BrowserController()