"""Pure deterministic risk controls shared by paper execution and backtesting."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

D = Decimal
HARD_TRADES = 50
HARD_POSITION = D("10000")
HARD_ALLOCATION = D("0.25")
HARD_DAILY_LOSS = D("10000")
UNIT = D("0.00000001")


def down(value):
    return D(value).quantize(UNIT, rounding=ROUND_DOWN)


@dataclass
class RiskContext:
    enabled: bool
    emergency_stop: bool
    fresh: bool
    prediction_available: bool
    validated: bool
    trades_today: int
    daily_loss: Decimal
    cash: Decimal
    quantity: Decimal
    price: Decimal


def signal_for(prediction, settings):
    if prediction is None:
        return "HOLD", "Prediction unavailable."
    costs = 2 * (settings.fee_rate + settings.slippage_rate)
    if prediction > max(settings.buy_threshold, costs):
        return "BUY", "Forecast exceeds BUY threshold and estimated round-trip costs."
    if prediction < -max(settings.sell_threshold, costs):
        return "SELL", "Forecast exceeds SELL threshold and estimated round-trip costs."
    return "HOLD", "Forecast does not exceed signal threshold and round-trip costs."


def approve(side, context, settings, risk):
    """Return a capped notional or a precise rejection. Selling never shorts."""
    c = context
    if not c.enabled:
        return D(0), "Paper trading disabled."
    if c.emergency_stop:
        return D(0), "Emergency stop active."
    if not c.fresh:
        return D(0), "Market data is stale or from the future."
    if not c.prediction_available:
        return D(0), "Prediction unavailable."
    if not c.validated:
        return D(0), "Model not validated and explicitly promoted."
    if c.trades_today >= min(risk.max_trades_per_day, HARD_TRADES):
        return D(0), "Maximum trades per UTC day reached."
    if c.daily_loss >= min(risk.max_daily_loss_usdc, HARD_DAILY_LOSS):
        return D(0), "Maximum daily paper loss reached."
    if side not in ("BUY", "SELL"):
        return D(0), "HOLD: no eligible trading signal."
    if not c.price.is_finite() or c.price <= 0 or c.cash < 0 or c.quantity < 0:
        return D(0), "Invalid price or balance."
    if not (0 <= settings.fee_rate <= D('.05') and 0 <= settings.slippage_rate <= D('.05')):
        return D(0), "Invalid fee/slippage settings."
    if side == "BUY" and c.cash <= 0:
        return D(0), "Insufficient USDC balance."
    if side == "SELL" and c.quantity <= 0:
        return D(0), "No XRP inventory; short selling prohibited."
    equity = c.cash + c.quantity * c.price
    max_position = min(risk.max_position_usdc, HARD_POSITION,
                       equity * min(risk.max_allocation, HARD_ALLOCATION))
    desired = (settings.manual_size_usdc if settings.sizing_mode == "manual" else
               min(c.cash * D('.02'), max_position) if side == "BUY" else
               min(c.quantity * c.price, risk.max_position_usdc, HARD_POSITION))
    if desired <= 0:
        return D(0), "Position size must be positive."
    if side == "BUY":
        # Allow for fill slippage and fees in both cash and allocation constraints.
        room = max_position - c.quantity * c.price
        cap = min(room / (1 + settings.slippage_rate),
                  c.cash / ((1 + settings.slippage_rate) * (1 + settings.fee_rate)))
        # Fee loss slightly reduces equity; conservatively reserve its full amount.
        cap = min(cap, (equity * min(risk.max_allocation, HARD_ALLOCATION) - c.quantity * c.price)
                  / (1 + settings.slippage_rate + settings.fee_rate))
        if cap <= 0:
            return D(0), "Insufficient USDC or position/allocation limit reached."
    else:
        cap = min(c.quantity * c.price, risk.max_position_usdc, HARD_POSITION)
        if cap <= 0:
            return D(0), "No XRP inventory; short selling prohibited."
        if settings.sizing_mode == "automatic":
            desired = cap
    # Known execution costs must not themselves cross the daily loss boundary.
    cost_rate = ((1 + settings.slippage_rate) * (1 + settings.fee_rate) - 1
                 if side == "BUY" else 1 - (1 - settings.slippage_rate) * (1 - settings.fee_rate))
    if cost_rate > 0:
        cap = min(cap, (min(risk.max_daily_loss_usdc, HARD_DAILY_LOSS) - c.daily_loss) / cost_rate)
    if settings.sizing_mode == "manual" and desired > cap:
        return D(0), "Manual size exceeds balance, inventory, position or allocation limit."
    amount = down(min(desired, cap))
    if amount < D("1"):
        return D(0), "Order below illustrative 1 USDC minimum."
    return amount, "Approved by deterministic paper risk manager."
