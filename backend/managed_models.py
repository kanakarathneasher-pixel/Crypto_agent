"""Execution tables and isolated ledgers; legacy paper history is preserved."""
from decimal import Decimal
from sqlalchemy import ForeignKey, String, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.models import Base, Money, utcnow


class ManagedAgent(Base):
    __tablename__ = 'managed_agents'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    mode: Mapped[str] = mapped_column(String(15), default='paper')
    phase: Mapped[str] = mapped_column(String(20), default='paused')
    config_json: Mapped[str] = mapped_column(Text)
    recovered: Mapped[bool] = mapped_column(Boolean, default=False)
    day: Mapped[str] = mapped_column(String(10), default='')
    day_equity: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    peak_equity: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    opened_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_fill_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_reconciled: Mapped[str | None] = mapped_column(String(40), nullable=True)
    close_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)


class ManagedOrder(Base):
    __tablename__ = 'managed_orders'
    __table_args__ = (UniqueConstraint('user_id', 'signal_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    signal_key: Mapped[str] = mapped_column(String(160))
    client_order_id: Mapped[str] = mapped_column(String(40), unique=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    side: Mapped[str] = mapped_column(String(5))
    purpose: Mapped[str] = mapped_column(String(15))
    state: Mapped[str] = mapped_column(String(25), default='PENDING_SUBMISSION')
    quantity: Mapped[Decimal] = mapped_column(Money)
    filled_quantity: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    average_price: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    fees: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    updated_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    reason_code: Mapped[str] = mapped_column(String(80), default='INTENT_PERSISTED')


class ManagedWallet(Base):
    __tablename__ = 'managed_wallets'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    mode: Mapped[str] = mapped_column(String(15), primary_key=True)
    cash: Mapped[Decimal] = mapped_column(Money, default=Decimal(1000))
    quantity: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    cost_basis: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    realized_pnl: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    initial_equity: Mapped[Decimal] = mapped_column(Money, default=Decimal(1000))


class ManagedFill(Base):
    __tablename__ = 'managed_fills'
    __table_args__ = (UniqueConstraint('order_id', 'trade_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('managed_orders.id'))
    trade_id: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[Decimal] = mapped_column(Money)
    price: Mapped[Decimal] = mapped_column(Money)
    fee: Mapped[Decimal] = mapped_column(Money)
    realized_pnl: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class AgentEvent(Base):
    __tablename__ = 'managed_events'
    __table_args__ = (UniqueConstraint('user_id', 'event_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    event_key: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
