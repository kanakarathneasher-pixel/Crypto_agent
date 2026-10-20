"""One frozen chronological candidate test, using next-hour OPEN fills and costs."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import joblib
import numpy as np
import pandas as pd
from backend.risk_manager import RiskContext, approve, signal_for, down
from src.coinbase_pipeline import FEATURES, ROOT, clean_candles, engineer_features

D = Decimal


def backtest(directory):
    folder = Path(directory)
    meta = json.loads((folder / "metadata.json").read_text())
    bundle = joblib.load(folder / "model.joblib")
    if "n_jobs" in bundle["model"].get_params():
        bundle["model"].set_params(n_jobs=1)
    clean, _ = clean_candles(pd.read_csv(ROOT / "data/raw/coinbase_xrp_usdc_1h.csv"))
    df = engineer_features(clean)
    start = pd.Timestamp(meta["partitions"]["test"]["start"])
    end = pd.Timestamp(meta["partitions"]["test"]["end"])
    if pd.Timestamp(meta["partitions"]["train"]["target_end"]) >= start:
        raise ValueError("Model training overlaps the backtest period.")
    settings = SimpleNamespace(sizing_mode="automatic", manual_size_usdc=D(10), buy_threshold=D('.02'),
        sell_threshold=D('.02'), fee_rate=D('.006'), slippage_rate=D('.001'))
    risk = SimpleNamespace(max_trades_per_day=5, max_position_usdc=D(25), max_allocation=D('.10'), max_daily_loss_usdc=D(25))
    cash, quantity, cost_basis = D(1000), D(0), D(0)
    day, day_equity, trades_today = "", D(1000), 0
    fills, equity = [], []
    usable = df.loc[(df.open_time >= start) & (df.open_time <= end)].copy()
    valid_inputs = np.isfinite(usable[FEATURES].to_numpy(dtype=float)).all(axis=1)
    forecasts = np.full(len(usable), np.nan)
    # Batched prediction is safe: each row's features are already strictly causal.
    forecasts[valid_inputs] = bundle["model"].predict(usable.loc[valid_inputs, FEATURES])
    # Forecast at completed t; execute at t+1 open. No t+1 prices enter features.
    for i in range(len(usable) - 1):
        row, following = usable.iloc[i], usable.iloc[i+1]
        if following.open_time - row.open_time != pd.Timedelta(hours=1):
            continue
        price = D(str(following.open))
        if day != str(following.open_time.date()):
            day, trades_today, day_equity = str(following.open_time.date()), 0, cash + quantity * price
        if not np.isfinite(row[FEATURES].to_numpy(dtype=float)).all():
            continue
        prediction = D(str(float(forecasts[i])))
        side, _ = signal_for(prediction, settings)
        context = RiskContext(True, False, True, True, True, trades_today,
            max(D(0), day_equity - cash - quantity * price), cash, quantity, price)
        amount, reason = approve(side, context, settings, risk)
        if amount:
            fill_price = down(price * (1 + settings.slippage_rate if side == "BUY" else 1 - settings.slippage_rate))
            units = down(amount / price)
            gross = down(units * fill_price)
            fee = down(gross * settings.fee_rate)
            realized = D(0)
            if side == "BUY":
                cash -= gross + fee
                quantity += units
                cost_basis += gross + fee
            else:
                cost = down(cost_basis * units / quantity)
                cash += gross - fee
                quantity -= units
                cost_basis -= cost
                realized = gross - fee - cost
            if cash < 0 or quantity < 0:
                raise ValueError("Backtest inventory constraint violated.")
            trades_today += 1
            fills.append({"timestamp": str(following.open_time), "side": side, "quantity": str(units),
                          "price": str(fill_price), "fee": str(fee), "realized_pnl": str(realized)})
        equity.append({"timestamp": str(following.open_time), "equity": float(cash + quantity * D(str(following.close)))})
    if not equity:
        raise ValueError("No usable test observations.")
    values = np.array([1000.] + [row["equity"] for row in equity])
    changes = values[1:] / values[:-1] - 1
    exits = [row for row in fills if row["side"] == "SELL"]
    benchmark_quantity = 1000 / (float(usable.open.iloc[1]) * 1.001 * 1.006)
    benchmark_final = benchmark_quantity * float(usable.close.iloc[-1]) * .999 * .994
    report = {"model_version": meta["version"], "model_eligible": meta["eligible"],
              "purpose": "Frozen experimental candidate backtest; does not approve or promote a model.",
              "period_start": equity[0]["timestamp"], "period_end": equity[-1]["timestamp"],
              "total_return": float(values[-1] / 1000 - 1),
              "max_drawdown": float(np.min(values / np.maximum.accumulate(values) - 1)),
              "fills": len(fills), "completed_sell_fills": len(exits),
              "win_rate": sum(D(row["realized_pnl"]) > 0 for row in exits) / len(exits) if exits else None,
              "hourly_sharpe_annualized": float(changes.mean() / changes.std() * np.sqrt(365 * 24)) if len(changes) > 100 and changes.std() > 0 else None,
              "buy_and_hold_return_after_costs": benchmark_final / 1000 - 1,
              "assumptions": "0.6% fee per fill, 0.1% slippage, next candle OPEN fills; 5 daily fills, 25 USDC position cap. Sharpe assumes hourly sampling and is descriptive only.",
              "warning": "Historical outcomes do not guarantee future results. Test period is not for repeated strategy optimization."}
    (folder / "backtest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame(equity).to_csv(folder / "backtest_equity.csv", index=False)
    pd.DataFrame(fills).to_csv(folder / "backtest_fills.csv", index=False)
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    backtest(parser.parse_args().directory)
