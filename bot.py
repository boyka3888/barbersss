from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN
from db import init_db
from handlers import admin, booking, common



def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN env var")

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    booking_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^(✍️ Записаться|✍️ Сабт шудан)$"), booking.start_booking)],
        states={
            booking.BRANCH: [CallbackQueryHandler(booking.pick_branch, pattern=r"^book:(branch|cancel)")],
            booking.SERVICE: [CallbackQueryHandler(booking.pick_service, pattern=r"^book:(service|cancel)")],
            booking.BARBER: [CallbackQueryHandler(booking.pick_barber, pattern=r"^book:(barber|cancel)")],
            booking.DATE: [CallbackQueryHandler(booking.pick_date, pattern=r"^book:(date|cancel)")],
            booking.TIME: [CallbackQueryHandler(booking.pick_time, pattern=r"^book:(time|cancel)")],
            booking.NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, booking.input_name)],
            booking.PHONE: [MessageHandler((filters.CONTACT | filters.TEXT) & ~filters.COMMAND, booking.input_phone)],
            booking.CONFIRM: [CallbackQueryHandler(booking.confirm_booking, pattern=r"^book:(confirm|cancel)")],
        },
        fallbacks=[CommandHandler("cancel", booking.fallback_cancel)],
    )

    admin_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^(👑 Админка|👑 Админ)$"), admin.open_admin),
            CallbackQueryHandler(admin.admin_callback, pattern=r"^admin:|^admbook:"),
        ],
        states={
            admin.SET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.set_shop_name)],
            admin.ADD_BRANCH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.add_branch_name)],
            admin.ADD_BRANCH_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.add_branch_address)],
            admin.ADD_BARBER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.add_barber_name)],
            admin.ADD_BARBER_BRANCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.add_barber_branch)],
            admin.ADD_SERVICE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.add_service_name)],
            admin.ADD_SERVICE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.add_service_price)],
            admin.ADD_SERVICE_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.add_service_duration)],
            admin.SET_SCHEDULE_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.schedule_start)],
            admin.SET_SCHEDULE_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.schedule_end)],
            admin.SET_SCHEDULE_STEP: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.schedule_step)],
        },
        fallbacks=[CommandHandler("cancel", booking.fallback_cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", common.start))
    app.add_handler(MessageHandler(filters.Regex(r"^(🇷🇺 Русский|🇹🇯 Тоҷикӣ)$"), common.select_language))

    app.add_handler(booking_conv)
    app.add_handler(admin_conv)

    app.add_handler(CommandHandler("cancel", booking.cancel_cmd))
    app.add_handler(CommandHandler("bekor", booking.bekor_cmd))

    app.add_handler(MessageHandler(filters.Regex(r"^(📋 Мои записи|📋 Сабтҳои ман)$"), common.show_my_bookings))
    app.add_handler(MessageHandler(filters.Regex(r"^(💰 Прайс|💰 Нархнома)$"), common.show_price))
    app.add_handler(MessageHandler(filters.Regex(r"^(🏢 Филиалы|🏢 Филиалҳо)$"), common.show_branches))
    app.add_handler(MessageHandler(filters.Regex(r"^(📍 Адрес / Контакты|📍 Суроға / Тамос)$"), common.show_contacts))
    app.add_handler(MessageHandler(filters.Regex(r"^(⭐ Отзывы|⭐ Баҳогузорӣ)$"), common.show_reviews))
    app.add_handler(MessageHandler(filters.Regex(r"^(⚙️ Настройки|⚙️ Танзимот)$"), common.show_settings))

    app.add_handler(CallbackQueryHandler(booking.user_cancel_callback, pattern=r"^usercancel:"))
    app.add_handler(CallbackQueryHandler(common.user_reschedule_callback, pattern=r"^userreschedule:"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, common.unknown))

    app.job_queue

    async def set_commands(application: Application):
        await application.bot.set_my_commands(
            [
                BotCommand("start", "Start"),
                BotCommand("cancel", "Cancel booking by code: /cancel BZ-XXXXXX"),
                BotCommand("bekor", "Бекор кардан: /bekor BZ-XXXXXX"),
            ]
        )

    app.post_init = set_commands
    return app
