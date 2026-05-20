"""
日志服务 — 抽自 modules/telegram_bot.py:546 `get_recent_errors`。

零 Telegram 依赖：编码尝试 + 错误分组 + 分页。Telegram bot 内的 InlineKeyboard 渲染
保留在 bot 文件中；这里只做解析。
"""
import os
import logging
from typing import List, Dict, Tuple, Optional


LOG_ENCODINGS = ('utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1')


def read_log_lines(log_file: str) -> List[str]:
    """尝试多种编码读取日志文件。读取失败返回空列表。"""
    if not os.path.exists(log_file):
        return []
    for enc in LOG_ENCODINGS:
        try:
            with open(log_file, 'r', encoding=enc) as f:
                return f.readlines()
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logging.error(f"读取日志文件 {log_file} 失败 ({enc}): {e}")
            return []
    logging.warning(f"日志文件 {log_file} 所有编码尝试均失败")
    return []


def parse_error_groups(lines: List[str], max_recent: int = 50) -> List[Dict]:
    """把日志行按 ERROR/CRITICAL 分组，每组含时间戳和多行内容。

    Args:
        lines: 原始日志行（含换行符）
        max_recent: 仅保留最后 N 条错误（按时间正序）

    Returns:
        ``[{timestamp, content: [str, ...]}, ...]`` 顺序从旧到新
    """
    error_logs = [l for l in lines if 'ERROR' in l or 'CRITICAL' in l]
    if not error_logs:
        return []

    recent = error_logs[-max_recent:]
    groups: List[Dict] = []
    cur_ts: Optional[str] = None
    cur_lines: List[str] = []

    for line in recent:
        is_new = ('ERROR' in line or 'CRITICAL' in line) and (
            ' - ERROR - ' in line or ' - CRITICAL - ' in line
        )
        if is_new:
            if cur_ts and cur_lines:
                groups.append({'timestamp': cur_ts, 'content': cur_lines})
            if ' - CRITICAL' in line:
                ts_part = line.split(' - CRITICAL')[0].strip()
                msg = line.split(' - CRITICAL - ')[-1].strip()
            else:
                ts_part = line.split(' - ERROR')[0].strip()
                msg = line.split(' - ERROR - ')[-1].strip()
            cur_ts = ts_part
            cur_lines = [msg]
        else:
            if cur_lines:
                cur_lines.append(line.rstrip('\r\n'))

    if cur_ts and cur_lines:
        groups.append({'timestamp': cur_ts, 'content': cur_lines})

    return groups


def paginate(items: List[Dict], page: int, per_page: int = 5) -> Tuple[List[Dict], int, int]:
    """分页。返回 (当前页数据, 当前页码, 总页数)。"""
    if not items:
        return [], 1, 1
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return items[start:start + per_page], page, total_pages


def get_recent_errors(log_file: str, page: int = 1, per_page: int = 5,
                      max_recent: int = 50) -> Dict:
    """一站式接口：读 + 分组 + 反转（最新在前）+ 分页。

    Returns:
        ``{groups, page, total_pages, total_groups}``
    """
    lines = read_log_lines(log_file)
    groups = parse_error_groups(lines, max_recent=max_recent)
    groups.reverse()  # 最近的在前
    page_data, cur_page, total_pages = paginate(groups, page, per_page)
    return {
        'groups': page_data,
        'page': cur_page,
        'total_pages': total_pages,
        'total_groups': len(groups),
    }
