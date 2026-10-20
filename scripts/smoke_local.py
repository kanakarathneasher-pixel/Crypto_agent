"""Verify the running Next.js proxy and FastAPI using disposable QA accounts."""
import json
from pathlib import Path
import secrets
import time
import requests

base = 'http://localhost:3000'
session = requests.Session()
session.headers.update({'X-Requested-With':'CryptoAgent', 'Origin':base})
response = session.get(base, timeout=15)
response.raise_for_status()
assert 'Orbit' in response.text
username = 'qa_' + secrets.token_hex(6)
password = secrets.token_urlsafe(24)
response = session.post(base+'/api/auth/register', json={'username':username,'password':password}, timeout=15)
assert response.status_code == 201, response.text
checks = {}
for path in ['/health','/auth/me','/market/latest','/market/history','/predictions/latest','/agent/status',
             '/agent/settings','/trades/paper','/portfolio/paper','/performance/paper','/decisions']:
    result = session.get(base+'/api'+path,timeout=15)
    assert result.status_code == 200, (path,result.text)
    checks[path] = result.json()
assert checks['/market/latest']['price'] is not None
assert checks['/market/history']
assert checks['/predictions/latest']['model']['validated'] is False
assert session.post(base+'/api/agent/start',timeout=15).status_code == 200
for _ in range(40):
    status = session.get(base+'/api/agent/status',timeout=15).json()
    if status['last_cycle']:
        break
    time.sleep(1)
assert status['last_cycle']['action'] == 'HOLD', status
assert session.post(base+'/api/agent/stop',timeout=15).json()['running'] is False
assert session.get(base+'/api/trades/paper',timeout=15).json() == []
assert session.post(base+'/api/chat',json={'message':'Why did my agent hold?'},timeout=15).json()['configured'] is False
checks['autonomous_cycle'] = status['last_cycle']
assert session.post(base+'/api/auth/logout',timeout=15).status_code == 200
assert session.get(base+'/api/portfolio/paper',timeout=15).status_code == 401
folder = Path('.qa')
folder.mkdir(exist_ok=True)
(folder/'smoke_results.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
print('PASS: production Next.js proxy, authenticated API, public market refresh, autonomous HOLD, stop, chat fallback and logout.')
