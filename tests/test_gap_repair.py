import pandas as pd
import pytest
import requests

from src.coinbase_pipeline import FEATURES, engineer_features, hourly_segments
from src.repair_coinbase_gaps import repair
from tests.test_pipeline import candles


def test_all_targets_are_exactly_one_hour_and_features_restart():
    data = candles(500).drop(index=list(range(130, 135)) + [300]).reset_index(drop=True)
    result = engineer_features(data)
    labeled = result.dropna(subset=["target_time", "target_next_return"])
    assert (labeled.target_time - labeled.open_time == pd.Timedelta(hours=1)).all()
    for _, part in data.groupby(hourly_segments(data)):
        expected = engineer_features(part.reset_index(drop=True))
        actual = result.loc[result.open_time.isin(part.open_time)].reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, expected)
        assert pd.isna(actual.target_next_return.iloc[-1])
        assert actual.sma_72.iloc[:71].isna().all()
        assert len(actual.dropna(subset=FEATURES + ["target_next_return"])) == max(0, len(part)-72)


@pytest.mark.parametrize("mode", ["recovered", "empty", "error"])
def test_recovery_preserves_raw_or_backs_up_and_reports(tmp_path, monkeypatch, mode):
    full = candles(200)
    raw = tmp_path / "raw.csv"
    full.drop(index=[100]).to_csv(raw, index=False)
    original = raw.read_bytes()

    def fetch(session, start, end):
        assert start == full.open_time.iloc[100]
        assert end - start == pd.Timedelta(hours=1)
        if mode == "error":
            raise requests.Timeout("test timeout")
        if mode == "empty":
            return []
        row = full.iloc[100]
        candle = {name: str(row[name]) for name in ["open", "high", "low", "close", "volume"]}
        candle["start"] = str(int(row.open_time.timestamp()))
        return [candle, candle]  # Duplicate API entries must not duplicate the merge.

    monkeypatch.setattr("src.repair_coinbase_gaps.loader.fetch_candles", fetch)
    report = repair(raw, tmp_path / "processed")
    assert report["recovered_candles"] == (1 if mode == "recovered" else 0)
    assert report["remaining_missing_hours"] == (0 if mode == "recovered" else 1)
    if mode == "recovered":
        from pathlib import Path
        assert Path(report["backup"]).read_bytes() == original
        assert len(pd.read_csv(raw)) == 200
    else:
        assert raw.read_bytes() == original
        assert report["backup"] is None
    saved = pd.read_csv(tmp_path / "processed/coinbase_xrp_usdc_features.csv")
    assert (pd.to_datetime(saved.target_time) - pd.to_datetime(saved.open_time)
            == pd.Timedelta(hours=1)).all()
