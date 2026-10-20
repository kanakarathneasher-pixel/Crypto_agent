"""Reusable Coinbase validation and causal features, independent of Binance scripts."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OHLCV = ["open_time", "open", "high", "low", "close", "volume"]
FEATURES = ["return_1h", "return_3h", "return_6h", "return_24h", "sma_6", "sma_24",
            "sma_72", "ema_12", "ema_26", "rsi_14", "macd", "macd_signal",
            "volatility_24h", "volume_change", "relative_volume", "candle_range",
            "candle_body", "hour", "day_of_week"]
SCHEMA_VERSION = "coinbase-hourly-v1"


def clean_candles(data):
    """Drop and report invalid records. Never forward-fill or interpolate prices."""
    df = data[OHLCV].copy()
    # Native API timestamps are UNIX seconds; stored CSV timestamps are ISO UTC.
    unix_seconds = pd.to_numeric(df.open_time, errors="coerce")
    if pd.api.types.is_datetime64_any_dtype(df.open_time):
        df["open_time"] = pd.to_datetime(df.open_time, utc=True, errors="coerce")
    elif pd.api.types.is_numeric_dtype(df.open_time) or (len(df) and unix_seconds.notna().all()):
        df["open_time"] = pd.to_datetime(unix_seconds, unit="s", utc=True, errors="coerce")
    else:
        df["open_time"] = pd.to_datetime(df.open_time, utc=True, errors="coerce", format="mixed")
    for column in OHLCV[1:]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    finite = np.isfinite(df[OHLCV[1:]]).all(axis=1)
    valid = (df.open_time.notna() & (df.open_time == df.open_time.dt.floor("h")) & finite
             & (df[["open", "high", "low", "close"]] > 0).all(axis=1) & (df.volume >= 0)
             & (df.high >= df[["open", "close", "low"]].max(axis=1))
             & (df.low <= df[["open", "close", "high"]].min(axis=1)))
    report = {"input_rows": len(df), "invalid_rows": int((~valid).sum()),
              "invalid_row_indices": df.index[~valid].tolist()}
    df = df.loc[valid].copy()
    report["duplicates"] = int(df.duplicated("open_time").sum())
    df = df.drop_duplicates("open_time", keep="last").sort_values("open_time").reset_index(drop=True)
    gaps = df.open_time.diff().dt.total_seconds().div(3600).sub(1).clip(lower=0).fillna(0)
    report["missing_hours"] = int(gaps.sum())
    report["gap_intervals"] = [{"previous": str(df.open_time.iloc[i-1]), "next": str(df.open_time.iloc[i]),
                                "missing_hours": int(gaps.iloc[i])} for i in range(1, len(df)) if gaps.iloc[i] > 0]
    # Flag large moves for review; a large valid move is not automatically an error.
    changes = df.close.pct_change(fill_method=None).abs()
    abnormal = (changes > 0.25) | ((df.high - df.low) / df.close > 0.5)
    report["abnormal_observations"] = df.loc[abnormal, "open_time"].astype(str).tolist()
    report["cleaned_rows"] = len(df)
    return df, report


def _segment_features(df):
    df = df.copy()
    close = df.close
    for hours in (1, 3, 6, 24):
        df[f"return_{hours}h"] = close.pct_change(hours, fill_method=None)
    for hours in (6, 24, 72):
        df[f"sma_{hours}"] = close.rolling(hours).mean()
    for hours in (12, 26):
        df[f"ema_{hours}"] = close.ewm(span=hours, adjust=False, min_periods=hours).mean()
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    df["rsi_14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    df.loc[(loss == 0) & (gain > 0), "rsi_14"] = 100
    df.loc[(loss == 0) & (gain == 0), "rsi_14"] = 50
    df["macd"] = df.ema_12 - df.ema_26
    df["macd_signal"] = df.macd.ewm(span=9, adjust=False, min_periods=9).mean()
    df["volatility_24h"] = df.return_1h.rolling(24).std()
    df["volume_change"] = df.volume.pct_change(fill_method=None)
    df["relative_volume"] = df.volume / df.volume.rolling(24).mean().replace(0, np.nan)
    df["candle_range"] = (df.high - df.low) / close
    df["candle_body"] = (df.close - df.open) / df.open
    df["hour"] = df.open_time.dt.hour
    df["day_of_week"] = df.open_time.dt.dayofweek
    df["target_next_return"] = close.shift(-1) / close - 1
    df["target_time"] = df.open_time.shift(-1)
    return df


def hourly_segments(cleaned):
    """Assign a new segment whenever consecutive timestamps are not one hour apart."""
    return cleaned.open_time.diff().ne(pd.Timedelta(hours=1)).cumsum().rename("segment_id")


def engineer_features(cleaned):
    """Restart indicators at gaps; the target is never used as an input feature."""
    if cleaned.empty:
        return pd.DataFrame(columns=OHLCV + FEATURES + ["target_next_return", "target_time"])
    segment = hourly_segments(cleaned)
    result = pd.concat([_segment_features(part) for _, part in cleaned.groupby(segment)], ignore_index=True)
    return result.replace([np.inf, -np.inf], np.nan)


def build_files(raw=None, folder=None):
    raw = raw or ROOT / "data/raw/coinbase_xrp_usdc_1h.csv"
    clean, report = clean_candles(pd.read_csv(raw))
    folder = folder or ROOT / "data/processed"
    folder.mkdir(parents=True, exist_ok=True)
    clean.to_csv(folder / "coinbase_xrp_usdc_cleaned.csv", index=False)
    segments = clean.assign(segment_id=hourly_segments(clean))
    segments.groupby("segment_id").agg(
        first_hour=("open_time", "min"), last_hour=("open_time", "max"),
        observations=("open_time", "size"),
    ).to_csv(folder / "coinbase_hourly_segments.csv")
    engineered = engineer_features(clean)
    usable = engineered.dropna(subset=FEATURES + ["target_next_return", "target_time"])
    usable = usable.loc[usable.target_time - usable.open_time == pd.Timedelta(hours=1)]
    report["continuous_segments"] = int(hourly_segments(clean).nunique())
    report["valid_training_observations"] = len(usable)
    report["excluded_training_observations"] = len(clean) - len(usable)
    usable.to_csv(folder / "coinbase_xrp_usdc_features.csv", index=False)
    (folder / "coinbase_quality_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("Usable supervised observations:", len(usable))
    return usable


if __name__ == "__main__":
    build_files()
