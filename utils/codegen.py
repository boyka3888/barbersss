import random
import string

from db import fetchone



def generate_booking_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(50):
        code = "BZ-" + "".join(random.choice(alphabet) for _ in range(6))
        if not fetchone("SELECT 1 FROM bookings WHERE code=?", (code,)):
            return code
    raise RuntimeError("Cannot generate unique booking code")
