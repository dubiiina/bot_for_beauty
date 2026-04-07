# Telegram-бот записи (маникюр)

Бот на **Python 3.10+**, **aiogram 3**, **SQLite**, **APScheduler** (напоминания за 24 часа).

## Установка

```bash
cd путь/к/проекту
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy env.example .env
```

Отредактируйте `.env`: укажите `BOT_TOKEN`, `ADMIN_ID`, `CHANNEL_ID`, `CHANNEL_LINK`, при необходимости `TIMEZONE` и параметры слотов админа.

## Запуск

```bash
python bot.py
```

Перед первым запуском в админке добавьте **рабочие дни** и **временные слоты** — иначе в календаре не будет доступных дат.

## Требования к Telegram

- Бот добавлен в канал как **администратор** (для проверки подписки и публикации записей).
- Указан корректный `CHANNEL_ID` (юзернейм с `@` или числовой id).

Файл базы: `data/salon.db` (создаётся автоматически).
