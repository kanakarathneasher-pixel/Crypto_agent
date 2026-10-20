"""Public market data only. No order endpoints or private-key support exist."""
from datetime import datetime, timezone
from decimal import Decimal
import requests
from src.coinbase_data_loader import fetch_candles, candles_frame, request_json, verify_product, HOUR
from src.coinbase_pipeline import clean_candles


def latest_market():
    now = datetime.now(timezone.utc)
    end = now.replace(minute=0, second=0, microsecond=0)
    with requests.Session() as session:
        product = verify_product(session)
        candles = fetch_candles(session, end - 300 * HOUR, end)
    frame, report = clean_candles(candles_frame(candles, end - 300 * HOUR, end))
    if report["invalid_rows"] or frame.empty:
        raise ValueError("Coinbase returned empty or invalid recent history.")
    price = Decimal(str(product["price"]))
    if not price.is_finite() or price <= 0:
        raise ValueError("Coinbase returned an invalid current price.")
    return {"product": "XRP-USDC", "price": price, "updated_at": now.isoformat(), "candles": frame}
