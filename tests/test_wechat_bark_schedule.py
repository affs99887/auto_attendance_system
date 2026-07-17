"""微信 Bark 转发的时段判定测试：分钟级边界、24:00 结束、起止顺序校验。"""
import unittest
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from modules.wechat_bark_listener import ConfigError, DEFAULT_CONFIG, SchedulePolicy


class SchedulePolicyTests(unittest.TestCase):
    timezone = ZoneInfo("Asia/Shanghai")

    def make_policy(self, start: str, end: str) -> SchedulePolicy:
        config = deepcopy(DEFAULT_CONFIG)
        config["schedule"]["start_time"] = start
        config["schedule"]["end_time"] = end
        policy = SchedulePolicy(config)
        # 固定节假日判定为"工作日"，让用例离线可重复（不依赖节假日数据源）
        policy.calendar.is_holiday = lambda _day: (False, "workday")
        return policy

    def test_minute_boundaries(self) -> None:
        policy = self.make_policy("07:30", "11:45")

        self.assertFalse(
            policy.decide(
                datetime(2026, 7, 17, 7, 29, 59, 999999, tzinfo=self.timezone)
            ).allowed
        )
        self.assertTrue(
            policy.decide(datetime(2026, 7, 17, 7, 30, tzinfo=self.timezone)).allowed
        )
        self.assertTrue(
            policy.decide(
                datetime(2026, 7, 17, 11, 44, 59, 999999, tzinfo=self.timezone)
            ).allowed
        )
        self.assertFalse(
            policy.decide(datetime(2026, 7, 17, 11, 45, tzinfo=self.timezone)).allowed
        )

    def test_24_hour_end_includes_last_microsecond(self) -> None:
        policy = self.make_policy("00:00", "24:00")

        self.assertTrue(
            policy.decide(
                datetime(2026, 7, 17, 23, 59, 59, 999999, tzinfo=self.timezone)
            ).allowed
        )

    def test_start_must_be_before_end(self) -> None:
        with self.assertRaises(ConfigError):
            self.make_policy("12:00", "12:00")


if __name__ == "__main__":
    unittest.main()
