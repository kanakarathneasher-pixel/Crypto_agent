'use client';
import {useCallback, useEffect, useState} from 'react';
import {requestJson as api} from '../../lib/api';
import type {OrbitUser} from '../../lib/workspace';

type Status = {eligible:boolean; configured:boolean; connected:boolean};
type Portfolio = {accounts:{currency:string; name:string; available:string; held:string; total:string}[]; updated_at:string};

export default function CoinbaseConnection({user}:{user:OrbitUser}) {
  const [status,setStatus]=useState<Status|null>(null);
  const [portfolio,setPortfolio]=useState<Portfolio|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [attempt,setAttempt]=useState(0);

  useEffect(()=>{
    if(user.guest) return;
    let active=true;
    setError('');setStatus(null);setPortfolio(null);
    api('/connections/coinbase').then(async value=>{
      if(!active) return;
      setStatus(value);
      if(value.connected) {
        const balances=await api('/connections/coinbase/portfolio');
        if(active) setPortfolio(balances);
      }
    }).catch(error=>{if(active) setError(error.message);});
    return ()=>{active=false;};
  },[user.id,user.guest,attempt]);

  const connection=useCallback(async (action:'connect'|'disconnect'|'refresh')=>{
    setBusy(true);setError('');setPortfolio(null);
    try {
      if(action==='refresh') setPortfolio(await api('/connections/coinbase/portfolio'));
      else {
        const result=await api(`/connections/coinbase/${action}`,'POST');
        setStatus(previous=>previous?{...previous,connected:result.connected}:previous);
        if(result.portfolio) setPortfolio(result.portfolio);
      }
    } catch(error) {setError((error as Error).message);} finally {setBusy(false);}
  },[]);

  return <section className="panel settings-panel">
    <div className="panel-heading"><div><h3>Coinbase connection</h3><p>View your actual holdings separately from paper funds.</p></div><span className="pill quiet">READ ONLY</span></div>
    {error&&<div className="error" role="alert">{error}<button className="text-button" disabled={busy} onClick={()=>setAttempt(value=>value+1)}>Retry connection check</button></div>}
    {user.guest?<p>Sign in to check whether your account can connect to Coinbase.</p>:!status?<p role="status">{error?'Connection status is unavailable.':'Checking connection status…'}</p>:status.connected?<>
      <div className="account-identity"><span className="status on"><i/>Connected to Coinbase</span><div className="account-tabs"><button className="secondary" disabled={busy} onClick={()=>connection('refresh')}>Refresh balances</button><button className="secondary" disabled={busy} onClick={()=>connection('disconnect')}>Disconnect</button></div></div>
      {busy&&<p role="status">Updating connection…</p>}
      {portfolio&&<>
        <p>Updated {new Date(portfolio.updated_at).toLocaleString()}. Includes portfolios accessible to your connection.</p>
        <div className="table-wrap"><table><thead><tr><th>Asset</th><th>Available</th><th>On hold</th><th>Total units</th></tr></thead><tbody>{portfolio.accounts.map((account,index)=><tr key={`${account.currency}-${index}`}><td><strong>{account.currency}</strong><small className="account-asset-name">{account.name}</small></td><td>{account.available}</td><td>{account.held}</td><td>{account.total}</td></tr>)}</tbody></table>{!portfolio.accounts.length&&<div className="empty-state">No accessible active accounts were returned.</div>}</div>
      </>}
      {!busy&&!portfolio&&<p>Balances are unavailable. Refresh to request a new snapshot.</p>}
      <p className="account-footnote">Disconnect removes the saved connection. Revoke the API key in Coinbase to remove its access completely.</p>
    </>:<>
      <p>{status.eligible&&status.configured?'Your connection is ready. Connect to verify access and load balances.':status.eligible?'Your connection is waiting for administrator setup.':'Coinbase connections currently support the configured workspace owner. Your Orbit account and paper portfolio are ready to use.'}</p>
      <button className="primary" disabled={busy||!status.eligible||!status.configured} onClick={()=>connection('connect')}>{busy?'Checking Coinbase…':'Connect Coinbase'}</button>
    </>}
  </section>;
}
