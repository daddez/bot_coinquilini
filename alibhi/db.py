from __future__ import annotations

import datetime as dt
import json
import secrets
from typing import Optional

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL, logger

Base = declarative_base()

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create tables and migrate legacy purchases -> transactions if applicable."""
    from sqlalchemy import text

    Base.metadata.create_all(engine)

    insp = inspect(engine)
    has_purchases = insp.has_table("purchases")
    has_transactions = insp.has_table("transactions")

    if has_purchases and has_transactions:
        try:
            with engine.begin() as conn:
                count_tx = conn.exec_driver_sql("SELECT COUNT(1) FROM transactions").scalar()
                if count_tx == 0:
                    conn.exec_driver_sql(
                        """
                        INSERT INTO transactions (telegram_id, nome, cognome, date, amount, operation, receipt_path)
                        SELECT telegram_id, nome, cognome, date, (0 - ABS(cost)) AS amount, 'spesa' AS operation, receipt_path
                        FROM purchases
                        """
                    )
                    try:
                        conn.exec_driver_sql("DROP TABLE purchases")
                    except Exception:
                        pass
        except Exception:
            logger.exception("[init_db] Migrazione da purchases a transactions fallita")

    # Lightweight migrations for Telegram ID sizes when running on PostgreSQL.
    try:
        if engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                stmts = [
                    # Core tables
                    "ALTER TABLE IF EXISTS websessions ALTER COLUMN telegram_id TYPE BIGINT",
                    "ALTER TABLE IF EXISTS users ALTER COLUMN telegram_id TYPE BIGINT",
                    "ALTER TABLE IF EXISTS transactions ALTER COLUMN telegram_id TYPE BIGINT",
                    # Cleaning tables
                    "ALTER TABLE IF EXISTS cleaning_polls ALTER COLUMN creator_id TYPE BIGINT",
                    "ALTER TABLE IF EXISTS cleaning_votes ALTER COLUMN voter_id TYPE BIGINT",
                    # pulizie columns may be NULL; cast explicitly
                    "ALTER TABLE IF EXISTS pulizie ALTER COLUMN pulitore_1 TYPE BIGINT USING NULLIF(pulitore_1::text, '')::BIGINT",
                    "ALTER TABLE IF EXISTS pulizie ALTER COLUMN pulitore_2 TYPE BIGINT USING NULLIF(pulitore_2::text, '')::BIGINT",
                    "ALTER TABLE IF EXISTS pulizie ALTER COLUMN pulitore_3 TYPE BIGINT USING NULLIF(pulitore_3::text, '')::BIGINT",
                    "ALTER TABLE IF EXISTS pulizie ALTER COLUMN pulitore_4 TYPE BIGINT USING NULLIF(pulitore_4::text, '')::BIGINT",
                    "ALTER TABLE IF EXISTS pulizie ALTER COLUMN pulitore_5 TYPE BIGINT USING NULLIF(pulitore_5::text, '')::BIGINT",
                    "ALTER TABLE IF EXISTS pulizie ALTER COLUMN pulitore_6 TYPE BIGINT USING NULLIF(pulitore_6::text, '')::BIGINT",
                    "ALTER TABLE IF EXISTS pulizie ALTER COLUMN prossimo TYPE BIGINT USING NULLIF(prossimo::text, '')::BIGINT",
                ]
                for s in stmts:
                    try:
                        conn.exec_driver_sql(s)
                    except Exception:
                        # Ignore if column already BIGINT or table missing
                        pass
    except Exception:
        logger.exception("[init_db] errore migrazione BIGINT per telegram_id")


def _new_session_token() -> str:
    return secrets.token_hex(32)


def create_web_session(chat_id: int, *, type_: str = "spesa_live", carousels: Optional[str] = None) -> str:
    """
    Create a new WebSession and return its token.
    type_:
      - 'spesa_live'     -> expires only via /api/finish
      - 'estratto_conto' -> expires by TTL timer
    """
    from .models import WebSession, User

    with SessionLocal() as db:
        user = db.get(User, chat_id)
        if not user:
            raise RuntimeError(f"Utente {chat_id} non registrato")

        now = dt.datetime.utcnow()
        tok = _new_session_token()
        ws = WebSession(
            telegram_id=chat_id,
            nome=user.first_name,
            cognome=user.last_name,
            started_at=now,
            token=tok,
            status="attiva",
            type=type_,
            carousels=carousels,
        )
        db.add(ws)
        db.commit()
        return tok


def get_balance(telegram_id: Optional[int] = None):
    from decimal import Decimal
    from sqlalchemy import func
    from .models import Transaction

    with SessionLocal() as db:
        if telegram_id is None:
            q = select(func.coalesce(func.sum(Transaction.amount), 0))
        else:
            q = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.telegram_id == telegram_id
            )
        total = db.execute(q).scalar() or 0
        return Decimal(str(total))


def ensure_minimum_data() -> None:
    """Optionally seed a few demo products if empty."""
    from sqlalchemy import func
    from .models import Product

    with SessionLocal() as db:
        count = db.execute(select(func.count(Product.id))).scalar() or 0
        if count == 0:
            db.add_all([Product(name="Latte"), Product(name="Pane"), Product(name="Pasta")])
            db.commit()

        # Non creiamo/alteriamo la tabella 'pulizie' qui: verrà gestita manualmente.
