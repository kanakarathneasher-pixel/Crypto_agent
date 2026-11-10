'use client';
import {type FormEvent, useEffect, useState} from 'react';
import {requestJson as api} from '../../lib/api';

export default function SignInPage() {
  const [register,setRegister]=useState(false);
  const [email,setEmail]=useState('');
  const [password,setPassword]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');

  useEffect(()=>{
    // Confirmation fragments never authorize an Orbit session. Remove tokens
    // from the URL; the subsequent password login verifies with Supabase.
    const fragment=new URLSearchParams(window.location.hash.slice(1));
    if(fragment.has('access_token')||fragment.has('error')) {
      window.history.replaceState(null,'',window.location.pathname+window.location.search);
      if(fragment.has('error')) setError('The confirmation link is invalid or expired. Please try registering again.');
      else setNotice('Please sign in with your email and password to continue.');
    }
  },[]);

  async function authenticate(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(busy) return;
    setBusy(true);setError('');setNotice('');
    try {
      const result=await api(register?'/auth/email/register':'/auth/email/login','POST',{email:email.trim(),password});
      setPassword('');
      if(result.requires_confirmation) {
        setRegister(false);setNotice(result.message);setBusy(false);
      } else window.location.reload();
    } catch(error) {setError((error as Error).message);setBusy(false);}
  }

  return <main className="workspace-gate signin-page">
    <section className="panel signin-card" aria-labelledby="signin-title">
      <a className="brand" href="/" aria-label="Orbit home">
        <svg className="brand-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true">
          <circle cx="16" cy="16" r="12" stroke="currentColor" strokeWidth="5"/>
          <circle cx="24" cy="7" r="5" fill="currentColor" stroke="var(--panel)" strokeWidth="2"/>
        </svg>
        <span>orbit<span className="brand-dot">.</span></span>
      </a>
      <h1 id="signin-title">{register?'Create your account':'Welcome back'}</h1>
      <p>{register?'Your Orbit workspace starts here.':'Sign in to your Orbit account.'}</p>
      <form className="signin-form" onSubmit={authenticate} aria-busy={busy}>
        <fieldset disabled={busy}>
          <label htmlFor="orbit-email">Email</label>
          <input id="orbit-email" name="email" type="email" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={320} placeholder="you@example.com" value={email} onChange={event=>setEmail(event.target.value)}/>
          <label htmlFor="orbit-password">Password</label>
          <input id="orbit-password" name="password" type="password" autoComplete={register?'new-password':'current-password'} required minLength={8} maxLength={128} aria-describedby={register?'password-help':undefined} value={password} onChange={event=>setPassword(event.target.value)}/>
          {register&&<p id="password-help" className="signin-help">Use at least 8 characters.</p>}
          {error&&<p className="error" role="alert">{error}</p>}
          {notice&&<p className="notice" role="status">{notice}</p>}
          <button className="primary signin-submit" type="submit">{busy?'Please wait...':register?'Create account':'Sign in'}</button>
        </fieldset>
      </form>
      <p className="signin-switch">{register?'Already have an account?':'New to Orbit?'}{' '}
        <button type="button" className="text-button" disabled={busy} onClick={()=>{setRegister(!register);setPassword('');setError('');setNotice('');}}>{register?'Sign in':'Register'}</button>
      </p>
    </section>
  </main>;
}
