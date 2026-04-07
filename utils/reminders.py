"""
Планирование и отмена напоминаний за 24 часа (APScheduler + БД).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from database.db import Database
from utils.time_helpers import combine_local, reminder_moment, should_schedule_reminder


def reminder_text(time_str: str) -> str:
    """Текст напоминания (как в ТЗ)."""
    return (
        "Напоминаем, что вы записаны на наращивание ресниц завтра в "
        f"<b>{time_str}</b>.\n"
        "Ждём вас ️"
    )


async def _send_reminder_job(bot: Bot, user_id: int, time_str: str) -> None:
    try:
        await bot.send_message(
            user_id,
            reminder_text(time_str),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        # Пользователь мог заблокировать бота — не роняем планировщик
        pass


def reminder_job_id(booking_id: int) -> str:
    return f"reminder_{booking_id}"


async def schedule_booking_reminder(
    *,
    bot: Bot,
    db: Database,
    scheduler: AsyncIOScheduler,
    booking_id: int,
    user_id: int,
    slot_date: str,
    slot_time: str,
    tz_name: str,
) -> None:
    """После создания записи: поставить напоминание, если до визита > 24 ч."""
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    appt = combine_local(slot_date, slot_time, tz_name)
    if not should_schedule_reminder(appt, now):
        return

    run_at = reminder_moment(appt)
    jid = reminder_job_id(booking_id)

    if scheduler.get_job(jid):
        scheduler.remove_job(jid)

    scheduler.add_job(
        _send_reminder_job,
        trigger=DateTrigger(run_date=run_at, timezone=tz),
        kwargs={
            "bot": bot,
            "user_id": user_id,
            "time_str": slot_time,
        },
        id=jid,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    await db.set_booking_reminder_job(booking_id, jid)


def cancel_reminder_job(scheduler: AsyncIOScheduler, booking_id: int) -> None:
    """Удалить задачу напоминания (перед удалением записи из БД)."""
    jid = reminder_job_id(booking_id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)


async def restore_reminders_from_db(
    *,
    bot: Bot,
    db: Database,
    scheduler: AsyncIOScheduler,
    tz_name: str,
) -> None:
    """При старте бота: восстановить задачи напоминаний из активных записей."""
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    rows = await db.get_all_bookings_for_reminder_restore()
    for b in rows:
        appt = combine_local(b.slot_date, b.slot_time, tz_name)
        if not should_schedule_reminder(appt, now):
            continue
        run_at = reminder_moment(appt)
        jid = reminder_job_id(b.id)
        if scheduler.get_job(jid):
            scheduler.remove_job(jid)
        scheduler.add_job(
            _send_reminder_job,
            trigger=DateTrigger(run_date=run_at, timezone=tz),
            kwargs={
                "bot": bot,
                "user_id": b.user_id,
                "time_str": b.slot_time,
            },
            id=jid,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        await db.set_booking_reminder_job(b.id, jid)
