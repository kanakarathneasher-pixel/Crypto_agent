'use client';
import {FormEvent, useEffect, useState} from 'react';
import {requestJson as api} from '../lib/api';
import GoogleSignIn from './GoogleSignIn';

type Status = {eligible:boolean; configured:boolean; connected:boolean};
type Portfolio = {accounts:{currency:string; name:string; available:string; held:string; total:string}[]; updated_at:string; scope:string};

export default function CoinbaseAccount({user}:{user:Record<string, any>}) {
  const [status,setStatus] = useState<Status|null>(null);
  const [portfolio,setPortfolio] = useState<Portfolio|null>(null);
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const [register,setRegister] = useState(true);
  const [username,setUsername] = useState('');
  const [password,setPassword] = useState('');

  useEffect(()=>{
    let active=true;
    api('/connections/coinbase').then(async value=>{
      if(!active) return;
      setStatus(value);
      if(value.connected) {
        const balances=await api('/connections/coinbase/portfolio');
        if(active) setPortfolio(balances);
      }
    }).catch(e=>{if(active) setError(e.message);});
    return ()=>{active=false;};
  },[]);

  async function authenticate(event:FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await api(register?'/auth/register':'/auth/login','POST',{username,password});
      setPassword(''); window.location.reload();
    } catch(e) {setError((e as Error).message);setBusy(false);}
  }
  async function connection(action:'connect'|'disconnect'|'refresh') {
    setBusy(true); setError(''); setPortfolio(null);
    try {
      if(action==='refresh') setPortfolio(await api('/connections/coinbase/portfolio'));
      else {
        const result=await api(`/connections/coinbase/${action}`,'POST');
        setStatus(previous=>previous?{...previous,connected:result.connected}:previous);
        if(result.portfolio) setPortfolio(result.portfolio);
      }
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function logout() {
    setBusy(true); setError(''); setPortfolio(null);
    try {await api('/auth/logout','POST');window.location.reload();}
    catch(e) {setError((e as Error).message);setBusy(false);}
  }

  return <div className="account-page">
    {error&&<div className="error" role="alert">{error}<button className="text-button" onClick={()=>window.location.reload()}>Retry</button></div>}
    <section className="panel settings-panel">
      <div className="panel-heading"><div><h3>Your Orbit account</h3><p>A personal sign-in keeps your Coinbase connection separate from guest workspaces.</p></div><span className="pill quiet">{user.guest?'GUEST':'SIGNED IN'}</span></div>
      <GoogleSignIn guest={Boolean(user.guest)}/>
      {user.guest?<>
        <div className="account-tabs" role="group" aria-label="Orbit account access">
          <button className={register?'primary':'secondary'} aria-pressed={register} disabled={busy} onClick={()=>{setRegister(true);setError('');}}>Create account</button>
          <button className={!register?'primary':'secondary'} aria-pressed={!register} disabled={busy} onClick={()=>{setRegister(false);setError('');}}>Sign in</button>
        </div>
        <form className="account-form" onSubmit={authenticate}>
          <label>Orbit username<input autoComplete="username" required minLength={3} maxLength={80} pattern="[a-zA-Z0-9_.\-]+" value={username} onChange={e=>setUsername(e.target.value)}/></label>
          <label>Orbit password<input type="password" autoComplete={register?'new-password':'current-password'} required minLength={12} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)}/></label>
          <p>Use an Orbit password of at least 12 characters. Coinbase credentials are managed separately.</p>
          <button className="primary" disabled={busy}>{busy?'Please wait…':register?'Create Orbit account':'Sign in to Orbit'}</button>
        </form>
      </>:<div className="account-identity"><div><strong>{user.username}</strong><p>Orbit user ID: <strong>{user.id}</strong></p></div><button className="secondary" disabled={busy} onClick={logout}>Sign out</button></div>}
    </section>
    <section className="panel settings-panel">
      <div className="panel-heading"><div><h3>Coinbase account</h3><p>Your actual Coinbase holdings, separate from simulated paper funds.</p></div><span className="pill quiet">READ ONLY</span></div>
      {user.guest?<p>Create an Orbit account or sign in above to set up your personal connection.</p>:!status?<p>{error?'Connection status is unavailable. Use Retry above.':'Checking connection status…'}</p>:status.connected?<>
        <div className="account-identity"><span className="status on"><i/>Connected to Coinbase</span><div className="account-tabs"><button className="secondary" disabled={busy} onClick={()=>connection('refresh')}>Refresh balances</button><button className="secondary" disabled={busy} onClick={()=>connection('disconnect')}>Disconnect</button></div></div>
        {busy&&<p role="status">Updating connection…</p>}
        {portfolio&&<>
          <p>Updated {new Date(portfolio.updated_at).toLocaleString()}. Includes only portfolios accessible to your API key.</p>
          <div className="table-wrap"><table><thead><tr><th>Asset</th><th>Available</th><th>On hold</th><th>Total units</th></tr></thead><tbody>{portfolio.accounts.map((account,index)=><tr key={`${account.currency}-${index}`}><td><strong>{account.currency}</strong><small className="account-asset-name">{account.name}</small></td><td>{account.available}</td><td>{account.held}</td><td>{account.total}</td></tr>)}</tbody></table>{!portfolio.accounts.length&&<div className="empty-state">Coinbase returned no accessible active accounts.</div>}</div>
        </>}
        {!busy&&!portfolio&&<p>Balances are unavailable. Refresh to request a new snapshot.</p>}
        <p className="account-footnote">Disconnect removes Orbit's saved connection. To revoke the API key itself, delete it in Coinbase Developer Platform.</p>
      </>:<>
        <p>{status.eligible&&status.configured?'Your backend is ready. Connect to verify the View-only key and load your balances.':'This first version supports one configured owner account. Complete the local setup below, then restart the backend.'}</p>
        <button className="primary" disabled={busy||!status.eligible||!status.configured} onClick={()=>connection('connect')}>{busy?'Checking Coinbase…':'Connect Coinbase'}</button>
        <details className="account-setup"><summary>Local test setup</summary><ol>
          <li>Your Orbit user ID is <strong>{user.id}</strong>. Set <code>COINBASE_READONLY_OWNER_USER_ID</code> to this ID in the backend <code>.env</code>.</li>
          <li>Create an ECDSA API key in <a className="text-button" href="https://portal.cdp.coinbase.com/access/api" target="_blank" rel="noopener noreferrer">Coinbase Developer Platform ↗</a>. Enable View only; disable Trade and Transfer.</li>
          <li>Put its key name and private key into <code>COINBASE_READONLY_KEY_NAME</code> and <code>COINBASE_READONLY_PRIVATE_KEY</code> in the backend <code>.env</code>.</li>
          <li>Restart the backend, reload this page, and select Connect Coinbase.</li>
        </ol><p>Store keys only in backend configuration. This connection can display balances; it cannot place trades or transfer funds.</p></details>
      </>}
    </section>
  </div>;
}
