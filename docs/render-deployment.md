# Deploy Orbit's backend to Render Free

Use the repository-root `render.yaml` Blueprint. This deploys only Python;
keep the Next.js frontend on Vercel. The Blueprint creates no paid resources.

## Before deployment

Create an external PostgreSQL database, for example a Supabase project. For
Supabase, use the **Session pooler** connection string for IPv4 compatibility.
Keep the database password in Render's secret environment variable editor.
Use a private application schema or disable the Supabase Data API for these
backend-owned tables; Orbit currently enforces user access through FastAPI,
not Supabase Auth/RLS policies. Do not expose its tables to anonymous clients.

This deployment keeps Orbit's existing account/password and Google sign-in
implementation. It does not switch to Supabase Auth. It starts with a fresh
database; local SQLite accounts and history are not copied automatically.
Preserve `crypto_agent.db` and its backups for a separate data migration.

## Create the service

1. Open https://dashboard.render.com/ and select **New > Blueprint**.
2. Connect `kanakarathneasher-pixel/Crypto_agent`, branch `main`.
3. Use `render.yaml` at the repository root and confirm the service is **Free**.
4. Supply these values when prompted:

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | External PostgreSQL connection URI; URI-encode password characters |
   | `ALLOWED_ORIGIN` | Exact stable frontend origin, such as `https://your-app.vercel.app`; no trailing slash |

5. Deploy. The start script requires PostgreSQL with TLS, applies Alembic
   migrations, then starts Uvicorn on Render's `PORT` with one process.
6. Check `https://YOUR-SERVICE.onrender.com/health` returns `status: ok`.
7. Set the Vercel frontend's `BACKEND_URL` to that Render HTTPS origin, without
   `/api` or a trailing path. Redeploy the frontend.
8. Check `https://YOUR-FRONTEND/api/health`, then register/sign in and verify
   the same account can sign in after a backend restart.

If creating a Web Service manually, leave **Root Directory** empty, choose
Python and Free, and copy the build/start commands and variables from
`render.yaml`. Do not set Root Directory to `frontend` or `backend`.

## Operation

Paper trading controls initially remain disabled (`TRADING_ENABLED=false`).
After reviewing the deployment, set it to `true` to allow paper Start/Stop.
Live execution remains disabled. Optional Google sign-in uses `GOOGLE_CLIENT_ID`
on Render and the public frontend origin in Google's authorized origins.
Optional chat credentials also belong only in Render's environment editor.

Keep exactly one service instance with one Uvicorn process: the worker lock is
local to a machine and does not coordinate separate Render instances. PostgreSQL
is supported in code, but real PostgreSQL integration/concurrency checks must
pass before relying on this deployment for trading workflows.

Render Free sleeps after 15 minutes without inbound traffic; the market agent
stops while it sleeps. Waking can take about a minute, which can exceed the
frontend proxy timeout; retry after startup. This is a demo, not a 24/7 agent.
If startup exceeds free memory, use a larger instance rather than removing risk
checks. Model binaries are not in GitHub: predictions stay unavailable/HOLD
until trusted model artifacts are separately installed. No model is promoted
by deployment.

Official references:
- https://render.com/docs/blueprint-spec
- https://render.com/docs/deploy-fastapi
- https://render.com/docs/free
- https://supabase.com/docs/guides/database/connecting-to-postgres
