# Orbit application structure

Orbit uses a Next.js frontend on Vercel, one FastAPI service on Render, and
external PostgreSQL (such as Supabase) for persisted accounts. Local development
can continue to use SQLite. No database schema change is required by this refactor.

## Responsibility boundaries

| Layer | Responsibility | Main files |
| --- | --- | --- |
| Workspace shell | Navigation, connection state, notifications | `frontend/app/page.tsx`, `frontend/hooks/useWorkspace.ts` |
| Account feature | Password/Google access and separate Coinbase balance connection | `frontend/features/account/` |
| Dashboard feature | Overview, activity, risk form, research, read-only chat | `frontend/features/dashboard/` |
| Agent and market features | Managed agent controls and independent live price chart | `frontend/features/agent/`, `frontend/features/market/` |
| Browser API client | JSON parsing, status-bearing errors, browser cookies/CSRF headers | `frontend/lib/api.ts` |
| Workspace startup | Readiness retry and single guest/session-opening request | `frontend/lib/workspace.ts` |
| Vercel API boundary | Server-only backend origin, cookie forwarding and SSE streaming | `frontend/lib/backend-proxy.ts` |
| Backend composition | Lifespan, middleware, health and router registration | `backend/main.py` |
| Account creation | Shared initial paper balances/settings for every provider | `backend/accounts.py` |
| Account routes | Password login, registration, guest sessions and logout | `backend/routes/auth.py` |
| Dashboard routes/service | Authenticated summary from user-scoped views | `backend/routes/dashboard.py`, `backend/dashboard.py` |
| Existing API | Backwards-compatible paper endpoints and chat | `backend/routes/legacy.py` |
| External identities | Google verification and owner-only read-only Coinbase access | `backend/google_auth.py`, `backend/coinbase_account.py` |
| Persistence | Pooled connections, migrations and user-keyed records | `backend/database.py`, `backend/models.py`, `migrations/` |

## Requests and sessions

The browser calls only `/api/*` on its frontend origin. Vercel forwards the
browser's own cookie, original Origin and CSRF header to Render. FastAPI resolves
the authenticated user before accessing their rows. Database credentials remain
on Render. Supabase is the PostgreSQL host; Orbit authentication remains in
FastAPI, rather than Supabase Auth.

Startup checks `/health` up to five times for transient network/502/504 errors.
It then calls `/auth/guest` once to reuse the existing session or open a guest
workspace. Configuration/authorization errors are shown immediately. Sign-in,
account creation and agent commands are never automatically replayed.

`GET /dashboard` replaces ten browser requests with one account summary.
Foreground account snapshots refresh every 15 seconds with no overlapping
requests. Polling pauses on Account and while the tab is hidden. Failed refreshes
retain the previous snapshot with an error banner and last-update time. A 401
pauses polling and offers reconnection. The live chart retains its independent
stream and fallback; the managed agent uses SSE with a 15-second status fallback.

The older individual endpoints remain available for backwards compatibility.
Deploy the backend first and check `/openapi.json` includes `/dashboard`, then
deploy the frontend. Briefly mismatched versions can otherwise produce a 404
while Render is still deploying.

## Persistence and deployment

Every account provider uses the same workspace initializer. Returning sign-in
reuses the existing user ID; a guest's history is not silently merged into a
personal account. Google-only users sign in through Google. Coinbase connection
permissions and identity linking are unchanged by the layout refactor.

PostgreSQL pools are bounded to five connections plus two overflow connections
per process, with connection health checks before reuse and a ten-second pool
wait. Keep one Render instance/process because the worker lock is machine-local.
These checks do not make the worker distributed or Render Free always-on.

Use `ALLOWED_ORIGIN` on Render for the exact frontend origin and `BACKEND_URL`
on Vercel for the backend origin. See [Render setup](render-deployment.md).
Protect backend-owned Supabase tables from its public Data API as described
there; Orbit does not use Supabase client-side row policies for authorization.

## Validation

Frontend checks cover API errors, session headers, proxy boundaries and bounded
startup recovery. Backend checks cover registration, repeat login, logout,
Google identities, Coinbase permissions, aggregate dashboard isolation and the
existing paper APIs. Tests use disposable SQLite databases. PostgreSQL-specific
concurrency and deployment behavior need checks against a dedicated test database;
passing the SQLite suite is not evidence of live PostgreSQL verification.
