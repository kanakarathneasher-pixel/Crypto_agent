"""Supabase email auth with mocked provider responses and disposable SQLite."""
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.config import config
from backend.main import app
from backend.models import AuthSession, SupabaseIdentity, User
from tests.test_backend import database

SUBJECT = '11111111-1111-4111-8111-111111111111'
EMAIL = 'person@example.test'
PASSWORD = 'strong-test-password'


def reply(status=200, **body):
    return httpx.Response(status, json=body)


def verified(subject=SUBJECT, email=EMAIL):
    return reply(id=subject, email=email, email_confirmed_at='2026-11-01T00:00:00Z', is_anonymous=False)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(config, 'supabase_url', 'https://orbit-test.supabase.co')
    monkeypatch.setattr(config, 'supabase_publishable_key', 'sb_publishable_test')
    request = Mock()
    monkeypatch.setattr('backend.supabase_auth.httpx.request', request)
    return request


def browser():
    return TestClient(app, headers={'X-Requested-With': 'CryptoAgent'})


def test_registration_waits_for_confirmation_without_local_account(database, provider):
    provider.return_value = reply(id=SUBJECT, email=EMAIL)
    with browser() as client:
        response = client.post('/auth/email/register', json={'email': ' Person@example.test ', 'password': PASSWORD})
        assert response.status_code == 201
        assert response.json()['requires_confirmation']
        assert 'crypto_session' not in client.cookies
        assert client.get('/auth/me').status_code == 401
    assert provider.call_count == 1
    assert provider.call_args.kwargs['json'] == {'email': EMAIL, 'password': PASSWORD}
    with database() as db:
        assert db.scalar(select(func.count(User.id))) == 0


def test_login_returns_same_account_and_keeps_password_out_of_orbit(database, provider):
    provider.side_effect = [reply(access_token='provider-token'), verified()] * 2
    with browser() as client:
        login = client.post('/auth/email/login', json={'email': EMAIL, 'password': PASSWORD})
        assert login.status_code == 200
        owner = login.json()
        assert owner['email'] == EMAIL and not owner['guest']
        assert client.get('/auth/me').json() == owner
        assert 'HttpOnly' in login.headers['set-cookie']
        assert 'provider-token' not in login.text + login.headers['set-cookie']
        assert client.get('/dashboard').status_code == 200
        assert client.post('/auth/logout').status_code == 200
        assert client.get('/auth/me').status_code == 401
        assert client.post('/auth/email/login', json={'email': EMAIL, 'password': PASSWORD}).json() == owner
    assert provider.call_args.kwargs['headers']['Authorization'] == 'Bearer provider-token'
    with database() as db:
        assert db.scalar(select(func.count(User.id))) == 1
        assert db.scalar(select(User)).password_hash == '!supabase'
        assert db.get(SupabaseIdentity, SUBJECT).user_id == owner['id']


def test_signup_with_auto_confirmation_opens_verified_workspace(database, provider):
    provider.side_effect = [reply(access_token='provider-token'), verified()]
    with browser() as client:
        result = client.post('/auth/email/register', json={'email': EMAIL, 'password': PASSWORD})
        assert result.status_code == 201 and result.json()['email'] == EMAIL
        assert client.get('/auth/me').json() == result.json()


def test_wrong_password_and_confirmation_errors_do_not_open_sessions(database, provider):
    with browser() as client:
        for code, message in [('invalid_credentials', 'Incorrect email or password.'),
                              ('email_not_confirmed', 'Confirm your email')]:
            provider.return_value = reply(400, error_code=code, msg='internal provider detail')
            result = client.post('/auth/email/login', json={'email': EMAIL, 'password': PASSWORD})
            assert result.status_code == 401 and message in result.json()['detail']
            assert 'internal provider detail' not in result.text
            assert 'crypto_session' not in client.cookies


@pytest.mark.parametrize('changes', [{'id':'not-a-uuid'}, {'email_confirmed_at':None},
                                   {'is_anonymous':True}, {'email':None}])
def test_unverified_provider_identity_is_rejected(database, provider, changes):
    identity = verified().json()
    identity.update(changes)
    provider.side_effect = [reply(access_token='provider-token'), reply(**identity)]
    with browser() as client:
        result = client.post('/auth/email/login', json={'email': EMAIL, 'password': PASSWORD})
        assert result.status_code == 401
        assert client.get('/auth/me').status_code == 401
    with database() as db:
        assert db.scalar(select(func.count(User.id))) == 0


def test_distinct_supabase_subjects_keep_workspaces_separate(database, provider):
    provider.side_effect = [reply(access_token='one'), verified(), reply(access_token='two'),
                           verified('22222222-2222-4222-8222-222222222222', 'other@example.test')]
    with browser() as first, browser() as second:
        owner = first.post('/auth/email/login', json={'email':EMAIL, 'password':PASSWORD}).json()
        assert first.put('/agent/settings', json={'manual_size_usdc':'13'}).status_code == 200
        other = second.post('/auth/email/login', json={'email':'other@example.test', 'password':PASSWORD}).json()
        assert owner['id'] != other['id']
        assert float(second.get('/agent/settings').json()['manual_size_usdc']) == 10
        assert float(first.get('/agent/settings').json()['manual_size_usdc']) == 13


def test_login_rotates_and_revokes_previous_orbit_session(database, provider):
    provider.side_effect = [reply(access_token='one'), verified()] * 2
    with browser() as client:
        body = {'email':EMAIL, 'password':PASSWORD}
        client.post('/auth/email/login', json=body)
        previous = client.cookies.get('crypto_session')
        client.post('/auth/email/login', json=body)
        assert client.cookies.get('crypto_session') != previous
    with database() as db:
        assert db.scalar(select(func.count(AuthSession.token_hash))) == 1


def test_missing_configuration_and_provider_timeout_fail_closed(database, provider, monkeypatch):
    with browser() as client:
        monkeypatch.setattr(config, 'supabase_publishable_key', '')
        body = {'email':EMAIL, 'password':PASSWORD}
        assert client.post('/auth/email/login', json=body).status_code == 503
        provider.assert_not_called()
        monkeypatch.setattr(config, 'supabase_publishable_key', 'sb_publishable_test')
        provider.side_effect = httpx.ReadTimeout('private provider details')
        result = client.post('/auth/email/login', json=body)
        assert result.status_code == 503 and 'private provider details' not in result.text
        assert provider.call_count == 1  # No automatic credential replay.
        assert 'crypto_session' not in client.cookies


@pytest.mark.parametrize('body', [{'email':'invalid', 'password':PASSWORD},
                                {'email':EMAIL, 'password':'short'},
                                {'email':EMAIL, 'password':PASSWORD, 'user_id':1}])
def test_invalid_credentials_never_reach_provider(database, provider, body):
    with browser() as client:
        assert client.post('/auth/email/login', json=body).status_code == 422
    provider.assert_not_called()
