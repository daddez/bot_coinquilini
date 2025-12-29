"""Alibhi package split from monolithic bot.py.

Modules are organized to keep concerns separated:
- config: env, constants, logging
- db: engine, sessions, init, db helpers
- models: SQLAlchemy ORM models
- schemas: light dataclasses and in-memory state
- utils: helpers shared across bot and web
- keyboards: Telegram keyboards and labels
- tasks: background tasks (purge, cleaning notifier)
- bot: Telegram bot app and handlers
- web: FastAPI app and routes
"""

