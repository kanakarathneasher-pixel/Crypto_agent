'use client';
import {useEffect, useState} from 'react';
import {requestJson} from '../lib/api';

type Row = Record<string, any>;
async function call(path: string, method = 'GET', body?: unknown) {
  return requestJson(`/v2/agent/${path}`, method, body);
}

export default function ManagedAgent() {
  const [state, setState] = useState<Row|null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState('');
  const refresh = () => call('status').then(setState).catch(e => setError(e.message));
  useEffect(() => {
    refresh();
    let refreshing = false;
    const timer = setInterval(async () => {
      if (refreshing) return;
      refreshing = true;
      try {await refresh();} finally {refreshing = false;}
    }, 2000);
    const events = new EventSource('/api/v2/agent/events', {withCredentials:true});
    events.addEventListener('activity', refresh);
    return () => {clearInterval(timer); events.close();};
  }, []);
  async function command(action: string) {
    setBusy(true); setError('');
    try {await call('commands','POST',{action,request_id:crypto.randomUUID()}); await refresh();}
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function configure() {
    setBusy(true); setError('');
    try {await call('configuration','PUT',{mode:'paper',settings:settings ? JSON.parse(settings) : {}}); await refresh();}
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <section className="panel settings-panel">
    <div className="panel-heading"><div><h3>Managed spot agent</h3><p>Persistent orders, risk controls and position monitoring</p></div>
      <span className="badge">{state?.mode?.toUpperCase() || 'PAPER'} / {state?.phase || 'NOT CONFIGURED'}</span></div>
    {error && <p role="alert" className="error">{error}</p>}
    {!state?.configured ? <><p>Initialize a separate managed paper ledger. Your earlier paper history remains available below.</p>
      <button className="primary" disabled={busy} onClick={configure}>Initialize paper agent</button></> : <>
      <p>Reconciliation: {state.reconciled ? 'complete' : 'pending'} · Last check: {state.last_reconciled || 'waiting for worker'}</p>
      <p>USDC: {state.wallet.cash} · XRP: {state.wallet.quantity} · Equity: {state.equity ?? 'unavailable'} · Total P&amp;L: {state.total_pnl ?? 'unavailable'}</p>
      <div className="agent-controls">{[['resume','Resume entries'],['pause','Pause entries'],['cancel_entries','Cancel entry orders'],['emergency_stop','Emergency stop'],['close_position','Close position']].map(([action,label]) =>
        <button key={action} className="secondary" disabled={busy} onClick={()=>command(action)}>{label}</button>)}</div>
      <p>Pause keeps exit monitoring active. Emergency stop cancels entry orders by default and does not liquidate positions. Protective exits require this backend to remain online.</p>
      <details><summary>Managed risk configuration</summary>
        <p>These settings apply to this managed ledger. The older settings below apply only to the legacy paper engine.</p>
        <button className="secondary" onClick={()=>call('configuration').then(v=>setSettings(JSON.stringify(v.settings,null,2))).catch(e=>setError(e.message))}>Load configuration</button>
        <textarea aria-label="Managed risk configuration JSON" rows={14} value={settings} onChange={e=>setSettings(e.target.value)} style={{width:'100%',fontFamily:'monospace'}}/>
        <button className="primary" disabled={busy || !settings || state.mode !== 'paper'} onClick={configure}>Save paper configuration</button>
      </details>
      <h4>Order lifecycle</h4><div className="table-wrap"><table><thead><tr><th>Side</th><th>State</th><th>Requested XRP</th><th>Filled XRP</th><th>Fees</th></tr></thead><tbody>{state.orders.map((o:Row)=><tr key={o.id}><td>{o.side}</td><td>{o.state}</td><td>{o.quantity}</td><td>{o.filled_quantity}</td><td>{o.fees}</td></tr>)}</tbody></table></div>
      <h4>Latest activity</h4>{state.events.slice(0,8).map((e:Row)=><p key={e.id}><strong>{e.kind}</strong> · {e.data.action || e.data.state || e.data.output_kind || ''} {e.data.reason_codes?.join(', ')}</p>)}
    </>}
  </section>;
}
