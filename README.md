# Telegram Amazon Affiliate Link Converter Bot

Original Python Telegram bot for Amazon link conversion. It supports:

- Amazon product links like `/dp/ASIN`, `/gp/product/ASIN`, `/gp/aw/d/ASIN`, review links, and many messy Amazon URLs
- Amazon short URLs like `amzn.in`, `amzn.to`, `a.co`, and redirect-style links if they resolve to Amazon
- Search/category/store Amazon URLs by adding/replacing your `tag` parameter
- Short redirect links from your own Render app: `https://your-app.onrender.com/a/Ab12CdE`
- SQLite logging for conversions, short links, and clicks
- Optional image-to-deal-description mode using `OPENAI_API_KEY`

## Important note about `amznn.in/VlJLEyy` style links

A bot cannot create links on `amznn.in` unless you own that domain or that service gives you an API key.
This bot creates your own short links on your Render domain by default. Example:

```text
https://your-render-service.onrender.com/a/VlJLEyy
```

If you buy/add your own custom domain to Render, you can make links look like:

```text
https://go.yourdomain.in/a/VlJLEyy
```

## Files

- `bot.py` - Flask webhook Telegram bot and short redirect server
- `config.py` - environment variable configuration
- `database.py` - SQLite database layer
- `requirements.txt` - Python dependencies
- `runtime.txt` - Python version for Render
- `.env.example` - local environment template

## Render free hosting setup

1. Create a Telegram bot from `@BotFather` and copy the token.
2. Upload these files to a GitHub repository.
3. In Render, create **New Web Service** from that repository.
4. Use:

```text
Build Command: pip install -r requirements.txt
Start Command: gunicorn bot:app
```

5. Set environment variables:

```text
BOT_TOKEN=your_bot_token
AFFILIATE_TAG=your_amazon_tracking_id
AMAZON_DOMAIN=www.amazon.in
BASE_URL=https://your-render-service.onrender.com
SHORT_BASE_URL=https://your-render-service.onrender.com
SHORTEN_LINKS=true
WEBHOOK_SECRET=any-long-random-secret
ADMIN_IDS=your_telegram_numeric_user_id
```

6. Optional image description:

```text
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
```

7. Deploy. Then open this once in browser to force webhook setup if needed:

```text
https://your-render-service.onrender.com/set-webhook?key=your_WEBHOOK_SECRET
```

## How to use in Telegram

Send:

```text
https://www.amazon.in/dp/B09XBJ1CTN?tag=oldtag
```

Bot returns a short link if `SHORTEN_LINKS=true`:

```text
https://your-render-service.onrender.com/a/Ab12CdE
```

That short link redirects to:

```text
https://www.amazon.in/dp/B09XBJ1CTN?tag=yourtag
```

For image posts, send a photo with Amazon link in caption. If `OPENAI_API_KEY` is set, the bot will generate a short deal caption from the image and include the converted affiliate link.

## Notes

- Use your valid Amazon Associates tracking ID.
- Do not hard-code secrets in code.
- Render free web services may sleep after inactivity, so the first request after sleep can be slower.
- SQLite database on Render free filesystem can reset on redeploy. For persistent stats, attach a persistent disk and set `DB_PATH=/var/data/bot.db`.
