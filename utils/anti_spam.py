from db import execute, fetchone, now_ts



def cleanup(user_id: int):
    cutoff = now_ts() - 3600
    execute("DELETE FROM rate_limits WHERE user_id=? AND ts<?", (user_id, cutoff))


def _count(user_id: int, action: str, seconds: int) -> int:
    row = fetchone(
        "SELECT COUNT(*) c FROM rate_limits WHERE user_id=? AND action=? AND ts>=?",
        (user_id, action, now_ts() - seconds),
    )
    return row["c"] if row else 0


def touch(user_id: int, action: str) -> None:
    execute("INSERT INTO rate_limits(user_id,action,ts) VALUES(?,?,?)", (user_id, action, now_ts()))


def is_blocked(user_id: int, actions_limit: int, booking_limit: int) -> bool:
    cleanup(user_id)
    if _count(user_id, "action", 60) >= actions_limit:
        return True
    if _count(user_id, "booking", 600) >= booking_limit:
        return True
    return False
