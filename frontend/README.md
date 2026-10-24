# Orbit dashboard — Vercel application

This folder is a standalone Next.js application. Set **Vercel Root Directory to
`frontend`**. It builds with Node.js 24 and npm; Python, models, datasets and the
trading worker are not part of this deployment.

```
frontend/
  app/                       Dashboard pages, styles and chart components
    api/[...path]/route.ts   Same-origin API proxy on the Node.js runtime
  lib/
    api.ts                   Browser JSON/error handling
    backend-origin.mjs       Backend URL validation, used only on the server
    backend-proxy.ts         Cookies, timeouts and streaming to Python
  tests/                     API routing, session and deployment tests
  .env.example               Example configuration, with no credentials
  next.config.ts             Next.js configuration, with no external rewrites
  vercel.json                Vercel framework/install/build defaults
  package.json               Node version and application scripts
  package-lock.json          Reproducible npm dependency installation
```

## Vercel settings

| Setting | Value |
|---|---|
| Root Directory | `frontend` |
| Framework | Next.js |
| Node.js | 24.x |
| Install | `npm ci` |
| Build | `npm run build` |
| Output Directory | Leave at the Next.js default |
| Environment variable | `BACKEND_URL=https://YOUR-PYTHON-BACKEND` |

Use a public HTTPS **origin**, without `/api` or another path. Configure the
variable for each deployment environment that should connect to the backend,
then redeploy. Keep it server-side; do not use a `NEXT_PUBLIC_` variable for it.

The frontend can build and deploy without this variable. API requests then
return a clear JSON 503 setup message. That is not a working trading backend:
you still need the Python service to use guest portfolios, market data or agents.
No demo predictions, prices or balances are substituted.

## Python service

Run the Python service separately on a continuously running host with persistent
storage. Its settings must include the exact dashboard origin:

```dotenv
ALLOWED_ORIGIN=https://YOUR-DASHBOARD.vercel.app
COOKIE_SECURE=true
LIVE_EXECUTION_ENABLED=false
```

Migrations, risk configuration, model installation and worker operation belong
to that service. See [the full deployment guide](../docs/vercel-deployment.md).

## Local development

From this folder:

```powershell
npm ci
npm run dev
```

The API proxy defaults to `http://127.0.0.1:8000` locally. Start Python in another
terminal from the repository root. An optional `.env.local` can override
`BACKEND_URL` for development. Never commit it.

## Checks and production preview

```powershell
npm run check
npm run build
npm start
```

`npm start` uses the host's `PORT` when provided. Do not build into the same
`.next` directory while `npm run dev` is running; stop development first or use
a separate checkout for build verification.

## API boundary

Browser requests stay on `/api/*` at the dashboard origin. The route handler
forwards them to the Python backend without adding `/api` to the backend path.
It preserves each browser's session cookie, CSRF header and original Origin;
streams SSE without buffering; and disables caching of user responses.
It does not execute trading logic, store credentials, or run the worker.

Missing configuration, network failures and response-header timeouts return
JSON 503/502/504 errors rather than HTML or misleading route-not-found errors.
Authorization responses from Python retain their original status. The proxy
does not retry order/control requests or follow redirects. Headers must arrive
within 15 seconds; established event streams last until the client/platform
disconnects them. The route declares a 60-second Vercel function duration, so
EventSource reconnects and the existing two-second polling fallback remain useful.

After deployment verify `/api/health`, then open the dashboard and confirm that
`POST /api/auth/guest` creates a guest session without a login screen.

## Verification of this structure

The 14 frontend tests and TypeScript checks passed. An isolated frontend-only
production build passed with `VERCEL=1` and no `BACKEND_URL`, Python installation,
model files or datasets in the build directory. A production preview served the
page with HTTP 200 and an actionable API 503 when unconfigured. With a running
Python backend, health, guest creation, portfolio and chart requests returned
200; guest cookies and live SSE events survived the proxy; an invalid Origin
still returned 403. These are local production-preview checks, not a claim that
your public Vercel/backend settings have been configured.
