from __future__ import annotations

import io
import json
import os
import re
import hmac
import hashlib
import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

import requests
from fastapi import HTTPException
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from zoneinfo import ZoneInfo
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.constants import ParseMode

from .config import (
    RECEIPTS_DIR,
    SESSION_TTL_SECONDS,
    SHOP_SECRET,
    TLY_TOKEN,
    logger,
    TIMEZONE,
)
from .db import SessionLocal
from .models import WebSession


# -------------------------------------------------------------
# Regex & formatting
# -------------------------------------------------------------

CURRENCY_RE = re.compile(r"^\d+(?:[\.,]\d{1,2})?$")


def format_eur(val: Decimal) -> str:
    s = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s + " €"


# -------------------------------------------------------------
# Session token helpers (shop webapp)
# -------------------------------------------------------------

def token_for_chat(chat_id: int) -> str:
    mac = hmac.new(SHOP_SECRET.encode(), str(chat_id).encode(), hashlib.sha256).hexdigest()
    return mac


def token_valid(chat_id: int, token: str) -> bool:
    expected = token_for_chat(chat_id)
    return hmac.compare_digest(expected, token)


def resolve_session_or_403(token: str) -> WebSession:
    """
    Resolve a session by token or raise 403.
    - 'spesa_live'     -> must be 'attiva'. No TTL.
    - 'estratto_conto' -> valid only until TTL expires. If expired, mark 'scaduta' and 403.
    """
    from sqlalchemy import select

    with SessionLocal() as db:
        ws = db.execute(select(WebSession).where(WebSession.token == token)).scalar_one_or_none()
        if not ws:
            raise HTTPException(status_code=403, detail="Sessione non valida o scaduta")

        if ws.type == "spesa_live":
            if ws.status != "attiva":
                raise HTTPException(status_code=403, detail="Sessione non valida o scaduta")
            return ws

        if ws.type == "estratto_conto":
            if SESSION_TTL_SECONDS > 0:
                age = (dt.datetime.utcnow() - ws.started_at).total_seconds()
                if age > SESSION_TTL_SECONDS:
                    if ws.status != "scaduta":
                        ws.status = "scaduta"
                        ws.ended_at = ws.ended_at or dt.datetime.utcnow()
                        db.commit()
                    raise HTTPException(status_code=403, detail="Sessione scaduta")
            return ws

        if ws.status != "attiva":
            raise HTTPException(status_code=403, detail="Sessione non valida o scaduta")
        return ws


def close_session(token: str) -> None:
    from sqlalchemy import select
    with SessionLocal() as db:
        ws = db.execute(select(WebSession).where(WebSession.token == token)).scalar_one_or_none()
        if ws and ws.status == "attiva":
            ws.status = "scaduta"
            ws.ended_at = dt.datetime.utcnow()
            db.commit()


def send_async_message(app, chat_id: int, text: str, *, reply_markup=None) -> None:
    """Schedule a Telegram message on PTB loop (thread-safe).

    reply_markup: optional Telegram reply markup (e.g., ReplyKeyboardRemove()).
    """
    try:
        app.create_task(
            app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        )
        logger.info(f"scheduled TG message to {chat_id} (len={len(text)})")
    except Exception:
        logger.exception(f"failed to schedule TG message to {chat_id}")
        raise


# -------------------------------------------------------------
# Navigation helpers (stack-based back navigation)
# -------------------------------------------------------------

def nav_reset(context, name: str) -> None:
    stack = [name]
    context.user_data["nav_stack"] = stack
    context.user_data["nav"] = name


def nav_push(context, name: str) -> None:
    stack = context.user_data.get("nav_stack")
    if not isinstance(stack, list):
        stack = []
    if not stack or stack[-1] != name:
        stack.append(name)
    context.user_data["nav_stack"] = stack
    context.user_data["nav"] = name


# -------------------------------------------------------------
# Receipt photo helpers
# -------------------------------------------------------------

FOTO_PREFIX = "Foto"
FOTO_EXT = ".jpg"
FOTO_RX = re.compile(rf"^{re.escape(FOTO_PREFIX)}\s*(\d+)(?:\.[A-Za-z0-9]+)?$", re.IGNORECASE)


def _scan_last_foto_number(dir_path: str) -> int:
    max_n = 0
    try:
        for name in os.listdir(dir_path):
            m = FOTO_RX.match(name)
            if m:
                try:
                    n = int(m.group(1))
                    if n > max_n:
                        max_n = n
                except Exception:
                    pass
    except FileNotFoundError:
        os.makedirs(dir_path, exist_ok=True)
    return max_n


def reserve_next_foto_path(dir_path: str, ext: str = FOTO_EXT) -> str:
    os.makedirs(dir_path, exist_ok=True)
    n = _scan_last_foto_number(dir_path) + 1
    while True:
        candidate = os.path.join(dir_path, f"{FOTO_PREFIX} {n}{ext}")
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            return candidate
        except FileExistsError:
            n += 1


async def show_back_keyboard(context, chat_id: int):
    from .keyboards import BACK_TEXT

    kb = ReplyKeyboardMarkup([[KeyboardButton(BACK_TEXT)]], resize_keyboard=True, one_time_keyboard=False)
    await context.bot.send_message(chat_id=chat_id, text="Ecco a te la scheda precedente", reply_markup=kb)


async def hide_reply_keyboard(context, chat_id: int):
    await context.bot.send_message(chat_id=chat_id, text=" ", reply_markup=ReplyKeyboardRemove())


async def clear_intro_if_any(context, chat_id: int):
    intro_id = context.user_data.get("intro_msg_id")
    if intro_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=intro_id)
        except Exception:
            pass
        context.user_data.pop("intro_msg_id", None)


def shorten_url(long_url: str) -> str:
    if not TLY_TOKEN:
        return long_url
    try:
        r = requests.post(
            "https://t.ly/api/v1/link/shorten",
            json={"long_url": long_url},
            headers={"Authorization": f"Bearer {TLY_TOKEN}", "Content-Type": "application/json"},
            timeout=10,
        )
        if r.ok:
            data = r.json()
            return data.get("short_url") or long_url
    except Exception:
        logger.exception("[t.ly] shorten failed")
    return long_url


def _to_display_tz(d: dt.datetime, tz_name: str = TIMEZONE) -> dt.datetime:
    """Convert a datetime to the configured display timezone.

    - Treat naive datetimes as UTC (stored values are UTC-based).
    - Use ZoneInfo(tz_name) when available; fall back to local system tz.
    """
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = dt.datetime.now().astimezone().tzinfo
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(tz)


def first_tx_datetime():
    from sqlalchemy import select, func
    from .models import Transaction

    with SessionLocal() as db:
        row = db.execute(select(func.min(Transaction.date))).scalar()
        return row


def build_statement_pdf_bytes(rows, foto_col_text: List[str]) -> bytes:
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title = styles["Title"]

    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=9, leading=12, alignment=TA_LEFT)
    cell_right = ParagraphStyle("cell_right", parent=styles["Normal"], fontSize=9, leading=12, alignment=TA_RIGHT)

    elems = [Paragraph("<b>Estratto conto – Fondo cassa comune</b>", title), Spacer(1, 8)]

    page_w, _ = A4
    content_w = page_w - doc.leftMargin - doc.rightMargin
    w_data = 25 * mm
    w_amount = 25 * mm
    w_op = 32 * mm
    w_operator = 35 * mm
    w_foto = content_w - (w_data + w_amount + w_op + w_operator)

    header = ["Data", "Transazione", "Operazione", "Operatore", "Foto ricevuta"]
    data = [header]

    for tx, foto_txt in zip(rows, foto_col_text):
        data.append(
            [
                Paragraph(_to_display_tz(tx.date).strftime("%d/%m/%Y %H:%M"), cell),
                Paragraph(f"{tx.amount:.2f}", cell_right),
                Paragraph(tx.operation or "", cell),
                Paragraph(f"{tx.nome} {tx.cognome}".strip(), cell),
                Paragraph(foto_txt or "Foto assente", cell),
            ]
        )

    table = Table(data, repeatRows=1, colWidths=[w_data, w_amount, w_op, w_operator, w_foto])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEADING", (0, 0), (-1, -1), 12),
            ]
        )
    )

    elems.append(table)
    doc.build(elems)
    return buf.getvalue()
