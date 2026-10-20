import numpy as np
import pandas as pd
import pytest
from src.neural_data import (SEQUENCE_FEATURES, sequence_features, sequence_ends,
    make_fold, fit_scaler, scaled_sequences, regression_metrics)


def synthetic_candles(n=700):
    # Synthetic data is confined to tests, never used in actual training/results.
    close = 2 + np.arange(n) * .0001 + np.sin(np.arange(n) * .3) * .002
    return pd.DataFrame({"open_time": pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC"),
        "open": close, "high": close+.01, "low": close-.01, "close": close,
        "volume": 100 + (np.arange(n) % 50)})


def test_neural_features_causal_and_price_level_independent():
    raw = synthetic_candles()
    original, _ = sequence_features(raw)
    changed = raw.copy()
    changed.loc[500:, ["open", "high", "low", "close"]] *= 2
    altered, _ = sequence_features(changed)
    pd.testing.assert_frame_equal(original.loc[:499, SEQUENCE_FEATURES], altered.loc[:499, SEQUENCE_FEATURES])
    scale = raw.copy()
    scale[["open", "high", "low", "close"]] *= 10
    scaled, _ = sequence_features(scale)
    np.testing.assert_allclose(original[SEQUENCE_FEATURES].to_numpy(dtype=float),
                               scaled[SEQUENCE_FEATURES].to_numpy(dtype=float), atol=1e-10, equal_nan=True)


def test_sequences_order_and_no_target_as_input():
    frame, _ = sequence_features(synthetic_candles())
    ends = sequence_ends(frame, 48)
    fold = make_fold(frame, ends, .5, .7)
    assert frame.target_time.iloc[fold.train[-1]] < frame.open_time.iloc[fold.validation[0]]
    assert frame.target_time.iloc[fold.validation[-1]] < frame.open_time.iloc[fold.evaluation[0]]
    scaler, used = fit_scaler(frame, fold.train, 48)
    assert used[-1] == fold.train[-1] and used[-1] < fold.validation[0]
    x, y = scaled_sequences(frame, fold.validation, scaler, 48)
    assert x.shape == (len(fold.validation),48,len(SEQUENCE_FEATURES))
    assert 'target_next_return' not in SEQUENCE_FEATURES
    end = fold.validation[0]
    np.testing.assert_allclose(x[0,-1],np.clip(scaler.transform(frame[SEQUENCE_FEATURES].iloc[[end]].to_numpy()),-10,10)[0],atol=1e-6)
    assert y[0]/100 == pytest.approx(frame.close.iloc[end+1]/frame.close.iloc[end]-1,abs=1e-9)


def test_scaler_does_not_learn_from_future_partitions():
    frame, _ = sequence_features(synthetic_candles())
    ends = sequence_ends(frame)
    fold = make_fold(frame,ends,.5,.7)
    before, _ = fit_scaler(frame,fold.train,48)
    frame.loc[fold.validation[0]:,SEQUENCE_FEATURES] = 100000
    after, _ = fit_scaler(frame,fold.train,48)
    np.testing.assert_array_equal(before.mean_,after.mean_)
    np.testing.assert_array_equal(before.scale_,after.scale_)


def test_sequences_never_bridge_missing_hours():
    raw = synthetic_candles().drop(index=350).reset_index(drop=True)
    frame, _ = sequence_features(raw)
    for end in sequence_ends(frame,48):
        window = frame.open_time.iloc[end-47:end+1]
        assert window.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all()
    first_after = np.flatnonzero(frame.open_time > pd.Timestamp('2023-01-15 14:00:00+00:00'))[0]
    assert first_after not in sequence_ends(frame,48)


def test_metrics_do_not_hide_abstentions_or_small_classes():
    result = regression_metrics(np.array([.01,-.01,0]),np.zeros(3))
    assert result['directional_accuracy'] == 0 and result['directional_samples'] == 2
    assert result['forecast_above_2pct_count'] == 0
    assert result['selective_directional_accuracy'] is None
    with pytest.raises(ValueError):
        regression_metrics(np.array([.01]),np.array([np.nan]))
