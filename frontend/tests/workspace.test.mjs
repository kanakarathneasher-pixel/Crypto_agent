import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError} from '../lib/api.ts';
import {connectWorkspace} from '../lib/workspace.ts';

test('cold backend readiness is retried before exactly one guest request',async()=>{
  const calls=[],progress=[];
  let healthCalls=0;
  const user={id:3,username:'returning',guest:false};
  const result=await connectWorkspace(message=>progress.push(message),async(path,method='GET')=>{
    calls.push([path,method]);
    if(path==='/health' && healthCalls++<2) throw new ApiError('timeout',504);
    return path==='/health'?{status:'ok'}:user;
  },async()=>{});
  assert.deepEqual(result,user);
  assert.deepEqual(calls,[['/health','GET'],['/health','GET'],['/health','GET'],['/auth/guest','POST']]);
  assert.ok(progress.some(message=>message.includes('Waking')));
});

test('configuration and authorization failures are not retried',async()=>{
  for(const status of [401,403,404,503]) {
    let calls=0;
    await assert.rejects(connectWorkspace(()=>{},async()=>{calls++;throw new ApiError('configuration',status);},async()=>{}),/configuration/);
    assert.equal(calls,1);
  }
});

test('workspace creation is never replayed after an ambiguous timeout',async()=>{
  let posts=0;
  await assert.rejects(connectWorkspace(()=>{},async(path)=>{
    if(path==='/health') return {status:'ok'};
    posts++;throw new ApiError('timeout after sending',504);
  },async()=>{}),/timeout after sending/);
  assert.equal(posts,1);
});

test('unavailable backend eventually stops without creating an account',async()=>{
  let calls=0;
  await assert.rejects(connectWorkspace(()=>{},async(path)=>{
    assert.equal(path,'/health');calls++;throw new ApiError('unavailable',502);
  },async()=>{}),/unavailable/);
  assert.equal(calls,5);
});
