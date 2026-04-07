"""Парсинг даты/времени записи и расчёт момента напоминания."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def combine_local(date_str: str, time_str: str, tz_name: str) -> datetime:
    """Собрать aware-datetime в заданной таймзоне."""
    tz = ZoneInfo(tz_name)
    d, t = date_str.strip(), time_str.strip()
    return datetime.fromisoformat(f"{d}T{t}:00").replace(tzinfo=tz)


def reminder_moment(appointment: datetime, hours_before: int = 24) -> datetime:
    """Момент отправки напоминания (за N часов до визита)."""
    return appointment - timedelta(hours=hours_before)


def should_schedule_reminder(
    appointment: datetime, now: datetime, hours_before: int = 24
) -> bool:
    """
    Нужно ли планировать напоминание: до визита больше 24 ч,
    и момент напоминания ещё в будущем относительно now.
    """
    rem = reminder_moment(appointment, hours_before)
    return appointment - now > timedelta(hours=hours_before) and rem > now
