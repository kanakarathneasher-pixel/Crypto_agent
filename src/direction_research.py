"""CPU direction research. No trading integration or automatic promotion.

Run: .venv/Scripts/python -m src.direction_research
Uses original training dates only; previously examined validation/test stay out.
"""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from src.coinbase_pipeline import ROOT, hourly_segments
from src.neural_data import SEQUENCE_FEATURES, sequence_features, make_fold

REFERENCE = ROOT / 'models/coinbase-20261020T121949544468Z/metadata.json'
NEUTRAL = .0001  # Direction metrics exclude absolute moves <= 0.01%.
FEE, SLIPPAGE = .006, .001  # Illustrative per-fill costs, not an account fee quote.


def horizon_frame(raw, hours):
    """Build labels within each continuous segment; no horizon crosses a gap."""
    if hours not in (1, 4, 24):
        raise ValueError('Supported horizons are 1, 4, and 24 hours.')
    frame, _ = sequence_features(raw)
    parts = []
    for _, part in frame.groupby(hourly_segments(frame)):
        part = part.copy()
        part['target_time'] = part.open_time.shift(-hours)
        part['target_next_return'] = part.close.shift(-hours) / part.close - 1
        # Trade simulation acts after candle t completes, at next candle OPEN.
        part['entry_time'] = part.open_time.shift(-1)
        part['entry_open'] = part.open.shift(-1)
        part['exit_time'] = part.open_time.shift(-hours) + pd.Timedelta(hours=1)
        part['exit_close'] = part.close.shift(-hours)
        parts.append(part)
    data = pd.concat(parts, ignore_index=True)
    data = data.dropna(subset=SEQUENCE_FEATURES + ['target_time', 'target_next_return',
                                                'entry_open', 'exit_close'])
    return data.reset_index(drop=True)


def score(returns, probability, threshold=.5):
    """Coverage uses all hours; accuracy excludes known near-zero outcomes."""
    actual, probability = np.asarray(returns, float), np.asarray(probability, float)
    if actual.shape != probability.shape or not len(actual) or not np.isfinite(probability).all():
        raise ValueError('Invalid probability arrays.')
    if ((probability < 0) | (probability > 1)).any():
        raise ValueError('Probabilities must be between zero and one.')
    active = np.ones(len(actual), bool) if threshold == .5 else (
        (probability >= threshold) | (probability <= 1-threshold))
    directional = np.abs(actual) > NEUTRAL
    mask = directional & active
    y, prediction = (actual > 0).astype(int), (probability >= .5).astype(int)
    return {
        'all_samples': len(actual), 'directional_samples': int(directional.sum()),
        'neutral_samples': int((~directional).sum()),
        'up_fraction': float(y[directional].mean()) if directional.any() else None,
        'coverage_all_hours': float(active.mean()), 'scored_predictions': int(mask.sum()),
        'accuracy': float(accuracy_score(y[mask], prediction[mask])) if mask.any() else None,
        'balanced_accuracy': float(balanced_accuracy_score(y[mask], prediction[mask]))
            if len(np.unique(y[mask])) == 2 else None,
        'confusion_matrix_down_up': confusion_matrix(y[mask], prediction[mask], labels=[0, 1]).tolist()
            if mask.any() else [[0, 0], [0, 0]],
        'log_loss': float(log_loss(y[mask], np.clip(probability[mask], 1e-6, 1-1e-6), labels=[0, 1]))
            if mask.any() else None,
    }


def spot_simulation(frame, probability, threshold=.6):
    """Descriptive long-only, non-overlapping fixed-horizon round trips.

    Invest 10% of current paper cash per trade, no leverage; next-open entry
    and horizon-close exit. Evaluates all hours, including neutral outcomes.
    This diagnostic is separate from the application's autonomous risk engine.
    """
    cash, busy_until = 1000., None
    realized_equity, fills = [cash], []
    for row, p in zip(frame.itertuples(), probability):
        if p < threshold or (busy_until is not None and row.entry_time < busy_until):
            continue
        allocated = cash * .10
        quantity = allocated / (row.entry_open * (1+SLIPPAGE) * (1+FEE))
        received = quantity * row.exit_close * (1-SLIPPAGE) * (1-FEE)
        pnl = received - allocated
        cash += pnl
        busy_until = row.exit_time
        fills.append({'entry_utc': str(row.entry_time), 'exit_utc': str(row.exit_time),
                      'allocated_usdc': allocated, 'pnl_usdc': pnl, 'equity_after_exit': cash})
        realized_equity.append(cash)
    values = np.asarray(realized_equity)
    benchmark = (frame.exit_close.iloc[-1] * (1-SLIPPAGE) * (1-FEE)
                 / (frame.entry_open.iloc[0] * (1+SLIPPAGE) * (1+FEE)) - 1)
    return {'initial_usdc': 1000., 'final_usdc': cash, 'return': cash/1000-1,
            'round_trips': len(fills),
            'win_rate': float(np.mean([f['pnl_usdc'] > 0 for f in fills])) if fills else None,
            'realized_exit_drawdown': float(np.min(values / np.maximum.accumulate(values)-1)),
            'buy_hold_return_after_costs': float(benchmark), 'fills': fills,
            'period_start': str(frame.entry_time.iloc[0]), 'period_end': str(frame.exit_time.iloc[-1]),
            'assumptions': '10% cash per trade; 0.6% fee and 0.1% slippage per fill; fixed horizon exits; no overlapping positions. Drawdown uses exits only and omits intratrade risk.'}


def partition(frame, indices):
    return {'first_candle': str(frame.open_time.iloc[indices[0]]),
            'last_candle': str(frame.open_time.iloc[indices[-1]]),
            'last_target': str(frame.target_time.iloc[indices[-1]]), 'rows': len(indices)}


def train(reference=REFERENCE):
    prior = json.loads(Path(reference).read_text())
    cutoff = pd.Timestamp(prior['partitions']['train']['target_end'])
    source = ROOT / 'data/raw/coinbase_xrp_usdc_1h.csv'
    raw = pd.read_csv(source)
    raw = raw.loc[pd.to_datetime(raw.open_time, utc=True) <= cutoff]
    version = datetime.now(timezone.utc).strftime('direction-%Y%m%dT%H%M%S%fZ')
    folder = ROOT / 'models' / version
    folder.mkdir(parents=True)
    report = {'version': version, 'approved': False, 'eligible': False,
              'product': 'XRP-USDC', 'status': 'training', 'features': SEQUENCE_FEATURES,
              'raw_cutoff': str(cutoff), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'packages': {n: importlib.metadata.version(n) for n in ['numpy', 'pandas', 'scikit-learn', 'xgboost']},
              'label': 'UP if return > 0, DOWN otherwise; fit and score exclude abs(return)<=0.0001. Coverage and simulation include all hours.',
              'selection': 'Highest validation balanced accuracy, then lowest validation log loss; evaluated once after selection.',
              'limitations': 'Historical development data already used in research. No untouched final test. Probabilities are uncalibrated. No claimed trading edge.',
              'horizons': {}}
    metadata = folder / 'metadata.json'
    metadata.write_text(json.dumps(report, indent=2))
    for horizon in (1, 4, 24):
        frame = horizon_frame(raw, horizon)
        ends = np.arange(len(frame))
        pooled, folds = [], []
        for number, fractions in enumerate(((.50, .65, .80), (.70, .85, 1.)), 1):
            fold = make_fold(frame, ends, *fractions)
            fit, validation, evaluation = (frame.iloc[i].copy() for i in
                                          [fold.train, fold.validation, fold.evaluation])
            # Exclude no-change labels only for classification; never remove eval hours.
            candidates = []
            for months in (6, 12, 24, None):
                recent = fit if months is None else fit.loc[
                    fit.open_time >= validation.open_time.min() - pd.DateOffset(months=months)]
                recent = recent.loc[recent.target_next_return.abs() > NEUTRAL]
                y = (recent.target_next_return > 0).astype(int)
                if len(recent) < 500 or y.nunique() != 2:
                    continue
                specs = [('logistic', make_pipeline(StandardScaler(), LogisticRegression(C=.1, max_iter=1000)))]
                specs += [(f'xgboost_depth{depth}', XGBClassifier(n_estimators=150,
                    max_depth=depth, learning_rate=.03, reg_lambda=10, subsample=.8,
                    colsample_bytree=.8, n_jobs=2, random_state=42, eval_metric='logloss'))
                    for depth in (2, 3)]
                for name, model in specs:
                    model.fit(recent[SEQUENCE_FEATURES], y)
                    p = model.predict_proba(validation[SEQUENCE_FEATURES])[:, 1]
                    result = score(validation.target_next_return, p)
                    candidates.append({'name': name, 'months': months, 'model': model,
                                       'validation': result, 'fit_rows': len(recent),
                                       'majority': int(y.mean() >= .5),
                                       'first_fit': str(recent.open_time.min())})
                print(f'{horizon}h fold {number}: fitted {months or "all"}-month window; {len(recent)} labeled rows', flush=True)
            chosen = max(candidates, key=lambda c: (c['validation']['balanced_accuracy'], -c['validation']['log_loss']))
            p = chosen['model'].predict_proba(evaluation[SEQUENCE_FEATURES])[:, 1]
            probability = {'selected': p, 'train_majority': np.full(len(p), chosen['majority'], float),
                           'always_up': np.ones(len(p)), 'always_down': np.zeros(len(p)),
                           'previous_direction': (evaluation.return_1h.to_numpy() >= 0).astype(float)}
            scores = {name: score(evaluation.target_next_return, values) for name, values in probability.items()}
            # Abstention thresholds are predetermined diagnostics, not selected on evaluation.
            selective = {str(t): score(evaluation.target_next_return, p, t) for t in (.55, .60, .65, .70)}
            sim = spot_simulation(evaluation, p)
            sub = folder / f'horizon_{horizon}h_fold_{number}'
            sub.mkdir()
            joblib.dump(chosen['model'], sub / 'classifier.joblib')
            pd.DataFrame(sim.pop('fills')).to_csv(sub / 'simulated_round_trips.csv', index=False)
            prediction = evaluation[['open_time', 'target_time', 'target_next_return', 'entry_time', 'entry_open', 'exit_time', 'exit_close']].copy()
            for name, values in probability.items():
                prediction[name] = values
            prediction.to_csv(sub / 'evaluation_predictions.csv', index=False)
            pooled.append(prediction)
            details = {'number': number, 'partitions': {name: partition(frame, indices) for name, indices in
                       [('train', fold.train), ('validation', fold.validation), ('evaluation', fold.evaluation)]},
                       'selected': {k: v for k, v in chosen.items() if k != 'model'},
                       'candidates': [{k: v for k, v in c.items() if k != 'model'} for c in candidates],
                       'evaluation': scores, 'selective': selective, 'fee_aware_simulation': sim}
            folds.append(details)
            (sub / 'metrics.json').write_text(json.dumps(details, indent=2))
            print(f'{horizon}h fold {number}: selected {chosen["name"]}, window {chosen["months"] or "all"}; evaluation accuracy {scores["selected"]["accuracy"]:.2%}, balanced {scores["selected"]["balanced_accuracy"]:.2%}', flush=True)
        all_predictions = pd.concat(pooled, ignore_index=True)
        assert not all_predictions.open_time.duplicated().any()
        pooled_metrics = {name: score(all_predictions.target_next_return, all_predictions[name]) for name in probability}
        report['horizons'][str(horizon)] = {'folds': folds, 'pooled': pooled_metrics,
            'selective': {str(t): score(all_predictions.target_next_return, all_predictions.selected, t)
                          for t in (.55, .60, .65, .70)}}
        all_predictions.to_csv(folder / f'predictions_{horizon}h.csv', index=False)
        metadata.write_text(json.dumps(report, indent=2))
    report['status'] = 'complete_research_only'
    metadata.write_text(json.dumps(report, indent=2))
    print('Saved completed direction experiment:', folder, flush=True)
    for horizon, result in report['horizons'].items():
        print(horizon + 'h:', json.dumps(result['pooled']), flush=True)
    return folder


if __name__ == '__main__':
    train()
