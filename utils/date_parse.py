"""Разбор даты из текста админом."""
from datetime import datetime


def parse_date_input(s: str) -> str | None:
    """Возвращает YYYY-MM-DD или None."""
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_time_input(s: str) -> str | None:
    """HH:MM или H:MM -> нормализованный HH:MM."""
    s = s.strip().replace(" ", "")
    for fmt in ("%H:%M", "%H.%M"):
        try:
            t = datetime.strptime(s, fmt).time()
            return f"{t.hour:02d}:{t.minute:02d}"
        except ValueError:
            continue
    return None
