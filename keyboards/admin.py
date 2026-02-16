from telegram import InlineKeyboardButton, InlineKeyboardMarkup



def admin_menu():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏷 Настройки", callback_data="admin:settings")],
            [InlineKeyboardButton("🏢 Филиалы", callback_data="admin:branches")],
            [InlineKeyboardButton("👥 Барберы", callback_data="admin:barbers")],
            [InlineKeyboardButton("🧾 Услуги", callback_data="admin:services")],
            [InlineKeyboardButton("🕒 График", callback_data="admin:schedule")],
            [InlineKeyboardButton("📅 Записи", callback_data="admin:bookings")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin:stats")],
        ]
    )


def booking_admin_actions(code: str):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Подтвердить", callback_data=f"admbook:ok:{code}")],
            [InlineKeyboardButton("🔁 Перенести", callback_data=f"admbook:move:{code}")],
            [InlineKeyboardButton("❌ Отменить", callback_data=f"admbook:cancel:{code}")],
            [InlineKeyboardButton("👁 Показать номер", callback_data=f"admbook:phone:{code}")],
        ]
    )
