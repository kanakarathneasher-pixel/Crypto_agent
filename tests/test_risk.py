from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace
import pytest
from backend.risk_manager import RiskContext, approve, signal_for


@pytest.fixture
def context():
    return RiskContext(True, False, True, True, True, 0, D(0), D(1000), D(0), D(2))


@pytest.fixture
def settings():
    return SimpleNamespace(sizing_mode="automatic", manual_size_usdc=D(10), fee_rate=D('.006'), slippage_rate=D('.001'),
                           buy_threshold=D('.02'), sell_threshold=D('.02'))


@pytest.fixture
def risk():
    return SimpleNamespace(max_trades_per_day=5, max_position_usdc=D(25), max_allocation=D('.1'), max_daily_loss_usdc=D(25))


@pytest.mark.parametrize("field,value,reason", [("enabled",False,"disabled"),("emergency_stop",True,"Emergency"),
    ("fresh",False,"stale"),("prediction_available",False,"unavailable"),("validated",False,"validated"),
    ("trades_today",5,"Maximum trades"),("daily_loss",D(25),"daily paper loss"),
    ("cash",D(0),"Insufficient"),("price",D(0),"Invalid"),("quantity",D(-1),"Invalid")])
def test_every_risk_rejection(context, settings, risk, field, value, reason):
    amount, explanation = approve("BUY", replace(context, **{field:value}), settings, risk)
    assert amount == 0 and reason.lower() in explanation.lower()


def test_automatic_caps_and_no_leverage(context, settings, risk):
    amount, _ = approve("BUY", context, settings, risk)
    assert 0 < amount <= D(25)
    assert amount * D('1.001') * D('1.006') <= context.cash
    risk.max_position_usdc = D(1)
    amount, _ = approve("BUY", context, settings, risk)
    assert amount == 0


def test_manual_limits_and_inventory(context, settings, risk):
    settings.sizing_mode = "manual"
    settings.manual_size_usdc = D(100)
    assert approve("BUY", context, settings, risk)[0] == 0
    settings.manual_size_usdc = D(10)
    assert approve("BUY", context, settings, risk)[0] == 10
    assert approve("SELL", context, settings, risk)[0] == 0
    assert approve("SELL", replace(context,quantity=D(3)), settings, risk)[0] == 0


def test_allocation_and_existing_position(context, settings, risk):
    assert approve("BUY", replace(context,quantity=D(13)),settings,risk)[0] == 0
    risk.max_position_usdc = D(10000)
    risk.max_allocation = D('.01')
    assert approve("BUY", replace(context,quantity=D(6)),settings,risk)[0] == 0


def test_hard_administrator_cap(context, settings, risk):
    risk.max_trades_per_day = 100000
    assert approve("BUY", replace(context,trades_today=50),settings,risk)[0] == 0
    risk.max_position_usdc = D(100000)
    risk.max_allocation = D(1)
    large = replace(context,cash=D(1000000))
    assert approve("BUY",large,settings,risk)[0] <= 10000


def test_fee_aware_signals(settings):
    assert signal_for(D('.001'),settings)[0] == "HOLD"
    assert signal_for(D('.03'),settings)[0] == "BUY"
    assert signal_for(D('-.03'),settings)[0] == "SELL"
    settings.fee_rate = D('.02')
    assert signal_for(D('.03'),settings)[0] == "HOLD"


def test_execution_costs_cannot_cross_daily_loss_budget(context,settings,risk):
    tight = replace(context,daily_loss=D('24.99'))
    amount, _ = approve("BUY",tight,settings,risk)
    estimated_cost = amount * ((1 + settings.slippage_rate) * (1 + settings.fee_rate) - 1)
    assert estimated_cost <= D('.01')


def test_automatic_sell_does_not_need_cash(context,settings,risk):
    amount, reason = approve("SELL",replace(context,cash=D(0),quantity=D(10)),settings,risk)
    assert amount == 20
