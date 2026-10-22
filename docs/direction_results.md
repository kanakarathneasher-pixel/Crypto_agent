# Direction-classification development experiment

Run: `direction-20261022T055414356445Z`. Raw data cutoff: **2025-10-23 10:00:00+00:00**.

This is historical development research. The old validation and final-test periods
were excluded before feature engineering. No fresh final-test result is claimed.

## Method

- Predict UP/DOWN directly with logistic regression and XGBoost (depths 2/3).
- Compare 6-, 12-, 24-month and all available training histories.
- Two expanding chronological folds; select by validation balanced accuracy,
  breaking ties by validation log loss. Scalers fit on training data only.
- Evaluate 1-, 4-, and 24-hour horizons; purge labels that touch the next partition.
- Exclude moves <=0.01% from fitting/direction scoring. Keep every evaluation
  hour for coverage and simulation. Longer-horizon labels overlap in time, so
  their observation counts do not represent independent trades.
- Predetermined abstention thresholds are diagnostics, not selected on evaluation.
  Classifier probabilities are uncalibrated.

## Accuracy on all qualifying directional observations

| Horizon | Accuracy | Balanced accuracy | Training-majority accuracy | Directional samples |
| --- | ---: | ---: | ---: | ---: |
| 1h | 52.87% | 52.81% | 50.41% | 5,892 |
| 4h | 50.75% | 50.77% | 49.82% | 5,935 |
| 24h | 51.28% | 51.37% | 51.75% | 5,944 |

These use slightly different sample sets from the earlier GRU/LSTM experiment;
differences are not a controlled head-to-head comparison.

## Models selected before evaluation

| Horizon / fold | Model | Window (months) | Evaluation candle dates UTC |
| --- | --- | --- | --- |
| 1h / 1 | logistic | 24 | 2025-01-06 01:00:00+00:00 to 2025-05-10 10:00:00+00:00 |
| 1h / 2 | xgboost_depth3 | 24 | 2025-06-20 23:00:00+00:00 to 2025-10-23 09:00:00+00:00 |
| 4h / 1 | logistic | 12 | 2025-01-05 23:00:00+00:00 to 2025-05-10 08:00:00+00:00 |
| 4h / 2 | xgboost_depth3 | 24 | 2025-06-20 20:00:00+00:00 to 2025-10-23 06:00:00+00:00 |
| 24h / 1 | xgboost_depth2 | 24 | 2025-01-05 10:00:00+00:00 to 2025-05-09 16:00:00+00:00 |
| 24h / 2 | logistic | 12 | 2025-06-20 03:00:00+00:00 to 2025-10-22 10:00:00+00:00 |

## Abstention diagnostics

Coverage is the fraction of all hours receiving an UP or DOWN forecast.
Accuracy below excludes near-zero realized moves. Do not cherry-pick a threshold
from this table and call it validated; future untouched evaluation is required.

| Horizon | Probability threshold | Accuracy | Coverage | Scored predictions |
| --- | ---: | ---: | ---: | ---: |
| 1h | 0.55 | 54.20% | 40.68% | 2402 |
| 1h | 0.6 | 56.92% | 11.02% | 650 |
| 1h | 0.65 | 61.44% | 2.58% | 153 |
| 1h | 0.7 | 62.50% | 1.07% | 64 |
| 4h | 0.55 | 51.70% | 48.15% | 2861 |
| 4h | 0.6 | 52.82% | 17.03% | 1011 |
| 4h | 0.65 | 52.57% | 4.55% | 272 |
| 4h | 0.7 | 59.34% | 1.52% | 91 |
| 24h | 0.55 | 53.47% | 42.40% | 2519 |
| 24h | 0.6 | 58.05% | 16.59% | 987 |
| 24h | 0.65 | 66.51% | 7.14% | 424 |
| 24h | 0.7 | 85.19% | 0.92% | 54 |

## Illustrative fee-aware spot simulation

Fixed rule chosen before evaluation: BUY if P(UP)>=0.60; otherwise HOLD.
Invest 10% of paper cash, enter next candle open, exit at horizon close,
and allow no overlapping positions. No short selling or leverage.
Fees are **0.6% per fill** and slippage **0.1% per fill**, illustrative assumptions.
Each fold starts with 1,000 USDC. This is a research diagnostic, not the app risk engine.
Benchmark invests 100% once, so its exposure differs from this strategy.

| Horizon / fold | Paper return | Round trips | Winning trades | Buy-and-hold after costs |
| --- | ---: | ---: | ---: | ---: |
| 1h / 1 | -33.52% | 319 | 17.87% | -2.92% |
| 1h / 2 | -22.74% | 185 | 7.03% | 12.13% |
| 4h / 1 | -15.09% | 160 | 30.00% | -1.33% |
| 4h / 2 | -17.71% | 155 | 20.65% | 11.43% |
| 24h / 1 | -0.36% | 27 | 51.85% | 2.03% |
| 24h / 2 | -5.24% | 40 | 35.00% | 10.29% |

All simulations lost money after these estimated costs. No candidate is approved.
The 24-hour high-threshold result covers very few, overlapping labels; it is not
evidence of broad high accuracy or profitable trading.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m src.direction_research
```

Saved artifacts include every validation comparison, exact split dates, selected
classifiers, prediction probabilities and simulated round trips under the run directory.
BTC/ETH context and probability calibration were not added in this first comparison.
Those are separate prospective experiments; new market data is needed for a fresh final test.
