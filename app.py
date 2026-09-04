import os
import sqlite3
from datetime import datetime, timedelta, timezone
from threading import Thread

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])

DB_FILE = "channels.db"

app = Flask(__name__)


# =========================
# DATABASE
# =========================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            username TEXT
        )
    """)

    conn.commit()
    conn.close()


def add_channel(chat_id, title, username):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO channels
        (chat_id, title, username)
        VALUES (?, ?, ?)
        """,
        (str(chat_id), title, username)
    )

    conn.commit()
    conn.close()


def remove_channel(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM channels WHERE chat_id = ?",
        (str(chat_id),)
    )

    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    return deleted > 0


def get_channels():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT chat_id, title, username FROM channels ORDER BY id"
    )

    channels = cursor.fetchall()

    conn.close()

    return channels


# =========================
# RENDER WEB SERVER
# =========================

@app.route("/")
def home():
    return "Telegram Multi Channel Bot is running!"


def run_server():
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )


# =========================
# ADMIN CHECK
# =========================

def is_admin(update: Update):
    return (
        update.effective_user is not None
        and update.effective_user.id == ADMIN_ID
    )


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    channels = get_channels()

    if not channels:
        await update.message.reply_text(
            "📂 No channels have been added yet."
        )
        return

    buttons = []

    for chat_id, title, username in channels:

        buttons.append([
            InlineKeyboardButton(
                f"📺 {title}",
                callback_data=f"channel:{chat_id}"
            )
        ])

    keyboard = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        "📺 Select a Channel\n\n"
        "Choose a channel below to generate "
        "a temporary Request-to-Join link.\n\n"
        "⏳ Link validity: 2 minutes",
        reply_markup=keyboard
    )


# =========================
# GENERATE LINK
# =========================

async def channel_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    chat_id = query.data.split(":", 1)[1]

    try:

        # Link expires after 2 minutes
        expire_time = (
            datetime.now(timezone.utc)
            + timedelta(minutes=2)
        )

        invite = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            expire_date=expire_time,
            creates_join_request=True
        )

        await query.message.reply_text(
            "📩 Temporary Join Request Link\n\n"
            f"🔗 {invite.invite_link}\n\n"
            "⏳ Valid for 2 minutes.\n"
            "📩 The user must send a Join Request."
        )

    except Exception as error:

        print("LINK ERROR:", error)

        await query.message.reply_text(
            "❌ Couldn't create the link.\n\n"
            "Make sure the bot is an administrator "
            "of this channel and has permission to "
            "manage invite links."
        )


# =========================
# ADD CHANNEL
# =========================

async def addchannel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Admin only."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "❌ Usage:\n\n"
            "/addchannel @ChannelUsername"
        )

        return

    channel = context.args[0]

    try:

        chat = await context.bot.get_chat(channel)

        member = await context.bot.get_chat_member(
            chat.id,
            context.bot.id
        )

        if member.status != "administrator":

            await update.message.reply_text(
                "❌ The bot is not an administrator "
                "of this channel."
            )

            return

        add_channel(
            chat.id,
            chat.title or "Unnamed Channel",
            chat.username
        )

        username_text = (
            f"@{chat.username}"
            if chat.username
            else "Private Channel"
        )

        await update.message.reply_text(
            "✅ Channel Added Successfully!\n\n"
            f"📺 {chat.title}\n"
            f"🆔 {chat.id}\n"
            f"👤 {username_text}"
        )

    except Exception as error:

        print("ADD ERROR:", error)

        await update.message.reply_text(
            "❌ Couldn't add this channel.\n\n"
            "Check that:\n"
            "1️⃣ The bot is in the channel.\n"
            "2️⃣ The bot is an administrator.\n"
            "3️⃣ The channel username is correct."
        )


# =========================
# SHOW CHANNELS
# =========================

async def channels_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Admin only."
        )

        return

    channels = get_channels()

    if not channels:

        await update.message.reply_text(
            "📂 No channels have been added."
        )

        return

    text = "📺 Your Channels\n\n"

    for index, (chat_id, title, username) in enumerate(
        channels,
        start=1
    ):

        username_text = (
            f"@{username}"
            if username
            else "Private Channel"
        )

        text += (
            f"{index}. {title}\n"
            f"   {username_text}\n"
            f"   ID: {chat_id}\n\n"
        )

    await update.message.reply_text(text)


# =========================
# REMOVE CHANNEL
# =========================

async def removechannel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Admin only."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "❌ Usage:\n\n"
            "/removechannel @ChannelUsername"
        )

        return

    channel = context.args[0]

    try:

        chat = await context.bot.get_chat(channel)

        removed = remove_channel(chat.id)

        if removed:

            await update.message.reply_text(
                "🗑️ Channel Removed\n\n"
                f"📺 {chat.title}"
            )

        else:

            await update.message.reply_text(
                "❌ This channel isn't in the bot's list."
            )

    except Exception as error:

        print("REMOVE ERROR:", error)

        await update.message.reply_text(
            "❌ Couldn't find that channel."
        )


# =========================
# ADMIN HELP
# =========================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Admin only."
        )

        return

    await update.message.reply_text(
        "🛠️ Admin Panel\n\n"
        "/addchannel @username\n"
        "➕ Add a channel\n\n"
        "/channels\n"
        "📺 Show all channels\n\n"
        "/removechannel @username\n"
        "🗑️ Remove a channel\n\n"
        "/start\n"
        "🔗 Open channel menu"
    )


# =========================
# MAIN
# =========================

def main():

    init_db()

    # Start Render web server
    Thread(
        target=run_server,
        daemon=True
    ).start()

    # Create Telegram application
    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("addchannel", addchannel)
    )

    application.add_handler(
        CommandHandler("channels", channels_command)
    )

    application.add_handler(
        CommandHandler("removechannel", removechannel)
    )

    application.add_handler(
        CommandHandler("admin", admin_command)
    )

    # Channel buttons
    application.add_handler(
        CallbackQueryHandler(
            channel_button,
            pattern=r"^channel:"
        )
    )

    print("Bot started successfully!")

    application.run_polling()


if __name__ == "__main__":
    main()
