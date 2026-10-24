"""Public market data only. No order endpoints or private-key support exist."""
from datetime import datetime, timezone
from decimal import Decimal
import requests
import time
from src.coinbase_data_loader import fetch_candles, candles_frame, request_json, verify_product, HOUR
from src.coinbase_pipeline import clean_candles

_history = None
_history_end = None
_history_checked = 0.0


def recent_history(session, end):
    """Reuse completed history between hourly boundaries; retry delayed candles."""
    global _history, _history_end, _history_checked
    if _history is not None and _history_end == end:
        latest = _history.open_time.iloc[-1].to_pydatetime()
        if latest == end-HOUR or time.monotonic()-_history_checked < 30:
            return _history.copy()
    candles = fetch_candles(session, end-300*HOUR, end)
    frame, report = clean_candles(candles_frame(candles, end-300*HOUR, end))
    if report['invalid_rows'] or frame.empty:
        raise ValueError('Coinbase returned empty or invalid recent history.')
    _history, _history_end, _history_checked = frame.copy(), end, time.monotonic()
    return frame


def latest_market():
    now = datetime.now(timezone.utc)
    end = now.replace(minute=0, second=0, microsecond=0)
    with requests.Session() as session:
        product = verify_product(session)
        frame = recent_history(session, end)
        book = request_json(session, 'https://api.coinbase.com/api/v3/brokerage/market/product_book',
                            params={'product_id': 'XRP-USDC', 'limit': 1})['pricebook']
        if book['product_id'] != 'XRP-USDC':
            raise ValueError('Unexpected book product.')
        bid, ask = Decimal(book['bids'][0]['price']), Decimal(book['asks'][0]['price'])
        if not bid.is_finite() or not ask.is_finite() or bid <= 0 or ask < bid:
            raise ValueError('Invalid Coinbase book.')
    price = Decimal(str(product["price"]))
    if not price.is_finite() or price <= 0:
        raise ValueError("Coinbase returned an invalid current price.")
    return {"product": "XRP-USDC", "price": price, "updated_at": book['time'], "candles": frame,
            'bid': bid, 'ask': ask,
            'base_increment': product['base_increment'], 'base_min_size': product['base_min_size'],
            'quote_min_size': product['quote_min_size'],
            'tradable': product.get('status', '').lower() == 'online' and not any(
                product.get(flag, False) for flag in ('trading_disabled', 'cancel_only', 'limit_only', 'post_only', 'view_only'))}
