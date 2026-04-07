"""
Точка входа: запуск бота, планировщика, восстановление напоминаний из БД.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, TIMEZONE
from database.db import Database
from handlers import register_handlers
from middlewares import InjectMiddleware
from utils.reminders import restore_reminders_from_db


async def main() -> None:
    if not BOT_TOKEN:
        logging.error("Задайте BOT_TOKEN в .env или переменных окружения.")
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    db = Database()
    await db.connect()

    scheduler = AsyncIOScheduler(timezone=ZoneInfo(TIMEZONE))
    scheduler.start()

    dp.update.outer_middleware(InjectMiddleware(db=db, scheduler=scheduler))
    register_handlers(dp)

    async def _startup() -> None:
        await restore_reminders_from_db(
            bot=bot,
            db=db,
            scheduler=scheduler,
            tz_name=TIMEZONE,
        )
        logging.info("Бот запущен, напоминания восстановлены из БД.")

    async def _shutdown() -> None:
        scheduler.shutdown(wait=False)
        await db.close()

    dp.startup.register(_startup)
    dp.shutdown.register(_shutdown)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
