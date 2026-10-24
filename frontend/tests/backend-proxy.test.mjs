import {test} from 'node:test';
import assert from 'node:assert/strict';
import {proxyBackend} from '../lib/backend-proxy.ts';
const env={VERCEL:'1',BACKEND_URL:'https://backend.example.com'};

test('a Vercel frontend can deploy without a backend and returns an actionable 503',async()=>{
  const response=await proxyBackend(new Request('https://dashboard.example/api/auth/guest',{method:'POST'}),['auth','guest'],{env:{VERCEL:'1'}});
  assert.equal(response.status,503);
  assert.match((await response.json()).detail,/Set BACKEND_URL/);
});

test('guest POST preserves body, CSRF, original origin and secure session cookies',async()=>{
  const request=new Request('https://dashboard.example/api/auth/guest',{method:'POST',
    headers:{origin:'https://dashboard.example','X-Requested-With':'CryptoAgent','content-type':'application/json',cookie:'crypto_session=browser-one'},
    body:'{}'});
  const response=await proxyBackend(request,['auth','guest'],{env,fetchImpl:async(url,options)=>{
    assert.equal(String(url),'https://backend.example.com/auth/guest');
    assert.equal(options.method,'POST');
    assert.equal(options.headers.get('origin'),'https://dashboard.example');
    assert.equal(options.headers.get('x-requested-with'),'CryptoAgent');
    assert.equal(options.headers.get('cookie'),'crypto_session=browser-one');
    assert.equal(new TextDecoder().decode(options.body),'{}');
    assert.equal(options.redirect,'manual');
    return Response.json({guest:true},{headers:{'Set-Cookie':'crypto_session=new-browser-session; HttpOnly; Secure; SameSite=Strict; Path=/'}});
  }});
  assert.equal(response.status,200);
  assert.match(response.headers.get('set-cookie'),/HttpOnly; Secure/);
  assert.equal(response.headers.get('cache-control'),'no-store');
});

test('cookies stay specific to each browser and query parameters are forwarded',async()=>{
  const seen=[];
  for(const cookie of ['session=one','session=two']) {
    const request=new Request('https://dashboard.example/api/trades/paper?limit=5',{headers:{cookie}});
    await proxyBackend(request,['trades','paper'],{env,fetchImpl:async(url,options)=>{
      assert.equal(new URL(url).search,'?limit=5');
      seen.push(options.headers.get('cookie'));
      return Response.json([]);
    }});
  }
  assert.deepEqual(seen,['session=one','session=two']);
});

test('SSE is streamed without buffering or forwarding internal headers',async()=>{
  const encoder=new TextEncoder();
  const stream=new ReadableStream({start(controller){controller.enqueue(encoder.encode('event: price\ndata: {}\n\n'));}});
  const response=await proxyBackend(new Request('https://dashboard.example/api/market/chart/events'),['market','chart','events'],{
    env,fetchImpl:async()=>new Response(stream,{headers:{'Content-Type':'text/event-stream','Server':'private-backend'}}),
  });
  assert.equal(response.headers.get('content-type'),'text/event-stream');
  assert.equal(response.headers.get('server'),null);
  const reader=response.body.getReader();
  assert.match(new TextDecoder().decode((await reader.read()).value),/event: price/);
  await reader.cancel();
});

test('unavailable backend, timeout, and redirects are controlled JSON responses',async()=>{
  const request=()=>new Request('https://dashboard.example/api/health');
  const offline=await proxyBackend(request(),['health'],{env,fetchImpl:async()=>{throw Error('private network details');}});
  assert.equal(offline.status,502);
  assert.doesNotMatch(JSON.stringify(await offline.json()),/private network/);
  const timeout=await proxyBackend(request(),['health'],{env,timeoutMs:1,fetchImpl:async(_,options)=>new Promise((_,reject)=>{
    options.signal.addEventListener('abort',()=>reject(Error('timeout')),{once:true});
  })});
  assert.equal(timeout.status,504);
  const redirect=await proxyBackend(request(),['health'],{env,fetchImpl:async()=>new Response(null,{status:302,headers:{location:'https://unexpected.example'}})});
  assert.equal(redirect.status,502);
});

test('backend authorization failures are preserved and invalid paths are rejected',async()=>{
  const unauthorized=await proxyBackend(new Request('https://dashboard.example/api/agent/status'),['agent','status'],{
    env,fetchImpl:async()=>Response.json({detail:'Session expired'},{status:401}),
  });
  assert.equal(unauthorized.status,401);
  const invalid=await proxyBackend(new Request('https://dashboard.example/api/health'),['..','health'],{env});
  assert.equal(invalid.status,400);
  const oversized=await proxyBackend(new Request('https://dashboard.example/api/chat',{method:'POST',body:'x'.repeat(65537)}),['chat'],{env});
  assert.equal(oversized.status,413);
});
