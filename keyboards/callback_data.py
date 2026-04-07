"""Типизированные callback_data для aiogram 3."""
from aiogram.filters.callback_data import CallbackData


class CalDate(CallbackData, prefix="cdate"):
    d: str  # YYYY-MM-DD


class TimeSlot(CallbackData, prefix="slot"):
    slot_id: int


class BookingAction(CallbackData, prefix="book"):
    action: str


class SubCheck(CallbackData, prefix="sub"):
    pass


class AdminAction(CallbackData, prefix="adm"):
    action: str


class AdminDayForSlots(CallbackData, prefix="adsd"):
    """Выбор дня для удаления слота."""
    d: str


class AdminDelSlotId(CallbackData, prefix="adls"):
    slot_id: int


class AdminDayForBookings(CallbackData, prefix="adbd"):
    """День для отмены записи админом."""
    d: str


class AdminCancelBookingId(CallbackData, prefix="adbc"):
    booking_id: int


class AdminWorkDayPick(CallbackData, prefix="awdp"):
    """Кнопки добавления рабочего дня."""
    d: str


class AdminSlotsDayPick(CallbackData, prefix="asdp"):
    """Выбор даты для добавления слотов кнопками."""
    d: str
    mode: str  # add | del


class AdminAddSlotTime(CallbackData, prefix="aast"):
    """Добавить/удалить слот на выбранную дату."""
    d: str
    t: str  # HH-MM (без двоеточия, чтобы pack() не падал)
    mode: str  # add | del
