from __future__ import annotations

from typing import List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .config import ADMIN_USER_ID


BACK_TEXT = "⬅️ Indietro"

DAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]

# Label pulsanti (label visibile, chiave interna)
CLEANING_BUTTONS: List[Tuple[str, str]] = [
    ("Camera Sandro, Mario", "camera_sm"),
    ("Camera Niccolò", "camera_niccolo"),
    ("Camera Daniel", "camera_daniel"),
    ("Camera Davide", "camera_davide"),
    ("Bagno Famiglia", "bagno_1"),
    ("Bagno Adottivi", "bagno_2"),
    ("Corridoio", "corridoio"),
    ("Uscio porta", "uscio"),
]

# Mappa chiave -> label leggibile
CLEANING_LABEL = {
    "camera_sm": "Camera di Sandro e Mario",
    "bagno_1": "Bagno Famiglia",
    "bagno_2": "Bagno Adottivi",
    "uscio": "Uscio della porta",
    "corridoio": "Corridoio",
}

# Aree mono-persona: risposta immediata
SINGLE_AREAS = {
    "camera_niccolo": "Niccolò",
    "camera_daniel": "Daniel",
    "camera_davide": "Davide",
}


def cleaning_areas_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for label, key in CLEANING_BUTTONS:
        row.append(InlineKeyboardButton(label, callback_data=f"cleaning:area:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def week_days_kb(poll_id: int) -> InlineKeyboardMarkup:
    pairs = [(0, 1), (2, 3), (4, 5)]
    rows = []
    for a, b in pairs:
        rows.append(
            [
                InlineKeyboardButton(DAYS[a], callback_data=f"cleanvote:{poll_id}:{a}"),
                InlineKeyboardButton(DAYS[b], callback_data=f"cleanvote:{poll_id}:{b}"),
            ]
        )
    rows.append([InlineKeyboardButton(DAYS[6], callback_data=f"cleanvote:{poll_id}:6")])
    return InlineKeyboardMarkup(rows)


def home_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    rows = []
    if chat_id == ADMIN_USER_ID:
        rows.append([InlineKeyboardButton("Funzioni Admin 🧰", callback_data="admin")])
    rows.append([InlineKeyboardButton("Organizza gli acquisti 🧾", callback_data="spesa")])
    rows.append([InlineKeyboardButton("Gestione contabilità 💸", callback_data="contab")])
    rows.append([InlineKeyboardButton("Crea lamentela anonima 🕵️", callback_data="complaint:new")])
    rows.append([InlineKeyboardButton("Calendario pulizie 🧹", callback_data="cleaning")])
    return InlineKeyboardMarkup(rows)


def spesa_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧺 Mostra lista della spesa", callback_data="spesa:view")],
            [InlineKeyboardButton("🛒 Facciamo la spesa in LIVE", callback_data="spesa:shop")],
            [InlineKeyboardButton("📝 Registra una spesa già fatta", callback_data="spesa:manual")],
        ]
    )


def spesa_view_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Aggiungi prodotto", callback_data="spesa:add")],
            [InlineKeyboardButton("🗑️ Rimuovi prodotto", callback_data="spesa:remove")],
        ]
    )


def receipt_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑️ Rimuovi", callback_data="receipt:replace")],
            [InlineKeyboardButton("➕ Invia un'altra", callback_data="receipt:addmore")],
            [InlineKeyboardButton("✅ Conferma", callback_data="receipt:confirm")],
        ]
    )

