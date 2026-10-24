"""Execution tests use explicit synthetic approved predictions, never production approval."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest
from sqlalchemy import select, func
from backend.managed_contracts import StrategyConfig, PredictionContract
from backend.managed_engine import ManagedEngine, PaperExchange, entry_check
from backend.managed_models import ManagedAgent, ManagedWallet, ManagedOrder, ManagedFill, AgentEvent
from backend.coinbase_execution import CoinbaseLive, AmbiguousSubmission, ExchangeUnavailable, normalize_order
from backend.config import config
from tests.test_backend import database, client, market_at

NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def market(now=NOW):
    result = market_at(now)
    result.update(bid=D('2'), ask=D('2.001'), base_increment='.000001',
                  base_min_size='.1', quote_min_size='1', tradable=True)
    return result


def prediction(now=NOW, **changes):
    fields = dict(model_version='synthetic-test-only', input_timestamp=now-timedelta(hours=1),
                  prediction_timestamp=now, output_kind='return', predicted_return=D('.10'),
                  validated_for_orders=True, data_quality='valid')
    fields.update(changes)
    return PredictionContract(**fields)


def configure(client):
    result = client.put('/v2/agent/configuration', json={'mode': 'paper'})
    assert result.status_code == 200, result.text
    assert client.post('/v2/agent/commands', json={'action': 'start', 'request_id': 'start-0001'}).status_code == 200


def test_paper_duplicate_pause_and_protective_exit(client, database, monkeypatch):
    configure(client)
    engine = ManagedEngine(database)
    engine.cycle(1, market(), prediction(), NOW)
    engine.cycle(1, market(), prediction(), NOW)
    with database() as db:
        assert db.scalar(select(func.count(ManagedFill.id))) == 1
        assert db.get(ManagedWallet, (1, 'paper')).quantity > 0
    assert client.post('/v2/agent/commands', json={'action': 'pause', 'request_id': 'pause-0001'}).status_code == 200
    later = NOW+timedelta(minutes=1)
    quote = market(later)
    quote.update(bid=D('1.8'), ask=D('1.801'))
    monkeypatch.setattr('backend.managed_engine.infer', Mock(side_effect=AssertionError('Exit must not depend on ML')))
    engine.cycle(1, quote, now=later)
    with database() as db:
        wallet = db.get(ManagedWallet, (1, 'paper'))
        assert wallet.quantity == 0 and wallet.cash > 0 and wallet.realized_pnl < 0
        assert db.scalar(select(func.count(ManagedFill.id))) == 2
        assert db.scalars(select(ManagedOrder).order_by(ManagedOrder.id)).all()[-1].reason_code == 'STOP_LOSS'


def test_ambiguous_submission_partial_fill_restart(client, database):
    configure(client)
    class Exchange:
        calls = 0
        partial = False
        complete = False
        def submit(self, order, quote, settings):
            self.calls += 1
            raise AmbiguousSubmission('timeout')
        def lookup(self, order, quote, settings):
            fills = []
            if self.partial:
                fills.append(dict(trade_id='first', quantity=order['quantity']/2, price=D(2), fee=D('.01')))
            if self.complete:
                fills.append(dict(trade_id='second', quantity=order['quantity']/2, price=D(2), fee=D('.01')))
            return {'state': 'FILLED' if self.complete else 'PARTIALLY_FILLED' if fills else 'UNKNOWN', 'id': 'exchange-1', 'fills': fills}
    exchange = Exchange()
    engine = ManagedEngine(database, lambda agent: exchange)
    engine.cycle(1, market(), prediction(), NOW)
    with database() as db:
        order = db.scalar(select(ManagedOrder))
        assert order.state == 'UNKNOWN'
        client_id = order.client_order_id
    exchange.partial = True
    ManagedEngine(database, lambda agent: exchange).cycle(1, market(), prediction(), NOW)
    with database() as db:
        assert db.scalar(select(ManagedOrder)).state == 'PARTIALLY_FILLED'
        assert db.scalar(select(func.count(ManagedFill.id))) == 1
    exchange.complete = True
    engine.cycle(1, market(), prediction(), NOW)
    engine.cycle(1, market(), prediction(), NOW)
    with database() as db:
        order = db.scalar(select(ManagedOrder))
        assert order.state == 'FILLED' and order.client_order_id == client_id
        assert db.scalar(select(func.count(ManagedFill.id))) == 2
        assert db.get(ManagedWallet, (1, 'paper')).quantity == order.quantity
    assert exchange.calls == 1


@pytest.mark.parametrize('change,expected', [
    ({'predicted_return': D('.001')}, 'NET_RETURN_TOO_LOW'),
    ({'predicted_return': None}, 'EXPECTED_RETURN_UNAVAILABLE'),
    ({'validated_for_orders': False}, 'MODEL_NOT_APPROVED'),
    ({'data_quality': 'invalid'}, 'INVALID_INPUT'),
    ({'input_timestamp': NOW-timedelta(hours=2)}, 'STALE_MODEL_INPUT'),
    ({'product': 'SOL-USDC'}, 'MODEL_CONTRACT_MISMATCH'),
    ({'probability_calibrated': True, 'probability_up': D('.4')}, 'CALIBRATED_PROBABILITY_TOO_LOW'),
])
def test_prediction_gates(change, expected):
    agent = SimpleNamespace(phase='running', recovered=True, day_equity=D(1000), peak_equity=D(1000), last_fill_at=None)
    wallet = SimpleNamespace(cash=D(1000), quantity=D(0))
    codes, _ = entry_check(agent, wallet, prediction(**change), market(), StrategyConfig(), NOW, 0, False)
    assert expected in codes


@pytest.mark.parametrize('case,expected', [
    ('pause', 'ENTRIES_PAUSED'), ('recovery', 'STARTUP_RECONCILIATION_REQUIRED'),
    ('pending', 'ORDER_PENDING_OR_UNKNOWN'), ('position', 'POSITION_ALREADY_OPEN'),
    ('daily', 'DAILY_LOSS_LIMIT'), ('drawdown', 'DRAWDOWN_LIMIT'),
    ('count', 'DAILY_TRADE_LIMIT'), ('cooldown', 'COOLDOWN'), ('stale', 'STALE_QUOTE'),
    ('spread', 'SPREAD_LIMIT'), ('product', 'PRODUCT_NOT_TRADABLE'), ('cash', 'INSUFFICIENT_AVAILABLE_FUNDS')])
def test_risk_controls(case, expected):
    agent = SimpleNamespace(phase='running', recovered=True, day_equity=D(1000), peak_equity=D(1000), last_fill_at=None)
    wallet = SimpleNamespace(cash=D(1000), quantity=D(0))
    quote = market()
    if case == 'pause': agent.phase = 'paused'
    if case == 'recovery': agent.recovered = False
    if case == 'position': wallet.quantity = D(1)
    if case == 'daily': agent.day_equity = D(1100)
    if case == 'drawdown': agent.peak_equity = D(1200)
    if case == 'cooldown': agent.last_fill_at = NOW.isoformat()
    if case == 'stale': quote['updated_at'] = (NOW-timedelta(minutes=10)).isoformat()
    if case == 'spread': quote['ask'] = D(3)
    if case == 'product': quote['tradable'] = False
    if case == 'cash': wallet.cash = D(0)
    codes, size = entry_check(agent, wallet, prediction(), quote, StrategyConfig(), NOW, 5 if case == 'count' else 0, case == 'pending')
    assert expected in codes
    assert size <= D(25)


def test_controls_auth_idempotency_emergency_and_isolation(client, database):
    configure(client)
    body = {'action': 'emergency_stop', 'request_id': 'emergency-1'}
    assert client.post('/v2/agent/commands', json=body).status_code == 200
    assert client.post('/v2/agent/commands', json=body).json()['duplicate']
    assert client.post('/v2/agent/commands', json={**body, 'action': 'resume'}).status_code == 409
    assert client.post('/v2/agent/commands', json={'action': 'resume', 'request_id': 'resume-123'}).status_code == 409
    assert client.put('/v2/agent/configuration', json={'mode': 'live'}).status_code == 409
    assert client.post('/auth/register', json={'username': 'bob', 'password': 'second-test-password'}).status_code == 201
    assert not client.get('/v2/agent/status').json()['configured']
    for path in ('orders', 'fills', 'activity'):
        assert client.get('/v2/agent/'+path).json() == []
    assert client.get('/v2/agent/prediction').json()['prediction'] is None
    assert client.post('/v2/agent/commands', json=body).status_code == 409
    client.post('/auth/logout')
    assert client.get('/v2/agent/status').status_code == 401
    assert client.post('/v2/agent/commands', json=body).status_code == 401


def test_paper_never_calls_live(client, database, monkeypatch):
    configure(client)
    monkeypatch.setattr(CoinbaseLive, 'submit', Mock(side_effect=AssertionError('live called')))
    ManagedEngine(database).cycle(1, market(), prediction(), NOW)
    CoinbaseLive.submit.assert_not_called()
    assert len(client.get('/v2/agent/fills').json()) == 1
    assert client.get('/v2/agent/performance').status_code == 200
    assert client.get('/v2/agent/orders?after=0&limit=0').status_code == 422


def test_live_gate_and_ambiguous_post(monkeypatch):
    monkeypatch.setattr(config, 'live_owner_user_id', 1)
    monkeypatch.setattr(config, 'live_execution_enabled', False)
    session = Mock()
    exchange = CoinbaseLive(1, session)
    exchange.token = Mock(return_value='test-only')
    with pytest.raises(ExchangeUnavailable, match='DISABLED'):
        exchange.request('POST', '/api/v3/brokerage/orders', {})
    session.request.assert_not_called()
    monkeypatch.setattr(config, 'live_execution_enabled', True)
    session.request.return_value.status_code = 503
    with pytest.raises(AmbiguousSubmission):
        exchange.request('POST', '/api/v3/brokerage/orders', {})
    assert session.request.call_count == 1


def test_cancel_ack_is_not_fill():
    assert normalize_order({'status': 'CANCEL_QUEUED', 'order_id': 'a'}, [])['state'] == 'CANCEL_PENDING'
    result = normalize_order({'status': 'OPEN', 'order_id': 'a'}, [dict(price='2', size='1', commission='.01', trade_id='x')])
    assert result['state'] == 'PARTIALLY_FILLED'


def test_invalid_book_records_hold(client, database):
    configure(client)
    quote = market()
    quote['ask'] = 'NaN'
    ManagedEngine(database).cycle(1, quote, prediction(), NOW)
    with database() as db:
        assert db.scalar(select(func.count(ManagedOrder.id))) == 0
        result = db.scalar(select(AgentEvent).where(AgentEvent.kind == 'decision'))
        assert json.loads(result.payload)['reason_codes'] == ['INVALID_MARKET_DATA']


def test_stale_hold_does_not_consume_next_hour_signal(client, database):
    configure(client)
    engine = ManagedEngine(database)
    unavailable = prediction(input_timestamp=None, data_quality='stale', predicted_return=None)
    engine.cycle(1, market(), unavailable, NOW)
    later = NOW+timedelta(hours=1)
    engine.cycle(1, market(later), prediction(later), later)
    with database() as db:
        assert db.scalar(select(func.count(ManagedFill.id))) == 1


def test_restart_cancels_unsubmitted_intent(client, database):
    configure(client)
    with database.begin() as db:
        db.add(ManagedOrder(user_id=1, signal_key='old-intent', client_order_id='stable-old-id',
                            side='BUY', purpose='entry', quantity=D(1)))
    adapter = Mock()
    engine = ManagedEngine(database, lambda agent: adapter)
    engine.dispatch(1, market(), NOW)
    adapter.submit.assert_not_called()
    with database() as db:
        assert db.scalar(select(ManagedOrder)).state == 'CANCELLED'


def test_emergency_default_preserves_position_and_pause_monitoring(client, database):
    configure(client)
    engine = ManagedEngine(database)
    engine.cycle(1, market(), prediction(), NOW)
    client.post('/v2/agent/commands', json={'action':'emergency_stop','request_id':'stop-0002'})
    engine.cycle(1, market(), prediction(), NOW)
    with database() as db:
        assert db.get(ManagedWallet, (1, 'paper')).quantity > 0
        assert db.scalar(select(func.count(ManagedFill.id))) == 1


def test_cancellation_waits_for_terminal_reconciliation(client, database):
    configure(client)
    with database.begin() as db:
        db.add(ManagedOrder(user_id=1, signal_key='accepted-order', client_order_id='accepted-id',
            exchange_order_id='exchange-id', side='BUY', purpose='entry', quantity=D(1), state='ACCEPTED'))
        db.get(ManagedAgent, 1).cancel_requested = True
    adapter = Mock()
    adapter.cancel.return_value = True
    adapter.lookup.return_value = {'state':'CANCEL_PENDING','fills':[]}
    engine = ManagedEngine(database, lambda agent: adapter)
    engine.dispatch(1, market(), NOW)
    with database() as db:
        assert db.scalar(select(ManagedOrder)).state == 'CANCEL_PENDING'
        assert db.get(ManagedAgent, 1).cancel_requested
    adapter.lookup.return_value = {'state':'CANCELLED','fills':[]}
    engine.dispatch(1, market(), NOW)
    with database() as db:
        assert db.scalar(select(ManagedOrder)).state == 'CANCELLED'
        assert not db.get(ManagedAgent, 1).cancel_requested


def test_negative_validated_return_reduces_inventory(client, database):
    configure(client)
    engine = ManagedEngine(database)
    engine.cycle(1, market(), prediction(), NOW)
    later = NOW+timedelta(hours=1)
    engine.cycle(1, market(later), prediction(later, predicted_return=D('-.1')), later)
    with database() as db:
        assert db.get(ManagedWallet, (1, 'paper')).quantity == 0
        assert db.scalars(select(ManagedOrder).order_by(ManagedOrder.id)).all()[-1].reason_code == 'ADVERSE_RETURN_FORECAST'
