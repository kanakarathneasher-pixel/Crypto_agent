'use client';
import {useEffect, useRef, useState} from 'react';
import {requestJson as api} from '../../lib/api';

type GoogleConfig = {enabled:boolean; client_id:string; linked:boolean; email:string|null};
type Identity = {
  initialize(options:{client_id:string; nonce:string; auto_select:boolean; ux_mode:string; callback:(result:{credential:string})=>void}):void;
  renderButton(element:HTMLElement, options:{theme:string; size:string; shape:string; text:string; width:number}):void;
  cancel():void;
};
declare global {interface Window {google?:{accounts:{id:Identity}}}}
let sdkLoading:Promise<void>|null=null;
function loadGoogle() {
  if(window.google?.accounts.id) return Promise.resolve();
  if(!sdkLoading) sdkLoading=new Promise<void>((resolve,reject)=>{
    const script=document.createElement('script');
    script.src='https://accounts.google.com/gsi/client'; script.async=true;
    const timer=window.setTimeout(()=>{script.remove();sdkLoading=null;reject(new Error('Google sign-in did not load. Check your connection or browser blocking settings.'));},12000);
    script.onload=()=>{window.clearTimeout(timer);resolve();};
    script.onerror=()=>{window.clearTimeout(timer);script.remove();sdkLoading=null;reject(new Error('Google sign-in could not load. Please retry.'));};
    document.head.appendChild(script);
  });
  return sdkLoading;
}

export default function GoogleSignIn({guest}:{guest:boolean}) {
  const [config,setConfig]=useState<GoogleConfig|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [ready,setReady]=useState(false);
  const [attempt,setAttempt]=useState(0);
  const button=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    let active=true;
    let removeThemeListener:(()=>void)|undefined;
    const container=button.current;
    setError('');setReady(false);
    async function start() {
      try {
        const settings:GoogleConfig=await api('/auth/google/config');
        if(!active) return;
        setConfig(settings);
        if(!settings.enabled||settings.linked) return;
        await loadGoogle();
        if(!active) return;
        const challenge=await api('/auth/google/challenge','POST');
        if(!active||!container) return;
        const identity=window.google?.accounts.id;
        if(!identity) throw new Error('Google sign-in is unavailable. Please retry.');
        identity.initialize({client_id:settings.client_id,nonce:challenge.nonce,auto_select:false,ux_mode:'popup',callback:async result=>{
          if(!active) return;
          setBusy(true);setError('');
          try {
            await api('/auth/google','POST',{credential:result.credential});
            window.location.reload();
          } catch(e) {if(active) {setError((e as Error).message);setReady(false);setBusy(false);container.replaceChildren();}}
        }});
        const theme=window.matchMedia('(prefers-color-scheme: dark)');
        const render=()=>{container.replaceChildren();identity.renderButton(container,{theme:theme.matches?'filled_black':'outline',size:'large',shape:'pill',text:'continue_with',width:280});};
        render();
        theme.addEventListener('change',render);
        removeThemeListener=()=>theme.removeEventListener('change',render);
        setReady(true);
      } catch(e) {if(active) setError((e as Error).message);}
    }
    start();
    return ()=>{active=false;removeThemeListener?.();container?.replaceChildren();window.google?.accounts.id.cancel();};
  },[attempt]);

  return <div className="google-signin">
    <p className="google-heading">{config?.linked?'Google account connected':guest?'Sign in or join with Google':'Add Google sign-in to this Orbit account'}</p>
    {config?.linked?<p>{config.email}</p>:<>
      <div ref={button} className={busy?'google-button busy':'google-button'} aria-busy={busy}/>
      {!config&&!error&&<p role="status">Checking Google sign-in…</p>}
      {config?.enabled&&!ready&&!error&&<p role="status">Loading Google sign-in…</p>}
      {config&&!config.enabled&&<><button className="secondary" disabled>Continue with Google</button><p className="google-help">Google sign-in setup is pending. The server needs a Google Web application client ID.</p></>}
      {busy&&<p role="status">Verifying your Google account…</p>}
      {error&&<div className="error" role="alert">{error}<button className="text-button" disabled={busy} onClick={()=>setAttempt(value=>value+1)}>Try Google again</button></div>}
      {guest?<p className="google-help">Google verifies your identity. Orbit creates a personal account on your first sign-in.</p>:<p className="google-help">Linking keeps your existing Orbit account, balances and Coinbase connection.</p>}
    </>}
  </div>;
}
