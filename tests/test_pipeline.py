from datetime import datetime, timezone
from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest
from src.coinbase_pipeline import clean_candles, engineer_features, FEATURES
from src.prediction import predict, load_approved


def candles(n=120):
    close = 1 + np.arange(n) / 10000 + .002 * np.sin(np.arange(n))
    return pd.DataFrame({"open_time": pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC"),
                         "open": close, "high": close + .01, "low": close - .01, "close": close,
                         "volume": np.full(n, 100.)})


def test_timestamp_duplicate_and_utc():
    df = candles(4)
    df.open_time = df.open_time.astype(str)
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    result, report = clean_candles(df)
    assert len(result) == 4 and report["duplicates"] == 1
    assert str(result.open_time.dt.tz) == "UTC"


@pytest.mark.parametrize("column,value", [("open", 0), ("low", -1), ("high", .1), ("volume", -1), ("close", np.inf), ("open_time", "broken")])
def test_invalid_candles_reported(column, value):
    df = candles(4)
    df[column] = df[column].astype(object)
    df.loc[0, column] = value
    result, report = clean_candles(df)
    assert report["invalid_rows"] == 1 and len(result) == 3


def test_unix_seconds():
    df = candles(4)
    expected = df.open_time.iloc[0]
    df.open_time = [int(t.timestamp()) for t in candles(4).open_time]
    result, _ = clean_candles(df)
    assert result.open_time.iloc[0] == expected
    df.open_time = df.open_time.astype(str)
    result, _ = clean_candles(df)
    assert result.open_time.iloc[0] == expected


def test_features_are_causal_target_is_next_hour():
    df = candles()
    a = engineer_features(df)
    df.loc[100:, "close"] *= 2
    b = engineer_features(df)
    pd.testing.assert_frame_equal(a.loc[:99, FEATURES], b.loc[:99, FEATURES])
    assert a.target_next_return.iloc[90] == pytest.approx(df.close.iloc[91] / df.close.iloc[90] - 1)
    assert "target_next_return" not in FEATURES
    assert a[FEATURES].iloc[-1].notna().all()
    assert pd.isna(a.target_next_return.iloc[-1])


def test_gaps_restart_indicators_and_target():
    df = candles(220).drop(index=[100]).reset_index(drop=True)
    result = engineer_features(df)
    assert pd.isna(result.target_next_return.iloc[99])
    assert pd.isna(result.sma_72.iloc[100])
    assert result.sma_72.iloc[171] > 0


def test_inference_real_features_and_exact_order():
    df = candles()
    now = df.open_time.iloc[-1].to_pydatetime() + pd.Timedelta(hours=1, minutes=2)
    class Model:
        def predict(self, inputs):
            assert list(inputs.columns) == FEATURES
            return np.array([.01])
    with patch("src.prediction.load_approved", return_value=({"model": Model(), "version": "test"}, {})):
        result = predict(df, now=now)
    assert result["predicted_return"] == .01
    assert result["estimated_price"] == pytest.approx(df.close.iloc[-1] * 1.01)


def test_prediction_stale_and_insufficient():
    df = candles()
    with pytest.raises(ValueError, match="stale"):
        predict(df, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="Insufficient"):
        predict(df.tail(20), now=df.open_time.iloc[-1] + pd.Timedelta(hours=1))


def test_missing_model_never_uses_binance(tmp_path):
    with pytest.raises(ValueError, match="No model"):
        load_approved(tmp_path / "absent.json")
