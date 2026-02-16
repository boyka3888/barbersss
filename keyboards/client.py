from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from config import ADMIN_IDS
from utils.i18n import tr



def main_menu(lang: str, user_id: int):
    rows = [
        [tr(lang, "menu_book"), tr(lang, "menu_my")],
        [tr(lang, "menu_price"), tr(lang, "menu_branches")],
        [tr(lang, "menu_contacts"), tr(lang, "menu_reviews")],
        [tr(lang, "menu_settings")],
    ]
    if user_id in ADMIN_IDS:
        rows.append([tr(lang, "menu_admin")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)



def language_keyboard():
    return ReplyKeyboardMarkup([["🇷🇺 Русский"], ["🇹🇯 Тоҷикӣ"]], resize_keyboard=True, one_time_keyboard=True)



def confirm_keyboard(lang: str):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(tr(lang, "confirm"), callback_data="book:confirm")],
            [InlineKeyboardButton(tr(lang, "cancel"), callback_data="book:cancel")],
        ]
    )



def contact_keyboard(lang: str):
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📞", request_contact=True)], [tr(lang, "cancel")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
