"""
Запись клиента: проверка подписки, календарь, FSM (имя, телефон, подтверждение).
"""
from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOOKING_DAYS_AHEAD, TIMEZONE
from database.db import Database, date_range_today_month, to_iso
from keyboards import (
    booking_confirm_kb,
    calendar_dates_kb,
    main_menu_kb,
    subscription_kb,
    time_slots_kb,
)
from keyboards.callback_data import BookingAction, CalDate, SubCheck, TimeSlot
from states.booking import BookingStates
from utils.notify import notify_admin_new_booking
from utils.reminders import cancel_reminder_job, schedule_booking_reminder
from utils.subscription import is_user_subscribed

router = Router(name="user_booking")


async def _ensure_subscription(
    bot: Bot, user_id: int, channel_id: str
) -> bool:
    if not channel_id:
        return True
    return await is_user_subscribed(bot, user_id, channel_id)


async def _start_booking_calendar(
    message: Message,
    state: FSMContext,
    db: Database,
) -> None:
    """Показать календарь доступных дат."""
    today, end = date_range_today_month(BOOKING_DAYS_AHEAD)
    start_s, end_s = to_iso(today), to_iso(end)
    dates = await db.get_bookable_dates(start_s, end_s)
    if not dates:
        await message.answer(
            "😔 Пока нет свободных дат на ближайший период. Загляните позже или напишите мастеру.",
            reply_markup=main_menu_kb(message.from_user.id),
        )
        await state.clear()
        return
    await state.set_state(BookingStates.choosing_date)
    await message.answer(
        "<b>Выберите дату</b>\n\n"
        f"Доступно расписание на <b>{BOOKING_DAYS_AHEAD}</b> дней вперёд.",
        parse_mode=ParseMode.HTML,
        reply_markup=calendar_dates_kb(dates),
    )


@router.message(F.text == "📅 Записаться")
async def booking_entry(
    message: Message,
    state: FSMContext,
    db: Database,
    bot: Bot,
) -> None:
    """Старт записи: подписка на канал и одна запись на пользователя."""
    uid = message.from_user.id if message.from_user else 0
    from config import CHANNEL_ID as CH

    if await db.user_has_booking(uid):
        await message.answer(
            "У вас уже есть активная запись. Сначала отмените её в разделе "
            "<b>«Моя запись»</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb(uid),
        )
        return

    if not await _ensure_subscription(bot, uid, CH):
        await message.answer(
            "Для записи необходимо подписаться на канал.",
            reply_markup=subscription_kb(),
        )
        return

    await _start_booking_calendar(message, state, db)


@router.callback_query(SubCheck.filter())
async def check_subscription_cb(
    cq: CallbackQuery,
    state: FSMContext,
    db: Database,
    bot: Bot,
) -> None:
    """Повторная проверка подписки."""
    from config import CHANNEL_ID as CH

    uid = cq.from_user.id if cq.from_user else 0
    msg = cq.message
    if msg is None:
        await cq.answer("Ошибка сообщения", show_alert=True)
        return

    if not CH:
        await cq.answer()
        await _start_booking_calendar(msg, state, db)
        return

    if await is_user_subscribed(bot, uid, CH):
        await cq.answer("Подписка подтверждена ✅")
        if await db.user_has_booking(uid):
            await msg.answer(
                "У вас уже есть активная запись.",
                reply_markup=main_menu_kb(uid),
            )
            return
        await _start_booking_calendar(msg, state, db)
    else:
        await cq.answer("Подписка не найдена", show_alert=True)


@router.callback_query(
    CalDate.filter(),
    StateFilter(BookingStates.choosing_date),
)
async def pick_date_cb(
    cq: CallbackQuery,
    callback_data: CalDate,
    state: FSMContext,
    db: Database,
) -> None:
    d = callback_data.d
    if await db.is_day_closed(d):
        await cq.answer("Этот день закрыт", show_alert=True)
        return
    slots = await db.list_slots_for_date(d)
    free = [(sid, t) for sid, t, ok in slots if ok]
    if not free:
        await cq.answer("Нет свободных слотов", show_alert=True)
        return
    await state.update_data(slot_date=d)
    await state.set_state(BookingStates.choosing_time)
    await cq.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    await cq.message.answer(  # type: ignore[union-attr]
        f"<b>Выберите время</b> на <code>{escape(d)}</code>:",
        parse_mode=ParseMode.HTML,
        reply_markup=time_slots_kb(free),
    )
    await cq.answer()


@router.callback_query(
    TimeSlot.filter(),
    StateFilter(BookingStates.choosing_time),
)
async def pick_time_cb(
    cq: CallbackQuery,
    callback_data: TimeSlot,
    state: FSMContext,
    db: Database,
) -> None:
    slot_id = callback_data.slot_id
    slot = await db.get_slot(slot_id)
    if not slot:
        await cq.answer("Слот недоступен", show_alert=True)
        return
    cur = await db.list_slots_for_date(slot.date)
    free_ids = [sid for sid, _t, free in cur if free]
    if slot_id not in free_ids:
        await cq.answer("Слот занят", show_alert=True)
        return
    await state.update_data(slot_id=slot_id, slot_time=slot.time)
    await state.set_state(BookingStates.entering_name)
    await cq.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    await cq.message.answer(  # type: ignore[union-attr]
        "Как к вам обращаться? Введите <b>имя</b>:",
        parse_mode=ParseMode.HTML,
    )
    await cq.answer()


@router.message(StateFilter(BookingStates.entering_name), F.text)
async def enter_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Имя слишком короткое. Попробуйте ещё раз.")
        return
    await state.update_data(client_name=name)
    await state.set_state(BookingStates.entering_phone)
    await message.answer(
        "Введите <b>номер телефона</b> (можно с +7):",
        parse_mode=ParseMode.HTML,
    )


@router.message(StateFilter(BookingStates.entering_phone), F.text)
async def enter_phone(message: Message, state: FSMContext) -> None:
    phone = (message.text or "").strip()
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 10:
        await message.answer("Похоже, номер указан неверно. Введите ещё раз.")
        return
    await state.update_data(phone=phone)
    data = await state.get_data()
    await state.set_state(BookingStates.confirming)
    await message.answer(
        "<b>Проверьте данные</b>\n\n"
        f"📅 Дата: <b>{escape(data['slot_date'])}</b>\n"
        f"🕒 Время: <b>{escape(data['slot_time'])}</b>\n"
        f"👤 Имя: {escape(data['client_name'])}\n"
        f"📞 Телефон: <code>{escape(phone)}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=booking_confirm_kb(),
    )


@router.callback_query(
    BookingAction.filter(F.action == "confirm_yes"),
    StateFilter(BookingStates.confirming),
)
async def confirm_booking_cb(
    cq: CallbackQuery,
    state: FSMContext,
    db: Database,
    bot: Bot,
    scheduler: AsyncIOScheduler,
) -> None:
    uid = cq.from_user.id if cq.from_user else 0
    data = await state.get_data()
    slot_id = data.get("slot_id")
    if not slot_id:
        await cq.answer("Сессия устарела", show_alert=True)
        await state.clear()
        return

    bid, err = await db.create_booking(
        uid,
        int(slot_id),
        data["client_name"],
        data["phone"],
        reminder_job_id=None,
    )
    if not bid:
        await cq.answer(err or "Ошибка", show_alert=True)
        await state.clear()
        return

    await schedule_booking_reminder(
        bot=bot,
        db=db,
        scheduler=scheduler,
        booking_id=bid,
        user_id=uid,
        slot_date=data["slot_date"],
        slot_time=data["slot_time"],
        tz_name=TIMEZONE,
    )

    await notify_admin_new_booking(
        bot,
        name=data["client_name"],
        phone=data["phone"],
        date_str=data["slot_date"],
        time_str=data["slot_time"],
        user_id=uid,
    )

    await state.clear()
    await cq.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    await cq.message.answer(  # type: ignore[union-attr]
        "✅ <b>Вы успешно записаны!</b>\nЖдём вас в назначенное время.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(uid),
    )
    await cq.answer()


@router.callback_query(
    BookingAction.filter(F.action == "confirm_edit"),
    StateFilter(BookingStates.confirming),
)
async def confirm_edit_cb(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BookingStates.entering_name)
    await cq.message.answer(  # type: ignore[union-attr]
        "Введите <b>имя</b> ещё раз:",
        parse_mode=ParseMode.HTML,
    )
    await cq.answer()


@router.callback_query(
    BookingAction.filter(F.action == "back_to_dates"),
    StateFilter(BookingStates.choosing_time),
)
async def back_to_dates_cb(
    cq: CallbackQuery,
    state: FSMContext,
    db: Database,
) -> None:
    today, end = date_range_today_month(BOOKING_DAYS_AHEAD)
    dates = await db.get_bookable_dates(to_iso(today), to_iso(end))
    await state.set_state(BookingStates.choosing_date)
    await cq.message.edit_text(  # type: ignore[union-attr]
        "<b>Выберите дату</b>\n\n"
        f"Доступно расписание на <b>{BOOKING_DAYS_AHEAD}</b> дней вперёд.",
        parse_mode=ParseMode.HTML,
        reply_markup=calendar_dates_kb(dates),
    )
    await cq.answer()


@router.callback_query(BookingAction.filter(F.action == "cancel_booking"))
async def cancel_flow_cb(cq: CallbackQuery, state: FSMContext) -> None:
    """Отмена сценария записи из inline."""
    await state.clear()
    uid = cq.from_user.id if cq.from_user else 0
    try:
        await cq.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    except Exception:
        pass
    await cq.message.answer(  # type: ignore[union-attr]
        "Запись отменена.",
        reply_markup=main_menu_kb(uid),
    )
    await cq.answer()


@router.callback_query(BookingAction.filter(F.action == "user_cancel_booking"))
async def user_cancel_booking_cb(
    cq: CallbackQuery,
    db: Database,
    scheduler: AsyncIOScheduler,
) -> None:
    """Отмена активной записи пользователя."""
    uid = cq.from_user.id if cq.from_user else 0
    b = await db.get_booking_by_user(uid)
    if not b:
        await cq.answer("Записи нет", show_alert=True)
        return
    cancel_reminder_job(scheduler, b.id)
    ok, _ = await db.cancel_booking_by_user(uid)
    if not ok:
        await cq.answer("Не удалось отменить", show_alert=True)
        return
    try:
        await cq.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    except Exception:
        pass
    await cq.message.answer(  # type: ignore[union-attr]
        "Запись отменена. Слот снова доступен для других клиентов.",
        reply_markup=main_menu_kb(uid),
    )
    await cq.answer("Отменено")
