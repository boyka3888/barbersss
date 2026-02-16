import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", "barbershop.db")

REMINDER_HOURS = int(os.getenv("REMINDER_HOURS", "2"))

ACTIONS_PER_MINUTE = int(os.getenv("ACTIONS_PER_MINUTE", "8"))
BOOKING_ATTEMPTS_PER_10M = int(os.getenv("BOOKING_ATTEMPTS_PER_10M", "3"))
TEMP_BLOCK_MINUTES = int(os.getenv("TEMP_BLOCK_MINUTES", "3"))

DEFAULT_SHOP_NAME = "Barber House"
DEFAULT_SLOT_STEP = 30
DEFAULT_WORK_START = "10:00"
DEFAULT_WORK_END = "20:00"

LANGUAGES = ("ru", "tj")
DEFAULT_LANGUAGE = "ru"
