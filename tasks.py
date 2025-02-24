import json
import os
from datetime import datetime

class TaskManager:
    def __init__(self):
        self.tasks_file = 'scheduled_tasks.json'
        self.tasks = self.load_tasks()
        self._update_task_ids()  # 确保所有任务都有ID

    def _update_task_ids(self):
        """更新所有任务的ID"""
        for i, task in enumerate(self.tasks):
            if 'id' not in task:
                task['id'] = i + 1
        self.save_tasks()

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
        """保存定时任务到文件"""
        try:
            with open(self.tasks_file, 'w', encoding='utf-8') as f:
                json.dump(self.tasks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存定时任务失败: {str(e)}")

    def add_task(self, task_type, scheduled_time):
        """添加定时任务"""
        # 获取新任务的ID
        new_id = max([task.get('id', 0) for task in self.tasks], default=0) + 1
        
        task = {
            'id': new_id,
            'type': task_type,
            'scheduled_time': scheduled_time,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.tasks.append(task)
        self.save_tasks()
        return new_id

    def remove_task_by_id(self, task_id):
        """根据ID移除定时任务"""
        original_length = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.get('id') != task_id]
        task_removed = len(self.tasks) < original_length
        self.save_tasks()
        return task_removed

    def get_task_by_id(self, task_id):
        """根据ID获取任务"""
        for task in self.tasks:
            if task.get('id') == task_id:
                return task
        return None

    def remove_task(self, task_type=None, scheduled_time=None):
        """移除定时任务"""
        if task_type:
            self.tasks = [t for t in self.tasks if t['type'] != task_type]
        if scheduled_time:
            self.tasks = [t for t in self.tasks if t['scheduled_time'] != scheduled_time]
        self.save_tasks()

    def get_tasks(self):
        """获取所有定时任务"""
        return self.tasks

    def clear_tasks(self):
        """清除所有定时任务"""
        self.tasks = []
        self.save_tasks() 