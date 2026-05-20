"""
截图档案服务 — 抽自 modules/telegram_bot.py:960 `_get_recent_images`。

零 Telegram 依赖：纯文件系统操作。
"""
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional


def list_screenshots(username: str, punch_type: str, limit: int = 5,
                     base_dir: str = 'screenshots') -> List[Dict]:
    """列出某用户某类型的最近 N 张截图。

    Args:
        username: 用户名，对应 ``screenshots/{username}/{punch_type}/``
        punch_type: 'punch_in' / 'punch_out'
        limit: 最多返回数量
        base_dir: 截图根目录（默认 ``screenshots``）

    Returns:
        每张图片字典：``{path, filename, time, time_str, type}``，按 time 倒序。
    """
    if punch_type not in ('punch_in', 'punch_out'):
        raise ValueError(f"unsupported punch_type: {punch_type}")

    directory = os.path.join(base_dir, username, punch_type)
    images: List[Dict] = []

    if not os.path.exists(directory):
        return images

    try:
        for filename in os.listdir(directory):
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue
            filepath = os.path.join(directory, filename)
            try:
                mtime = os.path.getmtime(filepath)
                images.append({
                    'path': filepath,
                    'filename': filename,
                    'time': mtime,
                    'time_str': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'type': '上班打卡' if punch_type == 'punch_in' else '下班打卡',
                })
            except Exception as e:
                logging.warning(f"获取文件 {filepath} 信息失败: {e}")
                continue
    except Exception as e:
        logging.error(f"列出 {directory} 失败: {e}")
        return images

    images.sort(key=lambda x: x['time'], reverse=True)
    return images[:limit]


def list_users_with_screenshots(base_dir: str = 'screenshots') -> List[str]:
    """枚举 screenshots/ 下所有用户目录。"""
    if not os.path.exists(base_dir):
        return []
    try:
        return sorted([
            name for name in os.listdir(base_dir)
            if os.path.isdir(os.path.join(base_dir, name))
        ])
    except Exception as e:
        logging.error(f"枚举截图用户失败: {e}")
        return []


def safe_screenshot_path(path: str, base_dir: str = 'screenshots') -> Optional[str]:
    """校验路径是否在 base_dir 内（防目录穿越）。返回绝对路径或 None。"""
    try:
        abs_base = os.path.abspath(base_dir)
        abs_path = os.path.abspath(path)
        if not abs_path.startswith(abs_base + os.sep) and abs_path != abs_base:
            return None
        if not os.path.isfile(abs_path):
            return None
        return abs_path
    except Exception:
        return None
