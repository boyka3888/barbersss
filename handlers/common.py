from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from db import ensure_user, fetchall, get_setting, get_user_language, set_user_language
from keyboards.client import language_keyboard, main_menu
from utils.i18n import shop_name, tr


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username, user.full_name)
    await update.message.reply_text(tr("ru", "choose_lang"), reply_markup=language_keyboard())


async def select_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    lang = "tj" if "Тоҷик" in text else "ru"
    set_user_language(user_id, lang)
    await update.message.reply_text(
        tr(lang, "welcome", shop=shop_name()),
        reply_markup=main_menu(lang, user_id),
    )


async def show_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    services = fetchall("SELECT * FROM services WHERE is_active=1 ORDER BY price_tjs")
    if not services:
        await update.message.reply_text(tr(lang, "no_data"))
        return
    text = "\n".join([f"{s['name']} — {s['price_tjs']} TJS 💰" for s in services])
    await update.message.reply_text(text)


async def show_branches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    rows = fetchall("SELECT * FROM branches WHERE is_active=1")
    if not rows:
        await update.message.reply_text(tr(lang, "no_data"))
        return
    await update.message.reply_text(
        "\n\n".join([f"🏢 {r['name']}\n📍 {r['address']}\n📞 {r['phone'] or '—'}" for r in rows])
    )


async def show_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_branches(update, context)


async def show_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = fetchall("SELECT text FROM reviews ORDER BY id DESC LIMIT 5")
    if not rows:
        await update.message.reply_text("⭐ Пока нет отзывов")
        return
    await update.message.reply_text("\n\n".join([f"⭐ {r['text']}" for r in rows]))


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    await update.message.reply_text(f"🌍 Language: {lang}\n🏷 {shop_name()}")


async def show_my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    rows = fetchall(
        """
        SELECT b.*, br.name branch_name, s.name service_name, ba.name barber_name
        FROM bookings b
        JOIN branches br ON br.id=b.branch_id
        JOIN services s ON s.id=b.service_id
        JOIN barbers ba ON ba.id=b.barber_id
        WHERE b.user_id=?
        ORDER BY b.date DESC, b.time DESC
        LIMIT 10
        """,
        (update.effective_user.id,),
    )
    if not rows:
        await update.message.reply_text(tr(lang, "no_data"))
        return

    for r in rows:
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(tr(lang, "cancel"), callback_data=f"usercancel:{r['code']}")],
                [InlineKeyboardButton(tr(lang, "reschedule"), callback_data=f"userreschedule:{r['code']}")],
            ]
        )
        await update.message.reply_text(
            f"🆔 {r['code']}\n🏢 {r['branch_name']}\n💈 {r['service_name']}\n👤 {r['barber_name']}\n📅 {r['date']}\n⏰ {r['time']}\n✅ {r['status']}",
            reply_markup=kb,
        )


async def user_reschedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Функция переноса: обратитесь администратору", show_alert=True)


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    await update.message.reply_text(tr(lang, "spam"))
