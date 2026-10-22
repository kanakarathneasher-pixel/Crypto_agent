"""Write a readable report from a completed direction experiment; no fitting."""
import argparse
import hashlib
import json
from pathlib import Path


def summarize(directory):
    folder = Path(directory)
    path = folder / 'metadata.json'
    report = json.loads(path.read_text())
    if report['status'] != 'complete_research_only':
        raise ValueError('Only completed experiments may be summarized.')
    report['artifact_sha256'] = {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in folder.rglob('classifier.joblib')}
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    lines = ['# Direction-classification development experiment', '',
             f"Run: `{report['version']}`. Raw data cutoff: **{report['raw_cutoff']}**.", '',
             'This is historical development research. The old validation and final-test periods',
             'were excluded before feature engineering. No fresh final-test result is claimed.', '',
             '## Method', '',
             '- Predict UP/DOWN directly with logistic regression and XGBoost (depths 2/3).',
             '- Compare 6-, 12-, 24-month and all available training histories.',
             '- Two expanding chronological folds; select by validation balanced accuracy,',
             '  breaking ties by validation log loss. Scalers fit on training data only.',
             '- Evaluate 1-, 4-, and 24-hour horizons; purge labels that touch the next partition.',
             '- Exclude moves <=0.01% from fitting/direction scoring. Keep every evaluation',
             '  hour for coverage and simulation. Longer-horizon labels overlap in time, so',
             '  their observation counts do not represent independent trades.',
             '- Predetermined abstention thresholds are diagnostics, not selected on evaluation.',
             '  Classifier probabilities are uncalibrated.', '',
             '## Accuracy on all qualifying directional observations', '',
             '| Horizon | Accuracy | Balanced accuracy | Training-majority accuracy | Directional samples |',
             '| --- | ---: | ---: | ---: | ---: |']
    for h, result in report['horizons'].items():
        m, baseline = result['pooled']['selected'], result['pooled']['train_majority']
        lines.append(f"| {h}h | {m['accuracy']:.2%} | {m['balanced_accuracy']:.2%} | {baseline['accuracy']:.2%} | {m['directional_samples']:,} |")
    lines += ['', 'These use slightly different sample sets from the earlier GRU/LSTM experiment;',
              'differences are not a controlled head-to-head comparison.', '',
              '## Models selected before evaluation', '',
              '| Horizon / fold | Model | Window (months) | Evaluation candle dates UTC |',
              '| --- | --- | --- | --- |']
    for h, result in report['horizons'].items():
        for fold in result['folds']:
            chosen, dates = fold['selected'], fold['partitions']['evaluation']
            lines.append(f"| {h}h / {fold['number']} | {chosen['name']} | {chosen['months'] or 'all'} | {dates['first_candle']} to {dates['last_candle']} |")
    lines += ['', '## Abstention diagnostics', '',
              'Coverage is the fraction of all hours receiving an UP or DOWN forecast.',
              'Accuracy below excludes near-zero realized moves. Do not cherry-pick a threshold',
              'from this table and call it validated; future untouched evaluation is required.', '',
              '| Horizon | Probability threshold | Accuracy | Coverage | Scored predictions |',
              '| --- | ---: | ---: | ---: | ---: |']
    for h, result in report['horizons'].items():
        for threshold, m in result['selective'].items():
            accuracy = f"{m['accuracy']:.2%}" if m['accuracy'] is not None else 'No predictions'
            lines.append(f"| {h}h | {threshold} | {accuracy} | {m['coverage_all_hours']:.2%} | {m['scored_predictions']} |")
    lines += ['', '## Illustrative fee-aware spot simulation', '',
              'Fixed rule chosen before evaluation: BUY if P(UP)>=0.60; otherwise HOLD.',
              'Invest 10% of paper cash, enter next candle open, exit at horizon close,',
              'and allow no overlapping positions. No short selling or leverage.',
              'Fees are **0.6% per fill** and slippage **0.1% per fill**, illustrative assumptions.',
              'Each fold starts with 1,000 USDC. This is a research diagnostic, not the app risk engine.',
              'Benchmark invests 100% once, so its exposure differs from this strategy.', '',
              '| Horizon / fold | Paper return | Round trips | Winning trades | Buy-and-hold after costs |',
              '| --- | ---: | ---: | ---: | ---: |']
    for h, result in report['horizons'].items():
        for fold in result['folds']:
            s = fold['fee_aware_simulation']
            wins = f"{s['win_rate']:.2%}" if s['win_rate'] is not None else 'No trades'
            lines.append(f"| {h}h / {fold['number']} | {s['return']:.2%} | {s['round_trips']} | {wins} | {s['buy_hold_return_after_costs']:.2%} |")
    lines += ['', 'All simulations lost money after these estimated costs. No candidate is approved.',
              'The 24-hour high-threshold result covers very few, overlapping labels; it is not',
              'evidence of broad high accuracy or profitable trading.', '',
              '## Reproduce', '', '```powershell',
              '.\\.venv\\Scripts\\python.exe -m src.direction_research',
              '```', '',
              'Saved artifacts include every validation comparison, exact split dates, selected',
              'classifiers, prediction probabilities and simulated round trips under the run directory.',
              'BTC/ETH context and probability calibration were not added in this first comparison.',
              'Those are separate prospective experiments; new market data is needed for a fresh final test.']
    text = '\n'.join(lines) + '\n'
    (folder / 'report.md').write_text(text, encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    (root / 'docs/direction_results.md').write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    summarize(parser.parse_args().directory)
