import os
import sqlite3
import secrets
import time
import threading
import logging
from flask import Flask, request, jsonify

import requests

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Your Render URL, for example:
# https://your-bot.onrender.com
RENDER_URL = os.getenv("RENDER_URL", "").strip().rstrip("/")

# Admin Telegram user ID
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Maximum 6 channels.
# Example:
# @channel1,@channel2,@channel3
CHANNELS = [
    x.strip()
    for x in os.getenv("CHANNELS", "").split(",")
    if x.strip()
][:6]

# Auto delete seconds.
# 0 = disabled
AUTO_DELETE = int(os.getenv("AUTO_DELETE", "0"))

PORT = int(os.getenv("PORT", "10000"))

DB_FILE = "bot.db"

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)

# =========================================================
# TELEGRAM API
# =========================================================

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def telegram(method, data=None):
    try:
        response = requests.post(
            f"{API}/{method}",
            data=data or {},
            timeout=30
        )

        result = response.json()

        if not result.get("ok"):
            logger.error(
                "Telegram API error %s: %s",
                method,
                result
            )

        return result

    except Exception as e:
        logger.exception("Telegram request failed: %s", e)
        return {"ok": False, "description": str(e)}


def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return telegram("sendMessage", data)


def delete_message(chat_id, message_id):
    return telegram(
        "deleteMessage",
        {
            "chat_id": chat_id,
            "message_id": message_id
        }
    )


# =========================================================
# DATABASE
# =========================================================

db_lock = threading.Lock()


def db():
    connection = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db_lock:
        connection = db()

        connection.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_name TEXT,
                owner_id INTEGER,
                created_at INTEGER NOT NULL
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                owner_id INTEGER,
                created_at INTEGER NOT NULL
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS batch_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_token TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_name TEXT
            )
        """)

        connection.commit()
        connection.close()


def save_file(file_id, file_type, file_name, owner_id):
    token = secrets.token_urlsafe(10)

    with db_lock:
        connection = db()

        connection.execute(
            """
            INSERT INTO files
            (token, file_id, file_type, file_name, owner_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                file_id,
                file_type,
                file_name,
                owner_id,
                int(time.time())
            )
        )

        connection.commit()
        connection.close()

    return token


def get_file(token):
    with db_lock:
        connection = db()

        row = connection.execute(
            "SELECT * FROM files WHERE token = ?",
            (token,)
        ).fetchone()

        connection.close()

    return row


def create_batch(owner_id):
    token = secrets.token_urlsafe(10)

    with db_lock:
        connection = db()

        connection.execute(
            """
            INSERT INTO batches
            (token, owner_id, created_at)
            VALUES (?, ?, ?)
            """,
            (
                token,
                owner_id,
                int(time.time())
            )
        )

        connection.commit()
        connection.close()

    return token


def add_batch_file(
    batch_token,
    file_id,
    file_type,
    file_name
):
    with db_lock:
        connection = db()

        connection.execute(
            """
            INSERT INTO batch_files
            (batch_token, file_id, file_type, file_name)
            VALUES (?, ?, ?, ?)
            """,
            (
                batch_token,
                file_id,
                file_type,
                file_name
            )
        )

        connection.commit()
        connection.close()


def get_batch_files(token):
    with db_lock:
        connection = db()

        rows = connection.execute(
            """
            SELECT *
            FROM batch_files
            WHERE batch_token = ?
            ORDER BY id ASC
            """,
            (token,)
        ).fetchall()

        connection.close()

    return rows


# =========================================================
# FORCE SUBSCRIPTION
# =========================================================

def check_membership(user_id):
    """
    Returns True if user is subscribed to all configured
    channels.
    """

    if not CHANNELS:
        return True

    for channel in CHANNELS:

        result = telegram(
            "getChatMember",
            {
                "chat_id": channel,
                "user_id": user_id
            }
        )

        if not result.get("ok"):
            logger.warning(
                "Could not check channel %s",
                channel
            )
            return False

        status = result["result"]["status"]

        if status in ("left", "kicked"):
            return False

    return True


def subscription_keyboard():
    buttons = []

    for channel in CHANNELS:
        username = channel.replace("@", "")

        buttons.append([
            {
                "text": f"Join @{username}",
                "url": f"https://t.me/{username}"
            }
        ])

    buttons.append([
        {
            "text": "✅ Check Subscription",
            "callback_data": "check_sub"
        }
    ])

    return {
        "inline_keyboard": buttons
    }


# =========================================================
# FILE EXTRACTION
# =========================================================

def extract_file(message):

    # Document
    if "document" in message:
        document = message["document"]

        return (
            document["file_id"],
            "document",
            document.get("file_name", "file")
        )

    # Video
    if "video" in message:
        video = message["video"]

        return (
            video["file_id"],
            "video",
            "video.mp4"
        )

    # Audio
    if "audio" in message:
        audio = message["audio"]

        return (
            audio["file_id"],
            "audio",
            audio.get("file_name", "audio.mp3")
        )

    # Photo
    if "photo" in message:
        photo = message["photo"][-1]

        return (
            photo["file_id"],
            "photo",
            "photo.jpg"
        )

    # Animation / GIF
    if "animation" in message:
        animation = message["animation"]

        return (
            animation["file_id"],
            "animation",
            animation.get("file_name", "animation.gif")
        )

    return None


# =========================================================
# SEND STORED FILE
# =========================================================

def send_stored_file(chat_id, file_id, file_type, file_name):

    if file_type == "document":
        return telegram(
            "sendDocument",
            {
                "chat_id": chat_id,
                "document": file_id
            }
        )

    if file_type == "video":
        return telegram(
            "sendVideo",
            {
                "chat_id": chat_id,
                "video": file_id
            }
        )

    if file_type == "audio":
        return telegram(
            "sendAudio",
            {
                "chat_id": chat_id,
                "audio": file_id
            }
        )

    if file_type == "photo":
        return telegram(
            "sendPhoto",
            {
                "chat_id": chat_id,
                "photo": file_id
            }
        )

    if file_type == "animation":
        return telegram(
            "sendAnimation",
            {
                "chat_id": chat_id,
                "animation": file_id
            }
        )

    return None


# =========================================================
# START
# =========================================================

def handle_start(message, token=None):

    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    if CHANNELS and not check_membership(user_id):

        send_message(
            chat_id,
            "<b>🔒 Join Required</b>\n\n"
            "Please join all required channels and "
            "then press <b>Check Subscription</b>.",
            subscription_keyboard()
        )

        return

    if token:

        file_row = get_file(token)

        if file_row:

            result = send_stored_file(
                chat_id,
                file_row["file_id"],
                file_row["file_type"],
                file_row["file_name"]
            )

            if result.get("ok") and AUTO_DELETE > 0:

                sent_message_id = result["result"]["message_id"]

                threading.Thread(
                    target=auto_delete_message,
                    args=(
                        chat_id,
                        sent_message_id,
                        AUTO_DELETE
                    ),
                    daemon=True
                ).start()

            return

        batch_files = get_batch_files(token)

        if batch_files:

            send_message(
                chat_id,
                f"📦 <b>Batch found!</b>\n\n"
                f"Files: <b>{len(batch_files)}</b>\n\n"
                "Sending your files..."
            )

            for row in batch_files:

                result = send_stored_file(
                    chat_id,
                    row["file_id"],
                    row["file_type"],
                    row["file_name"]
                )

                if (
                    result.get("ok")
                    and AUTO_DELETE > 0
                ):

                    sent_message_id = result["result"]["message_id"]

                    threading.Thread(
                        target=auto_delete_message,
                        args=(
                            chat_id,
                            sent_message_id,
                            AUTO_DELETE
                        ),
                        daemon=True
                    ).start()

            return

        send_message(
            chat_id,
            "❌ This link is invalid or expired."
        )

        return

    send_message(
        chat_id,
        "<b>👋 Welcome!</b>\n\n"
        "This bot can deliver files using secure links.\n\n"
        "Send a file to generate a link."
    )


# =========================================================
# AUTO DELETE
# =========================================================

def auto_delete_message(chat_id, message_id, seconds):

    try:
        time.sleep(seconds)
        delete_message(chat_id, message_id)

    except Exception as e:
        logger.error(
            "Auto delete error: %s",
            e
        )


# =========================================================
# CALLBACK
# =========================================================

def handle_callback(callback):

    callback_id = callback["id"]
    data = callback.get("data", "")
    message = callback.get("message")

    if not message:
        return

    chat_id = message["chat"]["id"]
    user_id = callback["from"]["id"]

    telegram(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id
        }
    )

    if data == "check_sub":

        if check_membership(user_id):

            send_message(
                chat_id,
                "✅ <b>Subscription verified!</b>\n\n"
                "You can now use the bot."
            )

        else:

            send_message(
                chat_id,
                "❌ You haven't joined all required channels yet.",
                subscription_keyboard()
            )


# =========================================================
# MESSAGE HANDLER
# =========================================================

def handle_message(message):

    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    text = message.get("text", "")

    # -----------------------------------------------------
    # COMMANDS
    # -----------------------------------------------------

    if text.startswith("/start"):

        parts = text.split(maxsplit=1)

        token = None

        if len(parts) == 2:
            token = parts[1].strip()

        handle_start(
            message,
            token
        )

        return

    if text == "/help":

        send_message(
            chat_id,
            "<b>📚 Commands</b>\n\n"
            "/start - Start bot\n"
            "/help - Help\n"
            "/batch - Create batch\n"
            "/cancelbatch - Cancel batch"
        )

        return

    # -----------------------------------------------------
    # BATCH CREATION
    # -----------------------------------------------------

    if text == "/batch":

        if user_id != ADMIN_ID:

            send_message(
                chat_id,
                "❌ Only the bot administrator can create batches."
            )

            return

        token = create_batch(user_id)

        # Save active batch in memory
        ACTIVE_BATCHES[user_id] = token

        send_message(
            chat_id,
            "📦 <b>Batch mode enabled!</b>\n\n"
            "Now send the files one by one.\n\n"
            "When finished, send:\n"
            "<code>/done</code>"
        )

        return

    if text == "/done":

        if user_id != ADMIN_ID:

            return

        token = ACTIVE_BATCHES.get(user_id)

        if not token:

            send_message(
                chat_id,
                "❌ No active batch."
            )

            return

        files = get_batch_files(token)

        if not files:

            send_message(
                chat_id,
                "❌ No files were added."
            )

            return

        del ACTIVE_BATCHES[user_id]

        link = make_link(token)

        send_message(
            chat_id,
            "<b>✅ Batch created!</b>\n\n"
            f"📦 Files: <b>{len(files)}</b>\n\n"
            f"🔗 <b>Link:</b>\n{link}"
        )

        return

    if text == "/cancelbatch":

        if user_id in ACTIVE_BATCHES:
            del ACTIVE_BATCHES[user_id]

        send_message(
            chat_id,
            "❌ Batch cancelled."
        )

        return

    # -----------------------------------------------------
    # FILE
    # -----------------------------------------------------

    extracted
