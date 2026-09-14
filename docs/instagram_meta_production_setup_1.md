# Instagram / Meta Production Setup — Current Official Requirements

Verified against Meta's current (2026) developer documentation via live search this phase
(`developers.facebook.com/docs/instagram-platform/*`) - not from stale training memory. Extends
the repository's own existing `design/instagram_official_api.md` (read-only contract) with the
write-side requirements this phase adds.

## Required Instagram account type

**Professional account** - Business or Creator. A personal account cannot publish via any official
API (Basic Display API, the personal-account read path, was shut down December 2024).

## Required Meta/Facebook linkage

**None required.** This repository correctly uses **Instagram API with Instagram Login**
("Business Login for Instagram") - the direct-Instagram OAuth path. It does **not** need a linked
Facebook Page (that would be the separate "Facebook Login for Business" route, not used here).

## Required app/account IDs

- An Instagram **app** registered in the Meta Developer Console (app id + app secret) is needed
  ONLY to run the one-time OAuth exchange (steps 1-2 below) - this repository does not store the
  app id/secret at all (deliberately, per the existing design doc's "do not invent redundant
  credentials").
- The resulting **numeric Instagram user id** (`ig-user-id`, from the token's own `/me` response)
  is what the codebase stores as `settings.instagram_business_account_id`.

## Required token type

A **long-lived Instagram User access token** (60-day validity, refreshable).

## Required permissions/scopes

| Scope | Purpose | Already used by this repo? |
|---|---|---|
| `instagram_business_basic` | profile + media read | Yes (read-only account reader) |
| `instagram_business_manage_insights` | insights read | Yes, optional/detected |
| **`instagram_business_content_publish`** | **create + publish media containers - REQUIRED for any real write** | **No live token exists with this scope today; this is the credential gap** |

## Token validity requirements

- Short-lived token (from the initial OAuth redirect) -> exchanged once for a long-lived token
  (60 days).
- Refresh any time the token is >= 24h old and before it expires, via
  `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token`.
- This repository does **not** automate any of steps 1-3 (issuance/exchange/refresh) - they remain
  an operator-run, out-of-band runbook (unchanged from the existing design doc's own stance).

## API version

`v23.0`, pinned via `settings.instagram_api_version` - current, confirmed via live search this
phase. A version bump is a one-line config change.

## Webhook/review/app-mode requirements

- **App Review**: the Meta app must be approved for `instagram_business_content_publish` (a
  standard Meta App Review submission - screenshots/use-case description, reviewed by Meta,
  typically days to a few weeks). Cannot be done by this codebase; this is entirely an operator/
  Founder-side Meta Developer Console action.
- **No webhook is required** for the publish flow itself (webhooks are used for
  comments/mentions/live-video events, none of which this phase touches).
- The app can operate in **Live mode** once approved for the specific scope requested - no special
  "app mode" beyond normal App Review is needed for basic content publishing.

## Read-only verification commands/endpoints (safe - no write, no secret printed)

Once a token is configured, `services/instagram_account_reader.py::InstagramAccountReader.
check_connection()` (built on `fetch_account_context()`/`fetch_account_insights()`) already
implements the correct, bounded, real verification sequence:

1. `GET https://graph.instagram.com/v23.0/{ig-user-id}?fields=id,username,account_type,media_count` -
   confirms the token is accepted and identifies exactly which account it authorizes (compare
   `username` against the intended NINJA PULSE account **before** any write is ever attempted -
   §5's own "if the resolved account is ambiguous or unexpected: STOP before writing").
2. `GET https://graph.instagram.com/v23.0/{ig-user-id}/insights?...` - capability probe (optional
   scope; a permission failure here does not block profile/media reads).

Neither call is a write. Both are already real, tested, and safe to run the moment a token exists.

## Safe production env variable names this codebase reads

```
INSTAGRAM_ACCESS_TOKEN                  (SecretStr - the long-lived token)
INSTAGRAM_BUSINESS_ACCOUNT_ID           (the numeric ig-user-id)
INSTAGRAM_ACCESS_TOKEN_EXPIRES_AT       (plain timestamp, not a secret - lets /accounts surface expiry)
INSTAGRAM_PUBLICATION_ENABLED           (must stay "false" through this phase and the next, until a
                                          Founder-reviewed real canary explicitly turns it on)
INSTAGRAM_AUTONOMOUS_PUBLICATION_ENABLED (must stay "false" - separate, narrower control)
```

No app id, no app secret, no client secret is ever stored in this codebase (confirmed unchanged
this phase) - only the already-issued long-lived token + account id, matching the minimum-footprint
design the existing read-only integration already established.

## Media hosting requirement (new this phase, write-side only)

Confirmed via live search: `image_url`/`video_url` must be a **publicly, internet-accessible HTTPS
URL** that Meta's servers can `cURL` at request time - no localhost, no private/internal address,
no signed URL with a lifetime shorter than the container-processing window. Static images via
`image_url` must be **JPEG**. See the main report §D for what this phase built and what remains a
genuine infrastructure (not code) decision.

Sources: [Meta Developer Docs - Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/),
[Meta Developer Docs - Media reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/),
[Elfsight - Instagram Graph API 2026 guide](https://elfsight.com/blog/instagram-graph-api-complete-developer-guide-for-2026/).
