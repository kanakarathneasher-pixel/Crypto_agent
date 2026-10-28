'use client';
import { FormEvent, useCallback, useEffect, useState } from 'react';
import ManagedAgent from './ManagedAgent';
import CoinbaseAccount from './CoinbaseAccount';
import LiveXrpChart from './LiveXrpChart';
import {requestJson as api} from '../lib/api';

type Row = Record<string, any>;
type Dashboard = {market: Row; agent: Row; model: Row; portfolio: Row; performance: Row; settings: Row; history: Row[]; trades: Row[]; decisions: Row[]; research: Row};
const money = (v: unknown, digits = 2) => v == null ? '—' : Number(v).toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits});
const pct = (v: unknown) => v == null ? '—' : `${(Number(v) * 100).toFixed(2)}%`;
const stamp = (v: string | null | undefined) => v ? new Date(v).toLocaleString(undefined, {timeZone: 'UTC', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) + ' UTC' : 'Not yet available';
// React development mode can mount twice. Reuse an in-flight guest request so
// the browser receives one session rather than creating competing workspaces.
let guestRequest: Promise<Row> | null = null;
function openWorkspace() {
  if (!guestRequest) guestRequest = api('/auth/guest','POST').finally(() => {guestRequest = null;});
  return guestRequest;
}

export default function Home() {
  const [user,setUser] = useState<Row|null>(null), [checking,setChecking] = useState(true);
  const [data,setData] = useState<Dashboard|null>(null), [tab,setTab] = useState('Overview');
  const [error,setError] = useState(''), [notice,setNotice] = useState(''), [busy,setBusy] = useState(false);

  const [form,setForm] = useState<Row>({}), [dirty,setDirty] = useState(false), [question,setQuestion] = useState('');
  const [chat,setChat] = useState<{role:string;text:string}[]>([]), [chatBusy,setChatBusy] = useState(false);
  const load = useCallback(async () => {
    const paths = ['/market/latest','/agent/status','/predictions/latest','/portfolio/paper','/performance/paper','/agent/settings','/market/history','/trades/paper','/decisions','/agent/research/latest'];
    const result = await Promise.all(paths.map(p => api(p)));
    setData({market:result[0],agent:result[1],model:result[2],portfolio:result[3],performance:result[4],settings:result[5],history:result[6],trades:result[7],decisions:result[8],research:result[9]});
    return result[5];
  },[]);
  useEffect(() => { openWorkspace().then(setUser).catch(e => setError(e.message)).finally(() => setChecking(false)); },[]);
  useEffect(() => {
    if (!user) return;
    load().then(setForm).catch(e => setError(e.message));
    let refreshing = false;
    const timer = setInterval(async () => {
      if (refreshing) return;
      refreshing = true;
      try {await load();} catch(e) {setError((e as Error).message);} finally {refreshing = false;}
    }, 2000);
    return () => clearInterval(timer);
  },[user,load]);
  async function action(path:string) {
    setBusy(true); setError(''); setNotice('');
    try { await api(path,'POST'); await load(); setNotice(path.endsWith('start') ? 'Paper evaluation started. Risk checks apply to every cycle.' : 'Paper agent stopped.'); }
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function save(e: FormEvent) {
    e.preventDefault(); setBusy(true);setError('');setNotice('');
    const names = ['max_trades_per_day','sizing_mode','manual_size_usdc','max_position_usdc','max_allocation','max_daily_loss_usdc','buy_threshold','sell_threshold','fee_rate','slippage_rate','emergency_stop'];
    const body = Object.fromEntries(names.map(k => [k,k === 'max_trades_per_day' ? Number(form[k]) : form[k]]));
    try {setForm(await api('/agent/settings','PUT',body));setDirty(false);await load();setNotice('Risk and sizing settings saved.');}
    catch(e) {setError((e as Error).message);}finally {setBusy(false);}
  }
  async function ask(e: FormEvent) {
    e.preventDefault();if (!question.trim() || chatBusy) return;
    const message = question;setQuestion('');setChat(c => [...c,{role:'You',text:message}]);setChatBusy(true);
    try {const response = await api('/chat','POST',{message});setChat(c => [...c,{role:'Orbit',text:response.answer}]);}
    catch(e) {setChat(c => [...c,{role:'System',text:(e as Error).message}]);}finally {setChatBusy(false);}
  }
  const field = (key:string,label:string,step='0.01',min='0',max?:string) => <label key={key}>{label}<input type="number" step={step} min={min} max={max} required value={form[key] ?? ''} onChange={e => {setDirty(true);setForm({...form,[key]:e.target.value});}}/></label>;
  if (checking) return <main className="loading">Connecting to your workspace…</main>;
  if (!user) return <main className="loading"><p role="alert">{error || "Unable to open the dashboard."}</p><button className="primary" onClick={()=>window.location.reload()}>Retry</button></main>;
  const prediction = data?.model.prediction?.fresh ? data.model.prediction : null;
  const portfolio = data?.portfolio, agent = data?.agent, settings = data?.settings;
  return <div className="workspace"><aside className="sidebar"><a className="brand" href="/" aria-label="Orbit home"><svg className="brand-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true"><circle cx="16" cy="16" r="12" stroke="currentColor" strokeWidth="5"/><circle cx="24" cy="7" r="5" fill="currentColor" stroke="var(--panel)" strokeWidth="2"/></svg><span>orbit<span className="brand-dot">.</span></span></a><div className="workspace-label">PAPER WORKSPACE</div><nav aria-label="Workspace navigation">{['Overview','Activity','Risk & settings','Account'].map((name,i)=><button key={name} aria-label={name} aria-current={tab===name?'page':undefined} onClick={()=>setTab(name)} className={tab===name?'selected':''}><span className="nav-icon"><NavigationIcon index={i}/></span><span className="nav-label">{name}</span></button>)}</nav><div className="sidebar-bottom"><div className="safe-card"><span>◇ PAPER ENVIRONMENT</span><p>Practice with simulated funds. Every order passes deterministic risk checks.</p></div><div className="identity"><div className="avatar">{user.username[0].toUpperCase()}</div><div><strong>{user.guest ? "Guest" : user.username}</strong><small>Paper workspace</small></div></div></div></aside>
    <div className="main-area"><header className="topbar"><span>Workspace <span className="slash">/</span> <strong>{tab}</strong></span><div className="topbar-right"><span className="pill">PAPER MODE</span><span className="muted">Coinbase · Spot</span></div></header><main className="content"><div className="page-heading"><div><span className="eyebrow">YOUR MARKET, IN FOCUS</span><h1>{tab==='Overview'?'Your crypto. In focus.':tab==='Activity'?'Agent activity':tab==='Account'?'Your account. Connected.':'Risk & settings'}</h1><p>{tab==='Overview'?'Understand the market. Follow every decision.':tab==='Activity'?'A transparent record of signals, checks, and simulated fills.':tab==='Account'?'Manage your Orbit sign-in and personal Coinbase connection.':'Set boundaries before your agent makes a decision.'}</p></div>{tab!=='Account'&&<div className="agent-controls"><span className={`status ${agent?.running?'on':''}`}><i/>{agent?.running?'Legacy agent running':'Legacy agent stopped'}</span><button className={agent?.running?'secondary':'primary'} disabled={busy||!data} onClick={()=>action(agent?.running?'/agent/stop':'/agent/start')}>{agent?.running?'■ Stop legacy agent':'▷ Start legacy paper agent'}</button></div>}</div>
    {error && <div className="error" role="alert">{error}<button aria-label="Dismiss error" onClick={()=>setError('')}>×</button></div>}{notice&&<div className="notice" role="status">{notice}</div>}
    {tab==='Account'&&<CoinbaseAccount user={user}/>}
    {tab!=='Account'&&(!data ? <div className="panel loading">Loading your account data…</div> : <>
    {!data.model.model.validated && <div className="validation-banner"><span>◇</span><div><strong>Research mode · Model trading is blocked</strong><p>{data.model.model.reason} Your agent can monitor and record HOLD decisions.</p></div><span className="badge">VALIDATION REQUIRED</span></div>}
    <ManagedAgent/>
    <div className="workspace-divider"><h2>Your market overview</h2><span className="pill quiet">PAPER PORTFOLIO</span></div><p className="workspace-description">Your original paper portfolio and market insights. Managed agent balances and controls are shown above.</p>
    {tab==='Overview' && <><section className="metrics"><article className="metric"><span className="metric-label">XRP / USDC <span className="tiny-tag">SPOT</span></span><h2>{data.market.price==null?'—':`$${money(data.market.price,4)}`}</h2><span className={data.market.fresh?'positive':'muted'}><i className="live-dot"/>{data.market.fresh?'Fresh Coinbase quote':'Quote unavailable or stale'}</span><small>{stamp(data.market.updated_at)}</small></article><article className="metric"><span className="metric-label">Legacy paper portfolio</span><h2>${money(portfolio?.equity_usdc)}</h2><span className={Number(portfolio?.pnl_usdc)>=0?'positive':'negative'}>{money(portfolio?.pnl_usdc)} USDC <span className="muted">paper P&L</span></span><small>Starting balance ${money(portfolio?.initial_usdc)}</small></article><article className="metric"><span className="metric-label">Next-hour forecast</span><h2>{pct(prediction?.predicted_return)}</h2><span className="muted">{prediction ? `Illustrative price $${money(prediction.estimated_price,4)}` : 'No approved forecast available'}</span><small>{stamp(prediction?.created_at)}</small></article><article className="metric"><span className="metric-label">Legacy trades today <span className="tiny-tag">UTC</span></span><h2>{agent?.trades_today} <span className="metric-denominator">/ {settings?.max_trades_per_day}</span></h2><span className="muted">Maximum, never a target</span><small>Zero trades is a valid outcome</small></article></section>
    <div className="overview-grid"><LiveXrpChart/><section className="panel portfolio-panel"><div className="panel-heading"><h3>Your paper holdings</h3><span>◉</span></div><div className="holding"><div className="coin usdc">$</div><div><strong>USDC</strong><small>Available balance</small></div><div className="holding-amount"><strong>{money(portfolio?.usdc)}</strong><small>USDC</small></div></div>{portfolio?.positions.map((p:Row)=><div className="holding" key={p.product}><div className="coin">X</div><div><strong>XRP</strong><small>Spot inventory</small></div><div className="holding-amount"><strong>{money(p.quantity,6)}</strong><small>XRP</small></div></div>)}<div className="holdings-note">Simulated funds only. No private Coinbase connection.</div><div className="mini-stat"><span>Total return</span><strong>{pct(data.performance.total_return)}</strong></div><div className="mini-stat"><span>Maximum drawdown</span><strong>{pct(data.performance.max_drawdown)}</strong></div><div className="mini-stat"><span>Fees paid</span><strong>{money(data.performance.fees_usdc)} USDC</strong></div></section></div>
    <section className="panel"><div className="panel-heading"><div><h3>Latest decisions</h3><p>Signals and risk checks, explained</p></div><button className="text-button" onClick={()=>setTab('Activity')}>View activity ↗</button></div><DecisionTable rows={data.decisions.slice(0,5)}/></section><div className="model-strip"><div><span className="eyebrow">MODEL VERSION</span><p>{data.model.model.version||'No promoted model'}</p></div><div><span className="eyebrow">LAST EVALUATION</span><p>{stamp(agent?.last_cycle?.created_at)}</p></div><div><span className="eyebrow">EXECUTION</span><p>Spot · Paper · No leverage</p></div></div></>}
    {tab==='Activity' && <><section className="panel"><div className="panel-heading"><div><h3>Decision journal</h3><p>Every hourly evaluation has a durable, unique record.</p></div><span className="pill quiet">LATEST 100</span></div><DecisionTable rows={data.decisions}/></section><section className="panel"><div className="panel-heading"><h3>Simulated fills</h3><span className="muted">Fees {pct(settings?.fee_rate)} · slippage {pct(settings?.slippage_rate)}</span></div><div className="table-wrap"><table><thead><tr><th>Time (UTC)</th><th>Side</th><th>XRP quantity</th><th>Fill price</th><th>Fee (USDC)</th><th>Realized P&L</th></tr></thead><tbody>{data.trades.map(t=><tr key={t.id}><td>{stamp(t.created_at)}</td><td><span className={`action ${t.side.toLowerCase()}`}>{t.side}</span></td><td>{money(t.quantity,6)}</td><td>${money(t.price,4)}</td><td>{money(t.fee,6)}</td><td>{money(t.realized_pnl,6)}</td></tr>)}</tbody></table>{!data.trades.length&&<div className="empty-state">No simulated fills. The agent is allowed to HOLD indefinitely.</div>}</div></section></>}
    {tab==='Risk & settings'&&<form onSubmit={save}><div className="settings-grid"><section className="panel settings-panel"><span className="eyebrow">01 / EXECUTION BOUNDARIES</span><h3>Risk limits</h3><p>Hard caps apply even when the model sees a signal.</p>{field('max_trades_per_day','Maximum trades per UTC day','1','1','50')}{field('max_position_usdc','Maximum XRP position value (USDC)','0.01','1','10000')}{field('max_allocation','Maximum XRP allocation (fraction)','0.01','0.01','0.25')}{field('max_daily_loss_usdc','Maximum daily paper loss (USDC)','0.01','0.01','10000')}<label className="check-label"><input type="checkbox" checked={Boolean(form.emergency_stop)} onChange={e=>{setDirty(true);setForm({...form,emergency_stop:e.target.checked});}}/>Emergency stop · immediately disables your agent</label></section><section className="panel settings-panel"><span className="eyebrow">02 / TRADE ASSUMPTIONS</span><h3>Position sizing & costs</h3><p>Fees and slippage are illustrative until verified for your tier.</p><label>Sizing mode<select value={form.sizing_mode||'automatic'} onChange={e=>{setDirty(true);setForm({...form,sizing_mode:e.target.value});}}><option value="automatic">Automatic · 2% of cash, capped</option><option value="manual">Manual · fixed USDC notional</option></select></label>{field('manual_size_usdc','Manual order size (USDC)','0.01','1','10000')}<div className="field-pair">{field('buy_threshold','BUY return threshold','0.001','0.001','0.5')}{field('sell_threshold','SELL return threshold','0.001','0.001','0.5')}</div><div className="field-pair">{field('fee_rate','Fee rate per fill','0.001','0','0.05')}{field('slippage_rate','Slippage rate','0.001','0','0.05')}</div><p className="field-help">0.006 = 0.6%. A signal must exceed both its threshold and estimated round-trip costs.</p></section></div><div className="save-bar"><span>{dirty?'You have unsaved changes.':'Settings are saved to your account.'}</span><button className="primary" disabled={busy||!dirty}>Save settings →</button></div></form>}
    <section className="panel research-panel"><div className="panel-heading"><div><h3>Selected research model</h3><p>{data.research.model?.version || 'No research model selected'}</p></div><span className="badge">OBSERVATION ONLY</span></div><p>Development direction accuracy: {pct(data.research.model?.development_accuracy)}. This model is not approved for orders.</p>{data.research.forecast ? <><p>Direction: <strong>{data.research.forecast.direction}</strong> / P(UP): {pct(data.research.forecast.probability_up)} (uncalibrated)</p><p>Completed candle: {stamp(data.research.forecast.candle_time)}</p><p>{data.research.forecast.reason}</p></> : <p>{data.research.reason || data.research.model?.reason}</p>}</section>
    </>)}
    {tab!=='Account'&&<section className="panel chat-panel"><div className="panel-heading"><div><h3><span className="spark">✧</span> Ask Orbit</h3><p>Understand your agent using your actual backend data.</p></div><span className="pill quiet">READ ONLY</span></div><div className="chat-messages" aria-live="polite">{!chat.length&&<p className="muted">Try “Why did my agent HOLD?” or “What are my risk limits?”</p>}{chat.map((m,i)=><div className={`chat-message ${m.role==='You'?'from-user':''}`} key={i}><strong>{m.role}</strong><p>{m.text}</p></div>)}{chatBusy&&<p className="muted">Reading your account state…</p>}</div><form className="chat-input" onSubmit={ask}><input aria-label="Ask your trading assistant" placeholder="Ask about your paper portfolio or latest decision…" value={question} onChange={e=>setQuestion(e.target.value)} maxLength={2000}/><button className="primary" disabled={chatBusy||!question.trim()}>Send ↗</button></form><small className="chat-disclaimer">Chat cannot execute trades or change risk limits. Forecasts do not guarantee returns.</small></section>}<footer>ORBIT / COINBASE PAPER WORKSPACE <span>Research with discipline. Trade only in simulation.</span></footer></main></div></div>;
}

function DecisionTable({rows}:{rows:Row[]}) {
  return <div className="table-wrap"><table><thead><tr><th>Evaluation (UTC)</th><th>Signal</th><th>Decision</th><th>Explanation</th></tr></thead><tbody>{rows.map(row=><tr key={row.id}><td className="nowrap">{stamp(row.candle_time)}</td><td>{row.signal}</td><td><span className={`action ${row.action.toLowerCase()}`}>{row.action}</span></td><td className="reason">{row.reason}</td></tr>)}</tbody></table>{!rows.length&&<div className="empty-state">No evaluation cycles yet. Start your paper agent to begin monitoring.</div>}</div>;
}

function NavigationIcon({index}:{index:number}) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{index===0?<><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/></>:index===1?<><path d="M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4"/></>:index===3?<><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></>:<><path d="m12 3 8 4v5c0 5-8 9-8 9s-8-4-8-9V7Z"/><path d="m8.5 12 2.5 2.5 4.5-5"/></>}</svg>;
}
