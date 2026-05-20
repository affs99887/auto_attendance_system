"""
chinese_calendar 的安全包装。

chinese_calendar 的法定节假日数据只覆盖有限年份（1.11.0 截至 2026）。一旦系统
日期跨过库数据上限，``is_workday`` / ``is_holiday`` 会抛 ``NotImplementedError``
（报错形如 "no available data for year XXXX"），进而中断打卡调度、状态查询等核心流程。

本模块对两个函数做兜底：库能算就用库的精确结果；库报错就降级为"周一~周五=工作日、
周六日=休息日"的简单判断，保证系统不因日历库过期而瘫痪。

用法：把 ``from chinese_calendar import is_workday, is_holiday``
改为   ``from modules.safe_calendar import is_workday, is_holiday``
"""
import logging
from datetime import date as _date, datetime as _datetime

from chinese_calendar import is_workday as _lib_is_workday
from chinese_calendar import is_holiday as _lib_is_holiday

_warned = False  # 只告警一次，避免刷屏


def _to_date(d):
    """把 date / datetime 统一成 date。"""
    if isinstance(d, _datetime):
        return d.date()
    if isinstance(d, _date):
        return d
    # 其它类型尽量不动，交给底层库自己报错
    return d


def _warn_once(func_name, err):
    global _warned
    if not _warned:
        logging.warning(
            f"chinese_calendar 数据超出范围，{func_name} 降级为周末判断: {err}"
        )
        _warned = True


def is_workday(d) -> bool:
    """判断是否工作日。库数据缺失时降级为"周一~周五"。"""
    try:
        return bool(_lib_is_workday(d))
    except Exception as e:  # NotImplementedError 及其它
        _warn_once('is_workday', e)
        dd = _to_date(d)
        try:
            return dd.weekday() < 5
        except Exception:
            return True  # 最终兜底：当作工作日，宁可多打卡也不漏


def is_holiday(d) -> bool:
    """判断是否节假日/休息日。库数据缺失时降级为"周六日"。"""
    try:
        return bool(_lib_is_holiday(d))
    except Exception as e:
        _warn_once('is_holiday', e)
        dd = _to_date(d)
        try:
            return dd.weekday() >= 5
        except Exception:
            return False
