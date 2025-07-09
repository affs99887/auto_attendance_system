"""
系统业务逻辑适配器
连接现有AttendanceSystem与Flet UI
"""

import asyncio
from typing import Optional, Callable, Any, Dict, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class SystemStatus:
    """系统状态数据结构"""
    is_running: bool = False
    last_punch_time: Optional[str] = None
    punch_status: str = "未打卡"
    watchdog_status: str = "未启动"
    uptime: str = "0分钟"
    error_count: int = 0

class SystemAdapter:
    """系统业务逻辑适配器"""
    
    def __init__(self, attendance_system=None):
        self.attendance_system = attendance_system
        self.page = None
        self.listeners: List[Callable] = []
        self.status = SystemStatus()
        self._running = False
        
    def set_page(self, page):
        """设置Flet页面实例"""
        self.page = page
        
    def add_listener(self, callback: Callable):
        """添加状态变化监听器"""
        self.listeners.append(callback)
        
    def remove_listener(self, callback: Callable):
        """移除状态变化监听器"""
        if callback in self.listeners:
            self.listeners.remove(callback)
            
    async def notify_listeners(self, event_type: str, data: Any = None):
        """通知所有监听器"""
        for listener in self.listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(event_type, data)
                else:
                    listener(event_type, data)
            except Exception as e:
                logger.error(f"Error notifying listener: {e}")
                
    async def start_system(self) -> Dict[str, Any]:
        """启动系统"""
        try:
            await self.notify_listeners("system_starting")
            
            # 如果有AttendanceSystem实例，启动它
            if self.attendance_system:
                # 这里需要根据实际AttendanceSystem的接口调整
                # 假设有一个start方法
                if hasattr(self.attendance_system, 'start'):
                    await self.attendance_system.start()
                    
            self.status.is_running = True
            self._running = True
            
            await self.notify_listeners("system_started", self.status)
            
            return {"success": True, "message": "系统启动成功"}
            
        except Exception as e:
            logger.error(f"Failed to start system: {e}")
            await self.notify_listeners("system_error", str(e))
            return {"success": False, "message": f"系统启动失败: {str(e)}"}
            
    async def stop_system(self) -> Dict[str, Any]:
        """停止系统"""
        try:
            await self.notify_listeners("system_stopping")
            
            # 如果有AttendanceSystem实例，停止它
            if self.attendance_system:
                if hasattr(self.attendance_system, 'stop'):
                    await self.attendance_system.stop()
                    
            self.status.is_running = False
            self._running = False
            
            await self.notify_listeners("system_stopped", self.status)
            
            return {"success": True, "message": "系统停止成功"}
            
        except Exception as e:
            logger.error(f"Failed to stop system: {e}")
            await self.notify_listeners("system_error", str(e))
            return {"success": False, "message": f"系统停止失败: {str(e)}"}
            
    async def punch_in(self) -> Dict[str, Any]:
        """上班打卡"""
        try:
            await self.notify_listeners("punch_starting", "punch_in")
            
            # 调用原有业务逻辑
            if self.attendance_system:
                result = await self.attendance_system.punch_in()
                
                # 更新状态
                self.status.punch_status = "已打卡上班"
                self.status.last_punch_time = "刚刚"
                
                await self.notify_listeners("punch_completed", {
                    "type": "punch_in",
                    "result": result,
                    "status": self.status
                })
                
                return {"success": True, "message": "上班打卡成功", "data": result}
            else:
                # 模拟打卡操作
                await asyncio.sleep(1)  # 模拟网络延迟
                self.status.punch_status = "已打卡上班"
                self.status.last_punch_time = "刚刚"
                
                await self.notify_listeners("punch_completed", {
                    "type": "punch_in",
                    "result": "模拟打卡成功",
                    "status": self.status
                })
                
                return {"success": True, "message": "上班打卡成功（模拟）"}
                
        except Exception as e:
            logger.error(f"Punch in failed: {e}")
            await self.notify_listeners("punch_error", {"type": "punch_in", "error": str(e)})
            return {"success": False, "message": f"上班打卡失败: {str(e)}"}
            
    async def punch_out(self) -> Dict[str, Any]:
        """下班打卡"""
        try:
            await self.notify_listeners("punch_starting", "punch_out")
            
            # 调用原有业务逻辑
            if self.attendance_system:
                result = await self.attendance_system.punch_out()
                
                # 更新状态
                self.status.punch_status = "已打卡下班"
                self.status.last_punch_time = "刚刚"
                
                await self.notify_listeners("punch_completed", {
                    "type": "punch_out", 
                    "result": result,
                    "status": self.status
                })
                
                return {"success": True, "message": "下班打卡成功", "data": result}
            else:
                # 模拟打卡操作
                await asyncio.sleep(1)  # 模拟网络延迟
                self.status.punch_status = "已打卡下班"
                self.status.last_punch_time = "刚刚"
                
                await self.notify_listeners("punch_completed", {
                    "type": "punch_out",
                    "result": "模拟打卡成功",
                    "status": self.status
                })
                
                return {"success": True, "message": "下班打卡成功（模拟）"}
                
        except Exception as e:
            logger.error(f"Punch out failed: {e}")
            await self.notify_listeners("punch_error", {"type": "punch_out", "error": str(e)})
            return {"success": False, "message": f"下班打卡失败: {str(e)}"}
            
    def get_status(self) -> SystemStatus:
        """获取当前系统状态"""
        return self.status
        
    async def get_punch_records(self) -> List[Dict]:
        """获取打卡记录"""
        if self.attendance_system and hasattr(self.attendance_system, 'get_punch_records'):
            return await self.attendance_system.get_punch_records()
        else:
            # 返回模拟数据
            return [
                {"date": "2025-06-26", "punch_in": "09:00", "punch_out": "18:00"},
                {"date": "2025-06-25", "punch_in": "09:05", "punch_out": "17:58"},
                {"date": "2025-06-24", "punch_in": "08:58", "punch_out": "18:02"},
            ]
            
    async def get_tasks(self) -> List[Dict]:
        """获取任务列表"""
        if self.attendance_system and hasattr(self.attendance_system, 'get_tasks'):
            return await self.attendance_system.get_tasks()
        else:
            # 返回模拟数据
            return [
                {"id": 1, "title": "每日上班打卡", "type": "punch_in", "time": "09:00", "status": "active"},
                {"id": 2, "title": "每日下班打卡", "type": "punch_out", "time": "18:00", "status": "active"},
            ]
            
    async def update_ui_status(self, status_data: Dict):
        """更新UI状态"""
        if self.page:
            # 更新页面状态
            self.page.update()
            
    def is_running(self) -> bool:
        """检查系统是否运行中"""
        return self._running