from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..schemas import PENDING, PENDING_LOCK


async def receipt_prompt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the receipt prompt right after the user sends the total cost.

    This is registered after cost_handler so that it runs once the stage
    has been switched to 'await_receipt'. If cost_handler already sent
    the prompt, this handler will not send duplicates on non-text updates
    and will usually run only once upon the amount message.
    """
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    with PENDING_LOCK:
        pending = PENDING.get(chat_id)
    if not pending or pending.stage != "await_receipt":
        return
    try:
        await update.message.reply_text(
            "Ora invia la foto della <b>ricevuta di pagamento fisica (es. scontrino)</b> o <b>digitale (es. screenshot della transazione Apple Pay)</b>",
            parse_mode=ParseMode.HTML,
        )
    except BadRequest:
        await update.message.reply_text(
            "Ora invia la foto della ricevuta di pagamento (fisica: scontrino; oppure digitale: screenshot della transazione)"
        )

