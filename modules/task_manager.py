"""
任务管理模块

负责定时任务的创建、存储、调度和管理
"""

import json
import os
import threading
from datetime import datetime


class TaskManager:
    """任务管理类"""

    def __init__(self):
        self.tasks_file = 'scheduled_tasks.json'
        # waitress HTTP 线程(del_task)与 asyncio 主循环线程(打卡/telegram)并发改写
        # self.tasks 和 scheduled_tasks.json，需互斥串行化整段 load→modify→save
        self._lock = threading.Lock()
        self.tasks = self.load_tasks()
        self._update_task_ids()  # 确保所有任务都有ID

    def _update_task_ids(self):
        """更新所有任务的ID"""
        with self._lock:
            for i, task in enumerate(self.tasks):
                if 'id' not in task:
                    task['id'] = i + 1
            self._save_tasks_unlocked()

    def load_tasks(self):
        """从文件加载定时任务"""
        if os.path.exists(self.tasks_file):
            try:
                with open(self.tasks_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载定时任务失败: {str(e)}")
                return []
        return []

    def save_tasks(self):
        """保存定时任务到文件（对外接口，自带锁）"""
        with self._lock:
            self._save_tasks_unlocked()

    def _save_tasks_unlocked(self):
        """保存定时任务到文件（临时文件 + os.replace 原子写）

        注意：本方法不自带锁，调用方必须已持有 self._lock（防止重入死锁）。
        非原子的 open('w') 截断写在并发或中途崩溃时会损坏 JSON，故改为
        先写临时文件再 os.replace 原子替换。
        """
        try:
            tmp_file = self.tasks_file + '.tmp'
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(self.tasks, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self.tasks_file)
        except Exception as e:
            print(f"保存定时任务失败: {str(e)}")

    def add_task(self, task_type, scheduled_time, username=None):
        """添加定时任务

        Args:
            task_type: 任务类型 (punch_in, punch_out, selenium_punch_out等)
            scheduled_time: 计划执行时间
            username: 关联的用户名（可选，用于多用户场景）
        """
        # 整段 load→modify→save 加锁串行化，避免 append 与 HTTP 线程重绑列表竞态丢任务
        with self._lock:
            # 获取新任务的ID
            new_id = max([task.get('id', 0) for task in self.tasks], default=0) + 1

            task = {
                'id': new_id,
                'type': task_type,
                'scheduled_time': scheduled_time,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            # 如果指定了用户名，添加到任务中
            if username:
                task['username'] = username

            self.tasks.append(task)
            self._save_tasks_unlocked()
            return new_id

    def remove_task_by_id(self, task_id):
        """根据ID移除定时任务"""
        with self._lock:
            original_length = len(self.tasks)
            self.tasks = [t for t in self.tasks if t.get('id') != task_id]
            task_removed = len(self.tasks) < original_length
            self._save_tasks_unlocked()
            return task_removed

    def get_task_by_id(self, task_id):
        """根据ID获取任务"""
        with self._lock:
            for task in self.tasks:
                if task.get('id') == task_id:
                    return task
            return None

    def remove_task(self, task_type=None, scheduled_time=None):
        """移除定时任务"""
        with self._lock:
            if task_type:
                self.tasks = [t for t in self.tasks if t['type'] != task_type]
            if scheduled_time:
                self.tasks = [t for t in self.tasks if t['scheduled_time'] != scheduled_time]
            self._save_tasks_unlocked()

    def get_tasks(self):
        """获取所有定时任务"""
        return self.tasks

    def clear_tasks(self):
        """清除所有定时任务"""
        with self._lock:
            self.tasks = []
            self._save_tasks_unlocked()


# 全局任务管理器实例
task_manager = TaskManager()