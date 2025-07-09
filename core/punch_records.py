import json
import os
from datetime import datetime

class PunchRecordManager:
    def __init__(self):
        self.records_dir = 'punch_records'
        self.ensure_records_dir()
        self.current_month_file = self._get_current_month_file()
        self.records = self.load_records()

    def ensure_records_dir(self):
        """确保记录目录存在"""
        if not os.path.exists(self.records_dir):
            os.makedirs(self.records_dir)

    def _get_current_month_file(self):
        """获取当前月份的记录文件路径"""
        current_date = datetime.now()
        return os.path.join(self.records_dir, f"{current_date.strftime('%Y_%m')}.json")

    def load_records(self):
        """从文件加载打卡记录"""
        if os.path.exists(self.current_month_file):
            try:
                with open(self.current_month_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载打卡记录失败: {str(e)}")
                return {}
        return {}

    def save_records(self):
        """保存打卡记录到文件"""
        try:
            with open(self.current_month_file, 'w', encoding='utf-8') as f:
                json.dump(self.records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存打卡记录失败: {str(e)}")

    def update_record(self, date_str, punch_type, time_str):
        """更新打卡记录"""
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