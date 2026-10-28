# Connect your own Coinbase account to Orbit

This version supports one operator-owned Coinbase account, with View-only access.
Other users can create Orbit accounts, but cannot use the owner's exchange key.
Real Coinbase holdings appear on **Account**, separately from paper ledgers. The
connection does not enable live trading or send holdings to the chatbot.

## 1. Create your Orbit sign-in

Open http://localhost:3000, choose **Account**, and create an Orbit username and
password (at least 12 characters), or sign into an existing account. These are
Orbit credentials, not your Coinbase credentials. Registration creates a new
personal paper workspace; it does not merge your earlier guest history.

After signing in, the Account panel shows your **Orbit user ID**. Keep this ID
for the backend owner setting. This binding uses the numeric ID, not a public
username, and must be configured by the backend operator.

## 2. Create a dedicated Coinbase View-only API key

In Coinbase Developer Platform, choose **API Keys > Secret API Keys**, create a
key, and expand the restrictions/advanced settings:

- Select the portfolio you want Orbit to display.
- Enable **View** only. Disable **Trade** and **Transfer**.
- Choose **ECDSA / ES256** (P-256), not Ed25519.
- If using an IP allowlist, use the backend machine's public outbound IP.

Copy the key name and complete private key directly into local backend
configuration. Do not paste keys into chat or a frontend environment variable.

Coinbase's current instructions:
https://docs.cdp.coinbase.com/coinbase-app/authentication-authorization/api-key-authentication

## 3. Configure the backend

If `.env` does not exist, copy `.env.example` to `.env`. Preserve any existing
configuration. Add or update these values in the repository-root `.env`:

```dotenv
COINBASE_READONLY_OWNER_USER_ID=YOUR_ORBIT_NUMERIC_USER_ID
COINBASE_READONLY_KEY_NAME=organizations/YOUR_ORGANIZATION/apiKeys/YOUR_KEY_ID
COINBASE_READONLY_PRIVATE_KEY="-----BEGIN EC PRIVATE KEY-----\nYOUR_KEY_CONTENT\n-----END EC PRIVATE KEY-----\n"
LIVE_EXECUTION_ENABLED=false
```

Replace the example with your actual complete PEM, retaining its original header,
footer and newlines. Literal `\n` separators are supported; a quoted multiline
value is also supported. No private key is stored in the database or returned to
the browser. These read-only settings are independent of the existing live
execution adapter's credentials.

Restart FastAPI from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Stop the old backend before starting its replacement. Refresh Orbit's Account
page and select **Connect Coinbase**. Orbit checks the key's actual permissions
before connecting and again on every balance refresh. Keys with Trade/Transfer
permission are rejected. It makes only GET requests to Coinbase's key-permission
and account-list endpoints.

## 4. Verify and disconnect

The table shows available, held and total asset **units**, not a calculated USD
portfolio valuation. It includes only accounts/portfolios accessible to the key.
Use **Refresh balances** for a new timestamped snapshot; failed reads clear the
display rather than presenting old balances as current. This is real account
data, not Coinbase sandbox data.

**Disconnect** clears the saved connection marker. It does not delete the key
from backend configuration or revoke it on Coinbase. Delete the key in Coinbase
Developer Platform to revoke its access. Removing/replacing the configured key
or changing the owner prevents the old connection from being used.

## Other users later

Do not share this owner key with other Orbit users. Multi-user Coinbase access
requires OAuth onboarding and per-user encrypted token storage/refresh/revocation.
Coinbase currently documents restrictions on creating new OAuth clients:
https://docs.cdp.coinbase.com/coinbase-app/oauth2-integration/quickstart

The owner test does not implement that multi-user OAuth flow.
