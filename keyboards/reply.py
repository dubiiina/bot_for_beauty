"""Reply-клавиатура главного меню."""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from config import ADMIN_ID


def main_menu_kb(user_id: int) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="📅 Записаться"),
        KeyboardButton(text="📌 Моя запись"),
    )
    builder.row(
        KeyboardButton(text="💅 Прайсы"),
        KeyboardButton(text="🖼 Портфолио"),
    )
    if user_id == ADMIN_ID:
        builder.row(KeyboardButton(text="⚙️ Админка"))
    return builder.as_markup(resize_keyboard=True)
