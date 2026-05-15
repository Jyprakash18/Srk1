import base64
import logging
import re
from flask import Flask, request, jsonify, abort, redirect
from urllib.parse import urlparse
import requests

import config
import database

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
database.init_db()

# -------------------- Telegram helpers --------------------
def telegram_api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.BOT_TOKEN}/{method}"

def send_message(chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
    payload = {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": False}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    try:
        r = requests.post(telegram_api("sendMessage"), json=payload, timeout=config.REQUEST_TIMEOUT)
        if not r.ok:
            log.warning("sendMessage failed: %s", r.text)
    except Exception as e:
        log.warning("sendMessage exception: %s", e)

def send_photo(chat_id: int, photo_bytes: bytes, caption: str | None = None) -> None:
    files = {"photo": ("image.jpg", photo_bytes)}
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption[:1024]
    try:
        r = requests.post(telegram_api("sendPhoto"), files=files, data=data, timeout=config.REQUEST_TIMEOUT)
        if not r.ok:
            log.warning("sendPhoto failed: %s", r.text)
    except Exception as e:
        log.warning("sendPhoto exception: %s", e)

# -------------------- Auto-post channels --------------------
def auto_post_to_channels(photo_bytes: bytes | None, text: str) -> None:
    channels = database.get_auto_post_channels()
    for chat_id in channels:
        try:
            log.info(f"Auto-post attempt to {chat_id}: {text[:50]}...")
            if photo_bytes:
                send_photo(chat_id, photo_bytes, caption=text)
            else:
                send_message(chat_id, text)
        except Exception as e:
            log.warning(f"Failed auto-post to {chat_id}: {e}")

# -------------------- Handle commands --------------------
def handle_command(text: str, chat_id: int, user: dict | None, message_id: int | None) -> bool:
    command = text.split()[0].split("@")[0].lower()
    
    if command == "/start":
        send_message(chat_id, "Bot ready!", message_id)
        return True

    if command == "/help":
        send_message(chat_id, "Send Amazon links or images.", message_id)
        return True

    # ---- Add channel admin commands ----
    if command == "/addchannel" and user and user.get("id") in config.ADMIN_IDS:
        try:
            new_chat_id = int(text.split()[1])
            database.add_auto_post_channel(new_chat_id)
            send_message(chat_id, f"Channel/group {new_chat_id} added for auto-posting.", message_id)
        except:
            send_message(chat_id, "Usage: /addchannel <chat_id>", message_id)
        return True

    if command == "/removechannel" and user and user.get("id") in config.ADMIN_IDS:
        try:
            remove_chat_id = int(text.split()[1])
            database.remove_auto_post_channel(remove_chat_id)
            send_message(chat_id, f"Channel/group {remove_chat_id} removed.", message_id)
        except:
            send_message(chat_id, "Usage: /removechannel <chat_id>", message_id)
        return True

    return False

# -------------------- Process messages --------------------
def process_message(message: dict) -> None:
    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        return
    user = message.get("from")
    message_id = message.get("message_id")
    text = message.get("text") or message.get("caption") or ""
    has_photo = bool(message.get("photo"))

    if text.startswith("/") and handle_command(text, chat_id, user, message_id):
        return

    # ----- Image processing -----
    image_bytes = None
    image_description = None
    if has_photo and config.OPENAI_API_KEY:
        file_id = message["photo"][-1].get("file_id")
        if file_id:
            try:
                file_info = requests.get(telegram_api("getFile"), params={"file_id": file_id}).json()
                file_path = file_info["result"]["file_path"]
                download_url = f"https://api.telegram.org/file/bot{config.BOT_TOKEN}/{file_path}"
                image_bytes = requests.get(download_url).content
            except Exception as e:
                log.warning(f"Image download failed: {e}")
        # Optional: Add OpenAI image description here

    # ----- Compose message to send -----
    parts = []
    if has_photo and image_bytes:
        if image_description:
            parts.append(image_description)
        parts.append(text)
        send_photo(chat_id, image_bytes, caption="\n\n".join(parts))
    elif text:
        send_message(chat_id, text, message_id)

    # ----- Auto-post to all configured channels -----
    caption_text = "\n\n".join(parts) if parts else text
    auto_post_to_channels(image_bytes if has_photo else None, caption_text)

# -------------------- Webhook -----
@app.post("/webhook")
def telegram_webhook():
    update = request.get_json(force=True, silent=True) or {}
    try:
        message = update.get("message") or update.get("edited_message")
        if message:
            process_message(message)
    except Exception as e:
        log.exception("Error processing update: %s", e)
    return jsonify({"ok": True})

# -------------------- Run server --------------------
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
