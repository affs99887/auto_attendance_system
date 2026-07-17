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
契约里的 coverage_end 是数据覆盖的最后一天（降级信号）：超出这天的日期都是按双休
估算的，法定假日/调休不可见，前端可据此提示。

对外暴露：
- get_calendar_info() -> 契约 dict（以服务器当天为基准，返回当月数据）
- get_weather_rest_periods() -> 天气头盔提醒所需的近期连续休息区间
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

# 已提示过的覆盖边界（同一边界只 warning 一次，避免每次请求都刷日志）
_warned_coverage = set()


def _coverage_end():
    """chinese_calendar 数据覆盖的最后一天。

    该库按整年收录节假日数据，所以覆盖到「最大年份的 12-31」；
    取不到（未安装/包结构变化）时返回 None。
    """
    try:
        import chinese_calendar as cc
        return datetime.date(max(cc.holidays.keys()).year, 12, 31)
    except Exception:
        return None


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
    """连续休息区间内若含法定假日，返回其中文名；否则 None。

    同一连续休息区间若包含两个法定节日（如国庆、中秋相连），按出现顺序合并展示。
    """
    names = []
    d = first
    while d <= last:
        name = _holiday_name(d)
        if name and name not in names:
            names.append(name)
        d += datetime.timedelta(days=1)
    if not names:
        return None
    return names[0] if len(names) == 1 else ''.join(name.replace('节', '') for name in names)


def get_weather_rest_periods(reference_day=None, lookahead_days=15):
    """返回天气提醒覆盖范围内的连续休息区间。

    范围额外包含 reference_day 的前一天，确保休假结束后的首个工作日 08:00 前，
    前端仍能识别刚结束的休息段。每段同时给出提醒窗口：
    「休息首日前一天 17:00」至「休息结束后首个工作日 08:00」。
    """
    today = reference_day or datetime.date.today()
    if isinstance(today, datetime.datetime):
        today = today.date()
    try:
        days = max(1, int(lookahead_days))
    except (TypeError, ValueError):
        days = 15

    scan_start = today - datetime.timedelta(days=1)
    scan_end = today + datetime.timedelta(days=days - 1)
    periods = []
    seen = set()
    current = scan_start

    while current <= scan_end:
        if not _is_off(current):
            current += datetime.timedelta(days=1)
            continue

        first, last = _off_span(current)
        key = (first, last)
        if key not in seen:
            seen.add(key)
            name = _span_holiday_name(first, last)
            next_workday = _workday_after(last)
            window_start = datetime.datetime.combine(
                first - datetime.timedelta(days=1),
                datetime.time(hour=17),
                tzinfo=datetime.timezone(datetime.timedelta(hours=8)),
            )
            window_end = datetime.datetime.combine(
                next_workday,
                datetime.time(hour=8),
                tzinfo=datetime.timezone(datetime.timedelta(hours=8)),
            )
            rest_days = (last - first).days + 1
            periods.append({
                'start': first.isoformat(),
                'end': last.isoformat(),
                'name': name,
                'label': (
                    f'{name}假期'
                    if name else
                    '周末双休' if rest_days == 2 else '周末休息日'
                ),
                'kind': 'holiday' if name else 'weekend',
                'next_workday': next_workday.isoformat(),
                'window_start': window_start.isoformat(),
                'window_end': window_end.isoformat(),
            })

        current = last + datetime.timedelta(days=1)

    return periods


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
            'coverage_end': None,
        }


def _build(today, after=None):
    year, month = today.year, today.month

    # ---- 数据覆盖边界（降级信号）：扫描区间超出这天后 _is_off 只按双休估算 ----
    coverage_end = _coverage_end()
    if coverage_end is not None and today + datetime.timedelta(days=_SCAN_DAYS) > coverage_end:
        if coverage_end not in _warned_coverage:
            _warned_coverage.add(coverage_end)
            logger.warning(
                '[日历] chinese_calendar 数据只覆盖到 %s，之后的日期仅按双休估算'
                '（法定假日/调休不可见），请升级 chinese_calendar',
                coverage_end.isoformat(),
            )

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
            # 今天可能已在假期中段：先向前回溯到该法定段的真实首日，
            # 否则 start/连休天数会错报成「从今天起」
            first = d
            while _holiday_name(first - datetime.timedelta(days=1)):
                first -= datetime.timedelta(days=1)
            # 从首日向后吃完整个法定假日连续段，按出现顺序收集段内假期名（去重）
            names = []
            last = first
            cur = first
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
                # 进行中的假期（首日在今天之前）钳为 0，不给负数
                'days_until': max(0, (first - today).days),
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
        'coverage_end': coverage_end.isoformat() if coverage_end else None,
    }
