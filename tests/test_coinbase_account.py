"""Private Coinbase connection isolation and read-only boundaries; no real keys/network."""
from unittest.mock import Mock

import jwt
import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.coinbase_account import ReadOnlyCoinbase, connection_reference
from backend.config import config
from backend.main import app
from backend.models import AgentSettings
from tests.test_backend import database, client


@pytest.fixture
def keys(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    monkeypatch.setattr(config, 'coinbase_readonly_private_key', pem)
    monkeypatch.setattr(config, 'coinbase_readonly_key_name', 'organizations/test/apiKeys/test')
    return key


def account(value='1.25000000', held='0.25'):
    return {'currency': 'XRP', 'name': 'XRP Wallet', 'available_balance': {'value': value}, 'hold': {'value': held}}


def response(data, status=200):
    return Mock(status_code=status, json=Mock(return_value=data))


def test_get_only_jwt_bound_to_coinbase_resource(keys):
    session = Mock()
    session.get.return_value = response({'can_view': True, 'can_trade': False, 'can_transfer': False})
    client = ReadOnlyCoinbase(session)
    client.verify_permissions()
    args, kwargs = session.get.call_args
    assert args == ('https://api.coinbase.com/api/v3/brokerage/key_permissions',)
    assert kwargs['allow_redirects'] is False
    claims = jwt.decode(kwargs['headers']['Authorization'].split()[1], keys.public_key(), algorithms=['ES256'])
    assert claims['uri'] == 'GET api.coinbase.com/api/v3/brokerage/key_permissions'
    assert claims['exp'] - claims['nbf'] == 120
    with pytest.raises(ValueError):
        client.get('/orders')
    assert session.get.call_count == 1


@pytest.mark.parametrize('permissions', [
    {'can_view': True, 'can_trade': True, 'can_transfer': False},
    {'can_view': True, 'can_trade': False, 'can_transfer': True},
    {'can_view': True}, {}, {'can_view': False, 'can_trade': False, 'can_transfer': False},
])
def test_write_or_incomplete_permissions_fail_closed(permissions):
    api = ReadOnlyCoinbase(Mock())
    api.get = Mock(return_value=permissions)
    with pytest.raises(HTTPException) as error:
        api.holdings()
    assert error.value.status_code == 409
    api.get.assert_called_once_with('/key_permissions')


def test_paginated_exact_balances():
    api = ReadOnlyCoinbase(Mock())
    api.get = Mock(side_effect=[
        {'can_view': True, 'can_trade': False, 'can_transfer': False},
        {'accounts': [account()], 'has_next': True, 'cursor': 'next-page'},
        {'accounts': [account('0', '0')], 'has_next': False},
    ])
    result = api.holdings()
    assert result['accounts'][0]['total'] == '1.50000000'
    assert result['accounts'][1]['total'] == '0'
    assert result['access'] == 'read_only'
    assert api.get.call_args_list[-1].args[1]['cursor'] == 'next-page'


@pytest.mark.parametrize('data', [
    {'accounts': [account('NaN')], 'has_next': False},
    {'accounts': [account('-1')], 'has_next': False},
    {'accounts': [account()], 'has_next': True},
    {'accounts': 'invalid', 'has_next': False}, {'accounts': [account()]},
])
def test_incomplete_balances_are_not_displayed(data):
    api = ReadOnlyCoinbase(Mock())
    api.verify_permissions = Mock()
    api.get = Mock(return_value=data)
    with pytest.raises(HTTPException) as error:
        api.holdings()
    assert error.value.status_code == 502


def test_repeated_cursor_is_rejected():
    api = ReadOnlyCoinbase(Mock())
    api.verify_permissions = Mock()
    api.get = Mock(return_value={'accounts': [account()], 'has_next': True, 'cursor': 'repeat'})
    with pytest.raises(HTTPException):
        api.holdings()
    assert api.get.call_count == 2


def test_errors_do_not_expose_credentials_or_provider_body(keys):
    session = Mock()
    session.get.return_value = response({'secret': 'do-not-display'}, 403)
    api = ReadOnlyCoinbase(session)
    with pytest.raises(HTTPException) as error:
        api.get('/accounts')
    assert 'do-not-display' not in error.value.detail
    session.get.side_effect = requests.ConnectionError('Authorization: secret')
    with pytest.raises(HTTPException) as error:
        api.get('/accounts')
    assert 'secret' not in error.value.detail


def test_owner_connect_disconnect_and_isolation(client, database, keys, monkeypatch):
    owner = client.get('/auth/me').json()['id']
    monkeypatch.setattr(config, 'coinbase_readonly_owner_user_id', owner)
    fetch = Mock(return_value={'accounts': [], 'updated_at': 'test', 'access': 'read_only'})
    monkeypatch.setattr(ReadOnlyCoinbase, 'holdings', fetch)
    assert client.get('/connections/coinbase/portfolio').status_code == 409
    assert client.post('/connections/coinbase/connect', headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/connections/coinbase/connect', headers={'X-Requested-With':''}).status_code == 403
    assert client.post('/connections/coinbase/connect').status_code == 200
    assert client.get('/connections/coinbase').json()['connected']
    assert client.get('/connections/coinbase/portfolio').status_code == 200
    assert not config.live_execution_enabled
    with database() as db:
        reference = db.get(AgentSettings, owner).exchange_secret_reference
        assert reference == connection_reference()
        assert config.coinbase_readonly_key_name not in reference
    with TestClient(app, headers={'X-Requested-With': 'CryptoAgent'}) as other:
        assert other.get('/connections/coinbase').status_code == 401
        other.post('/auth/guest')
        assert not other.get('/connections/coinbase').json()['connected']
        assert other.post('/connections/coinbase/connect').status_code == 403
        assert other.get('/connections/coinbase/portfolio').status_code == 403
        other.post('/auth/register', json={'username':'other-owner','password':'other-test-password'})
        assert other.get('/connections/coinbase/portfolio').status_code == 403
    assert fetch.call_count == 2
    monkeypatch.setattr(config, 'coinbase_readonly_key_name', 'rotated-key')
    assert not client.get('/connections/coinbase').json()['connected']
    assert client.get('/connections/coinbase/portfolio').status_code == 409
    assert client.post('/connections/coinbase/disconnect').status_code == 200
    with database() as db:
        assert db.get(AgentSettings, owner).exchange_secret_reference is None


def test_failed_validation_does_not_connect(client, keys, monkeypatch):
    monkeypatch.setattr(config, 'coinbase_readonly_owner_user_id', client.get('/auth/me').json()['id'])
    monkeypatch.setattr(ReadOnlyCoinbase, 'holdings', Mock(side_effect=HTTPException(409, 'View-only required')))
    assert client.post('/connections/coinbase/connect').status_code == 409
    assert not client.get('/connections/coinbase').json()['connected']
