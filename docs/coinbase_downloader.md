# Coinbase hourly history downloader

From PowerShell in the `Crypto_agent` folder, run your existing Windows virtual environment directly (activation is optional):

```powershell
.\.venv\Scripts\python.exe src\coinbase_data_loader.py
```

If pandas or requests is missing, install only these downloader dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install pandas requests
```

The public Advanced Trade endpoint needs no API credentials. It requests XRP-USDC with `ONE_HOUR` granularity. Coinbase's [official candles documentation](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-candles) documents UNIX-second `start` and `end` parameters and a maximum `limit` of 350 (checked October 20, 2026). This script uses the requested stricter limit of 300.

The window spans five calendar years up to the current UTC hour boundary, excluding the unfinished candle. For example, at 12:35 UTC the latest eligible candle starts at 11:00 UTC. February 29 maps to February 28 five years earlier.

Each batch covers at most 300 hours. The API end parameter is the last second of the batch; the next batch starts at the next hour. There are no page numbers. Requests are sequential, with a half-second delay, exponential backoff for connection errors, timeouts, HTTP 408/429/5xx, and support for `Retry-After` seconds or dates. Permanent errors stop the run.

Progress is saved after every successful batch in `data/raw/coinbase_xrp_usdc_1h.checkpoint.json`, including empty batches. The checkpoint contains both the accumulated records and the next window in one atomic file. If interrupted, run the same command again. The unfinished run retains its original time window so resume cannot skip history. After a completed run, a subsequent invocation starts a fresh scan with a newly calculated window, merging the existing CSV and checking history again. Run only one downloader process at a time.

The existing CSV stays in place while downloading. Before final replacement, the script preserves a timestamped `coinbase_xrp_usdc_1h.backup_*.csv` in the same directory. The final CSV keeps the original columns: `open_time,open,high,low,close,volume`. Timestamps are UTC; OHLCV values are numeric. Rows are sorted and duplicate timestamps removed, preferring the fresh observation. Only records within the requested window are included.

No missing candles or prices are generated. Empty historical windows do not stop the scan: five full years may not exist. At completion, the console prints earliest/latest candles, total unique records, duplicates removed (including overlaps with the existing CSV), and the missing-hour count. `coinbase_xrp_usdc_1h_missing_intervals.csv` lists every consecutive missing range with inclusive first/last timestamps and its hour count. Missing hours include empty history before the first candle and after the last; the report does not claim these periods were outages.

Run the offline checks without accessing Coinbase or changing real datasets:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_coinbase_data_loader.py -v
```
