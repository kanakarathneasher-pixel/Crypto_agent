
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

# STEP 1: Locate files
BASE_DIR = Path(__file__).resolve().parent

DATA_FILE = BASE_DIR / "data" / "processed" / "xrp_features.csv"
MODEL_FILE = BASE_DIR / "models" / "xrp_random_forest.joblib"

# STEP 2: Load features
df = pd.read_csv(DATA_FILE, parse_dates=["open_time"])
df = df.sort_values("open_time").reset_index(drop=True)

features = [
    "return_1h",
    "return_3h",
    "return_6h",
    "sma_6",
    "sma_24",
    "rsi_14",
    "volatility_24h",
    "volume_change"
]

target = "target_next_return"

X = df[features]
y = df[target]

# STEP 3: Split chronologically
# 70% training, 15% validation, 15% testing
n = len(df)

train_end = int(n * 0.70)
val_end = int(n * 0.85)

# Leave a one-row gap between partitions because
# each target uses the next hour's closing price.
X_train = X.iloc[:train_end - 1]
y_train = y.iloc[:train_end - 1]

X_val = X.iloc[train_end:val_end - 1]
y_val = y.iloc[train_end:val_end - 1]

X_test = X.iloc[val_end:]
y_test = y.iloc[val_end:]

print("Training samples:", len(X_train))
print("Validation samples:", len(X_val))
print("Testing samples:", len(X_test))

# STEP 4: Create model
model = RandomForestRegressor(
    n_estimators=200,
    max_depth=5,
    min_samples_leaf=5,
    random_state=42,
    n_jobs=-1
)

# STEP 5: Train model
print("\nTraining Random Forest...")
model.fit(X_train, y_train)

# STEP 6: Evaluate model
def evaluate(name, X_part, y_part):
    predictions = model.predict(X_part)

    mae = mean_absolute_error(y_part, predictions)
    rmse = np.sqrt(mean_squared_error(y_part, predictions))

    # Simple baseline: predict no price change
    baseline = np.zeros(len(y_part))
    baseline_mae = mean_absolute_error(y_part, baseline)

    print(f"\n{name} results:")
    print(f"Model MAE: {mae:.6f}")
    print(f"Model RMSE: {rmse:.6f}")
    print(f"Zero-return baseline MAE: {baseline_mae:.6f}")

    if mae < baseline_mae:
        print("Model beats zero-return baseline on MAE.")
    else:
        print("Model does NOT beat zero-return baseline on MAE.")

    return predictions

evaluate("Validation", X_val, y_val)
test_predictions = evaluate("Test", X_test, y_test)

# STEP 7: Display example predictions
results = pd.DataFrame({
    "actual_return": y_test.to_numpy(),
    "predicted_return": test_predictions
})

print("\nFirst 10 test predictions:")
print(results.head(10).to_string(index=False))

# STEP 8: Save model
MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)

joblib.dump(
    {"model": model, "features": features},
    MODEL_FILE
)

print("\nModel saved to:", MODEL_FILE)
