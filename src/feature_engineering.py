
from pathlib import Path
import numpy as np
import pandas as pd

# STEP 1: Locate our files
BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = (
    BASE_DIR / "data" / "processed" / "xrp_cleaned.csv"
)

OUTPUT_FILE = (
    BASE_DIR / "data" / "processed" / "xrp_features.csv"
)

# STEP 2: Load cleaned dataset
df = pd.read_csv(INPUT_FILE, parse_dates=["open_time"])

df = df.sort_values("open_time").reset_index(drop=True)

print("Loaded cleaned XRP data:", df.shape)

# STEP 3: Calculate hourly returns
df["return_1h"] = df["close"].pct_change(1)
df["return_3h"] = df["close"].pct_change(3)
df["return_6h"] = df["close"].pct_change(6)

# STEP 4: Calculate moving averages
df["sma_6"] = df["close"].rolling(6).mean()
df["sma_24"] = df["close"].rolling(24).mean()

# STEP 5: Calculate RSI (14 periods)
price_change = df["close"].diff()

gain = price_change.clip(lower=0)
loss = -price_change.clip(upper=0)

avg_gain = gain.ewm(
    alpha=1/14,
    adjust=False,
    min_periods=14
).mean()

avg_loss = loss.ewm(
    alpha=1/14,
    adjust=False,
    min_periods=14
).mean()

rs = avg_gain / avg_loss.replace(0, np.nan)

df["rsi_14"] = 100 - (100 / (1 + rs))

# Handle periods with no losses
df.loc[(avg_loss == 0) & (avg_gain > 0), "rsi_14"] = 100

# Handle periods with no gains or losses
df.loc[(avg_loss == 0) & (avg_gain == 0), "rsi_14"] = 50

# STEP 6: Calculate volatility
df["volatility_24h"] = (
    df["return_1h"].rolling(24).std()
)

# STEP 7: Calculate volume changes
df["volume_change"] = (
    df["volume"].pct_change()
)

# STEP 8: Create prediction target
# Tomorrow? No — our target is the NEXT HOUR.
df["target_next_return"] = (
    df["close"].shift(-1) / df["close"] - 1
)

# STEP 9: Remove missing and infinite feature values
df = df.replace([np.inf, -np.inf], np.nan)

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

df = df.dropna(
    subset=features + ["target_next_return"]
).copy()

# STEP 10: Save feature dataset
df.to_csv(OUTPUT_FILE, index=False)

print("\nFeature engineering completed!")
print("Final dataset shape:", df.shape)

print("\nFeatures created:")
print(df[features].head())

print("\nTarget preview:")
print(df["target_next_return"].head())

print("\nSaved to:", OUTPUT_FILE)
