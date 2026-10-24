from datetime import datetime, timezone
import hashlib
import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select, func
from xgboost import XGBClassifier

from src import classifier_prediction as classifier
from src.neural_data import SEQUENCE_FEATURES, sequence_features
from backend.models import AgentSettings, Decision, PaperFill, ExecutionLog, MarketSnapshot
from backend.worker import Worker
from tests.test_backend import client, database, market_at
from tests.test_pipeline import candles


@pytest.fixture
def selected_classifier(tmp_path, monkeypatch):
    monkeypatch.setattr(classifier, 'ROOT', tmp_path)
    monkeypatch.setattr(classifier, 'POINTER', tmp_path/'models/research_selected.json')
    folder = tmp_path/'models/research-test'
    folder.mkdir(parents=True)
    data, _ = sequence_features(candles(200))
    data = data.dropna(subset=SEQUENCE_FEATURES)
    y = (np.arange(len(data)) % 2).astype(int)
    model = XGBClassifier(n_estimators=3, max_depth=2, n_jobs=1)
    model.fit(data[SEQUENCE_FEATURES], y)
    folds = []
    for number in (1, 2):
        sub = folder/f'fold_{number}'
        sub.mkdir()
        model.save_model(sub/'classifier.ubj')
        folds.append({'number': number, 'artifact_sha256': hashlib.sha256((sub/'classifier.ubj').read_bytes()).hexdigest(),
                      'evaluation': {'xgboost': {'accuracy': .8 if number == 1 else .52}}})
    meta = {'version': 'research-test', 'product': 'XRP-USDC', 'status': 'complete_research_only',
            'features': SEQUENCE_FEATURES, 'folds': folds, 'pooled': {'xgboost': {'accuracy': .53}}}
    (folder/'metadata.json').write_text(json.dumps(meta))
    classifier.pin(folder)
    return folder


def test_classifier_pinned_latest_fold_forecast_and_tampering(selected_classifier):
    artifact, _, fold = classifier.read_selection()
    assert fold['number'] == 2  # Do not cherry-pick the 80% historical fold.
    raw = candles(200)
    now = raw.open_time.iloc[-1] + pd.Timedelta(hours=1, minutes=1)
    result = classifier.forecast(raw, now)
    assert result['action'] == 'HOLD' and not result['approved_for_orders']
    assert 0 <= result['probability_up'] <= 1
    assert 'predicted_return' not in result
    with pytest.raises(ValueError, match='stale'):
        classifier.forecast(raw, now + pd.Timedelta(hours=1))
    with pytest.raises(ValueError, match='continuous'):
        classifier.forecast(raw.drop(index=180), now)
    assert not (classifier.ROOT/'models/approved.json').exists()
    artifact.write_bytes(b'tampered')
    assert not classifier.selection_status()['available']
    with pytest.raises(ValueError, match='checksum'):
        classifier.forecast(raw, now)


def test_shadow_worker_cannot_fill_and_is_idempotent(client, database, monkeypatch):
    client.post('/agent/start')
    now = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    market = market_at(now)
    advisory = {'version': 'research-test', 'direction': 'UP', 'probability_up': 1.,
                'approved_for_orders': False, 'action': 'HOLD'}
    monkeypatch.setattr('backend.worker.SessionLocal', database)
    monkeypatch.setattr('backend.worker.latest_market', lambda: market)
    monkeypatch.setattr('backend.worker.forecast', lambda data: advisory)
    with patch('backend.worker.predict', side_effect=ValueError('No promoted model')):
        worker = Worker()
        worker.run_once()
        worker.run_once()
    with database() as db:
        assert db.scalar(select(func.count(PaperFill.id))) == 0
        decisions = list(db.scalars(select(Decision)))
        assert len(decisions) == 1 and decisions[0].action == 'HOLD'
        assert 'P(UP)=1.0000' in decisions[0].reason
        logs = list(db.scalars(select(ExecutionLog).where(ExecutionLog.message.like('Research forecast:%'))))
        assert len(logs) == 1 and logs[0].user_id == 1


def test_research_endpoint_authentication_and_separate_probability(client, database):
    assert client.get('/agent/research/latest').status_code == 200
    assert client.get('/agent/research/latest').json()['forecast'] is None
    market = market_at(datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0))
    frame = market['candles'].copy()
    frame.open_time = frame.open_time.astype(str)
    with database.begin() as db:
        db.add(MarketSnapshot(product='XRP-USDC', price=market['price'],
                              updated_at=market['updated_at'], candles_json=frame.to_json(orient='records')))
    with patch('backend.views.forecast', return_value={'probability_up': .61, 'action': 'HOLD', 'approved_for_orders': False}):
        response = client.get('/agent/research/latest').json()
    assert response['forecast']['probability_up'] == .61
    assert 'predicted_return' not in response['forecast']
    client.post('/auth/logout')
    assert client.get('/agent/research/latest').status_code == 401
