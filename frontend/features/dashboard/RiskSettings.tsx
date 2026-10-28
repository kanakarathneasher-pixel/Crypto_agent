'use client';
import {type FormEvent,useEffect,useState} from 'react';
import type {Row} from '../../lib/dashboard';
import {requestJson as api} from '../../lib/api';

export default function RiskSettings({settings,onSaved,onNotice}:{settings:Row;onSaved:()=>Promise<unknown>;onNotice:(message:string)=>void}) {
  const [form,setForm]=useState<Row>(settings);
  const [dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const refresh=onSaved,setNotice=onNotice;
  useEffect(()=>{if(!dirty) setForm(settings);},[settings,dirty]);
  async function save(e: FormEvent) {
    e.preventDefault(); setBusy(true);setError('');setNotice('');
    const names = ['max_trades_per_day','sizing_mode','manual_size_usdc','max_position_usdc','max_allocation','max_daily_loss_usdc','buy_threshold','sell_threshold','fee_rate','slippage_rate','emergency_stop'];
    const body = Object.fromEntries(names.map(k => [k,k === 'max_trades_per_day' ? Number(form[k]) : form[k]]));
    try {setForm(await api('/agent/settings','PUT',body));setDirty(false);await refresh();setNotice('Risk and sizing settings saved.');}
    catch(e) {setError((e as Error).message);}finally {setBusy(false);}
  }
  const field = (key:string,label:string,step='0.01',min='0',max?:string) => <label key={key}>{label}<input type="number" step={step} min={min} max={max} required value={form[key] ?? ''} onChange={e => {setDirty(true);setForm({...form,[key]:e.target.value});}}/></label>;
  return <>{error&&<p className="error" role="alert">{error}</p>}<form onSubmit={save}><div className="settings-grid"><section className="panel settings-panel"><span className="eyebrow">01 / EXECUTION BOUNDARIES</span><h3>Risk limits</h3><p>Hard caps apply even when the model sees a signal.</p>{field('max_trades_per_day','Maximum trades per UTC day','1','1','50')}{field('max_position_usdc','Maximum XRP position value (USDC)','0.01','1','10000')}{field('max_allocation','Maximum XRP allocation (fraction)','0.01','0.01','0.25')}{field('max_daily_loss_usdc','Maximum daily paper loss (USDC)','0.01','0.01','10000')}<label className="check-label"><input type="checkbox" checked={Boolean(form.emergency_stop)} onChange={e=>{setDirty(true);setForm({...form,emergency_stop:e.target.checked});}}/>Emergency stop · immediately disables your agent</label></section><section className="panel settings-panel"><span className="eyebrow">02 / TRADE ASSUMPTIONS</span><h3>Position sizing & costs</h3><p>Fees and slippage are illustrative until verified for your tier.</p><label>Sizing mode<select value={form.sizing_mode||'automatic'} onChange={e=>{setDirty(true);setForm({...form,sizing_mode:e.target.value});}}><option value="automatic">Automatic · 2% of cash, capped</option><option value="manual">Manual · fixed USDC notional</option></select></label>{field('manual_size_usdc','Manual order size (USDC)','0.01','1','10000')}<div className="field-pair">{field('buy_threshold','BUY return threshold','0.001','0.001','0.5')}{field('sell_threshold','SELL return threshold','0.001','0.001','0.5')}</div><div className="field-pair">{field('fee_rate','Fee rate per fill','0.001','0','0.05')}{field('slippage_rate','Slippage rate','0.001','0','0.05')}</div><p className="field-help">0.006 = 0.6%. A signal must exceed both its threshold and estimated round-trip costs.</p></section></div><div className="save-bar"><span>{dirty?'You have unsaved changes.':'Settings are saved to your account.'}</span><button className="primary" disabled={busy||!dirty}>Save settings →</button></div></form></>;
}
