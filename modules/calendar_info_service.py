"""
日历信息服务模块（墨水屏信息站用）

基于 chinese_calendar（项目既有依赖，用于工作日判定）计算：
- 当月每日的「休息日 / 法定假日 / 调休补班」标记（休息日含双休）
- 本周（周一起 7 天）的日期与休班标记（信息站「本周日历条」用，可跨月）
- 距最近休息日的倒计时（含双休；若今天就是休息日则给出剩余连休天数与节日名、
  假期结束后的下个工作日——驱动「休假中」全屏状态）
- 近期法定假期清单（最多 2 个：中文名、法定起止日、距今天数；相邻假期合并，
  如国庆+中秋连段输出「国庆中秋」）
- 后续调休补班日（最多 2 个，用于「补班 9/20 · 10/10」提示）
- 可选 after 参数：返回该日期之后的第一个工作日（「请假中」状态的销假日计算）

所有计算 try/except 包裹：chinese_calendar 不含目标年份数据时回退「仅按双休」，绝不外抛。

对外暴露：
- get_calendar_info() -> 契约 dict（以服务器当天为基准，返回当月数据）
"""

import datetime
import logging

logger = logging.getLogger(__name__)

# chinese_calendar 的英文节日名 -> 中文
_HOLIDAY_NAMES_CN = {
    "New Year's Day": '元旦',
    'Spring Festival': '春节',
    'Tomb-sweeping Day': '清明节',
    'Labour Day': '劳动节',
    'Dragon Boat Festival': '端午节',
    'Mid-autumn Festival': '中秋节',
    'National Day': '国庆节',
}

# 向后扫描的最大天数（覆盖跨年节假日与调休）
_SCAN_DAYS = 400


def _is_off(day):
    """是否休息日（法定假日或未被调休征用的双休）。数据缺失时回退按星期判断。"""
    try:
        import chinese_calendar as cc
        return not cc.is_workday(day)
    except Exception:
        return day.weekday() >= 5


def _holiday_name(day):
    """法定假日中文名；非法定假日（含普通双休）返回 None。"""
    try:
        import chinese_calendar as cc
        on_holiday, name = cc.get_holiday_detail(day)
        if on_holiday and name:
            return _HOLIDAY_NAMES_CN.get(name, name)
    except Exception:
        pass
    return None


def _is_makeup_workday(day):
    """是否调休补班日（周末却要上班）。"""
    return day.weekday() >= 5 and not _is_off(day)


def _off_span(start):
    """从 start（须为休息日）向前后延伸出连续休息区间，返回 (首日, 末日)。"""
    first = start
    while _is_off(first - datetime.timedelta(days=1)):
        first -= datetime.timedelta(days=1)
    last = start
    while _is_off(last + datetime.timedelta(days=1)):
        last += datetime.timedelta(days=1)
    return first, last


def _workday_after(day):
    """day 之后（不含 day）的第一个工作日。"""
    d = day + datetime.timedelta(days=1)
    for _ in range(60):
        if not _is_off(d):
            return d
        d += datetime.timedelta(days=1)
    return d


def _span_holiday_name(first, last):
    """连续休息区间内若含法定假日，返回其中文名；否则 None。"""
    d = first
    while d <= last:
        name = _holiday_name(d)
        if name:
            return name
        d += datetime.timedelta(days=1)
    return None


def get_calendar_info(after=None):
    """组装信息站日历契约。永不抛异常。

    after: 可选 ISO 日期字符串；给定时额外返回 workday_after（该日之后的首个工作日）。
    """
    today = datetime.date.today()
    try:
        return _build(today, after)
    except Exception:
        logger.exception('[日历] 组装日历信息失败，返回降级数据')
        return {
            'available': False,
            'today': today.isoformat(),
            'year': today.year,
            'month': today.month,
            'days': [],
            'week': [],
            'nearest_rest': None,
            'next_holidays': [],
            'next_makeup': [],
            'workday_after': None,
        }


def _build(today, after=None):
    year, month = today.year, today.month

    # ---- 当月每日标记 ----
    days = []
    d = datetime.date(year, month, 1)
    while d.month == month:
        days.append({
            'd': d.day,
            'off': _is_off(d),
            'statutory': _holiday_name(d) is not None,
            'makeup': _is_makeup_workday(d),
        })
        d += datetime.timedelta(days=1)

    # ---- 本周日历条（周一起 7 天，可跨月）----
    monday = today - datetime.timedelta(days=today.weekday())
    week = []
    for i in range(7):
        d = monday + datetime.timedelta(days=i)
        week.append({'date': d.isoformat(), 'd': d.day, 'off': _is_off(d)})

    # ---- 最近休息日（含双休；name/next_workday 驱动「休假中」全屏状态）----
    nearest_rest = None
    if _is_off(today):
        first, last = _off_span(today)
        name = _span_holiday_name(first, last)
        nearest_rest = {
            'days': 0,
            'date': today.isoformat(),
            'name': name,  # 节日名；普通双休为 None
            'label': f'{name}假期中' if name else '双休进行中',
            'span': [first.isoformat(), last.isoformat()],
            'kind': 'holiday' if name else 'weekend',
            'next_workday': _workday_after(last).isoformat(),
        }
    else:
        d = today + datetime.timedelta(days=1)
        for _ in range(_SCAN_DAYS):
            if _is_off(d):
                first, last = _off_span(d)
                name = _span_holiday_name(first, last)
                nearest_rest = {
                    'days': (d - today).days,
                    'date': d.isoformat(),
                    'name': name,
                    'label': f'{name}连休' if name else '本周双休',
                    'span': [first.isoformat(), last.isoformat()],
                    'kind': 'holiday' if name else 'weekend',
                    'next_workday': _workday_after(last).isoformat(),
                }
                break
            d += datetime.timedelta(days=1)

    # ---- 近期法定假期清单（今天起算，最多 2 个；按法定假日连续段聚合）----
    next_holidays = []
    d = today
    scanned = 0
    while scanned < _SCAN_DAYS and len(next_holidays) < 2:
        name = _holiday_name(d)
        if name:
            # 向后吃完整个法定假日连续段，收集段内出现过的假期名（保持出现顺序去重）
            names = []
            first = d
            last = d
            cur = d
            while True:
                n = _holiday_name(cur)
                if not n:
                    break
                if n not in names:
                    names.append(n)
                last = cur
                cur += datetime.timedelta(days=1)
                scanned += 1
            # 多个假期连段（如国庆+中秋）合并显示：去「节」拼接 → 国庆中秋
            label = names[0] if len(names) == 1 else ''.join(n.replace('节', '') for n in names)
            next_holidays.append({
                'name': label,
                'start': first.isoformat(),
                'end': last.isoformat(),
                'days_until': (first - today).days,
            })
            d = last + datetime.timedelta(days=1)
        else:
            d += datetime.timedelta(days=1)
            scanned += 1

    # ---- 后续调休补班日（最多 2 个）----
    next_makeup = []
    d = today
    for _ in range(_SCAN_DAYS):
        if _is_makeup_workday(d):
            next_makeup.append(d.isoformat())
            if len(next_makeup) >= 2:
                break
        d += datetime.timedelta(days=1)

    # ---- 可选：after 之后的首个工作日（请假销假日）----
    workday_after = None
    if after:
        try:
            workday_after = _workday_after(datetime.date.fromisoformat(after)).isoformat()
        except Exception:
            logger.warning('[日历] after 参数无效：%r', after)

    return {
        'available': True,
        'today': today.isoformat(),
        'year': year,
        'month': month,
        'days': days,
        'week': week,
        'nearest_rest': nearest_rest,
        'next_holidays': next_holidays,
        'next_makeup': next_makeup,
        'workday_after': workday_after,
    }
