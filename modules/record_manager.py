"""
打卡记录管理模块

负责打卡记录的存储、读取和管理
"""

import json
import os
import threading
from datetime import datetime
from modules.config import config


class PunchRecordManager:
    """打卡记录管理类"""

    def __init__(self):
        self.records_dir = config.PUNCH_RECORDS_DIR
        self.ensure_records_dir()
        self.current_month_file = self._get_current_month_file()
        self.records = self.load_records()
        # 并行打卡场景下，多个用户同时写同一月份 JSON 文件需要互斥
        self._lock = threading.Lock()

    def ensure_records_dir(self):
        """确保记录目录存在"""
        if not os.path.exists(self.records_dir):
            os.makedirs(self.records_dir)

    def _get_current_month_file(self):
        """获取当前月份的记录文件路径"""
        current_date = datetime.now()
        return os.path.join(self.records_dir, f"{current_date.strftime('%Y_%m')}.json")

    def _ensure_current_month(self):
        """跨月检查：进程常驻跨月后切换到新月份文件，避免新记录写进上个月文件

        注意：本方法不自带锁，调用方必须已持有 self._lock（防止重入死锁）。
        """
        new_file = self._get_current_month_file()
        if new_file != self.current_month_file:
            # 先把旧月份残留的内存记录落盘，再切换并重新加载新月份文件
            self.save_records()
            self.current_month_file = new_file
            self.records = self.load_records()

    def load_records(self):
        """从文件加载打卡记录"""
        if os.path.exists(self.current_month_file):
            try:
                with open(self.current_month_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载打卡记录失败: {str(e)}")
                # 解析失败多半是上次写入被强杀/断电截断，把损坏文件改名备份而非静默丢弃，
                # 避免随后第一次 save_records 用只含当天的记录覆盖整月历史
                try:
                    backup_file = self.current_month_file + '.corrupt'
                    os.replace(self.current_month_file, backup_file)
                    print(f"已将损坏的打卡记录备份为: {backup_file}")
                except Exception as backup_err:
                    print(f"备份损坏打卡记录失败: {str(backup_err)}")
                return {}
        return {}

    def save_records(self):
        """保存打卡记录到文件"""
        try:
            # 原子写：先写同目录临时文件并 fsync 落盘，再 os.replace 覆盖目标文件，
            # 防止写入过程中被 watchdog 强杀/断电/磁盘满导致目标文件留下半截 JSON
            tmp_file = self.current_month_file + '.tmp'
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(self.records, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self.current_month_file)
        except Exception as e:
            print(f"保存打卡记录失败: {str(e)}")

    def update_record(self, date_str, punch_type, time_str):
        """更新打卡记录（并行打卡场景下用 _lock 串行化整段 load→modify→save）"""
        with self._lock:
            # 跨月后先切换到当月文件，防止新记录写进上个月的归档
            self._ensure_current_month()

            if date_str not in self.records:
                self.records[date_str] = {
                    'punch_in_time': None,
                    'punch_out_time': None
                }

            if punch_type == "上班":
                self.records[date_str]['punch_in_time'] = time_str
            else:  # 下班
                self.records[date_str]['punch_out_time'] = time_str

            self.save_records()

    def get_today_record(self):
        """获取今日打卡记录"""
        with self._lock:
            # 跨月后先切换到当月文件，否则重启进程会读到新月空文件、今日记录丢失
            self._ensure_current_month()
            date_str = datetime.now().strftime('%Y-%m-%d')
            return self.records.get(date_str, {
                'punch_in_time': None,
                'punch_out_time': None
            })

    def get_month_records(self, year=None, month=None):
        """获取指定月份的打卡记录"""
        if year is None or month is None:
            return self.records
        
        target_file = os.path.join(self.records_dir, f"{year}_{month:02d}.json")
        if os.path.exists(target_file):
            try:
                with open(target_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载历史记录失败: {str(e)}")
                return {}
        return {}


# 全局打卡记录管理器实例
punch_record_manager = PunchRecordManager()