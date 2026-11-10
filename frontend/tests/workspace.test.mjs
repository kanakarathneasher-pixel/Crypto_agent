import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError} from '../lib/api.ts';
import {connectWorkspace} from '../lib/workspace.ts';

test('cold backend readiness is retried before restoring the existing session',async()=>{
  const calls=[],progress=[];
  let healthCalls=0;
  const user={id:3,username:'returning',guest:false};
  const result=await connectWorkspace(message=>progress.push(message),async(path,method='GET')=>{
    calls.push([path,method]);
    if(path==='/health' && healthCalls++<2) throw new ApiError('timeout',504);
    return path==='/health'?{status:'ok'}:user;
  },async()=>{});
  assert.deepEqual(result,user);
  assert.deepEqual(calls,[['/health','GET'],['/health','GET'],['/health','GET'],['/auth/me','GET']]);
  assert.ok(progress.some(message=>message.includes('Waking')));
});

test('configuration and authorization failures are not retried',async()=>{
  for(const status of [401,403,404,503]) {
    let calls=0;
    await assert.rejects(connectWorkspace(()=>{},async()=>{calls++;throw new ApiError('configuration',status);},async()=>{}),/configuration/);
    assert.equal(calls,1);
  }
});

test('session restoration is not replayed after a timeout',async()=>{
  let posts=0;
  await assert.rejects(connectWorkspace(()=>{},async(path)=>{
    if(path==='/health') return {status:'ok'};
    posts++;throw new ApiError('timeout after sending',504);
  },async()=>{}),/timeout after sending/);
  assert.equal(posts,1);
});

test('signed-out and guest sessions show sign-in without creating accounts',async()=>{
  for(const guest of [false,true]) {
    const calls=[];
    const user=await connectWorkspace(()=>{},async(path,method='GET')=>{
      calls.push([path,method]);
      if(path==='/health') return {status:'ok'};
      if(!guest) throw new ApiError('Sign in required.',401);
      return {id:1,username:'guest_existing',guest:true};
    });
    assert.equal(user,null);
    assert.deepEqual(calls,[['/health','GET'],['/auth/me','GET']]);
  }
});

test('unavailable backend eventually stops without creating an account',async()=>{
  let calls=0;
  await assert.rejects(connectWorkspace(()=>{},async(path)=>{
    assert.equal(path,'/health');calls++;throw new ApiError('unavailable',502);
  },async()=>{}),/unavailable/);
  assert.equal(calls,5);
});
