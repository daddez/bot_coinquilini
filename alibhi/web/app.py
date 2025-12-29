from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from ..config import RECEIPTS_DIR, logger
from ..tasks import cleaning_notifier_task, purge_sessions_task
from ..bot import app as bot_app


app = FastAPI(title="Alibhi Web App")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    req_id = uuid.uuid4().hex[:12]
    request.state.req_id = req_id
    try:
        logger.info(f"{req_id} → {request.method} {request.url.path} {request.url.query}")
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        logger.info(f"{req_id} ← {response.status_code} {request.url.path}")
        return response
    except Exception:
        logger.exception(f"{req_id} !! Unhandled exception on {request.url.path}")
        raise


contab_app = FastAPI(title="Contabilità - Subapp")
contab_app.mount("/receipts", StaticFiles(directory=str(RECEIPTS_DIR)), name="receipts")
app.mount("/contabilita", contab_app)


@app.on_event("startup")
async def _startup_tasks():
    import asyncio

    asyncio.create_task(purge_sessions_task())
    # Start cleaning notifier if Telegram app is set later; poll until available
    async def _wait_and_start():
        import asyncio as _aio

        for _ in range(60):  # wait up to ~60s
            if bot_app.TELEGRAM_APP is not None:
                break
            await _aio.sleep(1)
        if bot_app.TELEGRAM_APP is not None:
            await cleaning_notifier_task(bot_app.TELEGRAM_APP)
    asyncio.create_task(_wait_and_start())

# Import routes to register endpoints
from . import routes_shop as _routes_shop  # noqa: F401
from . import routes_contab as _routes_contab  # noqa: F401
