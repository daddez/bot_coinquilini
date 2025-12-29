from __future__ import annotations

import os
import threading

import uvicorn

from .bot.app import build_bot_app, set_telegram_app, start_polling_bot
from .config import BOT_TOKEN
from .db import ensure_minimum_data, init_db
from .web.app import app as fastapi_app


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Errore: BOT_TOKEN non impostato nelle variabili d'ambiente")
    init_db()
    ensure_minimum_data()

    # Build and start Telegram bot in a separate thread
    tg_app = build_bot_app()
    set_telegram_app(tg_app)
    t = threading.Thread(target=start_polling_bot, name="bot-thread", daemon=True)
    t.start()

    uvicorn.run(fastapi_app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))


if __name__ == "__main__":
    main()

