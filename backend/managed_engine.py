"""Persistent order intent -> submission -> reconciliation -> inventory ledger.

Only the background worker dispatches orders. Dashboard commands persist requests.
Unknown submissions are reconciled indefinitely, never blindly resubmitted.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_DOWN
import json
import uuid
from zoneinfo import ZoneInfo
from sqlalchemy import select, update, func, text
from backend.config import config
from backend.models import AgentSettings
from backend.managed_models import ManagedAgent, ManagedOrder, ManagedFill, ManagedWallet, AgentEvent
from backend.managed_contracts import StrategyConfig
from backend.coinbase_execution import CoinbaseLive, ExchangeUnavailable, AmbiguousSubmission
from backend.model_adapter import infer

D = Decimal
ACTIVE = ('PENDING_SUBMISSION', 'SUBMITTING', 'UNKNOWN', 'ACCEPTED', 'PARTIALLY_FILLED', 'CANCEL_PENDING')
TERMINAL = ('FILLED', 'CANCELLED', 'REJECTED')


def floor(value, increment=D('.00000001')):
    return (D(value)/increment).to_integral_value(rounding=ROUND_DOWN)*increment


def order_dict(order):
    return {name: getattr(order, name) for name in ('id', 'side', 'quantity', 'client_order_id', 'exchange_order_id', 'state', 'purpose')}


def event(db, user_id, key, kind, payload):
    if not db.scalar(select(AgentEvent.id).where(AgentEvent.user_id == user_id, AgentEvent.event_key == key)):
        db.add(AgentEvent(user_id=user_id, event_key=key, kind=kind, payload=json.dumps(payload, default=str)))


def lock_agent(db, user_id):
    if db.bind.dialect.name == 'sqlite':
        db.execute(text('BEGIN IMMEDIATE'))
    return db.execute(select(ManagedAgent).where(ManagedAgent.user_id == user_id).with_for_update()).scalar_one()


class PaperExchange:
    mode = 'paper'

    def __init__(self):
        self.cancelled = set()

    def submit(self, order, market, settings):
        price = D(str(market['ask' if order['side'] == 'BUY' else 'bid']))
        price *= 1+settings.slippage if order['side'] == 'BUY' else 1-settings.slippage
        price = floor(price)
        return {'state': 'FILLED', 'id': 'paper-'+order['client_order_id'], 'fills': [{
            'trade_id': 'paper-fill-'+order['client_order_id'], 'quantity': order['quantity'],
            'price': price, 'fee': floor(price*order['quantity']*settings.fee_rate)}]}

    def lookup(self, order, market, settings):
        if order['client_order_id'] in self.cancelled:
            return {'state': 'CANCELLED', 'id': order.get('exchange_order_id'), 'fills': []}
        return self.submit(order, market, settings)

    def cancel(self, order):
        self.cancelled.add(order['client_order_id'])
        return True


def exit_reason(agent, wallet, market, settings, now):
    if wallet.quantity <= 0:
        return None
    if agent.close_requested:
        return 'MANUAL_CLOSE'
    if agent.phase == 'emergency' and settings.emergency_flatten:
        return 'EMERGENCY_FLATTEN'
    if wallet.cost_basis <= 0:
        return 'POSITION_BASIS_UNKNOWN'
    value = wallet.quantity*D(str(market['bid']))/wallet.cost_basis-1
    if value <= -settings.stop_loss:
        return 'STOP_LOSS'
    if value >= settings.take_profit:
        return 'TAKE_PROFIT'
    if agent.opened_at and (now-datetime.fromisoformat(agent.opened_at)).total_seconds() >= settings.max_holding_seconds:
        return 'MAX_HOLDING_TIME'
    return None


def entry_check(agent, wallet, prediction, market, settings, now, trades_today, pending):
    """Pure deterministic gate; callers can replay it in backtests."""
    codes = []
    if agent.phase != 'running': codes.append('ENTRIES_PAUSED')
    if not agent.recovered: codes.append('STARTUP_RECONCILIATION_REQUIRED')
    if pending: codes.append('ORDER_PENDING_OR_UNKNOWN')
    if wallet.quantity > 0: codes.append('POSITION_ALREADY_OPEN')
    age = (now-datetime.fromisoformat(market['updated_at'])).total_seconds()
    if not 0 <= age <= settings.max_quote_age_seconds: codes.append('STALE_QUOTE')
    bid, ask = D(str(market['bid'])), D(str(market['ask']))
    if bid <= 0 or ask < bid: codes.append('INVALID_BOOK')
    spread = (ask-bid)/ask if ask > 0 else D(1)
    if spread > settings.max_spread: codes.append('SPREAD_LIMIT')
    if not market.get('tradable'): codes.append('PRODUCT_NOT_TRADABLE')
    if prediction.data_quality != 'valid': codes.extend(prediction.reason_codes or ['INVALID_INPUT'])
    if prediction.product != settings.product or prediction.candle_interval_seconds != 3600 or prediction.horizon_seconds != 3600:
        codes.append('MODEL_CONTRACT_MISMATCH')
    if prediction.input_timestamp is None or not 0 <= (now-prediction.input_timestamp-timedelta(hours=1)).total_seconds() <= 600:
        codes.append('STALE_MODEL_INPUT')
    if not prediction.validated_for_orders: codes.append('MODEL_NOT_APPROVED')
    if prediction.predicted_return is None:
        codes.append('EXPECTED_RETURN_UNAVAILABLE')
    else:
        net = prediction.predicted_return - (2*settings.fee_rate + spread + 2*settings.slippage + settings.uncertainty_buffer)
        if net <= settings.min_net_return: codes.append('NET_RETURN_TOO_LOW')
    if prediction.probability_calibrated and (prediction.probability_up is None or prediction.probability_up < settings.probability_threshold):
        codes.append('CALIBRATED_PROBABILITY_TOO_LOW')
    equity = wallet.cash+wallet.quantity*bid
    if agent.day_equity-equity >= settings.max_daily_loss: codes.append('DAILY_LOSS_LIMIT')
    if agent.peak_equity > 0 and 1-equity/agent.peak_equity >= settings.max_drawdown: codes.append('DRAWDOWN_LIMIT')
    if trades_today >= settings.max_trades_per_day: codes.append('DAILY_TRADE_LIMIT')
    if agent.last_fill_at and (now-datetime.fromisoformat(agent.last_fill_at)).total_seconds() < settings.cooldown_seconds:
        codes.append('COOLDOWN')
    # Include expected execution losses in sizing so costs don't breach daily loss.
    risk_distance = settings.stop_loss+2*(settings.fee_rate+settings.slippage)+spread
    notional = min(settings.max_position_usdc/(1+settings.slippage), equity*settings.max_exposure_fraction/(1+settings.slippage),
                   equity*settings.risk_per_trade_fraction/risk_distance,
                   wallet.cash/(1+settings.fee_rate)/(1+settings.slippage),
                   max(D(0), settings.max_daily_loss-(agent.day_equity-equity))/risk_distance)
    if notional <= 0: codes.append('INSUFFICIENT_AVAILABLE_FUNDS')
    return list(dict.fromkeys(codes)), max(D(0), notional)


class ManagedEngine:
    def __init__(self, factory, adapter_factory=None):
        self.factory = factory
        self.adapter_factory = adapter_factory or (lambda agent: PaperExchange() if agent.mode in ('paper', 'backtest') else CoinbaseLive(agent.user_id))

    def apply(self, user_id, order_id, result, now):
        with self.factory.begin() as db:
            agent = lock_agent(db, user_id)
            wallet = db.get(ManagedWallet, (user_id, agent.mode))
            order = db.get(ManagedOrder, order_id)
            if order.user_id != user_id: raise ValueError('ORDER_OWNER_MISMATCH')
            if result.get('id'): order.exchange_order_id = result['id']
            for f in result.get('fills', []):
                if db.scalar(select(ManagedFill.id).where(ManagedFill.order_id == order.id, ManagedFill.trade_id == f['trade_id'])):
                    continue
                quantity, price, fee = (D(str(f[k])) for k in ('quantity', 'price', 'fee'))
                if quantity <= 0 or price <= 0 or fee < 0 or not all(x.is_finite() for x in (quantity, price, fee)):
                    raise ValueError('INVALID_FILL')
                if order.filled_quantity+quantity > order.quantity: raise ValueError('OVERFILL')
                pnl = D(0)
                if order.side == 'BUY':
                    cost = quantity*price+fee
                    if wallet.cash < cost: raise ValueError('FILL_EXCEEDS_CASH')
                    if wallet.quantity == 0: agent.opened_at = now.isoformat()
                    wallet.cash -= cost; wallet.quantity += quantity; wallet.cost_basis += cost
                else:
                    if wallet.quantity < quantity: raise ValueError('FILL_WOULD_SHORT')
                    basis = wallet.cost_basis*quantity/wallet.quantity
                    pnl = quantity*price-fee-basis
                    wallet.cash += quantity*price-fee; wallet.quantity -= quantity; wallet.cost_basis -= basis
                    wallet.realized_pnl += pnl
                    if wallet.quantity == 0:
                        agent.opened_at = None; agent.close_requested = False
                old_gross = order.filled_quantity*order.average_price
                order.filled_quantity += quantity
                order.average_price = (old_gross+quantity*price)/order.filled_quantity
                order.fees += fee
                agent.last_fill_at = now.isoformat()
                db.add(ManagedFill(user_id=user_id, order_id=order.id, trade_id=f['trade_id'], quantity=quantity,
                                   price=price, fee=fee, realized_pnl=pnl, created_at=now.isoformat()))
                event(db, user_id, 'fill:'+f['trade_id'], 'fill', {'order_id': order.id, 'quantity': quantity, 'price': price, 'fee': fee})
                db.flush()
            state = result['state']
            # An exchange FILLED without all fill details remains unresolved.
            if state == 'FILLED' and order.filled_quantity < order.quantity: state = 'UNKNOWN'
            order.state, order.updated_at = state, now.isoformat()
            if result.get('reason_code'):
                order.reason_code = result['reason_code']
            event(db, user_id, f'order:{order.id}:{state}:{order.filled_quantity}', 'order',
                  {'order_id': order.id, 'state': state, 'filled_quantity': order.filled_quantity})

    def dispatch(self, user_id, market, now, allow_new_entries=False):
        with self.factory() as db:
            agent = db.get(ManagedAgent, user_id)
            adapter = self.adapter_factory(agent)
            settings = StrategyConfig.model_validate_json(agent.config_json)
            phase = agent.phase
            orders = [order_dict(o) for o in db.scalars(select(ManagedOrder).where(
                ManagedOrder.user_id == user_id, ManagedOrder.state.in_(ACTIVE)).order_by(ManagedOrder.id))]
            cancelling = agent.cancel_requested or (agent.phase == 'emergency' and settings.emergency_cancel_entries)
        for order in orders:
            try:
                if order['state'] == 'PENDING_SUBMISSION' and order['purpose'] == 'entry' and (phase != 'running' or not allow_new_entries):
                    self.apply(user_id, order['id'], {'state': 'CANCELLED', 'fills': []}, now)
                    continue
                if cancelling and order['purpose'] == 'entry':
                    if order['state'] == 'PENDING_SUBMISSION':
                        self.apply(user_id, order['id'], {'state': 'CANCELLED', 'fills': []}, now)
                        continue
                    adapter.cancel(order)
                    # Cancellation acknowledgement is not a terminal state.
                    with self.factory.begin() as db:
                        db.get(ManagedOrder, order['id']).state = 'CANCEL_PENDING'
                if order['state'] == 'PENDING_SUBMISSION' and not cancelling:
                    with self.factory.begin() as db:
                        claim = db.execute(update(ManagedOrder).where(ManagedOrder.id == order['id'],
                            ManagedOrder.state == 'PENDING_SUBMISSION').values(state='SUBMITTING'))
                    if claim.rowcount != 1: continue
                    result = adapter.submit(order, market, settings)
                elif order['state'] == 'PENDING_SUBMISSION' and order['purpose'] == 'exit':
                    # Pauses and entry-cancellation requests do not suppress protective exits.
                    with self.factory.begin() as db:
                        claim = db.execute(update(ManagedOrder).where(ManagedOrder.id == order['id'],
                            ManagedOrder.state == 'PENDING_SUBMISSION').values(state='SUBMITTING'))
                    if claim.rowcount != 1: continue
                    result = adapter.submit(order, market, settings)
                else:
                    result = adapter.lookup(order, market, settings)
                self.apply(user_id, order['id'], result, now)
            except ExchangeUnavailable:
                with self.factory.begin() as db:
                    persisted = db.get(ManagedOrder, order['id'])
                    persisted.state = 'UNKNOWN'
                    persisted.reason_code = 'RECONCILIATION_REQUIRED'
        with self.factory.begin() as db:
            agent = db.get(ManagedAgent, user_id)
            if not db.scalar(select(ManagedOrder.id).where(ManagedOrder.user_id == user_id,
                    ManagedOrder.purpose == 'entry', ManagedOrder.state.in_(ACTIVE)).limit(1)):
                agent.cancel_requested = False

    def cycle(self, user_id, market, prediction=None, now=None):
        now = now or datetime.now(timezone.utc)
        try:
            book_numbers = [D(str(market[key])) for key in ('bid', 'ask', 'base_increment', 'base_min_size', 'quote_min_size')]
            if (not all(value.is_finite() and value > 0 for value in book_numbers)
                    or book_numbers[1] < book_numbers[0] or market.get('product') != 'XRP-USDC'):
                raise ValueError('Invalid market contract')
            datetime.fromisoformat(market['updated_at']).astimezone(timezone.utc)
        except (ValueError, KeyError, ArithmeticError):
            with self.factory.begin() as db:
                event(db, user_id, 'invalid-market:'+now.isoformat(), 'decision',
                      {'action': 'HOLD', 'reason_codes': ['INVALID_MARKET_DATA']})
            return
        # Reconcile existing orders BEFORE proposing any new action, including after restart.
        self.dispatch(user_id, market, now)
        with self.factory.begin() as db:
            agent = lock_agent(db, user_id)
            settings = StrategyConfig.model_validate_json(agent.config_json)
            wallet = db.get(ManagedWallet, (user_id, agent.mode))
            adapter = self.adapter_factory(agent)
            pending = bool(db.scalar(select(ManagedOrder.id).where(ManagedOrder.user_id == user_id, ManagedOrder.state.in_(ACTIVE)).limit(1)))
            if agent.mode == 'live':
                balances = adapter.readiness()
                external = adapter.open_orders()
                known = set(db.scalars(select(ManagedOrder.exchange_order_id).where(ManagedOrder.user_id == user_id)))
                if any(o['order_id'] not in known for o in external) or balances.get('XRP_total', balances['XRP']) != wallet.quantity:
                    agent.recovered = False
                    event(db, user_id, 'recovery:'+now.isoformat(), 'risk', {'reason_codes': ['ACCOUNT_STATE_MISMATCH']})
                    return
                wallet.cash = balances['USDC']
            agent.recovered = not pending
            agent.last_reconciled = now.isoformat()
            equity = wallet.cash+wallet.quantity*D(str(market['bid']))
            if agent.mode == 'live' and wallet.initial_equity == 0:
                wallet.initial_equity = equity
            day = now.astimezone(ZoneInfo(settings.reset_timezone)).date().isoformat()
            if day != agent.day: agent.day, agent.day_equity = day, equity
            agent.peak_equity = max(agent.peak_equity, equity)
            reason = exit_reason(agent, wallet, market, settings, now)
            fresh_quote = 0 <= (now-datetime.fromisoformat(market['updated_at'])).total_seconds() <= settings.max_quote_age_seconds
            if not (reason and fresh_quote and not pending):
                prediction = prediction or infer(market['candles'], now)
            # A validated adverse return can reduce inventory. It never opens a short.
            valid_forecast = (prediction is not None and prediction.validated_for_orders and prediction.data_quality == 'valid'
                and prediction.product == settings.product and prediction.horizon_seconds == 3600
                and prediction.candle_interval_seconds == 3600 and prediction.input_timestamp is not None
                and 0 <= (now-prediction.input_timestamp-timedelta(hours=1)).total_seconds() <= 600)
            exit_cost = settings.fee_rate+settings.slippage+settings.uncertainty_buffer+settings.min_net_return
            if (reason is None and wallet.quantity > 0 and valid_forecast
                    and prediction.predicted_return is not None and prediction.predicted_return < -exit_cost):
                reason = 'ADVERSE_RETURN_FORECAST'
            if wallet.quantity > 0 and not agent.opened_at: agent.opened_at = now.isoformat()
            if reason and fresh_quote and not pending:
                side, quantity, purpose = 'SELL', wallet.quantity, 'exit'
                exits = db.scalar(select(func.count(ManagedOrder.id)).where(ManagedOrder.user_id == user_id, ManagedOrder.purpose == 'exit'))
                key = f'exit:{agent.opened_at}:{reason}:{exits}'
                codes = [reason]
            else:
                fills = list(db.scalars(select(ManagedFill).where(ManagedFill.user_id == user_id)))
                today_orders = {f.order_id for f in fills if datetime.fromisoformat(f.created_at).astimezone(ZoneInfo(settings.reset_timezone)).date().isoformat() == day}
                codes, notional = entry_check(agent, wallet, prediction, market, settings, now, len(today_orders), pending)
                side, purpose = ('HOLD' if codes else 'BUY'), 'entry'
                quantity = notional/D(str(market['ask']))
                expected_candle = now.replace(minute=0, second=0, microsecond=0)-timedelta(hours=1)
                key = 'entry:' + (prediction.input_timestamp.isoformat() if prediction.input_timestamp else expected_candle.isoformat())
                if db.scalar(select(AgentEvent.id).where(AgentEvent.user_id == user_id, AgentEvent.event_key == 'decision:'+key)):
                    return
                event(db, user_id, 'prediction:'+key, 'prediction', prediction.model_dump(mode='json'))
            increment = D(str(market['base_increment']))
            quantity = floor(quantity, increment)
            minimum = D(str(market['quote_min_size']))
            if quantity <= 0 or quantity*D(str(market['bid'])) < minimum:
                side = 'HOLD'; codes.append('BELOW_PRODUCT_MINIMUM')
            if quantity < D(str(market['base_min_size'])):
                side = 'HOLD'; codes.append('BELOW_BASE_MINIMUM')
            if not fresh_quote:
                side = 'HOLD'; codes.append('STALE_QUOTE')
            event(db, user_id, 'decision:'+key, 'decision', {'action': side, 'reason_codes': codes, 'equity': equity})
            exists = db.scalar(select(ManagedOrder.id).where(ManagedOrder.user_id == user_id, ManagedOrder.signal_key == key))
            if side in ('BUY', 'SELL') and not exists:
                db.add(ManagedOrder(user_id=user_id, signal_key=key,
                    client_order_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f'crypto-agent:{user_id}:{agent.mode}:{key}')),
                    side=side, purpose=purpose, quantity=quantity, reason_code=codes[0] if codes else 'ENTRY_CHECKS_PASSED'))
        self.dispatch(user_id, market, now, allow_new_entries=True)
