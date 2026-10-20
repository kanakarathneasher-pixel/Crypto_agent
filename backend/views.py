"""Read-only user-scoped views shared by API and chatbot tools."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from sqlalchemy import select, func
from backend.config import config
from backend.models import (AgentSettings, RiskSettings, PaperBalance, PaperPosition, PaperOrder,
    PaperFill, Decision, PredictionRecord, MarketSnapshot)


def public_row(row):
    if row is None:
        return None
    hidden = {"password_hash", "token_hash", "exchange_secret_reference", "user_id"}
    return {column.name: getattr(row, column.name) for column in row.__table__.columns if column.name not in hidden}


def market(db):
    snapshot = db.get(MarketSnapshot, "XRP-USDC")
    if not snapshot:
        return {"product": "XRP-USDC", "price": None, "fresh": False, "updated_at": None}
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot.updated_at)).total_seconds()
    return {"product": snapshot.product, "price": snapshot.price, "updated_at": snapshot.updated_at,
            "age_seconds": age, "fresh": 0 <= age <= 120}


def settings(db, user_id):
    agent = public_row(db.get(AgentSettings, user_id))
    risk = public_row(db.get(RiskSettings, user_id))
    return {**agent, **risk, "operator_enabled": config.trading_enabled,
            "admin_caps": {"max_trades_per_day": 50, "max_position_usdc": 10000,
                           "max_allocation": .25, "max_daily_loss_usdc": 10000}}


def trades(db, user_id, limit=100):
    rows = db.execute(select(PaperFill, PaperOrder).join(PaperOrder, PaperFill.order_id == PaperOrder.id)
        .where(PaperFill.user_id == user_id, PaperOrder.user_id == user_id)
        .order_by(PaperFill.id.desc()).limit(limit))
    return [{**public_row(fill), "side": order.side, "product": order.product, "status": order.status,
             "notional": order.notional} for fill, order in rows]


def portfolio(db, user_id):
    balance = db.get(PaperBalance, user_id)
    positions = list(db.scalars(select(PaperPosition).where(PaperPosition.user_id == user_id)))
    quote = market(db)
    held = any(position.quantity > 0 for position in positions)
    value = balance.usdc + sum((p.quantity * quote["price"] for p in positions), Decimal(0)) if quote["price"] is not None else (balance.usdc if not held else None)
    return {"mode": "paper", "usdc": balance.usdc, "initial_usdc": balance.initial_usdc,
            "positions": [public_row(position) for position in positions], "equity_usdc": value,
            "pnl_usdc": value - balance.initial_usdc if value is not None else None,
            "price_fresh": quote["fresh"], "valuation_timestamp": quote["updated_at"]}


def latest_prediction(db, user_id):
    record = db.scalar(select(PredictionRecord).where(PredictionRecord.user_id == user_id)
                       .order_by(PredictionRecord.id.desc()).limit(1))
    if record is None:
        return None
    age = (datetime.now(timezone.utc) - (datetime.fromisoformat(record.candle_time) + timedelta(hours=1))).total_seconds()
    return {**public_row(record), "fresh": 0 <= age <= 600, "age_seconds_since_candle_completed": age}


def decisions(db, user_id, limit=100):
    return [public_row(row) for row in db.scalars(select(Decision).where(Decision.user_id == user_id)
                                               .order_by(Decision.id.desc()).limit(limit))]


def status(db, user_id):
    agent = db.get(AgentSettings, user_id)
    today = datetime.now(timezone.utc).date().isoformat()
    count = db.scalar(select(func.count(PaperFill.id)).where(PaperFill.user_id == user_id,
                          PaperFill.created_at >= today + "T00:00:00+00:00"))
    recent = decisions(db, user_id, 1)
    return {"mode": "paper", "running": agent.enabled and not agent.emergency_stop and config.trading_enabled,
            "requested_enabled": agent.enabled, "emergency_stop": agent.emergency_stop,
            "operator_enabled": config.trading_enabled, "trades_today": count,
            "last_cycle": recent[0] if recent else None}


def performance(db, user_id):
    book = portfolio(db, user_id)
    fills = list(db.execute(select(PaperFill, PaperOrder).join(PaperOrder, PaperFill.order_id == PaperOrder.id)
                           .where(PaperFill.user_id == user_id, PaperOrder.user_id == user_id)))
    exits = [fill for fill, order in fills if order.side == "SELL"]
    equity = list(db.scalars(select(Decision.equity).where(Decision.user_id == user_id).order_by(Decision.id)))
    peak, drawdown = book["initial_usdc"], Decimal(0)
    for value in equity:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    return {**book, "total_return": book["pnl_usdc"] / book["initial_usdc"] if book["pnl_usdc"] is not None else None,
            "fills": len(fills), "fees_usdc": sum((fill.fee for fill, _ in fills), Decimal(0)),
            "max_drawdown": drawdown, "win_rate": sum(fill.realized_pnl > 0 for fill in exits) / len(exits) if exits else None,
            "metric_note": "Drawdown uses recorded hourly cycles; win rate uses realized SELL fills."}


def snapshot(db, user_id):
    return {"agent": status(db, user_id), "market": market(db), "prediction": latest_prediction(db, user_id),
            "portfolio": portfolio(db, user_id), "settings": settings(db, user_id),
            "trades": trades(db, user_id, 20), "decisions": decisions(db, user_id, 20),
            "performance": performance(db, user_id)}
