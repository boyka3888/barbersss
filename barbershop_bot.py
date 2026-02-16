#!/usr/bin/env python3
"""
💈 Telegram Barbershop Bot
Full-featured booking bot with admin panel, SQLite DB, reminders, and more.
Built with python-telegram-bot v21+ (latest async version).

Usage:
  1. pip install python-telegram-bot[job-queue]
  2. Set BOT_TOKEN and ADMIN_IDS below
  3. python barbershop_bot.py
"""

import os
import logging
import sqlite3
import re
from datetime import datetime, timedelta
from collections import defaultdict
from contextlib import contextmanager

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# ─── CONFIG ──────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8501777856:AAEcOaAffR3ZFfQ8nsHqewzEvfGC-77kQ4g")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "7232478996").split(",")))
DB_PATH = "barbershop.db"
REMINDER_HOURS = 2  # remind N hours before appointment

# Anti-spam: max actions per window
SPAM_MAX_ACTIONS = 5
SPAM_WINDOW_SECONDS = 120

# ─── LOGGING ─────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── CONVERSATION STATES ─────────────────────────────────────────────
(
    BOOK_SERVICE, BOOK_BARBER, BOOK_DATE, BOOK_TIME,
    BOOK_NAME, BOOK_PHONE, BOOK_CONFIRM
) = range(7)

REVIEW_TEXT = 10
RESCHEDULE_DATE, RESCHEDULE_TIME = 11, 12

# Admin conversation states
(
    ADMIN_ADD_BARBER_NAME, ADMIN_RENAME_BARBER_NEW,
    ADMIN_ADD_SERVICE_NAME, ADMIN_ADD_SERVICE_PRICE, ADMIN_ADD_SERVICE_DURATION,
    ADMIN_EDIT_SERVICE_FIELD, ADMIN_EDIT_SERVICE_VALUE,
    ADMIN_SCHEDULE_START, ADMIN_SCHEDULE_END, ADMIN_SCHEDULE_SLOT,
    ADMIN_BOOKINGS_BY_BARBER,
) = range(20, 31)

# ─── ANTI-SPAM ───────────────────────────────────────────────────────
spam_tracker: dict[int, list[float]] = defaultdict(list)


def is_spam(user_id: int) -> bool:
    now = datetime.now().timestamp()
    window = [t for t in spam_tracker[user_id] if now - t < SPAM_WINDOW_SECONDS]
    spam_tracker[user_id] = window
    if len(window) >= SPAM_MAX_ACTIONS:
        return True
    spam_tracker[user_id].append(now)
    return False


# ─── DATABASE ────────────────────────────────────────────────────────
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            phone TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS barbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL DEFAULT 0,
            duration INTEGER NOT NULL DEFAULT 30,
            emoji TEXT DEFAULT '✂️'
        );
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            barber_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            client_name TEXT,
            client_phone TEXT,
            status TEXT DEFAULT 'confirmed',
            admin_confirmed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            reminded INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (service_id) REFERENCES services(id),
            FOREIGN KEY (barber_id) REFERENCES barbers(id),
            UNIQUE(barber_id, date, time)
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        # Default settings
        defaults = {
            "work_start": "10:00",
            "work_end": "20:00",
            "slot_minutes": "30",
            "address": "📍 ул. Барберная, д. 1\n📞 +7 (999) 123-45-67\n🕐 Пн-Вс 10:00–20:00",
        }
        for k, v in defaults.items():
            db.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v)
            )

        # Seed data if empty
        if db.execute("SELECT COUNT(*) FROM barbers").fetchone()[0] == 0:
            for name in ["Алексей", "Дмитрий", "Артём"]:
                db.execute("INSERT INTO barbers(name) VALUES(?)", (name,))

        if db.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
            seed = [
                ("✂️ Стрижка", 1500, 30, "✂️"),
                ("🧔 Борода", 800, 20, "🧔"),
                ("💇‍♂️ Комплекс", 2000, 50, "💇‍♂️"),
                ("👦 Детская", 1000, 30, "👦"),
                ("🔥 VIP", 3500, 60, "🔥"),
            ]
            for name, price, dur, emoji in seed:
                db.execute(
                    "INSERT INTO services(name, price, duration, emoji) VALUES(?,?,?,?)",
                    (name, price, dur, emoji),
                )


def get_setting(key: str) -> str:
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""


def set_setting(key: str, value: str):
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value)
        )


def ensure_user(user):
    with get_db() as db:
        db.execute(
            """INSERT OR REPLACE INTO users(user_id, username, full_name)
               VALUES(?, ?, ?)""",
            (user.id, user.username or "", user.full_name or ""),
        )


# ─── HELPERS ─────────────────────────────────────────────────────────
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def main_menu_keyboard(user_id: int):
    buttons = [
        ["✍️ Записаться", "📋 Мои записи"],
        ["💰 Прайс", "📍 Контакты"],
        ["⭐ Отзывы", "⚙️ Настройки"],
    ]
    if is_admin(user_id):
        buttons.append(["👑 Админка"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def get_free_slots(barber_id: int, date_str: str, service_duration: int = 30) -> list[str]:
    start = get_setting("work_start")  # "10:00"
    end = get_setting("work_end")      # "20:00"
    slot_min = int(get_setting("slot_minutes") or 30)

    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    start_minutes = sh * 60 + sm
    end_minutes = eh * 60 + em

    # Generate all possible slots
    all_slots = []
    t = start_minutes
    while t + service_duration <= end_minutes:
        hh, mm = divmod(t, 60)
        all_slots.append(f"{hh:02d}:{mm:02d}")
        t += slot_min

    # Get booked slots for this barber+date
    with get_db() as db:
        rows = db.execute(
            """SELECT b.time, s.duration FROM bookings b
               JOIN services s ON s.id = b.service_id
               WHERE b.barber_id=? AND b.date=? AND b.status='confirmed'""",
            (barber_id, date_str),
        ).fetchall()

    # Build occupied time ranges
    occupied = []
    for row in rows:
        bh, bm = map(int, row["time"].split(":"))
        occ_start = bh * 60 + bm
        occ_end = occ_start + row["duration"]
        occupied.append((occ_start, occ_end))

    # Filter: a slot is free if [slot, slot+service_duration) doesn't overlap any occupied
    free = []
    for slot in all_slots:
        hh, mm = map(int, slot.split(":"))
        s_start = hh * 60 + mm
        s_end = s_start + service_duration
        conflict = any(not (s_end <= occ_s or s_start >= occ_e) for occ_s, occ_e in occupied)
        if not conflict:
            free.append(slot)

    # If date is today, exclude past times
    today = datetime.now().strftime("%Y-%m-%d")
    if date_str == today:
        now_minutes = datetime.now().hour * 60 + datetime.now().minute
        free = [s for s in free if int(s.split(":")[0]) * 60 + int(s.split(":")[1]) > now_minutes]

    return free


WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_RU = ["", "янв", "фев", "мар", "апр", "мая", "июн",
             "июл", "авг", "сен", "окт", "ноя", "дек"]


def next_7_days() -> list[tuple[str, str]]:
    """Return list of (date_str, label) for next 7 days."""
    result = []
    today = datetime.now()
    for i in range(7):
        d = today + timedelta(days=i)
        label = f"{WEEKDAYS_RU[d.weekday()]} {d.day} {MONTHS_RU[d.month]}"
        if i == 0:
            label = f"Сегодня ({label})"
        elif i == 1:
            label = f"Завтра ({label})"
        result.append((d.strftime("%Y-%m-%d"), label))
    return result


def format_booking(b) -> str:
    with get_db() as db:
        service = db.execute("SELECT * FROM services WHERE id=?", (b["service_id"],)).fetchone()
        barber = db.execute("SELECT * FROM barbers WHERE id=?", (b["barber_id"],)).fetchone()
    d = datetime.strptime(b["date"], "%Y-%m-%d")
    date_label = f"{WEEKDAYS_RU[d.weekday()]} {d.day} {MONTHS_RU[d.month]}"
    status_emoji = "✅" if b["status"] == "confirmed" else "❌"
    admin_mark = " (подтв. админом)" if b["admin_confirmed"] else ""
    return (
        f"{status_emoji} Запись #{b['id']}{admin_mark}\n"
        f"💈 {service['name'] if service else '?'}\n"
        f"👤 {barber['name'] if barber else '?'}\n"
        f"📅 {date_label}\n"
        f"⏰ {b['time']}\n"
        f"📞 {b['client_phone'] or '—'}\n"
        f"🧑 {b['client_name'] or '—'}"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ─── /start ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    await update.message.reply_text(
        "💈 <b>Добро пожаловать в BarberShop Bot!</b>\n\n"
        "Я помогу вам быстро записаться к барберу.\n"
        "Выберите действие из меню ниже 👇",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
    return ConversationHandler.END


# ─── PRICE ───────────────────────────────────────────────────────────
async def show_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as db:
        services = db.execute("SELECT * FROM services ORDER BY price").fetchall()
    if not services:
        await update.message.reply_text("Прайс пока пуст 😔")
        return
    lines = ["💰 <b>Прайс-лист</b>\n"]
    for s in services:
        lines.append(f"{s['emoji']} <b>{s['name']}</b> — {s['price']} ₽  ⏱ {s['duration']} мин")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── CONTACTS ────────────────────────────────────────────────────────
async def show_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    addr = get_setting("address")
    await update.message.reply_text(f"📍 <b>Наши контакты</b>\n\n{addr}", parse_mode="HTML")


# ─── SETTINGS ────────────────────────────────────────────────────────
async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ <b>Настройки</b>\n\n"
        "Пока здесь можно только посмотреть информацию.\n"
        "Управление доступно администратору через 👑 Админку.",
        parse_mode="HTML",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BOOKING FLOW (ConversationHandler)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_spam(update.effective_user.id):
        await update.message.reply_text("🚫 Слишком много запросов. Подождите пару минут.")
        return ConversationHandler.END

    ensure_user(update.effective_user)
    with get_db() as db:
        services = db.execute("SELECT * FROM services ORDER BY id").fetchall()
    if not services:
        await update.message.reply_text("😔 Услуги ещё не добавлены. Попробуйте позже.")
        return ConversationHandler.END

    buttons = []
    for s in services:
        buttons.append([InlineKeyboardButton(
            f"{s['emoji']} {s['name']} — {s['price']} ₽",
            callback_data=f"book_svc_{s['id']}"
        )])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="book_cancel")])

    await update.message.reply_text(
        "🧾 <b>Шаг 1/6 — Выберите услугу:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return BOOK_SERVICE


async def book_service_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "book_cancel":
        await query.edit_message_text("❌ Запись отменена.")
        return ConversationHandler.END

    service_id = int(query.data.split("_")[-1])
    context.user_data["book_service_id"] = service_id

    with get_db() as db:
        service = db.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
        context.user_data["book_service_duration"] = service["duration"]
        barbers = db.execute("SELECT * FROM barbers ORDER BY name").fetchall()

    if not barbers:
        await query.edit_message_text("😔 Барберов пока нет. Попробуйте позже.")
        return ConversationHandler.END

    buttons = []
    for b in barbers:
        buttons.append([InlineKeyboardButton(f"👤 {b['name']}", callback_data=f"book_barber_{b['id']}")])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="book_cancel")])

    await query.edit_message_text(
        "👤 <b>Шаг 2/6 — Выберите барбера:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return BOOK_BARBER


async def book_barber_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "book_cancel":
        await query.edit_message_text("❌ Запись отменена.")
        return ConversationHandler.END

    barber_id = int(query.data.split("_")[-1])
    context.user_data["book_barber_id"] = barber_id

    days = next_7_days()
    buttons = []
    for date_str, label in days:
        buttons.append([InlineKeyboardButton(f"📅 {label}", callback_data=f"book_date_{date_str}")])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="book_cancel")])

    await query.edit_message_text(
        "📅 <b>Шаг 3/6 — Выберите дату:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return BOOK_DATE


async def book_date_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "book_cancel":
        await query.edit_message_text("❌ Запись отменена.")
        return ConversationHandler.END

    date_str = query.data.replace("book_date_", "")
    context.user_data["book_date"] = date_str

    barber_id = context.user_data["book_barber_id"]
    duration = context.user_data.get("book_service_duration", 30)
    free = get_free_slots(barber_id, date_str, duration)

    if not free:
        await query.edit_message_text(
            "😔 На эту дату нет свободных слотов.\nПопробуйте другую дату.",
        )
        # Re-show date picker
        days = next_7_days()
        buttons = []
        for ds, label in days:
            buttons.append([InlineKeyboardButton(f"📅 {label}", callback_data=f"book_date_{ds}")])
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="book_cancel")])
        await query.message.reply_text(
            "📅 <b>Выберите другую дату:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return BOOK_DATE

    buttons = []
    row = []
    for i, slot in enumerate(free):
        row.append(InlineKeyboardButton(f"⏰ {slot}", callback_data=f"book_time_{slot}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="book_cancel")])

    await query.edit_message_text(
        "⏰ <b>Шаг 4/6 — Выберите время:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return BOOK_TIME


async def book_time_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "book_cancel":
        await query.edit_message_text("❌ Запись отменена.")
        return ConversationHandler.END

    time_str = query.data.replace("book_time_", "")
    context.user_data["book_time"] = time_str

    await query.edit_message_text(
        "🧑 <b>Шаг 5/6 — Введите ваше имя:</b>",
        parse_mode="HTML",
    )
    return BOOK_NAME


async def book_name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text("⚠️ Введите корректное имя (2–50 символов).")
        return BOOK_NAME
    context.user_data["book_name"] = name

    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📲 Отправить номер", request_contact=True)],
         ["❌ Отмена"]],
        resize_keyboard=True, one_time_keyboard=True,
    )
    await update.message.reply_text(
        "📞 <b>Шаг 6/6 — Отправьте номер телефона</b>\n\n"
        "Нажмите кнопку ниже или введите вручную:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return BOOK_PHONE


async def book_phone_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    elif update.message.text:
        if update.message.text == "❌ Отмена":
            await update.message.reply_text(
                "❌ Запись отменена.",
                reply_markup=main_menu_keyboard(update.effective_user.id),
            )
            return ConversationHandler.END
        phone = update.message.text.strip()
        if not re.match(r"^[\d\+\-\(\) ]{7,20}$", phone):
            await update.message.reply_text("⚠️ Введите корректный номер телефона.")
            return BOOK_PHONE
    else:
        await update.message.reply_text("⚠️ Отправьте номер телефона.")
        return BOOK_PHONE

    context.user_data["book_phone"] = phone

    # Show confirmation
    ud = context.user_data
    with get_db() as db:
        service = db.execute("SELECT * FROM services WHERE id=?", (ud["book_service_id"],)).fetchone()
        barber = db.execute("SELECT * FROM barbers WHERE id=?", (ud["book_barber_id"],)).fetchone()

    d = datetime.strptime(ud["book_date"], "%Y-%m-%d")
    date_label = f"{WEEKDAYS_RU[d.weekday()]} {d.day} {MONTHS_RU[d.month]}"

    text = (
        "📋 <b>Подтвердите запись:</b>\n\n"
        f"💈 <b>Услуга:</b> {service['name']}\n"
        f"👤 <b>Барбер:</b> {barber['name']}\n"
        f"📅 <b>Дата:</b> {date_label}\n"
        f"⏰ <b>Время:</b> {ud['book_time']}\n"
        f"🧑 <b>Имя:</b> {ud['book_name']}\n"
        f"📞 <b>Телефон:</b> {phone}\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data="book_confirm_yes"),
         InlineKeyboardButton("❌ Отмена", callback_data="book_confirm_no")],
    ])
    await update.message.reply_text(
        text, parse_mode="HTML", reply_markup=keyboard,
    )
    # Restore main menu keyboard
    await update.message.reply_text(
        "⬆️ Подтвердите запись выше",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
    return BOOK_CONFIRM


async def book_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "book_confirm_no":
        await query.edit_message_text("❌ Запись отменена.")
        return ConversationHandler.END

    ud = context.user_data
    user_id = update.effective_user.id

    # Try to insert booking (unique constraint protects double booking)
    try:
        with get_db() as db:
            db.execute(
                """INSERT INTO bookings(user_id, service_id, barber_id, date, time,
                   client_name, client_phone)
                   VALUES(?,?,?,?,?,?,?)""",
                (user_id, ud["book_service_id"], ud["book_barber_id"],
                 ud["book_date"], ud["book_time"], ud["book_name"], ud["book_phone"]),
            )
            booking_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            # Update user phone
            db.execute("UPDATE users SET phone=? WHERE user_id=?", (ud["book_phone"], user_id))
    except sqlite3.IntegrityError:
        await query.edit_message_text(
            "⚠️ Это время уже занято! Попробуйте другое время.",
        )
        return ConversationHandler.END

    # Send confirmation to client
    with get_db() as db:
        booking = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()

    cancel_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel_booking_{booking_id}")],
    ])
    await query.edit_message_text(
        f"✅ <b>Запись оформлена!</b>\n\n{format_booking(booking)}",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )

    # Notify admins
    admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"adm_confirm_{booking_id}"),
         InlineKeyboardButton("🔁 Перенести", callback_data=f"adm_reschedule_{booking_id}"),
         InlineKeyboardButton("❌ Отменить", callback_data=f"adm_cancel_{booking_id}")],
    ])
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"📩 <b>Новая запись!</b>\n\n{format_booking(booking)}\n\n"
                f"👤 User ID: {user_id} (@{update.effective_user.username or '—'})",
                parse_mode="HTML",
                reply_markup=admin_kb,
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

    # Clean up user_data
    for key in list(ud.keys()):
        if key.startswith("book_"):
            del ud[key]

    return ConversationHandler.END


async def book_cancel_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text '❌ Отмена' during booking."""
    await update.message.reply_text(
        "❌ Запись отменена.",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
    return ConversationHandler.END


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MY BOOKINGS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as db:
        bookings = db.execute(
            """SELECT * FROM bookings
               WHERE user_id=? AND status='confirmed' AND date>=?
               ORDER BY date, time""",
            (user_id, today),
        ).fetchall()

    if not bookings:
        await update.message.reply_text("📋 У вас нет предстоящих записей.")
        return

    for b in bookings:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_booking_{b['id']}"),
             InlineKeyboardButton("🔁 Перенести", callback_data=f"reschedule_{b['id']}")],
        ])
        await update.message.reply_text(
            format_booking(b), parse_mode="HTML", reply_markup=kb,
        )


# ─── Cancel / Reschedule callbacks ──────────────────────────────────
async def cancel_booking_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[-1])
    user_id = update.effective_user.id

    with get_db() as db:
        booking = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not booking:
            await query.edit_message_text("⚠️ Запись не найдена.")
            return
        if booking["user_id"] != user_id and not is_admin(user_id):
            await query.edit_message_text("⚠️ Нет прав для отмены.")
            return
        db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))

    await query.edit_message_text(f"❌ Запись #{booking_id} отменена.")

    # Notify client if admin cancelled
    if is_admin(user_id) and booking["user_id"] != user_id:
        try:
            await context.bot.send_message(
                booking["user_id"],
                f"❌ <b>Ваша запись #{booking_id} была отменена администратором.</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def reschedule_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[-1])

    with get_db() as db:
        booking = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking or booking["status"] != "confirmed":
        await query.edit_message_text("⚠️ Запись не найдена или уже отменена.")
        return ConversationHandler.END

    context.user_data["reschedule_id"] = booking_id
    context.user_data["reschedule_barber_id"] = booking["barber_id"]
    context.user_data["reschedule_service_id"] = booking["service_id"]

    with get_db() as db:
        service = db.execute("SELECT duration FROM services WHERE id=?", (booking["service_id"],)).fetchone()
    context.user_data["reschedule_duration"] = service["duration"] if service else 30

    days = next_7_days()
    buttons = []
    for ds, label in days:
        buttons.append([InlineKeyboardButton(f"📅 {label}", callback_data=f"resc_date_{ds}")])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="resc_cancel")])

    await query.edit_message_text(
        "🔁 <b>Перенос записи — выберите новую дату:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return RESCHEDULE_DATE


async def reschedule_date_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "resc_cancel":
        await query.edit_message_text("❌ Перенос отменён.")
        return ConversationHandler.END

    date_str = query.data.replace("resc_date_", "")
    context.user_data["reschedule_date"] = date_str

    barber_id = context.user_data["reschedule_barber_id"]
    duration = context.user_data.get("reschedule_duration", 30)
    free = get_free_slots(barber_id, date_str, duration)

    if not free:
        await query.edit_message_text("😔 Нет свободного времени на эту дату. Попробуйте другую.")
        return RESCHEDULE_DATE

    buttons = []
    row = []
    for slot in free:
        row.append(InlineKeyboardButton(f"⏰ {slot}", callback_data=f"resc_time_{slot}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="resc_cancel")])

    await query.edit_message_text(
        "⏰ <b>Выберите новое время:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return RESCHEDULE_TIME


async def reschedule_time_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "resc_cancel":
        await query.edit_message_text("❌ Перенос отменён.")
        return ConversationHandler.END

    time_str = query.data.replace("resc_time_", "")
    booking_id = context.user_data["reschedule_id"]
    new_date = context.user_data["reschedule_date"]

    try:
        with get_db() as db:
            db.execute(
                "UPDATE bookings SET date=?, time=? WHERE id=?",
                (new_date, time_str, booking_id),
            )
            booking = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    except sqlite3.IntegrityError:
        await query.edit_message_text("⚠️ Это время уже занято!")
        return ConversationHandler.END

    await query.edit_message_text(
        f"✅ <b>Запись #{booking_id} перенесена!</b>\n\n{format_booking(booking)}",
        parse_mode="HTML",
    )

    # Notify client
    if booking["user_id"] != update.effective_user.id:
        try:
            await context.bot.send_message(
                booking["user_id"],
                f"🔁 <b>Ваша запись #{booking_id} перенесена:</b>\n\n{format_booking(booking)}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    return ConversationHandler.END


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REVIEWS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def reviews_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Оставить отзыв", callback_data="review_write")],
        [InlineKeyboardButton("📖 Посмотреть отзывы", callback_data="review_read")],
    ])
    await update.message.reply_text("⭐ <b>Отзывы</b>", parse_mode="HTML", reply_markup=kb)


async def review_read_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    with get_db() as db:
        reviews = db.execute(
            "SELECT r.*, u.full_name FROM reviews r LEFT JOIN users u ON u.user_id=r.user_id "
            "WHERE r.status='published' ORDER BY r.created_at DESC LIMIT 10"
        ).fetchall()
    if not reviews:
        await query.edit_message_text("📖 Отзывов пока нет.")
        return
    lines = ["⭐ <b>Последние отзывы:</b>\n"]
    for r in reviews:
        lines.append(f"👤 <b>{r['full_name'] or 'Аноним'}</b>\n💬 {r['text']}\n")
    await query.edit_message_text("\n".join(lines), parse_mode="HTML")


async def review_write_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✍️ Напишите ваш отзыв (текстом):")
    return REVIEW_TEXT


async def review_text_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 5:
        await update.message.reply_text("⚠️ Слишком короткий отзыв. Напишите подробнее.")
        return REVIEW_TEXT

    user_id = update.effective_user.id
    with get_db() as db:
        db.execute(
            "INSERT INTO reviews(user_id, text) VALUES(?,?)", (user_id, text)
        )
        review_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    await update.message.reply_text(
        "✅ Спасибо за отзыв! Он будет опубликован после модерации.",
        reply_markup=main_menu_keyboard(user_id),
    )

    # Notify admins
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Опубликовать", callback_data=f"rev_publish_{review_id}"),
         InlineKeyboardButton("❌ Удалить", callback_data=f"rev_delete_{review_id}")],
    ])
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"📩 <b>Новый отзыв</b>\n\n"
                f"👤 {update.effective_user.full_name} (@{update.effective_user.username or '—'})\n"
                f"💬 {text}",
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception:
            pass

    return ConversationHandler.END


async def review_moderate_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    parts = query.data.split("_")
    action = parts[1]  # publish or delete
    review_id = int(parts[2])

    if action == "publish":
        with get_db() as db:
            db.execute("UPDATE reviews SET status='published' WHERE id=?", (review_id,))
        await query.edit_message_text(f"✅ Отзыв #{review_id} опубликован.")
    else:
        with get_db() as db:
            db.execute("UPDATE reviews SET status='deleted' WHERE id=?", (review_id,))
        await query.edit_message_text(f"❌ Отзыв #{review_id} удалён.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADMIN PANEL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Барберы", callback_data="adm_barbers"),
         InlineKeyboardButton("🧾 Услуги", callback_data="adm_services")],
        [InlineKeyboardButton("🕒 График", callback_data="adm_schedule"),
         InlineKeyboardButton("📅 Записи", callback_data="adm_bookings")],
        [InlineKeyboardButton("📊 Статистика", callback_data="adm_stats")],
    ])
    await update.message.reply_text(
        "👑 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=kb,
    )


# ─── BARBERS ADMIN ───────────────────────────────────────────────────
async def adm_barbers_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    with get_db() as db:
        barbers = db.execute("SELECT * FROM barbers ORDER BY name").fetchall()

    text = "👥 <b>Барберы:</b>\n\n"
    if barbers:
        for b in barbers:
            text += f"• {b['name']} (ID: {b['id']})\n"
    else:
        text += "Список пуст.\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить", callback_data="adm_barber_add")],
        [InlineKeyboardButton("✏️ Переименовать", callback_data="adm_barber_rename"),
         InlineKeyboardButton("🗑 Удалить", callback_data="adm_barber_delete")],
        [InlineKeyboardButton("◀️ Назад", callback_data="adm_back")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def adm_barber_add_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👤 Введите имя нового барбера:")
    return ADMIN_ADD_BARBER_NAME


async def adm_barber_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("⚠️ Слишком короткое имя.")
        return ADMIN_ADD_BARBER_NAME
    try:
        with get_db() as db:
            db.execute("INSERT INTO barbers(name) VALUES(?)", (name,))
        await update.message.reply_text(
            f"✅ Барбер «{name}» добавлен!",
            reply_markup=main_menu_keyboard(update.effective_user.id),
        )
    except sqlite3.IntegrityError:
        await update.message.reply_text("⚠️ Барбер с таким именем уже есть.")
    return ConversationHandler.END


async def adm_barber_delete_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    with get_db() as db:
        barbers = db.execute("SELECT * FROM barbers ORDER BY name").fetchall()
    if not barbers:
        await query.edit_message_text("Список барберов пуст.")
        return
    buttons = [[InlineKeyboardButton(f"🗑 {b['name']}", callback_data=f"adm_barber_del_{b['id']}")]
               for b in barbers]
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="adm_barbers")])
    await query.edit_message_text(
        "🗑 Выберите барбера для удаления:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def adm_barber_del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    barber_id = int(query.data.split("_")[-1])
    with get_db() as db:
        db.execute("DELETE FROM barbers WHERE id=?", (barber_id,))
    await query.edit_message_text("✅ Барбер удалён.")


async def adm_barber_rename_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    with get_db() as db:
        barbers = db.execute("SELECT * FROM barbers ORDER BY name").fetchall()
    if not barbers:
        await query.edit_message_text("Список барберов пуст.")
        return ConversationHandler.END
    buttons = [[InlineKeyboardButton(f"✏️ {b['name']}", callback_data=f"adm_barber_ren_{b['id']}")]
               for b in barbers]
    await query.edit_message_text(
        "✏️ Выберите барбера для переименования:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ADMIN_RENAME_BARBER_NEW


async def adm_barber_ren_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    barber_id = int(query.data.split("_")[-1])
    context.user_data["rename_barber_id"] = barber_id
    await query.edit_message_text("✏️ Введите новое имя барбера:")
    return ADMIN_RENAME_BARBER_NEW


async def adm_barber_ren_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    barber_id = context.user_data.get("rename_barber_id")
    if not barber_id:
        await update.message.reply_text("⚠️ Ошибка. Попробуйте снова.")
        return ConversationHandler.END
    with get_db() as db:
        db.execute("UPDATE barbers SET name=? WHERE id=?", (name, barber_id))
    await update.message.reply_text(
        f"✅ Барбер переименован в «{name}».",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
    return ConversationHandler.END


# ─── SERVICES ADMIN ─────────────────────────────────────────────────
async def adm_services_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    with get_db() as db:
        services = db.execute("SELECT * FROM services ORDER BY id").fetchall()

    text = "🧾 <b>Услуги:</b>\n\n"
    if services:
        for s in services:
            text += f"{s['emoji']} <b>{s['name']}</b> — {s['price']} ₽, {s['duration']} мин (ID:{s['id']})\n"
    else:
        text += "Список пуст.\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить", callback_data="adm_svc_add")],
        [InlineKeyboardButton("✏️ Изменить", callback_data="adm_svc_edit"),
         InlineKeyboardButton("🗑 Удалить", callback_data="adm_svc_delete")],
        [InlineKeyboardButton("◀️ Назад", callback_data="adm_back")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def adm_svc_add_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🧾 Введите название новой услуги:")
    return ADMIN_ADD_SERVICE_NAME


async def adm_svc_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_svc_name"] = update.message.text.strip()
    await update.message.reply_text("💰 Введите цену (число):")
    return ADMIN_ADD_SERVICE_PRICE


async def adm_svc_add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
        assert price >= 0
    except (ValueError, AssertionError):
        await update.message.reply_text("⚠️ Введите корректную цену (целое число).")
        return ADMIN_ADD_SERVICE_PRICE
    context.user_data["new_svc_price"] = price
    await update.message.reply_text("⏱ Введите длительность в минутах (например 30):")
    return ADMIN_ADD_SERVICE_DURATION


async def adm_svc_add_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dur = int(update.message.text.strip())
        assert 5 <= dur <= 300
    except (ValueError, AssertionError):
        await update.message.reply_text("⚠️ Введите корректную длительность (5–300 минут).")
        return ADMIN_ADD_SERVICE_DURATION

    name = context.user_data["new_svc_name"]
    price = context.user_data["new_svc_price"]
    with get_db() as db:
        db.execute(
            "INSERT INTO services(name, price, duration) VALUES(?,?,?)",
            (name, price, dur),
        )
    await update.message.reply_text(
        f"✅ Услуга «{name}» добавлена! ({price} ₽, {dur} мин)",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
    return ConversationHandler.END


async def adm_svc_delete_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    with get_db() as db:
        services = db.execute("SELECT * FROM services ORDER BY id").fetchall()
    if not services:
        await query.edit_message_text("Список услуг пуст.")
        return
    buttons = [[InlineKeyboardButton(f"🗑 {s['name']}", callback_data=f"adm_svc_del_{s['id']}")]
               for s in services]
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="adm_services")])
    await query.edit_message_text("🗑 Выберите услугу для удаления:", reply_markup=InlineKeyboardMarkup(buttons))


async def adm_svc_del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    svc_id = int(query.data.split("_")[-1])
    with get_db() as db:
        db.execute("DELETE FROM services WHERE id=?", (svc_id,))
    await query.edit_message_text("✅ Услуга удалена.")


async def adm_svc_edit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    with get_db() as db:
        services = db.execute("SELECT * FROM services ORDER BY id").fetchall()
    if not services:
        await query.edit_message_text("Список услуг пуст.")
        return ConversationHandler.END
    buttons = [[InlineKeyboardButton(f"✏️ {s['name']}", callback_data=f"adm_svc_ed_{s['id']}")]
               for s in services]
    await query.edit_message_text("✏️ Выберите услугу:", reply_markup=InlineKeyboardMarkup(buttons))
    return ADMIN_EDIT_SERVICE_FIELD


async def adm_svc_ed_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    svc_id = int(query.data.split("_")[-1])
    context.user_data["edit_svc_id"] = svc_id

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Название", callback_data="adm_svc_ef_name"),
         InlineKeyboardButton("💰 Цена", callback_data="adm_svc_ef_price"),
         InlineKeyboardButton("⏱ Длительность", callback_data="adm_svc_ef_duration")],
    ])
    await query.edit_message_text("Что изменить?", reply_markup=kb)
    return ADMIN_EDIT_SERVICE_FIELD


async def adm_svc_ef_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("adm_svc_ef_", "")
    context.user_data["edit_svc_field"] = field
    labels = {"name": "название", "price": "цену", "duration": "длительность (мин)"}
    await query.edit_message_text(f"Введите новое {labels.get(field, field)}:")
    return ADMIN_EDIT_SERVICE_VALUE


async def adm_svc_ev_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("edit_svc_field")
    svc_id = context.user_data.get("edit_svc_id")
    value = update.message.text.strip()

    if field in ("price", "duration"):
        try:
            value = int(value)
            assert value > 0
        except (ValueError, AssertionError):
            await update.message.reply_text("⚠️ Введите положительное число.")
            return ADMIN_EDIT_SERVICE_VALUE

    with get_db() as db:
        db.execute(f"UPDATE services SET {field}=? WHERE id=?", (value, svc_id))
    await update.message.reply_text(
        f"✅ Услуга обновлена!",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
    return ConversationHandler.END


# ─── SCHEDULE ADMIN ──────────────────────────────────────────────────
async def adm_schedule_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    ws = get_setting("work_start")
    we = get_setting("work_end")
    slot = get_setting("slot_minutes")

    text = (
        f"🕒 <b>Текущий график:</b>\n\n"
        f"🏁 Начало: {ws}\n"
        f"🏁 Конец: {we}\n"
        f"⏱ Шаг слота: {slot} мин"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏁 Время начала", callback_data="adm_sch_start"),
         InlineKeyboardButton("🏁 Время конца", callback_data="adm_sch_end")],
        [InlineKeyboardButton("⏱ Шаг слота", callback_data="adm_sch_slot")],
        [InlineKeyboardButton("◀️ Назад", callback_data="adm_back")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def adm_sch_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🏁 Введите время начала работы (например 09:00):")
    return ADMIN_SCHEDULE_START


async def adm_sch_start_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", val):
        await update.message.reply_text("⚠️ Формат: ЧЧ:ММ")
        return ADMIN_SCHEDULE_START
    set_setting("work_start", val)
    await update.message.reply_text(
        f"✅ Время начала: {val}",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
    return ConversationHandler.END


async def adm_sch_end_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🏁 Введите время окончания работы (например 20:00):")
    return ADMIN_SCHEDULE_END


async def adm_sch_end_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", val):
        await update.message.reply_text("⚠️ Формат: ЧЧ:ММ")
        return ADMIN_SCHEDULE_END
    set_setting("work_end", val)
    await update.message.reply_text(
        f"✅ Время окончания: {val}",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
    return ConversationHandler.END


async def adm_sch_slot_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("30 мин", callback_data="adm_sch_slot_30"),
         InlineKeyboardButton("45 мин", callback_data="adm_sch_slot_45"),
         InlineKeyboardButton("60 мин", callback_data="adm_sch_slot_60")],
    ])
    await query.edit_message_text("⏱ Выберите шаг слота:", reply_markup=kb)


async def adm_sch_slot_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.split("_")[-1]
    set_setting("slot_minutes", val)
    await query.edit_message_text(f"✅ Шаг слота: {val} мин")


# ─── BOOKINGS ADMIN ─────────────────────────────────────────────────
async def adm_bookings_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Сегодня", callback_data="adm_book_today"),
         InlineKeyboardButton("📆 Завтра", callback_data="adm_book_tomorrow")],
        [InlineKeyboardButton("🗂 Все", callback_data="adm_book_all"),
         InlineKeyboardButton("👤 По барберу", callback_data="adm_book_barber")],
        [InlineKeyboardButton("◀️ Назад", callback_data="adm_back")],
    ])
    await query.edit_message_text("📅 <b>Записи:</b>", parse_mode="HTML", reply_markup=kb)


async def adm_book_list_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    with get_db() as db:
        if query.data == "adm_book_today":
            bookings = db.execute(
                "SELECT * FROM bookings WHERE date=? AND status='confirmed' ORDER BY time",
                (today,)
            ).fetchall()
            title = "📌 Записи на сегодня"
        elif query.data == "adm_book_tomorrow":
            bookings = db.execute(
                "SELECT * FROM bookings WHERE date=? AND status='confirmed' ORDER BY time",
                (tomorrow,)
            ).fetchall()
            title = "📆 Записи на завтра"
        else:  # all
            bookings = db.execute(
                "SELECT * FROM bookings WHERE date>=? AND status='confirmed' ORDER BY date, time",
                (today,)
            ).fetchall()
            title = "🗂 Все предстоящие записи"

    if not bookings:
        await query.edit_message_text(f"{title}\n\nЗаписей нет 📭")
        return

    text = f"<b>{title}</b> ({len(bookings)})\n\n"
    for b in bookings:
        text += format_booking(b) + "\n\n"
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await query.edit_message_text(text, parse_mode="HTML")


async def adm_book_barber_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    with get_db() as db:
        barbers = db.execute("SELECT * FROM barbers ORDER BY name").fetchall()
    if not barbers:
        await query.edit_message_text("Нет барберов.")
        return

    buttons = [[InlineKeyboardButton(f"👤 {b['name']}", callback_data=f"adm_book_byb_{b['id']}")]
               for b in barbers]
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="adm_bookings")])
    await query.edit_message_text("👤 Выберите барбера:", reply_markup=InlineKeyboardMarkup(buttons))


async def adm_book_by_barber_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    barber_id = int(query.data.split("_")[-1])
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as db:
        barber = db.execute("SELECT * FROM barbers WHERE id=?", (barber_id,)).fetchone()
        bookings = db.execute(
            "SELECT * FROM bookings WHERE barber_id=? AND date>=? AND status='confirmed' ORDER BY date, time",
            (barber_id, today),
        ).fetchall()

    if not bookings:
        await query.edit_message_text(f"👤 {barber['name']}: записей нет 📭")
        return

    text = f"👤 <b>{barber['name']}</b> — записи ({len(bookings)}):\n\n"
    for b in bookings:
        text += format_booking(b) + "\n\n"
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await query.edit_message_text(text, parse_mode="HTML")


# ─── ADMIN CONFIRM / CANCEL / RESCHEDULE from notification ──────────
async def adm_confirm_booking_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    booking_id = int(query.data.split("_")[-1])
    with get_db() as db:
        db.execute("UPDATE bookings SET admin_confirmed=1 WHERE id=?", (booking_id,))
        booking = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    await query.edit_message_text(f"✅ Запись #{booking_id} подтверждена администратором.")
    if booking:
        try:
            await context.bot.send_message(
                booking["user_id"],
                f"✅ <b>Ваша запись #{booking_id} подтверждена администратором!</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def adm_cancel_booking_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    booking_id = int(query.data.split("_")[-1])
    with get_db() as db:
        booking = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    await query.edit_message_text(f"❌ Запись #{booking_id} отменена.")
    if booking:
        try:
            await context.bot.send_message(
                booking["user_id"],
                f"❌ <b>Ваша запись #{booking_id} была отменена администратором.</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def adm_reschedule_booking_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    booking_id = int(query.data.split("_")[-1])

    with get_db() as db:
        booking = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking or booking["status"] != "confirmed":
        await query.edit_message_text("⚠️ Запись не найдена или уже отменена.")
        return ConversationHandler.END

    context.user_data["reschedule_id"] = booking_id
    context.user_data["reschedule_barber_id"] = booking["barber_id"]
    context.user_data["reschedule_service_id"] = booking["service_id"]

    with get_db() as db:
        service = db.execute("SELECT duration FROM services WHERE id=?", (booking["service_id"],)).fetchone()
    context.user_data["reschedule_duration"] = service["duration"] if service else 30

    days = next_7_days()
    buttons = [[InlineKeyboardButton(f"📅 {label}", callback_data=f"resc_date_{ds}")] for ds, label in days]
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="resc_cancel")])

    await query.edit_message_text(
        f"🔁 <b>Перенос записи #{booking_id} — выберите дату:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return RESCHEDULE_DATE


# ─── STATS ───────────────────────────────────────────────────────────
async def adm_stats_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    with get_db() as db:
        # Counts
        today_count = db.execute(
            "SELECT COUNT(*) FROM bookings WHERE date=? AND status='confirmed'", (today,)
        ).fetchone()[0]
        week_count = db.execute(
            "SELECT COUNT(*) FROM bookings WHERE date>=? AND status='confirmed'", (week_ago,)
        ).fetchone()[0]
        month_count = db.execute(
            "SELECT COUNT(*) FROM bookings WHERE date>=? AND status='confirmed'", (month_ago,)
        ).fetchone()[0]
        total = db.execute(
            "SELECT COUNT(*) FROM bookings WHERE status='confirmed'"
        ).fetchone()[0]

        # Top services
        top_services = db.execute("""
            SELECT s.name, COUNT(*) as cnt FROM bookings b
            JOIN services s ON s.id=b.service_id
            WHERE b.status='confirmed'
            GROUP BY b.service_id ORDER BY cnt DESC LIMIT 5
        """).fetchall()

        # Top barbers
        top_barbers = db.execute("""
            SELECT br.name, COUNT(*) as cnt FROM bookings b
            JOIN barbers br ON br.id=b.barber_id
            WHERE b.status='confirmed'
            GROUP BY b.barber_id ORDER BY cnt DESC LIMIT 5
        """).fetchall()

        # Revenue estimates
        revenue_month = db.execute("""
            SELECT COALESCE(SUM(s.price), 0) FROM bookings b
            JOIN services s ON s.id=b.service_id
            WHERE b.date>=? AND b.status='confirmed'
        """, (month_ago,)).fetchone()[0]

    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"📈 <b>Записей:</b>\n"
        f"  • Сегодня: {today_count}\n"
        f"  • За неделю: {week_count}\n"
        f"  • За месяц: {month_count}\n"
        f"  • Всего: {total}\n\n"
        f"💰 <b>Выручка за месяц:</b> ~{revenue_month} ₽\n\n"
    )

    if top_services:
        text += "🏆 <b>Топ услуг:</b>\n"
        for i, s in enumerate(top_services, 1):
            text += f"  {i}. {s['name']} ({s['cnt']})\n"
        text += "\n"

    if top_barbers:
        text += "🏅 <b>Топ барберов:</b>\n"
        for i, b in enumerate(top_barbers, 1):
            text += f"  {i}. {b['name']} ({b['cnt']})\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад", callback_data="adm_back")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def adm_back_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Барберы", callback_data="adm_barbers"),
         InlineKeyboardButton("🧾 Услуги", callback_data="adm_services")],
        [InlineKeyboardButton("🕒 График", callback_data="adm_schedule"),
         InlineKeyboardButton("📅 Записи", callback_data="adm_bookings")],
        [InlineKeyboardButton("📊 Статистика", callback_data="adm_stats")],
    ])
    await query.edit_message_text("👑 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=kb)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REMINDERS (Job Queue)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 10 minutes. Sends reminders for bookings in ~2 hours."""
    now = datetime.now()
    remind_time = now + timedelta(hours=REMINDER_HOURS)
    remind_date = remind_time.strftime("%Y-%m-%d")
    remind_hhmm = remind_time.strftime("%H:%M")

    # Window: remind_time ± 5 minutes
    low = (remind_time - timedelta(minutes=5)).strftime("%H:%M")
    high = (remind_time + timedelta(minutes=5)).strftime("%H:%M")

    with get_db() as db:
        bookings = db.execute(
            """SELECT * FROM bookings
               WHERE date=? AND time>=? AND time<=?
               AND status='confirmed' AND reminded=0""",
            (remind_date, low, high),
        ).fetchall()

        for b in bookings:
            try:
                text = (
                    f"🔔 <b>Напоминание!</b>\n\n"
                    f"Ваша запись через ~{REMINDER_HOURS} ч:\n\n"
                    f"{format_booking(b)}\n\n"
                    f"Ждём вас! 💈"
                )
                await context.bot.send_message(b["user_id"], text, parse_mode="HTML")
                db.execute("UPDATE bookings SET reminded=1 WHERE id=?", (b["id"],))
            except Exception as e:
                logger.error(f"Reminder failed for booking {b['id']}: {e}")
        db.commit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN MESSAGE ROUTER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "💰 Прайс":
        await show_price(update, context)
    elif text == "📍 Контакты":
        await show_contacts(update, context)
    elif text == "📋 Мои записи":
        await my_bookings(update, context)
    elif text == "⭐ Отзывы":
        await reviews_menu(update, context)
    elif text == "⚙️ Настройки":
        await show_settings(update, context)
    elif text == "👑 Админка":
        await admin_menu(update, context)
    else:
        await update.message.reply_text(
            "Выберите действие из меню 👇",
            reply_markup=main_menu_keyboard(update.effective_user.id),
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# APPLICATION SETUP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # ── Booking ConversationHandler ──
    booking_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✍️ Записаться$"), book_start)],
        states={
            BOOK_SERVICE: [CallbackQueryHandler(book_service_chosen, pattern=r"^book_(svc_\d+|cancel)$")],
            BOOK_BARBER: [CallbackQueryHandler(book_barber_chosen, pattern=r"^book_(barber_\d+|cancel)$")],
            BOOK_DATE: [CallbackQueryHandler(book_date_chosen, pattern=r"^book_(date_|cancel)")],
            BOOK_TIME: [CallbackQueryHandler(book_time_chosen, pattern=r"^book_(time_|cancel)")],
            BOOK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Отмена$"), book_name_entered),
                MessageHandler(filters.Regex("^❌ Отмена$"), book_cancel_text),
            ],
            BOOK_PHONE: [
                MessageHandler(filters.CONTACT, book_phone_entered),
                MessageHandler(filters.TEXT & ~filters.COMMAND, book_phone_entered),
            ],
            BOOK_CONFIRM: [CallbackQueryHandler(book_confirm, pattern=r"^book_confirm_")],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.Regex("^❌ Отмена$"), book_cancel_text),
        ],
        allow_reentry=True,
    )

    # ── Review ConversationHandler ──
    review_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(review_write_cb, pattern=r"^review_write$")],
        states={
            REVIEW_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, review_text_entered),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        allow_reentry=True,
    )

    # ── Reschedule ConversationHandler (user + admin) ──
    reschedule_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(reschedule_start_cb, pattern=r"^reschedule_\d+$"),
            CallbackQueryHandler(adm_reschedule_booking_cb, pattern=r"^adm_reschedule_\d+$"),
        ],
        states={
            RESCHEDULE_DATE: [CallbackQueryHandler(reschedule_date_cb, pattern=r"^resc_(date_|cancel)")],
            RESCHEDULE_TIME: [CallbackQueryHandler(reschedule_time_cb, pattern=r"^resc_(time_|cancel)")],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        allow_reentry=True,
        per_message=False,
    )

    # ── Admin barber add ConversationHandler ──
    adm_barber_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_barber_add_cb, pattern=r"^adm_barber_add$")],
        states={
            ADMIN_ADD_BARBER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, adm_barber_add_name),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        allow_reentry=True,
    )

    # ── Admin barber rename ConversationHandler ──
    adm_barber_rename_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_barber_rename_cb, pattern=r"^adm_barber_rename$")],
        states={
            ADMIN_RENAME_BARBER_NEW: [
                CallbackQueryHandler(adm_barber_ren_select, pattern=r"^adm_barber_ren_\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, adm_barber_ren_name),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        allow_reentry=True,
    )

    # ── Admin service add ConversationHandler ──
    adm_svc_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_svc_add_cb, pattern=r"^adm_svc_add$")],
        states={
            ADMIN_ADD_SERVICE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_svc_add_name)],
            ADMIN_ADD_SERVICE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_svc_add_price)],
            ADMIN_ADD_SERVICE_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_svc_add_duration)],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        allow_reentry=True,
    )

    # ── Admin service edit ConversationHandler ──
    adm_svc_edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_svc_edit_cb, pattern=r"^adm_svc_edit$")],
        states={
            ADMIN_EDIT_SERVICE_FIELD: [
                CallbackQueryHandler(adm_svc_ed_select, pattern=r"^adm_svc_ed_\d+$"),
                CallbackQueryHandler(adm_svc_ef_chosen, pattern=r"^adm_svc_ef_"),
            ],
            ADMIN_EDIT_SERVICE_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, adm_svc_ev_entered),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        allow_reentry=True,
    )

    # ── Admin schedule ConversationHandlers ──
    adm_sch_start_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_sch_start_cb, pattern=r"^adm_sch_start$")],
        states={ADMIN_SCHEDULE_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_sch_start_entered)]},
        fallbacks=[CommandHandler("start", cmd_start)],
        allow_reentry=True,
    )
    adm_sch_end_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_sch_end_cb, pattern=r"^adm_sch_end$")],
        states={ADMIN_SCHEDULE_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_sch_end_entered)]},
        fallbacks=[CommandHandler("start", cmd_start)],
        allow_reentry=True,
    )

    # ── Register handlers (ORDER MATTERS!) ──
    app.add_handler(CommandHandler("start", cmd_start))

    # Conversations first (higher priority)
    app.add_handler(booking_conv)
    app.add_handler(review_conv)
    app.add_handler(reschedule_conv)
    app.add_handler(adm_barber_add_conv)
    app.add_handler(adm_barber_rename_conv)
    app.add_handler(adm_svc_add_conv)
    app.add_handler(adm_svc_edit_conv)
    app.add_handler(adm_sch_start_conv)
    app.add_handler(adm_sch_end_conv)

    # Callback queries (non-conversation)
    app.add_handler(CallbackQueryHandler(review_read_cb, pattern=r"^review_read$"))
    app.add_handler(CallbackQueryHandler(review_moderate_cb, pattern=r"^rev_(publish|delete)_\d+$"))
    app.add_handler(CallbackQueryHandler(cancel_booking_cb, pattern=r"^cancel_booking_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_confirm_booking_cb, pattern=r"^adm_confirm_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_cancel_booking_cb, pattern=r"^adm_cancel_\d+$"))

    # Admin panel callbacks
    app.add_handler(CallbackQueryHandler(adm_barbers_cb, pattern=r"^adm_barbers$"))
    app.add_handler(CallbackQueryHandler(adm_barber_delete_cb, pattern=r"^adm_barber_delete$"))
    app.add_handler(CallbackQueryHandler(adm_barber_del_confirm, pattern=r"^adm_barber_del_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_services_cb, pattern=r"^adm_services$"))
    app.add_handler(CallbackQueryHandler(adm_svc_delete_cb, pattern=r"^adm_svc_delete$"))
    app.add_handler(CallbackQueryHandler(adm_svc_del_confirm, pattern=r"^adm_svc_del_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_schedule_cb, pattern=r"^adm_schedule$"))
    app.add_handler(CallbackQueryHandler(adm_sch_slot_cb, pattern=r"^adm_sch_slot$"))
    app.add_handler(CallbackQueryHandler(adm_sch_slot_chosen, pattern=r"^adm_sch_slot_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_bookings_cb, pattern=r"^adm_bookings$"))
    app.add_handler(CallbackQueryHandler(adm_book_list_cb, pattern=r"^adm_book_(today|tomorrow|all)$"))
    app.add_handler(CallbackQueryHandler(adm_book_barber_cb, pattern=r"^adm_book_barber$"))
    app.add_handler(CallbackQueryHandler(adm_book_by_barber_cb, pattern=r"^adm_book_byb_\d+$"))
    app.add_handler(CallbackQueryHandler(adm_stats_cb, pattern=r"^adm_stats$"))
    app.add_handler(CallbackQueryHandler(adm_back_cb, pattern=r"^adm_back$"))

    # Main menu text router (lowest priority)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_router))

    # ── Reminder job ──
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(check_reminders, interval=600, first=10)
        logger.info("Reminder job scheduled (every 10 minutes)")

    # ── Set bot commands ──
    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start", "🏠 Главное меню"),
        ])

    app.post_init = post_init

    logger.info("🚀 Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
