"""Google sign-in security with synthetic tokens; no Google network requests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from backend.config import config
from backend.google_auth import google_keys
from backend.main import app
from backend.models import GoogleIdentity, GoogleLoginChallenge, User
from tests.test_backend import database, client


@pytest.fixture(scope='module')
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def google(monkeypatch, signing_key):
    monkeypatch.setattr(config, 'google_client_id', 'orbit-test.apps.googleusercontent.com')
    monkeypatch.setattr(google_keys, 'get_signing_key_from_jwt', Mock(return_value=SimpleNamespace(key=signing_key.public_key())))
    return signing_key


def credential(browser, key, **changes):
    response = browser.post('/auth/google/challenge')
    assert response.status_code == 200, response.text
    claims = {'sub':'synthetic-google-subject', 'email':'synthetic@example.test', 'email_verified':True,
              'iss':'https://accounts.google.com', 'aud':config.google_client_id,
              'iat':int(time.time()), 'exp':int(time.time())+300, 'nonce':response.json()['nonce']}
    claims.update(changes)
    return jwt.encode(claims, key, algorithm='RS256', headers={'kid':'test-key'})


def test_unconfigured_and_unauthenticated(database, monkeypatch):
    monkeypatch.setattr(config, 'google_client_id', '')
    with TestClient(app, headers={'X-Requested-With':'CryptoAgent'}) as browser:
        assert browser.get('/auth/google/config').status_code == 401
        browser.post('/auth/guest')
        assert not browser.get('/auth/google/config').json()['enabled']
        assert browser.post('/auth/google/challenge').status_code == 503


def test_signup_then_google_login_reuses_identity(database, google):
    with TestClient(app, headers={'X-Requested-With':'CryptoAgent'}) as browser:
        guest = browser.post('/auth/guest').json()['id']
        old_session = browser.cookies.get('crypto_session')
        token = credential(browser, google)
        result = browser.post('/auth/google', json={'credential':token})
        assert result.status_code == 200, result.text
        owner = result.json()['id']
        assert owner != guest and not result.json()['guest']
        assert browser.cookies.get('crypto_session') != old_session
        assert 'HttpOnly' in result.headers['set-cookie']
        assert browser.cookies.get('orbit_google_challenge') is None
        assert browser.get('/portfolio/paper').status_code == 200
        assert browser.get('/auth/google/config').json()['linked']
        browser.post('/auth/logout')
        browser.post('/auth/guest')
        token = credential(browser, google, email='updated@example.test')
        assert browser.post('/auth/google',json={'credential':token}).json()['id'] == owner
        assert browser.get('/auth/google/config').json()['email'] == 'updated@example.test'
        with database() as db:
            assert db.scalar(select(func.count(GoogleIdentity.subject))) == 1
            assert db.get(User,owner).password_hash == '!google'


def test_link_preserves_existing_owner_and_password_login(client, database, google):
    owner = client.get('/auth/me').json()['id']
    token = credential(client, google)
    result = client.post('/auth/google',json={'credential':token})
    assert result.status_code == 200 and result.json()['id'] == owner
    with database() as db:
        assert db.get(GoogleIdentity,'synthetic-google-subject').user_id == owner
    client.post('/auth/logout')
    assert client.post('/auth/login',json={'username':'alice','password':'long-test-password'}).json()['id'] == owner


@pytest.mark.parametrize('changes', [
    {'aud':'another-app'}, {'iss':'https://evil.example'}, {'exp':1},
    {'email_verified':False}, {'nonce':'wrong-browser'}, {'sub':''},
    {'azp':'another-app'}, {'iat':int(time.time())+86400},
    {'aud':['orbit-test.apps.googleusercontent.com','another-app']},
])
def test_invalid_identity_is_rejected_without_linking(client, database, google, changes):
    token = credential(client, google, **changes)
    result = client.post('/auth/google',json={'credential':token})
    assert result.status_code == 401
    assert not client.get('/auth/google/config').json()['linked']
    with database() as db:
        assert db.scalar(select(func.count(GoogleIdentity.subject))) == 0


def test_signature_and_algorithm_are_verified(client, google):
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = credential(client, wrong_key)
    assert client.post('/auth/google',json={'credential':token}).status_code == 401
    token = credential(client, google)
    claims = jwt.decode(token, options={'verify_signature':False})
    token = jwt.encode(claims, 'synthetic-invalid-key-that-is-long-enough',algorithm='HS256')
    assert client.post('/auth/google',json={'credential':token}).status_code == 401


def test_browser_binding_expiration_replay_and_csrf(client, database, google):
    token = credential(client, google)
    challenge_cookie = client.cookies.get('orbit_google_challenge')
    with TestClient(app, headers={'X-Requested-With':'CryptoAgent'}) as other:
        other.post('/auth/guest')
        other.cookies.set('orbit_google_challenge',challenge_cookie)
        assert other.post('/auth/google',json={'credential':token}).status_code == 401
    assert client.post('/auth/google',json={'credential':token},headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/auth/google',json={'credential':token},headers={'X-Requested-With':''}).status_code == 403
    assert client.post('/auth/google',json={'credential':token}).status_code == 200
    client.cookies.set('orbit_google_challenge',challenge_cookie)
    assert client.post('/auth/google',json={'credential':token}).status_code == 401
    token = credential(client, google)
    with database.begin() as db:
        db.scalar(select(GoogleLoginChallenge)).expires_at = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    assert client.post('/auth/google',json={'credential':token}).status_code == 401


def test_cannot_link_another_owners_google_account(client, database, google):
    owner = client.get('/auth/me').json()['id']
    assert client.post('/auth/google',json={'credential':credential(client,google)}).status_code == 200
    assert client.post('/auth/google',json={'credential':credential(client,google,sub='second-google-account')}).status_code == 409
    client.post('/auth/logout')
    second = client.post('/auth/register',json={'username':'bob','password':'another-long-test-password'}).json()['id']
    assert second != owner
    assert client.post('/auth/google',json={'credential':credential(client,google)}).status_code == 409
    assert client.get('/auth/me').json()['id'] == second


def test_google_key_fetch_failure_is_safe(client, google, monkeypatch):
    token = credential(client, google)
    monkeypatch.setattr(google_keys,'get_signing_key_from_jwt',Mock(side_effect=jwt.PyJWKClientConnectionError('secret internal detail')))
    result = client.post('/auth/google',json={'credential':token})
    assert result.status_code == 503 and 'secret' not in result.text
