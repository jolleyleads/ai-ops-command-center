# Google workspace sign-in

This adds Google identity sign-in for approved accounts to the existing single
operator workspace. It does not create customer tenants, change database schemas,
connect a new Gmail mailbox, or grant access to arbitrary Google users.

## Production activation

When Google Cloud is unavailable, the identity flow can reuse the existing
approved Gmail callback by setting `GOOGLE_LOGIN_REDIRECT_URI` to the current
`GOOGLE_OAUTH_REDIRECT_URI` (for this service,
`https://ai-ops-command-center.onrender.com/oauth/google/callback`). Identity
login starts and finishes on that origin, then opens the same `/chat-operator`
interface there. Its host-only session cookie stays on that origin. Matching
browser-bound identity state is dispatched to identity verification before the
mailbox callback; Gmail grants and database records are untouched. The custom
domain remains available, but sessions do not transfer between the two hosts.
Use the custom-domain callback below when it can be registered with Google.

1. In the existing Google OAuth web client's authorized redirect URIs, **add**
   `https://automakeai.live/auth/google/callback`. Preserve the existing Gmail
   callback and all other redirect URIs. This is an identity-only flow using
   `openid email`; it does not request Gmail/Calendar permissions.
2. On the production service set `GOOGLE_LOGIN_ALLOWED_EMAILS` to the comma-separated
   list of explicitly approved workspace owners (initial owner: `jolleyleads@gmail.com`).
   Set `GOOGLE_LOGIN_REDIRECT_URI=https://automakeai.live/auth/google/callback`.
3. Reuse the server's existing `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, or
   configure a separate Google web client through `GOOGLE_LOGIN_CLIENT_ID` and
   `GOOGLE_LOGIN_CLIENT_SECRET`. Never place client secrets or operator tokens in
   client-side code, URLs, documentation, or logs.
4. Confirm a strong `SECRET_KEY` and existing `OPERATOR_CONTROL_TOKEN` are configured.
   Missing configuration fails closed. No credential values need to be shown.
5. Deploy this change, open `/login`, complete Google sign-in with the approved
   account, and verify My Leads and campaign settings. Confirm an unapproved account
   is rejected, logout works, and unauthenticated dashboard requests return 401.

Google identities expire after eight hours. Removing an email from the allowlist
or rotating the operator control token invalidates its Google workspace session.
The token remains available for existing backend jobs and API integrations; users
do not type it during Google login. `/operator/login` redirects to the Google login
page when Google login is configured. Existing token POST login remains for backend
compatibility. Customer navigation uses `/login`.

Public self-service sign-up is intentionally not enabled because current lead,
campaign and mailbox records belong to one shared operator workspace. Add and test
tenant ownership boundaries before admitting unrelated customer accounts.

## Validation

Run tests with an isolated SQLite database, never the production database:

```sh
DATABASE_URL=sqlite:///:memory: python -m pytest tests/test_customer_auth.py tests/test_customer_dashboard.py tests/test_v1_ops_release_gate.py tests/test_business_campaign_flow.py -q
```

These tests mock Google responses. A real Google login still requires the provider
callback registration and production configuration above.
