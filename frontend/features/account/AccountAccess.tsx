'use client';
import {useState} from 'react';
import {requestJson as api} from '../../lib/api';
import type {OrbitUser} from '../../lib/workspace';

export default function AccountAccess({user}:{user:OrbitUser}) {
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  async function logout() {
    setBusy(true);setError('');
    try {await api('/auth/logout','POST');window.location.reload();}
    catch(error) {setError((error as Error).message);setBusy(false);}
  }
  return <section className="panel settings-panel">
    <div className="panel-heading"><div><h3>Your Orbit account</h3>
      <p>Your settings and paper history are saved to your account.</p>
    </div><span className="pill quiet">SIGNED IN</span></div>
    {error&&<p className="error" role="alert">{error}</p>}
    <div className="account-identity"><strong>{user.email||user.username}</strong><button className="secondary" disabled={busy} onClick={logout}>{busy?'Signing out...':'Sign out'}</button></div>
  </section>;
}
