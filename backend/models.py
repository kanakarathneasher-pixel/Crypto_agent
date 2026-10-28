"""Per-user records. Money uses exact scaled integers on SQLite/PostgreSQL."""
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Money(TypeDecorator):
    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else int((Decimal(str(value)) * 100000000).to_integral_value())

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value) / Decimal(100000000)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[str] = mapped_column(String(40))


class GoogleIdentity(Base):
    __tablename__ = 'google_identities'
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), unique=True)
    email: Mapped[str] = mapped_column(String(320))


class GoogleLoginChallenge(Base):
    __tablename__ = 'google_login_challenges'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_hash: Mapped[str] = mapped_column(String(64), index=True)
    nonce_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[str] = mapped_column(String(40))


class AgentSettings(Base):
    __tablename__ = "agent_settings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    product: Mapped[str] = mapped_column(String(30), default="XRP-USDC")
    sizing_mode: Mapped[str] = mapped_column(String(10), default="automatic")
    manual_size_usdc: Mapped[Decimal] = mapped_column(Money, default=Decimal("10"))
    buy_threshold: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.02"))
    sell_threshold: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.02"))
    fee_rate: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.006"))
    slippage_rate: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.001"))
    # Future exchange connections may reference an external secrets vault only.
    exchange_secret_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RiskSettings(Base):
    __tablename__ = "risk_settings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    max_trades_per_day: Mapped[int] = mapped_column(Integer, default=5)
    max_position_usdc: Mapped[Decimal] = mapped_column(Money, default=Decimal("25"))
    max_allocation: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.10"))
    max_daily_loss_usdc: Mapped[Decimal] = mapped_column(Money, default=Decimal("25"))


class PaperBalance(Base):
    __tablename__ = "paper_balances"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    usdc: Mapped[Decimal] = mapped_column(Money)
    initial_usdc: Mapped[Decimal] = mapped_column(Money)
    day: Mapped[str] = mapped_column(String(10), default="")
    day_start_equity: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    product: Mapped[str] = mapped_column(String(30), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cost_basis: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    realized_pnl: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))


class ModelVersion(Base):
    __tablename__ = "model_versions"
    version: Mapped[str] = mapped_column(String(100), primary_key=True)
    product: Mapped[str] = mapped_column(String(30))
    metadata_json: Mapped[str] = mapped_column(Text)


class PredictionRecord(Base):
    __tablename__ = "prediction_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    candle_time: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    model_version: Mapped[str] = mapped_column(ForeignKey("model_versions.version"))
    predicted_return: Mapped[Decimal] = mapped_column(Money)
    estimated_price: Mapped[Decimal] = mapped_column(Money)


class Decision(Base):
    __tablename__ = "trading_decisions"
    __table_args__ = (UniqueConstraint("user_id", "product", "candle_time"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product: Mapped[str] = mapped_column(String(30))
    candle_time: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    signal: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(Text)
    equity: Mapped[Decimal] = mapped_column(Money)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("prediction_records.id"), nullable=True)


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("trading_decisions.id"), unique=True)
    side: Mapped[str] = mapped_column(String(10))
    product: Mapped[str] = mapped_column(String(30))
    notional: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(20), default="approved")
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class PaperFill(Base):
    __tablename__ = "paper_fills"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("paper_orders.id"), unique=True)
    quantity: Mapped[Decimal] = mapped_column(Money)
    price: Mapped[Decimal] = mapped_column(Money)
    fee: Mapped[Decimal] = mapped_column(Money)
    realized_pnl: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class ExecutionLog(Base):
    __tablename__ = "agent_execution_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    level: Mapped[str] = mapped_column(String(15))
    message: Mapped[str] = mapped_column(Text)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    product: Mapped[str] = mapped_column(String(30), primary_key=True)
    updated_at: Mapped[str] = mapped_column(String(40))
    price: Mapped[Decimal] = mapped_column(Money)
    candles_json: Mapped[str] = mapped_column(Text)
