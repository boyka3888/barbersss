from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from config import ADMIN_IDS, BOOKING_ATTEMPTS_PER_10M, REMINDER_HOURS, ACTIONS_PER_MINUTE
from db import execute, fetchall, fetchone, get_setting, get_user_language, set_user_phone
from keyboards.admin import booking_admin_actions
from keyboards.client import confirm_keyboard, contact_keyboard, main_menu
from utils.anti_spam import is_blocked, touch
from utils.codegen import generate_booking_code
from utils.i18n import shop_name, tr
from utils.phone import detect_operator, mask_phone, normalize_tj_phone

(
    BRANCH,
    SERVICE,
    BARBER,
    DATE,
    TIME,
    NAME,
    PHONE,
    CONFIRM,
) = range(8)



def _day_options() -> list[tuple[str, str]]:
    result = []
    for i in range(7):
        d = datetime.now() + timedelta(days=i)
        result.append((d.strftime("%Y-%m-%d"), d.strftime("%d.%m (%a)")))
    return result



def _free_slots(branch_id: int, barber_id: int, date: str, duration: int) -> list[str]:
    step = int(get_setting("slot_step", "30"))
    start = get_setting("work_start", "10:00")
    end = get_setting("work_end", "20:00")
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    t = sh * 60 + sm
    end_m = eh * 60 + em
    rows = fetchall(
        """
        SELECT b.time, s.duration_min FROM bookings b
        JOIN services s ON s.id=b.service_id
        WHERE b.branch_id=? AND b.barber_id=? AND b.date=? AND b.status IN ('new','confirmed')
        """,
        (branch_id, barber_id, date),
    )
    occupied = []
    for row in rows:
        h, m = map(int, row["time"].split(":"))
        st = h * 60 + m
        occupied.append((st, st + row["duration_min"]))

    slots = []
    while t + duration <= end_m:
        if all((t + duration <= o1 or t >= o2) for o1, o2 in occupied):
            slots.append(f"{t // 60:02d}:{t % 60:02d}")
        t += step

    if date == datetime.now().strftime("%Y-%m-%d"):
        now_m = datetime.now().hour * 60 + datetime.now().minute
        slots = [s for s in slots if int(s[:2]) * 60 + int(s[3:]) > now_m]
    return slots


async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    if is_blocked(user_id, ACTIONS_PER_MINUTE, BOOKING_ATTEMPTS_PER_10M):
        await update.message.reply_text(tr(lang, "spam"))
        return ConversationHandler.END
    touch(user_id, "action")
    touch(user_id, "booking")

    branches = fetchall("SELECT * FROM branches WHERE is_active=1 ORDER BY id")
    kb = [[InlineKeyboardButton(b["name"], callback_data=f"book:branch:{b['id']}")] for b in branches]
    kb.append([InlineKeyboardButton(tr(lang, "cancel"), callback_data="book:cancel")])
    await update.message.reply_text(tr(lang, "select_branch"), reply_markup=InlineKeyboardMarkup(kb))
    return BRANCH


async def pick_branch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = get_user_language(q.from_user.id)
    if q.data == "book:cancel":
        await q.edit_message_text(tr(lang, "cancel"))
        return ConversationHandler.END
    branch_id = int(q.data.split(":")[-1])
    context.user_data["branch_id"] = branch_id

    services = fetchall("SELECT * FROM services WHERE is_active=1")
    kb = [[InlineKeyboardButton(f"{s['name']} — {s['price_tjs']} TJS 💰", callback_data=f"book:service:{s['id']}")] for s in services]
    kb.append([InlineKeyboardButton(tr(lang, "cancel"), callback_data="book:cancel")])
    await q.edit_message_text(tr(lang, "select_service"), reply_markup=InlineKeyboardMarkup(kb))
    return SERVICE


async def pick_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = get_user_language(q.from_user.id)
    if q.data == "book:cancel":
        await q.edit_message_text(tr(lang, "cancel"))
        return ConversationHandler.END
    service_id = int(q.data.split(":")[-1])
    context.user_data["service_id"] = service_id
    branch_id = context.user_data["branch_id"]

    barbers = fetchall("SELECT * FROM barbers WHERE branch_id=? AND is_active=1", (branch_id,))
    kb = [[InlineKeyboardButton(b["name"], callback_data=f"book:barber:{b['id']}")] for b in barbers]
    kb.append([InlineKeyboardButton(tr(lang, "cancel"), callback_data="book:cancel")])
    await q.edit_message_text(tr(lang, "select_barber"), reply_markup=InlineKeyboardMarkup(kb))
    return BARBER


async def pick_barber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = get_user_language(q.from_user.id)
    if q.data == "book:cancel":
        await q.edit_message_text(tr(lang, "cancel"))
        return ConversationHandler.END
    context.user_data["barber_id"] = int(q.data.split(":")[-1])
    days = _day_options()
    kb = [[InlineKeyboardButton(lbl, callback_data=f"book:date:{d}")] for d, lbl in days]
    kb.append([InlineKeyboardButton(tr(lang, "cancel"), callback_data="book:cancel")])
    await q.edit_message_text(tr(lang, "select_date"), reply_markup=InlineKeyboardMarkup(kb))
    return DATE


async def pick_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = get_user_language(q.from_user.id)
    if q.data == "book:cancel":
        await q.edit_message_text(tr(lang, "cancel"))
        return ConversationHandler.END
    date = q.data.split(":")[-1]
    context.user_data["date"] = date

    service = fetchone("SELECT * FROM services WHERE id=?", (context.user_data["service_id"],))
    slots = _free_slots(context.user_data["branch_id"], context.user_data["barber_id"], date, service["duration_min"])
    if not slots:
        await q.edit_message_text(tr(lang, "no_data"))
        return ConversationHandler.END

    kb, row = [], []
    for i, slot in enumerate(slots, 1):
        row.append(InlineKeyboardButton(slot, callback_data=f"book:time:{slot}"))
        if i % 4 == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(tr(lang, "cancel"), callback_data="book:cancel")])
    await q.edit_message_text(tr(lang, "select_time"), reply_markup=InlineKeyboardMarkup(kb))
    return TIME


async def pick_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["time"] = q.data.split(":")[-1]
    lang = get_user_language(q.from_user.id)
    await q.edit_message_text(tr(lang, "enter_name"))
    return NAME


async def input_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["client_name"] = update.message.text.strip()
    lang = get_user_language(update.effective_user.id)
    await update.message.reply_text(tr(lang, "enter_phone"), reply_markup=contact_keyboard(lang))
    return PHONE


async def input_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    raw = update.message.contact.phone_number if update.message.contact else (update.message.text or "")
    normalized = normalize_tj_phone(raw)
    if not normalized or not detect_operator(normalized):
        await update.message.reply_text(tr(lang, "invalid_phone"))
        return PHONE

    context.user_data["client_phone"] = normalized
    set_user_phone(update.effective_user.id, normalized)

    branch = fetchone("SELECT * FROM branches WHERE id=?", (context.user_data["branch_id"],))
    service = fetchone("SELECT * FROM services WHERE id=?", (context.user_data["service_id"],))
    barber = fetchone("SELECT * FROM barbers WHERE id=?", (context.user_data["barber_id"],))

    summary = (
        f"🏢 {branch['name']}\n"
        f"💈 {service['name']} ({service['price_tjs']} TJS)\n"
        f"👤 {barber['name']}\n"
        f"📅 {context.user_data['date']} {context.user_data['time']}\n"
        f"🧑 {context.user_data['client_name']}\n"
    )
    await update.message.reply_text(summary + "\n" + tr(lang, "confirm"), reply_markup=confirm_keyboard(lang))
    return CONFIRM


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = get_user_language(q.from_user.id)
    if q.data.endswith("cancel"):
        await q.edit_message_text(tr(lang, "cancel"))
        return ConversationHandler.END

    code = generate_booking_code()
    data = context.user_data
    try:
        execute(
            """
            INSERT INTO bookings(code,user_id,branch_id,service_id,barber_id,date,time,client_name,client_phone,status)
            VALUES(?,?,?,?,?,?,?,?,?,'new')
            """,
            (
                code,
                q.from_user.id,
                data["branch_id"],
                data["service_id"],
                data["barber_id"],
                data["date"],
                data["time"],
                data["client_name"],
                data["client_phone"],
            ),
        )
    except Exception:
        await q.edit_message_text("Слот уже занят")
        return ConversationHandler.END

    branch = fetchone("SELECT name FROM branches WHERE id=?", (data["branch_id"],))
    service = fetchone("SELECT name FROM services WHERE id=?", (data["service_id"],))
    barber = fetchone("SELECT name FROM barbers WHERE id=?", (data["barber_id"],))

    text = (
        f"{tr(lang, 'booked')}\n"
        f"🆔 {code}\n🏢 {branch['name']}\n💈 {service['name']}\n"
        f"👤 {barber['name']}\n📅 {data['date']}\n⏰ {data['time']}"
    )
    user_kb = InlineKeyboardMarkup([[InlineKeyboardButton(tr(lang, "cancel"), callback_data=f"usercancel:{code}")]])
    await q.edit_message_text(text, reply_markup=user_kb)

    for admin_id in ADMIN_IDS:
        await context.bot.send_message(
            admin_id,
            (
                f"📩 Новая запись\n🆔 {code}\n🏢 {branch['name']}\n💈 {service['name']}\n"
                f"👤 {barber['name']}\n📅 {data['date']} {data['time']}\n"
                f"🧑 {data['client_name']}\n📞 {mask_phone(data['client_phone'])}"
            ),
            reply_markup=booking_admin_actions(code),
        )

    dt = datetime.strptime(f"{data['date']} {data['time']}", "%Y-%m-%d %H:%M") - timedelta(hours=REMINDER_HOURS)
    if dt > datetime.now():
        context.job_queue.run_once(send_reminder, when=dt, data={"user_id": q.from_user.id, "code": code})

    context.user_data.clear()
    return ConversationHandler.END


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    row = fetchone(
        """
        SELECT b.code, b.date, b.time, br.name branch_name, s.name service_name
        FROM bookings b
        JOIN branches br ON br.id=b.branch_id
        JOIN services s ON s.id=b.service_id
        WHERE b.code=? AND b.status IN ('new','confirmed')
        """,
        (data["code"],),
    )
    if row:
        await context.bot.send_message(
            data["user_id"],
            f"⏰ Напоминание: через 2 часа запись\n🆔 {row['code']}\n🏢 {row['branch_name']}\n💈 {row['service_name']}\n📅 {row['date']} {row['time']}",
        )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = (" ".join(context.args) if context.args else "").strip()
    if not code:
        await update.message.reply_text("Использование: /cancel BZ-XXXXXX")
        return
    execute("UPDATE bookings SET status='cancelled' WHERE code=? AND user_id=?", (code, update.effective_user.id))
    await update.message.reply_text(f"❌ {code} отменён")


async def bekor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cancel_cmd(update, context)


async def user_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    code = q.data.split(":", 1)[1]
    execute("UPDATE bookings SET status='cancelled' WHERE code=? AND user_id=?", (code, q.from_user.id))
    await q.edit_message_text(f"❌ {code} отменён")


async def fallback_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    await update.message.reply_text(tr(lang, "cancel"), reply_markup=main_menu(lang, update.effective_user.id))
    return ConversationHandler.END
