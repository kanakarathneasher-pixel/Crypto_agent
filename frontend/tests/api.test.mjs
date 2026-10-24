import {test} from 'node:test';
import assert from 'node:assert/strict';
import {requestJson} from '../lib/api.ts';

test('plain-text proxy 500 gives an actionable error instead of a JSON exception', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response('Internal Server Error', {status:500});
  try {
    await assert.rejects(requestJson('/auth/guest','POST'), /backend is running on port 8000/);
  } finally {globalThis.fetch = original;}
});

test('JSON validation errors retain the API explanation', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({detail:'Session expired'}), {status:401});
  try {
    await assert.rejects(requestJson('/v2/agent/status'), /Session expired/);
  } finally {globalThis.fetch = original;}
});

test('guest request retains session cookies and CSRF header', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/auth/guest');
    assert.equal(options.credentials, 'include');
    assert.equal(options.headers['X-Requested-With'], 'CryptoAgent');
    assert.equal(options.method, 'POST');
    return new Response(JSON.stringify({guest:true}));
  };
  try {assert.deepEqual(await requestJson('/auth/guest','POST'), {guest:true});}
  finally {globalThis.fetch = original;}
});

test('successful HTML response is rejected without exposing its content', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response('<html>Private traceback</html>');
  try {await assert.rejects(requestJson('/agent/status'), /returned an invalid response/);}
  finally {globalThis.fetch = original;}
});

test('hosted 404 points to Vercel configuration instead of local port instructions', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  globalThis.window = {location:{hostname:'dashboard.vercel.app'}};
  globalThis.fetch = async () => new Response(JSON.stringify({detail:'Not Found'}), {status:404});
  try {await assert.rejects(requestJson('/auth/guest','POST'), /Check BACKEND_URL in Vercel/);}
  finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
