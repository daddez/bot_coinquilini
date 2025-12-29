from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import random
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import select, func
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes, ConversationHandler

from ..config import (
    ACCOUNTING_GIF_DIR,
    ADMIN_USER_ID,
    BASE_URL,
    BUSY_FLAG,
    IN_CONTAB_FLAG,
    RECEIPTS_DIR,
    logger,
)
from ..db import SessionLocal, create_web_session, get_balance
from ..keyboards import (
    BACK_TEXT,
    CLEANING_LABEL,
    DAYS,
    cleaning_areas_kb,
    home_kb,
    receipt_inline_kb,
    spesa_kb,
    spesa_view_actions_kb,
    week_days_kb,
)
from ..keyboards_pairs import home_kb as home_kb  # override layout to 2-per-row
from ..models import (
    CleaningArea,
    CleaningPoll,
    CleaningVote,
    Product,
    Transaction,
    User,
)
from ..schemas import PENDING, PENDING_LOCK, PendingPurchase
from ..utils import (
    CURRENCY_RE,
    clear_intro_if_any,
    nav_push,
    nav_reset,
    format_eur,
    hide_reply_keyboard,
    reserve_next_foto_path,
    show_back_keyboard,
)


# ---------------- Home & Navigation ----------------


async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Ciao {user.first_name}! Dimmi in che modo posso esserti utile 😉",
        reply_markup=home_kb(update.effective_chat.id),
    )


async def send_home(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await hide_reply_keyboard(context, chat_id)
    intro = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "Ciao, sono Alfred, il mio compito è aiutarti a gestire la tua nuova casa perugina. "
            "Come le donne, non comprendo le tue parole, ma capisco se premi i tasti giusti."
        ),
    )
    context.user_data["intro_msg_id"] = intro.message_id
    await context.bot.send_message(
        chat_id=chat_id,
        text="Fammi capire in che modo posso esserti utile 🤖",
        reply_markup=home_kb(chat_id),
    )
    nav_reset(context, "home")


async def send_spesa_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await context.bot.send_message(
        chat_id=chat_id,
        text="Eccoci nella sezione per gestire le spese presenti e future. Scegli cosa vuoi fare:",
        reply_markup=spesa_kb(),
    )
    await show_back_keyboard(context, chat_id)
    nav_push(context, "spesa_menu")


async def send_spesa_list(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    with SessionLocal() as db:
        products = (
            db.execute(select(Product).where(Product.status == "da_acquistare").order_by(Product.created_at.asc()))
            .scalars()
            .all()
        )
    if not products:
        await context.bot.send_message(
            chat_id=chat_id, text="La lista della spesa è vuota.", reply_markup=spesa_view_actions_kb()
        )
    else:
        lines = [f"{i}) {p.name}" for i, p in enumerate(products, start=1)]
        await context.bot.send_message(
            chat_id=chat_id,
            text="<b>Da acquistare</b>:\n" + "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=spesa_view_actions_kb(),
        )
    nav_push(context, "spesa_list")


async def back_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or (update.message.text or "").strip() != BACK_TEXT:
        return
    chat_id = update.effective_chat.id
    # Disabilita back durante inserimento importo/ricevuta
    try:
        from ..schemas import PENDING, PENDING_LOCK
        with PENDING_LOCK:
            pending = PENDING.get(chat_id)
        if pending and (pending.stage == "await_cost" or str(pending.stage).startswith("await_receipt")):
            return
    except Exception:
        pass
    stack = context.user_data.get("nav_stack") or []
    if not isinstance(stack, list) or len(stack) <= 1:
        return
    # Pop current and render previous
    stack.pop()
    target = stack[-1]
    context.user_data["nav_stack"] = stack
    if target == "home":
        await send_home(context, chat_id)
    elif target == "spesa_menu":
        await send_spesa_menu(context, chat_id)
    elif target == "spesa_list":
        await send_spesa_list(context, chat_id)
    elif target == "cleaning_menu":
        await context.bot.send_message(
            chat_id=chat_id, text="Seleziona l'area della casa che ti interessa:", reply_markup=cleaning_areas_kb()
        )
        nav_push(context, "cleaning_menu")
    else:
        await send_home(context, chat_id)


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("➕ Aggiungi denaro al saldo", callback_data="admin:addfunds")]]
    )


async def cb_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    if chat_id != ADMIN_USER_ID:
        await query.answer("Non autorizzato", show_alert=True)
        return
    await query.edit_message_text("Ecco le funzioni admin disponibili:", reply_markup=admin_kb())


async def cb_admin_addfunds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    if chat_id != ADMIN_USER_ID:
        await query.answer("Non autorizzato", show_alert=True)
        return
    context.user_data["await_admin_amount"] = True
    await query.edit_message_text("Inviami i soldi da aggiungere al saldo (es. 50.00).")


async def admin_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_USER_ID:
        return
    if not context.user_data.get("await_admin_amount"):
        return

    text = (update.message.text or "").strip()
    if not text or not CURRENCY_RE.match(text):
        await update.message.reply_text("Formato non valido. Inserisci solo il numero (es. 50.00).")
        return
    amount_str = text.replace(",", ".")
    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        await update.message.reply_text("Numero non valido. Riprova (es. 50.00).")
        return

    try:
        with SessionLocal() as db:
            user = db.get(User, chat_id)
            nome = user.first_name if user else ""
            cognome = user.last_name if user else ""
            now = dt.datetime.utcnow().replace(second=0, microsecond=0)
            tx = Transaction(
                telegram_id=chat_id,
                nome=nome,
                cognome=cognome,
                date=now,
                amount=amount,
                operation="ricarica fondo comune fisico",
                receipt_path=json.dumps([], ensure_ascii=False),
            )
            db.add(tx)
            db.commit()

        context.user_data["await_admin_amount"] = False
        try:
            balance = get_balance()
            msg_bal = f"{balance:.2f} €"
        except Exception:
            logger.exception("[admin_amount_handler] errore calcolo balance")
            msg_bal = "aggiornato"
        await update.message.reply_text(
            f"✅ Saldo aggiornato. Bilancio attuale: {msg_bal}", reply_markup=home_kb(chat_id)
        )
    except Exception:
        logger.exception("[admin_amount_handler] errore salvataggio ricarica")
        await update.message.reply_text("❌ Errore durante l'aggiornamento del saldo. Riprova.")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    from ..config import SLOTS

    with SessionLocal() as db:
        user = db.get(User, chat_id)
        if user:
            intro = await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Ciao, sono Alfred, il mio compito è aiutarti a gestire la tua nuova casa perugina. "
                    "Come le donne, non comprendo le tue parole, ma capisco se premi i tasti giusti."
                ),
            )
            context.user_data["intro_msg_id"] = intro.message_id
            await context.bot.send_message(
                chat_id=chat_id,
                text="Fammi capire in che modo posso esserti utile 🤖",
                reply_markup=home_kb(chat_id),
            )
            context.user_data["nav"] = "home"
            return

        taken = {u.slot for u in db.execute(select(User)).scalars()}
        available = [s for s in SLOTS.keys() if s not in taken]
        if not available:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Purtroppo non sei ancora registrato e al momento non ci sono slot disponibili. Riprova più tardi.",
            )
            return

        buttons = [[InlineKeyboardButton(s, callback_data=f"reg:{s}")] for s in available]
        await context.bot.send_message(
            chat_id=chat_id,
            text="Purtroppo non sei ancora registrato. Potresti dirmi chi sei?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def cb_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from ..config import SLOTS

    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    slot = query.data.split(":", 1)[1]
    with SessionLocal() as db:
        taken = {u.slot for u in db.execute(select(User)).scalars()}
        if slot in taken:
            available = [s for s in SLOTS.keys() if s not in taken]
            buttons = [[InlineKeyboardButton(s, callback_data=f"reg:{s}")] for s in available]
            await query.edit_message_text(
                "Peccato! Quel profilo è stato appena preso da qualcun altro. Scegline un altro:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return
        first, last = SLOTS[slot]
        try:
            user = User(telegram_id=chat_id, slot=slot, first_name=first, last_name=last)
            db.add(user)
            db.commit()
        except Exception:
            db.rollback()
            await query.edit_message_text("Si è verificato un conflitto di registrazione. Riprova.")
            return
    await query.edit_message_text(
        f"Benvenuto {first}, ti stavo aspettando! La registrazione è andata a buon fine"
    )
    await context.bot.send_message(
        chat_id=chat_id, text="Dimmi in che modo posso esserti utile 🤖", reply_markup=home_kb()
    )


# ---------------- Spesa menus ----------------


async def cb_spesa_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    await clear_intro_if_any(context, chat_id)

    try:
        balance = get_balance()
    except Exception:
        logger.exception("[cb_spesa_menu] errore nel calcolo del balance")
        balance = Decimal("0.00")

    testo1 = (
        "Bene, siamo nella sezione per gestire le spese presenti e future.\n"
        f"<b>Il bilancio disponibile attualmente ammonta a {format_eur(balance)}</b>"
    )
    back_kb = ReplyKeyboardMarkup([[KeyboardButton(BACK_TEXT)]], resize_keyboard=True, one_time_keyboard=False)
    m_balance = await context.bot.send_message(
        chat_id=chat_id, text=testo1, reply_markup=back_kb, parse_mode=ParseMode.HTML
    )
    context.user_data["spesa_balance_msg_id"] = m_balance.message_id

    await context.bot.send_message(
        chat_id=chat_id, text="Fammi capire in che modo posso esserti utile 🤖", reply_markup=spesa_kb()
    )
    try:
        await query.delete_message()
    except Exception:
        pass
    nav_push(context, "spesa_menu")


async def spesa_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await query.edit_message_text("La lista della spesa è vuota.", reply_markup=spesa_view_actions_kb())
        return
    lines = [f"{i}) {p.name}" for i, p in enumerate(products, start=1)]
    text = "<b>Da acquistare</b>:\n" + "\n".join(lines)
    await query.edit_message_text(text, reply_markup=spesa_view_actions_kb(), parse_mode=ParseMode.HTML)
    nav_push(context, "spesa_list")


async def spesa_shop_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    balance_id = context.user_data.pop("spesa_balance_msg_id", None)
    if balance_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=balance_id)
        except Exception:
            pass
    try:
        token = create_web_session(chat_id)
    except Exception as e:
        logger.exception("[spesa_shop_link] errore nel creare la sessione web")
        await query.edit_message_text(f"❌ Impossibile aprire la web app: {e}")
        return
    url = f"{BASE_URL}/shop?t={token}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Apri la web app", url=url)]])
    await query.edit_message_text(
        "Questa funzione consiste in una lista della spesa dinamica. "
        "Apri la webapp, troverai tutti gli articoli, non ancora acquistati, "
        "inseriti nella lista della spesa dai tuoi coinquilini. "
        "Man mano che compri i prodotti, clicca sul loro riquadro: "
        "verranno registrati come acquistati nel database. "
        "Quando avrai finito la spesa clicca sul bottone ''FINE SPESA''"
        "e continua su Telegram!",
        reply_markup=kb,
    )


async def receipt_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    with PENDING_LOCK:
        pending = PENDING.get(chat_id)
    if not pending:
        await query.edit_message_text("❌ Nessuna registrazione in corso.")
        return
    action = query.data
    if action == "receipt:replace":
        removed = None
        if pending.receipt_paths:
            removed = pending.receipt_paths.pop()
            try:
                if removed and os.path.isfile(removed):
                    os.remove(removed)
            except Exception:
                logger.warning(f"[receipt_router] impossibile rimuovere file {removed}")
        pending.stage = "await_receipt"
        await query.edit_message_text("Ok, foto rimossa dalla memoria.\nInvia qui la nuova foto 😉")
    elif action == "receipt:addmore":
        pending.stage = "await_receipt_more"
        await query.edit_message_text("Ok, aggiungi un'altra foto.")
    elif action == "receipt:confirm":
        if not pending.receipt_paths:
            await query.edit_message_text("❌ Non ho nessuna foto salvata, inviami almeno una foto prima di confermare.")
            return
        try:
            with SessionLocal() as db:
                user = db.get(User, chat_id)
                nome = user.first_name if user else ""
                cognome = user.last_name if user else ""
                now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
                receipt_json = json.dumps(pending.receipt_paths, ensure_ascii=False)
                amount = Decimal("0.00") - abs(pending.cost or Decimal("0.00"))
                tx = Transaction(
                    telegram_id=chat_id,
                    nome=nome,
                    cognome=cognome,
                    date=now,
                    amount=amount,
                    operation="spesa",
                    receipt_path=receipt_json,
                )
                db.add(tx)
                db.commit()
                logger.info(
                    f"[receipt_router] transaction id={tx.id} chat={chat_id}, amount={tx.amount}, pics={len(pending.receipt_paths)}"
                )
        except Exception as e:
            logger.exception(f"[receipt_router] Errore nel salvataggio Transaction (chat {chat_id})")
            await query.edit_message_text(f"❌ Errore nel salvataggio: {e}")
            return
        with PENDING_LOCK:
            PENDING.pop(chat_id, None)
        await query.edit_message_text("✅ Grazie, ho registrato la tua spesa. A presto!")
        intro = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Ciao, sono Alfred, il mio compito è aiutarti a gestire la tua nuova casa perugina. "
                "Come le donne, non comprendo le tue parole, ma capisco se premi i tasti giusti."
            ),
        )
        context.user_data["intro_msg_id"] = intro.message_id
        await context.bot.send_message(
            chat_id=chat_id, text="Dimmi in che modo posso esserti utile 🤖", reply_markup=home_kb(chat_id)
        )
    else:
        await query.answer("Comando non riconosciuto")


async def cost_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and (update.message.text or "").strip() == BACK_TEXT:
        return
    chat_id = update.effective_chat.id
    with PENDING_LOCK:
        pending = PENDING.get(chat_id)
    if not pending or pending.stage != "await_cost":
        return
    msg_dt = (update.message.date or dt.datetime.utcnow()).replace(tzinfo=None)
    if pending.start_time and msg_dt <= pending.start_time:
        return
    if not update.message.text:
        if update.message.voice:
            await update.message.reply_text(
                "In questa fase non posso accettare *note vocali*. Inserisci solo il numero (es. 12.50).",
                parse_mode=ParseMode.MARKDOWN,
            )
        elif update.message.audio:
            await update.message.reply_text(
                "In questa fase non posso accettare *audio*. Inserisci solo il numero (es. 12.50).",
                parse_mode=ParseMode.MARKDOWN,
            )
        elif update.message.document:
            await update.message.reply_text(
                "In questa fase non posso accettare *documenti*. Inserisci solo il numero (es. 12.50).",
                parse_mode=ParseMode.MARKDOWN,
            )
        elif update.message.photo:
            await update.message.reply_text(
                "In questa fase non posso accettare *foto*. Inserisci solo il numero (es. 12.50).",
                parse_mode=ParseMode.MARKDOWN,
            )
        elif update.message.sticker:
            await update.message.reply_text(
                "In questa fase non posso accettare *sticker*. Inserisci solo il numero (es. 12.50).",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text("Inserisci solo il numero dell'importo (es. 12.50).")
        return
    text = update.message.text.strip()
    if not CURRENCY_RE.match(text):
        await update.message.reply_text(
            "Formato non valido. Inserisci *solo* il numero (es. 12.50).", parse_mode=ParseMode.MARKDOWN
        )
        return
    text = text.replace(",", ".")
    try:
        cost = Decimal(text)
    except InvalidOperation:
        await update.message.reply_text("Numero non valido. Riprova (es. 12.50).")
        return
    with PENDING_LOCK:
        pending.cost = cost
        pending.stage = "await_receipt"
    await update.message.reply_text(f"Importo registrato: {cost:.2f} €.")
    # Receipt prompt is sent by receipt_prompt_handler (group=11) to avoid duplicates.


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    with PENDING_LOCK:
        pending = PENDING.get(chat_id)
    if not pending or not pending.stage.startswith("await_receipt"):
        return
    if not update.message.photo:
        if update.message.text:
            await update.message.reply_text("Adesso mi serve la *foto della ricevuta*, non testo.", parse_mode=ParseMode.MARKDOWN)
        elif update.message.voice:
            await update.message.reply_text(
                "Adesso mi serve la *foto della ricevuta*, non note vocali.", parse_mode=ParseMode.MARKDOWN
            )
        elif update.message.audio:
            await update.message.reply_text("Adesso mi serve la *foto della ricevuta*, non audio.", parse_mode=ParseMode.MARKDOWN)
        elif update.message.document:
            await update.message.reply_text(
                "Adesso mi serve la *foto della ricevuta*, non documenti.", parse_mode=ParseMode.MARKDOWN
            )
        elif update.message.sticker:
            await update.message.reply_text("Adesso mi serve la *foto della ricevuta*, non sticker.", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("Adesso mi serve la *foto della ricevuta*.", parse_mode=ParseMode.MARKDOWN)
        return

    if getattr(update.message, "media_group_id", None):
        await update.message.reply_text(
            "❌ Non posso accettare più foto contemporaneamente.\nPer favore invia *una foto per volta*.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    p = update.message.photo[-1]
    unique_id = p.file_unique_id
    size = p.file_size or 0
    with PENDING_LOCK:
        already = any((uid == unique_id and fsize == size) for (uid, fsize) in pending.receipt_meta)
    if already:
        await update.message.reply_text(
            "⚠️ Questa foto sembra identica a una già inviata.\nSe è un errore, scatta/riesporta la foto e rinviala."
        )
        return

    file = await p.get_file()
    tmp_name = f".incoming_{chat_id}_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    tmp_path = os.path.join(RECEIPTS_DIR, tmp_name)
    await file.download_to_drive(custom_path=tmp_path)
    dest_path = reserve_next_foto_path(str(RECEIPTS_DIR), ext=".jpg")
    os.replace(tmp_path, dest_path)
    path = os.path.abspath(dest_path)
    logger.info(f"[photo_handler] Scaricata foto scontrino per chat {chat_id} → {path}")
    with PENDING_LOCK:
        pending.receipt_paths.append(path)
        pending.receipt_meta.append((unique_id, size))
    await update.message.reply_text(
        "Ricevuta salvata in memoria. Vuoi sostituirla, aggiungerne altre o confermare?",
        reply_markup=receipt_inline_kb(),
    )


# ---------------- Complaint (anonymous) ----------------


COMPLAINT_FLAG = "await_complaint_text"
COMPLAINT_TEXT_KEY = "complaint_text"


async def cb_complaint_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await clear_intro_if_any(context, q.message.chat_id)
    context.user_data[COMPLAINT_FLAG] = True
    await q.edit_message_text(
        "Ah vuoi fare lo snitch!\nScrivi qui la tua lamentela. Verrà inviata in anonimo, non preoccuparti!"
    )


async def complaint_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get(COMPLAINT_FLAG):
        return
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Scrivi la tua lamentela in testo semplice, grazie.")
        return
    context.user_data[COMPLAINT_TEXT_KEY] = text
    context.user_data[COMPLAINT_FLAG] = False
    sender_id = update.effective_chat.id
    with SessionLocal() as db:
        users = db.execute(select(User)).scalars().all()
    rows = []
    current = []
    for u in users:
        if u.telegram_id == sender_id:
            continue
        full_name = f"{u.first_name} {u.last_name}".strip()
        current.append(InlineKeyboardButton(full_name, callback_data=f"complaint:to:{u.telegram_id}"))
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    if not rows:
        await update.message.reply_text("Non ho trovato altri utenti registrati a cui inoltrare la lamentela.")
        context.user_data.pop(COMPLAINT_TEXT_KEY, None)
        return
    await update.message.reply_text(
        "Indica l'utente a cui vuoi indirizzarla, in anonimo.", reply_markup=InlineKeyboardMarkup(rows)
    )


async def cb_complaint_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    m = re.match(r"^complaint:to:(\d+)$", q.data)
    if not m:
        await q.answer("Comando non valido", show_alert=True)
        return
    target_id = int(m.group(1))
    complaint = context.user_data.pop(COMPLAINT_TEXT_KEY, "").strip()
    if not complaint:
        await q.edit_message_text("Non ho trovato il testo della lamentela. Ricomincia pure dal menu.")
        return
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "⚠️ WARNING, stai facendo il birbantello!\n"
                "Qualcuno ha lasciato una lamentela per te:\n\n"
                f"{complaint}"
            ),
        )
    except Exception:
        await q.edit_message_text(
            "Non sono riuscito a inoltrare la lamentela a quell'utente (forse non ha avviato il bot)."
        )
        return
    await q.edit_message_text("La tua lamentela è stata inoltrata, alla prossima.")


# ---------------- Cleaning calendar ----------------


async def cb_cleaning_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await clear_intro_if_any(context, q.message.chat_id)
    await q.edit_message_text(
        "Seleziona l'area della casa che ti interessa:", reply_markup=cleaning_areas_kb()
    )
    nav_push(context, "cleaning_menu")


async def cb_cleaning_area(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # Area keys can include digits (e.g., 'bagno_1')
    m = re.match(r"^cleaning:area:([a-z0-9_]+)$", q.data)
    if not m:
        await q.answer("Comando non valido", show_alert=True)
        return
    key = m.group(1)
    if key in ("camera_niccolo", "camera_daniel", "camera_davide"):
        from ..keyboards import SINGLE_AREAS
        await q.edit_message_text(f"L'addetto alle pulizie di questa camera è {SINGLE_AREAS[key]}")
        return
    with SessionLocal() as db:
        area = db.get(CleaningArea, key)
        if not area:
            await q.edit_message_text("Configurazione pulizie non trovata per quest'area. Parla con l'admin.")
            return
    # Se 'prossimo' è già impostato, mostra il riepilogo con il nome/cognome.
    if area.prossimo:
        label = CLEANING_LABEL.get(key, key)
        nome_cognome = None
        try:
            with SessionLocal() as db:
                u = db.get(User, area.prossimo)
                if u:
                    nome_cognome = f"{u.first_name} {u.last_name}".strip()
        except Exception:
            pass
        who = nome_cognome or str(area.prossimo)
        msg = (
            f"Il prossimo a pulire sarà {who}.\n"
            f"Giorno di pulizia: {area.giorno or 'da decidere'}"
        )
        await q.edit_message_text(msg)
        return
    ids = [
        area.pulitore_1,
        area.pulitore_2,
        area.pulitore_3,
        area.pulitore_4,
        area.pulitore_5,
        area.pulitore_6,
    ]
    # Normalizza gli ID: accetta anche stringhe dal DB e convertili in int
    participants = []
    for i in ids:
        if i is None:
            continue
        s = str(i).strip()
        if not s or s.lower() == "none":
            continue
        try:
            participants.append(int(s))
        except Exception:
            continue
    if not participants:
        await q.edit_message_text("Nessun pulitore configurato per quest'area.")
        return
    try:
        with SessionLocal() as db:
            poll = CleaningPoll(
                area_key=key,
                creator_id=q.message.chat_id,
                participant_ids=json.dumps(participants, ensure_ascii=False),
                status="open",
            )
            db.add(poll)
            db.commit()
            poll_id = poll.id
    except Exception:
        logger.exception("[cb_cleaning_area] errore creazione sondaggio")
        await q.edit_message_text("Errore durante l'avvio del sondaggio. Parla con l'admin.")
        return
    lbl = CLEANING_LABEL.get(key, key)
    # Feedback immediato all'utente che ha cliccato
    try:
        await q.edit_message_text(f"Avvio sondaggio per: {lbl}…")
    except Exception:
        pass
    reachable, unreachable = [], []
    for uid in participants:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"🧹 {lbl}\nScegli un giorno della settimana in cui vorresti le pulizie venissero svolte:",
                reply_markup=week_days_kb(poll_id),
            )
            reachable.append(uid)
        except Exception:
            unreachable.append(uid)
    if unreachable:
        with SessionLocal() as db:
            p = db.get(CleaningPoll, poll_id)
            # Salva solo ID numerici raggiungibili
            p.participant_ids = json.dumps([int(x) for x in reachable], ensure_ascii=False)
            db.commit()
    msg = (
        f"Sondaggio avviato per: {lbl}. Partecipanti: {len(reachable)}"
        + (f" – Non raggiungibili: {len(unreachable)}" if unreachable else "")
    )
    await q.edit_message_text(msg)


async def cb_cleanvote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    m = re.match(r"^cleanvote:(\d+):([0-6])$", q.data)
    if not m:
        await q.answer("Comando non valido", show_alert=True)
        return
    poll_id = int(m.group(1))
    day_idx = int(m.group(2))
    voter = q.from_user.id
    with SessionLocal() as db:
        poll = db.get(CleaningPoll, poll_id)
        if not poll or poll.status != "open":
            await q.answer("Sondaggio non più attivo.", show_alert=True)
            return
        # Normalizza: in DB possono esserci stringhe; converti a int
        try:
            raw = json.loads(poll.participant_ids or "[]")
        except Exception:
            raw = []
        participants = []
        for x in raw:
            try:
                participants.append(int(str(x).strip()))
            except Exception:
                pass
        if voter not in participants:
            await q.answer("Non sei tra i partecipanti.", show_alert=True)
            return
        existing = db.execute(
            select(CleaningVote).where(
                CleaningVote.poll_id == poll_id, CleaningVote.voter_id == voter
            )
        ).scalar_one_or_none()
        if existing:
            existing.day = day_idx
            existing.voted_at = dt.datetime.utcnow()
        else:
            db.add(CleaningVote(poll_id=poll_id, voter_id=voter, day=day_idx))
        db.commit()
        try:
            await q.edit_message_text(f"Hai votato: {DAYS[day_idx]}")
        except Exception:
            pass
        votes = db.execute(select(CleaningVote).where(CleaningVote.poll_id == poll_id)).scalars().all()
        voted_ids = {v.voter_id for v in votes}
        if set(voted_ids) != set(participants):
            return
        counts = [0] * 7
        for v in votes:
            counts[v.day] += 1
        top = max(counts)
        winners = [i for i, c in enumerate(counts) if c == top]
        area_key = poll.area_key
        if len(winners) == 1:
            chosen = winners[0]
            poll.status = "closed"
            poll.result_day = chosen
            db.commit()
            area = db.get(CleaningArea, area_key)
            area.giorno = DAYS[chosen]
            primary = area.pulitore_1
            if primary and str(primary).lower() != "none":
                area.prossimo = primary
            else:
                for pid in [
                area.pulitore_1,
                area.pulitore_2,
                area.pulitore_3,
                area.pulitore_4,
                area.pulitore_5,
                area.pulitore_6,
                ]:
                    if pid and str(pid).lower() != "none":
                        area.prossimo = pid
                        break
            db.commit()
            result_text = f"✅ La maggioranza ha scelto: {DAYS[chosen]}"
        else:
            poll.status = "closed"
            poll.result_day = None
            db.commit()
            result_text = "⚠️ Non si è arrivati ad una conclusione, nessuna maggioranza ha vinto."
    lbl = CLEANING_LABEL.get(area_key, area_key)
    targets = set(participants + [poll.creator_id])
    for tid in targets:
        try:
            await context.bot.send_message(chat_id=tid, text=f"🧹 Sondaggio '{lbl}':\n{result_text}")
        except Exception:
            pass


async def cb_cleaning_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # Area keys can include digits (e.g., 'bagno_1')
    m = re.match(r"^cleaning:done:([a-z0-9_]+)$", q.data)
    if not m:
        await q.answer("Comando non valido", show_alert=True)
        return
    key = m.group(1)
    with SessionLocal() as db:
        area = db.get(CleaningArea, key)
        if not area:
            await q.answer("Area non trovata.", show_alert=True)
            return
        seq = [
            area.pulitore_1,
            area.pulitore_2,
            area.pulitore_3,
            area.pulitore_4,
            area.pulitore_5,
            area.pulitore_6,
        ]
        seq = [x for x in seq if x and str(x).lower() != "none"]
        if area.prossimo in seq:
            idx = seq.index(area.prossimo)
            area.prossimo = seq[(idx + 1) % len(seq)]
            db.commit()
    try:
        await q.edit_message_text("Grazie! Ho segnato che hai pulito. Al prossimo turno 😉")
    except Exception:
        pass


# ---------------- Router & Guards ----------------


async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data == "spesa":
        await cb_spesa_menu(update, context)
    elif data == "spesa:view":
        await spesa_view(update, context)
    elif data == "spesa:shop":
        await spesa_shop_link(update, context)
    elif data == "spesa:add":
        # Fallback routing for add product entry (conversation handles this too)
        from .conversations import spesa_add_entry
        await spesa_add_entry(update, context)
    elif data == "add:single":
        # Fallback: start single-product add without ConversationHandler state
        await add_single_fallback_entry(update, context)
    elif data == "add:multi":
        # Fallback: start multi-product add without ConversationHandler state
        await add_multi_fallback_entry(update, context)
    elif data == "spesa:manual":
        # Fallback routing for manual purchase entry
        from .conversations import spesa_manual_entry
        await spesa_manual_entry(update, context)
    elif data == "contab":
        # Handled by ConversationHandler entry (pattern ^contab$). Avoid duplicate handling here.
        return
    else:
        await query.answer("Comando non riconosciuto")


async def add_single_fallback_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback when ConversationHandler does not catch add:single.
    Prompts the user and sets a flag so a global text handler can process input.
    """
    query = update.callback_query
    await query.answer()
    context.user_data["await_add_name"] = True
    context.user_data["await_add_bulk"] = False
    context.user_data["add_mode"] = "single"
    await query.edit_message_text("Inserisci il nome del prodotto da aggiungere:")
    nav_push(context, "add")


async def add_multi_fallback_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback when ConversationHandler does not catch add:multi.
    Prompts the user and sets a flag so a global text handler can process input.
    """
    query = update.callback_query
    await query.answer()
    context.user_data["await_add_name"] = False
    context.user_data["await_add_bulk"] = True
    context.user_data["add_mode"] = "multi"
    await query.edit_message_text(
        "Inserisci i prodotti separati da punto e virgola (es: carne; 1.5kg farina 00; 3kg carne macinata; ...)"
    )
    nav_push(context, "add")


async def add_fallback_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global text handler to complete add-product flow when conversation is not active."""
    text = (update.message.text or "").strip() if update.message else ""
    if not text:
        return
    # Do not process commands here
    if text.startswith("/"):
        return
    # Only run when our explicit fallback flags are set by add_*_fallback_entry.
    # This prevents duplicate handling when the ConversationHandler already processes the message.
    if not (context.user_data.get("await_add_name") or context.user_data.get("await_add_bulk")):
        return
    try:
        logger.info(
            f"[add_fallback_text_handler] processing text via fallback: '{text}'"
            f" flags=(name={context.user_data.get('await_add_name')}, bulk={context.user_data.get('await_add_bulk')})"
        )
    except Exception:
        pass
    # Single product name
    if context.user_data.get("await_add_name"):
        # Clear the flag before processing to avoid re-entry
        context.user_data["await_add_name"] = False
        try:
            from .conversations import spesa_add_name
            await spesa_add_name(update, context)
        finally:
            # Ensure we don't leave stale flags
            context.user_data.pop("await_add_bulk", None)
            context.user_data.pop("add_mode", None)
        return
    # Multiple products list
    if context.user_data.get("await_add_bulk"):
        context.user_data["await_add_bulk"] = False
        try:
            from .conversations import spesa_add_bulk
            await spesa_add_bulk(update, context)
        finally:
            context.user_data.pop("await_add_name", None)
            context.user_data.pop("add_mode", None)
        return
    # Not our context; ignore
    return


async def busy_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only react to real user messages that arrive while a long-running
    # operation is in progress (e.g., statement generation).
    if not context.user_data.get(BUSY_FLAG):
        return
    if not update.message:
        return
    # Ignore the very message that triggered the busy state to avoid
    # sending the warning immediately after the user provided the date.
    try:
        if context.user_data.get("busy_ignore_msg_id") == update.message.message_id:
            return
    except Exception:
        pass
    await update.message.reply_text(
        "Non posso elaborare la tua richiesta, sto lavorando per te, attendi mentre finisco per favore!"
    )
