"""Download available XRP-USDC hourly history; re-run after interruption to resume.

No API keys required. Official documentation checked 2026-10-20:
https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-candles
Coinbase documents a 350-candle maximum; we deliberately request at most 300.
"""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
from pathlib import Path
import random
import shutil
import sys
import time

import pandas as pd
import requests

PRODUCT = "XRP-USDC"
GRANULARITY = "ONE_HOUR"
URL = f"https://api.coinbase.com/api/v3/brokerage/market/products/{PRODUCT}/candles"
BATCH_HOURS = 300
REQUEST_DELAY = 0.5  # Sequential requests, at most two per second; no bursts.
MAX_ATTEMPTS = 6
HOUR = timedelta(hours=1)
COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]
OUTPUT = (Path(__file__).resolve().parent.parent / "data" / "raw"
          / "coinbase_xrp_usdc_1h.csv")


def historical_window(now=None):
    """Five calendar years; end is exclusive, excluding the unfinished hour."""
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end = end.replace(minute=0, second=0, microsecond=0)
    try:
        start = end.replace(year=end.year - 5)
    except ValueError:  # Handle February 29 when the earlier year is not leap.
        start = end.replace(year=end.year - 5, day=28)
    return start, end


def normalize(frame):
    """Validate UTC timestamps and numeric OHLCV without inventing values."""
    if frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    frame = frame[COLUMNS].copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True, errors="raise")
    if frame.open_time.isna().any():
        raise ValueError("Missing candle timestamp.")
    if (frame.open_time != frame.open_time.dt.floor("h")).any():
        raise ValueError("Candle timestamp is not on a UTC hour boundary.")
    for column in COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not frame[column].map(math.isfinite).all():
            raise ValueError(f"Invalid or missing numeric value in {column}.")
    return frame


def combine(existing, incoming, start, end):
    frames = [frame for frame in (existing, incoming) if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=COLUMNS), 0
    frame = pd.concat(frames, ignore_index=True)
    frame = frame.loc[(frame.open_time >= start) & (frame.open_time < end)]
    duplicates = int(frame.duplicated("open_time").sum())
    # Prefer freshly downloaded values when an existing timestamp recurs.
    frame = frame.drop_duplicates("open_time", keep="last")
    return frame.sort_values("open_time").reset_index(drop=True), duplicates


def retry_after_seconds(value):
    """Retry-After supports seconds or an HTTP date."""
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0.0


def fetch_candles(session, start, end):
    """Fetch one time window, retrying network errors, 408, 429 and 5xx."""
    params = {
        "start": str(int(start.timestamp())),
        # Last second prevents an extra boundary candle if API end is inclusive.
        "end": str(int(end.timestamp()) - 1),
        "granularity": GRANULARITY,
        "limit": BATCH_HOURS,
    }
    payload = request_json(session, URL, params)
    if not isinstance(payload, dict) or not isinstance(payload.get("candles"), list):
        raise ValueError("Coinbase response does not contain a candles list.")
    return payload["candles"]


def request_json(session, url, params=None):
    """Shared public GET transport: no authentication or order capability."""
    for attempt in range(MAX_ATTEMPTS):
        time.sleep(REQUEST_DELAY)
        retry_after = 0.0
        try:
            response = session.get(url, params=params, timeout=(10, 30))
            retry_after = retry_after_seconds(response.headers.get("Retry-After"))
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as error:
            if isinstance(error, requests.HTTPError):
                status = error.response.status_code
                if status not in (408, 429) and not 500 <= status < 600:
                    raise  # Never treat a permanent error as empty history.
            if attempt == MAX_ATTEMPTS - 1:
                raise
            delay = max(retry_after, min(60, 2 ** attempt) + random.uniform(0, 0.5))
            print(f"Temporary request failure: {error}. Retrying in {delay:.1f}s.", flush=True)
            time.sleep(delay)


def verify_product(session):
    product = request_json(session, URL.removesuffix("/candles"))
    if product.get("product_id") != PRODUCT:
        raise ValueError(f"Coinbase did not recognize {PRODUCT}.")
    print("Verified Coinbase product:", product["product_id"])
    return product


def candles_frame(candles, start, end):
    if not candles:
        return pd.DataFrame(columns=COLUMNS)
    frame = pd.DataFrame(candles)
    frame["open_time"] = pd.to_datetime(
        pd.to_numeric(frame["start"], errors="raise"), unit="s", utc=True
    )
    frame = normalize(frame)
    # Exclude out-of-window observations defensively, including the current hour.
    return frame.loc[(frame.open_time >= start) & (frame.open_time < end)]


def save_checkpoint(path, state, frame):
    """Data and cursor share one atomic file so neither can get ahead."""
    records = frame.copy()
    records["open_time"] = records["open_time"].astype(str)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump({**state, "records": records.to_dict("records")}, handle, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def missing_intervals(frame, start, end):
    """Count absent hours across the whole window and group consecutive gaps."""
    expected = pd.date_range(start, end, freq="h", inclusive="left")
    missing = expected.difference(pd.DatetimeIndex(frame.open_time))
    ranges = []
    if len(missing):
        first = previous = missing[0]
        for stamp in missing[1:]:
            if stamp - previous != HOUR:
                ranges.append((first, previous, int((previous - first) / HOUR) + 1))
                first = stamp
            previous = stamp
        ranges.append((first, previous, int((previous - first) / HOUR) + 1))
    return len(missing), pd.DataFrame(
        ranges, columns=["first_missing_hour_utc", "last_missing_hour_utc", "missing_hours"]
    )


def download(output=OUTPUT):
    """Resume an unfinished fixed window, or start a fresh five-year scan."""
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = output.with_suffix(".checkpoint.json")
    state = None
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if (saved.get("version"), saved.get("product"), saved.get("granularity")) != (
            1, PRODUCT, GRANULARITY
        ):
            raise ValueError(f"Unrecognized checkpoint: {checkpoint}")
        if not saved["complete"]:
            frame = normalize(pd.DataFrame(saved.pop("records"), columns=COLUMNS))
            state = saved
            print(f"Resuming checkpoint: {checkpoint}")

    if state is None:
        start, end = historical_window()
        existing = normalize(pd.read_csv(output)) if output.exists() else pd.DataFrame(columns=COLUMNS)
        frame, duplicates = combine(existing, pd.DataFrame(columns=COLUMNS), start, end)
        state = {
            "version": 1, "product": PRODUCT, "granularity": GRANULARITY,
            "start": start.isoformat(), "end": end.isoformat(),
            "next_start": start.isoformat(), "batches": 0, "downloaded": 0,
            "duplicates": duplicates, "complete": False,
        }
        save_checkpoint(checkpoint, state, frame)

    start = datetime.fromisoformat(state["start"])
    end = datetime.fromisoformat(state["end"])
    cursor = datetime.fromisoformat(state["next_start"])
    total_batches = math.ceil((end - start) / (HOUR * BATCH_HOURS))
    print(f"UTC window: {start} <= candle start < {end}")
    print(f"Last fully completed candle starts: {end - HOUR}")
    with requests.Session() as session:
        session.headers.update({"User-Agent": "Crypto-agent-public-history/1.0"})
        verify_product(session)
        while cursor < end:
            batch_end = min(cursor + HOUR * BATCH_HOURS, end)
            candles = fetch_candles(session, cursor, batch_end)
            batch = candles_frame(candles, cursor, batch_end)
            frame, duplicates = combine(frame, batch, start, end)
            state["duplicates"] += duplicates
            state["downloaded"] += len(candles)
            state["batches"] += 1
            state["next_start"] = batch_end.isoformat()
            # Empty windows are successful historical checks, not stopping points.
            save_checkpoint(checkpoint, state, frame)
            print(
                f"Batch {state['batches']}/{total_batches} completed: "
                f"{cursor.isoformat()} to {batch_end.isoformat()} (exclusive); "
                f"received {len(candles)}, downloaded {state['downloaded']}, "
                f"unique records {len(frame)}" + (" [empty period]" if not candles else ""),
                flush=True,
            )
            cursor = batch_end

    missing_count, gaps = missing_intervals(frame, start, end)
    gap_output = output.with_name(output.stem + "_missing_intervals.csv")
    gaps.to_csv(gap_output, index=False)
    if output.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = output.with_name(f"{output.stem}.backup_{stamp}.csv")
        shutil.copy2(output, backup)  # Must succeed before replacing the dataset.
        print(f"Preserved backup: {backup}")
    temporary = output.with_suffix(".csv.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(output)
    state["complete"] = True
    save_checkpoint(checkpoint, state, frame)

    print("Earliest candle:", frame.open_time.min() if len(frame) else "none")
    print("Latest candle:", frame.open_time.max() if len(frame) else "none")
    print("Total records:", len(frame))
    print("Duplicate count removed (including existing CSV overlaps):", state["duplicates"])
    print("Missing-hour count (entire requested window):", missing_count)
    print("Missing intervals report:", gap_output)
    print("Missing hours may precede available history; they are not filled.")
    print("Saved to:", output)


def main():
    try:
        download()
    except (KeyboardInterrupt, requests.RequestException, ValueError, OSError, KeyError) as error:
        print(f"\nDownload stopped: {error}", file=sys.stderr)
        print("Re-run the same command to resume the last successful checkpoint.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
