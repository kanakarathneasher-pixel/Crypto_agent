from datetime import datetime, timezone, timedelta
from decimal import InvalidOperation
from unittest.mock import Mock
import pytest
from backend.xrp_chart import PublicTicker, candle_points, history
from tests.test_backend import database, client


def test_chart_candles_sorted_deduplicated_and_no_gap_fill():
    values = [{'start':'0','close':'1'}, {'start':'120','close':'2'},
              {'start':'120','close':'2.1'}, {'start':'180','close':'3'}]
    assert candle_points(values, 0, 180, 60) == [
        {'time':60000,'price':'1'}, {'time':180000,'price':'2.1'}]
    with pytest.raises(ValueError): candle_points([{'start':'0','close':'NaN'}],0,180,60)


def test_public_feed_filters_product_stale_and_duplicate_ticks():
    feed = PublicTicker()
    now = datetime.now(timezone.utc)
    def message(sequence, product='XRP-USD', price='1.2', stamp=now):
        return {'channel':'ticker','timestamp':stamp.isoformat(),'sequence_num':sequence,
                'events':[{'tickers':[{'product_id':product,'price':price}]}]}
    feed.accept(message(1), now)
    assert feed.latest['price'] == '1.2'
    feed.accept(message(1, price='9'), now)
    feed.accept(message(2, product='BTC-USD', price='99'), now)
    feed.accept(message(3, price='8', stamp=now-timedelta(minutes=5)), now)
    assert feed.latest['price'] == '1.2'
    assert feed.snapshot()['fresh'] is False  # A disconnected feed is never live.
    with feed.lock: feed.connected = True
    assert feed.snapshot()['fresh']
    with pytest.raises(ValueError): feed.accept(message(4, price='NaN'), now)


def test_chart_api_auth_history_cache_and_product_separation(client, monkeypatch):
    monkeypatch.setattr('backend.xrp_chart._cache', {})
    now = 1800000000
    end = now//300*300
    fetch = Mock(return_value={'candles':[{'start':str(end-300),'close':'1.25'}]})
    monkeypatch.setattr('backend.xrp_chart.request_json', fetch)
    first = history('1D', now)
    assert history('1D', now) == first
    assert fetch.call_count == 1
    assert first['product'] == 'XRP-USD' and not first['website_identical']
    assert fetch.call_args.kwargs['params']['limit'] == 300
    assert client.get('/market/chart/latest').json()['product'] == 'XRP-USD'
    assert client.get('/market/chart/history?period=INVALID').status_code == 422
    client.post('/auth/logout')
    assert client.get('/market/chart/latest').status_code == 401
    assert client.get('/market/chart/history').status_code == 401
