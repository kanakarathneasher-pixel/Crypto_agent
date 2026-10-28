import type {Row} from '../../lib/dashboard';
import {stamp} from '../../lib/format';

export default function DecisionTable({rows}:{rows:Row[]}) {
  return <div className="table-wrap"><table><thead><tr><th>Evaluation (UTC)</th><th>Signal</th><th>Decision</th><th>Explanation</th></tr></thead><tbody>{rows.map(row=><tr key={row.id}><td className="nowrap">{stamp(row.candle_time)}</td><td>{row.signal}</td><td><span className={`action ${row.action.toLowerCase()}`}>{row.action}</span></td><td className="reason">{row.reason}</td></tr>)}</tbody></table>{!rows.length&&<div className="empty-state">No evaluation cycles yet. Start your paper agent to begin monitoring.</div>}</div>;
}
