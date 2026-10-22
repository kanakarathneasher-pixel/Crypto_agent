# Focused XGBoost direction classifier

Run: `xgboost-direction-20261022T061816804978Z`.

Source: cleaned Coinbase XRP/USDC hourly CSV. Only candles up to
`2025-10-23 10:00:00+00:00` enter this development experiment. Prior validation and final-test dates are excluded.
These historical periods have been examined before; results are not an independent final test.

| Metric | XGBoost | Training-majority baseline |
| --- | ---: | ---: |
| accuracy | 53.05% | 50.41% |
| balanced_accuracy | 52.99% | 50.00% |

Scored directional observations: 5,892.
Moves of 0.01% or less are excluded from direction scoring; no confidence filtering.

Maximum 300 boosting rounds; depth 3; learning rate 0.03; L2=10;
80% row/column sampling; early stopping patience 20 on validation log loss.
CPU training with two threads; no GPU dependency.

| Fold | Best round | Completed rounds | Accuracy | Paper return after costs |
| --- | ---: | ---: | ---: | ---: |
| 1 | 63 | 83 | 53.66% | -25.64% |
| 2 | 51 | 71 | 52.45% | -3.07% |

Paper diagnostic: enter next hourly open when P(UP)>=0.60; exit next hour close;
10% cash per trade, non-overlapping positions, 0.6% fee and 0.1% slippage per fill.
Costs are illustrative. Probabilities are uncalibrated. No promotion or live trades.

Artifacts, histories and exact partitions: `models/xgboost-direction-20261022T061816804978Z/`.
Both native UBJ artifacts were reloaded and reproduced their evaluation probabilities.

Run with `.\.venv\Scripts\python.exe -m src.xgboost_direction`.
