"""Versioned Coinbase research. Training never promotes a model automatically."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor
from src.coinbase_pipeline import FEATURES, ROOT, SCHEMA_VERSION, build_files


def metrics(actual, prediction):
    actual, prediction = np.asarray(actual), np.asarray(prediction)
    # Exclude actual moves <= 1 basis point; zero forecasts count as abstentions/misses.
    mask = np.abs(actual) > 0.0001
    error = prediction - actual
    return {"mae": float(mean_absolute_error(actual, prediction)),
            "rmse": float(np.sqrt(mean_squared_error(actual, prediction))),
            "directional_accuracy": float((np.sign(actual[mask]) == np.sign(prediction[mask])).mean()) if mask.any() else None,
            "directional_samples": int(mask.sum()), "bias": float(error.mean()),
            "error_quantiles": dict(zip(["p05", "p50", "p95"], np.quantile(error, [.05, .5, .95]).tolist()))}


def train():
    df = build_files().reset_index(drop=True)
    if len(df) < 500:
        raise ValueError(f"Only {len(df)} usable Coinbase rows: need at least 500; trading remains blocked.")
    a, b = int(len(df) * .70), int(len(df) * .85)
    train, validation, test = df.iloc[:a-1], df.iloc[a:b-1], df.iloc[b:]
    prior_runs = sorted((ROOT / "models").glob("coinbase-*/metadata.json"))
    if prior_runs:
        previous = json.loads(prior_runs[-1].read_text())
        prior_test_end = pd.Timestamp(previous["partitions"]["test"]["target_end"])
        test = test.loc[test.open_time > prior_test_end]
        if len(test) < 200:
            raise ValueError("Retraining requires at least 200 newly completed, previously untested holdout hours. Existing final test data will not be reused.")
    # Purge any target touching the next partition, including across missing rows.
    train = train.loc[train.target_time < validation.open_time.min()]
    validation = validation.loc[validation.target_time < test.open_time.min()]
    candidates = {
        "random_forest": RandomForestRegressor(n_estimators=150, max_depth=5, min_samples_leaf=15, random_state=42, n_jobs=2),
        "xgboost": XGBRegressor(n_estimators=150, max_depth=3, learning_rate=.03, subsample=.8,
                                colsample_bytree=.8, reg_lambda=10, objective="reg:squarederror", random_state=42, n_jobs=2),
    }
    report = {"zero_return": {name: metrics(part.target_next_return, np.zeros(len(part)))
                              for name, part in [("validation", validation), ("test", test)]}}
    for name, model in candidates.items():
        model.fit(train[FEATURES], train.target_next_return)
        report[name] = {"validation": metrics(validation.target_next_return, model.predict(validation[FEATURES]))}
    selected = min(candidates, key=lambda name: report[name]["validation"]["mae"])
    # Selection is now fixed. The final test is evaluated once for reporting and gating.
    for name, model in candidates.items():
        report[name]["test"] = metrics(test.target_next_return, model.predict(test[FEATURES]))
    # Compare a previously approved artifact only on genuinely later, unseen data.
    pointer = ROOT / "models/approved.json"
    if pointer.exists():
        from src.prediction import load_approved
        incumbent, incumbent_meta = load_approved(pointer)
        unseen = test.loc[test.open_time > pd.Timestamp(incumbent_meta["partitions"]["test"]["target_end"])]
        report["incumbent_comparison"] = {
            "version": incumbent_meta["version"], "unseen_rows": len(unseen),
            "incumbent": metrics(unseen.target_next_return, incumbent["model"].predict(unseen[FEATURES])) if len(unseen) else None,
            "candidate": metrics(unseen.target_next_return, candidates[selected].predict(unseen[FEATURES])) if len(unseen) else None,
        }
    walk = []
    from sklearn.base import clone
    for fit_index, evaluate_index in TimeSeriesSplit(n_splits=3, gap=1).split(train):
        model = clone(candidates[selected])
        fit, evaluate = train.iloc[fit_index], train.iloc[evaluate_index]
        model.fit(fit[FEATURES], fit.target_next_return)
        walk.append({"model": metrics(evaluate.target_next_return, model.predict(evaluate[FEATURES])),
                     "baseline": metrics(evaluate.target_next_return, np.zeros(len(evaluate))),
                     "start": str(evaluate.open_time.min()), "end": str(evaluate.open_time.max())})
    def beats(candidate, baseline):
        return all(candidate[key] < .95 * baseline[key] for key in ("mae", "rmse"))
    eligible = (len(test) >= 200 and len(validation) >= 200
                and all(beats(report[selected][part], report["zero_return"][part]) for part in ("validation", "test"))
                and all(beats(fold["model"], fold["baseline"]) for fold in walk))
    version = datetime.now(timezone.utc).strftime("coinbase-%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "models" / version
    folder.mkdir(parents=True)
    artifact = folder / "model.joblib"
    joblib.dump({"model": candidates[selected], "features": FEATURES, "schema_version": SCHEMA_VERSION,
                 "product": "XRP-USDC", "version": version}, artifact)
    metadata = {"version": version, "product": "XRP-USDC", "schema_version": SCHEMA_VERSION,
                "features": FEATURES, "selected": selected, "eligible": bool(eligible), "approved": False,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "metrics": report, "walk_forward": walk,
                "partitions": {name: {"start": str(part.open_time.min()), "end": str(part.open_time.max()),
                                      "target_end": str(part.target_time.max()), "rows": len(part)}
                               for name, part in [("train", train), ("validation", validation), ("test", test)]},
                "direction_definition": "Actual absolute return > 0.0001; predicted zero counts as a miss.",
                "gate": "At least 200 validation/test rows; >5% MAE and RMSE improvement in validation, test and all training-only walk-forward folds.",
                "hyperparameters": candidates[selected].get_params(),
                "period_test_metrics": [metrics(part.target_next_return, candidates[selected].predict(part[FEATURES]))
                                        for indices in np.array_split(np.arange(len(test)), 3)
                                        if len(indices) for part in [test.iloc[indices]]]}
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    print("Saved candidate:", folder, "Eligible:", eligible, "Promotion remains explicit.")
    return folder


def promote(folder):
    folder = Path(folder).resolve()
    if not folder.is_relative_to((ROOT / "models").resolve()):
        raise ValueError("Only local models/ artifacts may be promoted.")
    metadata = json.loads((folder / "metadata.json").read_text())
    if not metadata["eligible"] or metadata["product"] != "XRP-USDC":
        raise ValueError("Candidate failed validation; promotion denied.")
    comparison = metadata["metrics"].get("incumbent_comparison")
    if comparison and (comparison["unseen_rows"] < 200 or any(
        comparison["candidate"][metric] >= comparison["incumbent"][metric] for metric in ("mae", "rmse")
    )):
        raise ValueError("Candidate does not convincingly improve the incumbent on new held-out data.")
    artifact = folder / "model.joblib"
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError("Artifact checksum mismatch.")
    pointer = ROOT / "models/approved.json"
    temporary = pointer.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"directory": str(folder), "version": metadata["version"]}), encoding="utf-8")
    temporary.replace(pointer)
    print("Explicitly promoted:", metadata["version"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["train", "promote"])
    parser.add_argument("--directory")
    args = parser.parse_args()
    if args.command == "train":
        train()
    else:
        if not args.directory:
            parser.error("promote requires --directory")
        promote(args.directory)
