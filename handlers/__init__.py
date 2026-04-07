"""Роутеры хендлеров."""
from aiogram import Dispatcher

from handlers.admin import router as admin_router
from handlers.user_booking import router as booking_router
from handlers.user_menu import router as menu_router


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(admin_router)
    dp.include_router(booking_router)
    dp.include_router(menu_router)
