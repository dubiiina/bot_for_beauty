"""Уведомления администратора и публикация в канал (HTML)."""
from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.enums import ParseMode

from config import ADMIN_ID, CHANNEL_ID
from database.db import Database


async def notify_admin_new_booking(
    bot: Bot,
    *,
    name: str,
    phone: str,
    date_str: str,
    time_str: str,
    user_id: int,
) -> None:
    text = (
        "<b>Новая запись</b>\n"
        f"📅 <b>{escape(date_str)}</b> в <b>{escape(time_str)}</b>\n"
        f"👤 Имя: {escape(name)}\n"
        f"📞 Телефон: <code>{escape(phone)}</code>\n"
        f"🆔 Клиент ID: <code>{user_id}</code>"
    )
    await bot.send_message(ADMIN_ID, text, parse_mode=ParseMode.HTML)


async def post_channel_schedule(
    bot: Bot,
    db: Database,
    *,
    date_str: str,
    highlight_name: str | None = None,
    highlight_time: str | None = None,
) -> None:
    """
    Сообщение в канал: расписание на дату + акцент на новой записи (если передано).
    """
    if not CHANNEL_ID:
        return
    bookings = await db.list_bookings_on_date(date_str)
    lines: list[str] = [
        f"<b>Расписание на {escape(date_str)}</b>",
        "",
    ]
    if not bookings:
        lines.append("<i>Записей пока нет.</i>")
    else:
        for b in bookings:
            mark = ""
            if (
                highlight_name
                and highlight_time
                and b.client_name == highlight_name
                and b.slot_time == highlight_time
            ):
                mark = " ⭐"
            lines.append(
                f"• <b>{escape(b.slot_time)}</b> — {escape(b.client_name)}, "
                f"<code>{escape(b.phone)}</code>{mark}"
            )
    await bot.send_message(CHANNEL_ID, "\n".join(lines), parse_mode=ParseMode.HTML)



