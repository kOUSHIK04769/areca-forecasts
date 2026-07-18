"""
src/notify/telegram.py
=======================
Sends the daily prediction summary to a Telegram chat via a bot.

Setup (one-time):
  1. Message @BotFather on Telegram, /newbot, copy the token into
     TELEGRAM_BOT_TOKEN in your .env.
  2. Message your new bot once (anything), then visit
     https://api.telegram.org/bot<TOKEN>/getUpdates and read your
     chat id from the JSON reply -> put it in TELEGRAM_CHAT_ID.

Other channels (WhatsApp via Twilio, Discord webhook, email/SMTP) follow
the same "format message -> POST to provider" shape; ask for those and
they'll be added as src/notify/whatsapp.py, discord.py, email_alert.py.
"""

from __future__ import annotations

import requests

from config import settings
from src.logging_setup import get_logger

log = get_logger(__name__)


def format_summary(prediction: dict) -> str:
    tomorrow = prediction["tomorrow"]
    lines = [
        f"*Shivamogga Arecanut - Daily Forecast*",
        f"Current price: ₹{prediction['current_price']:,.0f}/qtl",
        f"Tomorrow ({tomorrow['date']}): ₹{tomorrow['predicted_price']:,.0f} "
        f"(confidence {tomorrow['confidence_pct']:.0f}%)",
        f"Direction: {prediction['market_direction']} | "
        f"Call: *{prediction['recommendation']}* | Risk: {prediction['risk_level']}",
        "",
        "Why:",
    ]
    lines += [f"- {r}" for r in prediction["reasons"][:5]]
    return "\n".join(lines)


def send_telegram_alert(prediction: dict) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.info("Telegram not configured (TELEGRAM_BOT_TOKEN/CHAT_ID missing) - skipping alert.")
        return False

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": format_summary(prediction),
        "parse_mode": "Markdown",
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("Telegram alert sent.")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram alert failed: %s", exc)
        return False
