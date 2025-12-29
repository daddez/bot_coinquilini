from __future__ import annotations

from pathlib import Path
from typing import Dict

from fastapi import Body, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from ..bot import app as bot_app
from ..config import BASE_URL, logger
from ..db import SessionLocal
from ..models import Product, User
from ..schemas import PENDING, PENDING_LOCK, PendingPurchase
from ..utils import close_session, resolve_session_or_403, send_async_message
from telegram import ReplyKeyboardRemove
from .app import app


def _load_template(name: str) -> str:
    here = Path(__file__).parent
    return (here / "templates" / name).read_text(encoding="utf-8")


@app.get("/shop", response_class=HTMLResponse)
async def shop_page(t: str):
    _ = resolve_session_or_403(t)
    return HTMLResponse(_load_template("shop.html"))


@app.get("/api/items")
async def api_items(t: str):
    ws = resolve_session_or_403(t)
    with SessionLocal() as db:
        items = (
            db.execute(
                __import__("sqlalchemy").sql.select(Product).where(Product.status == "da_acquistare").order_by(Product.created_at.asc())
            )
            .scalars()
            .all()
        )
    return JSONResponse([{"id": it.id, "name": it.name} for it in items])


@app.post("/api/buy")
async def api_buy(payload: Dict = Body(...)):
    try:
        token = str(payload.get("t"))
        item_id = int(payload.get("id"))
    except Exception:
        logger.exception("[api_buy] payload non valido")
        raise HTTPException(status_code=400, detail="Payload non valido")
    ws = resolve_session_or_403(token)
    chat_id = ws.telegram_id
    try:
        with SessionLocal() as db:
            prod = db.get(Product, item_id)
            if not prod:
                raise HTTPException(status_code=404, detail="Prodotto non trovato")
            user = db.get(User, chat_id)
            full_name = f"{(user.first_name if user else '')} {(user.last_name if user else '')}".strip()
            prod.status = "acquistato"
            import datetime as dt

            prod.purchase_date = dt.datetime.utcnow()
            prod.buyer = full_name or None
            db.commit()
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"[api_buy] errore imprevisto per token {token}, item_id={item_id}")
        raise HTTPException(status_code=500, detail="Errore interno")
    return JSONResponse({"ok": True})


@app.post("/api/finish")
async def api_finish(payload: Dict = Body(...)):
    try:
        token = str(payload.get("t"))
    except Exception:
        logger.exception("[api_finish] payload non valido")
        raise HTTPException(status_code=400, detail="Payload non valido")
    ws = resolve_session_or_403(token)
    chat_id = ws.telegram_id
    logger.info(f"[api_finish] richiesta di chiusura spesa dalla sessione token={token} chat={chat_id}")
    try:
        with PENDING_LOCK:
            PENDING[chat_id] = PendingPurchase(
                items=[], stage="await_cost", start_time=__import__("datetime").datetime.utcnow().replace(tzinfo=None)
            )
        if bot_app.TELEGRAM_APP is None:
            logger.error("[api_finish] TELEGRAM_APP non inizializzato")
            raise HTTPException(status_code=500, detail="Bot non inizializzato")
        msg = (
            "Hai terminato la spesa live.\n\n"
            "Inserisci il costo totale della spesa che hai fatto (per tutti i prodotti acquistati, non solo quelli cliccati in app). Non usare simboli, solo numeri."
        )
        # Entra nella fase di inserimento importo: rimuovi la tastiera "Indietro".
        send_async_message(bot_app.TELEGRAM_APP, chat_id, msg, reply_markup=ReplyKeyboardRemove())
        close_session(token)
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"[api_finish] errore durante chiusura sessione token={token}")
        raise HTTPException(status_code=500, detail="Errore interno durante la chiusura spesa")
    return JSONResponse({"ok": True})
