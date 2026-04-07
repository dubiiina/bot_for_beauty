"""
Настройки бота. Скопируйте .env.example в .env и заполните значения,
либо задайте переменные окружения вручную.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из корня проекта
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)


def _get_int(name: str, default: int = 0) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return int(val)


# Токен бота от @BotFather
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# ID администратора (Telegram user id, число)
ADMIN_ID: int = _get_int("ADMIN_ID")

# Канал для публикации записей и проверки подписки (например: @channelname или -1001234567890)
CHANNEL_ID: str = os.getenv("CHANNEL_ID", "")

# Ссылка на канал для кнопки «Подписаться» (https://t.me/...)
CHANNEL_LINK: str = os.getenv("CHANNEL_LINK", "")

# Сколько дней вперёд показывать в календаре записи
BOOKING_DAYS_AHEAD: int = 30

# Часовой пояс для расчёта напоминаний (имя из базы tzdata, напр. Europe/Moscow)
TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Moscow")
