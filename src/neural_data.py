"""Causal, gap-aware sequence preparation shared by TensorFlow training/inference.

This module has no TensorFlow dependency, so the main application's environment
can test data boundaries without installing deep-learning packages.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from src.coinbase_pipeline import FEATURES, clean_candles, engineer_features

SEQUENCE_SCHEMA = "coinbase-sequence-v1"
SEQUENCE_FEATURES = [name for name in FEATURES if name not in ("hour", "day_of_week")] + [
    "hour_sin", "hour_cos", "weekday_sin", "weekday_cos"]
TARGET_SCALE = 100.0  # Train on percentage points; predict() converts back to returns.
CLIP_Z = 10.0


def sequence_features(candles):
    """Make price-level indicators relative to the current completed close."""
    clean, quality = clean_candles(candles)
    if quality["invalid_rows"]:
        raise ValueError("Invalid source candles; review the quality report before training.")
    frame = engineer_features(clean)
    for name in ("sma_6", "sma_24", "sma_72", "ema_12", "ema_26"):
        frame[name] = frame[name] / frame.close - 1
    for name in ("macd", "macd_signal"):
        frame[name] = frame[name] / frame.close
    frame["rsi_14"] /= 100
    frame["hour_sin"] = np.sin(2 * np.pi * frame.hour / 24)
    frame["hour_cos"] = np.cos(2 * np.pi * frame.hour / 24)
    frame["weekday_sin"] = np.sin(2 * np.pi * frame.day_of_week / 7)
    frame["weekday_cos"] = np.cos(2 * np.pi * frame.day_of_week / 7)
    return frame, quality


def sequence_ends(frame, lookback=48):
    """A label uses t+1; each input contains exactly [t-lookback+1, ..., t]."""
    if lookback < 2:
        raise ValueError("Lookback must be at least two hours.")
    valid = np.isfinite(frame[SEQUENCE_FEATURES].to_numpy(dtype=float)).all(axis=1)
    rolling_valid = pd.Series(valid).rolling(lookback).sum().eq(lookback).to_numpy()
    contiguous = (frame.open_time - frame.open_time.shift(lookback-1)).eq(pd.Timedelta(hours=lookback-1))
    target_valid = frame.target_next_return.notna() & frame.target_time.eq(frame.open_time + pd.Timedelta(hours=1))
    return np.flatnonzero(rolling_valid & contiguous.to_numpy() & target_valid.to_numpy())


@dataclass
class TemporalFold:
    train: np.ndarray
    validation: np.ndarray
    evaluation: np.ndarray


def make_fold(frame, ends, train_fraction, validation_end_fraction, evaluation_end_fraction=1.0):
    """Purge boundary labels; prior-hour context is allowed at inference time."""
    a, b, c = (int(len(ends) * fraction) for fraction in
               (train_fraction, validation_end_fraction, evaluation_end_fraction))
    train, validation, evaluation = ends[:a], ends[a:b], ends[b:c]
    if min(len(train), len(validation), len(evaluation)) < 2:
        raise ValueError("Not enough sequences for chronological partitions.")
    train = train[(frame.target_time.iloc[train] < frame.open_time.iloc[validation[0]]).to_numpy()]
    validation = validation[(frame.target_time.iloc[validation] < frame.open_time.iloc[evaluation[0]]).to_numpy()]
    if not len(train) or not len(validation):
        raise ValueError("No observations remain after label purging.")
    return TemporalFold(train, validation, evaluation)


def fit_scaler(frame, train_ends, lookback):
    """Fit only unique observations actually present in training windows."""
    used = np.zeros(len(frame), dtype=bool)
    for end in train_ends:
        used[end-lookback+1:end+1] = True
    values = frame.loc[used, SEQUENCE_FEATURES].to_numpy(dtype=float)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("Invalid training-window features.")
    scaler = StandardScaler().fit(values)
    return scaler, np.flatnonzero(used)


def scaled_sequences(frame, ends, scaler, lookback):
    data = scaler.transform(frame[SEQUENCE_FEATURES].to_numpy(dtype=float))
    data = np.clip(data, -CLIP_Z, CLIP_Z).astype(np.float32)
    x = np.stack([data[end-lookback+1:end+1] for end in ends])
    if not np.isfinite(x).all():
        raise ValueError("Sequence contains invalid features.")
    y = frame.target_next_return.iloc[ends].to_numpy(dtype=np.float32) * TARGET_SCALE
    return x, y


def regression_metrics(actual, predicted):
    """Return-error and directional metrics; do not call MAE 'accuracy'."""
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if len(actual) == 0 or actual.shape != predicted.shape or not np.isfinite(predicted).all():
        raise ValueError("Invalid evaluation arrays.")
    error = predicted - actual
    directional = np.abs(actual) > .0001
    selective = directional & (np.abs(predicted) > .02)
    return {"samples": len(actual), "mae": float(np.abs(error).mean()),
            "rmse": float(np.sqrt(np.mean(error ** 2))), "bias": float(error.mean()),
            "directional_accuracy": float((np.sign(actual[directional]) == np.sign(predicted[directional])).mean()) if directional.any() else None,
            "directional_samples": int(directional.sum()),
            "forecast_above_2pct_count": int((np.abs(predicted) > .02).sum()),
            "forecast_above_2pct_coverage": float((np.abs(predicted) > .02).mean()),
            "selective_directional_accuracy": float((np.sign(actual[selective]) == np.sign(predicted[selective])).mean()) if selective.any() else None,
            "error_quantiles": dict(zip(["p05", "p50", "p95"], np.quantile(error, [.05, .5, .95]).tolist()))}
