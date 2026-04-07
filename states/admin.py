"""FSM для админ-панели (ввод даты/времени и т.д.)."""
from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    menu = State()
    add_work_day_input = State()
    add_slot_date = State()
    add_slot_time = State()
    del_slot_pick_date = State()
    del_slot_pick_id = State()
    close_day_input = State()
    open_day_input = State()
    cancel_booking_pick_date = State()
    cancel_booking_pick_id = State()
    view_schedule_pick_date = State()
