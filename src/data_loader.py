
from pathlib import Path
import pandas as pd

# STEP 1: Find our XRP CSV file
BASE_DIR = Path(__file__).resolve().parent.parent
FILE_PATH = BASE_DIR / "data" / "raw" / "XRPUSDT-1h-2026-09.csv"

# STEP 2: Give names to the CSV columns
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

# STEP 3: Load the CSV
df = pd.read_csv(
    FILE_PATH,
    header=None,
    names=columns
)

# STEP 4: Convert timestamps into dates
df["open_time"] = pd.to_datetime(
    df["open_time"],
    unit="us",
    utc=True
)

# STEP 5: Display dataset information
print("\n===== XRP DATASET =====")

print("\nFirst 5 rows:")
print(df.head())

print("\nTotal rows and columns:")
print(df.shape)

print("\nColumn names:")
print(df.columns.tolist())

print("\nMissing values:")
print(df.isnull().sum())

print("\nDate range:")
print(df["open_time"].min())
print(df["open_time"].max())
