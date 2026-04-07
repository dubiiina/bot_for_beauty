"""
Главное меню: /start, прайсы, портфолио, просмотр своей записи (без FSM для прайсов).
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message

from database.db import Database
from keyboards import main_menu_kb, portfolio_kb
from keyboards.inline import cancel_my_booking_kb

router = Router(name="user_menu")


PRICES_HTML = (
    "<b>Прайс</b>\n\n"
    "Френч — <b>1000₽</b>\n"
    "Квадрат — <b>500₽</b>"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Приветствие и главное меню."""
    uid = message.from_user.id if message.from_user else 0
    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Здесь можно записаться на маникюр, посмотреть прайс и портфолио.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(uid),
    )


@router.message(F.text == "💅 Прайсы")
async def show_prices(message: Message) -> None:
    """Прайсы — без FSM."""
    await message.answer(PRICES_HTML, parse_mode=ParseMode.HTML)


@router.message(F.text == "🖼 Портфолио")
async def show_portfolio(message: Message) -> None:
    """Ссылка на портфолио — без FSM."""
    await message.answer(
        "<b>Портфолио работ</b>\n\nНажмите кнопку ниже, чтобы открыть галерею.",
        parse_mode=ParseMode.HTML,
        reply_markup=portfolio_kb(),
    )


@router.message(F.text == "📌 Моя запись")
async def my_booking(message: Message, db: Database) -> None:
    """Показать активную запись и кнопку отмены."""
    uid = message.from_user.id if message.from_user else 0
    b = await db.get_booking_by_user(uid)
    if not b:
        await message.answer(
            "У вас пока нет активной записи.",
            reply_markup=main_menu_kb(uid),
        )
        return
    text = (
        "<b>Ваша запись</b>\n\n"
        f"📅 Дата: <b>{b.slot_date}</b>\n"
        f"🕒 Время: <b>{b.slot_time}</b>\n"
        f"👤 Имя: {b.client_name}\n"
        f"📞 Телефон: <code>{b.phone}</code>"
    )
    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_my_booking_kb(),
    )
