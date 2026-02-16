from db import get_setting

TEXTS = {
    "ru": {
        "choose_lang": "Выберите язык / Забонро интихоб кунед:",
        "welcome": "💈 Добро пожаловать в {shop}!",
        "menu_book": "✍️ Записаться",
        "menu_my": "📋 Мои записи",
        "menu_price": "💰 Прайс",
        "menu_branches": "🏢 Филиалы",
        "menu_contacts": "📍 Адрес / Контакты",
        "menu_reviews": "⭐ Отзывы",
        "menu_settings": "⚙️ Настройки",
        "menu_admin": "👑 Админка",
        "select_branch": "🏢 Выберите филиал",
        "select_service": "🧾 Выберите услугу",
        "select_barber": "👤 Выберите барбера",
        "select_date": "📅 Выберите дату",
        "select_time": "⏰ Выберите время",
        "enter_name": "🧑 Введите имя",
        "enter_phone": "📞 Отправьте номер или введите вручную",
        "confirm": "✅ Подтвердить запись?",
        "cancel": "❌ Отменить",
        "reschedule": "🔁 Перенести",
        "booked": "✅ Запись создана",
        "invalid_phone": "Неверный оператор/номер",
        "spam": "🚫 Слишком много действий. Попробуйте позже.",
        "no_data": "Пока пусто",
    },
    "tj": {
        "choose_lang": "Забонро интихоб кунед / Выберите язык:",
        "welcome": "💈 Хуш омадед ба {shop}!",
        "menu_book": "✍️ Сабт шудан",
        "menu_my": "📋 Сабтҳои ман",
        "menu_price": "💰 Нархнома",
        "menu_branches": "🏢 Филиалҳо",
        "menu_contacts": "📍 Суроға / Тамос",
        "menu_reviews": "⭐ Баҳогузорӣ",
        "menu_settings": "⚙️ Танзимот",
        "menu_admin": "👑 Админ",
        "select_branch": "🏢 Филиалро интихоб кунед",
        "select_service": "🧾 Хизматро интихоб кунед",
        "select_barber": "👤 Усторо интихоб кунед",
        "select_date": "📅 Сана",
        "select_time": "⏰ Вақт",
        "enter_name": "🧑 Номро нависед",
        "enter_phone": "📞 Рақамро фиристед ё нависед",
        "confirm": "✅ Сабтро тасдиқ мекунед?",
        "cancel": "❌ Бекор кардан",
        "reschedule": "🔁 Кӯчонидан",
        "booked": "✅ Сабт сохта шуд",
        "invalid_phone": "Оператор/рақам нодуруст аст",
        "spam": "🚫 Амалҳо зиёд шуданд. Баъдтар кӯшиш кунед.",
        "no_data": "Ҳоло холӣ",
    },
}


def tr(lang: str, key: str, **kwargs) -> str:
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, key)
    return text.format(**kwargs)


def shop_name() -> str:
    return get_setting("barbershop_name", "Barber House")
