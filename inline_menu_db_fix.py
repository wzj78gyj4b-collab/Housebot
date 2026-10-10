"""SQLite schema hotfix for Housebot's inline group-settings menu.

Integration:
1. Copy SETTINGS_DEFAULTS, ensure_group_settings_schema, get_settings and
   update_setting into the existing main.py (or import them after adapting DB_FILE).
2. Keep a backup of house_bot.db before restarting the bot.
3. Do not run a second bot process against the same Telegram token.
"""
import sqlite3

# Keep this mapping in sync with the settings buttons in get_group_settings_page1().
SETTINGS_DEFAULTS = {
    "rules": 1,
    "anti_spam": 1,
    "welcome": 1,
    "anti_flood": 0,
    "goodbye": 0,
    "captcha": 1,
    "controls": 1,
    "admin_ping": 1,
    "media": 0,
    "mention": 1,
    "guardian": 0,
    "approval": 0,
    "dellmsg": 1,
    "join_check": 0,
    "captcha_rules": 0,
    "bot_welcome_active": 1,
    "bot_filters_active": 1,
    "bot_commands_active": 1,
}


def ensure_group_settings_schema(conn: sqlite3.Connection) -> None:
    """Add only missing columns; safe to run repeatedly."""
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS group_settings "
        "(chat_id INTEGER PRIMARY KEY)"
    )
    cursor.execute("PRAGMA table_info(group_settings)")
    existing = {row[1] for row in cursor.fetchall()}

    for column, default in SETTINGS_DEFAULTS.items():
        # Column names come only from the constant above, never user input.
        if column not in existing:
            cursor.execute(
                f"ALTER TABLE group_settings ADD COLUMN "
                f"{column} INTEGER NOT NULL DEFAULT {default}"
            )
    conn.commit()


def get_settings(db_file: str, chat_id: int) -> dict:
    conn = sqlite3.connect(db_file)
    try:
        ensure_group_settings_schema(conn)
        columns = ", ".join(SETTINGS_DEFAULTS.keys())
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {columns} FROM group_settings WHERE chat_id = ?",
            (chat_id,),
        )
        row = cursor.fetchone()

        if row is None:
            names = ", ".join(["chat_id", *SETTINGS_DEFAULTS.keys()])
            placeholders = ", ".join(["?"] * (len(SETTINGS_DEFAULTS) + 1))
            values = [chat_id, *SETTINGS_DEFAULTS.values()]
            cursor.execute(
                f"INSERT INTO group_settings ({names}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
            row = tuple(SETTINGS_DEFAULTS.values())

        return {
            key: bool(value)
            for key, value in zip(SETTINGS_DEFAULTS.keys(), row)
        }
    finally:
        conn.close()


def update_setting(db_file: str, chat_id: int, key: str, value: bool) -> None:
    if key not in SETTINGS_DEFAULTS:
        raise ValueError(f"Unknown group setting: {key}")

    conn = sqlite3.connect(db_file)
    try:
        ensure_group_settings_schema(conn)
        names = ", ".join(["chat_id", *SETTINGS_DEFAULTS.keys()])
        placeholders = ", ".join(["?"] * (len(SETTINGS_DEFAULTS) + 1))
        values = [chat_id, *SETTINGS_DEFAULTS.values()]
        conn.execute(
            f"INSERT OR IGNORE INTO group_settings ({names}) VALUES ({placeholders})",
            values,
        )
        conn.execute(
            f"UPDATE group_settings SET {key} = ? WHERE chat_id = ?",
            (int(value), chat_id),
        )
        conn.commit()
    finally:
        conn.close()
