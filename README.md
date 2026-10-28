# Orbit — Coinbase paper-trading research agent

An integrated local Python/FastAPI + Next.js application for **XRP-USDC spot paper trading**. The background worker monitors Coinbase public data while FastAPI runs. Each user has authenticated, isolated settings, balances, positions, decisions, orders and fills. The chatbot has read-only tools. A separately gated live adapter is implemented but disabled and has not been exercised against a real account.

See [managed agent setup, model contract, dashboard APIs, recovery and tests](docs/managed-agent.md) for the new persistent execution service. Initialize it in the dashboard's **Managed spot agent** panel. The existing classifier remains observation-only; no model was retrained or automatically approved.

The dashboard opens directly with an isolated guest paper workspace. No sign-in
or registration is required. Guest access cannot enable live trading.

To test real account balances for your own Coinbase account, open **Account** in
the dashboard and follow [the View-only account setup](docs/coinbase-account-setup.md).
This owner-only connection keeps exchange holdings separate from simulated funds.

The Account page also supports **Continue with Google** for sign-in or linking an
existing Orbit account. Configure a Google Web client ID using the
[Google sign-in setup guide](docs/google-signin-setup.md).

Hosting on Vercel requires a separately running Python backend and the frontend
`BACKEND_URL` setting. Deploy only the self-contained [`frontend/`](frontend/README.md)
application to Vercel, with Root Directory `frontend`. Follow
[Vercel deployment and troubleshooting](docs/vercel-deployment.md).

For a free backend demo, use the [Render deployment guide](docs/render-deployment.md)
and repository-root `render.yaml`, with external PostgreSQL for persistent accounts.

**Current research result: no model qualified for promotion.** Monitoring and autonomous HOLD decisions work, but model-driven fills are blocked. The old Binance pipeline, dataset and experimental model are preserved. See [actual data, model and backtest results](docs/research_results.md).

## Windows setup and run

Use PowerShell from `C:\Users\KLC\Downloads\Crypto_agent`. Python 3.14 and Node 24 were used in verification. Node must meet Next.js's documented minimum (20.9+). Dependencies are pinned in Python requirements and the npm lockfile.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Copy `.env.example` only when you do not already have `.env`; preserve existing secrets. To allow Start/Stop paper controls, set `TRADING_ENABLED=true` in `.env` and restart the backend. Leave `TRADING_MODE=paper`. No model will be promoted by this setting.

Terminal 1:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open **http://localhost:3000** for direct guest access, then initialize the Managed spot agent panel. API documentation: **http://127.0.0.1:8000/docs**. Keep the frontend URL on `localhost` to match `ALLOWED_ORIGIN`. Both backend and frontend must remain running. Starting only Next.js leaves `/api/*` requests unable to reach the backend on port 8000. The development server binds loopback; hosted/mobile-device access requires a deliberately configured network deployment.

For a production frontend build locally:

```powershell
cd frontend
npm.cmd run build
npm.cmd run start
```

The Next.js `/api/*` proxy connects to FastAPI on 127.0.0.1:8000. The UI polls account data every 30 seconds; the backend polls public Coinbase data independently. Start/Stop changes only the authenticated user's state. Missing models produce logged HOLD explanations. An empty trade history is expected until an eligible model is explicitly promoted and all deterministic controls pass.

## Data and research commands

```powershell
# Five-year target window, actual available Coinbase history only; automatic resume.
.\.venv\Scripts\python.exe src\coinbase_data_loader.py

# Reusable validation and causal feature generation, separate from Binance files.
.\.venv\Scripts\python.exe -m src.coinbase_pipeline

# Train versioned research candidates; never auto-promote.
.\.venv\Scripts\python.exe -m src.research train

# Frozen candidate backtest; replace the directory with your actual candidate version.
.\.venv\Scripts\python.exe -m src.backtest models/coinbase-20261020T121949544468Z
```

The successful initial run used 28,662 Coinbase candles and produced 28,446 supervised observations. A later training invocation requires at least 200 **new, previously untested** holdout hours; an immediate rerun correctly stops. Models use fixed initial conservative parameters, train-only walk-forward diagnostics, purged chronological boundaries, and validation-only candidate selection. Final-test performance is reported once, never used to choose a different model retrospectively. Fees/slippage and strategy thresholds must not be repeatedly optimized against that final test period.

The approved-model pointer is `models/approved.json`. There is currently no approved pointer. Only a candidate meeting the baseline/walk-forward gate can be explicitly promoted:

```powershell
.\.venv\Scripts\python.exe -m src.research promote --directory models/YOUR_ELIGIBLE_VERSION
```

Failed candidates are denied. A promoted incumbent is compared on newly unseen data, and its replacement must improve both MAE and RMSE. Promotion checks artifact integrity and changes an atomic pointer; it never overwrites the Binance model. Artifact loading is restricted to trusted local `models/` paths because joblib is capable of executing code.

Weekly/monthly retraining can be run through Windows Task Scheduler using `.venv\Scripts\python.exe` with arguments `scripts\retrain.py` and **Start in** set to this project root. It refreshes historical data, trains a candidate only with sufficient new holdout data, and never promotes automatically. Review metrics and backtests before a separate promotion. Do not run the standalone downloader concurrently with retraining; use one historical writer.

## Risk and paper execution

- Every eligible order passes deterministic checks independent of ML and chat: operator/user enable flags, emergency stop, fresh market data, available/matching prediction, approved model, daily fill count, daily paper loss, balances, inventory and position/allocation caps.
- BUY/SELL forecasts must exceed both a configured signal threshold and estimated round-trip costs. A forecast is not a probability. HOLD can continue indefinitely.
- Automatic BUY sizing uses at most 2% of available cash, further capped by risk limits. Automatic SELL sizing reduces available inventory. Manual notionals must fit every cap or are rejected. No short selling, leverage or negative balances are allowed.
- Hard administrator caps: 50 fills per UTC day, 10,000 USDC maximum asset position, 25% asset allocation, and 10,000 USDC daily loss limit. Users may choose lower limits. Position caps constrain new buys; market price changes can later increase position value.
- Fees default to **0.6% per fill** and slippage to **0.1%**. These are illustrative, not verified against your Coinbase fee tier. Both are charged in simulated execution. Known execution costs are capped by the remaining daily-loss budget.
- Daily loss is equity relative to the first monitored evaluation of each UTC day. It includes realized/unrealized price moves and costs after that mark. It cannot reconstruct an unobserved midnight valuation following downtime and is not a guaranteed price-loss stop.
- SQLite uses an immediate write transaction; PostgreSQL uses a user-row lock. A unique user/product/candle key and one order/fill per decision prevent duplicates. Decision, prediction, order, fill and balances commit together or roll back together. No execution endpoint accepts a user-supplied order.

## Chatbot

Set `OPENAI_API_KEY` and `OPENAI_MODEL` in your untracked `.env` if desired, then restart FastAPI. Choose a model available to your account that supports Responses function tools. The implementation follows the [official OpenAI function-calling documentation](https://developers.openai.com/api/docs/guides/function-calling).

The backend forces an authenticated state read before the answer and exposes no mutation tools. It supplies current stored market/account/prediction/decision data with freshness metadata. It does not send passwords, session tokens or exchange-secret references. Missing configuration returns a clear unavailable message while the dashboard and agent remain usable. Actual provider calls require your account/key; only mocked provider calls were tested here. Chat is single-turn with current state; conversation text is shown locally and is not persisted as account history.

## Tests and verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm.cmd run build
```

Tests cover downloader retries/resume/backups, timestamp parsing, invalid candles, gap-aware causal features, feature ordering, model integrity, inference, deterministic risk controls, UTC day rollover, decimal accounting, transactional rollback, concurrent-cycle idempotency, authentication, CSRF, user isolation, read-only chatbot tools and the worker lock. Tests use temporary migrated databases and synthetic data clearly confined to tests.

`scripts/preview_backend.py` starts a disposable `.qa/preview.db` on port 8000 with paper execution enabled. With that preview and the frontend running, `scripts/smoke_local.py` verifies the actual HTTP proxy, market monitor, autonomous HOLD, Start/Stop, chat fallback and logout. Use this script **only with the disposable QA backend**, not an existing personal account database. It creates a randomly credentialed test account and does not print/save its password. This integration check passed. No browser was available to visually verify the responsive layout.

## Architecture and operations

| Component | Location |
| --- | --- |
| Public historical transport, checkpoints and backups | `src/coinbase_data_loader.py` |
| Coinbase cleaning and features | `src/coinbase_pipeline.py` |
| Model comparison, promotion and backtest | `src/research.py`, `src/backtest.py` |
| Exact-schema approved-model inference | `src/prediction.py` |
| Account/session security and Pydantic validation | `backend/auth.py`, `backend/schemas.py` |
| FastAPI routes and read-only account views | `backend/main.py`, `backend/views.py` |
| Deterministic risk and transactional paper execution | `backend/risk_manager.py`, `backend/trading_agent.py` |
| Public monitoring and one scheduler | `backend/coinbase_client.py`, `backend/worker.py` |
| SQLAlchemy models and Alembic schema revisions | `backend/models.py`, `migrations/` |
| Read-only OpenAI integration | `backend/chat.py` |
| Responsive authenticated dashboard | `frontend/app/` |

The schema stores monetary/quantity values as integers scaled by 100,000,000, avoiding SQLite floating-point storage. User-scoped database queries derive identity from a hashed, revocable, 12-hour opaque session, never a requested user ID. Passwords use Argon2; cookies are HttpOnly and SameSite Strict. State-changing browser calls require an allowed origin and custom CSRF header. Local authentication/chat rate limiting is in-process; hosted multi-worker deployment needs a shared limiter. There are no default accounts or hardcoded secrets. Future exchange integration may store only a vault reference, never plaintext credentials.

Run `alembic upgrade head` before serving. Schema creation never happens in normal app startup. The initial migration is frozen into explicit operations; subsequent changes need new reviewed Alembic revisions. Back up the SQLite file before migrations. For PostgreSQL, install a compatible PostgreSQL driver, change `DATABASE_URL`, run migrations and verify locking/integration tests against that database. PostgreSQL has not been exercised in this local run.

The worker is started through FastAPI lifespan, polls at the configured interval and obtains an OS file lock keyed by the database URL. Reloads/multiple local workers cannot own the scheduler simultaneously. All such processes must share the same project working directory and identical database URL. This is a **single-machine prototype**, not a distributed scheduler. Persisted settings and unique decisions make restarts safe; downtime hours are not replayed as retroactive fills. Failed market fetches log an error and do not trade on cached prices. SQLite and `.env` must have appropriate filesystem access controls.

True 24/7 monitoring requires a continuously running machine/server. Before hosting, configure HTTPS, secure cookies, restricted origins, backups, shared rate limits, monitoring, production registration policy and server lifecycle supervision. Mobile browser layout is implemented; reaching the local app from a physical phone requires an explicitly secured network deployment. SOL-USDC is a future extension: product-keyed storage is ready, but product validation, configuration, model training/schema and tests must be added before enabling it. Live trading is intentionally absent.
