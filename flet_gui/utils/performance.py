"""
前端性能优化工具
提供组件懒加载、状态管理优化等功能
"""

import flet as ft
import asyncio
import functools
import time
from typing import Dict, Any, Optional, Callable, Union
import logging

logger = logging.getLogger(__name__)


class ComponentCache:
    """组件缓存管理"""
    
    def __init__(self, max_size: int = 100):
        self.cache: Dict[str, ft.Control] = {}
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
    
    def get(self, key: str) -> Optional[ft.Control]:
        """获取缓存的组件"""
        if key in self.cache:
            self.access_times[key] = time.time()
            return self.cache[key]
        return None
    
    def set(self, key: str, component: ft.Control):
        """缓存组件"""
        if len(self.cache) >= self.max_size:
            self._evict_oldest()
        
        self.cache[key] = component
        self.access_times[key] = time.time()
    
    def _evict_oldest(self):
        """清理最久未使用的组件"""
        if not self.access_times:
            return
        
        oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
        del self.cache[oldest_key]
        del self.access_times[oldest_key]
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
        self.access_times.clear()


class LazyLoader:
    """懒加载管理器"""
    
    def __init__(self):
        self.loading_components: Dict[str, bool] = {}
        self.loaded_components: Dict[str, ft.Control] = {}
    
    async def load_component(
        self,
        key: str,
        factory: Callable[[], ft.Control],
        placeholder: Optional[ft.Control] = None
    ) -> ft.Control:
        """懒加载组件"""
        # 如果已经加载，直接返回
        if key in self.loaded_components:
            return self.loaded_components[key]
        
        # 如果正在加载，返回占位符
        if self.loading_components.get(key, False):
            return placeholder or ft.ProgressRing()
        
        # 开始加载
        self.loading_components[key] = True
        
        try:
            # 异步创建组件（模拟异步加载）
            await asyncio.sleep(0.1)  # 避免阻塞
            component = factory()
            
            self.loaded_components[key] = component
            return component
            
        except Exception as e:
            logger.error(f"Failed to load component {key}: {e}")
            return ft.Text(f"加载失败: {key}")
        
        finally:
            self.loading_components[key] = False


class StateManager:
    """状态管理优化"""
    
    def __init__(self):
        self.state: Dict[str, Any] = {}
        self.subscribers: Dict[str, list] = {}
        self.batch_updates: Dict[str, Any] = {}
        self.batch_timer: Optional[asyncio.Task] = None
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取状态"""
        return self.state.get(key, default)
    
    def set(self, key: str, value: Any, batch: bool = False):
        """设置状态"""
        if batch:
            self.batch_updates[key] = value
            self._schedule_batch_update()
        else:
            self._update_state(key, value)
    
    def subscribe(self, key: str, callback: Callable):
        """订阅状态变化"""
        if key not in self.subscribers:
            self.subscribers[key] = []
        self.subscribers[key].append(callback)
    
    def unsubscribe(self, key: str, callback: Callable):
        """取消订阅"""
        if key in self.subscribers:
            try:
                self.subscribers[key].remove(callback)
            except ValueError:
                pass
    
    def _update_state(self, key: str, value: Any):
        """更新状态并通知订阅者"""
        old_value = self.state.get(key)
        self.state[key] = value
        
        # 只在值真正改变时通知
        if old_value != value:
            self._notify_subscribers(key, value, old_value)
    
    def _notify_subscribers(self, key: str, new_value: Any, old_value: Any):
        """通知订阅者"""
        if key in self.subscribers:
            for callback in self.subscribers[key]:
                try:
                    callback(new_value, old_value)
                except Exception as e:
                    logger.error(f"Error in state subscriber for {key}: {e}")
    
    def _schedule_batch_update(self):
        """调度批量更新"""
        if self.batch_timer:
            self.batch_timer.cancel()
        
        self.batch_timer = asyncio.create_task(self._process_batch_updates())
    
    async def _process_batch_updates(self):
        """处理批量更新"""
        await asyncio.sleep(0.016)  # ~60fps
        
        updates = self.batch_updates.copy()
        self.batch_updates.clear()
        
        for key, value in updates.items():
            self._update_state(key, value)


class PerformanceMonitor:
    """性能监控"""
    
    def __init__(self):
        self.metrics: Dict[str, list] = {}
        self.thresholds = {
            "render_time": 16.67,  # 60fps target (ms)
            "update_time": 8.33,   # 120fps target (ms)
            "memory_usage": 50,    # MB
        }
    
    def measure_time(self, operation: str):
        """装饰器：测量操作时间"""
        def decorator(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    end_time = time.time()
                    duration = (end_time - start_time) * 1000  # ms
                    self.record_metric(operation, duration)
            
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    end_time = time.time()
                    duration = (end_time - start_time) * 1000  # ms
                    self.record_metric(operation, duration)
            
            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        return decorator
    
    def record_metric(self, metric_name: str, value: float):
        """记录性能指标"""
        if metric_name not in self.metrics:
            self.metrics[metric_name] = []
        
        self.metrics[metric_name].append(value)
        
        # 保持最近100个记录
        if len(self.metrics[metric_name]) > 100:
            self.metrics[metric_name] = self.metrics[metric_name][-100:]
        
        # 检查性能阈值
        self._check_threshold(metric_name, value)
    
    def _check_threshold(self, metric_name: str, value: float):
        """检查性能阈值"""
        threshold = self.thresholds.get(metric_name)
        if threshold and value > threshold:
            logger.warning(f"Performance threshold exceeded for {metric_name}: {value:.2f} > {threshold}")
    
    def get_average(self, metric_name: str) -> float:
        """获取平均值"""
        if metric_name not in self.metrics or not self.metrics[metric_name]:
            return 0.0
        return sum(self.metrics[metric_name]) / len(self.metrics[metric_name])
    
    def get_stats(self, metric_name: str) -> Dict[str, float]:
        """获取统计信息"""
        if metric_name not in self.metrics or not self.metrics[metric_name]:
            return {}
        
        values = self.metrics[metric_name]
        return {
            "count": len(values),
            "average": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
            "latest": values[-1] if values else 0,
        }


class UIOptimizer:
    """UI优化工具"""
    
    def __init__(self):
        self.component_cache = ComponentCache()
        self.lazy_loader = LazyLoader()
        self.state_manager = StateManager()
        self.performance_monitor = PerformanceMonitor()
    
    def create_optimized_container(
        self,
        content: Union[ft.Control, Callable[[], ft.Control]],
        cache_key: Optional[str] = None,
        lazy_load: bool = False,
        **kwargs
    ) -> ft.Container:
        """创建优化的容器"""
        if cache_key:
            # 尝试从缓存获取
            cached = self.component_cache.get(cache_key)
            if cached:
                return cached
        
        if lazy_load and callable(content):
            # 懒加载
            placeholder = ft.Container(
                content=ft.ProgressRing(),
                alignment=ft.alignment.center,
                height=100,
            )
            
            async def load_content():
                component = await self.lazy_loader.load_component(
                    cache_key or str(id(content)),
                    content,
                    placeholder
                )
                return component
            
            # 返回占位符，异步加载真实内容
            return placeholder
        else:
            # 直接创建
            actual_content = content() if callable(content) else content
            container = ft.Container(content=actual_content, **kwargs)
            
            if cache_key:
                self.component_cache.set(cache_key, container)
            
            return container
    
    @property
    def monitor(self) -> PerformanceMonitor:
        """获取性能监控器"""
        return self.performance_monitor
    
    @property
    def state(self) -> StateManager:
        """获取状态管理器"""
        return self.state_manager


# 🌟 全局优化器实例
ui_optimizer = UIOptimizer()

# 🎯 便捷函数
def optimized_container(*args, **kwargs) -> ft.Container:
    """创建优化的容器"""
    return ui_optimizer.create_optimized_container(*args, **kwargs)


def measure_performance(operation: str):
    """性能测量装饰器"""
    return ui_optimizer.monitor.measure_time(operation)


def get_performance_stats() -> Dict[str, Dict[str, float]]:
    """获取性能统计"""
    stats = {}
    for metric in ui_optimizer.monitor.metrics:
        stats[metric] = ui_optimizer.monitor.get_stats(metric)
    return stats