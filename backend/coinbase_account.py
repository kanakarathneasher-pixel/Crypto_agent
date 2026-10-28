"""Owner-only Coinbase balance connection. Credentials stay in backend environment.

This client has no order/transfer methods and rejects keys with write permissions.
The persisted connection reference is bound to the configured key fingerprint.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import secrets
import time

import jwt
import requests
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from fastapi import APIRouter, Depends, HTTPException, Request

from backend.auth import current_user, is_guest, rate_limit
from backend.config import config
from backend.database import session_dependency
from backend.models import AgentSettings

router = APIRouter(prefix='/connections/coinbase', tags=['Coinbase read-only account'])
PREFIX = '/api/v3/brokerage'


def configured():
    return bool(config.coinbase_readonly_owner_user_id and config.coinbase_readonly_key_name
                and config.coinbase_readonly_private_key)


def connection_reference():
    fingerprint = hashlib.sha256((config.coinbase_readonly_key_name + '\0' +
                                 config.coinbase_readonly_private_key).encode()).hexdigest()
    return 'env:coinbase-readonly:' + fingerprint


def require_owner(user):
    if is_guest(user) or user.id != config.coinbase_readonly_owner_user_id:
        raise HTTPException(403, 'This test connection is available only to the configured Orbit owner.')
    if not configured():
        raise HTTPException(409, 'Configure the read-only Coinbase credentials in the backend first.')


class ReadOnlyCoinbase:
    def __init__(self, session=None):
        self.session = session or requests

    def get(self, resource, params=None):
        # No caller-controlled URL, method or resource is accepted by the HTTP API.
        if resource not in {'/accounts', '/key_permissions'}:
            raise ValueError('Unsupported read-only resource')
        try:
            key = load_pem_private_key(config.coinbase_readonly_private_key.replace('\\n', '\n').encode(), password=None)
            if not isinstance(key, EllipticCurvePrivateKey) or key.curve.name != 'secp256r1':
                raise ValueError('ECDSA P-256 required')
            stamp = int(time.time())
            path = PREFIX + resource
            token = jwt.encode({'sub': config.coinbase_readonly_key_name, 'iss': 'cdp', 'nbf': stamp,
                                'exp': stamp + 120, 'uri': 'GET api.coinbase.com' + path}, key,
                               algorithm='ES256', headers={'kid': config.coinbase_readonly_key_name,
                                                          'nonce': secrets.token_hex()})
        except (ValueError, TypeError, jwt.PyJWTError):
            raise HTTPException(409, 'The backend needs a valid Coinbase ECDSA (ES256) API key.') from None
        try:
            response = self.session.get('https://api.coinbase.com' + path, params=params,
                                        headers={'Authorization': 'Bearer ' + token},
                                        timeout=(3, 8), allow_redirects=False)
            if response.status_code in {401, 403}:
                raise HTTPException(502, 'Coinbase rejected the key. Check its permissions, portfolio and IP restrictions.')
            if response.status_code != 200:
                raise HTTPException(502, 'Coinbase is unavailable. Try refreshing later.')
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError('Invalid response')
            return result
        except (requests.RequestException, ValueError):
            # Never expose provider bodies, request headers, credentials or tracebacks.
            raise HTTPException(502, 'Unable to read Coinbase. Check connectivity and try again.') from None

    def verify_permissions(self):
        permissions = self.get('/key_permissions')
        if (permissions.get('can_view') is not True or permissions.get('can_trade') is not False
                or permissions.get('can_transfer') is not False):
            raise HTTPException(409, 'Use a View-only Coinbase key. Trade and Transfer permissions must be disabled.')

    def holdings(self):
        self.verify_permissions()
        rows, cursors, cursor = [], set(), None
        for _ in range(20):
            data = self.get('/accounts', {'limit': 250, **({'cursor': cursor} if cursor else {})})
            try:
                accounts = data['accounts']
                if not isinstance(accounts, list) or not isinstance(data.get('has_next'), bool):
                    raise ValueError('Invalid pagination')
                for account in accounts:
                    if account.get('active') is False:
                        continue
                    currency = account['currency']
                    available = Decimal(account['available_balance']['value'])
                    held = Decimal(account['hold']['value'])
                    if not all(v.is_finite() and v >= 0 for v in (available, held)):
                        raise ValueError('Invalid balance')
                    rows.append({'currency': currency, 'name': account.get('name', currency),
                                 'available': str(available), 'held': str(held), 'total': str(available + held)})
                if not data['has_next']:
                    return {'accounts': rows, 'updated_at': datetime.now(timezone.utc).isoformat(),
                            'access': 'read_only', 'source': 'Coinbase', 'scope': 'API-key accessible portfolios'}
                cursor = data.get('cursor')
                if not isinstance(cursor, str) or not cursor or cursor in cursors:
                    raise ValueError('Invalid cursor')
                cursors.add(cursor)
            except (KeyError, TypeError, AttributeError, InvalidOperation, ValueError):
                raise HTTPException(502, 'Coinbase returned incomplete balances. No partial portfolio is displayed.') from None
        raise HTTPException(502, 'Coinbase pagination limit reached. No partial portfolio is displayed.')


@router.get('')
def status(user=Depends(current_user), db=Depends(session_dependency)):
    eligible = not is_guest(user) and user.id == config.coinbase_readonly_owner_user_id
    ready = configured() if eligible else False
    settings = db.get(AgentSettings, user.id)
    return {'eligible': eligible, 'configured': ready,
            'connected': bool(ready and settings and settings.exchange_secret_reference == connection_reference()),
            'access': 'read_only'}


@router.post('/connect')
def connect(request: Request, user=Depends(current_user), db=Depends(session_dependency)):
    require_owner(user)
    rate_limit(request, 'coinbase-account', 12)
    # Verify permissions and balances before marking this user as connected.
    portfolio = ReadOnlyCoinbase().holdings()
    db.get(AgentSettings, user.id).exchange_secret_reference = connection_reference()
    db.commit()
    return {'connected': True, 'portfolio': portfolio}


@router.get('/portfolio')
def portfolio(request: Request, user=Depends(current_user), db=Depends(session_dependency)):
    require_owner(user)
    settings = db.get(AgentSettings, user.id)
    if not settings or settings.exchange_secret_reference != connection_reference():
        raise HTTPException(409, 'Connect your Coinbase account first.')
    rate_limit(request, 'coinbase-account', 12)
    return ReadOnlyCoinbase().holdings()


@router.post('/disconnect')
def disconnect(user=Depends(current_user), db=Depends(session_dependency)):
    # Works even after the operator removes the credentials or changes the owner.
    settings = db.get(AgentSettings, user.id)
    if settings and (settings.exchange_secret_reference or '').startswith('env:coinbase-readonly:'):
        settings.exchange_secret_reference = None
        db.commit()
    return {'connected': False}
