"""
定时任务服务 — 与 attendance_system 协作创建定时打卡任务。

抽取自 modules/telegram_bot.py settime 多步状态机的"最终落地"部分。bot 内的多步
交互（callback_query/handle_message）保留不变；GUI/API 直接调单步 ``create_scheduled_punch_task``。
"""
import logging
from datetime import datetime
from typing import Optional, Tuple


async def create_scheduled_punch_task(
    attendance_system,
    punch_type: str,
    mode: str,
    hour: Optional[int] = None,
    minute: Optional[int] = None,
    delay_minutes: Optional[int] = None,
    username: Optional[str] = None,
) -> Tuple[bool, str, Optional[int]]:
    """创建定时打卡任务。

    Args:
        attendance_system: ``AttendanceSystem`` 实例
        punch_type: 'punch_in' / 'punch_out'
        mode: 'absolute' (用 hour/minute) / 'delay' (用 delay_minutes 计算)
        hour, minute: mode='absolute' 时必填
        delay_minutes: mode='delay' 时必填
        username: 可选，绑定到任务记录

    Returns:
        ``(success, message, task_id|None)``
    """
    if punch_type not in ('punch_in', 'punch_out'):
        return False, f'不支持的 punch_type: {punch_type}', None

    if mode not in ('absolute', 'delay'):
        return False, f'不支持的 mode: {mode}', None

    # 计算目标时间
    if mode == 'absolute':
        if hour is None or minute is None:
            return False, 'absolute 模式需 hour/minute', None
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            return False, '时间范围非法', None
        target_h, target_m = hour, minute
    else:  # delay
        if delay_minutes is None or delay_minutes < 0:
            return False, 'delay 模式需 delay_minutes>=0', None
        now = datetime.now()
        target = now.replace(second=0, microsecond=0)
        # 加 delay 分钟
        from datetime import timedelta
        target = target + timedelta(minutes=delay_minutes)
        target_h, target_m = target.hour, target.minute

    time_str = f'{target_h:02d}:{target_m:02d}'

    try:
        if punch_type == 'punch_out':
            ok = await attendance_system.schedule_punch_out(target_h, target_m)
            if not ok:
                return False, '调度下班打卡任务失败', None
            # schedule_punch_out 内部已 add_task；取最近的 task_id
            tasks = attendance_system.task_manager.get_tasks()
            last_id = max((t.get('id', 0) for t in tasks if t.get('type') == 'punch_out'), default=None)
            return True, f'已设置下班打卡任务 @ {time_str}', last_id
        else:
            # punch_in: 用 task_manager.add_task + 简单 schedule（沿用 bot 内同等逻辑）
            task_id = attendance_system.task_manager.add_task('punch_in', time_str, username=username)
            # 由 schedule_manager 在下次循环时拾起；这里只入库
            return True, f'已设置上班打卡任务 @ {time_str}', task_id
    except Exception as e:
        logging.exception('create_scheduled_punch_task failed')
        return False, f'内部错误: {e}', None
