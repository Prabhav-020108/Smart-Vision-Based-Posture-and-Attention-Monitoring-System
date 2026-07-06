"""Minimal Telegram bot notifier — the project's IoT channel.

Rather than teaching the ESP32 to speak WiFi, the laptop (which is already
online to serve the dashboard) pushes a message straight to a Telegram chat
whenever a serious alert fires. A phone buzzing from across the room is a
more convincing live demonstration of "this system reaches beyond the
laptop" than adding networking firmware to the microcontroller would be,
for a fraction of the implementation risk.

Setup (see README): message @BotFather on Telegram to create a bot and get
a token, then message your new bot once and use the getUpdates endpoint (or
@userinfobot) to find your numeric chat id. Put both in .env.

If TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set, every function here is
a harmless no-op — the rest of the app is unaffected either way.
"""

from __future__ import annotations

import threading

import requests

from src.utils.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
_REQUEST_TIMEOUT_SECONDS = 5


def send_telegram_message(text: str) -> bool:
    """Send a message to the configured chat. Returns True on success.

    This makes a blocking HTTP call — never call this directly from the
    vision worker loop (a slow or unreachable network would stall frame
    processing, which is exactly the class of bug the reliability fix
    elsewhere in this project exists to prevent). Use
    ``send_telegram_message_async`` from anywhere in the hot path instead.
    """

    if not TELEGRAM_ENABLED:
        return False

    try:
        response = requests.post(
            _API_URL,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        ok = response.status_code == 200
        if not ok:
            print(f"[telegram] Send failed: {response.status_code} {response.text[:200]}")
        return ok
    except Exception as exc:
        print(f"[telegram] Send error: {exc}")
        return False


def send_telegram_message_async(text: str) -> None:
    """Fire-and-forget variant — safe to call from the vision worker loop."""

    if not TELEGRAM_ENABLED:
        return
    threading.Thread(target=send_telegram_message, args=(text,), daemon=True).start()
