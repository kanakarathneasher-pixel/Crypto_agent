"""Exercise the aggregate endpoint with two distinct, persisted accounts."""
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import config
from tests.test_backend import database


def test_dashboard_requires_session(database):
    with TestClient(app) as browser:
        assert browser.get('/dashboard').status_code == 401


def test_dashboard_matches_existing_views_and_isolates_accounts(database, monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'model_path', str(tmp_path / 'unapproved.json'))
    headers={'X-Requested-With': 'CryptoAgent'}
    with TestClient(app, headers=headers) as alice, TestClient(app, headers=headers) as bob:
        assert alice.post('/auth/register', json={'username':'alice','password':'long-test-password'}).status_code == 201
        assert bob.post('/auth/register', json={'username':'bob','password':'another-long-password'}).status_code == 201
        assert alice.put('/agent/settings', json={'manual_size_usdc':'17'}).status_code == 200
        result=alice.get('/dashboard')
        assert result.status_code == 200
        assert result.headers['cache-control'] == 'no-store'
        snapshot=result.json()
        for key, path in [('portfolio','/portfolio/paper'),('settings','/agent/settings'),
                          ('trades','/trades/paper'),('decisions','/decisions')]:
            assert snapshot[key] == alice.get(path).json()
        assert float(snapshot['settings']['manual_size_usdc']) == 17
        assert float(bob.get('/dashboard').json()['settings']['manual_size_usdc']) == 10
        assert snapshot['model']['model']['validated'] is False
        for secret in ['password_hash','token_hash','exchange_secret_reference']:
            assert secret not in result.text


def test_returning_account_keeps_workspace_and_identity(database):
    with TestClient(app, headers={'X-Requested-With':'CryptoAgent'}) as browser:
        created=browser.post('/auth/register', json={'username':'returning','password':'long-test-password'}).json()
        browser.put('/agent/settings', json={'manual_size_usdc':'19'})
        browser.post('/auth/logout')
        assert browser.get('/dashboard').status_code == 401
        logged_in=browser.post('/auth/login', json={'username':'returning','password':'long-test-password'}).json()
        assert logged_in == created
        assert logged_in['guest'] is False
        assert browser.get('/auth/me').json() == created
        assert float(browser.get('/dashboard').json()['settings']['manual_size_usdc']) == 19
