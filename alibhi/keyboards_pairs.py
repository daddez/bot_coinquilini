from __future__ import annotations

from telegram import InlineKeyboardMarkup

# Reuse base keyboard to preserve labels and callbacks
from .keyboards import home_kb as _base_home_kb


def home_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """Return the home keyboard arranged two buttons per row.

    Builds on the existing home_kb from keyboards.py to keep labels/callbacks
    identical, but rearranges the layout into pairs.
    """
    base = _base_home_kb(chat_id)
    buttons = [btn for row in (base.inline_keyboard or []) for btn in row]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)

