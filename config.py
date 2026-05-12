"""Configuration for the Amazon affiliate Telegram bot.

Set these values as Render environment variables. Do not hard-code secrets here.
"""

import os


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int_set(value: str) -> set[int]:
    ids: set[int] = set()
    for item in (value or "").replace(" ", "").split(","):
        if item and item.lstrip("-").isdigit():
            ids.add(int(item))
    return ids


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Example India tracking ID: dealzbazaar0
AFFILIATE_TAG = os.getenv("AFFILIATE_TAG", "dealzbazaar0").strip()

# Default output domain. Keep this as www.amazon.in for India Associates tags.
AMAZON_DOMAIN = os.getenv("AMAZON_DOMAIN", "www.amazon.in").strip().lower()

# Your Render URL, e.g. https://amazon-link-bot.onrender.com
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")

# Optional custom short domain. If empty, BASE_URL is used.
SHORT_BASE_URL = os.getenv("SHORT_BASE_URL", BASE_URL).strip().rstrip("/")

# true = bot returns your own short redirect links like https://your-app.onrender.com/a/Ab12CdE
# false = bot returns direct Amazon affiliate links like https://www.amazon.in/dp/ASIN?tag=yourtag
SHORTEN_LINKS = _as_bool(os.getenv("SHORTEN_LINKS", "true"), True)

# On Render free without a disk this file can reset on redeploy. For persistence, attach a disk and use /var/data/bot.db.
DB_PATH = os.getenv("DB_PATH", "bot.db").strip()

# Set a random secret. Telegram sends it back in X-Telegram-Bot-Api-Secret-Token.
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

# Optional comma-separated Telegram user IDs allowed to view /stats.
ADMIN_IDS = _as_int_set(os.getenv("ADMIN_IDS", ""))

# Optional: set this to enable automatic image descriptions.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "12"))
