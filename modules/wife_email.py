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


SUCCESS_TITLES = {
    '上班': [
        '报告老婆，我已到岗！',
        '报告老婆：今日份搬砖已开工',
        '老婆大人，你老公到公司啦',
        '上班打卡成功，今天也会好好赚钱的',
    ],
    '下班': [
        '报告老婆，我已下班！',
        '报告老婆：今日搬砖任务圆满完成',
        '老婆大人，你老公下班啦',
        '下班打卡成功，正在奔向老婆',
    ],
}

SUCCESS_LINES = {
    '上班': [
        '今天也会认真搬砖，下班第一时间向你汇报。',
        '已在工位坐好，想你的进度条开始加载。',
        '开工！今天的目标：准时下班回家。',
        '老婆今天也要开开心心的呀。',
    ],
    '下班': [
        '正在收拾东西准备回家，晚饭吃什么你来定～',
        '今天也有好好工作，回家求夸夸。',
        '电量剩余 5%，急需老婆充电。',
        '已离开工位，预计很快抵达老婆身边。',
    ],
}

# 明天不上班（周末/节假日）时额外补的一句
TOMORROW_OFF_LINES = {
    '上班': '熬过今天就放假啦，明天可以一起睡懒觉。',
    '下班': '明天不用上班，今晚可以安心晚睡啦。',
}

ICONS = {'上班': '💼', '下班': '🏠', '失败': '🙈', '任务': '⏰'}


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
    title = random.choice(SUCCESS_TITLES[kind])
    lines = [random.choice(SUCCESS_LINES[kind])]
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
                        '打卡截图在附件里，请老婆查收 —— 你老公的自动打卡小助手代发')
    return f'{title} · {_short_time(punch_time)}', html_body


def build_punch_failure(kind: str, punch_time: datetime) -> Tuple[str, str]:
    """打卡失败。语气轻松，但要把"没打上、我已经知道了"说清楚。"""
    title = f'报告老婆：{kind}卡出了点小状况'
    lines = [
        f'刚才的{kind}自动打卡没成功，系统已经同时提醒我本人了。',
        '我会马上处理，不用担心～',
    ]
    rows = [('发生时间', punch_time.strftime('%H:%M:%S'))]
    html_body = _render(ICONS['失败'], title, lines, rows,
                        '当时的页面截图在附件里 —— 你老公的自动打卡小助手代发')
    return f'{title} · {_short_time(punch_time)}', html_body


def build_task_scheduled(kind: str, scheduled_time: str, task_type: str,
                         who: str = 'me') -> Tuple[str, str]:
    """定时打卡任务设置好了。

    who: 'me' = 只给我打卡；'her' = 给老婆本人打卡；'both' = 两个人都打（恢复双账号后才会出现）。
    scheduled_time 形如 '2026-11-04 16:50'。
    """
    hhmm = scheduled_time[-5:] if len(scheduled_time) >= 5 else scheduled_time
    if who == 'her':
        title = f'老婆大人：你的{kind}卡已帮你安排在 {hhmm}'
        line = '到点会自动帮你打卡，你只管安心～'
    elif who == 'both':
        title = f'报告老婆：咱俩的{kind}卡已安排在 {hhmm}'
        line = '到点两个人一起自动打卡，打完再来汇报～'
    else:
        title = f'报告老婆：我的{kind}卡已安排在 {hhmm}'
        line = '闹钟已经定好，到点自动打卡，打完再来跟你汇报～'

    rows = [
        ('计划时间', scheduled_time),
        ('任务类型', task_type),
        ('设置时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
    ]
    html_body = _render(ICONS['任务'], title, [line], rows, '—— 你老公的自动打卡小助手代发')
    try:
        scheduled_dt = datetime.strptime(scheduled_time, '%Y-%m-%d %H:%M')
        subject = f'{title} · {scheduled_dt.month}月{scheduled_dt.day}日'
    except ValueError:
        subject = title
    return subject, html_body
