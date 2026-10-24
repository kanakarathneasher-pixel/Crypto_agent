# Deploy the dashboard on Vercel

The existing application has two running services: a Next.js dashboard and a
Python FastAPI backend. Uploading the frontend to Vercel does not start
`backend.main:app` on your computer or deploy its worker automatically.

## 1. Deploy the Python backend

Run the repository root on a continuously running Python host with HTTPS,
outbound Coinbase REST/WebSocket access, and persistent disk. Keep one backend
process/instance for this local-prototype worker and SQLite architecture.
Do not rely on an ephemeral filesystem for paper balances or guest sessions.

Install: `python -m pip install -r requirements.txt`

Before starting, apply migrations: `python -m alembic upgrade head`

Start: `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1`

If your host requires its own `PORT`, use that assigned port in the start command.
The host's public HTTPS endpoint routes to this internal process port.

Backend environment variables:

```dotenv
# Replace with the exact stable Vercel dashboard origin, without trailing slash.
ALLOWED_ORIGIN=https://your-dashboard.vercel.app
COOKIE_SECURE=true
WORKER_ENABLED=true
WORKER_POLL_SECONDS=2
TRADING_MODE=paper
LIVE_EXECUTION_ENABLED=false
# Example only: /var/data must be a real mounted persistent directory.
DATABASE_URL=sqlite:////var/data/crypto_agent.db
```

Retain the other paper risk settings from `.env.example`. No Coinbase private
key is required. Preview domains are not automatically authorized; use the
configured stable dashboard domain. Do not disable origin or CSRF checks.

Check `https://YOUR-BACKEND/health` and `https://YOUR-BACKEND/docs` before linking
Vercel. `/health` must return JSON. The deployed commit must include
`POST /auth/guest`; an older backend can return 404 even when healthy.

Model binaries and selected-model pointers are ignored by Git. Transfer trusted
model artifacts to the backend's `models/` directory separately if inference is
required. Guest access and public market charts work without model binaries;
predictions remain unavailable/HOLD until the artifacts are installed. Do not
invent predictions or automatically approve a model during deployment.

## 2. Configure Vercel

Use the existing GitHub repository:

- Framework preset: **Next.js**.
- Root Directory: **frontend**.
- Install command: `npm ci`.
- Build command: `npm run build`.
- Output directory: Next.js default; do not use static export or `out`.
- Environment variable, in the selected deployment environment:
  `BACKEND_URL=https://YOUR-PUBLIC-PYTHON-BACKEND`.

`BACKEND_URL` is a server-side build setting. It must be the HTTPS origin only,
without `/api`, credentials, or another path. This repository's backend endpoints
are `/auth/guest`, `/market/latest`, etc., rather than `/api/auth/guest`.
After changing it, **redeploy** the frontend; existing builds keep their rewrites.
Vercel builds deliberately fail when BACKEND_URL is missing or points at localhost.

The browser continues using `/api/*` on the dashboard origin. The Next.js external
rewrite proxies to the Python backend and passes cookies, keeping guest sessions
on the dashboard's origin. Do not change the browser to call the backend directly;
that would require a different cross-site cookie design.

## 3. Verify

1. Open `https://YOUR-DASHBOARD/api/health`. It should show backend health JSON.
2. Open the dashboard. Its automatic `POST /api/auth/guest` should return 200
   and an HTTP-only secure session cookie.
3. `GET /api/agent/status` and `/api/market/chart/latest` should return 200.
4. The chart should show live data or an honest stale/reconnecting state.

If `/api/health` is 404, inspect the Vercel root directory, framework and deployed
rewrites. If health works but guest access is 404, check that the backend has
the current `/auth/guest` endpoint and BACKEND_URL has no extra `/api` prefix.
403 on guest access usually means ALLOWED_ORIGIN does not exactly match the
dashboard domain. Repeated 401 after successful guest creation means the cookie
is not being preserved; inspect Set-Cookie in the browser network panel.

The UI's two-second REST polling remains a fallback if a hosting proxy buffers
or interrupts SSE streams. A serverless frontend deployment does not provide
the continuously running worker, persistent SQLite disk, or model artifacts.

Official references:
- https://vercel.com/docs/routing/rewrites
- https://vercel.com/docs/environment-variables
- https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites
