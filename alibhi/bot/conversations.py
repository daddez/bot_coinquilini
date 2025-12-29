from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes, ConversationHandler

from ..config import (
    ACCOUNTING_GIF_DIR,
    BASE_URL,
    BUSY_FLAG,
    IN_CONTAB_FLAG,
    RECEIPTS_DIR,
    logger,
)
from ..db import SessionLocal, create_web_session
from ..keyboards import spesa_kb, spesa_view_actions_kb
from ..models import Product, Transaction, User
from ..schemas import PENDING, PENDING_LOCK, PendingPurchase
from ..utils import (
    CURRENCY_RE,
    clear_intro_if_any,
    nav_push,
    first_tx_datetime,
    build_statement_pdf_bytes,
    shorten_url,
)


# ---------- Conversation state constants ----------
ADD_NAME, ADD_BULK = range(2)
RM_SELECT, RM_CONFIRM = range(2)
MANUAL_SELECT = 2

ASK_START_DATE, ASK_END_DATE = range(2)


# ---------- Aggiungi prodotto ----------
async def spesa_add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Aggiungere singolo prodotto", callback_data="add:single")],
            [InlineKeyboardButton("🧾 Aggiungi più prodotti", callback_data="add:multi")],
        ]
    )
    await query.edit_message_text("Come vuoi aggiungere?", reply_markup=kb)
    nav_push(context, "add")


async def add_single_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Inserisci il nome del prodotto da aggiungere:")
    nav_push(context, "add")
    return ADD_NAME


async def add_multi_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Inserisci i prodotti separati da punto e virgola (es: carne; 1.5kg farina 00; 3kg carne macinata; ...)"
    )
    nav_push(context, "add")
    return ADD_BULK


async def spesa_add_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Nessun testo inserito. Riprova con un elenco separato da ;")
        return ADD_BULK
    parts = [p.strip() for p in re.split(r"\s*;\s*", text) if p.strip()]
    if not parts:
        await update.message.reply_text("Formato non valido. Esempio: carne; 1.5kg farina 00; 3kg carne macinata")
        return ADD_BULK
    with SessionLocal() as db:
        for name in parts:
            db.add(Product(name=name, status="da_acquistare"))
        db.commit()
        logger.info(f"[spesa_add_bulk] Inseriti {len(parts)} prodotti: {parts}")
    chat_id = update.effective_chat.id
    sent = await context.bot.send_message(chat_id=chat_id, text=f"Ho aggiunto {len(parts)} prodotti ✅.")
    await asyncio.sleep(2)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=chat_id,
        text="Rieccoci nella sezione per gestire le spese presenti e future. Scegli cosa vuoi fare:",
        reply_markup=spesa_kb(),
    )
    return ConversationHandler.END


async def spesa_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Il nome non può essere vuoto. Inseriscilo di nuovo:")
        return ADD_NAME
    with SessionLocal() as db:
        db.add(Product(name=name, status="da_acquistare"))
        db.commit()
        logger.info(f"[spesa_add_name] Inserito prodotto: {name}")
    chat_id = update.effective_chat.id
    sent = await context.bot.send_message(chat_id=chat_id, text=f"Prodotto aggiunto: {name} ✅.")
    await asyncio.sleep(2)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=chat_id,
        text="Eccoci nella sezione per gestire le spese presenti e future. Scegli cosa vuoi fare:",
        reply_markup=spesa_kb(),
    )
    return ConversationHandler.END


async def spesa_add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operazione annullata.", reply_markup=spesa_kb())
    context.user_data.pop("add_name", None)
    return ConversationHandler.END


# ---------- Rimuovi prodotto ----------
async def spesa_rm_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    with SessionLocal() as db:
        products = (
            db.execute(select(Product).where(Product.status == "da_acquistare").order_by(Product.created_at.asc()))
            .scalars()
            .all()
        )
    if not products:
        await query.edit_message_text("La lista è vuota, nulla da rimuovere.", reply_markup=spesa_view_actions_kb())
        return ConversationHandler.END
    index_map = {i + 1: p.id for i, p in enumerate(products)}
    context.user_data["rm_index_map"] = index_map
    pretty = [f"{i}) {p.name}" for i, p in enumerate(products, start=1)]
    await query.edit_message_text(
        "Elenco dei prodotti ancora da acquistare:\n"
        + "\n".join(pretty)
        + "\n\nIndicami i numeri da eliminare, separati da virgola (es: 1,2,5)"
    )
    nav_push(context, "remove")
    return RM_SELECT


async def spesa_rm_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Inserisci almeno un indice valido.")
        return RM_SELECT
    raw = [t.strip() for t in text.split(",") if t.strip()]
    if not raw:
        await update.message.reply_text("Formato non valido. Esempio: 1,2,5")
        return RM_SELECT
    index_map: Dict[int, int] = context.user_data.get("rm_index_map", {})
    invalid = [x for x in raw if not x.isdigit() or int(x) not in index_map]
    if invalid:
        await update.message.reply_text(
            f"Mi dispiace, ma i seguenti numeri da te indicati non sono associati ad alcun prodotto: {', '.join(invalid)}. Riprova:"
        )
        return RM_SELECT
    ids = [index_map[int(x)] for x in raw]
    context.user_data["rm_ids"] = ids
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Sì, elimina", callback_data="rm:confirm")],
            [InlineKeyboardButton("❌ Annulla", callback_data="rm:cancel")],
        ]
    )
    await update.message.reply_text(f"Confermi l'eliminazione di {len(ids)} prodotto/i?", reply_markup=kb)
    return RM_CONFIRM


async def spesa_rm_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.endswith("cancel"):
        await query.edit_message_text("Operazione annullata.", reply_markup=spesa_kb())
        context.user_data.pop("rm_index_map", None)
        context.user_data.pop("rm_ids", None)
        return ConversationHandler.END
    ids = context.user_data.get("rm_ids", [])
    with SessionLocal() as db:
        for _id in ids:
            p = db.get(Product, _id)
            if p:
                db.delete(p)
        db.commit()
    await query.edit_message_text("Prodotti eliminati.", reply_markup=spesa_kb())
    context.user_data.pop("rm_index_map", None)
    context.user_data.pop("rm_ids", None)
    return ConversationHandler.END


# ---------- Registrazione manuale spesa ----------
async def spesa_manual_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    balance_id = context.user_data.pop("spesa_balance_msg_id", None)
    if balance_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=balance_id)
        except Exception:
            pass
    with SessionLocal() as db:
        products = (
            db.execute(select(Product).where(Product.status == "da_acquistare").order_by(Product.created_at.asc()))
            .scalars()
            .all()
        )
    if not products:
        with PENDING_LOCK:
            PENDING[chat_id] = PendingPurchase(
                items=[],
                stage="await_cost",
                start_time=dt.datetime.utcnow().replace(tzinfo=None),
            )
        await query.edit_message_text(
            "Potresti dirmi quanto hai speso? Indica solo il numero, senza simboli o lettere (es. 12.50)."
        )
        return ConversationHandler.END
    index_map = {i + 1: p.id for i, p in enumerate(products)}
    context.user_data["manual_index_map"] = index_map
    pretty = [f"{i}) {p.name}" for i, p in enumerate(products, start=1)]
    text = (
        "Hai acquistato uno di questi prodotti?\n"
        + "\n".join(pretty)
        + '\n\nSe sì, indica i numeri acquistati separati da punto e virgola (es. "1; 2; 6").\n'
        'Se non hai acquistato nessuno di questi, scrivi semplicemente "No".'
    )
    await query.edit_message_text(text)
    nav_push(context, "manual")
    return MANUAL_SELECT


async def spesa_manual_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    raw = (update.message.text or "").strip()
    norm = re.sub(r"[^a-zA-ZàèéìòóùÀÈÉÌÒÓÙ]", "", raw).lower()
    if norm == "no":
        with PENDING_LOCK:
            PENDING[chat_id] = PendingPurchase(
                items=[],
                stage="await_cost",
                start_time=dt.datetime.utcnow().replace(tzinfo=None),
            )
        context.user_data.pop("manual_index_map", None)
        await update.message.reply_text(
            "Perfetto. Procediamo comunque.\n\nPotresti dirmi quanto hai speso? Indica solo il numero, senza simboli o lettere (es. 12.50)."
        )
        return ConversationHandler.END
    parts = [p.strip() for p in re.split(r"\s*;\s*", raw) if p.strip()]
    index_map: Dict[int, int] = context.user_data.get("manual_index_map", {})
    if not parts or any(not p.isdigit() or int(p) not in index_map for p in parts):
        await update.message.reply_text('Formato non valido. Esempio corretto: "1; 2; 6" oppure scrivi "No".')
        return MANUAL_SELECT
    ids = [index_map[int(p)] for p in parts]
    with SessionLocal() as db:
        user = db.get(User, chat_id)
        full_name = f"{(user.first_name if user else '')} {(user.last_name if user else '')}".strip() or None
        now = dt.datetime.utcnow()
        for pid in ids:
            prod = db.get(Product, pid)
            if prod:
                prod.status = "acquistato"
                prod.purchase_date = now
                prod.buyer = full_name
        db.commit()
    with PENDING_LOCK:
        PENDING[chat_id] = PendingPurchase(
            items=[],
            stage="await_cost",
            start_time=dt.datetime.utcnow().replace(tzinfo=None),
        )
    context.user_data.pop("manual_index_map", None)
    await update.message.reply_text(
        "Potresti dirmi quanto hai speso? Indica solo il numero, senza simboli o lettere (es. 12.50)."
    )
    return ConversationHandler.END


# ---------- Contabilità (estratto conto) ----------

DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")


def _parse_date_or_keyword(text: str, kind: str) -> Optional[dt.datetime]:
    t = (text or "").strip()
    t_norm = t.lower()
    if kind == "start" and t_norm in ("inizio",):
        return None
    if kind == "end" and t_norm in ("oggi",):
        now = dt.datetime.utcnow()
        return now.replace(hour=23, minute=59, second=59, microsecond=0)
    m = DATE_RE.match(t)
    if not m:
        return None
    d, mth, y = map(int, m.groups())
    try:
        if kind == "start":
            return dt.datetime(y, mth, d, 0, 0, 0)
        else:
            return dt.datetime(y, mth, d, 23, 59, 59)
    except ValueError:
        return None


async def cb_contab_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    intro_id = context.user_data.get("intro_msg_id")
    if intro_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=intro_id)
        except Exception:
            pass
        context.user_data.pop("intro_msg_id", None)
    testo1 = (
        "Benvenuto in questa nuova sezione, qui potrai generare un estratto conto stampabile delle attività "
        "economiche a cui il vostro <b>fondo cassa comune</b> è stato sottoposto."
    )
    try:
        await q.edit_message_text(testo1, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await context.bot.send_message(chat_id=q.message.chat_id, text=testo1, parse_mode=ParseMode.HTML)
        else:
            raise
    testo2 = (
        "Indicami la <b>data esatta</b> dalla quale vuoi che io inizi a cercare le attività economiche. "
        "(IMPORTANTE: scrivi la data usando questo formato: <b>giorno/mese/anno</b>, esempio <code>11/06/2020</code>).\n\n"
        "Se non hai una data esatta in mente puoi semplicemente scrivere <b>\"Inizio\"</b> ed io cercherò tutte le "
        "attività economiche dal primo momento in cui questa app è stata usata da voi."
    )
    await context.bot.send_message(chat_id=chat_id, text=testo2, parse_mode=ParseMode.HTML)
    context.user_data["contab"] = {}
    nav_push(context, "contab")
    context.user_data[IN_CONTAB_FLAG] = True
    return ASK_START_DATE


async def contab_ask_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get(IN_CONTAB_FLAG):
        return ConversationHandler.END
    chat_id = update.effective_chat.id
    start_dt = _parse_date_or_keyword(update.message.text, "start")
    if start_dt is None and (update.message.text or "").strip().lower() != "inizio":
        await update.message.reply_text(
            "Formato non valido. Inserisci una data <b>gg/mm/aaaa</b> oppure scrivi <b>Inizio</b>.",
            parse_mode=ParseMode.HTML,
        )
        return ASK_START_DATE
    context.user_data["contab"]["start"] = start_dt
    await update.message.reply_text(
        "Bene, ora dimmi <b>fino a quale data</b> vuoi che io cerchi.\n"
        "(IMPORTANTE: formato <b>giorno/mese/anno</b>, es. <code>19/06/2020</code>).\n\n"
        "Se non hai una data esatta in mente puoi semplicemente scrivere <b>Oggi</b> ed io cercherò tutte le "
        "attività economiche registrate fino ad oggi.",
        parse_mode=ParseMode.HTML,
    )
    return ASK_END_DATE


async def contab_ask_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get(IN_CONTAB_FLAG):
        return ConversationHandler.END
    chat_id = update.effective_chat.id
    end_dt = _parse_date_or_keyword(update.message.text, "end")
    if end_dt is None and (update.message.text or "").strip().lower() != "oggi":
        await update.message.reply_text(
            "Formato non valido. Inserisci una data <b>gg/mm/aaaa</b> oppure scrivi <b>Oggi</b>.",
            parse_mode=ParseMode.HTML,
        )
        return ASK_END_DATE
    await update.message.reply_text("Inizio ricerca…")
    try:
        if os.path.isdir(ACCOUNTING_GIF_DIR):
            gifs = [p for p in Path(ACCOUNTING_GIF_DIR).glob("*") if p.is_file()]
            if gifs:
                from random import choice

                gif = choice(gifs)
                with open(gif, "rb") as f:
                    await context.bot.send_animation(chat_id=chat_id, animation=f)
    except Exception:
        logger.exception("[contab] invio GIF fallito (ok ignorare)")
    # Mark the accounting process as busy. Store the triggering
    # message id so the busy guard won't reply to this same input.
    context.user_data[BUSY_FLAG] = True
    try:
        context.user_data["busy_ignore_msg_id"] = update.message.message_id
    except Exception:
        pass
    start_dt = context.user_data["contab"].get("start")
    context.application.create_task(_build_and_send_statement(context, chat_id, start_dt, end_dt))
    context.user_data[IN_CONTAB_FLAG] = False
    return ConversationHandler.END


async def _build_and_send_statement(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, start_dt: Optional[dt.datetime], end_dt: dt.datetime
):
    from sqlalchemy import select
    from ..models import Transaction

    try:
        if start_dt is None:
            start_dt = first_tx_datetime() or dt.datetime(1970, 1, 1)
        with SessionLocal() as db:
            q = (
                select(Transaction)
                .where(Transaction.date >= start_dt, Transaction.date <= end_dt)
                .order_by(Transaction.date.asc(), Transaction.id.asc())
            )
            txs: List[Transaction] = db.execute(q).scalars().all()
        if not txs:
            await context.bot.send_message(chat_id=chat_id, text="Nessuna attività trovata nell'intervallo selezionato.")
            return
        foto_col_texts: List[str] = []
        all_items: List[Dict[str, str]] = []
        for tx in txs:
            try:
                paths = json.loads(tx.receipt_path or "[]")
            except Exception:
                paths = []
            for p in paths:
                rel = p
                pref_dir = f"{str(RECEIPTS_DIR).rstrip(os.sep)}{os.sep}"
                if os.path.isabs(rel):
                    try:
                        rel = str(Path(rel).resolve().relative_to(Path(RECEIPTS_DIR).resolve()))
                    except Exception:
                        rel = Path(rel).name
                else:
                    if rel.startswith(pref_dir):
                        rel = rel[len(pref_dir) :]
                    elif rel.startswith("receipts" + os.sep):
                        rel = rel[len("receipts" + os.sep) :]
                file_path = Path(RECEIPTS_DIR) / rel
                if not file_path.exists():
                    continue
                from urllib.parse import quote

                rel_enc = quote(rel)
                url = f"/contabilita/receipts/{rel_enc}"
                all_items.append({"title": Path(rel).name, "url": url})
        short = None
        if not all_items:
            for _ in txs:
                foto_col_texts.append(
                    "<b>Foto</b>: assente<br/><b>Url di visualizzazione</b>: link non disponibile"
                )
        else:
            try:
                token = create_web_session(
                    chat_id, type_="estratto_conto", carousels=json.dumps(all_items, ensure_ascii=False)
                )
            except Exception:
                logger.exception("[statement] creazione websessions fallita")
                token = None
            if token:
                carousel_url = f"{BASE_URL}/contabilita/s/{token}"
                short = shorten_url(carousel_url)
            for tx in txs:
                try:
                    paths = json.loads(tx.receipt_path or "[]")
                except Exception:
                    paths = []
                names = [Path(p).name for p in paths]
                names_text = ", ".join(names) if names else "assente"
                cell = (
                    f"<b>Foto</b>: {names_text}<br/><b>Url di visualizzazione</b>: "
                    f"{short or 'link non disponibile'}"
                )
                foto_col_texts.append(cell)
        pdf_bytes = build_statement_pdf_bytes(txs, foto_col_texts)
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"estratto_conto_{ts}.pdf"
        await context.bot.send_document(chat_id=chat_id, document=pdf_bytes, filename=fname)
        await context.bot.send_message(chat_id=chat_id, text="✅ Estratto conto pronto!")
    except Exception as e:
        logger.exception("[contab] errore generazione estratto")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Errore durante la generazione: {e}")
    finally:
        context.user_data[BUSY_FLAG] = False
        # Clear guard helper so future flows start clean
        context.user_data.pop("busy_ignore_msg_id", None)
        context.user_data.pop("contab", None)
