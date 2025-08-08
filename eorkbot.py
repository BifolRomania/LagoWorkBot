import os
import re
import sqlite3
import pandas as pd
from datetime import datetime
from telethon import TelegramClient, events
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

# ======== CONFIG ========
API_ID = 20676315
API_HASH = "0ecd754a3b356e1ed4bc09a9c4b82484"
PHONE_NUMBER = "+373xxxxxxxx"  # <-- your Telegram phone number here

BOT_TOKEN = "YOUR_BOT_TOKEN"   # <-- your Telegram Bot token from @BotFather
YOUR_USER_ID = 123456789       # <-- your Telegram user ID (to send messages only to you)
GROUP_NAME = "Ospătari lago"
TARGET_NAME = "Goia Viorel"
DB_FILE = "payments.db"

# ======== DATABASE ========
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS schedule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    restaurant TEXT,
                    name TEXT,
                    status TEXT
                )''')
    conn.commit()
    conn.close()

def add_entry(date, restaurant, name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO schedule (date, restaurant, name, status) VALUES (?, ?, ?, ?)",
              (date, restaurant, name, None))
    conn.commit()
    conn.close()

def update_status(entry_id, status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE schedule SET status = ? WHERE id = ?", (status, entry_id))
    conn.commit()
    conn.close()

def get_report():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM schedule", conn)
    conn.close()
    return df

# ======== TELETHON CLIENT ========
client = TelegramClient("user_session", API_ID, API_HASH)

@client.on(events.NewMessage)
async def handler(event):
    if event.chat and GROUP_NAME.lower() in (event.chat.title or "").lower():
        text = event.message.message

        # Find date in format dd.mm
        date_match = re.search(r"(\d{2}\.\d{2})", text)
        if date_match:
            date = date_match.group(1) + f".{datetime.now().year}"

        # Split by restaurant sections
        blocks = re.split(r"\n(?=[A-Z][a-z]+)", text)
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) > 1:
                restaurant = lines[0].strip()
                for line in lines[1:]:
                    if TARGET_NAME.lower() in line.lower():
                        add_entry(date, restaurant, TARGET_NAME)
                        await send_payment_prompt(date, restaurant)

# ======== BOT FUNCTIONS ========
async def send_payment_prompt(date, restaurant):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Paid", callback_data=f"paid|{date}|{restaurant}"),
         InlineKeyboardButton("❌ Unpaid", callback_data=f"unpaid|{date}|{restaurant}")]
    ])
    await bot_app.bot.send_message(
        chat_id=YOUR_USER_ID,
        text=f"📅 {date} — {restaurant}\nWere you paid?",
        reply_markup=keyboard
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status, date, restaurant = query.data.split("|")

    # Update DB
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM schedule WHERE date=? AND restaurant=? AND name=?", (date, restaurant, TARGET_NAME))
    row = c.fetchone()
    if row:
        update_status(row[0], status)
    conn.close()

    await query.edit_message_text(f"📅 {date} — {restaurant}\nStatus: {'✅ Paid' if status == 'paid' else '❌ Unpaid'}")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_report()
    if df.empty:
        await update.message.reply_text("No data yet.")
        return

    # Send text summary
    summary = df.to_string(index=False)
    await update.message.reply_text(f"📊 Payment Report:\n```\n{summary}\n```", parse_mode="Markdown")

    # Save CSV and send
    csv_path = "payment_report.csv"
    df.to_csv(csv_path, index=False)
    await update.message.reply_document(document=InputFile(csv_path))

# ======== START EVERYTHING ========
if __name__ == "__main__":
    init_db()

    # Start bot
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
    bot_app.add_handler(CallbackQueryHandler(button_callback))
    bot_app.add_handler(CommandHandler("report", report_command))

    # Run both Telethon & Bot in parallel
    import asyncio
    async def main():
        await client.start(phone=PHONE_NUMBER)
        await asyncio.gather(
            client.run_until_disconnected(),
            bot_app.run_polling()
        )

    asyncio.run(main())
@client.on(events.NewMessage)
async def handler(event):
    if event.chat and GROUP_NAME.lower() in (event.chat.title or "").lower():
        text = event.message.message.strip()

        # Split into blocks by date (format dd.mm)
        date_blocks = re.split(r"(?=\d{2}\.\d{2})", text)
        for block in date_blocks:
            block = block.strip()
            if not block:
                continue

            # First date in the block
            date_match = re.match(r"(\d{2}\.\d{2})", block)
            if date_match:
                date = date_match.group(1) + f".{datetime.now().year}"
                rest_text = block[len(date_match.group(0)):].strip()

                # Split by restaurant names (capitalized line)
                restaurant_blocks = re.split(r"\n(?=[A-ZȘȚĂÂÎ][a-zșțăâî]+)", rest_text)
                for r_block in restaurant_blocks:
                    lines = r_block.strip().split("\n")
                    if len(lines) > 1:
                        restaurant = lines[0].strip()
                        for line in lines[1:]:
                            if TARGET_NAME.lower() in line.lower():
                                add_entry(date, restaurant, TARGET_NAME)
                                await send_payment_prompt(date, restaurant)
