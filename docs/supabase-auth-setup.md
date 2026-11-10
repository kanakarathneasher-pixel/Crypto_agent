# Orbit email and password sign-in

Orbit's startup screen has email/password Sign in and Register. Supabase Auth
stores and verifies credentials. Orbit does not store the password: its database
only binds the verified Supabase user ID to an isolated paper workspace. Signing
in again with the same Supabase identity returns to that workspace. Existing
username/Google accounts are not automatically merged by matching email.

## Configure the project

In your Supabase project, enable the Email provider under Authentication. Copy
the Project URL and publishable key (a legacy anon key also works) from the
project's API settings. Add to the repository-root `.env`:

```dotenv
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
```

These are backend settings. A service-role key is not needed. Keep existing
`DATABASE_URL` and other settings. Supabase Auth and Orbit's workspace database
are separate: configuring Auth does not move local trading records to Supabase.
Use the external PostgreSQL setup for persistent hosted workspace data.

Under Authentication URL Configuration, set Site URL to `http://localhost:3000`
for local development. Set it to the exact public HTTPS frontend origin when
hosting and configure allowed redirect URLs as appropriate. Use
`ALLOWED_ORIGIN` with the same frontend origin in Orbit's backend.

With email confirmation enabled, Register sends a confirmation email and shows
an inbox message. Open the link, then sign in using the same email/password.
With confirmation disabled in Supabase, successful registration opens the
workspace directly. Configure SMTP in Supabase for production email delivery.
Orbit does not disable project email verification or password policy settings.

## Apply the migration and run

Back up the workspace database, then run:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Run `npm.cmd run dev` in `frontend/`, then open http://localhost:3000.
Restart the backend after changing `.env`. Render's startup script applies the
migration automatically; configure both Supabase environment variables there.
Use `COOKIE_SECURE=true` on public HTTPS deployments.

## Sessions and validation

The backend calls Supabase's signup or password-token endpoint and verifies the
resulting access token through the project's `/auth/v1/user` endpoint. It issues
Orbit's existing HttpOnly, SameSite session cookie, valid for 12 hours. Browser
refreshes restore that session through `/auth/me`; signed-out startup creates no
guest accounts. Passwords and provider tokens are not stored in browser storage
or Orbit's database. Sign out revokes the current Orbit session. Supabase
password resets or remote sign-out do not revoke existing Orbit cookies; they
expire under Orbit's normal session policy.

Automated tests mock Supabase and cover confirmation, repeat login, isolation,
logout, invalid credentials and service failures. A live signup/login test needs
your Supabase project configuration and an email account you control.

References:

- https://supabase.com/docs/guides/auth/passwords
- https://supabase.com/docs/guides/auth/redirect-urls
- https://github.com/supabase/auth
