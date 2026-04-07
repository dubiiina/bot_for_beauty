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

from config import ADMIN_ID, ADMIN_SLOTS_END, ADMIN_SLOTS_START, BOOKING_DAYS_AHEAD, SLOT_STEP_MINUTES
from database.db import Database, date_range_today_month, to_iso
from keyboards.callback_data import (
    AdminAction,
    AdminAddSlotTime,
    AdminCancelBookingId,
    AdminDayForBookings,
    AdminDayForSlots,
    AdminDelSlotId,
    AdminSlotsDayPick,
    AdminWorkDayPick,
)
from keyboards.inline import admin_main_kb
from states.admin import AdminStates
from utils.date_parse import parse_date_input, parse_time_input
from utils.reminders import cancel_reminder_job

router = Router(name="admin")

admin_only_msg = F.from_user.id == ADMIN_ID
admin_only_cb = F.from_user.id == ADMIN_ID


def _human_date_short(iso_date: str) -> str:
    # YYYY-MM-DD -> 15.04
    try:
        y, m, d = iso_date.split("-")
        return f"{d}.{m}"
    except Exception:
        return iso_date


def _month_ahead_dates() -> list[str]:
    today, end = date_range_today_month(BOOKING_DAYS_AHEAD)
    out: list[str] = []
    d = today
    while d <= end:
        out.append(to_iso(d))
        d += timedelta(days=1)
    return out


def _iter_times_30min(start_hhmm: str, end_hhmm: str, step_min: int) -> list[str]:
    # генерирует времена [start, end) с шагом step_min
    from datetime import datetime as _dt, timedelta as _td

    base = "2000-01-01"
    s = _dt.fromisoformat(f"{base}T{start_hhmm}:00")
    e = _dt.fromisoformat(f"{base}T{end_hhmm}:00")
    out: list[str] = []
    cur = s
    while cur < e:
        out.append(cur.strftime("%H:%M"))
        cur += _td(minutes=step_min)
    return out


def _pack_time_for_cb(hhmm: str) -> str:
    return hhmm.replace(":", "-")


def _unpack_time_from_cb(hhmm: str) -> str:
    return hhmm.replace("-", ":")


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


# --- Быстро: рабочие дни кнопками ---
@router.callback_query(
    AdminAction.filter(F.action == "work_days_buttons"),
    StateFilter(AdminStates.menu),
    admin_only_cb,
)
async def admin_work_days_buttons(cq: CallbackQuery, db: Database) -> None:
    dates = _month_ahead_dates()
    # одним запросом получаем рабочие дни в диапазоне
    work_days = set(await db.list_work_days(dates[0], dates[-1]))

    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for d in dates:
        exists = d in work_days
        txt = f"{_human_date_short(d)}{' ✅' if exists else ''}"
        row.append(
            InlineKeyboardButton(text=txt, callback_data=AdminWorkDayPick(d=d).pack())
        )
        if len(row) >= 7:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(
        InlineKeyboardButton(
            text="« Назад", callback_data=AdminAction(action="back_admin").pack()
        )
    )
    await cq.message.answer(  # type: ignore[union-attr]
        "<b>Рабочие дни</b>\nНажимайте даты, чтобы добавить как рабочие (✅ — уже добавлено).",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup(),
    )
    await cq.answer()


@router.callback_query(AdminWorkDayPick.filter(), admin_only_cb)
async def admin_work_day_add_cb(cq: CallbackQuery, callback_data: AdminWorkDayPick, db: Database) -> None:
    d = callback_data.d
    ok = await db.add_work_day(d)
    await cq.answer("Добавлено ✅" if ok else "Уже было", show_alert=False)
    # перерисовка клавиатуры
    msg = cq.message
    if msg is None:
        return
    dates = _month_ahead_dates()
    work_days = set(await db.list_work_days(dates[0], dates[-1]))
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for dd in dates:
        exists = dd in work_days
        txt = f"{_human_date_short(dd)}{' ✅' if exists else ''}"
        row.append(
            InlineKeyboardButton(text=txt, callback_data=AdminWorkDayPick(d=dd).pack())
        )
        if len(row) >= 7:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(
        InlineKeyboardButton(
            text="« Назад", callback_data=AdminAction(action="back_admin").pack()
        )
    )
    await msg.edit_reply_markup(reply_markup=builder.as_markup())


# --- Быстро: слоты 30 минут кнопками ---
@router.callback_query(
    AdminAction.filter(F.action == "slots_buttons"),
    StateFilter(AdminStates.menu),
    admin_only_cb,
)
async def admin_slots_buttons_pick_date(cq: CallbackQuery) -> None:
    dates = _month_ahead_dates()
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for d in dates:
        row.append(
            InlineKeyboardButton(
                text=_human_date_short(d),
                callback_data=AdminSlotsDayPick(d=d, mode="add").pack(),
            )
        )
        if len(row) >= 7:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="« Назад", callback_data=AdminAction(action="back_admin").pack()))
    await cq.message.answer(  # type: ignore[union-attr]
        "<b>Слоты (шаг 30 минут)</b>\nВыберите дату:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup(),
    )
    await cq.answer()


@router.callback_query(AdminSlotsDayPick.filter(), admin_only_cb)
async def admin_slots_buttons_pick_time(
    cq: CallbackQuery, callback_data: AdminSlotsDayPick, db: Database
) -> None:
    d = callback_data.d
    mode = callback_data.mode or "add"
    # Показываем времена с отметками, что уже есть
    times = _iter_times_30min(ADMIN_SLOTS_START, ADMIN_SLOTS_END, SLOT_STEP_MINUTES or 30)
    existing = await db.list_slots_for_date(d)
    existing_map = {t: free for _sid, t, free in existing}

    builder = InlineKeyboardBuilder()
    # переключатель режима
    mode_label = "➕ Режим: добавление" if mode == "add" else "🗑 Режим: удаление"
    toggle_to = "del" if mode == "add" else "add"
    builder.row(
        InlineKeyboardButton(
            text=mode_label,
            callback_data=AdminSlotsDayPick(d=d, mode=toggle_to).pack(),
        )
    )

    row: list[InlineKeyboardButton] = []
    for t in times:
        if t in existing_map:
            txt = f"{t} {'✅' if existing_map[t] else '🔒'}"
        else:
            txt = t
        row.append(
            InlineKeyboardButton(
                text=txt,
                callback_data=AdminAddSlotTime(d=d, t=_pack_time_for_cb(t), mode=mode).pack(),
            )
        )
        if len(row) >= 4:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="« К датам", callback_data=AdminAction(action="slots_buttons").pack()))
    await cq.message.answer(  # type: ignore[union-attr]
        f"<b>Слоты на {escape(d)}</b>\n"
        "Нажмите время, чтобы <b>добавить</b> или <b>удалить</b> слот.\n"
        "✅ — слот существует и свободен, 🔒 — слот занят.",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup(),
    )
    await cq.answer()


@router.callback_query(AdminAddSlotTime.filter(), admin_only_cb)
async def admin_add_slot_time_cb(
    cq: CallbackQuery, callback_data: AdminAddSlotTime, db: Database
) -> None:
    d = callback_data.d
    t = _unpack_time_from_cb(callback_data.t)
    mode = callback_data.mode or "add"
    # Для удобства: если день ещё не рабочий — добавим автоматически
    await db.add_work_day(d)

    if mode == "del":
        # удаляем только если слот существует и свободен
        slots = await db.list_slots_for_date(d)
        slot_id = None
        is_free = False
        for sid, tt, free in slots:
            if tt == t:
                slot_id = sid
                is_free = free
                break
        if slot_id is None:
            await cq.answer("Слота нет", show_alert=False)
        elif not is_free:
            await cq.answer("Слот занят — удаление запрещено", show_alert=True)
        else:
            ok, err = await db.delete_slot(int(slot_id))
            await cq.answer("Удалено ✅" if ok else (err or "Не удалось"), show_alert=not ok)
    else:
        ok, err = await db.add_slot(d, t)
        await cq.answer("Слот добавлен ✅" if ok else (err or "Не удалось"), show_alert=not ok)

    # перерисовка клавиатуры этого же окна
    msg = cq.message
    if msg is None:
        return
    times = _iter_times_30min(ADMIN_SLOTS_START, ADMIN_SLOTS_END, SLOT_STEP_MINUTES or 30)
    existing = await db.list_slots_for_date(d)
    existing_map = {tt: free for _sid, tt, free in existing}

    builder = InlineKeyboardBuilder()
    mode_label = "➕ Режим: добавление" if mode == "add" else "🗑 Режим: удаление"
    toggle_to = "del" if mode == "add" else "add"
    builder.row(
        InlineKeyboardButton(
            text=mode_label,
            callback_data=AdminSlotsDayPick(d=d, mode=toggle_to).pack(),
        )
    )
    row: list[InlineKeyboardButton] = []
    for tt in times:
        if tt in existing_map:
            txt = f"{tt} {'✅' if existing_map[tt] else '🔒'}"
        else:
            txt = tt
        row.append(
            InlineKeyboardButton(
                text=txt,
                callback_data=AdminAddSlotTime(d=d, t=_pack_time_for_cb(tt), mode=mode).pack(),
            )
        )
        if len(row) >= 4:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(
        InlineKeyboardButton(
            text="« К датам", callback_data=AdminAction(action="slots_buttons").pack()
        )
    )
    await msg.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(AdminAction.filter(F.action == "back_admin"), admin_only_cb)
async def admin_back_to_menu(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.menu)
    await cq.message.answer(  # type: ignore[union-attr]
        "<b>Админ-панель</b>\nВыберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_main_kb(),
    )
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
