# Instagram Official Read API — reference for the NINJA PULSE adapter

DIRECTOR-CONTROL-PLANE-1C §2/§28. This is the API surface `services/instagram_account_reader.py`
targets. It is deliberately a small, versioned document — provider-specific field/scope/endpoint
names live here and in the adapter's own module docstring, never scattered through the Director
layer. Verified against Meta's current developer documentation and the 2026 API-change guidance
(Instagram Basic Display API was shut down December 2024; personal accounts can no longer be read
by any official API).

## OFFICIAL_API_FAMILY

**Instagram API with Instagram Login** (a.k.a. **"Business Login for Instagram"**). This is the
direct-Instagram OAuth path that replaced the deprecated Instagram Basic Display API. It works for
Instagram **professional** accounts (Business or Creator); a Creator account does **not** need a
linked Facebook Page.

We are **not** using "Facebook Login for Business" (the Facebook-Page-linked route) — the NINJA
PULSE account is a single professional account and the direct route is the smallest-permission fit
(§2's "choose the smallest-permission route").

## AUTH_MODEL

OAuth 2.0 **directly with Instagram** — no Facebook account in the loop.

1. The operator completes the interactive **Business Login for Instagram** flow once
   (`https://www.instagram.com/oauth/authorize` → short-lived code → `POST
   https://api.instagram.com/oauth/access_token` → short-lived token).
2. Exchange for a **long-lived Instagram User access token**:
   `GET https://graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=…&access_token=…`
   → a token valid **60 days**.
3. Refresh (any time after the token is ≥ 24 h old, before it expires):
   `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=…`
   → a new 60-day token.

**This phase does NOT automate steps 1–3.** `services/instagram_account_reader.py` consumes an
already-issued long-lived token supplied via `settings.instagram_access_token` (SecretStr) plus the
account id via `settings.instagram_business_account_id`. Steps 1–3 are an operational runbook the
operator performs out-of-band; only the resulting long-lived token + id are configured. No
`client_secret` / app-id is stored in this codebase (§7: "do not invent redundant credentials").
When the token nears expiry, `settings.instagram_access_token_expires_at` (a plain timestamp, not
the token) lets `/accounts` surface `TOKEN_STATUS` / `TOKEN_EXPIRY_AT`; the operator runs the
refresh call and updates the two config values.

The token is sent to the provider **only** as an `Authorization: Bearer <token>` header — never in
the query string — so it can never leak through httpx's own request logging or any URL that
reaches a log line (§7/§24).

## API_COMPATIBILITY

- **HOST**: `https://graph.instagram.com` — `settings.instagram_graph_base_url`.
- **VERSION**: pinned in `settings.instagram_api_version` (default **`v23.0`**). A version bump is a
  one-line config change; there is no inline version literal in the adapter (§28: "do not freeze
  obsolete assumptions in code").
- All requests: `GET {host}/{version}{path}` with `Authorization: Bearer`.

## REQUIRED_SCOPES

| Scope | Grants | Adapter behavior |
|---|---|---|
| `instagram_business_basic` | profile fields + owned media list | **always required.** Without it the connection check reports ERROR. |
| `instagram_business_manage_insights` | media insights + account insights | **optional.** Capability is **detected** from a real probe (`GET /{ig-user-id}/insights`) at connection-check time — never assumed. A permission error → `read_insights = UNAVAILABLE`; the account is still `CONNECTED` for profile + media. |

**No write scopes** are requested or used: `instagram_business_content_publish`,
`instagram_business_manage_comments`, `instagram_business_manage_messages` are never in the adapter.
There is no publish / edit / delete / comment / DM code path anywhere (§4).

## READABLE_FIELDS

### Profile — `GET /{ig-user-id}?fields=…`
`id`, `user_id`, `username`, `name`, `account_type` (`BUSINESS` / `MEDIA_CREATOR` / …),
`profile_picture_url`, `followers_count`, `follows_count`, `media_count`, `biography`.

### Media — `GET /{ig-user-id}/media?fields=…&limit=…`
`id`, `caption`, `media_type` (`IMAGE` / `VIDEO` / `CAROUSEL_ALBUM`), `media_product_type`
(`FEED` / `REELS` / `STORY`), `media_url`, `permalink`, `thumbnail_url`, `timestamp`, `like_count`,
`comments_count`. Bounded to the latest **≤ 30** objects, at most **2** pages via
`paging.cursors.after` — no full-history sync (§6).

### Media insights — `GET /{media-id}/insights?metric=…`
Candidate set requested: `reach`, `likes`, `comments`, `saved`, `shares`, `total_interactions`,
`views` (+ for Reels: `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time`). Any metric the
API rejects for a given media type / permission is **omitted from the result** — never returned as
`0` / estimated / inferred (§3). Status is `available` (all requested returned), `partial` (some),
or `unavailable`.

### Account insights — `GET /{ig-user-id}/insights?metric=reach,profile_views&period=day&metric_type=total`
Same "omit, never fabricate" rule. Used at connection-check time as the capability probe for
`read_insights`.

## INSIGHTS_SUPPORTED

Detected at runtime, per account/token, and cached in `instagram_accounts.capabilities`
(`{"read_profile": "AVAILABLE", "read_media": "AVAILABLE", "read_insights": "AVAILABLE" | "UNAVAILABLE"}`).
`/accounts` renders exactly this map. Nothing claims an insight metric exists until the provider
has actually returned it.

## Rate limits (§17)

Instagram enforces ~**200 calls / hour / user**. The adapter's bounded operations:

| Operation | Official calls |
|---|---|
| `run_instagram_connection_check()` | **2** (profile + insights probe) |
| `sync_instagram_feed_context()` | **≤ 2** (profile + media list, ≤ 2 pages counts as 1–2) — `INSTAGRAM_API_CALLS_PER_SYNC ≈ 2–3` |
| `fetch_media_insights(window)` | 1 per media, capped at the 30-item window (only called by a future performance collector, not by Director refresh) |

There is **no** background poller in this phase (§18). `run_instagram_connection_check()` and
`sync_instagram_feed_context()` are the two explicit, on-demand, bounded read paths.
