"""Inference uses only explicitly promoted, locally trusted Coinbase artifacts."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from src.coinbase_pipeline import FEATURES, ROOT, SCHEMA_VERSION, clean_candles, engineer_features


def load_approved(pointer):
    path = Path(pointer)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise ValueError("No model explicitly promoted; model-driven trading is blocked.")
    reference = json.loads(path.read_text())
    folder = Path(reference["directory"]).resolve()
    if not folder.is_relative_to((ROOT / "models").resolve()):
        raise ValueError("Model must be in the local models directory.")
    metadata = json.loads((folder / "metadata.json").read_text())
    artifact = folder / "model.joblib"
    if not metadata.get("eligible") or metadata.get("product") != "XRP-USDC":
        raise ValueError("Model has not passed Coinbase validation.")
    if metadata.get("schema_version") != SCHEMA_VERSION or metadata.get("features") != FEATURES:
        raise ValueError("Model feature schema mismatch.")
    if reference["version"] != metadata["version"] or hashlib.sha256(artifact.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError("Model version/checksum mismatch.")
    # joblib is code-capable: accept only artifacts created and promoted locally.
    bundle = joblib.load(artifact)
    if any(bundle.get(key) != metadata[key] for key in ("features", "schema_version", "version", "product")):
        raise ValueError("Artifact metadata mismatch.")
    if "n_jobs" in bundle["model"].get_params():
        bundle["model"].set_params(n_jobs=1)  # Small hourly inference needs no thread pool.
    return bundle, metadata


def predict(candles, pointer="models/approved.json", now=None):
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    clean, report = clean_candles(candles)
    if report["invalid_rows"]:
        raise ValueError("Invalid candles received during inference.")
    clean = clean.loc[clean.open_time + pd.Timedelta(hours=1) <= now]
    if clean.empty:
        raise ValueError("No completed candles.")
    latest = clean.open_time.iloc[-1]
    if not pd.Timedelta(0) <= now - (latest + pd.Timedelta(hours=1)) <= pd.Timedelta(minutes=10):
        raise ValueError("Completed candle data is stale.")
    inputs = engineer_features(clean).iloc[[-1]][FEATURES]
    if not np.isfinite(inputs.to_numpy(dtype=float)).all():
        raise ValueError("Insufficient contiguous candles or invalid features.")
    bundle, metadata = load_approved(pointer)
    value = float(bundle["model"].predict(inputs)[0])
    if not np.isfinite(value) or value <= -1 or abs(value) > 1:
        raise ValueError("Invalid model output.")
    close = float(clean.close.iloc[-1])
    return {"predicted_return": value, "estimated_price": close * (1 + value),
            "candle_time": latest.isoformat(), "timestamp": now.isoformat(),
            "version": bundle["version"], "validated": True, "metadata": metadata}
