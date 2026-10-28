'use client';
import {type FormEvent, useState} from 'react';
import {requestJson as api} from '../../lib/api';
import type {OrbitUser} from '../../lib/workspace';
import GoogleSignIn from './GoogleSignIn';

export default function AccountAccess({user}:{user:OrbitUser}) {
  const [register,setRegister]=useState(false);
  const [username,setUsername]=useState('');
  const [password,setPassword]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');

  async function authenticate(event:FormEvent) {
    event.preventDefault();setBusy(true);setError('');
    try {
      await api(register?'/auth/register':'/auth/login','POST',{username,password});
      setPassword('');window.location.reload();
    } catch(error) {setError((error as Error).message);setBusy(false);}
  }
  async function logout() {
    setBusy(true);setError('');
    try {await api('/auth/logout','POST');window.location.reload();}
    catch(error) {setError((error as Error).message);setBusy(false);}
  }
  return <section className="panel settings-panel">
    <div className="panel-heading"><div><h3>Your Orbit account</h3>
      <p>{user.guest?'Sign in to return to your saved workspace on any device.':'Your settings and paper history are saved to your account.'}</p>
    </div><span className="pill quiet">{user.guest?'GUEST':'SIGNED IN'}</span></div>
    {error&&<p className="error" role="alert">{error}</p>}
    <GoogleSignIn guest={user.guest}/>
    {user.guest?<>
      <div className="account-tabs" role="group" aria-label="Orbit account access">
        <button className={!register?'primary':'secondary'} aria-pressed={!register} disabled={busy} onClick={()=>{setRegister(false);setError('');}}>Sign in</button>
        <button className={register?'primary':'secondary'} aria-pressed={register} disabled={busy} onClick={()=>{setRegister(true);setError('');}}>Create account</button>
      </div>
      <form className="account-form" onSubmit={authenticate}>
        <label>Orbit username<input autoComplete="username" required minLength={3} maxLength={80} pattern="[a-zA-Z0-9_.\-]+" value={username} onChange={event=>setUsername(event.target.value)}/></label>
        <label>Orbit password<input type="password" autoComplete={register?'new-password':'current-password'} required minLength={12} maxLength={128} value={password} onChange={event=>setPassword(event.target.value)}/></label>
        <p>{register?'Choose a password of at least 12 characters. Your new account starts with a separate paper portfolio.':'Use your existing Orbit username and password.'}</p>
        <button className="primary" disabled={busy}>{busy?'Please wait…':register?'Create Orbit account':'Sign in to Orbit'}</button>
      </form>
    </>:<div className="account-identity"><div><strong>{user.username}</strong><p>Orbit user ID: {user.id}</p></div><button className="secondary" disabled={busy} onClick={logout}>Sign out</button></div>}
  </section>;
}
