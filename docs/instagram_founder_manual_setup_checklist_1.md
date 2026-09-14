# Instagram Founder Manual Setup Checklist

Two independent action groups remain that code cannot complete. Neither requires pasting any
secret into this chat - both are configured directly in their own respective systems, then only a
non-secret PRESENCE check is run here to confirm readiness.

---

## Group A — Meta credentials

### A1. Register/confirm the Meta app and complete Business Login for Instagram

- **WHAT TO OPEN**: [Meta for Developers](https://developers.facebook.com/) console.
- **WHAT TO CREATE/CONNECT**: an app configured for "Instagram API with Instagram Login" (NOT
  Facebook Login for Business - see `docs/instagram_meta_production_setup_1.md`). Connect it to
  the real NINJA PULSE Instagram professional (Business or Creator) account.
- **WHAT PERMISSION/SETTING TO ENABLE**: request `instagram_business_basic`,
  `instagram_business_manage_insights` (already used, read-only), and
  **`instagram_business_content_publish`** (new - required for any real write). Submit for Meta
  App Review if the app is not already Live-mode-approved for this scope.
- **WHAT NON-SECRET IDENTIFIER THE CODE NEEDS**: the resulting numeric Instagram user id
  (`ig-user-id`, from the token's own `/me` response).
- **WHERE IT SHOULD BE CONFIGURED**: production `.env` (service-specific override for
  `content_worker`/`backend`, never the shared file if other services would reject the new key -
  mirrors the Telegram unified-flag rollout's own established pattern), as
  `INSTAGRAM_BUSINESS_ACCOUNT_ID`.
- **HOW CLAUDE CAN VERIFY IT WITHOUT PRINTING SECRETS**: `printenv | grep -c
  '^INSTAGRAM_BUSINESS_ACCOUNT_ID='` inside the container (prints `1` or `0`, never the value).

### A2. Complete the OAuth exchange and store the long-lived token

- **WHAT TO OPEN**: the Business Login for Instagram authorize URL
  (`https://www.instagram.com/oauth/authorize`, per `design/instagram_official_api.md`).
- **WHAT TO CREATE/CONNECT**: complete the interactive login once, exchange the short-lived code
  for a token, then exchange that for a 60-day long-lived token (both documented calls, operator-
  run, never automated by this codebase).
- **WHAT PERMISSION/SETTING TO ENABLE**: none further - the scopes were already requested in A1.
- **WHAT NON-SECRET IDENTIFIER THE CODE NEEDS**: the token's own expiry date/time (not the token
  itself).
- **WHERE IT SHOULD BE CONFIGURED**: `INSTAGRAM_ACCESS_TOKEN` (the token, as a secret env value -
  never committed, never pasted into any chat) and `INSTAGRAM_ACCESS_TOKEN_EXPIRES_AT` (a plain
  timestamp) in the same service-specific override.
- **HOW CLAUDE CAN VERIFY IT WITHOUT PRINTING SECRETS**: `printenv | grep -c
  '^INSTAGRAM_ACCESS_TOKEN='` (presence only) plus, once present, a REAL read-only call via
  `services.instagram_account_reader.InstagramAccountReader.check_connection()` - confirms the
  token is accepted and reports which account it resolves to (compare against the intended NINJA
  PULSE `username` before anything else happens - §5's own explicit "if ambiguous or unexpected:
  STOP before writing").

---

## Group B — Media hosting infrastructure

### B1. Provision a real, public HTTPS endpoint for Instagram media

- **WHAT TO OPEN**: the hosting/DNS provider already used for this project (or a new one, if none
  exists yet - none was found in this codebase's own infrastructure).
- **WHAT TO CREATE/CONNECT**: one of:
  1. A domain name (or a subdomain of an existing one) pointed at the production host, plus a TLS
     certificate (e.g. via Let's Encrypt/Caddy/nginx) reverse-proxying to the existing `backend`
     service's already-built `/media/instagram/{asset_id}.jpg` route (this phase's own code,
     `app/routes/instagram_media.py` - already real and tested, needs only real HTTPS ingress in
     front of it), **or**
  2. A managed object-storage service with public-HTTPS-by-default (e.g. an S3-compatible bucket
     with a CDN in front) - would require a small, separate follow-up wiring change to upload
     instead of serving locally (not built this phase, since the choice of provider is itself the
     Founder decision this checklist exists for).
- **WHAT PERMISSION/SETTING TO ENABLE**: whichever the chosen approach needs (e.g., DNS A/CNAME
  record, TLS cert issuance, or a bucket's public-read policy scoped ONLY to the media path -
  never the whole bucket/filesystem).
- **WHAT NON-SECRET IDENTIFIER THE CODE NEEDS**: the resulting base URL, e.g.
  `https://media.ninjapulse.example`.
- **WHERE IT SHOULD BE CONFIGURED**: `INSTAGRAM_MEDIA_PUBLIC_BASE_URL` in production `.env`
  (service-specific override, `content_worker`/`backend`).
- **HOW CLAUDE CAN VERIFY IT WITHOUT PRINTING SECRETS**: `services.instagram_media_hosting.
  media_hosting_readiness()` - reports `media_hosting_ready: true/false` from a real HTTPS-scheme +
  real DNS-resolves-to-a-public-address check (no secret involved; the base URL itself is not a
  secret). A final end-to-end confirmation (a real `curl` against the real public URL from outside
  the production network) is a reasonable one-time manual smoke test the Founder or Claude can run
  together once B1 is live.

---

No step above requires sending a token, password, or client secret into this chat. Every
verification Claude can run reports only booleans/non-secret identifiers.
