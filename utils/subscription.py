"""Проверка подписки на канал через getChatMember."""
from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ChatMemberStatus


async def is_user_subscribed(bot: Bot, user_id: int, channel_id: str) -> bool:
    """
    True, если пользователь в канале не в статусе left/kicked.
    Бот должен быть администратором канала (или канал публичный с доступом).
    """
    if not channel_id:
        return True  # проверка отключена
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    except Exception:
        return False
    return member.status in (
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    )
