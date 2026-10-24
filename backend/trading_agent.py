"""Transactional paper orders. A cycle is unique per user/product/candle."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from sqlalchemy import select, func, text
from backend.config import config
from backend.models import (User, AgentSettings, RiskSettings, PaperBalance, PaperPosition,
    Decision, PaperOrder, PaperFill, PredictionRecord, ModelVersion, ExecutionLog)
from backend.risk_manager import RiskContext, approve, signal_for, down

D = Decimal


def execute_cycle(session, user_id, market, prediction=None, prediction_error=None, now=None,
                  advisory=None, advisory_error=None):
    """Caller owns transaction. Serialize user updates before examining risk state."""
    now = now or datetime.now(timezone.utc)
    if session.bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    session.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one()
    settings = session.get(AgentSettings, user_id)
    risk = session.get(RiskSettings, user_id)
    balance = session.get(PaperBalance, user_id)
    position = session.get(PaperPosition, (user_id, settings.product))
    candle_time = market["candles"].open_time.iloc[-1].isoformat()
    prior = session.scalar(select(Decision).where(Decision.user_id == user_id,
        Decision.product == settings.product, Decision.candle_time == candle_time))
    if prior:
        return prior  # Durable idempotency, including HOLD decisions.
    price = D(str(market["price"]))
    equity = balance.usdc + position.quantity * price
    today = now.date().isoformat()
    if balance.day != today:
        balance.day, balance.day_start_equity = today, equity
    loss = max(D(0), balance.day_start_equity - equity)
    trades_today = session.scalar(select(func.count(PaperFill.id)).where(
        PaperFill.user_id == user_id, PaperFill.created_at >= today + "T00:00:00+00:00"))
    candle_end = datetime.fromisoformat(candle_time) + timedelta(hours=1)
    observed = datetime.fromisoformat(market["updated_at"])
    fresh = (0 <= (now - observed).total_seconds() <= 120
             and 0 <= (now - candle_end).total_seconds() <= 600)
    prediction_id = None
    if prediction:
        if not session.get(ModelVersion, prediction["version"]):
            session.add(ModelVersion(version=prediction["version"], product=settings.product,
                                     metadata_json=json.dumps(prediction["metadata"])))
            session.flush()
        record = PredictionRecord(user_id=user_id, candle_time=candle_time,
            model_version=prediction["version"], predicted_return=D(str(prediction["predicted_return"])),
            estimated_price=D(str(prediction["estimated_price"])))
        session.add(record)
        session.flush()
        prediction_id = record.id
    value = D(str(prediction["predicted_return"])) if prediction else None
    signal, explanation = signal_for(value, settings)
    prediction_valid = bool(prediction and prediction.get("validated") and prediction.get("candle_time") == candle_time)
    context = RiskContext(config.trading_enabled and settings.enabled, settings.emergency_stop, fresh,
        prediction is not None, prediction_valid, trades_today, loss, balance.usdc, position.quantity, price)
    notional, reason = approve(signal, context, settings, risk)
    advisory_note = None
    if advisory:
        advisory_note = (f"Research classifier {advisory['version']}: {advisory['direction']}, "
                         f"P(UP)={advisory['probability_up']:.4f}. Observation only; not order input.")
        session.add(ExecutionLog(user_id=user_id, level='INFO',
                                 message='Research forecast: ' + json.dumps(advisory)))
    elif advisory_error:
        advisory_note = 'Research forecast unavailable: ' + advisory_error
    decision = Decision(user_id=user_id, product=settings.product, candle_time=candle_time,
        signal=signal, action=signal if notional > 0 else "HOLD",
        reason=" ".join(filter(None, [explanation, reason, prediction_error, advisory_note])),
        equity=equity, prediction_id=prediction_id)
    session.add(decision)
    session.flush()
    if notional:
        order = PaperOrder(user_id=user_id, decision_id=decision.id, side=signal,
                           product=settings.product, notional=notional, status="approved")
        session.add(order)
        session.flush()
        fill_price = down(price * (1 + settings.slippage_rate if signal == "BUY" else 1 - settings.slippage_rate))
        quantity = down(notional / price)
        gross = down(quantity * fill_price)
        fee = down(gross * settings.fee_rate)
        realized = D(0)
        if signal == "BUY":
            if gross + fee > balance.usdc:
                raise ValueError("Paper fill would exceed available cash.")
            balance.usdc -= gross + fee
            position.quantity += quantity
            position.cost_basis += gross + fee
        else:
            if quantity > position.quantity:
                raise ValueError("Paper fill would short XRP.")
            cost = down(position.cost_basis * quantity / position.quantity)
            realized = gross - fee - cost
            balance.usdc += gross - fee
            position.quantity -= quantity
            position.cost_basis -= cost
            position.realized_pnl += realized
        order.status = "filled"
        session.add(PaperFill(user_id=user_id, order_id=order.id, quantity=quantity,
                              price=fill_price, fee=fee, realized_pnl=realized, created_at=now.isoformat()))
        decision.equity = balance.usdc + position.quantity * price
    session.add(ExecutionLog(user_id=user_id, level="INFO", message=f"{candle_time}: {decision.action}: {decision.reason}"))
    return decision
