"""Run inside .venv-tf. TensorFlow stays optional in the backend environment."""
import hashlib
import json
import joblib
import numpy as np
import pandas as pd
import pytest

tf = pytest.importorskip('tensorflow')
from src import tensorflow_research as research
from src.neural_data import (SEQUENCE_FEATURES, SEQUENCE_SCHEMA, TARGET_SCALE, CLIP_Z,
    sequence_features, sequence_ends, fit_scaler, scaled_sequences)
from tests.test_neural_data import synthetic_candles


@pytest.mark.parametrize('architecture',['gru','lstm'])
def test_model_forward_save_reload_and_train_batch(tmp_path,architecture):
    model = research.make_model(architecture,8,len(SEQUENCE_FEATURES))
    x = np.ones((4,8,len(SEQUENCE_FEATURES)),dtype=np.float32)
    y = np.array([.1,-.1,.2,-.2],dtype=np.float32)
    loss = model.train_on_batch(x,y)
    assert np.isfinite(loss)
    expected = research.neural_predictions(model,x)
    path = tmp_path/'model.keras'
    model.save(path)
    loaded = tf.keras.models.load_model(path,compile=False,safe_mode=True)
    np.testing.assert_allclose(expected,research.neural_predictions(loaded,x),rtol=1e-6)


def test_artifact_inference_and_tamper_rejection(tmp_path,monkeypatch):
    monkeypatch.setattr(research,'ROOT',tmp_path)
    folder = tmp_path/'models'/'tensorflow-test'
    folder.mkdir(parents=True)
    raw = synthetic_candles(400)
    frame, _ = sequence_features(raw)
    ends = sequence_ends(frame,24)
    scaler,_ = fit_scaler(frame,ends[:100],24)
    model = research.make_model('gru',24,len(SEQUENCE_FEATURES))
    model.save(folder/'model.keras')
    joblib.dump(scaler,folder/'scaler.joblib')
    metadata = {'format':'keras-sequence-v1','schema_version':SEQUENCE_SCHEMA,'features':SEQUENCE_FEATURES,
        'status':'complete_research_only','product':'XRP-USDC','lookback':24,'target_scale':TARGET_SCALE,
        'clip_z':CLIP_Z,'version':'test','selected_neural':'gru',
        'checksums':{name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ('model.keras','scaler.joblib')}}
    (folder/'metadata.json').write_text(json.dumps(metadata))
    as_of = raw.open_time.iloc[-1] + pd.Timedelta(hours=1)
    result = research.predict_research(folder,raw,as_of)
    assert result['validated'] is False and result['mode'] == 'research_only'
    assert result['predicted_return'] == 0
    with pytest.raises(ValueError,match='stale'):
        research.predict_research(folder,raw,as_of + pd.Timedelta(hours=2))
    with pytest.raises(ValueError,match='contiguous'):
        research.predict_research(folder,raw.drop(index=390),as_of)
    (folder/'scaler.joblib').write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='checksum'):
        research.load_research_model(folder)


def test_development_loader_excludes_original_validation_and_test(tmp_path,monkeypatch):
    monkeypatch.setattr(research,'ROOT',tmp_path)
    raw = synthetic_candles(400)
    (tmp_path/'data'/'raw').mkdir(parents=True)
    raw.to_csv(tmp_path/'data/raw/coinbase_xrp_usdc_1h.csv',index=False)
    reference = tmp_path/'reference.json'
    reference.write_text(json.dumps({'product':'XRP-USDC','partitions':{
        'train':{'target_end':raw.open_time.iloc[250].isoformat()},
        'validation':{'start':raw.open_time.iloc[251].isoformat()},
        'test':{'start':raw.open_time.iloc[350].isoformat()}}}))
    frame,_,provenance = research.load_development_data(reference)
    assert frame.open_time.max() == raw.open_time.iloc[250]
    assert frame.target_time.max() <= raw.open_time.iloc[250]
    assert pd.Timestamp(provenance['excluded_original_test_start']) > frame.open_time.max()
