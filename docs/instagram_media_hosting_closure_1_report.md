# INSTAGRAM-MEDIA-HOSTING-CLOSURE-1 — Report

Base: `99014ac` (feature/instagram-production-readiness-closure-1). Branch:
`feature/instagram-media-hosting-closure-1`. No Instagram publication attempted. Both publication
flags remain `false` throughout.

## A. Production infrastructure audit

Re-audited the live production host (`31.77.219.165`) directly, read-only:

- `docker ps` — only `backend` publishes a port to the host (`0.0.0.0:8000->8000/tcp`, plain HTTP).
  `content_worker`, `automation_worker`, `news_analysis_worker`, `telegram_bot` each expose
  `8000/tcp` internally to the Docker network only — none are reachable from outside the host at
  all today.
- `ss -tlnp` on the host — nothing listens on 80 or 443. `docker ps -a` — no nginx/Caddy/Traefik/
  proxy container exists, now or ever created on this host.
- No `certbot`, no `acme.sh`, no `~/.acme.sh`, no `/etc/letsencrypt`, no `cloudflared` binary, and no
  systemd unit for any of nginx/Caddy/Traefik/Cloudflare Tunnel.
- `ufw status` — inactive (no firewall blocking 80/443 if something were to listen — the blocker is
  the total absence of any TLS-terminating process, not a firewall rule).
- Reverse DNS for `31.77.219.165` resolves only to a generic hosting-provider PTR record
  (`vm178145.hosted-by.qwins.co`) — there is no application domain (e.g. a `ninjapulse.*` name)
  pointed at this host anywhere.

## B. Existing HTTPS ingress

**None.** `backend` is plain HTTP on port 8000. No certificate, no domain, no reverse proxy. Since
Let's Encrypt (and every standard public CA) requires a real domain name for issuance — it cannot
issue a certificate for a bare IP address — a valid, Meta-trusted TLS certificate is not achievable
on this host today regardless of what reverse-proxy software might be installed, until a domain is
pointed here.

## C. Existing storage/media facilities

Confirmed (again) that no object-storage SDK or credential exists anywhere in this codebase or in
production's `.env`: no `boto3`, no `google.cloud.storage`, no S3/R2/GCS/Cloudflare-prefixed
environment keys of any kind. `core/config.py`'s `image_storage_root` confirms storage is local
filesystem only. Option B (existing object storage) is not available.

## D. Chosen architecture

**No new architecture was deployed this phase** — Option A (existing public HTTPS domain/reverse
proxy) and Option B (existing object storage) are both genuinely unavailable per A/B/C above. Per
§4's own instruction, this stops before any external provisioning.

What *was* done: the already-built local half of Option A
(`services/instagram_media_hosting.py` + `app/routes/instagram_media.py`, from
INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1) was re-audited, a real bug found in it was fixed, its
test coverage was hardened against the exact test matrix this phase specifies, and it was wired
into the publish adapter's fail-closed path — so that whichever ingress Founder eventually chooses
(reverse proxy + domain, or a managed storage service), the local registration/serving/identity/
retention mechanism underneath it needs no further code work.

## E. Why alternatives were rejected

- **Self-signed certificate over the existing bare IP**: rejected — Meta's fetcher requires a
  CA-trusted certificate; a self-signed one would be silently rejected at fetch time, and this
  would still not satisfy "PUBLIC_HTTPS_URL_AVAILABLE" in any way Meta accepts.
- **Serving over the existing plain-HTTP `backend:8000`**: rejected — explicitly forbidden by prior
  phase's own disclosed decision and this phase's §3 requirement ("public HTTPS", "valid TLS
  certificate"); doing so anyway is exactly the "workaround" this phase's brief prohibits.
- **Provisioning a new external object-storage account/bucket** (e.g. Cloudflare R2, S3): would
  satisfy Meta's requirements without needing a domain (R2 offers a public `*.r2.dev`-style URL by
  default) but requires a **new external account/service** Founder has not authorized — falls
  squarely under Option C per §4, and under §12's explicit "new... S3/R2 account/bucket... STOP
  BEFORE DEPLOYMENT."

## F. Security model (of the existing, re-audited local mechanism)

Unchanged design, re-confirmed by the hardened test suite:
- Dedicated allowlisted directory (`instagram_media_storage_root`) only — no other path is ever
  read or written.
- Asset ids are exact 32-hex-character sha256 prefixes; `get_publication_asset()` rejects any
  non-conforming id (traversal characters included) **before** touching the filesystem at all — a
  crafted traversal-style id both at the function level and through the actual HTTP route (percent-
  encoded `../` segments) now has an explicit regression test (new).
  - Content-Type allowlist: exactly `image/jpeg` (Meta's `image_url` requirement).
  - Bounded size: 8MB cap, enforced before any bytes are written.
  - Bounded retention: 1-hour TTL, tracked via file mtime (fixed this phase - see G below).
  - No directory listing, no arbitrary file read: the route only ever resolves
    `{asset_id}.jpg` inside the storage root via `get_publication_asset()`, never a caller-supplied
    path.
  - No credential-bearing query parameters anywhere in the URL scheme.
  - GET and HEAD only (HEAD added this phase - see I below); no other method is registered on the
    route.
  - Fails closed for missing/expired/malformed ids: 404, indistinguishable from "never existed."

## G. Asset identity model

`asset_id = sha256(bytes)[:32]` - unchanged. New explicit test
(`test_hosted_digest_matches_rendered_digest`) proves `HOSTED_ASSET_EQUALS_RENDERED_ASSET` directly:
the served bytes' own sha256 digest equals the digest of the exact bytes that were registered, and
the asset id is literally a prefix of that digest — the hosting layer has no path by which it could
substitute different bytes for the same id.

## H. Retention/cleanup — bug found and fixed

**Real bug found this phase**: `register_publication_asset()` skipped writing when a dedup hit
occurred (identical bytes already staged from an earlier registration), but never refreshed that
file's mtime. Since `get_publication_asset()` derives an asset's expiry purely from the file's own
mtime + the fixed 1-hour TTL, a legitimate **re-registration** of previously-seen content (e.g. the
same rendered image reused for a retried package build, more than an hour after it was first
staged) would be reported as **already expired the instant it was "registered" again** — a false
HOLD/BLOCK for content that was never actually stale from the caller's point of view.

**Fix**: `register_publication_asset()` now calls `os.utime()` to bump the file's mtime to "now" on
every call, including a dedup hit — mtime is the single source of truth for "last registered at,"
never "first ever written at." Two new tests
(`test_expired_asset_is_unservable_even_though_bytes_remain_on_disk`,
`test_reregistering_identical_bytes_after_expiry_refreshes_the_window`) cover both the correct
expiry behavior and the fix directly, including a real repro of the bug (confirmed failing before
the fix, passing after).

TTL is 1 hour (`DEFAULT_TTL_SECONDS = 3600`, unchanged) — chosen originally (prior phase) to safely
exceed Meta's own typical container-processing window (seconds) while bounding public exposure;
this phase found no reason to change it. Cleanup remains lazy (expired files are left on disk,
never served) rather than actively swept — acceptable for the bounded local directory this
represents; an active sweep can be added trivially later without any interface change if retention
volume ever becomes a concern.

## I. Implementation diff (this phase, on top of `99014ac`)

- `services/instagram_media_hosting.py` — the mtime-refresh-on-dedup-hit fix (§H).
- `app/routes/instagram_media.py` — added explicit `HEAD` support (`@router.api_route(...,
  methods=["GET", "HEAD"])`), returning the same headers (including a now-explicit
  `Content-Length`) with an empty body for HEAD. Previously a HEAD request 405'd — a real risk had
  Meta's own fetcher (or any HTTPS-reachability smoke test) probed with HEAD before GET.
- `services/instagram_publish_adapter.py` — new `InstagramPublishErrorCode.MEDIA_HOSTING_NOT_READY`
  and a new fail-closed check in `publish_instagram_content()`: a real (`shadow=False`)
  single/carousel publish attempt now checks `media_hosting_readiness()` and returns `BLOCKED`
  **before** ever constructing the old placeholder `"pending-media-ref:..."` string, let alone
  calling the client. Gated identically to the existing flag/approval checks (`if not shadow`) -
  zero effect on shadow publishes, zero effect in production today (the pre-existing
  `PUBLICATION_DISABLED` check already fires first, since `instagram_publication_enabled=False`).
  REEL is unaffected — its own separate `external_video_asset_ref` presence check is untouched;
  video hosting stays out of this phase's scope.
- No renderer, visual layout, or creative-generation file was touched. No database migration.

## J. Tests

New/updated this phase, mapped to the required matrix:

| Item | Test |
|---|---|
| A. valid JPG staged/served | `test_route_serves_a_registered_asset_and_404s_for_unknown_ids` (pre-existing) |
| B. PNG rejected (only JPEG accepted) | `test_png_rejected_only_jpeg_accepted_for_instagram` (pre-existing) |
| C. video/Reel asset | N/A — current implementation has no video media-hosting path (REEL uses a separate, pre-existing `external_video_asset_ref` field, unaffected); disclosed, not fabricated |
| D. correct Content-Type | `test_route_serves_a_registered_asset_and_404s_for_unknown_ids` (pre-existing) |
| E. HEAD/GET behavior | `test_route_supports_head_without_body` (**new**, found the missing-HEAD gap) |
| F. unknown ID → 404 | `test_lookup_of_never_registered_id_is_none`, route test (pre-existing) |
| G. expired ID → 404 | `test_expired_asset_is_unservable_even_though_bytes_remain_on_disk` (**new**) |
| H. path traversal rejected | `test_lookup_rejects_malformed_id_never_touches_filesystem` (pre-existing) + `test_route_rejects_a_path_traversal_style_id` (**new**, route-level) |
| I. arbitrary filesystem path unservable | same as H, both function- and route-level |
| J. disallowed extension/type rejected | `test_non_image_bytes_rejected`, `test_png_rejected_only_jpeg_accepted_for_instagram` (pre-existing) |
| K. oversized asset rejected | `test_oversized_asset_rejected` (pre-existing) |
| L. hosted digest == rendered digest | `test_hosted_digest_matches_rendered_digest` (**new**) |
| M. public URL construction correct | `test_build_public_media_url_succeeds_for_a_real_safe_configured_base_url` (pre-existing) |
| N. missing base URL → not ready | `test_media_hosting_readiness_is_false_by_default_in_this_environment`, `test_build_public_media_url_returns_none_when_base_url_unconfigured` (pre-existing) |
| O. hosting failure → HOLD/BLOCK before write | `test_live_publish_fails_closed_when_media_hosting_not_ready` + `test_live_publish_proceeds_past_the_media_hosting_gate_once_ready` (**new**) |
| P. Telegram regression = zero | full freeze suite re-run, 40/40 pass (unchanged) |
| Q. Instagram visuals byte-identical | renderer test suite re-run untouched, all pass; no renderer file modified |

Plus a new autouse fixture (`_isolated_storage_root`) that gives every test in
`test_instagram_media_hosting.py` its own empty `tmp_path`-backed storage directory - the real,
pre-existing test-isolation gap that made the mtime bug (§H) directly reproducible against real
elapsed wall-clock time during this audit.

**Results**: `tests/test_instagram_media_hosting.py` 32/32 pass (was 27; 2 genuinely regressed
under the old code once isolated from stale host state, both now fixed and covered).
`tests/test_instagram_publish_adapter.py` 19/19 pass (17 pre-existing + 2 new). Combined Instagram
suite (14 files) 139/139 pass. Telegram/unified-pipeline freeze suite 40/40 pass. `ruff check` clean
on every changed file.

## K. External HTTPS fetch verification

**Not performed** — there is no public HTTPS endpoint to fetch in this environment (§A/§B). No test
artifact was staged externally, and none was deleted, since none was created.

## L. Production deployment

**Not performed.** Even though this phase's code changes are narrow, additive, and fully reversible
(a real bug fix, one new fail-closed gate, one new HTTP method on an existing route), deploying
them would require rebuilding and restarting `backend` (which owns the media route) and
`content_worker`/wherever `publish_instagram_content` runs - real production risk - for **zero
readiness gain**, since `MEDIA_HOSTING_READY` cannot become `true` regardless of this deploy while
the external HTTPS blocker (§A/§B) remains unresolved. Deploying now would be disruption without
benefit. This branch is ready to build and deploy together with whichever ingress solution Founder
authorizes.

## M. Rollback

N/A — nothing was deployed. The branch itself is fully reversible (no migration, no production
state change); deleting it or leaving it un-merged has zero production effect.

## N. Telegram / non-regression

`TELEGRAM_CHANGED=false`, `STORY_MEMORY_CHANGED=false`, `ARXIV_CHANGED=false`,
`UNIFIED_PIPELINE_CHANGED=false`, `INSTAGRAM_VISUALS_CHANGED=false`. No file under any of those
areas was touched. Freeze suite re-run confirms zero regression (§J).

## O. Instagram publication status

`INSTAGRAM_PUBLICATION_PERFORMED=false`. Both `instagram_publication_enabled` and
`instagram_autonomous_publication_enabled` remain `false`, confirmed via direct settings import
after all changes.

## P. Final readiness matrix

```
MEDIA_HOSTING_ARCHITECTURE=NONE_AVAILABLE_LOCAL_MECHANISM_READY
EXISTING_PUBLIC_HTTPS_INFRA_AVAILABLE=false
NEW_EXTERNAL_PROVIDER_REQUIRED=true

PUBLIC_HTTPS_URL_AVAILABLE=false
TLS_VALID=false
UNAUTHENTICATED_FETCH_READY=false
CONTENT_TYPE_CORRECT=true

HOSTED_ASSET_EQUALS_RENDERED_ASSET=true
PATH_TRAVERSAL_POSSIBLE=false
ARBITRARY_FILE_READ_POSSIBLE=false

RETENTION_POLICY_READY=true
CLEANUP_READY=true
FAIL_CLOSED_READY=true

INSTAGRAM_ACCOUNT_READY=true
INSTAGRAM_CREDENTIALS_READY=true
INSTAGRAM_WRITE_PERMISSION_READY=UNVERIFIED
MEDIA_HOSTING_READY=false
```

## Exact minimal Founder setup required (Option C)

Either of the following closes `MEDIA_HOSTING_READY` (pick one — the code already supports the
first without further changes; the second needs one small, disclosed wiring change to upload
instead of serving locally):

1. **Domain + reverse proxy** (reuses the code built this phase and in the prior closure phase
   as-is): register or point an existing domain's DNS A/AAAA record at `31.77.219.165`, then
   install a reverse proxy (nginx or Caddy) on that host with a Let's Encrypt certificate for that
   domain, forwarding `/media/instagram/*` to `backend:8000`. Set
   `INSTAGRAM_MEDIA_PUBLIC_BASE_URL=https://<that-domain>` in production `.env`.
2. **Managed object storage with public HTTPS by default** (e.g. Cloudflare R2, S3 + CloudFront):
   provision the bucket/account (a new external, possibly-paid service - Founder decision), then a
   small follow-up phase swaps the local-filesystem write in `register_publication_asset()` for an
   upload call to that service and uses its returned public URL directly.

No DNS, certificate, or account was created or modified this phase.

## Verdict

`INSTAGRAM_MEDIA_HOSTING_BLOCKED_EXTERNAL_SETUP_REQUIRED`
