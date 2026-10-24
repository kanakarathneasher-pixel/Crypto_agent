from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
import pandas as pd
import pytest
from pydantic import ValidationError
from backend import coinbase_client
from backend.config import Config
from tests.test_pipeline import candles


def test_hourly_cache_is_reused_but_refreshes_at_next_boundary(monkeypatch):
    monkeypatch.setattr(coinbase_client, '_history', None)
    monkeypatch.setattr(coinbase_client, '_history_end', None)
    fetch = Mock(return_value=[])
    monkeypatch.setattr(coinbase_client, 'fetch_candles', fetch)
    def frame(values, start, end):
        result = candles(120)
        result.open_time = pd.date_range(end=end-timedelta(hours=1), periods=120, freq='h', tz='UTC')
        return result
    monkeypatch.setattr(coinbase_client, 'candles_frame', frame)
    end = datetime(2026, 10, 24, 10, tzinfo=timezone.utc)
    first = coinbase_client.recent_history(None, end)
    first.loc[0, 'close'] = 999
    second = coinbase_client.recent_history(None, end)
    assert fetch.call_count == 1
    assert second.close.iloc[0] != 999
    third = coinbase_client.recent_history(None, end+timedelta(hours=1))
    assert fetch.call_count == 2
    assert third.open_time.iloc[-1] == pd.Timestamp(end)


def test_two_second_interval_is_valid_and_faster_polling_is_rejected():
    assert Config(worker_poll_seconds=2).worker_poll_seconds == 2
    with pytest.raises(ValidationError):
        Config(worker_poll_seconds=1)
