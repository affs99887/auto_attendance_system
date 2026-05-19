"""临时验证脚本 — 启动 mock backend 验证 web_server.py。验证完后删除。"""
import asyncio
import os
import sys

sys.path.insert(0, '.')
from modules.web_server import start as start_web


class MockTM:
    def __init__(self):
        self._t = [{'id': 1, 'type': 'punch_in', 'scheduled_time': '17:30', 'created_at': '2026-05-19 08:00:00'}]

    def get_tasks(self):
        return list(self._t)

    def remove_task_by_id(self, tid):
        before = len(self._t)
        self._t = [x for x in self._t if x['id'] != tid]
        return len(self._t) < before


class MockAS:
    def __init__(self):
        self._event_bus = None
        self.users = [{'username': 'demo_user'}]
        self.task_manager = MockTM()

    def get_status_snapshot(self):
        return {
            'current_time': '2026-05-19T08:30:00',
            'is_workday': True,
            'is_work_time': True,
            'current_operation': None,
            'today_records': {'demo_user': {'punch_in_time': '08:29:55', 'punch_out_time': None}},
            'config': {
                'work_start_time': '09:00',
                'work_end_time': '17:30',
                'use_selenium_login': True,
                'selenium_headless': True,
            },
            'scheduled_tasks': self.task_manager.get_tasks(),
            'users': ['demo_user'],
            'active_controllers': 0,
            'resources': {'cpu_percent': 12.3, 'memory_percent': 58.1},
        }

    async def start_punch_operation(self, op, user=None):
        return (True, f'mock-{op}-started-{user}')

    async def cancel_current_operation(self):
        return (True, 'mock-cancelled')

    def update_dynamic_config(self, patch):
        return {
            'USE_SELENIUM_LOGIN': patch.get('USE_SELENIUM_LOGIN', True),
            'SELENIUM_HEADLESS': patch.get('SELENIUM_HEADLESS', True),
        }


async def main():
    os.makedirs('logs', exist_ok=True)
    if not os.path.exists('logs/attendance_system.log'):
        with open('logs/attendance_system.log', 'w', encoding='utf-8') as f:
            f.write('2026-05-19 08:00:00 - INFO - mock-startup\n')

    aas = MockAS()
    handle = await start_web(aas, asyncio.get_running_loop(), 8765, 8766)
    # 用打印的形式输出 token，便于父进程读
    print('READY token=' + handle['token'], flush=True)

    # 持续推送，方便 WS 验证（每 2 秒一条）
    counter = 0
    while True:
        await asyncio.sleep(2)
        counter += 1
        handle['event_bus'].publish_threadsafe('punch:progress', {
            'title': 'mock', 'content': f'progress-{counter}', 'message': f'm{counter}',
        })
        # 同时追加一行日志，验证 log:stream
        with open('logs/attendance_system.log', 'a', encoding='utf-8') as f:
            f.write(f'2026-05-19 08:30:{counter:02d} - INFO - mock-heartbeat-{counter}\n')


if __name__ == '__main__':
    asyncio.run(main())
