# Managed Coinbase spot agent

This service reuses the saved model without retraining. Paper mode is the default.
The background worker belongs to FastAPI, not the browser. Closing the dashboard
does not stop monitoring; shutting down the backend does.

## Model and approval status

The selected artifact is
`models/xgboost-direction-20261022T061816804978Z/fold_2/classifier.ubj`, pinned with
SHA-256 checksums in `models/research_selected.json`. `metadata.json` contains the
ordered schema and chronological split dates. `src/classifier_prediction.py`
checks both model and metadata checksums before loading the native XGBoost model.

The contract is XRP-USDC, completed ONE_HOUR candles, next-hour direction. It uses
one row of 21 features from `src.neural_data.sequence_features`, including the
72-hour SMA and gap-aware indicators, with the same price normalization and
cyclic calendar features used during training. It has no saved learned scaler
and no 48-hour neural sequence input. The worker retrieves 300 recent candles;
missing hours restart the indicators. Required feature order:

```
return_1h, return_3h, return_6h, return_24h,
sma_6, sma_24, sma_72, ema_12, ema_26, rsi_14,
macd, macd_signal, volatility_24h, volume_change, relative_volume,
candle_range, candle_body, hour_sin, hour_cos, weekday_sin, weekday_cos
```

Pooled development direction accuracy was 53.05%; the latest fold achieved
52.45%. The saved cost-aware simulations were negative. Its probability is
uncalibrated and it does not estimate return magnitude. Consequently it is
**not approved for orders**, including simulated entries in this managed engine.
`MODEL_NOT_APPROVED` and `EXPECTED_RETURN_UNAVAILABLE` are expected HOLD reasons.
There is no fabricated expected return, confidence percentage, or automatic
promotion. A separately validated return model may use the existing explicit
`models/approved.json` promotion contract. Missing artifacts produce HOLD.

`PredictionContract` documents version, product, hourly interval/horizon, source
candle start, prediction time, output kind, optional return/price/probability,
calibration flag, approval flag, data quality and reason codes. Inputs older than
10 minutes after the latest candle completion are rejected. A 07:00 candle
becomes available at 08:00; its forecast should be evaluated near 08:00.

## Install and run on Windows

From the existing project root in PowerShell:

```powershell
cd C:\Users\KLC\Downloads\Crypto_agent
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Create .env from .env.example only if you do not already have .env.
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd C:\Users\KLC\Downloads\Crypto_agent\frontend
npm ci
npm run dev
```

Open http://localhost:3000 for direct guest access, and select **Initialize paper agent**
in the Managed spot agent panel, then **Resume entries**. It starts a separate
1,000-USDC simulated ledger; the earlier paper ledger and history remain intact.
The legacy worker is excluded for managed users. Legacy controls reject attempts
to start that older strategy for a managed user. Managed risk settings are in
the managed panel; older dashboard sections are labelled legacy where relevant.

Do not turn on `LIVE_EXECUTION_ENABLED` for this demonstration. No Coinbase key
is needed. `WORKER_ENABLED=true` runs the scheduler. An OS file lock permits one
scheduler per database on this machine, including during reloads. Run all backend
processes from this root. This is a single-host prototype; multi-host deployment
requires a database-backed worker lease, shared clock and operational monitoring.

The live chart retains its two-second fallback, while account summaries and
managed status refresh every 15 seconds in a visible tab. Backend worker polling
is configured separately (`WORKER_POLL_SECONDS=2` locally, 30 in the Render
Blueprint). Network latency, rate-limit backoff, and processing may
delay individual updates; requests do not overlap. The hourly candle chart only
adds a point when a candle completes. The backend reuses completed history until
the next UTC hourly boundary and retries delayed boundary candles after 30 seconds.
Faster quote updates do not change the model's hourly prediction horizon.

The overview also includes a separate **XRP-USD reference chart**, reconstructed
from Coinbase Advanced Trade public candles and its public `ticker` WebSocket.
It offers 1H/1D/1W/1M ranges, hover inspection, live freshness status, heartbeats,
reconnect backoff and a two-second REST fallback for buffered SSE connections.
History and streaming routes are `/market/chart/history?period=1D`,
`/market/chart/latest` and `/market/chart/events`; the normal guest session applies.
Run `python -m scripts.check_xrp_chart` for a read-only live connectivity check.

This is not an embedded or identical copy of `coinbase.com/price/xrp`. That page
returned `X-Frame-Options: SAMEORIGIN` during verification and its pricing notes
allow data from other exchanges. The dashboard labels the reference series USD,
provides an original-page link, and retains XRP-USDC for strategy data, inference,
balances and orders. Chart ticks never become synthetic model candles. History
contains completed candle closes with their completion timestamps; current trade
ticks are appended for display only. No missing prices are generated.

## Order flow and recovery

`worker.py` retrieves a validated public book and completed candles, then calls
`ManagedEngine`. `model_adapter.py` builds the prediction envelope. The pure
`entry_check` checks approval, product/schema timing, round-trip fees, spread,
slippage, uncertainty buffer, sizing, cash, allocation, daily loss, drawdown,
cooldown, daily frequency, current inventory and pending orders. Calibrated
probability thresholds apply only when the contract says calibration is valid.
Threshold defaults are conservative illustrative settings, not optimized or
validated profit guarantees. Daily reset defaults to UTC and accepts IANA zones.

The database commits intent and deterministic client UUID before any submission.
A conditional update claims the intent. Submissions are never blindly retried:
timeout/invalid response becomes UNKNOWN; REST searches by client ID and then
reconciles order status and unique fills. Acceptance is not a fill. Cancellation
acknowledgement remains pending until exchange status confirms it. Partial fills
update quantity, cash, cost basis, fees and realized P&L transactionally. Lagging
fill details remain UNKNOWN. Unsubmitted entry intents found on restart are
cancelled rather than submitted with an old risk decision. Existing unresolved
orders prevent new entries. No SELL can exceed recorded inventory.

Migration `0002` adds isolated managed ledgers, agents, orders, fills and audit
events. Money is stored as scaled integers at eight decimal places; order sizes
are rounded down to Coinbase increments. Existing tables are preserved.

User WebSocket messages wake REST reconciliation; only REST fill details update
the ledger. Reconnects request reconciliation. Polling continues independently
of WebSocket availability. Market refresh failures hold trading until recovery.

Pause stops entries while stop-loss, take-profit, maximum holding-time and manual
close monitoring continue. **Cancel entry orders** is separate. **Emergency
stop** defaults to cancelling entries without liquidation; `emergency_flatten`
explicitly enables closure. Resume from emergency requires review and reconfigure
while flat. Limits block new entries but do not suppress protective exits.
Protection is implemented in the running agent, not exchange-hosted brackets.
It depends on connectivity and the process staying online. Market IOC orders can
slip beyond estimated slippage, and stops cannot guarantee a maximum realized
loss. Dust below product minimums is held with an explicit rejection reason.

## Live adapter and remaining operational blockers

`coinbase_execution.py` implements CDP ES256 P-256 JWTs, account/key-permission
checks, preview, spot market IOC submission, cancellation, order lookup, paginated
fills, bounded GET retries, timeouts, and private user WebSocket reconnects.
All mutations require the backend `LIVE_EXECUTION_ENABLED` gate. Live mode also
requires `LIVE_OWNER_USER_ID`, `COINBASE_KEY_NAME`, `COINBASE_PRIVATE_KEY`, and an
explicit authenticated configuration request. A single backend key is bound to
one local identity; it is never shared across local users. The key must have
view/trade permissions and no transfer permission. Other exchange users need
separate credential/OAuth infrastructure before live support can be expanded.
Execution mode is fixed when a managed account is initialized. Use a separate
local account for another mode; paper and live performance histories are never
combined into a single ledger.

Live startup rejects unexplained XRP inventory or external open orders; it does
not invent acquisition cost for pre-existing holdings. Account availability is
verified. Secrets remain in backend environment variables and are not returned
by APIs or logged. Use HTTPS and `COOKIE_SECURE=true` outside local development.

No real account, key, private WebSocket or live order was exercised during this
task. The live adapter is implemented and locally tested with simulated responses;
real-account acceptance and operational readiness remain unverified. The current
model's missing approval/expected-return contract blocks strategy entries even
if an operator were to configure live mode. Leave live disabled.

## Authenticated dashboard contract

FastAPI schema: http://127.0.0.1:8000/docs and `/openapi.json`.
The dashboard calls `POST /auth/guest` automatically and uses an isolated
HTTP-only `crypto_session` cookie without asking for credentials. An existing
valid browser session is retained. Guest sessions expire after 12 hours; clearing
the cookie or expiration starts a new workspace and does not expose the previous
workspace. Guests cannot configure live execution. Existing account endpoints
remain for API compatibility, but the dashboard has no sign-in form. Mutations require
`X-Requested-With: CryptoAgent`; browser origins must match `ALLOWED_ORIGIN`.
All queries are scoped to the authenticated user. There is no user ID parameter
that grants access to another account.

| Endpoint | Contract |
|---|---|
| GET `/health` | Database readiness and current process worker state |
| PUT `/v2/agent/configuration` | `{mode:"paper", settings:{...StrategyConfig}}`; validated and audited |
| GET `/v2/agent/configuration` | Current mode and complete validated configuration |
| POST `/v2/agent/commands` | `{action, request_id}`; unique UUID, duplicate requests return existing acknowledgement |
| GET `/v2/agent/status` | Phase, reconciliation time, model status, wallet, equity/P&L, latest 100 orders/fills and 30 activity records |
| GET `/v2/agent/events?after=0` | SSE activity stream; user-scoped monotonic IDs; reconnect using Last-Event-ID |
| GET `/v2/agent/orders`, `/fills`, `/activity` | Cursor pagination with `after` record ID and `limit` up to 500 |
| GET `/v2/agent/prediction`, `/performance` | Latest prediction contract; equity, realized/unrealized P&L, fees and recorded drawdown |
| GET `/market/latest`, `/market/history` | Existing public quote/history views |
| GET `/agent/research/latest` | Existing model's actual research forecast or failure reason |

Commands: `start`, `resume`, `pause`, `cancel_entries`, `emergency_stop`,
`close_position`. A command acknowledgement is not a completed order or fill.
Orders expose `PENDING_SUBMISSION`, `SUBMITTING`, `ACCEPTED`, `PARTIALLY_FILLED`,
`FILLED`, `CANCEL_PENDING`, `CANCELLED`, `REJECTED`, `UNKNOWN`.

SSE example:
```
id: 42
event: activity
data: {"kind":"decision","timestamp":"...","data":{"action":"HOLD","reason_codes":["MODEL_NOT_APPROVED"],"equity":"1000"}}
```

Frontend integration (the existing Next proxy sends `/api/*` to FastAPI):
```typescript
await fetch('/api/v2/agent/commands', {
  method: 'POST', credentials: 'include',
  headers: {'Content-Type':'application/json','X-Requested-With':'CryptoAgent'},
  body: JSON.stringify({action:'pause',request_id:crypto.randomUUID()})
});
const stream = new EventSource('/api/v2/agent/events', {withCredentials:true});
stream.addEventListener('activity', event => console.log(JSON.parse(event.data)));
// On unmount: stream.close(); backend monitoring continues.
```

## Tests and evaluation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.check_coinbase_sandbox
.\.venv\Scripts\python.exe -m scripts.backtest_managed --limit 168
# Full saved development evaluation period; no tuning or final holdout consumption:
.\.venv\Scripts\python.exe -m scripts.backtest_managed --output reports/managed_full_replay.json
cd frontend
npm run build
```

The replay creates an isolated temporary migrated database, uses the same model
adapter, decisions, risk logic and ledger, and executes only after signal
availability at the next contiguous candle open. Signals cannot see that open.
It includes 0.6% illustrative fee per fill, 0.1% slippage and 0.1% full spread.
Hourly data cannot establish intrahour stop paths or realistic partial-fill
liquidity. Cash HOLD and buy-and-hold benchmarks use the exact replay interval.
No strategy thresholds are tuned by this command.

Actual 168-hour replay: **2025-06-21 00:00 to 2025-06-28 00:00 UTC**. Zero fills,
0% return, 0% drawdown, 0% exposure; win rate, average trade return and Sharpe are
undefined because there were no trades. Buy-and-hold after assumed costs:
**-0.4154%**. All 168 entries were blocked by model approval and missing expected
return. This is an integration result, not evidence of profitable trading.
Machine-readable results: `reports/managed_replay.json`.

The sandbox GET checks parsed four static mocked orders and an accounts list.
Sandbox responses do not demonstrate fill realism or profitability. No real or
sandbox submissions were made. The final chronological test set was not used.

Verification performed: full Python suite **102 passed, 1 skipped**; after the
final protective-exit and dashboard-state changes, the relevant backend/execution
suite **43 passed**. The final Next.js production build passed. A real local
backend startup returned healthy with an active worker and served OpenAPI.
The local database was backed up to
`crypto_agent.db.20261022T074219Z.bak` before migration to revision `0002`.

## Official references checked for this implementation

- [CDP API key authentication](https://docs.cdp.coinbase.com/coinbase-app/authentication-authorization/api-key-authentication)
- [Create order](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/create-order)
- [Preview orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders)
- [Public product book](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-book)
- [WebSocket endpoints](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-endpoints)
- [Sandbox limitations](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/sandbox)
