"""Inline-клавиатуры: календарь, слоты, подтверждение, админка, подписка."""
from __future__ import annotations

from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import CHANNEL_LINK
from keyboards.callback_data import (
    AdminAction,
    BookingAction,
    CalDate,
    SubCheck,
    TimeSlot,
)


def _human_date(iso_date: str) -> str:
    """YYYY-MM-DD -> «15 апр»."""
    d = datetime.strptime(iso_date, "%Y-%m-%d")
    months = (
        "янв",
        "фев",
        "мар",
        "апр",
        "мая",
        "июн",
        "июл",
        "авг",
        "сен",
        "окт",
        "ноя",
        "дек",
    )
    return f"{d.day} {months[d.month - 1]}"


def calendar_dates_kb(dates: list[str]) -> InlineKeyboardMarkup:
    """Сетка дат (до 7 кнопок в ряд) — только доступные для записи дни."""
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for d in dates:
        row.append(
            InlineKeyboardButton(
                text=_human_date(d),
                callback_data=CalDate(d=d).pack(),
            )
        )
        if len(row) >= 7:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(
        InlineKeyboardButton(
            text="« В меню",
            callback_data=BookingAction(action="cancel_booking").pack(),
        )
    )
    return builder.as_markup()


def time_slots_kb(slots: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """Слоты: (id, HH:MM)."""
    builder = InlineKeyboardBuilder()
    for slot_id, t in slots:
        builder.row(
            InlineKeyboardButton(
                text=t,
                callback_data=TimeSlot(slot_id=slot_id).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="« Назад к датам",
            callback_data=BookingAction(action="back_to_dates").pack(),
        )
    )
    return builder.as_markup()


def booking_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Подтвердить",
            callback_data=BookingAction(action="confirm_yes").pack(),
        ),
        InlineKeyboardButton(
            text="✏️ Изменить",
            callback_data=BookingAction(action="confirm_edit").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="« Отмена",
            callback_data=BookingAction(action="cancel_booking").pack(),
        )
    )
    return builder.as_markup()


def subscription_kb() -> InlineKeyboardMarkup:
    """Подписаться + проверить."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Подписаться", url=CHANNEL_LINK or "https://t.me/")
    )
    builder.row(
        InlineKeyboardButton(
            text="Проверить подписку",
            callback_data=SubCheck().pack(),
        )
    )
    return builder.as_markup()


def portfolio_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Смотреть портфолио",
            url="https://ru.pinterest.com/crystalwithluv/_created/",
        )
    )
    return builder.as_markup()


def admin_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить рабочий день",
            callback_data=AdminAction(action="add_work_day").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🕒 Добавить слот",
            callback_data=AdminAction(action="add_slot").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить слот",
            callback_data=AdminAction(action="del_slot").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔒 Закрыть день",
            callback_data=AdminAction(action="close_day").pack(),
        ),
        InlineKeyboardButton(
            text="🔓 Открыть день",
            callback_data=AdminAction(action="open_day").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить запись клиента",
            callback_data=AdminAction(action="cancel_booking").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📋 Расписание на дату",
            callback_data=AdminAction(action="view_day").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="« Закрыть",
            callback_data=AdminAction(action="exit").pack(),
        )
    )
    return builder.as_markup()


def cancel_my_booking_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить запись",
            callback_data=BookingAction(action="user_cancel_booking").pack(),
        )
    )
    return builder.as_markup()
