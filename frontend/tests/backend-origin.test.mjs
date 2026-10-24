import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resolveBackendOrigin} from '../lib/backend-origin.mjs';
import {spawnSync} from 'node:child_process';

test('local development retains the local Python backend', () => {
  assert.equal(resolveBackendOrigin({}), 'http://127.0.0.1:8000');
});
test('Vercel requires an explicitly deployed HTTPS backend', () => {
  assert.throws(()=>resolveBackendOrigin({VERCEL:'1'}), /Set BACKEND_URL/);
  for (const url of ['http://localhost:8000', 'https://127.0.0.1', 'http://backend.example.com']) {
    assert.throws(()=>resolveBackendOrigin({VERCEL:'1',BACKEND_URL:url}), /public HTTPS/);
  }
  assert.equal(resolveBackendOrigin({VERCEL:'1',BACKEND_URL:' https://backend.example.com/ '}), 'https://backend.example.com');
});
test('backend URL cannot accidentally include the frontend API prefix or credentials', () => {
  for (const url of ['example.com', 'https://example.com/api', 'https://user:secret@example.com', 'https://example.com?token=private']) {
    assert.throws(()=>resolveBackendOrigin({BACKEND_URL:url}));
  }
});

test('the real Next.js config uses the deployed backend in its rewrite', () => {
  const script = "import config from './next.config.ts'; console.log(JSON.stringify(await config.rewrites()));";
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], {
    cwd: new URL('../', import.meta.url),
    env: {...process.env, VERCEL:'1', BACKEND_URL:'https://backend.example.com'},
    encoding:'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  const rules = JSON.parse(result.stdout.trim());
  assert.deepEqual(rules, [{source:'/api/:path*', destination:'https://backend.example.com/:path*'}]);
});
