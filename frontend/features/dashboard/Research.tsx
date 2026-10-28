import type {Row} from '../../lib/dashboard';
import {pct,stamp} from '../../lib/format';

export default function Research({research}:{research:Row}) {
  return <section className="panel research-panel">
    <div className="panel-heading"><div><h3>Selected research model</h3><p>{research.model?.version||'No research model selected'}</p></div><span className="badge">OBSERVATION ONLY</span></div>
    <p>Development direction accuracy: {pct(research.model?.development_accuracy)}. This model is not approved for orders.</p>
    {research.forecast?<>
      <p>Direction: <strong>{research.forecast.direction}</strong> / P(UP): {pct(research.forecast.probability_up)} (uncalibrated)</p>
      <p>Completed candle: {stamp(research.forecast.candle_time)}</p><p>{research.forecast.reason}</p>
    </>:<p>{research.reason||research.model?.reason}</p>}
  </section>;
}
