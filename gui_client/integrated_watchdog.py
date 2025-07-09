#!/usr/bin/env python3
"""
集成看门狗类 - 内置到GUI中的看门狗系统
自动启动、监控系统状态和处理错误恢复
"""

import threading
import time
import json
import os
import logging
import psutil
from datetime import datetime
from typing import Dict, Any, Optional, Callable


class IntegratedWatchdog:
    """集成到GUI中的看门狗类"""
    
    def __init__(self, gui_app=None):
        """
        初始化集成看门狗
        
        Args:
            gui_app: GUI应用实例，用于回调状态更新
        """
        self.gui_app = gui_app
        self.config_file = "gui_integrated_watchdog_config.json"
        self.config = self._load_config()
        
        # 状态管理
        self.is_running = False
        self.status = "disabled"  # disabled, starting, running, stopping, error
        self.restart_count = 0
        self.last_error = None
        self.max_restarts = self.config.get("max_restarts", 10)
        self.health_status = {}
        
        # 监控线程
        self.monitor_thread = None
        self.stop_event = threading.Event()
        
        # 回调函数
        self.status_callback: Optional[Callable] = None
        
        # 日志设置
        self.logger = logging.getLogger(__name__)
        
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        default_config = {
            "monitor_interval": 30,
            "max_restarts": 10,
            "memory_threshold": 85,
            "cpu_threshold": 90,
            "auto_start": True,
            "restart_delay": 5
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 合并默认配置
                    default_config.update(config)
            return default_config
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            return default_config
    
    def _save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"保存配置文件失败: {e}")
    
    def set_status_callback(self, callback: Callable):
        """设置状态更新回调函数"""
        self.status_callback = callback
    
    def _update_status(self, status: str, error: str = None):
        """更新状态并触发回调"""
        self.status = status
        if error:
            self.last_error = error
        
        if self.status_callback:
            try:
                self.status_callback(status, error)
            except Exception as e:
                self.logger.error(f"状态回调失败: {e}")
    
    def start(self):
        """启动看门狗"""
        if self.is_running:
            return True
        
        self.logger.info("启动集成看门狗...")
        self._update_status("starting")
        
        try:
            self.stop_event.clear()
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
            
            self.is_running = True
            self._update_status("running")
            self.logger.info("集成看门狗启动成功")
            return True
            
        except Exception as e:
            error_msg = f"看门狗启动失败: {e}"
            self.logger.error(error_msg)
            self._update_status("error", error_msg)
            return False
    
    def stop(self):
        """停止看门狗"""
        if not self.is_running:
            return
        
        self.logger.info("停止集成看门狗...")
        self._update_status("stopping")
        
        try:
            self.stop_event.set()
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=5)
            
            self.is_running = False
            self._update_status("disabled")
            self.logger.info("集成看门狗已停止")
            
        except Exception as e:
            error_msg = f"看门狗停止失败: {e}"
            self.logger.error(error_msg)
            self._update_status("error", error_msg)
    
    def _monitor_loop(self):
        """监控循环"""
        while not self.stop_event.is_set():
            try:
                # 检查系统资源
                self._check_system_resources()
                
                # 检查GUI应用状态
                if self.gui_app:
                    self._check_gui_status()
                
                # 检查错误日志
                self._check_error_logs()
                
                # 等待下一次检查
                self.stop_event.wait(self.config["monitor_interval"])
                
            except Exception as e:
                error_msg = f"监控循环错误: {e}"
                self.logger.error(error_msg)
                self._update_status("error", error_msg)
                
                # 等待一段时间后重试
                self.stop_event.wait(self.config["restart_delay"])
    
    def _check_system_resources(self):
        """检查系统资源使用情况"""
        try:
            # 检查内存使用率
            memory_percent = psutil.virtual_memory().percent
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # 更新健康状态
            self.health_status = {
                "memory_percent": memory_percent,
                "cpu_percent": cpu_percent,
                "memory_ok": memory_percent <= self.config["memory_threshold"],
                "cpu_ok": cpu_percent <= self.config["cpu_threshold"],
                "last_check": datetime.now().isoformat()
            }
            
            if memory_percent > self.config["memory_threshold"]:
                self.logger.warning(f"内存使用率过高: {memory_percent}%")
            
            if cpu_percent > self.config["cpu_threshold"]:
                self.logger.warning(f"CPU使用率过高: {cpu_percent}%")
                
        except Exception as e:
            self.logger.error(f"资源检查失败: {e}")
            self.health_status = {"error": str(e), "last_check": datetime.now().isoformat()}
    
    def _check_gui_status(self):
        """检查GUI应用状态"""
        try:
            if hasattr(self.gui_app, 'attendance_system'):
                system = self.gui_app.attendance_system
                if system and hasattr(system, 'is_running'):
                    if not system.is_running and self.restart_count < self.config["max_restarts"]:
                        self.logger.info("检测到系统停止，尝试重启...")
                        self._restart_system()
                        
        except Exception as e:
            self.logger.error(f"GUI状态检查失败: {e}")
    
    def _check_error_logs(self):
        """检查错误日志"""
        try:
            # 这里可以添加日志文件监控逻辑
            # 检查最近的错误日志，决定是否需要重启
            pass
        except Exception as e:
            self.logger.error(f"日志检查失败: {e}")
    
    def _restart_system(self):
        """重启系统"""
        try:
            if self.restart_count >= self.config["max_restarts"]:
                self.logger.error("达到最大重启次数，停止自动重启")
                return
            
            self.restart_count += 1
            self.logger.info(f"执行第{self.restart_count}次系统重启...")
            
            # 如果GUI应用有重启方法，调用它
            if self.gui_app and hasattr(self.gui_app, 'restart_system'):
                self.gui_app.restart_system()
            
            # 等待重启完成
            time.sleep(self.config["restart_delay"])
            
        except Exception as e:
            error_msg = f"系统重启失败: {e}"
            self.logger.error(error_msg)
            self._update_status("error", error_msg)
    
    def get_status(self) -> Dict[str, Any]:
        """获取看门狗状态信息"""
        return {
            "status": self.status,
            "is_running": self.is_running,
            "restart_count": self.restart_count,
            "last_error": self.last_error,
            "config": self.config.copy()
        }
    
    def update_config(self, new_config: Dict[str, Any]):
        """更新配置"""
        self.config.update(new_config)
        self.max_restarts = self.config.get("max_restarts", 10)
        self._save_config()
        self.logger.info("看门狗配置已更新")
    
    def reset_restart_count(self):
        """重置重启计数"""
        self.restart_count = 0
        self.logger.info("重启计数已重置")