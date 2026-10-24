"""Replay the selected model through the production decision/risk/order engine.

Uses only the existing latest fold's development evaluation period. No fitting or
threshold selection occurs. The final holdout remains untouched. Next candle open
is visible only to the fill simulator, never to inference or the decision gate.
"""
import argparse
from datetime import timedelta
from decimal import Decimal as D
import json
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from backend.config import config
from backend.database import make_engine
from backend.models import User
from backend.managed_models import ManagedAgent, ManagedWallet, ManagedFill, ManagedOrder, AgentEvent
from backend.managed_contracts import StrategyConfig
from backend.managed_engine import ManagedEngine, PaperExchange
from src.classifier_prediction import read_selection
from src.coinbase_pipeline import clean_candles


class ReplayExchange(PaperExchange):
    def submit(self, order, market, settings):
        execution = dict(market, bid=market['execution_bid'], ask=market['execution_ask'])
        return super().submit(order, execution, settings)


def run(source, limit=None):
    _, metadata, fold = read_selection()
    frame, quality = clean_candles(pd.read_csv(source))
    bounds = fold['partitions']['evaluation']
    start, end = pd.Timestamp(bounds['first_candle']), pd.Timestamp(bounds['last_candle'])
    if pd.Timestamp(fold['partitions']['validation']['last_target']) >= start:
        raise ValueError('Evaluation overlaps fitting/validation targets.')
    indices = frame.index[(frame.open_time >= start) & (frame.open_time <= end)].tolist()
    if limit: indices = indices[:limit]
    if not indices: raise ValueError('No candles in the saved evaluation period.')
    settings = StrategyConfig()
    equity, exposure, executed_indices = [], [], []
    with tempfile.TemporaryDirectory(prefix='crypto-replay-') as directory:
        url = 'sqlite:///'+Path(directory, 'replay.db').as_posix()
        original_url = config.database_url
        try:
            config.database_url = url
            command.upgrade(AlembicConfig('alembic.ini'), 'head')
        finally:
            config.database_url = original_url
        database_engine = make_engine(url)
        factory = sessionmaker(database_engine, expire_on_commit=False)
        try:
            with factory.begin() as db:
                db.add(User(id=1, username='isolated-replay', password_hash='LOGIN-DISABLED'))
                db.flush()
                db.add(ManagedAgent(user_id=1, mode='backtest', phase='running', config_json=settings.model_dump_json()))
                db.add(ManagedWallet(user_id=1, mode='backtest'))
            agent = ManagedEngine(factory, lambda _: ReplayExchange())
            for count, index in enumerate(indices):
                if index+1 >= len(frame) or frame.open_time.iloc[index+1]-frame.open_time.iloc[index] != pd.Timedelta(hours=1):
                    continue  # Never synthesize a missing execution candle.
                row, following = frame.iloc[index], frame.iloc[index+1]
                now = (row.open_time+pd.Timedelta(hours=1)).to_pydatetime()
                price, opening = D(str(row.close)), D(str(following.open))
                quote = dict(product='XRP-USDC', price=price, bid=price*D('.9995'), ask=price*D('1.0005'),
                    updated_at=now.isoformat(), candles=frame.iloc[max(0,index-299):index+1].copy(),
                    base_increment='.000001', base_min_size='.000001', quote_min_size='1', tradable=True,
                    execution_bid=opening*D('.9995'), execution_ask=opening*D('1.0005'))
                agent.cycle(1, quote, now=now)
                with factory() as db:
                    wallet = db.get(ManagedWallet, (1, 'backtest'))
                    value = wallet.cash+wallet.quantity*D(str(following.close))
                    equity.append(float(value))
                    exposure.append(float(wallet.quantity*D(str(following.close))/value) if value else 0)
                executed_indices.append(index)
                if (count+1) % 100 == 0: print(f'Replayed {count+1}/{len(indices)} hours', flush=True)
            with factory() as db:
                fills = list(db.scalars(select(ManagedFill)))
                sell_ids = set(db.scalars(select(ManagedOrder.id).where(ManagedOrder.side == 'SELL')))
                exits = [f for f in fills if f.order_id in sell_ids]
                reasons = {}
                for event in db.scalars(select(AgentEvent).where(AgentEvent.kind == 'decision')):
                    for reason in json.loads(event.payload)['reason_codes']: reasons[reason] = reasons.get(reason, 0)+1
            if not equity: raise ValueError('No continuous replay intervals.')
            curve = np.array([1000]+equity)
            returns = curve[1:]/curve[:-1]-1
            first, last = executed_indices[0], executed_indices[-1]
            entry_price = D(str(frame.iloc[first+1].open))*D('1.0005')*(1+settings.slippage)
            exit_price = D(str(frame.iloc[last+1].close))*D('.9995')*(1-settings.slippage)
            benchmark = exit_price*(1-settings.fee_rate)/(entry_price*(1+settings.fee_rate))-1
            return dict(model_version=metadata['version'], period_start=str(frame.open_time.iloc[first]+pd.Timedelta(hours=1)),
                period_end=str(frame.open_time.iloc[last+1]+pd.Timedelta(hours=1)), observations=len(equity),
                evaluation='Previously examined development fold; not a new untouched final test.',
                net_return=equity[-1]/1000-1, maximum_drawdown=float(np.min(curve/np.maximum.accumulate(curve)-1)),
                filled_orders=len({f.order_id for f in fills}), closed_trades=len(exits),
                win_rate=sum(f.realized_pnl>0 for f in exits)/len(exits) if exits else None,
                average_net_trade_return=float(np.mean([float(f.realized_pnl/(f.quantity*f.price-f.fee-f.realized_pnl)) for f in exits])) if exits else None,
                mean_exposure=float(np.mean(exposure)), sharpe_hourly_annualized=float(np.mean(returns)/np.std(returns)*np.sqrt(365*24)) if np.std(returns)>0 else None,
                buy_hold_net_return=float(benchmark), cash_hold_net_return=0, reason_counts=reasons,
                assumptions={'fee_per_fill':str(settings.fee_rate),'slippage_per_fill':str(settings.slippage),'full_spread':'.001',
                'fills':'Full quantity at next contiguous open plus costs. Hourly exits; intrahour paths unavailable.',
                'approval':'Production approval gates retained. Current classifier should HOLD.'}, data_quality=quality)
        finally:
            database_engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='data/processed/coinbase_xrp_usdc_cleaned.csv')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--output', default='reports/managed_replay.json')
    args = parser.parse_args()
    report = run(args.data, args.limit)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str))
