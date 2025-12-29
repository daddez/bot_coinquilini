from __future__ import annotations

import asyncio
import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .config import SESSIONS, SESSIONS_LOCK, logger
from .db import SessionLocal
from .keyboards import CLEANING_LABEL, DAYS
from .models import CleaningArea


async def purge_sessions_task():
    while True:
        await asyncio.sleep(60)
        now = dt.datetime.utcnow()
        with SESSIONS_LOCK:
            for sid in list(SESSIONS.keys()):
                if now > SESSIONS[sid]["expires_at"]:
                    del SESSIONS[sid]


async def cleaning_notifier_task(telegram_app):
    """Send daily cleaning reminders between 08:00 and 10:00 UTC.
    Avoid duplicates within the same day per area.
    """
    _last_sent = {}  # {luogo: 'YYYY-MM-DD'}
    while True:
        try:
            now = dt.datetime.utcnow()
            if 8 <= now.hour < 10:
                today_str = now.date().isoformat()
                weekday = now.weekday()
                day_it = DAYS[weekday]
                with SessionLocal() as db:
                    areas = db.execute(  # type: ignore
                        __import__("sqlalchemy").sql.select(CleaningArea)
                    ).scalars().all()
                for a in areas:
                    if (a.giorno or "").lower() == "da decidere":
                        continue
                    if a.giorno != day_it:
                        continue
                    if _last_sent.get(a.luogo) == today_str:
                        continue
                    if not a.prossimo:
                        continue
                    label = CLEANING_LABEL.get(a.luogo, a.luogo)
                    try:
                        kb = InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "Ok, ho pulito", callback_data=f"cleaning:done:{a.luogo}"
                                    )
                                ]
                            ]
                        )
                        await telegram_app.bot.send_message(
                            chat_id=a.prossimo,
                            text=(
                                "🧹 Oggi è il giorno delle pulizie,\n"
                                f"ti tocca pulire: <b>{label}</b>"
                            ),
                            reply_markup=kb,
                            parse_mode=ParseMode.HTML,
                        )
                        _last_sent[a.luogo] = today_str
                    except Exception:
                        pass
            await asyncio.sleep(60)
        except Exception:
            await asyncio.sleep(60)

