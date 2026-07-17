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

load_dotenv()  # reads variables from a local .env file

TOKEN = os.environ["TOKEN"]  # set this in a .env file

# Thread ID of the "Welcome" topic — where @all mentions get mirrored to.
# Get this from a message link in that topic: https://t.me/c/<chat>/<TOPIC_ID>
_welcome_topic_env = os.environ.get("WELCOME_TOPIC_ID")
WELCOME_TOPIC_ID = int(_welcome_topic_env) if _welcome_topic_env else None

# Topic id 1 is Telegram's "General" topic — it's special-cased by the API
# and must NOT be passed as an explicit message_thread_id, or sendMessage
# fails with "Message thread not found". Omit the parameter entirely
# instead when targeting it.
WELCOME_IS_GENERAL = WELCOME_TOPIC_ID == 1
WELCOME_SEND_THREAD_ID = None if WELCOME_IS_GENERAL else WELCOME_TOPIC_ID

if WELCOME_TOPIC_ID is None:
    print("WARNING: WELCOME_TOPIC_ID not set in .env — @all mirroring is disabled.")

# Trigger phrases for the mention mirror. Kept configurable because plain
# "@all"/"@admin" are common conventions — if another bot in the group also
# listens for those, both will fire on the same message. Change these to
# something more unique to this bot if that happens.
TRIGGER_ALL = os.environ.get("TRIGGER_ALL", "@alll")
TRIGGER_ADMIN = os.environ.get("TRIGGER_ADMIN", "@admin")

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
print(f"Config -> WELCOME_TOPIC_ID={WELCOME_TOPIC_ID} (general={WELCOME_IS_GENERAL}) "
      f"TRIGGER_ALL={TRIGGER_ALL!r} TRIGGER_ADMIN={TRIGGER_ADMIN!r}")


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


async def send_mention_batches(context, chat_id, thread_id, members, exclude_user_id, header_text=None):
    """Sends @-mentions for `members` in batches of 5 into the given topic,
    skipping `exclude_user_id`. `header_text`, if given, is repeated at the
    top of every batch (matches the old inline /echo behavior)."""

    batch_size = 5
    safe_header = html.escape(header_text) if header_text else None

    for i in range(0, len(members), batch_size):

        batch = members[i:i + batch_size]

        mentions = []

        for user_id, username, first_name in batch:

            if user_id == exclude_user_id:
                continue

            if username:
                mentions.append(f"@{username}")
            else:
                safe_name = html.escape(first_name or "user")
                mentions.append(f'<a href="tg://user?id={user_id}">{safe_name}</a>')

        if not mentions:
            continue

        mention_line = " ".join(mentions)
        msg = f"{safe_header}\n\n{mention_line}" if safe_header else mention_line

        send_kwargs = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
        }

        if thread_id is not None:
            send_kwargs["message_thread_id"] = thread_id

        try:
            await context.bot.send_message(**send_kwargs)
        except Exception as e:
            print(f"Failed to send mention batch: {e}")

        await asyncio.sleep(1)


async def send_topic_message(context, chat_id, thread_id, text, parse_mode=None):
    send_kwargs = {
        "chat_id": chat_id,
        "text": text,
    }

    if parse_mode:
        send_kwargs["parse_mode"] = parse_mode

    if thread_id is not None:
        send_kwargs["message_thread_id"] = thread_id

    await context.bot.send_message(**send_kwargs)


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
    message_thread_id = update.message.message_thread_id  # None if not in a topic

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
    # MENTION MIRROR
    # "@all" tags everyone, "@admin" tags admins only.
    # The original message text is reposted into Welcome with the tags
    # appended below it.
    # =========================
    wants_admin_tag = TRIGGER_ADMIN in clean_text
    wants_all_tag = TRIGGER_ALL in clean_text and not wants_admin_tag

    if WELCOME_TOPIC_ID is not None and (wants_admin_tag or wants_all_tag):

        admins = await context.bot.get_chat_administrators(chat_id)
        admin_ids = {admin.user.id for admin in admins}

        if user.id not in admin_ids:
            try:
                await update.message.delete()
            except Exception as e:
                print(f"Failed to delete non-admin trigger message: {e}")

            try:
                await send_topic_message(
                    context,
                    chat_id,
                    message_thread_id,
                    "only admins can use trigger"
                )
            except Exception as e:
                print(f"Failed to send non-admin trigger warning: {e}")

            return

        if wants_admin_tag:
            mirror_members = [
                (admin.user.id, admin.user.username, admin.user.first_name)
                for admin in admins
            ]
        else:
            cursor.execute("""
            SELECT user_id, username, first_name
            FROM members
            WHERE chat_id = ?
            """, (chat_id,))

            mirror_members = cursor.fetchall()

        if mirror_members:

            await send_mention_batches(
                context,
                chat_id,
                WELCOME_SEND_THREAD_ID,
                mirror_members,
                exclude_user_id=user.id,
                header_text=text
            )

    return


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
