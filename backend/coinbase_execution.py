"""Coinbase spot REST and user stream. All live writes require an operator gate.

Uses ES256 CDP JWTs, not legacy Exchange HMAC. No transfer endpoints exist here.
"""
from decimal import Decimal
import json
import secrets
import threading
import time
from urllib.parse import quote
import requests
from backend.config import config

D = Decimal
BASE = 'https://api.coinbase.com'
SANDBOX = 'https://api-sandbox.coinbase.com'
PREFIX = '/api/v3/brokerage'


class ExchangeUnavailable(RuntimeError):
    pass


class AmbiguousSubmission(ExchangeUnavailable):
    pass


def normalize_order(order, fills):
    states = {'OPEN': 'ACCEPTED', 'PENDING': 'ACCEPTED', 'FILLED': 'FILLED',
              'CANCELLED': 'CANCELLED', 'EXPIRED': 'CANCELLED', 'FAILED': 'REJECTED',
              'CANCEL_QUEUED': 'CANCEL_PENDING'}
    result = {'state': states.get(order.get('status'), 'UNKNOWN'), 'id': order.get('order_id'), 'fills': []}
    for f in fills:
        price, size = D(str(f['price'])), D(str(f['size']))
        if f.get('size_in_quote'):
            size /= price
        # Coinbase's spot fills commission is denominated in the quote currency.
        result['fills'].append({'trade_id': str(f.get('entry_id') or f['trade_id']),
            'quantity': size, 'price': price, 'fee': D(str(f['commission']))})
    if result['state'] == 'ACCEPTED' and result['fills']:
        result['state'] = 'PARTIALLY_FILLED'
    if D(str(order.get('filled_size', '0'))) > sum((f['quantity'] for f in result['fills']), D(0)):
        # Fill reporting may lag order status, including a terminal cancellation.
        result['state'] = 'UNKNOWN'
    return result


class CoinbaseLive:
    """One backend owner's key, explicitly bound to one local user identity."""
    mode = 'live'

    def __init__(self, user_id, session=None):
        if user_id != config.live_owner_user_id:
            raise ExchangeUnavailable('LIVE_ACCOUNT_NOT_BOUND_TO_USER')
        self.user_id = user_id
        self.session = session or requests.Session()

    def token(self, method=None, path=None):
        import jwt
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
        name, pem = config.coinbase_key_name, config.coinbase_private_key.replace('\\n', '\n')
        if not name or not pem:
            raise ExchangeUnavailable('COINBASE_CREDENTIALS_MISSING')
        try:
            key = load_pem_private_key(pem.encode(), password=None)
            if not isinstance(key, EllipticCurvePrivateKey) or key.curve.name != 'secp256r1':
                raise ValueError('ES256 P-256 key required')
            stamp = int(time.time())
            payload = {'sub': name, 'iss': 'cdp', 'nbf': stamp, 'exp': stamp+120}
            if method:
                payload['uri'] = f'{method} api.coinbase.com{path}'
            return jwt.encode(payload, key, algorithm='ES256', headers={'kid': name, 'nonce': secrets.token_hex()})
        except (ValueError, TypeError) as error:
            raise ExchangeUnavailable('INVALID_ES256_KEY') from None

    def request(self, method, path, body=None, params=None):
        if method != 'GET' and not config.live_execution_enabled:
            raise ExchangeUnavailable('LIVE_EXECUTION_DISABLED')
        for attempt in range(3 if method == 'GET' else 1):
            try:
                response = self.session.request(method, BASE+path, json=body, params=params,
                    headers={'Authorization': 'Bearer '+self.token(method, path)}, timeout=(5, 15))
                if response.status_code in (408, 429) or response.status_code >= 500:
                    if method != 'GET':
                        raise AmbiguousSubmission('MUTATION_OUTCOME_UNKNOWN')
                    delay = max(2**attempt, float(response.headers.get('Retry-After', '0')))
                    if attempt == 2 or delay > 60:
                        raise ExchangeUnavailable('COINBASE_TEMPORARILY_UNAVAILABLE')
                    time.sleep(delay)
                    continue
                if response.status_code >= 400:
                    raise ExchangeUnavailable(f'COINBASE_HTTP_{response.status_code}')
                try:
                    return response.json()
                except ValueError:
                    if method != 'GET':
                        raise AmbiguousSubmission('INVALID_MUTATION_RESPONSE') from None
                    raise ExchangeUnavailable('INVALID_EXCHANGE_RESPONSE') from None
            except (requests.Timeout, requests.ConnectionError):
                if method != 'GET':
                    raise AmbiguousSubmission('MUTATION_OUTCOME_UNKNOWN') from None
                if attempt == 2:
                    raise ExchangeUnavailable('COINBASE_NETWORK_UNAVAILABLE') from None
                time.sleep(2**attempt)
        raise ExchangeUnavailable('COINBASE_UNAVAILABLE')

    def paged(self, resource, key, params=None):
        params = dict(params or {})
        rows, cursors = [], set()
        for _ in range(100):
            data = self.request('GET', PREFIX+resource, params=params)
            rows.extend(data.get(key, []))
            cursor = data.get('cursor')
            if not cursor or not data.get('has_next', bool(cursor)):
                return rows
            if cursor in cursors:
                raise ExchangeUnavailable('REPEATED_CURSOR')
            cursors.add(cursor)
            params['cursor'] = cursor
        raise ExchangeUnavailable('PAGINATION_LIMIT')

    def readiness(self):
        permissions = self.request('GET', PREFIX+'/key_permissions')
        if not permissions.get('can_view') or not permissions.get('can_trade') or permissions.get('can_transfer', True):
            raise ExchangeUnavailable('KEY_REQUIRES_VIEW_TRADE_WITHOUT_TRANSFER')
        accounts = self.paged('/accounts', 'accounts', {'limit': 250})
        balances = {}
        for a in accounts:
            if a.get('active') is False or a.get('ready') is False:
                continue
            currency = a['currency']
            balances[currency] = balances.get(currency, D(0)) + D(a['available_balance']['value'])
            balances[currency+'_total'] = balances.get(currency+'_total', D(0)) + D(a['available_balance']['value']) + D(a.get('hold', {}).get('value', '0'))
        if not all(c in balances for c in ('USDC', 'XRP')):
            raise ExchangeUnavailable('SPOT_ACCOUNTS_UNAVAILABLE')
        return balances

    def preview(self, order):
        payload = self.payload(order)
        payload.pop('client_order_id')
        result = self.request('POST', PREFIX+'/orders/preview', payload)
        if result.get('errs') or not result.get('preview_id'):
            raise ExchangeUnavailable('PREVIEW_REJECTED')
        return result

    @staticmethod
    def payload(order):
        return {'client_order_id': order['client_order_id'], 'product_id': 'XRP-USDC',
                'side': order['side'], 'order_configuration': {
                    'market_market_ioc': {'base_size': str(order['quantity'])}}}

    def submit(self, order, market, settings):
        # The service persisted the stable ID before this one and only POST.
        try:
            balances = self.readiness()
            required = order['quantity']*D(str(market['ask']))*(1+settings.slippage)*(1+settings.fee_rate)
            if ((order['side'] == 'BUY' and balances['USDC'] < required)
                    or (order['side'] == 'SELL' and balances['XRP'] < order['quantity'])):
                raise ExchangeUnavailable('INSUFFICIENT_EXCHANGE_AVAILABLE_BALANCE')
            preview = self.preview(order)
        except ExchangeUnavailable as error:
            # No create-order request was sent, so this outcome is definitive.
            return {'state': 'REJECTED', 'fills': [], 'reason_code': str(error)}
        payload = self.payload(order)
        payload['preview_id'] = preview['preview_id']
        response = self.request('POST', PREFIX+'/orders', payload)
        if not response.get('success'):
            return {'state': 'REJECTED', 'id': None, 'fills': []}
        return {'state': 'ACCEPTED', 'id': response['success_response']['order_id'], 'fills': []}

    def lookup(self, order, market, settings):
        exchange_id = order.get('exchange_order_id')
        if not exchange_id:
            orders = self.paged('/orders/historical/batch', 'orders', {'product_ids': ['XRP-USDC'], 'limit': 100})
            found = next((o for o in orders if o.get('client_order_id') == order['client_order_id']), None)
            if not found:
                # Absence is NOT permission to submit again after an ambiguous result.
                return {'state': 'UNKNOWN', 'id': None, 'fills': []}
            exchange_id = found['order_id']
        response = self.request('GET', PREFIX+'/orders/historical/'+quote(exchange_id, safe=''))
        fills = self.paged('/orders/historical/fills', 'fills', {'order_ids': [exchange_id], 'limit': 100})
        return normalize_order(response['order'], fills)

    def open_orders(self):
        return self.paged('/orders/historical/batch', 'orders', {'product_ids': ['XRP-USDC'], 'order_status': ['OPEN', 'PENDING']})

    def cancel(self, order):
        if not order.get('exchange_order_id'):
            return False
        result = self.request('POST', PREFIX+'/orders/batch_cancel', {'order_ids': [order['exchange_order_id']]})
        return any(r.get('success') for r in result.get('results', []))


class UserOrderStream:
    """A stream hint wakes REST reconciliation; stream messages never book fills."""
    def __init__(self, exchange, wake, stop):
        self.exchange, self.wake, self.stop = exchange, wake, stop

    def run(self):
        import websocket
        delay = 1
        while not self.stop.is_set():
            connection = None
            try:
                connection = websocket.create_connection('wss://advanced-trade-ws-user.coinbase.com', timeout=10)
                for channel in ('user', 'heartbeats'):
                    connection.send(json.dumps({'type': 'subscribe', 'channel': channel,
                        'product_ids': ['XRP-USDC'], 'jwt': self.exchange.token()}))
                self.wake.set()  # Reconnect always requires a complete REST reconciliation.
                last = None
                delay = 1
                while not self.stop.is_set():
                    message = json.loads(connection.recv())
                    if message.get('channel') == 'user':
                        sequence = message.get('sequence_num')
                        if last is None or sequence != last+1:
                            self.wake.set()
                        last = sequence
                        self.wake.set()
            except Exception:
                self.wake.set()
                self.stop.wait(delay)
                delay = min(60, delay*2)
            finally:
                if connection:
                    connection.close()
