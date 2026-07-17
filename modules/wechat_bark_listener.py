#!/usr/bin/env python3
"""
微信通知 Bark 转发监听核心（仅 macOS 生效）。

原理：轮询读取 macOS 通知中心的 SQLite 数据库（需要"完全磁盘访问"权限），
解析微信通知的标题/正文，按"时段 + 中国节假日"规则过滤后推送到 Bark。
状态游标存在 state 文件里做去重；节假日数据来自 holiday-cn 年度 JSON（带本地缓存）。

两种用法：
- 被 modules/wechat_bark_service.py 以后台线程驱动（传入 stop_event 控制停止）；
- 命令行独立运行：python -m modules.wechat_bark_listener --config xx.json，
  支持 --test / --check-schedule / --list-apps / --dry-run / --once。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import plistlib
import re
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


DEFAULT_CONFIG: dict[str, Any] = {
    "bark": {
        "server": "https://api.day.app",
        "device_key": "",
        "group": "WeChat",
        "sound": "",
        "level": "active",
        "url": "",
        "icon": "",
        "use_post": True,
    },
    "wechat": {
        "bundle_ids": ["com.tencent.xinwechat"],
        "title_prefix": "微信",
        "show_sender_in_body": False,
        "sender_label": "发送人",
        "ignore_title_patterns": [],
        "ignore_body_patterns": [],
    },
    "listener": {
        "poll_interval_seconds": 2,
        "send_existing_on_start": False,
        "state_file": "~/.wechat-bark-listener/state.json",
        "db_path": "",
        "max_body_chars": 800,
    },
    "schedule": {
        "enabled": True,
        "timezone": "Asia/Shanghai",
        "start_time": "07:00",
        "end_time": "12:00",
        "weekends_are_holidays": True,
        "holiday_source_urls": [
            "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
            "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
        ],
        "holiday_cache_dir": "~/.wechat-bark-listener/holidays",
        "holiday_cache_ttl_hours": 168,
        "allow_on_holiday_fetch_error": False,
    },
}

FIELD_ALIASES = {
    "NSTitle": "title",
    "titl": "title",
    "title": "title",
    "Title": "title",
    "NSSubtitle": "subtitle",
    "subt": "subtitle",
    "subtitle": "subtitle",
    "Subtitle": "subtitle",
    "NSInformativeText": "body",
    "informativeText": "body",
    "InformativeText": "body",
    "body": "body",
    "Body": "body",
    "message": "body",
    "Message": "body",
    "content": "body",
    "Content": "body",
}

NOISE_STRINGS = {
    "$archiver",
    "$classes",
    "$class",
    "$null",
    "$objects",
    "$top",
    "app",
    "cate",
    "date",
    "dest",
    "iden",
    "orig",
    "req",
    "soun",
    "srce",
    "styl",
    "titl",
    "usda",
    "uuid",
    "NSArray",
    "NSData",
    "NSDate",
    "NSDictionary",
    "NSMutableArray",
    "NSMutableData",
    "NSMutableDictionary",
    "NSMutableString",
    "NSNumber",
    "NSObject",
    "NSString",
    "NS.keys",
    "NS.objects",
    "NS.time",
    "NS.uuidbytes",
    "NS.uuidstring",
    "NSAlert",
    "NSApplicationBundleIdentifier",
    "NSApplicationName",
    "NSImage",
    "NSInformativeText",
    "NSSubtitle",
    "NSTitle",
}


@dataclass
class NotificationRecord:
    record_id: int
    app_identifier: str
    delivered_at: float | None
    title: str
    subtitle: str
    body: str


class ConfigError(RuntimeError):
    pass


class NotificationDatabaseError(RuntimeError):
    pass


class HolidayDataError(RuntimeError):
    pass


@dataclass
class ScheduleDecision:
    allowed: bool
    reason: str
    now: datetime


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_legacy_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    schedule = normalized.get("schedule")
    if not isinstance(schedule, dict):
        return normalized

    migrated_schedule = dict(schedule)
    if "start_time" not in migrated_schedule and "start_hour" in migrated_schedule:
        migrated_schedule["start_time"] = f"{migrated_schedule['start_hour']}:00"
    if "end_time" not in migrated_schedule and "end_hour" in migrated_schedule:
        migrated_schedule["end_time"] = f"{migrated_schedule['end_hour']}:00"
    normalized["schedule"] = migrated_schedule
    return normalized


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return DEFAULT_CONFIG
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        user_config = json.load(fh)
    if not isinstance(user_config, dict):
        raise ConfigError("Config root must be a JSON object")
    return deep_merge(DEFAULT_CONFIG, normalize_legacy_config(user_config))


def expand_path(path: str | os.PathLike[str] | None) -> Path | None:
    if not path:
        return None
    return Path(os.path.expandvars(os.path.expanduser(str(path))))


def quote_ident(name: str) -> str:
    if name == "rowid":
        return "rowid"
    return '"' + name.replace('"', '""') + '"'


def sqlite_uri(path: Path) -> str:
    quoted = urllib.parse.quote(str(path), safe="/:")
    return f"file:{quoted}?mode=ro"


def notification_db_candidates() -> Iterable[Path]:
    home = Path.home()
    yield home / "Library/Group Containers/group.com.apple.usernoted/db2/db"
    yield home / "Library/Group Containers/group.com.apple.usernoted/db/db"

    legacy_dir = home / "Library/Application Support/NotificationCenter"
    try:
        yield from sorted(legacy_dir.glob("*.db"))
    except PermissionError:
        return


def find_notification_db(configured_path: str | None) -> Path:
    explicit = expand_path(configured_path)
    if explicit:
        if explicit.exists():
            return explicit
        raise NotificationDatabaseError(f"Configured notification database does not exist: {explicit}")

    permission_errors: list[str] = []
    for candidate in notification_db_candidates():
        try:
            if candidate.exists():
                return candidate
        except PermissionError as exc:
            permission_errors.append(f"{candidate}: {exc}")

    suffix = ""
    if permission_errors:
        suffix = "\nPermission errors:\n" + "\n".join(permission_errors)
    raise NotificationDatabaseError(
        "找不到 macOS 通知中心数据库。请给“微信 Bark 转发”开启完全磁盘访问权限，"
        "或在配置中填写 listener.db_path。"
        + suffix
    )


class NotificationStore:
    def __init__(self, db_path: Path, bundle_ids: list[str]) -> None:
        self.db_path = db_path
        self.bundle_ids = bundle_ids
        self.schema = self._inspect_schema()

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "NotificationStore":
        db_path = find_notification_db(config["listener"].get("db_path"))
        bundle_ids = [str(item) for item in config["wechat"].get("bundle_ids", []) if str(item).strip()]
        if not bundle_ids:
            raise ConfigError("wechat.bundle_ids must contain at least one bundle id")
        return cls(db_path, bundle_ids)

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(sqlite_uri(self.db_path), uri=True, timeout=2)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as exc:
            raise NotificationDatabaseError(
                f"无法打开通知中心数据库：{self.db_path}\n"
                "请给“微信 Bark 转发”开启完全磁盘访问权限后重新启动应用。"
            ) from exc

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        try:
            return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})")}
        except sqlite3.Error as exc:
            raise NotificationDatabaseError(f"Unable to read table info for {table}") from exc

    def _inspect_schema(self) -> dict[str, str]:
        with self._connect() as conn:
            tables = {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            if "app" not in tables or "record" not in tables:
                raise NotificationDatabaseError(
                    "Unsupported Notification Center database schema: expected tables 'app' and 'record'."
                )

            app_columns = self._table_columns(conn, "app")
            record_columns = self._table_columns(conn, "record")

        app_id = first_present(app_columns, ["app_id", "id"])
        app_identifier = first_present(app_columns, ["identifier", "bundle_id", "bundleid"])
        record_app_id = first_present(record_columns, ["app_id"])
        record_id = first_present(record_columns, ["rec_id", "id"]) or "rowid"
        record_data = first_present(record_columns, ["data", "blob"])
        delivered_at = first_present(record_columns, ["delivered_date", "request_date", "request_last_date"])

        missing = [
            name
            for name, value in {
                "app id": app_id,
                "app identifier": app_identifier,
                "record app id": record_app_id,
                "record data": record_data,
            }.items()
            if not value
        ]
        if missing:
            raise NotificationDatabaseError(
                "Unsupported Notification Center database schema; missing " + ", ".join(missing)
            )

        return {
            "app_id": app_id or "",
            "app_identifier": app_identifier or "",
            "record_app_id": record_app_id or "",
            "record_id": record_id,
            "record_data": record_data or "",
            "delivered_at": delivered_at or "",
        }

    def list_apps(self) -> list[tuple[str, int]]:
        record_id = self.record_id_expr()
        app_identifier = f"a.{quote_ident(self.schema['app_identifier'])}"
        app_join = self.join_expr()
        query = (
            f"SELECT {app_identifier} AS identifier, COUNT({record_id}) AS count "
            f"FROM app a LEFT JOIN record r ON {app_join} "
            f"GROUP BY {app_identifier} "
            "ORDER BY count DESC, identifier ASC"
        )
        with self._connect() as conn:
            return [(str(row["identifier"]), int(row["count"])) for row in conn.execute(query)]

    def record_id_expr(self) -> str:
        record_id = self.schema["record_id"]
        if record_id == "rowid":
            return "r.rowid"
        return f"r.{quote_ident(record_id)}"

    def delivered_at_expr(self) -> str:
        delivered_at = self.schema.get("delivered_at")
        if not delivered_at:
            return "NULL"
        return f"r.{quote_ident(delivered_at)}"

    def join_expr(self) -> str:
        return (
            f"r.{quote_ident(self.schema['record_app_id'])} = "
            f"a.{quote_ident(self.schema['app_id'])}"
        )

    def placeholders(self) -> str:
        return ",".join("?" for _ in self.bundle_ids)

    def max_record_id(self) -> int:
        record_id = self.record_id_expr()
        app_identifier = f"a.{quote_ident(self.schema['app_identifier'])}"
        query = (
            f"SELECT MAX({record_id}) AS max_id "
            f"FROM record r JOIN app a ON {self.join_expr()} "
            f"WHERE {app_identifier} IN ({self.placeholders()})"
        )
        with self._connect() as conn:
            row = conn.execute(query, self.bundle_ids).fetchone()
        return int(row["max_id"] or 0)

    def fetch_after(self, last_record_id: int, limit: int = 100) -> list[NotificationRecord]:
        record_id = self.record_id_expr()
        data_col = f"r.{quote_ident(self.schema['record_data'])}"
        app_identifier = f"a.{quote_ident(self.schema['app_identifier'])}"
        delivered_at = self.delivered_at_expr()
        query = (
            f"SELECT {record_id} AS record_id, {app_identifier} AS app_identifier, "
            f"{delivered_at} AS delivered_at, {data_col} AS data "
            f"FROM record r JOIN app a ON {self.join_expr()} "
            f"WHERE {app_identifier} IN ({self.placeholders()}) AND {record_id} > ? "
            f"ORDER BY {record_id} ASC LIMIT ?"
        )
        params: list[Any] = [*self.bundle_ids, int(last_record_id), int(limit)]
        with self._connect() as conn:
            rows = list(conn.execute(query, params))

        records: list[NotificationRecord] = []
        for row in rows:
            parsed = parse_notification_blob(bytes(row["data"] or b""))
            records.append(
                NotificationRecord(
                    record_id=int(row["record_id"]),
                    app_identifier=str(row["app_identifier"]),
                    delivered_at=float(row["delivered_at"]) if row["delivered_at"] is not None else None,
                    title=parsed.get("title", ""),
                    subtitle=parsed.get("subtitle", ""),
                    body=parsed.get("body", ""),
                )
            )
        return records


def first_present(columns: set[str], names: list[str]) -> str | None:
    for name in names:
        if name in columns:
            return name
    return None


def resolve_uid(value: Any, objects: list[Any] | None, depth: int = 0) -> Any:
    if depth > 20:
        return value
    if objects is not None and isinstance(value, plistlib.UID):
        index = value.data
        if 0 <= index < len(objects):
            return resolve_uid(objects[index], objects, depth + 1)
    return value


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\x00", " ")).strip()


def value_to_text(value: Any, objects: list[Any] | None, depth: int = 0) -> str:
    if depth > 20:
        return ""

    value = resolve_uid(value, objects, depth)
    if value is None:
        return ""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, bytes):
        return clean_text(decode_bytes(value))
    if isinstance(value, (int, float, bool)):
        return ""
    if isinstance(value, list):
        parts = [value_to_text(item, objects, depth + 1) for item in value]
        return clean_text(" ".join(part for part in parts if part))
    if isinstance(value, dict):
        for key in ("NS.string", "NSString", "string", "value"):
            if key in value:
                text = value_to_text(value[key], objects, depth + 1)
                if text:
                    return text
        parts = collect_strings(value, objects, depth + 1)
        return clean_text(" ".join(parts[:3]))
    return ""


def decode_bytes(value: bytes) -> str:
    for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
        try:
            text = value.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text.strip():
            return text
    return value.decode("utf-8", errors="ignore")


def extract_known_fields(node: Any, objects: list[Any] | None, fields: dict[str, str] | None = None, depth: int = 0) -> dict[str, str]:
    if fields is None:
        fields = {}
    if depth > 30:
        return fields

    node = resolve_uid(node, objects, depth)
    if isinstance(node, dict):
        ns_keys = node.get("NS.keys")
        ns_objects = node.get("NS.objects")
        if isinstance(ns_keys, list) and isinstance(ns_objects, list):
            for key_ref, value_ref in zip(ns_keys, ns_objects):
                key = value_to_text(key_ref, objects, depth + 1)
                field_name = FIELD_ALIASES.get(key)
                if field_name and field_name not in fields:
                    text = value_to_text(value_ref, objects, depth + 1)
                    if text and text not in NOISE_STRINGS:
                        fields[field_name] = text

        for key, value in node.items():
            key_text = value_to_text(key, objects, depth + 1)
            field_name = FIELD_ALIASES.get(key_text)
            if field_name and field_name not in fields:
                text = value_to_text(value, objects, depth + 1)
                if text and text not in NOISE_STRINGS:
                    fields[field_name] = text
            extract_known_fields(value, objects, fields, depth + 1)
    elif isinstance(node, list):
        for item in node:
            extract_known_fields(item, objects, fields, depth + 1)

    return fields


def collect_strings(node: Any, objects: list[Any] | None, depth: int = 0, seen: set[int] | None = None) -> list[str]:
    if seen is None:
        seen = set()
    if depth > 30:
        return []

    node = resolve_uid(node, objects, depth)
    if isinstance(node, str):
        text = clean_text(node)
        return [text] if text else []
    if isinstance(node, bytes):
        text = clean_text(decode_bytes(node))
        return [text] if text else []
    if not isinstance(node, (dict, list, tuple)):
        return []

    node_id = id(node)
    if node_id in seen:
        return []
    seen.add(node_id)

    strings: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            strings.extend(collect_strings(key, objects, depth + 1, seen))
            strings.extend(collect_strings(value, objects, depth + 1, seen))
    else:
        for item in node:
            strings.extend(collect_strings(item, objects, depth + 1, seen))
    return strings


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = clean_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def looks_user_visible(value: str) -> bool:
    if not value or value in NOISE_STRINGS or value in FIELD_ALIASES:
        return False
    if value.startswith("$") or value.startswith("NS."):
        return False
    if value.startswith("com.apple.") or value.startswith("com.tencent."):
        return False
    if re.fullmatch(r"[A-Za-z0-9_.$:/-]{4,}", value) and any(ch in value for ch in "./:$"):
        return False
    return True


def printable_fallback_strings(raw: bytes) -> list[str]:
    decoded = raw.decode("utf-8", errors="ignore")
    chunks = re.findall(r"[\w\u3400-\u9fff][\w\s\u3400-\u9fff，。！？：；、（）()@#%+\-]{1,}", decoded)
    ascii_chunks = [item.decode("utf-8", errors="ignore") for item in re.findall(rb"[\x20-\x7e]{3,}", raw)]
    return unique_preserving_order([*chunks, *ascii_chunks])


def parse_notification_blob(raw: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    strings: list[str] = []

    parsed: Any | None = None
    candidates = [raw]
    bplist_index = raw.find(b"bplist00")
    if bplist_index > 0:
        candidates.append(raw[bplist_index:])

    for candidate in candidates:
        try:
            parsed = plistlib.loads(candidate)
            break
        except Exception:
            continue

    if parsed is not None:
        objects = parsed.get("$objects") if isinstance(parsed, dict) and isinstance(parsed.get("$objects"), list) else None
        fields.update(extract_known_fields(parsed, objects))
        strings = collect_strings(parsed, objects)

    usable_strings = [item for item in unique_preserving_order(strings) if looks_user_visible(item)]
    if not usable_strings:
        usable_strings = [item for item in printable_fallback_strings(raw) if looks_user_visible(item)]

    title = fields.get("title", "")
    subtitle = fields.get("subtitle", "")
    body = fields.get("body", "")

    if not title and usable_strings:
        title = usable_strings[0]
    if not body:
        fallback_body = [item for item in usable_strings if item not in {title, subtitle}]
        if fallback_body:
            body = "\n".join(fallback_body[:3])
    if not subtitle and body == title:
        body = ""

    return {"title": title, "subtitle": subtitle, "body": body}


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"last_record_id": 0}
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, json.JSONDecodeError):
            logging.warning("State file is unreadable; starting from current notification cursor")
            return {"last_record_id": 0}
        if not isinstance(state, dict):
            return {"last_record_id": 0}
        return {"last_record_id": int(state.get("last_record_id") or 0)}

    def save(self, last_record_id: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump({"last_record_id": int(last_record_id)}, fh, ensure_ascii=False, indent=2)
        tmp_path.replace(self.path)


class HolidayCalendar:
    def __init__(self, config: dict[str, Any]) -> None:
        schedule = config.get("schedule", {})
        self.weekends_are_holidays = bool(schedule.get("weekends_are_holidays", True))
        self.allow_on_fetch_error = bool(schedule.get("allow_on_holiday_fetch_error", False))
        self.cache_dir = expand_path(schedule.get("holiday_cache_dir")) or Path.home() / ".wechat-bark-listener/holidays"
        self.cache_ttl = timedelta(hours=float(schedule.get("holiday_cache_ttl_hours") or 168))
        self.source_urls = self._source_urls(schedule)
        self._years: dict[int, dict[date, bool]] = {}

    def _source_urls(self, schedule: dict[str, Any]) -> list[str]:
        configured = schedule.get("holiday_source_urls") or schedule.get("holiday_source_url") or []
        if isinstance(configured, str):
            configured = [configured]
        urls = [str(url).strip() for url in configured if str(url).strip()]
        if not urls:
            raise ConfigError("schedule.holiday_source_urls must contain at least one URL template")
        return urls

    def is_holiday(self, target: date) -> tuple[bool, str]:
        if self.weekends_are_holidays and target.weekday() >= 5:
            return True, "weekend"

        try:
            is_off_day = self._is_off_day(target)
        except HolidayDataError as exc:
            if self.allow_on_fetch_error:
                logging.warning("Holiday data unavailable; allowing forwarding because config permits it: %s", exc)
                return False, "holiday data unavailable; allowed by config"
            return True, f"holiday data unavailable: {exc}"

        if is_off_day:
            return True, "holiday"
        return False, "workday"

    def _is_off_day(self, target: date) -> bool:
        current_year = self._load_year(target.year)
        if target in current_year:
            return current_year[target]

        extra_years: list[int] = []
        if target.month == 12:
            extra_years.append(target.year + 1)
        elif target.month == 1:
            extra_years.append(target.year - 1)

        for year in extra_years:
            try:
                days = self._load_year(year)
            except HolidayDataError as exc:
                logging.debug("Optional holiday year %s unavailable: %s", year, exc)
                continue
            if target in days:
                return days[target]

        return False

    def _load_year(self, year: int) -> dict[date, bool]:
        if year in self._years:
            return self._years[year]

        cache_path = self.cache_dir / f"{year}.json"
        cached_payload = self._read_cache(cache_path)
        if cached_payload is not None and not self._cache_is_stale(cache_path):
            self._years[year] = self._parse_year(cached_payload, year)
            return self._years[year]

        try:
            payload = self._fetch_year(year)
        except HolidayDataError:
            if cached_payload is not None:
                logging.warning("Using stale holiday cache for %s", year)
                self._years[year] = self._parse_year(cached_payload, year)
                return self._years[year]
            raise

        self._write_cache(cache_path, payload)
        self._years[year] = self._parse_year(payload, year)
        return self._years[year]

    def _read_cache(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logging.warning("Holiday cache is unreadable: %s", exc)
            return None
        return payload if isinstance(payload, dict) else None

    def _cache_is_stale(self, path: Path) -> bool:
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            return True
        return datetime.now() - modified_at > self.cache_ttl

    def _write_cache(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        tmp_path.replace(path)

    def _fetch_year(self, year: int) -> dict[str, Any]:
        errors: list[str] = []
        for template in self.source_urls:
            url = template.format(year=year)
            request = urllib.request.Request(url, headers={"User-Agent": "wechat-bark-listener/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"{url}: {exc}")
                continue
            if isinstance(payload, dict):
                return payload
            errors.append(f"{url}: response is not a JSON object")
        raise HolidayDataError("; ".join(errors) or f"unable to fetch holiday data for {year}")

    def _parse_year(self, payload: dict[str, Any], year: int) -> dict[date, bool]:
        days = payload.get("days", [])
        if not isinstance(days, list):
            raise HolidayDataError(f"holiday data for {year} does not contain a days list")

        parsed: dict[date, bool] = {}
        for item in days:
            if not isinstance(item, dict):
                continue
            raw_date = item.get("date")
            if not isinstance(raw_date, str):
                continue
            try:
                day = date.fromisoformat(raw_date)
            except ValueError:
                continue
            parsed[day] = bool(item.get("isOffDay"))
        return parsed


def parse_schedule_clock(value: Any, fallback: str, field_name: str, allow_24: bool = False) -> tuple[int, str]:
    text = str(value or fallback).strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        raise ConfigError(f"{field_name} must use HH:MM format")

    hour = int(match.group(1))
    minute = int(match.group(2))
    if allow_24 and hour == 24 and minute == 0:
        return 24 * 60, "24:00"
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ConfigError(f"{field_name} is not a valid time")
    return hour * 60 + minute, f"{hour:02d}:{minute:02d}"


class SchedulePolicy:
    def __init__(self, config: dict[str, Any]) -> None:
        schedule = config.get("schedule", {})
        self.enabled = bool(schedule.get("enabled", True))
        self.timezone_name = str(schedule.get("timezone") or "Asia/Shanghai")
        self.timezone = ZoneInfo(self.timezone_name)
        self.start_minutes, self.start_time_label = parse_schedule_clock(
            schedule.get("start_time"), "07:00", "schedule.start_time"
        )
        self.end_minutes, self.end_time_label = parse_schedule_clock(
            schedule.get("end_time"), "12:00", "schedule.end_time", allow_24=True
        )
        if self.start_minutes >= self.end_minutes:
            raise ConfigError("schedule.start_time must be earlier than schedule.end_time")
        self.calendar = HolidayCalendar(config)

    def decide(self, now: datetime | None = None) -> ScheduleDecision:
        current = now or datetime.now(self.timezone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=self.timezone)
        else:
            current = current.astimezone(self.timezone)

        if not self.enabled:
            return ScheduleDecision(True, "schedule disabled", current)

        current_seconds = (
            current.hour * 3600
            + current.minute * 60
            + current.second
            + current.microsecond / 1_000_000
        )
        if not self.start_minutes * 60 <= current_seconds < self.end_minutes * 60:
            return ScheduleDecision(
                False,
                f"outside allowed window {self.start_time_label}-{self.end_time_label}",
                current,
            )

        is_holiday, reason = self.calendar.is_holiday(current.date())
        if is_holiday:
            return ScheduleDecision(False, reason, current)
        return ScheduleDecision(True, "workday window", current)


class BarkClient:
    def __init__(self, config: dict[str, Any], dry_run: bool = False) -> None:
        bark = config["bark"]
        self.server = str(bark.get("server") or "https://api.day.app").rstrip("/")
        self.device_key = str(bark.get("device_key") or "").strip()
        self.dry_run = dry_run
        self.use_post = bool(bark.get("use_post", True))
        self.options = {
            key: value
            for key in ("group", "sound", "level", "url", "icon", "badge", "copy", "autoCopy", "isArchive")
            if (value := bark.get(key)) not in ("", None)
        }

        if not self.device_key and not self.dry_run:
            raise ConfigError("bark.device_key is required")

    def push(self, title: str, body: str) -> None:
        title = title or "微信通知"
        body = body or "收到一条新的微信通知"
        if self.dry_run:
            print(json.dumps({"title": title, "body": body, **self.options}, ensure_ascii=False))
            return

        if self.use_post:
            try:
                self._push_post(title, body)
                return
            except urllib.error.HTTPError as exc:
                if exc.code not in (404, 405):
                    raise
                logging.warning("Bark POST endpoint unavailable; falling back to GET")

        self._push_get(title, body)

    def _push_post(self, title: str, body: str) -> None:
        payload = {
            "device_key": self.device_key,
            "title": title,
            "body": body,
            **self.options,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.server}/push",
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        self._send(request)

    def _push_get(self, title: str, body: str) -> None:
        path = "/".join(
            urllib.parse.quote(part, safe="")
            for part in (self.device_key, title, body)
        )
        query = urllib.parse.urlencode(self.options)
        url = f"{self.server}/{path}"
        if query:
            url = f"{url}?{query}"
        self._send(urllib.request.Request(url, method="GET"))

    def _send(self, request: urllib.request.Request) -> None:
        with urllib.request.urlopen(request, timeout=10) as response:
            content = response.read()
        if not content:
            return
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        code = payload.get("code")
        if code not in (None, 200):
            raise RuntimeError(f"Bark push failed: {payload}")


def compile_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        if not pattern:
            continue
        compiled.append(re.compile(str(pattern), re.IGNORECASE))
    return compiled


def should_ignore(record: NotificationRecord, title_patterns: list[re.Pattern[str]], body_patterns: list[re.Pattern[str]]) -> bool:
    title_text = record.title or ""
    body_text = "\n".join(part for part in (record.subtitle, record.body) if part)
    return any(pattern.search(title_text) for pattern in title_patterns) or any(
        pattern.search(body_text) for pattern in body_patterns
    )


def format_for_bark(record: NotificationRecord, config: dict[str, Any]) -> tuple[str, str]:
    prefix = str(config["wechat"].get("title_prefix") or "").strip()
    show_sender_in_body = bool(config["wechat"].get("show_sender_in_body", True))
    sender_label = str(config["wechat"].get("sender_label") or "发送人").strip()
    max_body_chars = int(config["listener"].get("max_body_chars") or 800)

    sender = clean_text(record.title)
    title = sender or "微信通知"
    if prefix and not title.startswith(prefix):
        title = f"{prefix}: {title}"

    body_parts: list[str] = []
    if show_sender_in_body and sender and sender not in {"微信", "WeChat"}:
        body_parts.append(f"{sender_label}: {sender}" if sender_label else sender)
    body_parts.extend(
        unique_preserving_order(
            part for part in (record.subtitle, record.body) if part and clean_text(part) != sender
        )
    )
    body = "\n".join(body_parts) or "收到一条新的微信通知"
    if len(body) > max_body_chars:
        body = body[: max_body_chars - 1].rstrip() + "..."
    return title, body


def run_listener(config: dict[str, Any], args: argparse.Namespace,
                 stop_event: threading.Event | None = None) -> int:
    if args.test:
        client = BarkClient(config, dry_run=args.dry_run)
        client.push("微信监听测试", "Bark 推送配置正常")
        return 0

    schedule_policy = SchedulePolicy(config)
    if args.check_schedule:
        decision = schedule_policy.decide()
        print(
            json.dumps(
                {
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "now": decision.now.isoformat(),
                    "timezone": schedule_policy.timezone_name,
                    "start_time": schedule_policy.start_time_label,
                    "end_time": schedule_policy.end_time_label,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    store = NotificationStore.from_config(config)
    logging.info("Using notification database: %s", store.db_path)
    logging.info("Listening for bundle ids: %s", ", ".join(store.bundle_ids))

    if args.list_apps:
        for identifier, count in store.list_apps():
            print(f"{identifier}\t{count}")
        return 0

    client = BarkClient(config, dry_run=args.dry_run)
    state_path = expand_path(config["listener"].get("state_file"))
    if state_path is None:
        raise ConfigError("listener.state_file is required")
    state_store = StateStore(state_path)
    state = state_store.load()
    last_record_id = int(state.get("last_record_id") or 0)

    send_existing = bool(config["listener"].get("send_existing_on_start")) or bool(args.send_existing)
    if last_record_id <= 0 and not send_existing:
        last_record_id = store.max_record_id()
        state_store.save(last_record_id)
        logging.info("Initialized cursor at record id %s; existing notifications will not be forwarded", last_record_id)

    title_patterns = compile_patterns(config["wechat"].get("ignore_title_patterns", []))
    body_patterns = compile_patterns(config["wechat"].get("ignore_body_patterns", []))
    poll_interval = float(config["listener"].get("poll_interval_seconds") or 2)

    stop = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True

    # 后台线程模式（stop_event 非 None）用事件控制停止；signal 只能在主线程注册，
    # 命令行独立运行时才走信号方式。
    if stop_event is None:
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)

    def should_stop() -> bool:
        return stop or (stop_event is not None and stop_event.is_set())

    while not should_stop():
        current_max = store.max_record_id()
        if current_max and last_record_id > current_max:
            logging.warning("Notification cursor is ahead of database; resetting to %s", current_max)
            last_record_id = current_max
            state_store.save(last_record_id)

        records = store.fetch_after(last_record_id)
        for record in records:
            if should_ignore(record, title_patterns, body_patterns):
                logging.info("Ignored notification record %s", record.record_id)
                last_record_id = record.record_id
                state_store.save(last_record_id)
                continue

            schedule_decision = schedule_policy.decide()
            if not schedule_decision.allowed:
                logging.info(
                    "Skipped notification record %s because schedule blocked it: %s",
                    record.record_id,
                    schedule_decision.reason,
                )
                last_record_id = record.record_id
                state_store.save(last_record_id)
                continue

            title, body = format_for_bark(record, config)
            client.push(title, body)
            last_record_id = record.record_id
            state_store.save(last_record_id)
            logging.info("Forwarded notification record %s from %s", record.record_id, record.app_identifier)

        if args.once:
            break
        # 可打断的轮询等待：线程模式下 stop_event.wait 让"停止监听"立即生效
        if stop_event is not None:
            stop_event.wait(poll_interval)
        else:
            time.sleep(poll_interval)

    logging.info("Stopped")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Forward macOS WeChat notifications to Bark.")
    parser.add_argument("--config", type=Path, default=Path("config.json"), help="Path to config JSON")
    parser.add_argument("--list-apps", action="store_true", help="List app bundle identifiers found in Notification Center")
    parser.add_argument("--test", action="store_true", help="Send a test Bark notification and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print notifications instead of sending to Bark")
    parser.add_argument("--once", action="store_true", help="Scan once and exit")
    parser.add_argument("--send-existing", action="store_true", help="Forward existing notifications when no state exists")
    parser.add_argument("--check-schedule", action="store_true", help="Print whether forwarding is currently allowed")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        config = load_config(args.config if args.config.exists() else None if args.list_apps else args.config)
        return run_listener(config, args)
    except (ConfigError, NotificationDatabaseError, sqlite3.Error, urllib.error.URLError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
