from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, parse_qs, quote_plus, unquote, urlencode, urlparse, urlunparse

import requests
from flask import Flask, abort, jsonify, redirect, request

import config
import database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
database.init_db()

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
ASIN_PATTERNS = [
    re.compile(r"/(?:dp|gp/product|gp/aw/d|product-reviews)/([A-Z0-9]{10})(?:[/?#]|$)", re.I),
    re.compile(r"/(?:exec/obidos/ASIN|o/ASIN)/([A-Z0-9]{10})(?:[/?#]|$)", re.I),
]
SHORT_AMAZON_HOSTS = {
    "amzn.in",
    "www.amzn.in",
    "amzn.to",
    "www.amzn.to",
    "a.co",
    "www.a.co",
    # Added because many Indian deal bots use/look for this style. It will only work if the URL redirects.
    "amznn.in",
    "www.amznn.in",
}
TRAILING_PUNCTUATION = ".,!?;:)]}"


@dataclass
class ConversionResult:
    original_url: str
    target_url: str
    output_url: str
    asin: str | None = None
    short_code: str | None = None
    resolved_url: str | None = None


def telegram_api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.BOT_TOKEN}/{method}"


def is_amazon_host(hostname: str) -> bool:
    host = hostname.lower().split(":", 1)[0]
    return host in SHORT_AMAZON_HOSTS or "amazon." in host


def is_short_amazon_host(hostname: str) -> bool:
    return hostname.lower().split(":", 1)[0] in SHORT_AMAZON_HOSTS


def split_url_punctuation(raw_url: str) -> tuple[str, str]:
    suffix = ""
    url = raw_url
    while url and url[-1] in TRAILING_PUNCTUATION:
        suffix = url[-1] + suffix
        url = url[:-1]
    return url, suffix


def resolve_url(url: str) -> str:
    """Follow redirects for Amazon short URLs. Falls back to the original URL on failure."""
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            timeout=config.REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 AmazonAffiliateTelegramBot/1.0"},
        )
        return response.url or url
    except requests.RequestException as exc:
        log.warning("Could not resolve URL %s: %s", url, exc)
        return url


def extract_asin(url: str) -> str | None:
    parsed = urlparse(url)
    path = unquote(parsed.path or "")

    for pattern in ASIN_PATTERNS:
        match = pattern.search(path)
        if match:
            return match.group(1).upper()

    query = parse_qs(parsed.query)
    for key in ("asin", "ASIN"):
        for value in query.get(key, []):
            value = value.strip().upper()
            if re.fullmatch(r"[A-Z0-9]{10}", value):
                return value

    # Fallback for uncommon Amazon paths where ASIN is a standalone path segment.
    for segment in path.split("/"):
        segment = segment.strip().upper()
        if re.fullmatch(r"[A-Z0-9]{10}", segment):
            return segment
    return None


def build_direct_affiliate_url(asin: str) -> str:
    return f"https://{config.AMAZON_DOMAIN}/dp/{asin}?tag={quote_plus(config.AFFILIATE_TAG)}"


def add_affiliate_tag_to_url(url: str) -> str:
    parsed = urlparse(url)
    query_items = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() != "tag"]
    query_items.append(("tag", config.AFFILIATE_TAG))
    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc,
            parsed.path or "/",
            "",
            urlencode(query_items, doseq=True),
            "",
        )
    )


def convert_amazon_url(url: str) -> ConversionResult | None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc or not is_amazon_host(parsed.netloc):
        return None

    asin = extract_asin(url)
    resolved_url: str | None = None

    if not asin or is_short_amazon_host(parsed.netloc):
        resolved_url = resolve_url(url)
        asin = extract_asin(resolved_url)

    if asin:
        target_url = build_direct_affiliate_url(asin)
    else:
        # Search/category/store pages do not always contain an ASIN, so keep their URL and replace/add tag.
        target_url = add_affiliate_tag_to_url(resolved_url or url)

    short_code = None
    output_url = target_url
    if config.SHORTEN_LINKS and config.SHORT_BASE_URL:
        short_code = database.create_or_get_short_link(target_url, original_url=url, asin=asin)
        output_url = f"{config.SHORT_BASE_URL}/a/{short_code}"

    return ConversionResult(
        original_url=url,
        target_url=target_url,
        output_url=output_url,
        asin=asin,
        short_code=short_code,
        resolved_url=resolved_url,
    )


def convert_text_links(text: str, chat_id: int | None, user: dict[str, Any] | None) -> tuple[str, list[ConversionResult]]:
    conversions: list[ConversionResult] = []

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        clean_url, suffix = split_url_punctuation(raw)
        result = convert_amazon_url(clean_url)
        if not result:
            return raw

        conversions.append(result)
        database.log_conversion(
            chat_id=chat_id,
            user_id=user.get("id") if user else None,
            username=user.get("username") if user else None,
            original_url=result.original_url,
            target_url=result.target_url,
            output_url=result.output_url,
            short_code=result.short_code,
            asin=result.asin,
        )
        return result.output_url + suffix

    return URL_RE.sub(replace, text), conversions


def send_message(chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
    if not config.BOT_TOKEN:
        log.error("BOT_TOKEN is missing; cannot send message")
        return

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": False,
    }
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}

    try:
        response = requests.post(telegram_api("sendMessage"), json=payload, timeout=config.REQUEST_TIMEOUT)
        if not response.ok:
            log.warning("sendMessage failed: %s", response.text)
    except requests.RequestException as exc:
        log.warning("sendMessage error: %s", exc)


def get_telegram_file_bytes(file_id: str) -> bytes | None:
    try:
        file_response = requests.get(
            telegram_api("getFile"), params={"file_id": file_id}, timeout=config.REQUEST_TIMEOUT
        )
        file_response.raise_for_status()
        file_path = file_response.json()["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{config.BOT_TOKEN}/{file_path}"
        data_response = requests.get(download_url, timeout=config.REQUEST_TIMEOUT)
        data_response.raise_for_status()
        return data_response.content
    except (KeyError, requests.RequestException, ValueError) as exc:
        log.warning("Could not download Telegram file: %s", exc)
        return None


def describe_image(image_bytes: bytes) -> str | None:
    if not config.OPENAI_API_KEY:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Create a short Indian shopping deal caption from this image. "
                                "Do not invent exact price, discount, brand, model, or claims that are not visible. "
                                "Use natural Hinglish/Hindi style. Keep it under 70 words."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded}", "detail": "low"},
                        },
                    ],
                }
            ],
            max_tokens=180,
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception as exc:  # External API failures should not break Telegram webhook handling.
        log.warning("Image description failed: %s", exc)
        return None


def start_text() -> str:
    mode = "short links" if config.SHORTEN_LINKS else "direct Amazon affiliate links"
    return (
        "Namaste! Amazon Affiliate Link Converter ready hai.\n\n"
        "Use:\n"
        "1) Amazon product/search link bhejo.\n"
        "2) Photo + caption me Amazon link bhejo, main caption link convert kar dunga.\n"
        "3) OPENAI_API_KEY set hoga to image se short deal description bhi auto ban sakti hai.\n\n"
        f"Current output mode: {mode}\n"
        f"Affiliate tag: {config.AFFILIATE_TAG}"
    )


def help_text() -> str:
    return (
        "Examples:\n"
        "https://www.amazon.in/dp/B09XBJ1CTN\n"
        "https://amzn.in/xxxxxxx\n\n"
        "Bot product links ko clean affiliate URL me convert karta hai. "
        "SHORTEN_LINKS=true aur BASE_URL set hone par output your-app.onrender.com/a/code jaisa short link hota hai.\n\n"
        "Commands: /start, /help, /stats"
    )


def handle_command(text: str, chat_id: int, user: dict[str, Any] | None, message_id: int | None) -> bool:
    command = text.split()[0].split("@", 1)[0].lower()
    if command == "/start":
        send_message(chat_id, start_text(), message_id)
        return True
    if command == "/help":
        send_message(chat_id, help_text(), message_id)
        return True
    if command == "/stats":
        if not config.ADMIN_IDS:
            send_message(chat_id, "ADMIN_IDS env var set karo, phir /stats private rahega.", message_id)
            return True
        if not user or user.get("id") not in config.ADMIN_IDS:
            send_message(chat_id, "Sorry, /stats sirf admin ke liye hai.", message_id)
            return True
        stats = database.get_stats()
        send_message(
            chat_id,
            f"Stats:\nConversions: {stats['conversions']}\nShort links: {stats['links']}\nClicks: {stats['clicks']}",
            message_id,
        )
        return True
    return False
if command == "/addchannel" and user.get("id") in config.ADMIN_IDS:
    try:
        new_chat_id = int(text.split()[1])
        database.add_auto_post_channel(new_chat_id)
        send_message(chat_id, f"Channel/group {new_chat_id} added for auto-posting.", message_id)
    except (IndexError, ValueError):
        send_message(chat_id, "Usage: /addchannel <chat_id>", message_id)
    return True

if command == "/removechannel" and user.get("id") in config.ADMIN_IDS:
    try:
        remove_chat_id = int(text.split()[1])
        database.remove_auto_post_channel(remove_chat_id)
        send_message(chat_id, f"Channel/group {remove_chat_id} removed.", message_id)
    except (IndexError, ValueError):
        send_message(chat_id, "Usage: /removechannel <chat_id>", message_id)
    return True

def process_message(message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return

    user = message.get("from") or {}
    message_id = message.get("message_id")
    text = message.get("text") or message.get("caption") or ""
    has_photo = bool(message.get("photo"))

    # Handle commands first
    if text.startswith("/") and handle_command(text, chat_id, user, message_id):
        return

    # Convert any Amazon links in text
    converted_text, conversions = convert_text_links(text, chat_id, user)

    # Image description
    image_description = None
    image_bytes = None
    if has_photo and config.OPENAI_API_KEY:
        file_id = message["photo"][-1].get("file_id")
        image_bytes = get_telegram_file_bytes(file_id) if file_id else None
        if image_bytes:
            image_description = describe_image(image_bytes)

    # Prepare message to send to the user
    parts: list[str] = []
    if has_photo:
        if image_description:
            parts.append(image_description)
        if conversions:
            parts.append(converted_text.strip())
        if not parts:
            if config.OPENAI_API_KEY:
                parts.append("Image mila, lekin Amazon link nahi mila. Caption me Amazon product link bhejo.")
            else:
                parts.append(
                    "Image mila. Auto description ke liye OPENAI_API_KEY set karo, "
                    "aur affiliate link ke liye image caption me Amazon product link bhejo."
                )
        # Send photo with caption
        if image_bytes:
            send_photo(chat_id, image_bytes, caption="\n\n".join(parts))
        else:
            send_message(chat_id, "\n\n".join(parts), message_id)
    elif conversions:
        # Send converted text for links only
        send_message(chat_id, converted_text.strip(), message_id)
    elif text.strip():
        send_message(chat_id, "Amazon link nahi mila. Product link bhejo, main affiliate/short link bana dunga.", message_id)
    else:
        send_message(chat_id, help_text(), message_id)

    # ---------------- Auto-post to all configured channels ----------------
    # Caption or message text to post
    caption_text = "\n\n".join(parts) if has_photo else (converted_text.strip() if conversions else text.strip())
    auto_post_to_channels(image_bytes if has_photo else None, caption_text)
    user = message.get("from") or {}
    message_id = message.get("message_id")
    text = message.get("text") or message.get("caption") or ""
    has_photo = bool(message.get("photo"))

    if text.startswith("/") and handle_command(text, chat_id, user, message_id):
        return

    converted_text, conversions = convert_text_links(text, chat_id, user)

    image_description = None
    if has_photo and config.OPENAI_API_KEY:
        file_id = message["photo"][-1].get("file_id")
        image_bytes = get_telegram_file_bytes(file_id) if file_id else None
        if image_bytes:
            image_description = describe_image(image_bytes)

    if has_photo:
        parts: list[str] = []
        if image_description:
            parts.append(image_description)
        if conversions:
            parts.append(converted_text.strip())
        if not parts:
            if config.OPENAI_API_KEY:
                parts.append("Image mila, lekin Amazon link nahi mila. Caption me Amazon product link bhejo.")
            else:
                parts.append(
                    "Image mila. Auto description ke liye OPENAI_API_KEY set karo, "
                    "aur affiliate link ke liye image caption me Amazon product link bhejo."
                )
        send_message(chat_id, "\n\n".join(parts), message_id)
        return

    if conversions:
        send_message(chat_id, converted_text.strip(), message_id)
        return

    if text.strip():
        send_message(chat_id, "Amazon link nahi mila. Product link bhejo, main affiliate/short link bana dunga.", message_id)
    else:
        send_message(chat_id, help_text(), message_id)


def process_update(update: dict[str, Any]) -> None:
    message = update.get("message") or update.get("edited_message")
    if message:
        process_message(message)


def setup_webhook() -> tuple[bool, str]:
    if not config.BOT_TOKEN:
        return False, "BOT_TOKEN missing"
    if not config.BASE_URL:
        return False, "BASE_URL missing"

    payload: dict[str, Any] = {
        "url": f"{config.BASE_URL}/webhook",
        "allowed_updates": ["message", "edited_message"],
        "drop_pending_updates": False,
    }
    if config.WEBHOOK_SECRET:
        payload["secret_token"] = config.WEBHOOK_SECRET

    try:
        response = requests.post(telegram_api("setWebhook"), json=payload, timeout=config.REQUEST_TIMEOUT)
        if response.ok:
            return True, response.text
        return False, response.text
    except requests.RequestException as exc:
        return False, str(exc)


@app.get("/")
def index():
    return jsonify(
        {
            "ok": True,
            "service": "Amazon Affiliate Telegram Bot",
            "mode": "short" if config.SHORTEN_LINKS else "direct",
        }
    )


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/set-webhook")
def set_webhook_route():
    if config.WEBHOOK_SECRET and request.args.get("key") != config.WEBHOOK_SECRET:
        abort(403)
    ok, details = setup_webhook()
    return jsonify({"ok": ok, "details": details})


@app.get("/a/<code>")
def short_redirect(code: str):
    target_url = database.get_target_url(code)
    if not target_url:
        abort(404)
    database.record_click(code)
    return redirect(target_url, code=302)


@app.post("/webhook")
def telegram_webhook():
    if config.WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if token != config.WEBHOOK_SECRET:
            abort(403)

    update = request.get_json(silent=True) or {}
    try:
        process_update(update)
    except Exception as exc:
        log.exception("Update processing failed: %s", exc)
    return jsonify({"ok": True})


if config.BOT_TOKEN and config.BASE_URL:
    ok, details = setup_webhook()
    log.info("Webhook setup: ok=%s details=%s", ok, details)
else:
    log.warning("BOT_TOKEN or BASE_URL missing; webhook was not configured")


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
