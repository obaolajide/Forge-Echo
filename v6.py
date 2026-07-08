import sqlite3
import asyncio
import html
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters
)

load_dotenv()  # reads variables from a local .env file, if present

TOKEN = os.environ["TOKEN"]  # set this in a .env file, never hardcode it

db = sqlite3.connect(
    "database.db",
    check_same_thread=False
)

cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS members (
    chat_id INTEGER,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    PRIMARY KEY(chat_id, user_id)
)
""")

db.commit()

print("Database connected")


# =========================
# EVENT TRACKING
# =========================
async def track_members(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.chat_member:
        return

    chat_id = update.effective_chat.id
    user = update.chat_member.new_chat_member.user
    new_status = update.chat_member.new_chat_member.status

    # USER JOINED OR PROMOTED
    if new_status in ["member", "administrator"]:

        cursor.execute("""
        INSERT OR REPLACE INTO members
        (chat_id, user_id, username, first_name)
        VALUES (?, ?, ?, ?)
        """, (
            chat_id,
            user.id,
            user.username,
            user.first_name
        ))

        db.commit()

    # USER LEFT OR KICKED
    elif new_status in ["left", "kicked"]:

        cursor.execute("""
        DELETE FROM members
        WHERE chat_id = ? AND user_id = ?
        """, (
            chat_id,
            user.id
        ))

        db.commit()


async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:
        return

    # FIX: get_chat_administrators (used below) only works in
    # group/supergroup chats. Bail out early for private chats/channels
    # so we don't crash on an unhandled exception.
    if update.effective_chat.type not in ("group", "supergroup"):
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    text = update.message.text
    clean_text = text.strip().lower()

    print(f"{user.first_name}: {text}")

    if user.is_bot:
        return

    # SAVE USER (message tracking)
    cursor.execute("""
    INSERT OR REPLACE INTO members
    (chat_id, user_id, username, first_name)
    VALUES (?, ?, ?, ?)
    """, (
        chat_id,
        user.id,
        user.username,
        user.first_name
    ))

    db.commit()

    # =========================
    # SUFFIX TRIGGER LOGIC
    # =========================

    trigger_all = "/echo"
    trigger_admin = "/echo admin"

    is_admin_echo = clean_text.endswith(trigger_admin)
    is_echo = clean_text.endswith(trigger_all) and not is_admin_echo

    if not (is_echo or is_admin_echo):
        return

    # ADMIN CHECK
    admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = [admin.user.id for admin in admins]

    if user.id not in admin_ids:
        await update.message.reply_text("Only admins can use this command.")
        return

    # MESSAGE EXTRACTION
    if is_admin_echo:
        custom_message = text[:-len(trigger_admin)].strip()
    else:
        custom_message = text[:-len(trigger_all)].strip()

    if custom_message == "":
        custom_message = "Attention everyone"

    # GET MEMBERS
    cursor.execute("""
    SELECT user_id, username, first_name
    FROM members
    WHERE chat_id = ?
    """, (chat_id,))

    members = cursor.fetchall()

    # ADMIN MODE FILTER
    if is_admin_echo:
        admin_set = set(admin_ids)
        members = [m for m in members if m[0] in admin_set]

    if not members:
        await update.message.reply_text("No stored members yet.")
        return

    # BATCH SEND
    batch_size = 5

    for i in range(0, len(members), batch_size):

        batch = members[i:i + batch_size]

        mentions = []

        for user_id, username, first_name in batch:

            if user_id == user.id:
                continue

            if username:
                mentions.append(f"@{username}")
            else:
                # FIX: a bare first name is just text, it doesn't notify
                # the user. Use a tg://user inline-mention entity instead,
                # which pings them the same way an @username does.
                safe_name = html.escape(first_name or "user")
                mentions.append(f'<a href="tg://user?id={user_id}">{safe_name}</a>')

        if not mentions:
            continue

        safe_custom_message = html.escape(custom_message)
        msg = f"{safe_custom_message}\n\n" + " ".join(mentions)

        # FIX: wrap the send in try/except so one failed batch (e.g. flood
        # control, a user who blocked the bot) doesn't abort the remaining
        # batches.
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Failed to send batch {i // batch_size}: {e}")

        await asyncio.sleep(1)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    # FIX: without this, every network hiccup (e.g. internet dropping)
    # prints a full traceback. This logs one short line instead and lets
    # the built-in retry loop keep doing its job.
    print(f"Update caused error: {context.error}")


app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(
    MessageHandler(filters.TEXT, handler)
)

app.add_handler(
    ChatMemberHandler(track_members, ChatMemberHandler.CHAT_MEMBER)
)

app.add_error_handler(error_handler)

print("Bot running...")

# FIX: chat_member updates are not delivered by default under polling.
# Without allowed_updates=Update.ALL_TYPES, track_members basically never fires.
try:
    app.run_polling(allowed_updates=Update.ALL_TYPES)
except KeyboardInterrupt:
    print("Bot stopped.")
