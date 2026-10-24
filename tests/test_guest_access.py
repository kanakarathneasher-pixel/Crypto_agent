"""Direct dashboard entry still isolates browser sessions and forbids live access."""
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from backend.main import app
from backend.models import User, AuthSession
from backend.config import config
from tests.test_backend import database


def test_guest_direct_access_and_reuse(database):
    with TestClient(app, headers={'X-Requested-With':'CryptoAgent'}) as browser:
        response = browser.post('/auth/guest')
        assert response.status_code == 200 and response.json()['guest']
        assert 'HttpOnly' in response.headers['set-cookie']
        assert browser.get('/portfolio/paper').status_code == 200
        assert browser.put('/agent/settings', json={'manual_size_usdc':'17'}).status_code == 200
        assert browser.post('/auth/guest').json()['id'] == response.json()['id']
        with database() as db:
            assert db.scalar(select(func.count(User.id))) == 1
        assert browser.post('/v2/agent/commands', json={'action':'start','request_id':'test-start'}).status_code == 409
        assert browser.put('/v2/agent/configuration', json={'mode':'paper'}).status_code == 200


def test_guests_are_isolated_and_live_is_forbidden(database, monkeypatch):
    with TestClient(app, headers={'X-Requested-With':'CryptoAgent'}) as first, TestClient(app, headers={'X-Requested-With':'CryptoAgent'}) as second:
        a, b = first.post('/auth/guest').json(), second.post('/auth/guest').json()
        assert a['id'] != b['id']
        first.put('/agent/settings', json={'manual_size_usdc':'17'})
        assert float(second.get('/agent/settings').json()['manual_size_usdc']) == 10
        monkeypatch.setattr(config, 'live_execution_enabled', True)
        monkeypatch.setattr(config, 'live_owner_user_id', a['id'])
        assert first.put('/v2/agent/configuration', json={'mode':'live'}).status_code == 403
        assert first.post('/auth/guest', headers={'Origin':'https://evil.example'}).status_code == 403


def test_expired_guest_creates_separate_workspace(database):
    with TestClient(app, headers={'X-Requested-With':'CryptoAgent'}) as browser:
        original = browser.post('/auth/guest').json()['id']
        with database.begin() as db:
            db.scalar(select(AuthSession)).expires_at = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        assert browser.post('/auth/guest').json()['id'] != original
        with database() as db:
            assert db.scalar(select(func.count(User.id))) == 2
