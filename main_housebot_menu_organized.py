import asyncio
import logging
import os
import sys
import aiohttp
import sqlite3
import random
import re
from datetime import datetime, timedelta
import urllib.parse as urllib_parse
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, ChatJoinRequest, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from house_ai import process_message

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    sys.exit("Kein TELEGRAM_BOT_TOKEN gefunden!")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# --- SQLITE DATENBANK INITIALISIERUNG ---
DB_FILE = "house_bot.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            rules INTEGER, anti_spam INTEGER, welcome INTEGER, anti_flood INTEGER,
            goodbye INTEGER, captcha INTEGER, controls INTEGER, admin_ping INTEGER,
            media INTEGER, mention INTEGER, guardian INTEGER, approval INTEGER, dellmsg INTEGER,
            join_check INTEGER, captcha_rules INTEGER, bot_welcome_active INTEGER, 
            bot_filters_active INTEGER, bot_commands_active INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workplaces (
            admin_chat_id INTEGER PRIMARY KEY,
            title TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_welcome (
            chat_id INTEGER PRIMARY KEY,
            status INTEGER,
            mode TEXT,
            text TEXT,
            media_url TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id INTEGER PRIMARY KEY,
            rules_text TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS warnings (
            chat_id INTEGER,
            user_id INTEGER,
            count INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS warning_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            admin_name TEXT,
            reason TEXT,
            timestamp TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS known_groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS linked_stations (
            admin_chat_id INTEGER,
            target_chat_id INTEGER,
            PRIMARY KEY (admin_chat_id, target_chat_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS log_channels (
            log_chat_id INTEGER,
            target_chat_id INTEGER,
            log_mod INTEGER DEFAULT 1,
            log_spam INTEGER DEFAULT 1,
            log_joins INTEGER DEFAULT 1,
            PRIMARY KEY (log_chat_id, target_chat_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS username_cache (
            username TEXT PRIMARY KEY,
            user_id INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS german_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote TEXT,
            author TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_activity (
            chat_id INTEGER,
            user_id INTEGER,
            full_name TEXT,
            username TEXT,
            message_count INTEGER DEFAULT 0,
            last_active TEXT,
            joined BOOLEAN DEFAULT 1,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_captchas (
            user_id INTEGER,
            chat_id INTEGER,
            PRIMARY KEY (user_id, chat_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bad_words (
            chat_id INTEGER,
            word TEXT,
            PRIMARY KEY (chat_id, word)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS afk_users (
            chat_id INTEGER,
            user_id INTEGER,
            reason TEXT,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_filters (
            chat_id INTEGER,
            keyword TEXT,
            reply_text TEXT,
            PRIMARY KEY (chat_id, keyword)
        )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM german_quotes")
    if cursor.fetchone()[0] == 0:
        house_quotes = [
            ("Alle lügen.", "Dr. Gregory House"),
            ("Menschliche Dummheit überrascht mich immer wieder aufs Neue. Sie hat einfach keine Grenzen.", "Dr. Gregory House"),
            ("Wenn du die Leute mit der Wahrheit schockierst, erwarten sie wenigstens, dass du ein Clown bist.", "Dr. Gregory House"),
            ("Arroganz ist dann gerechtfertigt, wenn man recht hat.", "Dr. Gregory House"),
            ("Fast jede Diagnose fängt mit einer Lüge an.", "Dr. Gregory House"),
            ("Es ist nicht Lupus. Es ist nie Lupus.", "Dr. Gregory House"),
            ("Die Leute wollen nicht die Wahrheit, sie wollen, dass ihre Illusionen unsterblich bleiben.", "Dr. Gregory House")
        ]
        cursor.executemany("INSERT INTO german_quotes (quote, author) VALUES (?, ?)", house_quotes)
        conn.commit()

    conn.commit()
    conn.close()

init_db()

chat_message_buffers = {}
pending_admin_actions = {}

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


def ensure_group_settings_schema(conn):
    """Fügt fehlende Einstellungsspalten hinzu, ohne vorhandene zu verändern."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY
        )
    """)
    cursor.execute("PRAGMA table_info(group_settings)")
    existing = {row[1] for row in cursor.fetchall()}

    for column, default in SETTINGS_DEFAULTS.items():
        if column not in existing:
            cursor.execute(
                f"ALTER TABLE group_settings "
                f"ADD COLUMN {column} INTEGER NOT NULL DEFAULT {default}"
            )
            existing.add(column)

    conn.commit()


def get_settings(chat_id: int) -> dict:
    conn = sqlite3.connect(DB_FILE)
    try:
        ensure_group_settings_schema(conn)
        cursor = conn.cursor()
        columns = ", ".join(SETTINGS_DEFAULTS.keys())
        cursor.execute(
            f"SELECT {columns} FROM group_settings WHERE chat_id = ?",
            (chat_id,)
        )
        row = cursor.fetchone()

        if row is None:
            names = ", ".join(["chat_id", *SETTINGS_DEFAULTS.keys()])
            placeholders = ", ".join(["?"] * (len(SETTINGS_DEFAULTS) + 1))
            values = [chat_id, *SETTINGS_DEFAULTS.values()]
            cursor.execute(
                f"INSERT INTO group_settings ({names}) VALUES ({placeholders})",
                values
            )
            conn.commit()
            row = tuple(SETTINGS_DEFAULTS.values())

        return {
            key: bool(value)
            for key, value in zip(SETTINGS_DEFAULTS.keys(), row)
        }
    finally:
        conn.close()


def update_setting(chat_id: int, key: str, value: bool):
    if key not in SETTINGS_DEFAULTS:
        raise ValueError(f"Unbekannte Einstellung: {key}")

    # Stellt sicher, dass Schema und Gruppeneintrag existieren.
    get_settings(chat_id)

    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute(
            f"UPDATE group_settings SET {key} = ? WHERE chat_id = ?",
            (int(value), chat_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_welcome_config(chat_id: int) -> dict:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT status, mode, text, media_url FROM group_welcome WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE group_welcome ADD COLUMN media_url TEXT")
        conn.commit()
        cursor.execute("SELECT status, mode, text, media_url FROM group_welcome WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
    conn.close()
    
    if not row:
        default_conf = (1, "ai", "Willkommen Patient {user} auf dieser Station. Reiß dich zusammen.", None)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO group_welcome VALUES (?, ?, ?, ?, ?)", (chat_id, *default_conf))
        conn.commit()
        conn.close()
        row = default_conf
        
    return {"status": bool(row[0]), "mode": row[1], "text": row[2], "media_url": row[3]}

def update_welcome_config(chat_id: int, status: bool = None, mode: str = None, text: str = None, media_url: str = None):
    w = get_welcome_config(chat_id)
    if status is not None: w["status"] = status
    if mode is not None: w["mode"] = mode
    if text is not None: w["text"] = text
    if media_url is not None: w["media_url"] = media_url
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO group_welcome VALUES (?, ?, ?, ?, ?)", (chat_id, int(w["status"]), w["mode"], w["text"], w["media_url"]))
    conn.commit()
    conn.close()

def get_group_rules_text(chat_id: int) -> str:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT rules_text FROM group_rules WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if row: return row[0]
    return "📋 **Gruppenregeln:**\n1. Respektvoller Umgang.\n2. Kein Spam.\n3. Keine unerlaubte Werbung."

def set_group_rules_text(chat_id: int, text: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO group_rules VALUES (?, ?)", (chat_id, text))
    conn.commit()
    conn.close()

def save_group_title(chat_id: int, title: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO known_groups VALUES (?, ?)", (chat_id, title))
    conn.commit()
    conn.close()

def get_known_groups() -> dict:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, title FROM known_groups")
    rows = cursor.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def cache_username(username: str, user_id: int):
    if not username: return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO username_cache VALUES (?, ?)", (username.lower(), user_id))
    conn.commit()
    conn.close()

def get_user_id_by_username(username: str) -> int:
    if not username: return None
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM username_cache WHERE username = ?", (username.lower(),))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_admin_chats_for_group(target_chat_id: int) -> list:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT admin_chat_id FROM linked_stations WHERE target_chat_id = ?", (target_chat_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_target_chats(admin_chat_id: int) -> list:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT target_chat_id FROM linked_stations WHERE admin_chat_id = ?", (admin_chat_id,))
    rows = cursor.fetchall()
    conn.close()
    if rows: return [r[0] for r in rows]
    return [admin_chat_id]

async def send_log(bot: Bot, target_chat_id: int, log_type: str, text: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    col_map = {"mod": "log_mod", "spam": "log_spam", "joins": "log_joins"}
    col = col_map.get(log_type, "log_mod")
    cursor.execute(f"SELECT log_chat_id FROM log_channels WHERE target_chat_id = ? AND {col} = 1", (target_chat_id,))
    rows = cursor.fetchall()
    conn.close()
    for row in rows:
        try: await bot.send_message(row[0], text)
        except Exception: pass

# --- LEVELSYSTEM & RÄNGE ---

def get_rank_details(count: int) -> tuple:
    if count >= 200: return "🏆 Dr. House (Unfehlbarer Diagnostiker)", "[Chefarzt & Genie]"
    elif count >= 100: return "🏥 Chefarzt der Abteilung", "[Leitender Arzt]"
    elif count >= 50: return "👨‍⚕️ Oberarzt", "[Facharzt]"
    elif count >= 20: return "🩺 Assistenzarzt", "[Stationsarzt]"
    elif count >= 5: return "💊 Behandlungspflege", "[Pflegekraft]"
    else: return "🦠 Patient (Quarantänestation)", "[Neuzugang]"

async def record_user_activity(message: Message, chat_id: int, user_id: int, full_name: str, username: str):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT message_count FROM user_activity WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    row = cursor.fetchone()
    old_count = row[0] if row else 0
    new_count = old_count + 1
    
    old_rank, _ = get_rank_details(old_count)
    new_rank, new_tag = get_rank_details(new_count)
    
    if row:
        cursor.execute("UPDATE user_activity SET message_count = ?, last_active = ?, full_name = ?, username = ? WHERE chat_id = ? AND user_id = ?", (new_count, now_str, full_name, username, chat_id, user_id))
    else:
        cursor.execute("INSERT INTO user_activity (chat_id, user_id, full_name, username, message_count, last_active, joined) VALUES (?, ?, ?, ?, 1, ?, 1)", (chat_id, user_id, full_name, username, now_str))
    conn.commit()
    conn.close()
    
    if old_rank != new_rank and new_count in [5, 20, 50, 100, 200]:
        await message.reply(f"🎉 **BEFÖRDERUNG AUF DER STATION!** 🎉\n\nGlückwunsch, **{full_name}**! Neuer Rang: **{new_rank}** (`{new_tag}`)")

def register_new_member_activity(chat_id: int, user_id: int, full_name: str, username: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM user_activity WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO user_activity (chat_id, user_id, full_name, username, message_count, last_active, joined)
            VALUES (?, ?, ?, ?, 0, 'Noch nie', 1)
        ''', (chat_id, user_id, full_name, username))
        conn.commit()
    conn.close()

async def check_weekly_reset():
    while True:
        now = datetime.now()
        if now.weekday() == 0 and now.hour == 0 and now.minute == 1:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM bot_metadata WHERE key = 'last_reset'")
            row = cursor.fetchone()
            today_str = now.strftime("%Y-%m-%d")
            
            if not row or row[0] != today_str:
                cursor.execute("UPDATE user_activity SET message_count = 0")
                cursor.execute("INSERT OR REPLACE INTO bot_metadata (key, value) VALUES ('last_reset', ?)", (today_str,))
                conn.commit()
                logging.info("Wöchentlicher Aktivitäts-Zähler wurde zurückgesetzt (Montag 00:01 Uhr).")
            conn.close()
            await asyncio.sleep(60)
        await asyncio.sleep(30)

last_welcome_msg = {}
waiting_for_input = {}

HELP_TEXT = """
🤖 **HILFE & BEFEHLSÜBERSICHT**

🛡️ **Moderations-Befehle**:
• `/ban <@user/ID>` – Bannt den Nutzer dauerhaft.
• `/unban <@user/ID>` – Hebt einen Ban wieder auf.
• `/kick <@user/ID>` – Wirft den Nutzer aus der Gruppe.
• `/mute <@user/ID> [Zeit]` – Stummschaltung (z.B. `/mute 30m`).
• `/unmute <@user/ID>` – Hebt die Stummschaltung auf.
• `/warn <@user/ID> [Grund]` – Verwarnt einen Nutzer.

🌍 **Nützliche Tools & APIs**:
• `/wetter <Stadt>` – Zeigt echte Live-Wetterdaten.
• `/wiki <Suchbegriff>` – Liefert deutsche Wikipedia-Zusammenfassungen.
• `/zitat` – Spuckt zynische Dr.-House-Zitate aus.
• `/nasa` – Das offizielle NASA-Bild des Tages.
• `/define <Wort>` – Englische Wortdefinition per Dictionary-API.

⚙️ **Setup & Admin-Befehle**:
• `/setworkplace` – Legt den aktuellen Chat als Admin-Raum fest.
• `/link` – Verknüpft die Zielgruppe mit dem Arbeitsraum.
• `/setlog <gruppen_id>` – Verknüpft den Log-Kanal.
• `/send <Nachricht>` – Sendet ein Rundschreiben in verknüpfte Gruppen.
• `/reload` – Aktualisiert Gruppendaten.
• `/addbadword <wort>` – Fügt Schimpfwort hinzu.
• `/delbadword <wort>` – Entfernt Schimpfwort.
"""

def get_private_start_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    b1 = InlineKeyboardButton(text="➕ Bot zu Gruppe hinzufügen", url=f"https://t.me/{bot_username}?startgroup=true")
    b2 = InlineKeyboardButton(text="⚙️ Gruppeneinstellungen verwalten", callback_data="private_group_list")
    b3 = InlineKeyboardButton(text="🔗 Gruppe verknüpfen (Info)", callback_data="private_link_info")
    b4 = InlineKeyboardButton(text="📢 Log-Kanal verknüpfen", callback_data="private_log_info")
    b5 = InlineKeyboardButton(text="❓ Hilfe & Support", callback_data="private_help")
    return InlineKeyboardMarkup(inline_keyboard=[[b1], [b2], [b3], [b4], [b5]])

def get_group_list_keyboard(user_groups: dict) -> InlineKeyboardMarkup:
    keyboard = []
    for chat_id, title in user_groups.items():
        keyboard.append([InlineKeyboardButton(text="👥 " + title, callback_data="select_group_" + str(chat_id))])
    keyboard.append([InlineKeyboardButton(text="🔙 Zurück zum Hauptmenü", callback_data="private_home")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_group_settings_page1(chat_id: int) -> InlineKeyboardMarkup:
    """Übersicht: Kategorien statt einer langen, unübersichtlichen Schalterliste."""
    cid = str(chat_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ Moderation & Sicherheit", callback_data=f"settings_cat_moderation_{cid}")],
        [InlineKeyboardButton(text="👋 Begrüßung & Verabschiedung", callback_data=f"menu_welcome_{cid}")],
        [InlineKeyboardButton(text="🤖 KI & Bot-Funktionen", callback_data=f"settings_cat_bot_{cid}")],
        [InlineKeyboardButton(text="📋 Gruppenregeln", callback_data=f"menu_rules_{cid}")],
        [InlineKeyboardButton(text="📊 Aktivität & Ränge", callback_data=f"settings_cat_activity_{cid}")],
        [InlineKeyboardButton(text="📡 Protokolle & Verknüpfungen", callback_data=f"settings_cat_logs_{cid}")],
        [InlineKeyboardButton(text="🔙 Zurück zur Gruppenwahl", callback_data="private_group_list")]
    ])


def get_settings_category_keyboard(chat_id: int, category: str) -> InlineKeyboardMarkup:
    settings = get_settings(chat_id)
    categories = {
        "moderation": [
            ("anti_spam", "🔗 Anti-Spam / Links"),
            ("anti_flood", "🌊 Anti-Flood"),
            ("captcha", "🧩 Captcha"),
            ("join_check", "🚪 Beitrittsprüfung"),
            ("captcha_rules", "📜 Regeln-Captcha"),
            ("controls", "🎛️ Gruppensteuerung"),
            ("media", "🖼️ Medien"),
            ("mention", "📣 Erwähnungen"),
            ("guardian", "🛡️ Guardian-Schutz"),
            ("approval", "✅ Beitrittsfreigabe"),
            ("dellmsg", "🧹 Nachrichten löschen"),
        ],
        "bot": [
            ("bot_welcome_active", "👋 Bot-Begrüßung"),
            ("bot_filters_active", "🧰 Bot-Filter"),
            ("bot_commands_active", "⚡ Bot-Befehle"),
            ("admin_ping", "🔔 Admin-Hinweise"),
        ],
        "activity": [],
        "logs": [],
    }
    descriptions = {
        "moderation": "🛡️ **Moderation & Sicherheit**\nSchutz- und Gruppenoptionen. Hinweis: Die Wirkung einzelner vorhandener Schalter muss separat geprüft werden.",
        "bot": "🤖 **KI & Bot-Funktionen**\nSteuere die zentralen Bot-Funktionen. KI-Antworten selbst werden in Gruppen durch Erwähnung oder Antwort auf eine Bot-Nachricht ausgelöst.",
        "activity": "📊 **Aktivität & Ränge**\nDer Bot erfasst Nachrichtenaktivität und berechnet Ränge. Der Aktivitätszähler wird wöchentlich zurückgesetzt. Für diesen Bereich sind aktuell keine zusätzlichen Schalter hinterlegt.",
        "logs": "📡 **Protokolle & Verknüpfungen**\nRichte diese Funktionen über die Befehle ein:\n/setlog <gruppen_id> · /setworkplace · /link",
    }
    rows = []
    for key, label in categories.get(category, []):
        status = "✅ Aktiv" if settings.get(key, False) else "❌ Aus"
        rows.append([InlineKeyboardButton(text=f"{label}: {status}", callback_data=f"setting_toggle_{key}_{chat_id}")])
    rows.append([InlineKeyboardButton(text="🔙 Zurück zu den Kategorien", callback_data=f"select_group_{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_rules_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Regeln bearbeiten", callback_data="edit_rules_prompt_" + str(chat_id))],
        [InlineKeyboardButton(text="🔙 Zurück", callback_data="select_group_" + str(chat_id))]
    ])

def get_welcome_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    w = get_welcome_config(chat_id)
    cid = str(chat_id)
    mode_text = "🤖 KI" if w["mode"] == "ai" else "📝 Personalisiert"
    status_text = "✅ An" if w["status"] else "❌ Aus"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Status: {status_text}", callback_data=f"welc_toggle_status_{cid}"),
         InlineKeyboardButton(text=f"Modus: {mode_text}", callback_data=f"welc_toggle_mode_{cid}")],
        [InlineKeyboardButton(text="✏️ Text bearbeiten", callback_data=f"edit_welcome_prompt_{cid}")],
        [InlineKeyboardButton(text="🖼️ Medien-URL setzen", callback_data=f"edit_welcome_media_{cid}")],
        [InlineKeyboardButton(text="🔙 Zurück", callback_data="select_group_" + cid)]
    ])

async def verify_user_admin_in_group(user_id: int, group_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=group_id, user_id=user_id)
        return member.status in ["creator", "administrator"]
    except Exception:
        return False

async def resolve_target(message: Message):
    if message.reply_to_message:
        return message.reply_to_message.from_user.id, message.reply_to_message.from_user.full_name
    args = message.text.split()
    if len(args) > 1:
        identifier = args[1]
        if message.entities:
            for ent in message.entities:
                if ent.type == "text_mention" and ent.user: return ent.user.id, ent.user.full_name
        if identifier.startswith("@"):
            uid = get_user_id_by_username(identifier[1:].lower())
            if uid: return uid, identifier
        elif identifier.isdigit():
            return int(identifier), f"Nutzer {identifier}"
    return None, None

# --- ARBEITSRAUM & /link BEFEHL ---

@dp.message(Command("setworkplace"))
async def cmd_setworkplace(message: Message):
    if not await verify_user_admin_in_group(message.from_user.id, message.chat.id):
        await message.reply("🚫 Du musst Administrator in diesem Chat sein.")
        return
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO workplaces VALUES (?, ?)", (message.chat.id, message.chat.title or "Admin-Raum"))
    conn.commit()
    conn.close()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Arbeitsraum verwalten", callback_data=f"wp_manage_{message.chat.id}")],
        [InlineKeyboardButton(text="🗑️ Arbeitsraum löschen", callback_data=f"wp_delete_{message.chat.id}")]
    ])
    await message.reply(f"✅ **Arbeitsraum erfolgreich festgelegt!**", reply_markup=kb)

@dp.message(Command("link"))
async def cmd_link_station(message: Message):
    if message.chat.type == "private":
        await message.reply("❌ Bitte führe den Befehl `/link` direkt in der Zielgruppe aus.")
        return
        
    if not await verify_user_admin_in_group(message.from_user.id, message.chat.id):
        await message.reply("🚫 Nur Administratoren können verknüpfen.")
        return
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT admin_chat_id, title FROM workplaces ORDER BY rowid DESC LIMIT 1")
    wp = cursor.fetchone()
    
    if not wp:
        conn.close()
        await message.reply("❌ Noch kein Arbeitsraum festgelegt. Nutze `/setworkplace` im Admin-Chat.")
        return
        
    admin_chat_id, wp_title = wp[0], wp[1]
    target_chat_id = message.chat.id
    target_title = message.chat.title or "Unbekannte Gruppe"
    
    cursor.execute("INSERT OR REPLACE INTO known_groups VALUES (?, ?)", (target_chat_id, target_title))
    cursor.execute("INSERT OR IGNORE INTO linked_stations VALUES (?, ?)", (admin_chat_id, target_chat_id))
    conn.commit()
    conn.close()
    
    await message.reply(f"✅ Gruppe erfolgreich mit Arbeitsraum (**{wp_title}**) verknüpft!")

@dp.callback_query(F.data.startswith("wp_manage_"))
async def cb_wp_manage(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data.replace("wp_manage_", ""))
    target_chats = get_target_chats(chat_id)
    text = f"⚙️ **Arbeitsraum-Verwaltung** (`{chat_id}`)\n\nVerknüpfte Zielgruppen: {len(target_chats)}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ Arbeitsraum löschen", callback_data=f"wp_delete_{chat_id}")],
        [InlineKeyboardButton(text="🔙 Schließen", callback_data="private_home")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("wp_delete_"))
async def cb_wp_delete(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data.replace("wp_delete_", ""))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ Ja, löschen", callback_data=f"wp_del_yes_{chat_id}")],
        [InlineKeyboardButton(text="❌ Abbrechen", callback_data=f"wp_manage_{chat_id}")]
    ])
    await callback.message.edit_text("❓ Möchtest du diesen Arbeitsraum wirklich löschen?", reply_markup=kb)

@dp.callback_query(F.data.startswith("wp_del_yes_"))
async def cb_wp_del_yes(callback: CallbackQuery):
    await callback.answer("Gelöscht!", show_alert=True)
    chat_id = int(callback.data.replace("wp_del_yes_", ""))
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM workplaces WHERE admin_chat_id = ?", (chat_id,))
    cursor.execute("DELETE FROM linked_stations WHERE admin_chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("🗑️ Arbeitsraum gelöscht.")

# --- SEPARATE NATIVE API BEFEHLE (Wetter, Wiki, NASA, Zitate, Define) ---

@dp.message(Command("wetter"))
async def cmd_wetter(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Verwendung: `/wetter <Stadt>` (z.B. `/wetter Berlin`)")
        return
    city = args[1].strip()
    url = f"https://wttr.in/{urllib_parse.quote(city)}?format=3"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    await message.reply(f"🌤️ **Wetterbericht für {city}:**\n{text.strip()}")
                else:
                    await message.reply("❌ Konnte keine Wetterdaten abrufen.")
    except Exception as e:
        await message.reply(f"❌ Fehler: {e}")

@dp.message(Command("wiki"))
async def cmd_wiki(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Verwendung: `/wiki <Suchbegriff>`")
        return
    query = args[1].strip()
    url = f"https://de.wikipedia.org/api/rest_v1/page/summary/{urllib_parse.quote(query)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    extract = data.get("extract", "Keine Zusammenfassung gefunden.")
                    title = data.get("title", query)
                    await message.reply(f"📚 **Wikipedia: {title}**\n\n{extract}")
                else:
                    await message.reply("❌ Nichts auf Wikipedia gefunden.")
    except Exception as e:
        await message.reply(f"❌ Fehler: {e}")

@dp.message(Command("zitat"))
async def cmd_zitat(message: Message):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT quote, author FROM german_quotes")
    rows = cursor.fetchall()
    conn.close()
    if rows:
        q, a = random.choice(rows)
        await message.reply(f"„{q}“\n— *{a}*")
    else:
        await message.reply("„Alle lügen.“ — *Dr. Gregory House*")

@dp.message(Command("nasa"))
async def cmd_nasa(message: Message):
    # Öffentlicher NASA APOD API Key (Demo)
    url = "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    title = data.get("title", "NASA Bild")
                    explanation = data.get("explanation", "")[:400] + "..."
                    img_url = data.get("url", "")
                    await message.answer_photo(photo=img_url, caption=f"🌌 **NASA Bild des Tages: {title}**\n\n{explanation}")
                else:
                    await message.reply("❌ Konnte NASA-Daten nicht abrufen.")
    except Exception as e:
        await message.reply(f"❌ Fehler: {e}")

@dp.message(Command("define"))
async def cmd_define(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Verwendung: `/define <word>`")
        return
    word = args[1].strip()
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib_parse.quote(word)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    meaning = data[0]['meanings'][0]['definitions'][0]['definition']
                    await message.reply(f"📖 **Definition ({word}):**\n{meaning}")
                else:
                    await message.reply("❌ Wort nicht gefunden.")
    except Exception as e:
        await message.reply(f"❌ Fehler: {e}")

# --- ADMIN-RAUM & MULTI-GRUPPEN AKTIONEN ---

@dp.message(Command("send"))
async def cmd_send(message: Message, bot: Bot):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Verwendung: `/send <Nachricht>`")
        return
    text_to_send = args[1]
    target_chats = get_target_chats(message.chat.id)
    if not target_chats:
        await message.reply("❌ Kein Chat verknüpft.")
        return
    if len(target_chats) == 1:
        try:
            await bot.send_message(target_chats[0], f"📢 **Nachricht aus Arbeitsraum:**\n\n{text_to_send}")
            await message.reply("✅ Gesendet.")
        except Exception as e:
            await message.reply(f"❌ Fehler: {e}")
    else:
        groups = get_known_groups()
        keyboard = [[InlineKeyboardButton(text=f"👥 {groups.get(tid, tid)}", callback_data=f"sendto_{tid}")] for tid in target_chats]
        pending_admin_actions[message.from_user.id] = {"action": "send", "payload": text_to_send}
        await message.reply("Wähle die Zielgruppe aus:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("sendto_"))
async def cb_sendto(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    target_id = int(callback.data.replace("sendto_", ""))
    user_id = callback.from_user.id
    if user_id not in pending_admin_actions:
        return
    text = pending_admin_actions.pop(user_id)["payload"]
    try:
        await bot.send_message(target_id, f"📢 **Nachricht aus Arbeitsraum:**\n\n{text}")
        await callback.message.edit_text("✅ Erfolgreich gesendet.")
    except Exception as e:
        await callback.message.edit_text(f"❌ Fehler: {e}")

async def execute_admin_moderation(message: Message, bot: Bot, command_type: str):
    tid, tname = await resolve_target(message)
    if not tid:
        await message.reply(f"Wen möchtest du {command_type}n?")
        return
    target_chats = get_target_chats(message.chat.id)
    if not target_chats:
        await message.reply("❌ Keine Gruppe verknüpft.")
        return
    if len(target_chats) == 1:
        await perform_mod_action(bot, message, target_chats[0], tid, tname, command_type)
    else:
        groups = get_known_groups()
        keyboard = [[InlineKeyboardButton(text=f"👥 {groups.get(cid, cid)}", callback_data=f"mod_{command_type}_{cid}_{tid}")] for cid in target_chats]
        await message.reply(f"In welcher Gruppe soll **{tname}** ({command_type}) bearbeitet werden?", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

async def perform_mod_action(bot: Bot, message: Message, chat_id: int, target_id: int, target_name: str, action: str):
    try:
        if action == "ban":
            await bot.ban_chat_member(chat_id, target_id)
            await message.reply(f"🚫 {target_name} gebannt.")
        elif action == "unban":
            await bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
            await message.reply(f"🔓 {target_name} entbannt.")
        elif action == "kick":
            await bot.ban_chat_member(chat_id, target_id)
            await bot.unban_chat_member(chat_id, target_id)
            await message.reply(f"👢 {target_name} gekickt.")
        elif action == "mute":
            await bot.restrict_chat_member(chat_id, target_id, permissions=ChatPermissions(can_send_messages=False))
            await message.reply(f"🔇 {target_name} stummgeschaltet.")
            await send_log(bot, chat_id, "mod", f"🔇 [MUTE] {target_name}")
        elif action == "unmute":
            perms = ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True)
            await bot.restrict_chat_member(chat_id, target_id, permissions=perms)
            await message.reply(f"🔊 Stummschaltung für {target_name} aufgehoben.")
    except Exception as e:
        await message.reply(f"❌ Fehler: {e}")

@dp.callback_query(F.data.startswith("mod_"))
async def cb_mod_action(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    parts = callback.data.split("_")
    action, chat_id, target_id = parts[1], int(parts[2]), int(parts[3])
    try:
        if action == "ban": await bot.ban_chat_member(chat_id, target_id)
        elif action == "unban": await bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
        elif action == "kick": 
            await bot.ban_chat_member(chat_id, target_id)
            await bot.unban_chat_member(chat_id, target_id)
        elif action == "mute": await bot.restrict_chat_member(chat_id, target_id, permissions=ChatPermissions(can_send_messages=False))
        elif action == "unmute":
            perms = ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True)
            await bot.restrict_chat_member(chat_id, target_id, permissions=perms)
        await callback.message.edit_text(f"✅ Aktion **{action}** erfolgreich ausgeführt.")
    except Exception as e:
        await callback.message.edit_text(f"❌ Fehler: {e}")

# --- MODERATIONSBEFEHLE ---

@dp.message(Command("ban", "unban", "kick", "mute", "unmute"))
async def cmd_moderation_general(message: Message, bot: Bot):
    cmd = message.text.split()[0].replace("/", "").lower()
    if message.chat.type == "private":
        await execute_admin_moderation(message, bot, cmd)
    else:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM workplaces WHERE admin_chat_id = ?", (message.chat.id,))
        is_wp = cursor.fetchone()
        conn.close()
        
        if is_wp:
            await execute_admin_moderation(message, bot, cmd)
        else:
            if not get_settings(message.chat.id).get("bot_commands_active", True): return
            tid, tname = await resolve_target(message)
            if not tid: return
            for cid in get_target_chats(message.chat.id):
                if await verify_user_admin_in_group(message.from_user.id, cid):
                    try:
                        if cmd == "ban": await bot.ban_chat_member(cid, tid)
                        elif cmd == "unban": await bot.unban_chat_member(cid, tid, only_if_banned=True)
                        elif cmd == "kick":
                            await bot.ban_chat_member(cid, tid)
                            await bot.unban_chat_member(cid, tid)
                        elif cmd == "mute": await bot.restrict_chat_member(cid, tid, permissions=ChatPermissions(can_send_messages=False))
                        elif cmd == "unmute":
                            perms = ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True)
                            await bot.restrict_chat_member(cid, tid, permissions=perms)
                    except Exception: pass
            await message.reply(f"✅ Moderationsbefehl `{cmd}` ausgeführt.")

@dp.message(Command("warn"))
async def cmd_warn(message: Message, bot: Bot):
    if not get_settings(message.chat.id).get("bot_commands_active", True): return
    tid, tname = await resolve_target(message)
    if not tid: return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    curr_warn = 0
    for cid in get_target_chats(message.chat.id):
        if not await verify_user_admin_in_group(message.from_user.id, cid): continue
        cursor.execute("SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?", (cid, tid))
        row = cursor.fetchone()
        curr_warn = (row[0] if row else 0) + 1
        cursor.execute("INSERT OR REPLACE INTO warnings VALUES (?, ?, ?)", (cid, tid, curr_warn))
        args = message.text.split(maxsplit=2)
        reason = args[2] if len(args) > 2 else "Kein Grund"
        cursor.execute("INSERT INTO warning_logs (chat_id, user_id, admin_name, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (cid, tid, message.from_user.full_name, reason, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()
        if curr_warn >= 3:
            try:
                await bot.ban_chat_member(cid, tid)
                cursor.execute("INSERT OR REPLACE INTO warnings VALUES (?, ?, 0)", (cid, tid))
                conn.commit()
            except Exception: pass
    conn.close()
    if curr_warn >= 3: await message.reply(f"🚫 {tname} hat 3 Verwarnungen und wurde gebannt.")
    else: await message.reply(f"⚠️ Verwarnung {curr_warn}/3 für {tname}.")

# --- /start BEFEHL ---

@dp.message(Command("start"))
async def cmd_start(message: Message, bot: Bot):
    bi = await bot.get_me()
    if message.chat.type in ["group", "supergroup"]:
        await message.answer(f"🤖 **Admin-Menü** für {message.chat.title}:", reply_markup=get_private_start_keyboard(bi.username))
        return
    await message.answer(f"Hallo!\nIch bin **{bi.full_name}**, dein Bot.", reply_markup=get_private_start_keyboard(bi.username))

@dp.message(Command("reload"))
async def cmd_reload(message: Message):
    if message.chat.type in ["group", "supergroup"]:
        save_group_title(message.chat.id, message.chat.title)
        await message.answer("🔄 Aktualisiert.")

@dp.message(Command("setlog"))
async def cmd_setlog(message: Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit(): return
    tid = int(args[1])
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO log_channels (log_chat_id, target_chat_id, log_mod, log_spam, log_joins) VALUES (?, ?, 1, 1, 1)", (message.chat.id, tid))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Log-Kanal für Gruppe `{tid}` eingerichtet.")

# --- CALLBACKS FÜR DAS MENÜ ---

@dp.callback_query(F.data == "private_group_list")
async def cb_group_list(callback: CallbackQuery):
    await callback.answer()
    groups = get_known_groups()
    if not groups:
        await callback.message.edit_text("Keine Gruppen gefunden. Nutze `/link` in der Zielgruppe.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Zurück", callback_data="private_home")]]))
    else:
        await callback.message.edit_text("Wähle die Gruppe aus, die du verwalten möchtest:", reply_markup=get_group_list_keyboard(groups))

@dp.callback_query(F.data == "private_link_info")
async def cb_link_info(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Lege zuerst in einem Arbeitsraum `/setworkplace` fest. Gehe danach in die Zielgruppe und tippe dort `/link`.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Zurück", callback_data="private_home")]]))

@dp.callback_query(F.data == "private_log_info")
async def cb_log_info(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Führe im Log-Kanal den Befehl `/setlog <gruppen_id>` aus.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Zurück", callback_data="private_home")]]))

@dp.callback_query(F.data == "private_help")
async def cb_private_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(HELP_TEXT, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Zurück", callback_data="private_home")]]))

@dp.callback_query(F.data.startswith("select_group_"))
async def cb_select_group(callback: CallbackQuery):
    await callback.answer()
    cid = int(callback.data.replace("select_group_", ""))
    await callback.message.edit_text("⚙️ **Gruppenverwaltung**\nWähle einen Bereich aus:", reply_markup=get_group_settings_page1(cid))


@dp.callback_query(F.data.startswith("settings_cat_"))
async def cb_settings_category(callback: CallbackQuery):
    await callback.answer()
    # Format: settings_cat_<category>_<chat_id>
    _, _, category, cid = callback.data.split("_", 3)
    chat_id = int(cid)
    titles = {
        "moderation": "🛡️ **Moderation & Sicherheit**",
        "bot": "🤖 **KI & Bot-Funktionen**",
        "activity": "📊 **Aktivität & Ränge**",
        "logs": "📡 **Protokolle & Verknüpfungen**",
    }
    await callback.message.edit_text(titles.get(category, "⚙️ **Einstellungen**"), reply_markup=get_settings_category_keyboard(chat_id, category))


@dp.callback_query(F.data.startswith("menu_rules_"))
async def cb_menu_rules(callback: CallbackQuery):
    await callback.answer()
    cid = int(callback.data.replace("menu_rules_", ""))
    await callback.message.edit_text("📋 **Gruppenregeln**\nHier kannst du den Regeltext bearbeiten.", reply_markup=get_rules_menu_keyboard(cid))


@dp.callback_query(F.data.startswith("menu_welcome_"))
async def cb_menu_welcome(callback: CallbackQuery):
    await callback.answer()
    cid = int(callback.data.replace("menu_welcome_", ""))
    await callback.message.edit_text("👋 **Begrüßung & Verabschiedung**\nVerwalte Begrüßungstext und Begrüßungsmodus.", reply_markup=get_welcome_menu_keyboard(cid))


@dp.callback_query(F.data.startswith("welc_toggle_status_"))
async def cb_w_status(callback: CallbackQuery):
    await callback.answer("Aktualisiert.")
    cid = int(callback.data.replace("welc_toggle_status_", ""))
    w = get_welcome_config(cid)
    update_welcome_config(cid, status=not w["status"])
    await callback.message.edit_reply_markup(reply_markup=get_welcome_menu_keyboard(cid))


@dp.callback_query(F.data.startswith("welc_toggle_mode_"))
async def cb_w_mode(callback: CallbackQuery):
    await callback.answer("Aktualisiert.")
    cid = int(callback.data.replace("welc_toggle_mode_", ""))
    w = get_welcome_config(cid)
    update_welcome_config(cid, mode="manual" if w["mode"] == "ai" else "ai")
    await callback.message.edit_reply_markup(reply_markup=get_welcome_menu_keyboard(cid))


@dp.callback_query(F.data.startswith("edit_welcome_prompt_"))
async def cb_edit_w_prompt(callback: CallbackQuery):
    await callback.answer()
    cid = int(callback.data.replace("edit_welcome_prompt_", ""))
    waiting_for_input[callback.from_user.id] = {"chat_id": cid, "type": "welcome_text"}
    await callback.message.answer("✏️ Sende den neuen Begrüßungstext:")


@dp.callback_query(F.data.startswith("edit_welcome_media_"))
async def cb_edit_w_media(callback: CallbackQuery):
    await callback.answer()
    cid = int(callback.data.replace("edit_welcome_media_", ""))
    waiting_for_input[callback.from_user.id] = {"chat_id": cid, "type": "welcome_media"}
    await callback.message.answer("🖼️ Sende die URL zum Begrüßungsbild/GIF:")


@dp.callback_query(F.data.startswith("setting_toggle_"))
async def cb_setting_toggle(callback: CallbackQuery):
    await callback.answer("Einstellung aktualisiert.")
    payload = callback.data.replace("setting_toggle_", "", 1)
    key, cid = payload.rsplit("_", 1)
    chat_id = int(cid)
    settings = get_settings(chat_id)
    if key in settings:
        update_setting(chat_id, key, not settings[key])
    category_by_key = {
        "anti_spam": "moderation", "anti_flood": "moderation", "captcha": "moderation",
        "join_check": "moderation", "captcha_rules": "moderation", "controls": "moderation",
        "media": "moderation", "mention": "moderation", "guardian": "moderation",
        "approval": "moderation", "dellmsg": "moderation",
        "bot_welcome_active": "bot", "bot_filters_active": "bot",
        "bot_commands_active": "bot", "admin_ping": "bot",
    }
    category = category_by_key.get(key, "moderation")
    await callback.message.edit_reply_markup(reply_markup=get_settings_category_keyboard(chat_id, category))


# Kompatibilität mit alten Nachrichten, die noch alte toggle_s1-Buttons enthalten.
@dp.callback_query(F.data.startswith("toggle_s1_"))
async def cb_toggle_page1_legacy(callback: CallbackQuery):
    await callback.answer("Einstellung aktualisiert.")
    parts = callback.data.split("_")
    cid, rkey = int(parts[3]), parts[2]
    mapping = {
        "botwelcomeactive": "bot_welcome_active", "botfiltersactive": "bot_filters_active",
        "botcommandsactive": "bot_commands_active", "antispam": "anti_spam",
        "joincheck": "join_check", "captcharules": "captcha_rules", "rules": "rules",
    }
    key = mapping.get(rkey, rkey)
    settings = get_settings(cid)
    if key in settings:
        update_setting(cid, key, not settings[key])
    await callback.message.edit_text("⚙️ **Gruppenverwaltung**\nWähle einen Bereich aus:", reply_markup=get_group_settings_page1(cid))


@dp.callback_query(F.data == "private_home")
async def cb_home(callback: CallbackQuery):
    await callback.answer()
    bi = await bot.get_me()
    await callback.message.edit_text(f"Willkommen im Hauptmenü von **{bi.full_name}**.", reply_markup=get_private_start_keyboard(bi.username))

@dp.message(F.chat.type == "private")
async def handle_private(message: Message):
    uid = message.from_user.id
    if uid in waiting_for_input:
        data = waiting_for_input.pop(uid)
        cid = data["chat_id"]
        if data["type"] == "rules": set_group_rules_text(cid, message.text)
        elif data["type"] == "welcome_text": update_welcome_config(cid, text=message.text, mode="manual")
        elif data["type"] == "welcome_media": update_welcome_config(cid, media_url=message.text)
        await message.answer("✅ Gespeichert!")
        return
    # Im privaten Chat darf die KI antworten
    analysis = await process_message(message.text)
    if analysis.get("reply"): await message.answer(analysis["reply"])

@dp.chat_member()
async def handle_chat_member_update(event: ChatMemberUpdated, bot: Bot):
    chat_id = event.chat.id
    if event.new_chat_member.status == "member":
        settings = get_settings(chat_id)
        if not settings.get("bot_welcome_active", True): return
        
        user = event.new_chat_member.user
        cfg = get_welcome_config(chat_id)
        if not cfg["status"]: return
        
        # Hier greift die Gemini-KI für die Begrüßung
        welc_text = ""
        if cfg["mode"] == "ai":
            prompt = f"Schreibe eine kurze, zynische Begrüßung im Dr.-House-Stil für den neuen Patienten namens {user.full_name}."
            res = await process_message(prompt)
            welc_text = res.get("reply", f"Willkommen Patient {user.full_name}.")
        else:
            welc_text = cfg["text"].replace("{user}", user.full_name)
            
        try:
            if cfg["media_url"]: await bot.send_animation(chat_id, animation=cfg["media_url"], caption=welc_text)
            else: await bot.send_message(chat_id, welc_text)
        except Exception: pass
        await send_log(bot, chat_id, "joins", f"📥 [BEITRITT] {user.full_name}")

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_group_message(message: Message, bot: Bot):
    chat_id = message.chat.id
    user = message.from_user
    if user.username: cache_username(user.username, user.id)
    
    if message.chat.type in ["group", "supergroup"]:
        save_group_title(chat_id, message.chat.title)
        settings = get_settings(chat_id)
        
        me = await bot.get_me()
        # Gemini-KI greift in der Gruppe NUR, wenn der Bot direkt erwähnt oder zitiert wird
        if (message.reply_to_message and message.reply_to_message.from_user.id == me.id) or f"@{me.username}" in message.text:
            analysis = await process_message(message.text)
            if analysis.get("reply"):
                try: await message.reply(analysis["reply"])
                except Exception: pass
            return

        if not settings.get("bot_filters_active", True):
            await record_user_activity(message, chat_id, user.id, user.full_name, user.username)
            return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute("SELECT word FROM bad_words WHERE chat_id = ?", (chat_id,))
        badwords = [r[0] for r in cursor.fetchall()]
        if any(bw in message.text.lower() for bw in badwords):
            try:
                await message.delete()
                cursor.execute("SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user.id))
                w = cursor.fetchone()
                cnt = (w[0] if w else 0) + 1
                cursor.execute("INSERT OR REPLACE INTO warnings VALUES (?, ?, ?)", (chat_id, user.id, cnt))
                conn.commit()
                if cnt >= 3:
                    await bot.ban_chat_member(chat_id, user.id)
                    await message.answer(f"🚫 {user.full_name} hat 3 Verwarnungen erreicht und wurde gebannt.")
                else:
                    await message.answer(f"⚠️ {user.full_name}, verbotenes Wort! ({cnt}/3)")
            except Exception: pass
            conn.close()
            return

        cursor.execute("SELECT keyword, reply_text FROM group_filters WHERE chat_id = ?", (chat_id,))
        for kw, rtxt in cursor.fetchall():
            if kw in message.text.lower():
                await message.reply(rtxt)
                break
        conn.close()

        if settings.get("anti_spam", True) and ("t.me/" in message.text or "http://" in message.text or "https://" in message.text):
            try:
                await message.delete()
                await message.answer(f"⚠️ {user.full_name}, Links sind untersagt!")
            except Exception: pass
            return

        await record_user_activity(message, chat_id, user.id, user.full_name, user.username)

async def main():
    logging.basicConfig(level=logging.INFO)
    print("Bot mit separaten APIs und präziser KI-Steuerung gestartet...")
    asyncio.create_task(check_weekly_reset())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): logging.info("Gestoppt.")
    except Exception as e: logging.critical(f"Kritischer Fehler: {e}")
