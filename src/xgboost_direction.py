"""Focused next-hour XGBoost classifier experiment on the cleaned Coinbase CSV.

CPU-only research: python -m src.xgboost_direction
Early stopping uses validation only. Prior validation/test dates stay excluded.
"""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from src.coinbase_pipeline import ROOT, clean_candles
from src.direction_research import REFERENCE, NEUTRAL, horizon_frame, score, partition, spot_simulation
from src.neural_data import SEQUENCE_FEATURES, make_fold


def train():
    source = ROOT / 'data/processed/coinbase_xrp_usdc_cleaned.csv'
    reference = json.loads(REFERENCE.read_text())
    cutoff = pd.Timestamp(reference['partitions']['train']['target_end'])
    cleaned, quality = clean_candles(pd.read_csv(source))
    if quality['invalid_rows'] or quality['duplicates']:
        raise ValueError('Cleaned CSV failed validation; review it before training.')
    development = cleaned.loc[cleaned.open_time <= cutoff].copy()
    frame = horizon_frame(development, 1)
    if len(frame) < 3000:
        raise ValueError('Insufficient development observations.')
    version = datetime.now(timezone.utc).strftime('xgboost-direction-%Y%m%dT%H%M%S%fZ')
    folder = ROOT / 'models' / version
    folder.mkdir(parents=True)
    report = {'version': version, 'status': 'training', 'eligible': False, 'approved': False,
              'product': 'XRP-USDC', 'source': str(source), 'source_rows': len(cleaned),
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'development_cutoff': str(cutoff), 'features': SEQUENCE_FEATURES,
              'reference_metadata_sha256': hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
              'quality': quality, 'folds': [],
              'packages': {name: importlib.metadata.version(name) for name in
                           ['xgboost', 'scikit-learn', 'numpy', 'pandas']},
              'label': 'Next-hour UP versus DOWN. Absolute returns <=0.0001 excluded from fitting and accuracy; included in coverage/simulation.',
              'limitations': 'Previously used historical development dates; not a fresh final test. Uncalibrated probabilities. No model promotion.'}
    metadata = folder / 'metadata.json'
    metadata.write_text(json.dumps(report, indent=2))
    pooled = []
    for number, fractions in enumerate(((.50, .65, .80), (.70, .85, 1.)), 1):
        fold = make_fold(frame, np.arange(len(frame)), *fractions)
        fit, validation, evaluation = (frame.iloc[i] for i in [fold.train, fold.validation, fold.evaluation])
        fit = fit.loc[fit.target_next_return.abs() > NEUTRAL]
        valid_labeled = validation.loc[validation.target_next_return.abs() > NEUTRAL]
        model = XGBClassifier(n_estimators=300, max_depth=3, learning_rate=.03,
                              reg_lambda=10, subsample=.8, colsample_bytree=.8,
                              n_jobs=2, random_state=42, tree_method='hist', device='cpu',
                              objective='binary:logistic', eval_metric='logloss', early_stopping_rounds=20)
        print(f'Fold {number}: training {len(fit)} rows, validation {len(valid_labeled)} labeled rows, later evaluation {len(evaluation)} hours.', flush=True)
        model.fit(fit[SEQUENCE_FEATURES], (fit.target_next_return > 0).astype(int),
                  eval_set=[(fit[SEQUENCE_FEATURES], (fit.target_next_return > 0).astype(int)),
                            (valid_labeled[SEQUENCE_FEATURES], (valid_labeled.target_next_return > 0).astype(int))],
                  verbose=25)
        # XGBoost predict_proba automatically uses the validation best iteration.
        p = model.predict_proba(evaluation[SEQUENCE_FEATURES])[:, 1]
        majority = int((fit.target_next_return > 0).mean() >= .5)
        comparison = {'xgboost': score(evaluation.target_next_return, p),
                      'majority': score(evaluation.target_next_return, np.full(len(p), majority, float))}
        sub = folder / f'fold_{number}'
        sub.mkdir()
        joblib.dump(model, sub / 'classifier.joblib')
        model.save_model(sub / 'classifier.ubj')
        reloaded = XGBClassifier()
        reloaded.load_model(sub / 'classifier.ubj')
        np.testing.assert_allclose(p, reloaded.predict_proba(evaluation[SEQUENCE_FEATURES])[:, 1], rtol=1e-7)
        history = model.evals_result()
        pd.DataFrame({'boosting_round': np.arange(len(history['validation_0']['logloss']))+1,
                      'training_log_loss': history['validation_0']['logloss'],
                      'validation_log_loss': history['validation_1']['logloss']}).to_csv(sub/'learning_history.csv', index=False)
        sim = spot_simulation(evaluation, p)
        pd.DataFrame(sim.pop('fills')).to_csv(sub / 'simulated_round_trips.csv', index=False)
        detail = {'number': number, 'best_boosting_round': model.best_iteration+1,
                  'rounds_completed': len(history['validation_0']['logloss']),
                  'partitions': {name: partition(frame, indices) for name, indices in
                                 [('train', fold.train), ('validation', fold.validation), ('evaluation', fold.evaluation)]},
                  'training_directional_rows': len(fit), 'evaluation': comparison,
                  'validation': score(validation.target_next_return, model.predict_proba(validation[SEQUENCE_FEATURES])[:, 1]),
                  'fee_aware_simulation': sim,
                  'artifact_sha256': hashlib.sha256((sub/'classifier.ubj').read_bytes()).hexdigest()}
        report['folds'].append(detail)
        probabilities = evaluation[['open_time', 'target_time', 'target_next_return']].copy()
        probabilities['probability_up'] = p
        probabilities['majority_prediction'] = majority
        probabilities.to_csv(sub / 'evaluation_predictions.csv', index=False)
        pooled.append(probabilities)
        metadata.write_text(json.dumps(report, indent=2))
        print(f"Fold {number} complete: accuracy {comparison['xgboost']['accuracy']:.2%}, balanced accuracy {comparison['xgboost']['balanced_accuracy']:.2%}, majority {comparison['majority']['accuracy']:.2%}; best round {model.best_iteration+1}.", flush=True)
    combined = pd.concat(pooled, ignore_index=True)
    assert not combined.open_time.duplicated().any()
    report['pooled'] = {'xgboost': score(combined.target_next_return, combined.probability_up),
                        'majority': score(combined.target_next_return, combined.majority_prediction)}
    report['status'] = 'complete_research_only'
    metadata.write_text(json.dumps(report, indent=2))
    combined.to_csv(folder / 'evaluation_predictions.csv', index=False)
    lines = ['# Focused XGBoost direction classifier', '', f'Run: `{version}`.', '',
             'Source: cleaned Coinbase XRP/USDC hourly CSV. Only candles up to',
             f'`{cutoff}` enter this development experiment. Prior validation and final-test dates are excluded.',
             'These historical periods have been examined before; results are not an independent final test.', '',
             '| Metric | XGBoost | Training-majority baseline |', '| --- | ---: | ---: |']
    for key in ['accuracy', 'balanced_accuracy']:
        lines.append(f"| {key} | {report['pooled']['xgboost'][key]:.2%} | {report['pooled']['majority'][key]:.2%} |")
    lines += ['', f"Scored directional observations: {report['pooled']['xgboost']['directional_samples']:,}.",
              'Moves of 0.01% or less are excluded from direction scoring; no confidence filtering.', '',
              'Maximum 300 boosting rounds; depth 3; learning rate 0.03; L2=10;',
              '80% row/column sampling; early stopping patience 20 on validation log loss.',
              'CPU training with two threads; no GPU dependency.', '',
              '| Fold | Best round | Completed rounds | Accuracy | Paper return after costs |',
              '| --- | ---: | ---: | ---: | ---: |']
    for f in report['folds']:
        lines.append(f"| {f['number']} | {f['best_boosting_round']} | {f['rounds_completed']} | {f['evaluation']['xgboost']['accuracy']:.2%} | {f['fee_aware_simulation']['return']:.2%} |")
    lines += ['', 'Paper diagnostic: enter next hourly open when P(UP)>=0.60; exit next hour close;',
              '10% cash per trade, non-overlapping positions, 0.6% fee and 0.1% slippage per fill.',
              'Costs are illustrative. Probabilities are uncalibrated. No promotion or live trades.', '',
              f'Artifacts, histories and exact partitions: `models/{version}/`.',
              'Both native UBJ artifacts were reloaded and reproduced their evaluation probabilities.', '',
              'Run with `.\\.venv\\Scripts\\python.exe -m src.xgboost_direction`.']
    (folder / 'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    (ROOT / 'docs/xgboost_direction_results.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('Completed:', folder, flush=True)
    print(json.dumps(report['pooled'], indent=2), flush=True)
    return folder


if __name__ == '__main__':
    train()
