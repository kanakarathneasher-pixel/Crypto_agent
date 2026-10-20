import json
import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from src import backtest
from src.coinbase_pipeline import FEATURES
from tests.test_pipeline import candles


def test_chronological_backtest_costs_and_no_shorting(tmp_path,monkeypatch):
    monkeypatch.setattr(backtest,'ROOT',tmp_path)
    folder = tmp_path/'models'/'candidate'
    folder.mkdir(parents=True)
    raw = tmp_path/'data'/'raw'
    raw.mkdir(parents=True)
    df = candles(250)
    df.to_csv(raw/'coinbase_xrp_usdc_1h.csv',index=False)
    metadata = {'version':'synthetic-test','eligible':False,'partitions':{
        'train':{'target_end':str(df.open_time.iloc[80])},
        'test':{'start':str(df.open_time.iloc[100]),'end':str(df.open_time.iloc[200])}}}
    (folder/'metadata.json').write_text(json.dumps(metadata))
    model = DummyRegressor(strategy='constant',constant=.03).fit(np.zeros((10,len(FEATURES))),np.zeros(10))
    joblib.dump({'model':model},folder/'model.joblib')
    result = backtest.backtest(folder)
    fills = pd.read_csv(folder/'backtest_fills.csv')
    assert result['fills'] > 0
    assert (fills.fee > 0).all()
    assert fills.side.eq('BUY').all()
    first = fills.iloc[0]
    assert pd.Timestamp(first.timestamp) == df.open_time.iloc[101]
    assert first.price > df.open.iloc[101]  # BUY slippage paid at next OPEN.
    assert result['model_eligible'] is False
    model = DummyRegressor(strategy='constant',constant=-.03).fit(np.zeros((10,len(FEATURES))),np.zeros(10))
    joblib.dump({'model':model},folder/'model.joblib')
    result = backtest.backtest(folder)
    assert result['fills'] == 0  # SELL forecasts cannot create short positions.
