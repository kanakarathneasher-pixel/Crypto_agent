import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resolveBackendOrigin} from '../lib/backend-origin.mjs';

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
