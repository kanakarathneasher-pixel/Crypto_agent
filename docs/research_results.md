# Coinbase research results — October 20, 2026

The complete run retrieved **28,662 actual hourly XRP-USDC candles** from **2023-07-13 20:00 UTC through 2026-10-20 11:00 UTC**. It requested 147 chronological windows of at most 300 hours. There were 169 overlaps with the original CSV, removed during combination. The original 169-row dataset is preserved in `data/raw/coinbase_xrp_usdc_1h.backup_20261020T121010898760Z.csv`.

The requested five-year window contained 15,162 absent hours, mostly before available history. Within actual coverage, there are **10 missing hours**: five between 2025-10-25 15:00 and 21:00 UTC, and five between 2026-05-08 01:00 and 07:00 UTC. No candles were filled. Preprocessing rejected zero invalid rows and flagged zero observations under the stated abnormal-move thresholds. The feature dataset has 28,446 supervised rows and 19 features. Indicators restart at each gap; targets never span gaps.

## Model comparison

Model version: `coinbase-20261020T121949544468Z`. The old Binance Random Forest remains untouched.

| Partition | Candle starts, UTC | Rows |
| --- | --- | ---: |
| Training | 2023-07-16 19:00 to 2025-10-23 09:00 | 19,911 |
| Validation | 2025-10-23 11:00 to 2026-04-22 09:00 | 4,266 |
| Final test | 2026-04-22 11:00 to 2026-10-20 10:00 | 4,267 |

One boundary row was purged between partitions; each training/validation target occurs before the next partition. Inputs have no learned scaling or imputation. Initial model parameters were fixed before evaluation; selection between RF and XGBoost used validation MAE only. No parameter search was performed against the final test. Three expanding-window folds used only training data.

| Model | Validation MAE | Validation RMSE | Test MAE | Test RMSE | Test directional accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| Zero return | 0.00485540 | 0.00720018 | 0.00400901 | 0.00648132 | 0% (abstention baseline) |
| Random Forest | 0.00486856 | 0.00722542 | 0.00401006 | 0.00650612 | 49.64% |
| XGBoost | 0.00487553 | 0.00724812 | 0.00400662 | 0.00647040 | 49.52% |

Returns are fractions, so 0.004 is a 0.4% return error. Directional accuracy excludes actual absolute moves <= 0.0001 (one basis point); a predicted zero is counted as a miss. There are 4,158 qualifying test observations. Directional accuracy is secondary to error metrics and does not imply trade profitability.

RF was selected on validation MAE, but neither candidate achieved the required >5% MAE and RMSE improvement across validation, test and all training-only walk-forward folds. **No model is eligible or promoted. Model-driven paper fills remain blocked.** XGBoost's small advantage on the final test is not used to retrospectively select it.

The versioned `metadata.json` stores complete error quantiles, bias, per-period results, fold dates, parameters, schema order, partition/target dates and artifact checksum. A reporting error was corrected and the unchanged initial model run repeated; no parameters were adjusted using those results. An earlier incomplete version folder contains a model artifact without metadata and is not loadable/promotable.

## Frozen strategy backtest

The selected RF was examined as an unapproved research candidate over **2026-04-22 12:00 UTC to 2026-10-20 10:00 UTC**, with predictions from completed candles and fills at the following hourly OPEN. The strategy uses 2% BUY/SELL thresholds, estimated round-trip cost checks, 0.6% fee per fill, 0.1% slippage, a 25 USDC position cap, 10% allocation cap and five daily fills maximum. These costs are illustrative, not a verified client Coinbase tier.

Result: **0 fills, 0% return, 0% drawdown**. Win rate and Sharpe are undefined. Buy-and-hold, including illustrative entry and liquidation costs, returned **-12.3898%**. HOLD produced a flat cash portfolio, not evidence of predictive skill or profitable trading. No strategy parameters were optimized against this period. The paper risk manager subsequently gained an additional known-cost daily-loss check; this does not alter the zero-fill result.

Artifacts: `models/coinbase-20261020T121949544468Z/{metadata.json,model.joblib,backtest.json,backtest_equity.csv,backtest_fills.csv}`. The final artifact was not refit on validation/test data. Subsequent training requires at least 200 new, previously untested final-holdout hours. Historical results do not guarantee future returns.

## Integration evidence and limits

The local production Next.js proxy was exercised against FastAPI, a migrated disposable SQLite database, and live public Coinbase monitoring. Authentication, market history, portfolio, risk settings, model rejection, an autonomous HOLD cycle, Stop, missing-key chatbot behavior and logout were verified. Provider function-calling is mocked in tests; no OpenAI key was supplied or billed. No browsers were available through the UI tool, so visual desktop/mobile QA remains unverified. CSS breakpoints and the TypeScript production build are checked in source/build, not claimed as screenshot verification.

Final offline verification: **51 tests passed**, including frozen migrations, concurrent cycle deduplication, failed-fill rollback, all risk controls, actual feature-based inference, model integrity, API user isolation, rate limiting, and cost-bearing chronological backtest fills. The Next.js 16.4.2 / React 19.3.1 production build passed TypeScript checks. npm's install audit reported zero vulnerabilities at verification time.
