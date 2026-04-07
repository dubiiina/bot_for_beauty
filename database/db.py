"""
Асинхронная работа с SQLite: расписание, записи, закрытие дней.
"""
from __future__ import annotations

import aiosqlite
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# Путь к файлу БД рядом с пакетом database/
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "salon.db"


@dataclass
class SlotRow:
    id: int
    date: str  # YYYY-MM-DD
    time: str  # HH:MM


@dataclass
class BookingRow:
    id: int
    user_id: int
    slot_id: int
    client_name: str
    phone: str
    reminder_job_id: Optional[str]
    slot_date: str
    slot_time: str


class Database:
    """Обёртка над aiosqlite с методами предметной области."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else DB_PATH

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self.init_schema()

    async def close(self) -> None:
        await self._conn.close()

    async def init_schema(self) -> None:
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS work_days (
                d TEXT PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS day_closures (
                d TEXT PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                d TEXT NOT NULL,
                t TEXT NOT NULL,
                UNIQUE(d, t)
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                slot_id INTEGER NOT NULL UNIQUE,
                client_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                reminder_job_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (slot_id) REFERENCES slots(id) ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS idx_slots_d ON slots(d);
            CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);
            """
        )
        await self._conn.commit()

    # --- Рабочие дни ---

    async def add_work_day(self, d: str) -> bool:
        """Добавить рабочий день (YYYY-MM-DD). False если уже есть."""
        try:
            await self._conn.execute("INSERT INTO work_days(d) VALUES (?)", (d,))
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def has_work_day(self, d: str) -> bool:
        cur = await self._conn.execute("SELECT 1 FROM work_days WHERE d = ?", (d,))
        row = await cur.fetchone()
        return row is not None

    async def list_work_days(self, start: str, end: str) -> list[str]:
        """Список рабочих дней в диапазоне [start, end]."""
        cur = await self._conn.execute(
            "SELECT d FROM work_days WHERE d >= ? AND d <= ? ORDER BY d",
            (start, end),
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def get_bookable_dates(self, start: str, end: str) -> list[str]:
        """
        Даты, на которые можно записаться: рабочий день, день не закрыт,
        есть хотя бы один свободный слот.
        """
        cur = await self._conn.execute(
            """
            SELECT DISTINCT s.d
            FROM slots s
            INNER JOIN work_days w ON w.d = s.d
            LEFT JOIN day_closures c ON c.d = s.d
            LEFT JOIN bookings b ON b.slot_id = s.id
            WHERE s.d >= ? AND s.d <= ?
              AND c.d IS NULL
            GROUP BY s.d
            HAVING SUM(CASE WHEN b.id IS NULL THEN 1 ELSE 0 END) > 0
            ORDER BY s.d
            """,
            (start, end),
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]

    # --- Закрытие дня целиком ---

    async def close_day(self, d: str) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO day_closures(d) VALUES (?)", (d,)
        )
        await self._conn.commit()

    async def open_day(self, d: str) -> None:
        await self._conn.execute("DELETE FROM day_closures WHERE d = ?", (d,))
        await self._conn.commit()

    async def is_day_closed(self, d: str) -> bool:
        cur = await self._conn.execute(
            "SELECT 1 FROM day_closures WHERE d = ?", (d,)
        )
        return (await cur.fetchone()) is not None

    # --- Слоты ---

    async def add_slot(self, d: str, t: str) -> tuple[bool, str]:
        """
        Добавить слот. Требуется, чтобы день был в work_days.
        Возвращает (ok, сообщение об ошибке).
        """
        if not await self.has_work_day(d):
            return False, "Сначала добавьте этот день как рабочий."
        try:
            await self._conn.execute(
                "INSERT INTO slots(d, t) VALUES (?, ?)", (d, t)
            )
            await self._conn.commit()
            return True, ""
        except aiosqlite.IntegrityError:
            return False, "Такой слот уже существует."

    async def delete_slot(self, slot_id: int) -> tuple[bool, str]:
        cur = await self._conn.execute(
            "SELECT 1 FROM bookings WHERE slot_id = ?", (slot_id,)
        )
        if await cur.fetchone():
            return False, "На этот слот есть запись — сначала отмените её."
        cur = await self._conn.execute("DELETE FROM slots WHERE id = ?", (slot_id,))
        await self._conn.commit()
        if cur.rowcount == 0:
            return False, "Слот не найден."
        return True, ""

    async def get_slot(self, slot_id: int) -> Optional[SlotRow]:
        cur = await self._conn.execute(
            "SELECT id, d, t FROM slots WHERE id = ?", (slot_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        return SlotRow(id=row["id"], date=row["d"], time=row["t"])

    async def list_slots_for_date(self, d: str) -> list[tuple[int, str, bool]]:
        """
        Слоты на дату: (id, время HH:MM, свободен).
        """
        cur = await self._conn.execute(
            """
            SELECT s.id, s.t,
                   CASE WHEN b.id IS NULL THEN 1 ELSE 0 END AS free
            FROM slots s
            LEFT JOIN bookings b ON b.slot_id = s.id
            WHERE s.d = ?
            ORDER BY s.t
            """,
            (d,),
        )
        rows = await cur.fetchall()
        return [(r["id"], r["t"], bool(r["free"])) for r in rows]

    # --- Записи ---

    async def user_has_booking(self, user_id: int) -> bool:
        cur = await self._conn.execute(
            "SELECT 1 FROM bookings WHERE user_id = ?", (user_id,)
        )
        return (await cur.fetchone()) is not None

    async def get_booking_by_user(self, user_id: int) -> Optional[BookingRow]:
        cur = await self._conn.execute(
            """
            SELECT b.id, b.user_id, b.slot_id, b.client_name, b.phone,
                   b.reminder_job_id, s.d, s.t
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.user_id = ?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return BookingRow(
            id=row["id"],
            user_id=row["user_id"],
            slot_id=row["slot_id"],
            client_name=row["client_name"],
            phone=row["phone"],
            reminder_job_id=row["reminder_job_id"],
            slot_date=row["d"],
            slot_time=row["t"],
        )

    async def get_booking_by_id(self, booking_id: int) -> Optional[BookingRow]:
        cur = await self._conn.execute(
            """
            SELECT b.id, b.user_id, b.slot_id, b.client_name, b.phone,
                   b.reminder_job_id, s.d, s.t
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = ?
            """,
            (booking_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return BookingRow(
            id=row["id"],
            user_id=row["user_id"],
            slot_id=row["slot_id"],
            client_name=row["client_name"],
            phone=row["phone"],
            reminder_job_id=row["reminder_job_id"],
            slot_date=row["d"],
            slot_time=row["t"],
        )

    async def create_booking(
        self,
        user_id: int,
        slot_id: int,
        client_name: str,
        phone: str,
        reminder_job_id: Optional[str],
    ) -> tuple[Optional[int], str]:
        if await self.user_has_booking(user_id):
            return None, "У вас уже есть активная запись."
        cur = await self._conn.execute(
            "SELECT 1 FROM bookings WHERE slot_id = ?", (slot_id,)
        )
        if await cur.fetchone():
            return None, "Этот слот уже занят."
        try:
            await self._conn.execute(
                """
                INSERT INTO bookings(user_id, slot_id, client_name, phone, reminder_job_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, slot_id, client_name, phone, reminder_job_id),
            )
            await self._conn.commit()
            cur = await self._conn.execute("SELECT last_insert_rowid()")
            bid = (await cur.fetchone())[0]
            return bid, ""
        except aiosqlite.IntegrityError:
            return None, "Не удалось создать запись (слот занят или у вас уже есть запись)."

    async def set_booking_reminder_job(self, booking_id: int, job_id: Optional[str]) -> None:
        await self._conn.execute(
            "UPDATE bookings SET reminder_job_id = ? WHERE id = ?",
            (job_id, booking_id),
        )
        await self._conn.commit()

    async def cancel_booking_by_user(self, user_id: int) -> tuple[bool, Optional[BookingRow]]:
        b = await self.get_booking_by_user(user_id)
        if not b:
            return False, None
        await self._conn.execute("DELETE FROM bookings WHERE id = ?", (b.id,))
        await self._conn.commit()
        return True, b

    async def cancel_booking_by_id(self, booking_id: int) -> Optional[BookingRow]:
        b = await self.get_booking_by_id(booking_id)
        if not b:
            return None
        await self._conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        await self._conn.commit()
        return b

    async def list_bookings_on_date(self, d: str) -> list[BookingRow]:
        cur = await self._conn.execute(
            """
            SELECT b.id, b.user_id, b.slot_id, b.client_name, b.phone,
                   b.reminder_job_id, s.d, s.t
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE s.d = ?
            ORDER BY s.t
            """,
            (d,),
        )
        rows = await cur.fetchall()
        out: list[BookingRow] = []
        for row in rows:
            out.append(
                BookingRow(
                    id=row["id"],
                    user_id=row["user_id"],
                    slot_id=row["slot_id"],
                    client_name=row["client_name"],
                    phone=row["phone"],
                    reminder_job_id=row["reminder_job_id"],
                    slot_date=row["d"],
                    slot_time=row["t"],
                )
            )
        return out

    async def get_all_bookings_for_reminder_restore(self) -> list[BookingRow]:
        """Все записи (для восстановления задач планировщика)."""
        cur = await self._conn.execute(
            """
            SELECT b.id, b.user_id, b.slot_id, b.client_name, b.phone,
                   b.reminder_job_id, s.d, s.t
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            ORDER BY s.d, s.t
            """
        )
        rows = await cur.fetchall()
        out: list[BookingRow] = []
        for row in rows:
            out.append(
                BookingRow(
                    id=row["id"],
                    user_id=row["user_id"],
                    slot_id=row["slot_id"],
                    client_name=row["client_name"],
                    phone=row["phone"],
                    reminder_job_id=row["reminder_job_id"],
                    slot_date=row["d"],
                    slot_time=row["t"],
                )
            )
        return out


def date_range_today_month(days: int = 30) -> tuple[date, date]:
    """Сегодня и конец окна (сегодня + days - 1)."""
    today = date.today()
    end = today + timedelta(days=days - 1)
    return today, end


def to_iso(d: date) -> str:
    return d.isoformat()
