"""Retry only internal hourly gaps. Run: python -m src.repair_coinbase_gaps."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd
import requests

from src import coinbase_data_loader as loader
from src.coinbase_pipeline import clean_candles, build_files


def missing_hours(frame):
    """Derive missing timestamps directly from the actual candle coverage."""
    if frame.empty:
        return pd.DatetimeIndex([], tz="UTC")
    return pd.date_range(frame.open_time.min(), frame.open_time.max(), freq="h").difference(
        pd.DatetimeIndex(frame.open_time)
    )


def repair(output=loader.OUTPUT, report_dir=None):
    output = Path(output)
    report_dir = Path(report_dir) if report_dir else output.parent.parent / "processed"
    report_dir.mkdir(parents=True, exist_ok=True)
    original_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    original = pd.read_csv(output)
    clean, quality = clean_candles(original)
    # Raw history is preserved rather than silently deleting invalid existing rows.
    if quality["invalid_rows"] or quality["duplicates"]:
        raise ValueError("Raw data has invalid or duplicate rows; review before gap repair.")
    missing = missing_hours(clean)
    incoming = []
    attempts = []
    with requests.Session() as session:
        for _, group in pd.Series(missing).groupby(
            pd.Series(missing).diff().ne(pd.Timedelta(hours=1)).cumsum()
        ):
            cursor, end = group.iloc[0], group.iloc[-1] + pd.Timedelta(hours=1)
            while cursor < end:
                stop = min(cursor + pd.Timedelta(hours=loader.BATCH_HOURS), end)
                attempt = {"start_utc": str(cursor), "end_exclusive_utc": str(stop)}
                try:
                    candles = loader.fetch_candles(session, cursor, stop)
                    frame = loader.candles_frame(candles, cursor, stop)
                    frame, validation = clean_candles(frame)
                    frame = frame.loc[frame.open_time.isin(missing)]
                    incoming.append(frame)
                    attempt.update(status="success", returned=len(candles),
                                   valid_missing_candles=len(frame),
                                   invalid_candles=validation["invalid_rows"])
                except (requests.RequestException, ValueError, KeyError) as error:
                    # A failed request is not evidence that Coinbase has no candles.
                    attempt.update(status="request_failed", error=str(error))
                attempts.append(attempt)
                print(json.dumps(attempt), flush=True)
                cursor = stop
    recovered = pd.concat(incoming, ignore_index=True) if incoming else clean.iloc[:0]
    recovered = recovered.drop_duplicates("open_time")
    combined = pd.concat([clean, recovered], ignore_index=True).sort_values("open_time")
    remaining = missing_hours(combined)
    backup = None
    if len(recovered):
        if hashlib.sha256(output.read_bytes()).hexdigest() != original_hash:
            raise RuntimeError("Raw CSV changed during recovery; refusing to overwrite it.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = output.with_name(f"{output.stem}.backup_gap_repair_{stamp}.csv")
        shutil.copy2(output, backup)
        temporary = output.with_suffix(".repair.tmp")
        combined.to_csv(temporary, index=False)
        temporary.replace(output)
    pd.DataFrame({"missing_hour_utc": remaining}).to_csv(
        report_dir / "coinbase_remaining_missing_hours.csv", index=False
    )
    usable = build_files(output, report_dir)
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "original_sha256": original_hash,
        "result_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "original_missing_timestamps": [str(t) for t in missing],
        "recovered_candles": len(recovered),
        "remaining_missing_hours": len(remaining),
        "remaining_gap_intervals": int(pd.Series(remaining).diff().ne(pd.Timedelta(hours=1)).sum()),
        "valid_training_observations": len(usable),
        "backup": str(backup) if backup else None,
        "attempts": attempts,
    }
    (report_dir / "coinbase_gap_recovery_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    repair()
