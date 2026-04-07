"""
Админ-панель: только ADMIN_ID, inline-меню + FSM для ввода дат/времени.
"""
from __future__ import annotations

from datetime import timedelta
from html import escape

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import ADMIN_ID, BOOKING_DAYS_AHEAD
from database.db import Database, date_range_today_month, to_iso
from keyboards.callback_data import (
    AdminAction,
    AdminCancelBookingId,
    AdminDayForBookings,
    AdminDayForSlots,
    AdminDelSlotId,
)
from keyboards.inline import admin_main_kb
from states.admin import AdminStates
from utils.date_parse import parse_date_input, parse_time_input
from utils.reminders import cancel_reminder_job

router = Router(name="admin")

admin_only_msg = F.from_user.id == ADMIN_ID
admin_only_cb = F.from_user.id == ADMIN_ID


@router.message(F.text == "⚙️ Админка", admin_only_msg)
async def admin_open(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.menu)
    await message.answer(
        "<b>Админ-панель</b>\nВыберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_main_kb(),
    )


@router.callback_query(AdminAction.filter(F.action == "exit"), admin_only_cb)
async def admin_exit_cb(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await cq.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    except Exception:
        pass
    await cq.message.answer("Вы вышли из админки.")  # type: ignore[union-attr]
    await cq.answer()


# --- Добавить рабочий день ---
@router.callback_query(
    AdminAction.filter(F.action == "add_work_day"),
    StateFilter(AdminStates.menu),
    admin_only_cb,
)
async def admin_add_work_day_start(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.add_work_day_input)
    await cq.message.answer(  # type: ignore[union-attr]
        "Введите дату рабочего дня в формате <code>YYYY-MM-DD</code> "
        "или <code>ДД.ММ.ГГГГ</code>:",
        parse_mode=ParseMode.HTML,
    )
    await cq.answer()


@router.message(StateFilter(AdminStates.add_work_day_input), admin_only_msg, F.text)
async def admin_add_work_day_done(message: Message, state: FSMContext, db: Database) -> None:
    d = parse_date_input(message.text or "")
    if not d:
        await message.answer("Не удалось разобрать дату. Попробуйте ещё раз.")
        return
    ok = await db.add_work_day(d)
    await state.set_state(AdminStates.menu)
    if ok:
        await message.answer(
            f"✅ День <b>{escape(d)}</b> добавлен как рабочий.",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_main_kb(),
        )
    else:
        await message.answer(
            "Этот день уже был в списке рабочих.",
            reply_markup=admin_main_kb(),
        )


# --- Добавить слот ---
@router.callback_query(
    AdminAction.filter(F.action == "add_slot"),
    StateFilter(AdminStates.menu),
    admin_only_cb,
)
async def admin_add_slot_start(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.add_slot_date)
    await cq.message.answer(  # type: ignore[union-attr]
        "Введите <b>дату</b> слота (<code>YYYY-MM-DD</code> или <code>ДД.ММ.ГГГГ</code>):",
        parse_mode=ParseMode.HTML,
    )
    await cq.answer()


@router.message(StateFilter(AdminStates.add_slot_date), admin_only_msg, F.text)
async def admin_add_slot_date(message: Message, state: FSMContext) -> None:
    d = parse_date_input(message.text or "")
    if not d:
        await message.answer("Дата не распознана. Введите ещё раз.")
        return
    await state.update_data(slot_d=d)
    await state.set_state(AdminStates.add_slot_time)
    await message.answer(
        "Введите <b>время</b> слота в формате <code>ЧЧ:ММ</code> (например, 10:30):",
        parse_mode=ParseMode.HTML,
    )


@router.message(StateFilter(AdminStates.add_slot_time), admin_only_msg, F.text)
async def admin_add_slot_time(
    message: Message, state: FSMContext, db: Database
) -> None:
    data = await state.get_data()
    d = data.get("slot_d")
    if not d:
        await state.set_state(AdminStates.menu)
        await message.answer("Сессия сброшена.", reply_markup=admin_main_kb())
        return
    t = parse_time_input(message.text or "")
    if not t:
        await message.answer("Время не распознано. Введите, например, <code>14:00</code>.")
        return
    ok, err = await db.add_slot(d, t)
    await state.set_state(AdminStates.menu)
    if ok:
        await message.answer(
            f"✅ Слот <b>{escape(d)}</b> в <b>{escape(t)}</b> добавлен.",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_main_kb(),
        )
    else:
        await message.answer(f"❌ {err}", reply_markup=admin_main_kb())


# --- Удалить слот ---
@router.callback_query(
    AdminAction.filter(F.action == "del_slot"),
    StateFilter(AdminStates.menu),
    admin_only_cb,
)
async def admin_del_slot_dates(cq: CallbackQuery, state: FSMContext, db: Database) -> None:
    today, end = date_range_today_month(BOOKING_DAYS_AHEAD + 60)
    # все дни, где есть слоты
    cur_dates: set[str] = set()
    d0, d1 = to_iso(today), to_iso(end)
    # грубо: берём из work_days и проверяем слоты
    for wd in await db.list_work_days(d0, d1):
        slots = await db.list_slots_for_date(wd)
        if slots:
            cur_dates.add(wd)
    if not cur_dates:
        await cq.answer("Нет слотов для удаления", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for d in sorted(cur_dates):
        builder.row(
            InlineKeyboardButton(
                text=d,
                callback_data=AdminDayForSlots(d=d).pack(),
            )
        )
    await state.set_state(AdminStates.del_slot_pick_date)
    await cq.message.answer(  # type: ignore[union-attr]
        "Выберите дату, с которой удалить слот:",
        reply_markup=builder.as_markup(),
    )
    await cq.answer()


@router.callback_query(
    AdminDayForSlots.filter(),
    StateFilter(AdminStates.del_slot_pick_date),
    admin_only_cb,
)
async def admin_del_slot_list(
    cq: CallbackQuery,
    callback_data: AdminDayForSlots,
    state: FSMContext,
    db: Database,
) -> None:
    d = callback_data.d
    slots = await db.list_slots_for_date(d)
    if not slots:
        await cq.answer("Слотов нет", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for sid, t, free in slots:
        label = f"{t} {'(свободен)' if free else '(занят)'}"
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=AdminDelSlotId(slot_id=sid).pack(),
            )
        )
    await state.set_state(AdminStates.del_slot_pick_id)
    await state.update_data(del_slot_d=d)
    await cq.message.answer(  # type: ignore[union-attr]
        f"Слоты на <b>{escape(d)}</b>. Нажмите слот для удаления:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup(),
    )
    await cq.answer()


@router.callback_query(
    AdminDelSlotId.filter(),
    StateFilter(AdminStates.del_slot_pick_id),
    admin_only_cb,
)
async def admin_del_slot_do(
    cq: CallbackQuery,
    callback_data: AdminDelSlotId,
    state: FSMContext,
    db: Database,
) -> None:
    sid = callback_data.slot_id
    ok, err = await db.delete_slot(sid)
    await state.set_state(AdminStates.menu)
    if ok:
        await cq.message.answer(  # type: ignore[union-attr]
            "✅ Слот удалён.",
            reply_markup=admin_main_kb(),
        )
    else:
        await cq.message.answer(  # type: ignore[union-attr]
            f"❌ {err}",
            reply_markup=admin_main_kb(),
        )
    await cq.answer()


# --- Закрыть / открыть день ---
@router.callback_query(
    AdminAction.filter(F.action == "close_day"),
    StateFilter(AdminStates.menu),
    admin_only_cb,
)
async def admin_close_day(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.close_day_input)
    await cq.message.answer(  # type: ignore[union-attr]
        "Введите дату, которую нужно <b>полностью закрыть</b> для записи:",
        parse_mode=ParseMode.HTML,
    )
    await cq.answer()


@router.message(StateFilter(AdminStates.close_day_input), admin_only_msg, F.text)
async def admin_close_day_done(message: Message, state: FSMContext, db: Database) -> None:
    d = parse_date_input(message.text or "")
    if not d:
        await message.answer("Дата не распознана.")
        return
    await db.close_day(d)
    await state.set_state(AdminStates.menu)
    await message.answer(
        f"🔒 День <b>{escape(d)}</b> закрыт для записей.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_main_kb(),
    )


@router.callback_query(
    AdminAction.filter(F.action == "open_day"),
    StateFilter(AdminStates.menu),
    admin_only_cb,
)
async def admin_open_day(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.open_day_input)
    await cq.message.answer(  # type: ignore[union-attr]
        "Введите дату, с которой снять <b>полное закрытие</b>:",
        parse_mode=ParseMode.HTML,
    )
    await cq.answer()


@router.message(StateFilter(AdminStates.open_day_input), admin_only_msg, F.text)
async def admin_open_day_done(message: Message, state: FSMContext, db: Database) -> None:
    d = parse_date_input(message.text or "")
    if not d:
        await message.answer("Дата не распознана.")
        return
    await db.open_day(d)
    await state.set_state(AdminStates.menu)
    await message.answer(
        f"🔓 День <b>{escape(d)}</b> снова доступен (если есть слоты).",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_main_kb(),
    )


# --- Отмена записи клиента ---
@router.callback_query(
    AdminAction.filter(F.action == "cancel_booking"),
    StateFilter(AdminStates.menu),
    admin_only_cb,
)
async def admin_cancel_book_dates(cq: CallbackQuery, state: FSMContext, db: Database) -> None:
    today, end = date_range_today_month(BOOKING_DAYS_AHEAD + 90)
    dates_with = []
    d = today
    while d <= end:
        ds = to_iso(d)
        bs = await db.list_bookings_on_date(ds)
        if bs:
            dates_with.append(ds)
        d += timedelta(days=1)
    if not dates_with:
        await cq.answer("Нет записей", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for ds in dates_with[:40]:
        builder.row(
            InlineKeyboardButton(
                text=ds,
                callback_data=AdminDayForBookings(d=ds).pack(),
            )
        )
    await state.set_state(AdminStates.cancel_booking_pick_date)
    await cq.message.answer(  # type: ignore[union-attr]
        "Выберите дату записи для отмены:",
        reply_markup=builder.as_markup(),
    )
    await cq.answer()


@router.callback_query(
    AdminDayForBookings.filter(),
    StateFilter(AdminStates.cancel_booking_pick_date),
    admin_only_cb,
)
async def admin_cancel_book_list(
    cq: CallbackQuery,
    callback_data: AdminDayForBookings,
    db: Database,
    state: FSMContext,
) -> None:
    d = callback_data.d
    bookings = await db.list_bookings_on_date(d)
    if not bookings:
        await cq.answer("Пусто", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for b in bookings:
        label = f"{b.slot_time} — {b.client_name}"
        builder.row(
            InlineKeyboardButton(
                text=label[:60],
                callback_data=AdminCancelBookingId(booking_id=b.id).pack(),
            )
        )
    await state.set_state(AdminStates.cancel_booking_pick_id)
    await cq.message.answer(  # type: ignore[union-attr]
        "Выберите запись для отмены:",
        reply_markup=builder.as_markup(),
    )
    await cq.answer()


@router.callback_query(
    AdminCancelBookingId.filter(),
    StateFilter(AdminStates.cancel_booking_pick_id),
    admin_only_cb,
)
async def admin_cancel_book_do(
    cq: CallbackQuery,
    callback_data: AdminCancelBookingId,
    state: FSMContext,
    db: Database,
    scheduler: AsyncIOScheduler,
) -> None:
    bid = callback_data.booking_id
    b = await db.get_booking_by_id(bid)
    if not b:
        await cq.answer("Запись не найдена", show_alert=True)
        return
    cancel_reminder_job(scheduler, bid)
    await db.cancel_booking_by_id(bid)
    await state.set_state(AdminStates.menu)
    await cq.message.answer(  # type: ignore[union-attr]
        f"✅ Запись #{bid} отменена. Слот освобождён.",
        reply_markup=admin_main_kb(),
    )
    await cq.answer()


# --- Просмотр расписания на дату ---
@router.callback_query(
    AdminAction.filter(F.action == "view_day"),
    StateFilter(AdminStates.menu),
    admin_only_cb,
)
async def admin_view_start(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.view_schedule_pick_date)
    await cq.message.answer(  # type: ignore[union-attr]
        "Введите дату для просмотра (<code>YYYY-MM-DD</code>):",
        parse_mode=ParseMode.HTML,
    )
    await cq.answer()


@router.message(StateFilter(AdminStates.view_schedule_pick_date), admin_only_msg, F.text)
async def admin_view_done(message: Message, state: FSMContext, db: Database) -> None:
    d = parse_date_input(message.text or "")
    if not d:
        await message.answer("Дата не распознана.")
        return
    bookings = await db.list_bookings_on_date(d)
    slots = await db.list_slots_for_date(d)
    lines = [f"<b>Расписание на {escape(d)}</b>\n"]
    if await db.is_day_closed(d):
        lines.append("<i>День полностью закрыт для записи.</i>\n")
    lines.append("")
    lines.append("<b>Слоты:</b>")
    if not slots:
        lines.append("<i>Нет слотов.</i>")
    else:
        for sid, t, free in slots:
            st = "свободен" if free else "занят"
            lines.append(f"• <code>{escape(t)}</code> — {st} (id {sid})")
    lines.append("")
    lines.append("<b>Записи:</b>")
    if not bookings:
        lines.append("<i>Нет записей.</i>")
    else:
        for b in bookings:
            lines.append(
                f"• <b>{escape(b.slot_time)}</b> — {escape(b.client_name)}, "
                f"<code>{escape(b.phone)}</code>, user <code>{b.user_id}</code>"
            )
    await state.set_state(AdminStates.menu)
    await message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_main_kb(),
    )
