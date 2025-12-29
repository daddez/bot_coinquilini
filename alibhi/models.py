from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    BigInteger,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)

from .db import Base


class WebSession(Base):
    __tablename__ = "websessions"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    nome = Column(String, nullable=False)
    cognome = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String, nullable=False, default="attiva")  # 'attiva' | 'scaduta'
    type = Column(String, nullable=False, default="spesa_live")
    carousels = Column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    slot = Column(String, nullable=False, unique=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("slot", name="uq_user_slot"),
    )


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(String, default="da_acquistare", nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)

    purchase_date = Column(DateTime, nullable=True)
    buyer = Column(String, nullable=True)
    shopping_session = Column(Integer, nullable=True)


@event.listens_for(Product, "before_update")
def _product_before_update(mapper, connection, target):
    target.updated_at = dt.datetime.utcnow()


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    nome = Column(String, nullable=False)
    cognome = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    operation = Column(String, nullable=False, default="spesa")
    receipt_path = Column(Text, nullable=False)


class Carousel(Base):
    __tablename__ = "carousels"
    sid = Column(String, primary_key=True)
    cid = Column(String, primary_key=True)
    items_json = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    def items(self):
        return json.loads(self.items_json)


class CleaningArea(Base):
    __tablename__ = "pulizie"
    luogo = Column(String, primary_key=True)
    giorno = Column(String, nullable=False, default="da decidere")
    pulitore_1 = Column(BigInteger, nullable=True)
    pulitore_2 = Column(BigInteger, nullable=True)
    pulitore_3 = Column(BigInteger, nullable=True)
    pulitore_4 = Column(BigInteger, nullable=True)
    pulitore_5 = Column(BigInteger, nullable=True)
    pulitore_6 = Column(BigInteger, nullable=True)
    prossimo = Column(BigInteger, nullable=True)


class CleaningPoll(Base):
    __tablename__ = "cleaning_polls"
    id = Column(Integer, primary_key=True)
    area_key = Column(String, nullable=False)
    started_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    creator_id = Column(BigInteger, nullable=False)
    participant_ids = Column(Text, nullable=False)  # JSON list[int]
    status = Column(String, default="open", nullable=False)  # 'open' | 'closed'
    result_day = Column(Integer, nullable=True)  # 0..6


class CleaningVote(Base):
    __tablename__ = "cleaning_votes"
    poll_id = Column(Integer, primary_key=True)
    voter_id = Column(BigInteger, primary_key=True)
    day = Column(Integer, nullable=False)
    voted_at = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
