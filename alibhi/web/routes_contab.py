from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select

from ..config import RECEIPTS_DIR, SESSION_TTL_SECONDS
from ..db import SessionLocal
from ..models import WebSession
from ..utils import resolve_session_or_403
from .app import contab_app


def _load_template(name: str) -> str:
    here = Path(__file__).parent
    return (here / "templates" / name).read_text(encoding="utf-8")


@contab_app.get("/s/{token}", response_class=HTMLResponse)
async def contab_session_page(token: str):
    with SessionLocal() as db:
        ws = db.execute(select(WebSession).where(WebSession.token == token)).scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Not Found")
    return HTMLResponse(_load_template("contab_carousel.html"))


@contab_app.get("/api/session/{token}/carousel")
async def contab_session_carousel(token: str):
    ws = resolve_session_or_403(token)
    if ws.type != "estratto_conto" or ws.carousels is None:
        raise HTTPException(status_code=404, detail="Not Found")
    raw = ws.carousels
    if isinstance(raw, str):
        try:
            raw_items = json.loads(raw) or []
        except Exception:
            raw_items = []
    elif isinstance(raw, list):
        raw_items = raw
    else:
        raw_items = []
    items = []
    from urllib.parse import urlparse

    for it in raw_items:
        if not isinstance(it, dict):
            continue
        u = it.get("url") or it.get("src") or it.get("href")
        title = it.get("title") or it.get("caption") or ""
        if not u:
            continue
        if isinstance(u, str) and (u.startswith("http://") or u.startswith("https://")):
            try:
                u = urlparse(u).path or u
            except Exception:
                pass
        items.append({"url": u, "title": title})
    return JSONResponse(items)


@contab_app.get("/api/session/{token}/info")
async def contab_session_info(token: str):
    with SessionLocal() as db:
        ws = db.execute(select(WebSession).where(WebSession.token == token)).scalar_one_or_none()
        if not ws:
            raise HTTPException(status_code=404, detail="Not Found")
        ttl = SESSION_TTL_SECONDS if (ws.type == "estratto_conto" and SESSION_TTL_SECONDS > 0) else None
        remaining = None
        if ttl is not None:
            age = (dt.datetime.utcnow() - ws.started_at).total_seconds()
            remaining = max(0, int(ttl - age))
            if remaining == 0 and ws.status != "scaduta":
                try:
                    ws_db = db.execute(select(WebSession).where(WebSession.id == ws.id)).scalar_one_or_none()
                    if ws_db and ws_db.status != "scaduta":
                        ws_db.status = "scaduta"
                        ws_db.ended_at = ws_db.ended_at or dt.datetime.utcnow()
                        db.commit()
                    ws.status = "scaduta"
                except Exception:
                    pass
        started = (ws.started_at or dt.datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")
        return JSONResponse(
            {
                "nome": ws.nome,
                "cognome": ws.cognome,
                "type": ws.type,
                "status": ws.status,
                "started_at": started,
                "ttl_seconds": ttl,
                "remaining_seconds": remaining,
            }
        )


@contab_app.post("/api/session/{token}/close")
async def contab_session_close(token: str):
    with SessionLocal() as db:
        ws = db.execute(select(WebSession).where(WebSession.token == token)).scalar_one_or_none()
        if not ws:
            return JSONResponse({"status": "not_found"}, status_code=404)
        if ws.status != "scaduta":
            ws.status = "scaduta"
            ws.ended_at = dt.datetime.utcnow()
            db.commit()
        return JSONResponse({"status": "ok"}, status_code=200)


@contab_app.get("/debug/session/{token}")
def _debug_session(token: str):
    with SessionLocal() as db:
        ws = db.execute(select(WebSession).where(WebSession.token == token)).scalar_one_or_none()
        if not ws:
            return JSONResponse({"found": False}, status_code=404)
        raw = ws.carousels
        try:
            parsed = json.loads(raw) if raw else None
        except Exception as e:
            parsed = f"JSON_ERROR: {e}"
        return {
            "found": True,
            "type": ws.type,
            "status": ws.status,
            "started_at": str(ws.started_at),
            "carousels_len": (len(parsed) if isinstance(parsed, list) else None),
            "carousels_sample": (parsed[:2] if isinstance(parsed, list) else parsed),
            "carousels_raw_prefix": (raw[:300] if isinstance(raw, str) else None),
        }


@contab_app.get("/debug/ping/{name}")
def _debug_ping(name: str):
    from urllib.parse import quote

    return {"url": f"/contabilita/receipts/{quote(name)}"}

