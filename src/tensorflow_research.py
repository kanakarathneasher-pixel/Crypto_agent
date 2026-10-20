"""CPU GRU/LSTM research; no access to production model promotion or trading.

Run with .venv-tf, not the backend .venv. The original final test and validation
periods are excluded. Development fold scores cannot qualify a model for trading.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys

# Set before TensorFlow is imported; modest CPU use and reproducible operations.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_NUM_INTRAOP_THREADS", "2")
os.environ.setdefault("TF_NUM_INTEROP_THREADS", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor
from src.coinbase_pipeline import ROOT
from src.neural_data import (SEQUENCE_FEATURES, SEQUENCE_SCHEMA, TARGET_SCALE, CLIP_Z,
    sequence_features, sequence_ends, make_fold, fit_scaler, scaled_sequences, regression_metrics)


def tensorflow():
    import tensorflow as tf
    return tf


def make_model(architecture, lookback, feature_count, seed=42):
    tf = tensorflow()
    tf.keras.utils.set_random_seed(seed)
    recurrent = {"gru": tf.keras.layers.GRU, "lstm": tf.keras.layers.LSTM}[architecture]
    inputs = tf.keras.Input(shape=(lookback, feature_count))
    x = recurrent(32, kernel_regularizer=tf.keras.regularizers.l2(1e-4))(inputs)
    x = tf.keras.layers.Dropout(.2)(x)
    x = tf.keras.layers.Dense(16, activation="relu", kernel_regularizer=tf.keras.regularizers.l2(1e-4))(x)
    outputs = tf.keras.layers.Dense(1, kernel_initializer="zeros", bias_initializer="zeros")(x)
    model = tf.keras.Model(inputs, outputs, name=f"xrp_{architecture}")
    model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=.001, clipnorm=1.0), loss="mae")
    return model


def dataset(x, y=None, batch_size=128):
    tf = tensorflow()
    data = tf.data.Dataset.from_tensor_slices(x if y is None else (x, y))
    options = tf.data.Options()
    options.threading.private_threadpool_size = 2
    options.threading.max_intra_op_parallelism = 1
    options.deterministic = True
    return data.with_options(options).batch(batch_size).prefetch(1)


def neural_predictions(model, x):
    return np.asarray(model.predict(dataset(x), verbose=0)).reshape(-1) / TARGET_SCALE


def train_neural(architecture, x, y, vx, vy, folder, epochs=25):
    tf = tensorflow()
    tf.keras.backend.clear_session()
    model = make_model(architecture, x.shape[1], x.shape[2])
    path = folder / f"{architecture}.keras"

    class Progress(tf.keras.callbacks.Callback):
        def on_epoch_end(self, epoch, logs=None):
            print(f"{folder.name}/{architecture} epoch {epoch+1}: "
                  f"loss={logs['loss']:.6f}, validation_loss={logs['val_loss']:.6f}", flush=True)

    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(str(path), monitor="val_loss", save_best_only=True),
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=4, min_delta=.0001, restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", patience=2, factor=.5, min_lr=.00005),
        tf.keras.callbacks.CSVLogger(str(folder / f"{architecture}_history.csv")), Progress(),
    ]
    history = model.fit(dataset(x, y), validation_data=dataset(vx, vy), epochs=epochs, verbose=0, callbacks=callbacks)
    # The checkpoint and evaluated model must be identical (minimum raw val_loss).
    model = tf.keras.models.load_model(path, compile=False, safe_mode=True)
    return model, {"epochs_completed": len(history.history["loss"]),
                   "best_epoch": int(np.argmin(history.history["val_loss"])) + 1,
                   "parameters": model.count_params()}


def partition_dates(frame, indices):
    return {"first_candle": frame.open_time.iloc[indices[0]].isoformat(),
            "last_candle": frame.open_time.iloc[indices[-1]].isoformat(),
            "last_target": frame.target_time.iloc[indices[-1]].isoformat(), "sequences": len(indices)}


def load_development_data(metadata_path):
    """Restrict raw candles before engineering; old validation/test are excluded."""
    metadata_path = Path(metadata_path)
    prior = json.loads(metadata_path.read_text(encoding="utf-8"))
    if prior.get("product") != "XRP-USDC":
        raise ValueError("Reference research must be Coinbase XRP-USDC.")
    cutoff = pd.Timestamp(prior["partitions"]["train"]["target_end"])
    raw_path = ROOT / "data/raw/coinbase_xrp_usdc_1h.csv"
    raw = pd.read_csv(raw_path)
    raw_time = pd.to_datetime(raw.open_time, utc=True)
    raw = raw.loc[raw_time <= cutoff].copy()
    frame, quality = sequence_features(raw)
    # The final row has no next-hour target and is automatically excluded.
    return frame, quality, {"reference_metadata": str(metadata_path),
        "reference_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
        "last_allowed_raw_candle": cutoff.isoformat(),
        "excluded_original_validation_start": prior["partitions"]["validation"]["start"],
        "excluded_original_test_start": prior["partitions"]["test"]["start"],
        "source_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest()}


def train(metadata_path, lookback=48, epochs=25):
    tf = tensorflow()
    tf.config.experimental.enable_op_determinism()
    frame, quality, provenance = load_development_data(metadata_path)
    ends = sequence_ends(frame, lookback)
    if len(ends) < 3000:
        raise ValueError(f"Only {len(ends)} sequences; at least 3000 required for this experiment.")
    version = datetime.now(timezone.utc).strftime("tensorflow-%Y%m%dT%H%M%S%fZ")
    output = ROOT / "models" / version
    output.mkdir(parents=True)
    metadata = {"version": version, "format": "keras-sequence-v1", "schema_version": SEQUENCE_SCHEMA,
        "product": "XRP-USDC", "features": SEQUENCE_FEATURES, "lookback": lookback,
        "target_scale": TARGET_SCALE, "clip_z": CLIP_Z, "eligible": False, "approved": False,
        "status": "training", "provenance": provenance, "quality": quality,
        "limitations": "Training-only development folds; these dates were used in prior research. No new untouched future test is available. No promotion or 90% accuracy claim.",
        "architecture": "32 GRU/LSTM units, dropout 0.2, Dense(16), L2 1e-4, MAE, Adam 0.001/clipnorm 1; early stopping patience 4; seed 42",
        "direction_definition": "Actual absolute return > 0.0001; predicted zero counts as a miss. 2% selective coverage is reported separately.",
        "packages": {name: importlib.metadata.version(name) for name in
                     ("tensorflow", "keras", "numpy", "pandas", "scikit-learn", "xgboost")},
        "python": sys.version, "devices": [device.name for device in tf.config.list_physical_devices()], "folds": []}
    metadata_file = output / "metadata.json"
    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Training directory: {output}\nDevelopment sequences: {len(ends)}\nCutoff: {provenance['last_allowed_raw_candle']}", flush=True)
    pooled = []
    # Two expanding training windows, with non-overlapping development evaluations.
    for number, fractions in enumerate(((.50, .65, .80), (.70, .85, 1.0)), start=1):
        fold = make_fold(frame, ends, *fractions)
        folder = output / f"fold_{number}"
        folder.mkdir()
        scaler, fitted_rows = fit_scaler(frame, fold.train, lookback)
        joblib.dump(scaler, folder / "scaler.joblib")
        x, y = scaled_sequences(frame, fold.train, scaler, lookback)
        vx, vy = scaled_sequences(frame, fold.validation, scaler, lookback)
        ex, ey = scaled_sequences(frame, fold.evaluation, scaler, lookback)
        actual = frame.target_next_return.iloc[fold.evaluation].to_numpy(dtype=float)
        validation_actual = frame.target_next_return.iloc[fold.validation].to_numpy(dtype=float)
        validation_scores, training_info = {}, {}
        # Only validation is read while selecting architecture/hyperparameters.
        for architecture in ("gru", "lstm"):
            model, info = train_neural(architecture, x, y, vx, vy, folder, epochs)
            validation_scores[architecture] = regression_metrics(validation_actual, neural_predictions(model, vx))
            training_info[architecture] = info
            del model
        tabular_candidates = []
        for depth in (2, 3):
            model = XGBRegressor(n_estimators=150, max_depth=depth, learning_rate=.03, reg_lambda=10,
                subsample=.8, colsample_bytree=.8, random_state=42, n_jobs=2, objective="reg:squarederror")
            model.fit(x[:, -1], y / TARGET_SCALE)
            score = regression_metrics(validation_actual, model.predict(vx[:, -1]))
            tabular_candidates.append((score["mae"], model, score))
        _, tabular, score = min(tabular_candidates, key=lambda item: item[0])
        validation_scores["xgboost"] = score
        joblib.dump(tabular, folder / "xgboost.joblib")
        selected = min(validation_scores, key=lambda name: validation_scores[name]["mae"])
        selected_neural = min(("gru", "lstm"), key=lambda name: validation_scores[name]["mae"])
        # Selection is frozen before the evaluation labels are scored.
        forecasts = {"zero_return": np.zeros(len(actual)),
                     "persistence": frame.return_1h.iloc[fold.evaluation].to_numpy(),
                     "xgboost": tabular.predict(ex[:, -1])}
        for architecture in ("gru", "lstm"):
            model = tf.keras.models.load_model(folder / f"{architecture}.keras", compile=False, safe_mode=True)
            forecasts[architecture] = neural_predictions(model, ex)
            del model
        evaluation = {name: regression_metrics(actual, forecast) for name, forecast in forecasts.items()}
        result = {"number": number, "partitions": {name: partition_dates(frame, indices) for name, indices in
                    (("train", fold.train), ("validation", fold.validation), ("development_evaluation", fold.evaluation))},
                  "scaler_last_observation": frame.open_time.iloc[fitted_rows[-1]].isoformat(),
                  "validation": validation_scores, "evaluation": evaluation,
                  "selected_on_validation": selected, "selected_neural_on_validation": selected_neural,
                  "xgboost_max_depth": tabular.get_params()["max_depth"], "training": training_info}
        metadata["folds"].append(result)
        (folder / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        forecast_frame = pd.DataFrame({"candle_time": frame.open_time.iloc[fold.evaluation].astype(str).to_numpy(),
            "target_time": frame.target_time.iloc[fold.evaluation].astype(str).to_numpy(), "actual_return": actual,
            **{f"{name}_prediction": values for name, values in forecasts.items()},
            "selected_prediction": forecasts[selected]})
        forecast_frame.to_csv(folder / "development_predictions.csv", index=False)
        pooled.append(forecast_frame)
        metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"Fold {number}: selected {selected} on validation. Development metrics:\n{json.dumps(evaluation, indent=2)}", flush=True)
        if number == 2:
            # Save the latest-fold neural winner, without refitting on evaluation.
            shutil.copy2(folder / f"{selected_neural}.keras", output / "model.keras")
            shutil.copy2(folder / "scaler.joblib", output / "scaler.joblib")
            metadata["selected_neural"] = selected_neural
            metadata["selected_overall_on_last_validation"] = selected
    combined = pd.concat(pooled, ignore_index=True)
    if combined.candle_time.duplicated().any():
        raise ValueError("Development evaluation folds overlap.")
    combined.to_csv(output / "development_predictions.csv", index=False)
    metadata["pooled_development"] = {name: regression_metrics(combined.actual_return, combined[f"{name}_prediction"])
        for name in ("zero_return", "persistence", "gru", "lstm", "xgboost", "selected")}
    metadata["checksums"] = {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                              for name in ("model.keras", "scaler.joblib")}
    metadata["status"] = "complete_research_only"
    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"\nSaved research model: {output}\n{json.dumps(metadata['pooled_development'], indent=2)}", flush=True)
    return output


def load_research_model(directory):
    folder = Path(directory).resolve()
    if not folder.is_relative_to((ROOT / "models").resolve()):
        raise ValueError("Only trusted local models/ artifacts can be loaded.")
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    if (metadata.get("format"), metadata.get("schema_version"), metadata.get("features"), metadata.get("status")) != (
        "keras-sequence-v1", SEQUENCE_SCHEMA, SEQUENCE_FEATURES, "complete_research_only"
    ) or metadata.get("product") != "XRP-USDC":
        raise ValueError("Research model metadata/schema mismatch or incomplete training.")
    if metadata["target_scale"] != TARGET_SCALE or metadata["clip_z"] != CLIP_Z:
        raise ValueError("Research preprocessing contract mismatch.")
    for name in ("model.keras", "scaler.joblib"):
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != metadata["checksums"][name]:
            raise ValueError("Research artifact checksum mismatch.")
    model = tensorflow().keras.models.load_model(folder / "model.keras", compile=False, safe_mode=True)
    scaler = joblib.load(folder / "scaler.joblib")
    if model.input_shape[1:] != (metadata["lookback"], len(SEQUENCE_FEATURES)):
        raise ValueError("Model input shape differs from metadata.")
    return model, scaler, metadata


def predict_research(directory, candles, as_of=None):
    """Diagnostic forecast only; never returns validated=True for the trading API."""
    model, scaler, metadata = load_research_model(directory)
    now = pd.Timestamp(as_of or datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise ValueError("as_of must be timezone-aware.")
    raw = candles.copy()
    raw_time = pd.to_datetime(raw.open_time, utc=True)
    raw = raw.loc[raw_time + pd.Timedelta(hours=1) <= now]
    frame, _ = sequence_features(raw)
    lookback = metadata["lookback"]
    recent = frame.tail(lookback)
    if len(recent) != lookback or not recent.open_time.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Not enough contiguous completed candles for inference.")
    if not np.isfinite(recent[SEQUENCE_FEATURES].to_numpy(dtype=float)).all():
        raise ValueError("Insufficient indicator warm-up or invalid features.")
    age = (now - (recent.open_time.iloc[-1] + pd.Timedelta(hours=1))).total_seconds()
    if not 0 <= age <= 3600:
        raise ValueError("Research inference data is stale.")
    z = scaler.transform(recent[SEQUENCE_FEATURES].to_numpy(dtype=float))
    x = np.clip(z, -CLIP_Z, CLIP_Z).astype(np.float32)[None]
    value = float(neural_predictions(model, x)[0])
    if not np.isfinite(value) or not -1 < value < 1:
        raise ValueError("Invalid neural forecast.")
    return {"mode": "research_only", "validated": False, "version": metadata["version"],
        "architecture": metadata["selected_neural"], "predicted_return": value,
        "illustrative_next_price": float(recent.close.iloc[-1]) * (1 + value),
        "candle_time": recent.open_time.iloc[-1].isoformat(), "as_of": now.isoformat(),
        "fraction_of_inputs_clipped": float((np.abs(z) > CLIP_Z).mean()),
        "warning": "Experimental forecast; not a calibrated probability or an approved trading signal."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["train", "predict"])
    parser.add_argument("--reference", default="models/coinbase-20261020T121949544468Z/metadata.json")
    parser.add_argument("--lookback", type=int, choices=[24, 48, 72], default=48)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--directory")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    if args.command == "train":
        if not 1 <= args.epochs <= 100:
            parser.error("epochs must be between 1 and 100")
        train(args.reference, args.lookback, args.epochs)
    else:
        if not args.directory:
            parser.error("predict requires --directory")
        data = pd.read_csv(ROOT / "data/raw/coinbase_xrp_usdc_1h.csv")
        print(json.dumps(predict_research(args.directory, data, args.as_of), indent=2))
