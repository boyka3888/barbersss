# Barbershop Telegram Bot 💈

Простой Telegram-бот для барбершопа на **python-telegram-bot (latest async)**.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="<TOKEN>"
export ADMIN_IDS="123456789"
python main.py
```

## Что реализовано

- RU/TJ выбор языка при `/start`.
- Клиентское меню с записью по шагам.
- Несколько филиалов, барберы по филиалам, услуги с ценами TJS.
- Уникальный код записи `BZ-XXXXXX`.
- Команды `/cancel BZ-XXXXXX` и `/bekor BZ-XXXXXX`.
- Админ-уведомления по записи + кнопка показа полного номера.
- Антиспам лимиты через таблицу `rate_limits`.
- Валидация номеров Таджикистана и определение оператора по префиксам (таблица `operators`).
- Напоминание через JobQueue за 2 часа до записи.

## Структура

- `main.py`, `bot.py`
- `config.py`
- `db.py`
- `handlers/`
- `keyboards/`
- `utils/`
