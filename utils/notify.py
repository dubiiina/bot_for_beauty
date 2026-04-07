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



