import asyncio
import re
import sqlite3
from datetime import datetime
import time
import threading
import requests
from telethon import TelegramClient, events
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler
import config
import json

# --- DB Setup ---
conn = sqlite3.connect("schedule.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    hall TEXT,
    notified INTEGER DEFAULT 0,
    paid_status TEXT DEFAULT NULL
)
""")
conn.commit()

# --- Regex patterns ---
DATE_PATTERN = r"(\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b)"
HALL_PATTERN = r"(toscana|sicilia|siena|portofino|picolino)"
NAME_PATTERN = rf"\b{re.escape(config.YOUR_NAME)}\b"

# --- Date parser ---
def parse_date(date_str: str) -> str:
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%d.%m", "%d/%m/%Y", "%d/%m/%y", "%d/%m"):
        try:
            date_obj = datetime.strptime(date_str, fmt)
            if "%Y" not in fmt and "%y" not in fmt:
                date_obj = date_obj.replace(year=datetime.now().year)
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str

# --- Gemini AI parsing ---
def parse_with_gemini(text: str):
    if not config.GEMINI_API_KEY.strip():
        return None
    try:
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent?key={config.GEMINI_API_KEY}"
        prompt = (
            f"Extract all work shifts for '{config.YOUR_NAME}' from the following message.\n"
            f"Return ONLY a valid JSON array, where each object has:\n"
            f" - 'date': in YYYY-MM-DD format\n"
            f" - 'hall': one of: Toscana, Sicilia, Siena, Portofino, Picolino\n"
            f"If there are no matches, return an empty array [].\n\n"
            f"Message:\n{text}"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return json.loads(raw_text)
    except Exception as e:
        print("Gemini error:", e)
        return None

# --- Regex fallback parsing ---
def parse_with_regex(message: str):
    entries = []
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    for line in lines:
        if not re.search(NAME_PATTERN, line, re.IGNORECASE):
            continue
        date_match = re.search(DATE_PATTERN, line)
        if not date_match:
            continue
        raw_date = date_match.group(1)
        parsed_date = parse_date(raw_date)
        hall_match = re.search(HALL_PATTERN, line, re.IGNORECASE)
        hall = hall_match.group(1).title() if hall_match else ""
        entries.append({"date": parsed_date, "hall": hall})
    return entries

# --- Save entry ---
def save_schedule_entry(date, hall):
    cur.execute("INSERT INTO schedule (date, hall) VALUES (?, ?)", (date, hall))
    conn.commit()

# --- Notify instantly ---
def notify_admin(date, hall):
    keyboard = [
        [
            InlineKeyboardButton("✅ Paid", callback_data=f"paid:{date}:{hall}"),
            InlineKeyboardButton("❌ Waiting", callback_data=f"waiting:{date}:{hall}")
        ]
    ]
    app.bot.send_message(
        chat_id=config.ADMIN_CHAT_ID,
        text=f"📅 New shift:\nDate: {date}\nHall: {hall or 'Unknown'}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- Reminder loop ---
def reminder_loop():
    while True:
        today = datetime.now().date()
        cur.execute("SELECT id, date, hall FROM schedule WHERE paid_status IS NULL")
        rows = cur.fetchall()
        for row_id, date_str, hall in rows:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            if today > date_obj:
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Paid", callback_data=f"paid_id:{row_id}"),
                        InlineKeyboardButton("❌ Waiting", callback_data=f"waiting_id:{row_id}")
                    ]
                ]
                app.bot.send_message(
                    chat_id=config.ADMIN_CHAT_ID,
                    text=f"💰 Have you been paid for {date_str} ({hall or 'Unknown'})?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        time.sleep(3600)

# --- Button click handler ---
async def button_click(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("paid_id:") or data.startswith("waiting_id:"):
        status, row_id = data.split("_id:")
        cur.execute("UPDATE schedule SET paid_status = ? WHERE id = ?", (status, row_id))
        conn.commit()
        await query.edit_message_text(f"✅ Status set to: {status}")
    elif data.startswith("paid:") or data.startswith("waiting:"):
        status, date, hall = data.split(":")
        cur.execute("UPDATE schedule SET paid_status = ? WHERE date = ? AND hall = ?", (status, date, hall))
        conn.commit()
        await query.edit_message_text(f"✅ Status set to: {status}")

# --- Telethon listener ---
async def telethon_listener():
    async with TelegramClient("session", config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH) as client:
        @client.on(events.NewMessage(chats=config.GROUP_ID))
        async def handler(event):
            text = event.message.message
            if not text:
                return
            parsed = parse_with_gemini(text) or parse_with_regex(text)
            if parsed:
                for entry in parsed:
                    save_schedule_entry(entry["date"], entry.get("hall", ""))
                    notify_admin(entry["date"], entry.get("hall", ""))

        print("📡 Listening for messages...")
        await client.run_until_disconnected()

# --- Start bot + listener ---
app = Application.builder().token(config.BOT_TOKEN).build()
app.add_handler(CallbackQueryHandler(button_click))

threading.Thread(target=reminder_loop, daemon=True).start()

async def main():
    await asyncio.gather(
        telethon_listener(),
        app.run_polling()
    )

if __name__ == "__main__":
    asyncio.run(main())
