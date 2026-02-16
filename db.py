import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from config import (
    DB_PATH,
    DEFAULT_LANGUAGE,
    DEFAULT_SHOP_NAME,
    DEFAULT_SLOT_STEP,
    DEFAULT_WORK_END,
    DEFAULT_WORK_START,
)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                language TEXT NOT NULL DEFAULT 'ru',
                phone TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS branches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                phone TEXT,
                geo TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS barbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(branch_id) REFERENCES branches(id)
            );

            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price_tjs INTEGER NOT NULL,
                duration_min INTEGER NOT NULL DEFAULT 30,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                barber_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                client_name TEXT NOT NULL,
                client_phone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(branch_id) REFERENCES branches(id),
                FOREIGN KEY(service_id) REFERENCES services(id),
                FOREIGN KEY(barber_id) REFERENCES barbers(id),
                UNIQUE(branch_id, barber_id, date, time)
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                rating INTEGER,
                text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS operators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                prefixes TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                ts INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            """
        )

        defaults = {
            "barbershop_name": DEFAULT_SHOP_NAME,
            "work_start": DEFAULT_WORK_START,
            "work_end": DEFAULT_WORK_END,
            "slot_step": str(DEFAULT_SLOT_STEP),
        }
        for key, value in defaults.items():
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))

        if db.execute("SELECT COUNT(*) c FROM branches").fetchone()["c"] == 0:
            db.execute(
                "INSERT INTO branches(name,address,phone) VALUES(?,?,?)",
                ("Центр", "Душанбе, марказ", "+992900000000"),
            )

        if db.execute("SELECT COUNT(*) c FROM barbers").fetchone()["c"] == 0:
            db.execute("INSERT INTO barbers(branch_id,name) VALUES(1,'Усто Али')")

        if db.execute("SELECT COUNT(*) c FROM services").fetchone()["c"] == 0:
            db.executemany(
                "INSERT INTO services(name,price_tjs,duration_min) VALUES(?,?,?)",
                [("✂️ Стрижка", 80, 30), ("🧔 Борода", 50, 30)],
            )

        if db.execute("SELECT COUNT(*) c FROM operators").fetchone()["c"] == 0:
            db.executemany(
                "INSERT INTO operators(name,prefixes) VALUES(?,?)",
                [
                    ("Tcell", json.dumps(["93", "92", "50"])),
                    ("MegaFon", json.dumps(["88", "90"])),
                    ("Babilon", json.dumps(["91", "98"])),
                    ("ZET-Mobile", json.dumps(["95", "99"])),
                ],
            )


def get_setting(key: str, default: str = "") -> str:
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))


def ensure_user(user_id: int, username: str | None, full_name: str | None) -> None:
    with get_db() as db:
        db.execute(
            """
            INSERT INTO users(user_id, username, full_name, language)
            VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
              username=excluded.username,
              full_name=excluded.full_name
            """,
            (user_id, username or "", full_name or "", DEFAULT_LANGUAGE),
        )


def get_user_language(user_id: int) -> str:
    with get_db() as db:
        row = db.execute("SELECT language FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row["language"] if row and row["language"] else DEFAULT_LANGUAGE


def set_user_language(user_id: int, lang: str) -> None:
    with get_db() as db:
        db.execute("UPDATE users SET language=? WHERE user_id=?", (lang, user_id))


def set_user_phone(user_id: int, phone: str) -> None:
    with get_db() as db:
        db.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, user_id))


def fetchall(query: str, params: tuple[Any, ...] = ()):
    with get_db() as db:
        return db.execute(query, params).fetchall()


def fetchone(query: str, params: tuple[Any, ...] = ()):
    with get_db() as db:
        return db.execute(query, params).fetchone()


def execute(query: str, params: tuple[Any, ...] = ()) -> int:
    with get_db() as db:
        cur = db.execute(query, params)
        return cur.lastrowid


def now_ts() -> int:
    return int(datetime.now().timestamp())
