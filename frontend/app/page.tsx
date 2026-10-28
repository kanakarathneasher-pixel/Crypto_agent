'use client';
import { useState } from 'react';
import ManagedAgent from '../features/agent/ManagedAgent';
import AccountPage from '../features/account/AccountPage';
import WorkspaceGate from './components/WorkspaceGate';
import {useWorkspace} from '../hooks/useWorkspace';
import Overview from '../features/dashboard/Overview';
import Activity from '../features/dashboard/Activity';
import RiskSettings from '../features/dashboard/RiskSettings';
import AskOrbit from '../features/dashboard/AskOrbit';
import Research from '../features/dashboard/Research';
import {requestJson as api} from '../lib/api';

export default function Home() {
  const [tab,setTab] = useState('Overview');
  const {user,checking,message,connectionError,data,refresh,refreshError,lastUpdated,expired} = useWorkspace(tab==='Account');
  const [error,setError] = useState(''), [notice,setNotice] = useState(''), [busy,setBusy] = useState(false);
  async function action(path:string) {
    setBusy(true); setError(''); setNotice('');
    try { await api(path,'POST'); await refresh(); setNotice(path.endsWith('start') ? 'Paper evaluation started. Risk checks apply to every cycle.' : 'Paper agent stopped.'); }
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  if (checking || !user) return <WorkspaceGate checking={checking} message={message} error={connectionError}/>;
  const agent=data?.agent;
  return <div className="workspace"><aside className="sidebar"><a className="brand" href="/" aria-label="Orbit home"><svg className="brand-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true"><circle cx="16" cy="16" r="12" stroke="currentColor" strokeWidth="5"/><circle cx="24" cy="7" r="5" fill="currentColor" stroke="var(--panel)" strokeWidth="2"/></svg><span>orbit<span className="brand-dot">.</span></span></a><div className="workspace-label">PAPER WORKSPACE</div><nav aria-label="Workspace navigation">{['Overview','Activity','Risk & settings','Account'].map((name,i)=><button key={name} aria-label={name} aria-current={tab===name?'page':undefined} onClick={()=>setTab(name)} className={tab===name?'selected':''}><span className="nav-icon"><NavigationIcon index={i}/></span><span className="nav-label">{name}</span></button>)}</nav><div className="sidebar-bottom"><div className="safe-card"><span>◇ PAPER ENVIRONMENT</span><p>Practice with simulated funds. Every order passes deterministic risk checks.</p></div><div className="identity"><div className="avatar">{user.username[0].toUpperCase()}</div><div><strong>{user.guest ? "Guest" : user.username}</strong><small>Paper workspace</small></div></div></div></aside>
    <div className="main-area"><header className="topbar"><span>Workspace <span className="slash">/</span> <strong>{tab}</strong></span><div className="topbar-right"><span className="pill">PAPER MODE</span><span className="muted">Coinbase · Spot</span></div></header><main className="content"><div className="page-heading"><div><span className="eyebrow">YOUR MARKET, IN FOCUS</span><h1>{tab==='Overview'?'Your crypto. In focus.':tab==='Activity'?'Agent activity':tab==='Account'?'Your account. Connected.':'Risk & settings'}</h1><p>{tab==='Overview'?'Understand the market. Follow every decision.':tab==='Activity'?'A transparent record of signals, checks, and simulated fills.':tab==='Account'?'Manage your Orbit sign-in and personal Coinbase connection.':'Set boundaries before your agent makes a decision.'}</p></div>{tab!=='Account'&&<div className="agent-controls"><span className={`status ${agent?.running?'on':''}`}><i/>{agent?.running?'Legacy agent running':'Legacy agent stopped'}</span><button className={agent?.running?'secondary':'primary'} disabled={busy||!data} onClick={()=>action(agent?.running?'/agent/stop':'/agent/start')}>{agent?.running?'■ Stop legacy agent':'▷ Start legacy paper agent'}</button></div>}</div>
    {refreshError&&tab!=='Account'&&<div className="connection-banner" role="status"><span>{refreshError} {data?'Showing the last saved snapshot.':''}</span><button className="text-button" disabled={busy} onClick={()=>expired?window.location.reload():void refresh().catch(()=>{})}>{expired?'Reconnect':'Retry update'}</button></div>}
    {user.guest&&tab==='Overview'&&<div className="guest-banner"><div><strong>You’re exploring a guest workspace.</strong><p>Sign in to return to your saved account and settings.</p></div><button className="secondary" onClick={()=>setTab('Account')}>Sign in / Create account</button></div>}
    {lastUpdated&&tab!=='Account'&&<p className="sync-caption">Account snapshot updated {lastUpdated.toLocaleTimeString()} · Live prices update separately</p>}
    {error && <div className="error" role="alert">{error}<button aria-label="Dismiss error" onClick={()=>setError('')}>×</button></div>}{notice&&<div className="notice" role="status">{notice}</div>}
    {tab==='Account'&&<AccountPage user={user}/>}
    {tab!=='Account'&&(!data?<div className="panel loading">Loading your account data…</div>:<>
      {!data.model.model.validated&&<div className="validation-banner"><span>◇</span><div><strong>Research mode · Model trading is blocked</strong><p>{data.model.model.reason} Your agent can monitor and record HOLD decisions.</p></div><span className="badge">VALIDATION REQUIRED</span></div>}
      {tab==='Overview'&&<ManagedAgent/>}
      <div className="workspace-divider"><h2>{tab==='Activity'?'Your paper activity':tab==='Risk & settings'?'Legacy paper settings':'Your market overview'}</h2><span className="pill quiet">PAPER PORTFOLIO</span></div>
      <p className="workspace-description">Your legacy paper portfolio and market insights. Managed agent controls are available on Overview.</p>
      {tab==='Overview'&&<Overview data={data} onActivity={()=>setTab('Activity')}/>}
      {tab==='Activity'&&<Activity data={data}/>}
      {tab==='Risk & settings'&&<RiskSettings settings={data.settings} onSaved={refresh} onNotice={setNotice}/>}
      {tab==='Overview'&&<Research research={data.research}/>}
    </>)}
    <div hidden={tab==='Account'}><AskOrbit/></div><footer>ORBIT / COINBASE PAPER WORKSPACE <span>Research with discipline. Trade only in simulation.</span></footer></main></div></div>;
}

function NavigationIcon({index}:{index:number}) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{index===0?<><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/></>:index===1?<><path d="M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4"/></>:index===3?<><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></>:<><path d="m12 3 8 4v5c0 5-8 9-8 9s-8-4-8-9V7Z"/><path d="m8.5 12 2.5 2.5 4.5-5"/></>}</svg>;
}
