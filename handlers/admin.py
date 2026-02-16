from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from config import ADMIN_IDS
from db import execute, fetchall, fetchone, get_setting, set_setting
from keyboards.admin import admin_menu

(
    SET_NAME,
    ADD_BRANCH_NAME,
    ADD_BRANCH_ADDRESS,
    ADD_BARBER_NAME,
    ADD_BARBER_BRANCH,
    ADD_SERVICE_NAME,
    ADD_SERVICE_PRICE,
    ADD_SERVICE_DURATION,
    SET_SCHEDULE_START,
    SET_SCHEDULE_END,
    SET_SCHEDULE_STEP,
) = range(100, 111)



def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def open_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    await update.message.reply_text("👑 Админка", reply_markup=admin_menu())


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not _is_admin(q.from_user.id):
        return ConversationHandler.END

    if q.data == "admin:settings":
        await q.edit_message_text("Введите новое название барбершопа:")
        return SET_NAME
    if q.data == "admin:branches":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Добавить филиал", callback_data="admin:addbranch")]])
        await q.edit_message_text("🏢 Филиалы", reply_markup=kb)
        return ConversationHandler.END
    if q.data == "admin:addbranch":
        await q.edit_message_text("Название филиала:")
        return ADD_BRANCH_NAME
    if q.data == "admin:barbers":
        await q.edit_message_text("Введите имя барбера:")
        return ADD_BARBER_NAME
    if q.data == "admin:services":
        await q.edit_message_text("Название услуги:")
        return ADD_SERVICE_NAME
    if q.data == "admin:schedule":
        await q.edit_message_text("Начало рабочего времени (HH:MM):")
        return SET_SCHEDULE_START

    if q.data.startswith("admbook:"):
        _, action, code = q.data.split(":")
        if action == "ok":
            execute("UPDATE bookings SET status='confirmed' WHERE code=?", (code,))
            await q.edit_message_text(f"✅ {code} подтверждено")
        elif action == "cancel":
            execute("UPDATE bookings SET status='cancelled' WHERE code=?", (code,))
            await q.edit_message_text(f"❌ {code} отменено")
        elif action == "phone":
            row = fetchone("SELECT client_phone FROM bookings WHERE code=?", (code,))
            if row:
                await q.message.reply_text(f"📞 {row['client_phone']}")
        elif action == "move":
            await q.message.reply_text("🔁 Перенос через карточку клиента в 'Мои записи'")
        return ConversationHandler.END

    return ConversationHandler.END


async def set_shop_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return ConversationHandler.END
    set_setting("barbershop_name", update.message.text.strip())
    await update.message.reply_text("✅ Название обновлено")
    return ConversationHandler.END


async def add_branch_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["branch_name"] = update.message.text.strip()
    await update.message.reply_text("Адрес филиала:")
    return ADD_BRANCH_ADDRESS


async def add_branch_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    execute(
        "INSERT INTO branches(name,address,is_active) VALUES(?,?,1)",
        (context.user_data["branch_name"], update.message.text.strip()),
    )
    await update.message.reply_text("✅ Филиал добавлен")
    return ConversationHandler.END


async def add_barber_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["barber_name"] = update.message.text.strip()
    branches = fetchall("SELECT id,name FROM branches WHERE is_active=1")
    txt = "Выберите branch_id и отправьте число:\n" + "\n".join([f"{b['id']}: {b['name']}" for b in branches])
    await update.message.reply_text(txt)
    return ADD_BARBER_BRANCH


async def add_barber_branch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    branch_id = int(update.message.text.strip())
    execute(
        "INSERT INTO barbers(name,branch_id,is_active) VALUES(?,?,1)",
        (context.user_data["barber_name"], branch_id),
    )
    await update.message.reply_text("✅ Барбер добавлен")
    return ConversationHandler.END


async def add_service_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["service_name"] = update.message.text.strip()
    await update.message.reply_text("Цена (TJS):")
    return ADD_SERVICE_PRICE


async def add_service_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["service_price"] = int(update.message.text.strip())
    await update.message.reply_text("Длительность (мин):")
    return ADD_SERVICE_DURATION


async def add_service_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    execute(
        "INSERT INTO services(name,price_tjs,duration_min,is_active) VALUES(?,?,?,1)",
        (
            context.user_data["service_name"],
            context.user_data["service_price"],
            int(update.message.text.strip()),
        ),
    )
    await update.message.reply_text("✅ Услуга добавлена")
    return ConversationHandler.END


async def schedule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["work_start"] = update.message.text.strip()
    await update.message.reply_text("Конец рабочего времени (HH:MM):")
    return SET_SCHEDULE_END


async def schedule_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["work_end"] = update.message.text.strip()
    await update.message.reply_text("Шаг слота (30/45/60):")
    return SET_SCHEDULE_STEP


async def schedule_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_setting("work_start", context.user_data["work_start"])
    set_setting("work_end", context.user_data["work_end"])
    set_setting("slot_step", update.message.text.strip())
    await update.message.reply_text(
        f"✅ График обновлен: {get_setting('work_start')}–{get_setting('work_end')}, шаг {get_setting('slot_step')}"
    )
    return ConversationHandler.END
