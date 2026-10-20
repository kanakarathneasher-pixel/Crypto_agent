
from pathlib import Path
import pandas as pd

# STEP 1: Locate project folders
BASE_DIR = Path(__file__).resolve().parent.parent

RAW_FILE = (
    BASE_DIR / "data" / "raw" /
    "XRPUSDT-1h-2026-09.csv"
)

OUTPUT_FILE = (
    BASE_DIR / "data" / "processed" /
    "xrp_cleaned.csv"
)

# STEP 2: Define column names
columns = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore"
]

# STEP 3: Load raw dataset
df = pd.read_csv(
    RAW_FILE,
    header=None,
    names=columns
)

print("Original dataset shape:", df.shape)

# STEP 4: Convert timestamps
df["open_time"] = pd.to_datetime(
    df["open_time"],
    unit="us",
    utc=True,
    errors="coerce"
)

# STEP 5: Convert price/volume columns
numeric_columns = [
    "open", "high", "low",
    "close", "volume",
    "quote_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume"
]

for column in numeric_columns:
    df[column] = pd.to_numeric(
        df[column],
        errors="coerce"
    )

# STEP 6: Remove duplicate timestamps
df = df.drop_duplicates(
    subset=["open_time"],
    keep="first"
)

# STEP 7: Remove missing essential values
essential_columns = [
    "open_time", "open", "high",
    "low", "close", "volume"
]

df = df.dropna(subset=essential_columns)

# STEP 8: Remove invalid market records
valid_prices = (
    (df["open"] > 0) &
    (df["high"] > 0) &
    (df["low"] > 0) &
    (df["close"] > 0)
)

valid_candles = (
    (df["high"] >= df[["open", "close", "low"]].max(axis=1)) &
    (df["low"] <= df[["open", "close", "high"]].min(axis=1))
)

valid_volume = df["volume"] >= 0

df = df[
    valid_prices &
    valid_candles &
    valid_volume
].copy()

# STEP 9: Sort chronologically
df = df.sort_values("open_time")
df = df.reset_index(drop=True)

# STEP 10: Check for missing hourly candles
time_differences = df["open_time"].diff()
missing_hours = (
    time_differences > pd.Timedelta(hours=1)
).sum()

print("Detected gaps between hourly candles:", missing_hours)

# STEP 11: Save cleaned dataset
OUTPUT_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)

df.to_csv(OUTPUT_FILE, index=False)

print("\nPreprocessing completed!")
print("Cleaned dataset shape:", df.shape)
print("Missing values in essential columns:")
print(df[essential_columns].isnull().sum())
print("Saved to:", OUTPUT_FILE)
