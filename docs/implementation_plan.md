# Audit and implementation plan

Existing Binance scripts are working procedural scripts with import-time side effects. Preserve them and the 720-row Binance dataset, processed outputs and experimental Random Forest. Coinbase has 169 six-column candles. Backend and inference are placeholders; frontend is empty. Windows .venv works outside the execution sandbox. Node 24.19.0 and npm 11.17.0 are available. Installed pandas 3.0.6, NumPy 2.5.4, sklearn 1.9.1, XGBoost 3.4.1, FastAPI 0.151.0 and Pydantic 2.14.1 are retained. SQLAlchemy, Alembic, OpenAI, pytest, HTTPX, pydantic-settings and Argon2 are missing and will be installed.

1. Extend the existing checkpointed Coinbase collector with product verification and run it.
2. Add a Coinbase-only validated preprocessing and gap-aware causal feature pipeline; preserve Binance scripts.
3. Compare zero/RF/XGBoost chronologically with purged boundaries, walk-forward diagnostics, versioned artifacts, and an explicit promotion gate. Never approve the old Binance model for XRP-USDC.
4. Add migrated SQLAlchemy storage, opaque authenticated sessions, per-user settings, decimal balances, decisions, orders, fills, predictions and execution logs.
5. Implement public market monitoring, schema-checked inference, deterministic risk checks and transactional/idempotent paper execution. Use one OS-locked worker; no live adapter exists.
6. Add authenticated APIs, read-only chatbot tools and a responsive local Next.js dashboard.
7. Run offline tests, temporal backtests, production frontend build and local integration smoke checks; record actual results and limitations.

Development fee/slippage defaults are illustrative. No exchange credentials, live orders, automatic model promotion or guaranteed-profit claims.
