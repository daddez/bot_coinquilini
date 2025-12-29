from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------
# Configurazione e costanti
# -------------------------------------------------------------

ADMIN_USER_ID = 7896754678 # Sostituisci con l'ID Telegram dell'amministratore


# Flag conversazione contabilità
IN_CONTAB_FLAG = "in_contab"

# Directory ricevute
RECEIPTS_DIR = Path(os.getenv("RECEIPTS_DIR", "/home/ubuntu/alibhi-bot/receipts"))
if not RECEIPTS_DIR.exists():
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

# Memorie in-process
SESSIONS: Dict[str, Dict] = {}
SESSIONS_LOCK = threading.Lock()

ACCOUNTING_GIF_DIR = os.getenv(
    "ACCOUNTING_GIF_DIR", "/home/ubuntu/alibhi-bot/multimedia_PER_chatbot/gif_typing_pc"
)
TLY_TOKEN = os.getenv("TLY_TOKEN", "")

# Flag per blocco input durante elaborazioni contabilità
BUSY_FLAG = "accounting_busy"

# Memoria dei caroselli {carousel_id: [{"title":..., "url": ...}], ...}
RECEIPT_CAROUSELS: Dict[str, List[Dict[str, str]]] = {}

# TTL sessioni (estratto_conto)
SESSION_TTL_SECONDS = int(os.getenv("ACCOUNTING_SESSION_TTL_SECONDS", "7200"))

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8080")
SHOP_SECRET = os.getenv("SHOP_SECRET", "change-me")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///alibhi.db")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Rome")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("alibhi")

# Slots predefiniti (nome, cognome)
SLOTS: Dict[str, Tuple[str, str]] = {
    "Sandro": ("Sandro", "Miano"),
    "Mario": ("Mario", "Mariano"),
    "Niccolò": ("Niccolò", "Iannarone"),
    "Daniel": ("Daniel", "Pulituccio"),
}
