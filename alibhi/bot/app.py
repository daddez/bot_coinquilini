from __future__ import annotations

import asyncio
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ..config import BOT_TOKEN
from ..config import logger as _logger
from .handlers import (
    add_fallback_text_handler,
    admin_amount_handler,
    back_reply_handler,
    busy_guard,
    cb_admin_addfunds,
    cb_admin_menu,
    cb_cleaning_area,
    cb_cleaning_done,
    cb_cleaning_menu,
    cb_cleanvote,
    cb_complaint_choose,
    cb_complaint_new,
    cb_register,
    cb_router,
    cmd_start,
    complaint_text_handler,
    cost_handler,
    photo_handler,
    receipt_router,
    spesa_shop_link,
    spesa_view,
)
from .addons import receipt_prompt_handler
from .conversations import (
    ADD_BULK,
    ADD_NAME,
    ASK_END_DATE,
    ASK_START_DATE,
    MANUAL_SELECT,
    RM_CONFIRM,
    RM_SELECT,
    add_multi_start,
    add_single_start,
    cb_contab_entry,
    contab_ask_end,
    contab_ask_start,
    spesa_add_bulk,
    spesa_add_cancel,
    spesa_add_entry,
    spesa_add_name,
    spesa_manual_entry,
    spesa_manual_select,
    spesa_rm_confirm,
    spesa_rm_entry,
    spesa_rm_select,
)
from ..keyboards_pairs import home_kb as _home_kb_pairs  # override home layout to pairs


TELEGRAM_APP: Optional[Application] = None


def build_bot_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 1) Global text handler so BACK button works in most places
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, back_reply_handler, block=False), group=50)

    # Complaint flow (anonymous complaints)
    app.add_handler(CallbackQueryHandler(cb_complaint_new, pattern=r"^complaint:new$"))
    # Put complaint text handler after conversations (higher group) so it doesn't steal generic text
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_text_handler, block=False),
        group=40,
    )
    app.add_handler(CallbackQueryHandler(cb_complaint_choose, pattern=r"^complaint:to:\d+$"))

    # /start and registration
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_register, pattern=r"^reg:\w+"))

    # Cleaning calendar
    app.add_handler(CallbackQueryHandler(cb_cleaning_menu, pattern=r"^cleaning$"))
    # Allow digits in area keys (e.g., 'bagno_1')
    app.add_handler(CallbackQueryHandler(cb_cleaning_area, pattern=r"^cleaning:area:[a-z0-9_]+$"))
    app.add_handler(CallbackQueryHandler(cb_cleanvote, pattern=r"^cleanvote:\d+:[0-6]$"))
    app.add_handler(CallbackQueryHandler(cb_cleaning_done, pattern=r"^cleaning:done:[a-z0-9_]+$"))

    # Conversations: add products
    # Add products conversation: handle entry + text states
    add_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(spesa_add_entry, pattern=r"^spesa:add$"),
            CallbackQueryHandler(add_single_start, pattern=r"^add:single$"),
            CallbackQueryHandler(add_multi_start, pattern=r"^add:multi$"),
        ],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, spesa_add_name)],
            ADD_BULK: [MessageHandler(filters.TEXT & ~filters.COMMAND, spesa_add_bulk)],
        },
        fallbacks=[MessageHandler(filters.COMMAND, spesa_add_cancel)],
        name="add_product_conv",
    )
    app.add_handler(add_conv)

    # Conversations: remove products
    rm_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(spesa_rm_entry, pattern=r"^spesa:remove$")],
        states={
            RM_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, spesa_rm_select)],
            RM_CONFIRM: [CallbackQueryHandler(spesa_rm_confirm, pattern=r"^rm:(confirm|cancel)$")],
        },
        fallbacks=[],
        name="remove_product_conv",
    )
    app.add_handler(rm_conv)

    # Conversations: manual purchase
    manual_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(spesa_manual_entry, pattern=r"^spesa:manual$")],
        states={
            MANUAL_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, spesa_manual_select)],
        },
        fallbacks=[],
        name="manual_purchase_conv",
    )
    app.add_handler(manual_conv)

    # Conversation: accounting statement
    contab_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_contab_entry, pattern=r"^contab$")],
        states={
            ASK_START_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, contab_ask_start)],
            ASK_END_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, contab_ask_end)],
        },
        fallbacks=[],
        name="accounting_conv",
    )
    app.add_handler(contab_conv, group=30)

    # Receipt inline keyboard router
    app.add_handler(CallbackQueryHandler(receipt_router, pattern=r"^receipt:(replace|addmore|confirm)$"))

    # Admin functions
    app.add_handler(CallbackQueryHandler(cb_admin_menu, pattern=r"^admin$"))
    app.add_handler(CallbackQueryHandler(cb_admin_addfunds, pattern=r"^admin:addfunds$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_amount_handler, block=False))

    # Fallback text handler for add product flows (when ConversationHandler isn't active)
    # Place it early, but after admin_amount_handler to avoid numeric capture;
    # group=5 so it runs before cost_handler (group=10) and before back button (group=50)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, add_fallback_text_handler, block=False),
        group=5,
    )

    # Receipt pipeline
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.PHOTO, cost_handler), group=10)
    # Post-cost prompt (runs after cost_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_prompt_handler), group=11)

    # Router and guard
    app.add_handler(CallbackQueryHandler(cb_router))
    app.add_handler(MessageHandler(filters.ALL, busy_guard), group=100)

    return app


def set_telegram_app(app: Application) -> None:
    global TELEGRAM_APP
    TELEGRAM_APP = app


def start_polling_bot() -> None:
    # Python 3.12 threads do not have a loop by default
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _logger.info("Starting Telegram polling…")
    assert TELEGRAM_APP is not None, "TELEGRAM_APP not set"
    TELEGRAM_APP.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)
