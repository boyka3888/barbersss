import json
import re

from db import fetchall



def normalize_tj_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("992") and len(digits) == 12:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 10:
        return f"+992{digits[1:]}"
    if len(digits) == 9:
        return f"+992{digits}"
    return None


def detect_operator(normalized_phone: str) -> str | None:
    local = normalized_phone.replace("+992", "")
    prefix2 = local[:2]
    rows = fetchall("SELECT name, prefixes FROM operators")
    for row in rows:
        prefixes = json.loads(row["prefixes"])
        if prefix2 in prefixes:
            return row["name"]
    return None


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 5:
        return "***"
    if digits.startswith("992"):
        digits = digits[3:]
    return f"+992 {digits[:2]} *** ** {digits[-2:]}"
