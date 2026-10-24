"""Pinned XGBoost direction forecasts for observation only; never order inputs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from src.coinbase_pipeline import ROOT
from src.neural_data import SEQUENCE_FEATURES, sequence_features

POINTER = ROOT / 'models/research_selected.json'


def read_selection(pointer=None):
    """Only load a native classifier inside our local model directory."""
    reference = json.loads(Path(pointer or POINTER).read_text(encoding='utf-8'))
    folder = (ROOT / reference['directory']).resolve()
    if not folder.is_relative_to((ROOT / 'models').resolve()):
        raise ValueError('Selected classifier must stay inside models/.')
    metadata = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
    if (metadata.get('version') != reference['version'] or metadata.get('product') != 'XRP-USDC'
            or metadata.get('status') != 'complete_research_only'
            or metadata.get('features') != SEQUENCE_FEATURES):
        raise ValueError('Selected classifier metadata/schema mismatch.')
    if hashlib.sha256((folder/'metadata.json').read_bytes()).hexdigest() != reference['metadata_sha256']:
        raise ValueError('Selected classifier metadata checksum mismatch.')
    # Latest chronological fold, not the fold with highest observed evaluation accuracy.
    fold = max(metadata['folds'], key=lambda item: item['number'])
    artifact = folder / f"fold_{fold['number']}" / 'classifier.ubj'
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if digest != reference['artifact_sha256'] or digest != fold['artifact_sha256']:
        raise ValueError('Selected classifier artifact checksum mismatch.')
    return artifact, metadata, fold


def pin(directory):
    folder = Path(directory).resolve()
    if not folder.is_relative_to((ROOT / 'models').resolve()):
        raise ValueError('Only local research artifacts may be selected.')
    metadata = json.loads((folder/'metadata.json').read_text())
    fold = max(metadata['folds'], key=lambda item: item['number'])
    artifact = folder / f"fold_{fold['number']}" / 'classifier.ubj'
    reference = {'directory': folder.relative_to(ROOT).as_posix(), 'version': metadata['version'],
                 'purpose': 'observation_only', 'approved_for_orders': False,
                 'metadata_sha256': hashlib.sha256((folder/'metadata.json').read_bytes()).hexdigest(),
                 'artifact_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
                 'selected_at_utc': datetime.now(timezone.utc).isoformat()}
    temporary = POINTER.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(reference, indent=2), encoding='utf-8')
    read_selection(temporary)  # Verify everything before replacing the selection.
    temporary.replace(POINTER)
    return selection_status()


def selection_status():
    try:
        _, metadata, fold = read_selection()
        return {'available': True, 'version': metadata['version'], 'type': 'xgboost_direction',
                'mode': 'observation_only', 'approved_for_orders': False,
                'development_accuracy': metadata['pooled']['xgboost']['accuracy'],
                'latest_fold_accuracy': fold['evaluation']['xgboost']['accuracy'],
                'reason': 'Development results and cost-aware losses do not approve trading.'}
    except (OSError, ValueError, KeyError) as error:
        return {'available': False, 'mode': 'observation_only', 'approved_for_orders': False,
                'reason': str(error)}


def forecast(candles, now=None):
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise ValueError('Prediction time must include a timezone.')
    times = pd.to_datetime(candles.open_time, utc=True, errors='raise')
    completed = candles.loc[times + pd.Timedelta(hours=1) <= now]
    frame, _ = sequence_features(completed)
    if frame.empty:
        raise ValueError('No completed candles for classifier.')
    row = frame.iloc[-1]
    age = now - (row.open_time + pd.Timedelta(hours=1))
    if not pd.Timedelta(0) <= age <= pd.Timedelta(minutes=10):
        raise ValueError('Classifier input is stale.')
    inputs = frame.iloc[[-1]][SEQUENCE_FEATURES]
    if not np.isfinite(inputs.to_numpy(dtype=float)).all():
        raise ValueError('Insufficient continuous indicator history.')
    artifact, metadata, _ = read_selection()
    model = XGBClassifier(n_jobs=1)
    model.load_model(artifact)
    value = float(model.predict_proba(inputs)[0, 1])
    if not np.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Invalid classifier probability.')
    return {'version': metadata['version'], 'product': 'XRP-USDC', 'candle_time': row.open_time.isoformat(),
            'forecast_time': now.isoformat(), 'probability_up': value, 'probability_down': 1-value,
            'direction': 'UP' if value >= .6 else 'DOWN' if value <= .4 else 'UNCERTAIN',
            'mode': 'observation_only', 'approved_for_orders': False, 'action': 'HOLD',
            'reason': 'Uncalibrated direction probability is not an expected return or an approved trading signal.'}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--select', required=True)
    print(json.dumps(pin(parser.parse_args().select), indent=2))
