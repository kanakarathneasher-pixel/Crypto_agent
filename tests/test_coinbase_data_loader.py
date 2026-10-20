"""Offline tests: no API calls and no changes to the real dataset."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from src import coinbase_data_loader as loader


START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def candle(stamp, close="2"):
    return {"start": str(int(stamp.timestamp())), "open": "1", "high": "3",
            "low": "1", "close": close, "volume": "10"}


class DownloaderTests(unittest.TestCase):
    def test_calendar_window_excludes_unfinished_hour_and_handles_leap_day(self):
        start, end = loader.historical_window(datetime(2024, 2, 29, 12, 45, tzinfo=timezone.utc))
        self.assertEqual(start, datetime(2019, 2, 28, 12, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2024, 2, 29, 12, tzinfo=timezone.utc))

    def test_numeric_utc_sort_deduplicate_and_filter(self):
        end = START + 3 * loader.HOUR
        data = loader.candles_frame([
            candle(START + loader.HOUR), candle(START), candle(START, "2.5"), candle(end)
        ], START, end)
        frame, duplicates = loader.combine(pd.DataFrame(columns=loader.COLUMNS), data, START, end)
        self.assertEqual(duplicates, 1)
        self.assertEqual(list(frame.open_time), [START, START + loader.HOUR])
        self.assertEqual(frame.iloc[0].close, 2.5)
        self.assertEqual(str(frame.open_time.dt.tz), "UTC")

    def test_gaps_include_empty_edges_and_internal_hours(self):
        end = START + 6 * loader.HOUR
        frame = loader.candles_frame([candle(START + loader.HOUR), candle(START + 3 * loader.HOUR)], START, end)
        count, gaps = loader.missing_intervals(frame, START, end)
        self.assertEqual(count, 4)
        self.assertEqual(list(gaps.missing_hours), [1, 1, 2])
        count, gaps = loader.missing_intervals(pd.DataFrame(columns=loader.COLUMNS), START, end)
        self.assertEqual(count, 6)
        self.assertEqual(len(gaps), 1)

    @patch.object(loader.time, "sleep")
    def test_retry_network_and_rate_limit_and_request_parameters(self, sleep):
        limited = Mock(status_code=429, headers={"Retry-After": "7"})
        limited.raise_for_status.side_effect = requests.HTTPError(response=limited)
        success = Mock(status_code=200, headers={})
        success.json.return_value = {"candles": []}
        session = Mock()
        session.get.side_effect = [requests.Timeout("timeout"), limited, success]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(loader.fetch_candles(session, START, START + 300 * loader.HOUR), [])
        params = session.get.call_args.kwargs["params"]
        self.assertEqual(params["limit"], 300)
        self.assertEqual(params["granularity"], "ONE_HOUR")
        self.assertEqual(int(params["end"]) - int(params["start"]), 300 * 3600 - 1)
        sleep.assert_any_call(7.0)

    @patch.object(loader.time, "sleep")
    def test_permanent_error_is_not_empty_history(self, sleep):
        response = Mock(status_code=400, headers={})
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        session = Mock()
        session.get.return_value = response
        with self.assertRaises(requests.HTTPError):
            loader.fetch_candles(session, START, START + loader.HOUR)
        self.assertEqual(session.get.call_count, 1)

    def test_interrupted_download_resumes_empty_batch_and_preserves_backup(self):
        end = START + 601 * loader.HOUR
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "history.csv"
            original = loader.candles_frame([candle(START)], START, end)
            original.to_csv(output, index=False)
            original_bytes = output.read_bytes()
            with patch.object(loader, "historical_window", return_value=(START, end)), patch.object(loader, "verify_product"), redirect_stdout(io.StringIO()):
                with patch.object(loader, "fetch_candles", side_effect=[[], requests.Timeout("stop")]):
                    with self.assertRaises(requests.Timeout):
                        loader.download(output)
                self.assertEqual(output.read_bytes(), original_bytes)
                state = json.loads(output.with_suffix(".checkpoint.json").read_text())
                self.assertEqual(state["batches"], 1)
                self.assertEqual(state["next_start"], (START + 300 * loader.HOUR).isoformat())
                with patch.object(loader, "fetch_candles", side_effect=[
                    [candle(START + 300 * loader.HOUR)], [candle(START + 600 * loader.HOUR)]
                ]) as fetch:
                    loader.download(output)
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(fetch.call_args_list[0].args[1:], (START + 300 * loader.HOUR, START + 600 * loader.HOUR))
                self.assertEqual(fetch.call_args_list[1].args[1:], (START + 600 * loader.HOUR, end))
            self.assertEqual(len(pd.read_csv(output)), 3)
            backups = list(Path(directory).glob("*.backup_*.csv"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original_bytes)
            state = json.loads(output.with_suffix(".checkpoint.json").read_text())
            self.assertTrue(state["complete"])
            gaps = pd.read_csv(output.with_name("history_missing_intervals.csv"))
            self.assertEqual(gaps.missing_hours.sum(), 598)

    def test_invalid_values_are_rejected(self):
        with self.assertRaises(ValueError):
            loader.candles_frame([candle(START, "NaN")], START, START + loader.HOUR)


if __name__ == "__main__":
    unittest.main()
