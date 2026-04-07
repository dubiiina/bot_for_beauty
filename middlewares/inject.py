"""Передача зависимостей (БД, планировщик) в хендлеры."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from database.db import Database


class InjectMiddleware(BaseMiddleware):
    def __init__(self, db: Database, scheduler: Any) -> None:
        self.db = db
        self.scheduler = scheduler

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        data["scheduler"] = self.scheduler
        return await handler(event, data)
