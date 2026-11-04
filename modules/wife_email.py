"""
给老婆的趣味邮件文案

打卡成功、打卡失败、定时打卡任务设置好这三种情况，各生成一封口吻轻松的 HTML 邮件（标题 + 正文）。
只负责拼文案，不负责发送；想改措辞直接改下面的文案列表即可，每次从列表里随机挑一句，避免天天一样。
"""

import html
import random
from datetime import datetime, timedelta
from typing import Optional, Tuple

from modules.safe_calendar import is_workday


# 对她的称呼，每封邮件随机挑一个，整封邮件统一用这一个；文案里的 {name} 会被替换成它
NICKNAMES = ['老婆', '娇嘟', '乖乖']

SUCCESS_TITLES = {
    '上班': [
        '报告{name}，我已到岗！',
        '报告{name}：今日份搬砖已开工',
        '{name}，嘎哥到公司啦',
        '上班打卡成功，今天也会好好赚钱的',
    ],
    '下班': [
        '报告{name}，我已下班！',
        '报告{name}：今日搬砖任务圆满完成',
        '{name}，老公下班啦',
        '下班打卡成功，正在奔向{name}',
    ],
}

SUCCESS_LINES = {
    '上班': [
        '今天也会认真搬砖，下班第一时间向你汇报。',
        '已在工位坐好，想你的进度条开始加载。',
        '开工！今天的目标：准时下班回家。',
        '{name}今天也要开开心心的呀。',
    ],
    '下班': [
        '正在收拾东西准备回家，晚饭吃什么你来定～',
        '今天也有好好工作，回家求夸夸。',
        '电量剩余 5%，急需{name}充电。',
        '已离开工位，预计很快抵达{name}身边。',
    ],
}

# 明天不上班（周末/节假日）时额外补的一句
TOMORROW_OFF_LINES = {
    '上班': '熬过今天就放假啦，明天可以一起睡懒觉。',
    '下班': '明天不用上班，今晚可以安心晚睡啦。',
}

ICONS = {'上班': '💼', '下班': '🏠', '失败': '🙈', '任务': '⏰'}

# 落款里的自称，每次随机挑一个
SELF_NAMES = ['老公', '嘎哥']


def _signature() -> str:
    return f'—— {random.choice(SELF_NAMES)}的自动打卡小助手代发'


def _short_time(dt: datetime) -> str:
    """邮件标题里的时间，例如 11月4日 16:41。标题带上时间，邮箱就不会把每天的邮件折叠成同一串对话。"""
    return f"{dt.month}月{dt.day}日 {dt.strftime('%H:%M')}"


def _tomorrow_is_off(now: datetime) -> bool:
    return not is_workday((now + timedelta(days=1)).date())


def _render(icon: str, title: str, lines: list, rows: list, footer: str) -> str:
    """拼一张居中的卡片。邮件客户端大多不认 <style> 标签，所以样式全部写在行内。"""
    lines_html = ''.join(
        f'<p style="margin:0 0 8px;text-align:center;color:#555;font-size:15px;line-height:1.6;">{html.escape(t)}</p>'
        for t in lines if t
    )
    rows_html = ''.join(
        '<tr>'
        f'<td style="padding:6px 0;color:#999;font-size:14px;width:84px;vertical-align:top;">{html.escape(k)}</td>'
        f'<td style="padding:6px 0;color:#333;font-size:14px;">{html.escape(v)}</td>'
        '</tr>'
        for k, v in rows if v
    )
    return f"""
<html>
<body style="margin:0;padding:0;">
<div style="background:#fff5f7;padding:24px 12px;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
  <div style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:16px;padding:28px 24px;">
    <div style="font-size:44px;line-height:1;text-align:center;">{icon}</div>
    <h2 style="margin:16px 0 12px;text-align:center;color:#d6336c;font-size:22px;">{html.escape(title)}</h2>
    {lines_html}
    <table style="margin:18px auto 0;border-collapse:collapse;">{rows_html}</table>
    <p style="margin:22px 0 0;text-align:center;color:#bbb;font-size:12px;">{html.escape(footer)}</p>
  </div>
</div>
</body>
</html>
"""


def build_punch_success(kind: str, punch_time: datetime,
                        worked_minutes: Optional[int] = None) -> Tuple[str, str]:
    """打卡成功。kind 为 '上班' 或 '下班'；worked_minutes 只在下班时传，拿不到就不显示工时这一行。"""
    name = random.choice(NICKNAMES)
    title = random.choice(SUCCESS_TITLES[kind]).format(name=name)
    lines = [random.choice(SUCCESS_LINES[kind]).format(name=name)]
    if _tomorrow_is_off(punch_time):
        lines.append(TOMORROW_OFF_LINES[kind])

    rows = [(f'{kind}打卡', punch_time.strftime('%H:%M:%S'))]
    if kind == '下班' and worked_minutes:
        hours, minutes = divmod(int(worked_minutes), 60)
        worked = f'{hours} 小时 {minutes} 分钟'
        if worked_minutes >= 9 * 60:
            worked += '（加了会儿班，求心疼）'
        rows.append(('今日工时', worked))

    html_body = _render(ICONS[kind], title, lines, rows,
                        f'打卡截图在附件里，请{name}查收 {_signature()}')
    return f'{title} · {_short_time(punch_time)}', html_body


def build_punch_failure(kind: str, punch_time: datetime) -> Tuple[str, str]:
    """打卡失败。语气轻松，但要把"没打上、我已经知道了"说清楚。"""
    name = random.choice(NICKNAMES)
    title = f'报告{name}：{kind}卡出了点小状况'
    lines = [
        f'刚才的{kind}自动打卡没成功，系统已经同时提醒我本人了。',
        '我会马上处理，不用担心～',
    ]
    rows = [('发生时间', punch_time.strftime('%H:%M:%S'))]
    html_body = _render(ICONS['失败'], title, lines, rows,
                        f'当时的页面截图在附件里 {_signature()}')
    return f'{title} · {_short_time(punch_time)}', html_body


def build_task_scheduled(kind: str, scheduled_time: str, task_type: str) -> Tuple[str, str]:
    """定时打卡任务设置好了。scheduled_time 形如 '2026-11-04 16:50'。"""
    hhmm = scheduled_time[-5:] if len(scheduled_time) >= 5 else scheduled_time
    name = random.choice(NICKNAMES)
    title = f'报告{name}：我的{kind}卡已安排在 {hhmm}'
    line = '闹钟已经定好，到点自动打卡，打完再来跟你汇报～'

    rows = [
        ('计划时间', scheduled_time),
        ('任务类型', task_type),
        ('设置时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
    ]
    html_body = _render(ICONS['任务'], title, [line], rows, _signature())
    try:
        scheduled_dt = datetime.strptime(scheduled_time, '%Y-%m-%d %H:%M')
        subject = f'{title} · {scheduled_dt.month}月{scheduled_dt.day}日'
    except ValueError:
        subject = title
    return subject, html_body
