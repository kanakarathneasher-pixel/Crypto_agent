import type {Dashboard} from '../../lib/dashboard';
import {money,pct,stamp} from '../../lib/format';
import DecisionTable from './DecisionTable';

export default function Activity({data}:{data:Dashboard}) {
  const {settings}=data;
  return <><section className="panel"><div className="panel-heading"><div><h3>Decision journal</h3><p>Every hourly evaluation has a durable, unique record.</p></div><span className="pill quiet">LATEST 100</span></div><DecisionTable rows={data.decisions}/></section><section className="panel"><div className="panel-heading"><h3>Simulated fills</h3><span className="muted">Fees {pct(settings?.fee_rate)} · slippage {pct(settings?.slippage_rate)}</span></div><div className="table-wrap"><table><thead><tr><th>Time (UTC)</th><th>Side</th><th>XRP quantity</th><th>Fill price</th><th>Fee (USDC)</th><th>Realized P&L</th></tr></thead><tbody>{data.trades.map(t=><tr key={t.id}><td>{stamp(t.created_at)}</td><td><span className={`action ${t.side.toLowerCase()}`}>{t.side}</span></td><td>{money(t.quantity,6)}</td><td>${money(t.price,4)}</td><td>{money(t.fee,6)}</td><td>{money(t.realized_pnl,6)}</td></tr>)}</tbody></table>{!data.trades.length&&<div className="empty-state">No simulated fills. The agent is allowed to HOLD indefinitely.</div>}</div></section>
  </>;
}
