"""Display-only XRP-USD chart. Never supplies candles or prices to the strategy.

Coinbase's website is not embeddable. This reconstructs an explicitly labelled
exchange reference chart; it does not claim the website's aggregate price series.
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import logging
import threading
import time
from typing import Literal
import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from backend.auth import current_user
from backend.database import SessionLocal
from backend.models import AuthSession
from src.coinbase_data_loader import request_json

log = logging.getLogger(__name__)
PRODUCT = 'XRP-USD'
RANGES = {'1H': (3600, 60, 'ONE_MINUTE'), '1D': (86400, 300, 'FIVE_MINUTE'),
          '1W': (604800, 3600, 'ONE_HOUR'), '1M': (2592000, 21600, 'SIX_HOUR')}
router = APIRouter(prefix='/market/chart', tags=['Display-only Coinbase XRP-USD chart'])
_cache = {}
_cache_lock = threading.Lock()


def candle_points(candles, start, end, step):
    """Use actual completed closes. Never fill empty price intervals."""
    points = {}
    for candle in candles:
        stamp = int(candle['start'])
        price = Decimal(candle['close'])
        if not price.is_finite() or price <= 0:
            raise ValueError('Invalid Coinbase chart price.')
        if start <= stamp and stamp+step <= end:
            points[stamp+step] = {'time': (stamp+step)*1000, 'price': str(price)}
    return [points[stamp] for stamp in sorted(points)]


def history(period, now=None):
    now = int(now if now is not None else time.time())
    duration, step, granularity = RANGES[period]
    end = now//step*step
    key = (period, end)
    with _cache_lock:
        if key in _cache:
            return _cache[key]
        with requests.Session() as session:
            result = request_json(session, f'https://api.coinbase.com/api/v3/brokerage/market/products/{PRODUCT}/candles',
                params={'start': str(end-duration), 'end': str(end), 'granularity': granularity, 'limit': 300})
        points = candle_points(result['candles'], end-duration, end, step)
        if not points:
            raise ValueError('Coinbase returned no chart history.')
        payload = {'product': PRODUCT, 'currency': 'USD', 'period': period, 'interval_seconds': step,
            'points': points, 'source': 'Coinbase Advanced Trade', 'website_identical': False,
            'original_url': 'https://www.coinbase.com/price/xrp'}
        # At most one cached response for each of four ranges.
        for old in list(_cache):
            if old[0] == period: del _cache[old]
        _cache[key] = payload
        return payload


class PublicTicker:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.connection = None
        self.latest = None
        self.connected = False
        self.sequence = None

    def accept(self, message, now=None):
        if message.get('channel') != 'ticker': return
        stamp = datetime.fromisoformat(message['timestamp'].replace('Z', '+00:00'))
        if stamp.tzinfo is None: raise ValueError('Missing chart timestamp timezone.')
        now = now or datetime.now(timezone.utc)
        if not -5 <= (now-stamp).total_seconds() <= 30:
            return  # Never present an old snapshot or future tick as live.
        sequence = message.get('sequence_num')
        with self.lock:
            if self.sequence is not None and sequence is not None and sequence <= self.sequence: return
            self.sequence = sequence
            for event in message.get('events', []):
                for ticker in event.get('tickers', []):
                    if ticker.get('product_id') != PRODUCT: continue
                    price = Decimal(ticker['price'])
                    if not price.is_finite() or price <= 0: raise ValueError('Invalid live chart price.')
                    point = {'time': int(stamp.timestamp()*1000), 'price': str(price)}
                    if self.latest is None or point['time'] >= self.latest['time']:
                        self.latest = point

    def snapshot(self):
        with self.lock:
            point = self.latest.copy() if self.latest else None
            fresh = point is not None and 0 <= time.time()-point['time']/1000 <= 15
            return {'product': PRODUCT, 'currency': 'USD', 'point': point,
                    'connected': self.connected, 'fresh': bool(fresh and self.connected)}

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, daemon=True, name='public-xrp-chart')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.connection:
            self.connection.close()
        if self.thread: self.thread.join(timeout=2)

    def run(self):
        import websocket
        delay = 1
        while not self.stop_event.is_set():
            try:
                self.connection = websocket.create_connection('wss://advanced-trade-ws.coinbase.com', timeout=10)
                with self.lock: self.sequence = None
                for channel in ('ticker', 'heartbeats'):
                    self.connection.send(json.dumps({'type': 'subscribe', 'channel': channel, 'product_ids': [PRODUCT]}))
                delay = 1
                while not self.stop_event.is_set():
                    message = json.loads(self.connection.recv())
                    if message.get('channel') == 'ticker':
                        self.accept(message)
                        with self.lock: self.connected = True
            except Exception:
                log.warning('Public XRP chart disconnected; reconnecting with backoff.')
            finally:
                with self.lock: self.connected = False
                if self.connection: self.connection.close()
                self.connection = None
            self.stop_event.wait(delay)
            delay = min(delay*2, 30)


ticker = PublicTicker()


@router.get('/history')
def chart_history(period: Literal['1H', '1D', '1W', '1M'] = '1D', user=Depends(current_user)):
    try:
        return history(period)
    except (requests.RequestException, ValueError, KeyError, ArithmeticError):
        raise HTTPException(503, 'Coinbase chart history is temporarily unavailable.') from None


@router.get('/latest')
def latest(user=Depends(current_user)):
    return ticker.snapshot()


@router.get('/events')
async def chart_events(request: Request, user=Depends(current_user)):
    user_id = user.id
    token_hash = hashlib.sha256(request.cookies.get('crypto_session', '').encode()).hexdigest()
    async def stream():
        previous = None
        while not await request.is_disconnected():
            with SessionLocal() as db:
                record = db.get(AuthSession, token_hash)
                if not record or record.user_id != user_id or datetime.fromisoformat(record.expires_at) <= datetime.now(timezone.utc):
                    break
            data = json.dumps(ticker.snapshot())
            if data != previous:
                yield 'event: price\ndata: '+data+'\n\n'
                previous = data
            else:
                yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type='text/event-stream',
        headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'})
