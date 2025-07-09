"""
状态管理器
管理应用状态和数据流
"""

import asyncio
from typing import Dict, Any, List, Callable
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

@dataclass
class AppState:
    """应用全局状态"""
    current_page: str = "dashboard"
    system_running: bool = False
    punch_status: str = "未打卡"
    tasks: List[Dict] = field(default_factory=list)
    punch_records: List[Dict] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    theme_mode: str = "system"
    loading: bool = False
    loading_message: str = ""
    error_message: str = ""
    success_message: str = ""

class StateManager:
    """状态管理器"""
    
    def __init__(self):
        self.state = AppState()
        self.observers: Dict[str, List[Callable]] = {}
        self._lock = asyncio.Lock()
        
    def subscribe(self, event: str, callback: Callable):
        """订阅状态变化事件"""
        if event not in self.observers:
            self.observers[event] = []
        self.observers[event].append(callback)
        
    def unsubscribe(self, event: str, callback: Callable):
        """取消订阅状态变化事件"""
        if event in self.observers and callback in self.observers[event]:
            self.observers[event].remove(callback)
            
    async def emit(self, event: str, data: Any = None):
        """发出状态变化事件"""
        if event in self.observers:
            for callback in self.observers[event]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(data)
                    else:
                        callback(data)
                except Exception as e:
                    logger.error(f"Error in state observer: {e}")
                    
    async def update_state(self, **kwargs):
        """更新状态"""
        async with self._lock:
            old_state = dict(self.state.__dict__)
            
            for key, value in kwargs.items():
                if hasattr(self.state, key):
                    setattr(self.state, key, value)
                    
            # 发出状态变化事件
            for key, value in kwargs.items():
                if old_state.get(key) != value:
                    await self.emit(f"state_changed_{key}", value)
                    
            await self.emit("state_changed", self.state)
            
    def get_state(self) -> AppState:
        """获取当前状态"""
        return self.state
        
    async def set_loading(self, loading: bool, message: str = ""):
        """设置加载状态"""
        await self.update_state(loading=loading, loading_message=message)
        
    async def set_error(self, message: str):
        """设置错误消息"""
        await self.update_state(error_message=message)
        
    async def set_success(self, message: str):
        """设置成功消息"""
        await self.update_state(success_message=message)
        
    async def clear_messages(self):
        """清除所有消息"""
        await self.update_state(
            error_message="",
            success_message="",
            loading_message=""
        )
        
    async def navigate_to(self, page: str):
        """导航到页面"""
        await self.update_state(current_page=page)
        
    async def add_log(self, message: str):
        """添加日志"""
        current_logs = self.state.logs.copy()
        current_logs.append(message)
        # 只保留最新的100条日志
        if len(current_logs) > 100:
            current_logs = current_logs[-100:]
        await self.update_state(logs=current_logs)

# 全局状态管理器实例
app_state = StateManager()