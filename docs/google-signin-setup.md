# Google sign-in for Orbit

Orbit uses the official Google Identity Services button in **Account**. It sends
the Google ID token to the backend, which verifies its signature, issuer,
audience, expiry, verified email and a short-lived browser-bound nonce. Tokens
are discarded after verification; users receive Orbit's normal HttpOnly session.

## Configure Google Cloud

1. Open https://console.cloud.google.com/ and select or create your project.
2. In **Google Auth Platform**, configure branding, audience and the consent
   screen. While using a Testing audience, add the Google accounts you want to
   test under Test users as required by your project's Google configuration.
3. Create an OAuth client with application type **Web application**.
4. Add `http://localhost:3000` to **Authorized JavaScript origins**. Add the exact
   public HTTPS frontend origin separately when deploying. Origins have no path
   or trailing slash. Use the same frontend address when opening Orbit.
5. Copy the client ID (ending in `.apps.googleusercontent.com`). This popup flow
   uses a JavaScript callback, so it needs no OAuth redirect URI or client secret.

Add to the repository-root `.env` (backend configuration):

```dotenv
GOOGLE_CLIENT_ID=YOUR_WEB_CLIENT_ID.apps.googleusercontent.com
```

No new Python/npm dependency is needed. Keep `COOKIE_SECURE=true` for public
HTTPS deployments. The browser loads Google's SDK only when Google sign-in is
configured and the Account page is opened; password sign-in continues to work if
the SDK is blocked.

## Apply the schema and restart

Back up the existing database before migrating. For the normal SQLite database,
use SQLite's backup API for a consistent copy if the service is running. Then:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Stop the previous backend before starting its replacement. Refresh **Account**
and select **Continue with Google**. Allow the Google popup. If a sign-in attempt
expires after five minutes, use **Try Google again** to get a new challenge.

## Existing Orbit users

To preserve your current user ID and Coinbase owner binding, sign into your
existing Orbit account first, then use the Google button to link that account.
Future Google sign-ins will open the same Orbit account. Existing password login
remains available. A Google account already linked to another Orbit user cannot
be linked to your current account.

For new users, Google sign-in creates a personal paper workspace with a generated
Orbit username. Guest paper history remains separate. Google-only users do not
have a password login. The stable Google `sub` claim identifies the account;
email addresses never automatically merge or link existing Orbit accounts.

Google authentication does not authorize access to Coinbase. The owner-only
read-only Coinbase connection still needs its separate configuration. Multi-user
Coinbase OAuth is a separate integration.

## Validation

Automated tests use locally signed synthetic Google-shaped tokens and mocked
public keys; they never sign into Google or access a real Google account. Actual
end-to-end Google sign-in requires your configured client ID and your own Google
sign-in in the browser.

Official references:
- https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid
- https://developers.google.com/identity/gsi/web/guides/display-button
- https://developers.google.com/identity/gsi/web/guides/verify-google-id-token
