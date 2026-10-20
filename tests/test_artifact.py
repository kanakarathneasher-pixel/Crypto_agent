import hashlib
import json
import joblib
import pytest
from sklearn.dummy import DummyRegressor
import numpy as np
from src import prediction
from src.coinbase_pipeline import FEATURES, SCHEMA_VERSION


def test_artifact_schema_validation_and_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction, 'ROOT', tmp_path)
    folder = tmp_path/'models'/'candidate'
    folder.mkdir(parents=True)
    artifact = folder/'model.joblib'
    model = DummyRegressor().fit(np.zeros((10,len(FEATURES))),np.zeros(10))
    bundle = {'model':model,'version':'test','features':FEATURES,'schema_version':SCHEMA_VERSION,'product':'XRP-USDC'}
    joblib.dump(bundle,artifact)
    meta = {k:v for k,v in bundle.items() if k != 'model'}
    meta.update(eligible=True,sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())
    (folder/'metadata.json').write_text(json.dumps(meta))
    pointer = tmp_path/'models'/'approved.json'
    pointer.write_text(json.dumps({'directory':str(folder),'version':'test'}))
    assert prediction.load_approved(pointer)[0]['version'] == 'test'
    meta['eligible'] = False
    (folder/'metadata.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='validation'):
        prediction.load_approved(pointer)
    meta['eligible'] = True
    meta['features'] = list(reversed(FEATURES))
    (folder/'metadata.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='schema'):
        prediction.load_approved(pointer)
    meta['features'] = FEATURES
    (folder/'metadata.json').write_text(json.dumps(meta))
    artifact.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='checksum'):
        prediction.load_approved(pointer)
