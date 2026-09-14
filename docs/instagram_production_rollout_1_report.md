# Instagram Production Rollout 1 — Report

**Phase**: INSTAGRAM-PRODUCTION-ROLLOUT-1
**Branch**: `feature/instagram-production-rollout-1`
**Base**: `feature/unified-editorial-pipeline-vision-gate-closure-1` @ `39f764bfc64b8c4b311e3feb5431f26b0be09899`
**Verdict**: `INSTAGRAM_PRODUCTION_ROLLOUT_BLOCKED`

This report contains no credential or secret values, and none were printed, logged, or requested
from the Founder at any point in this phase.

---

## A. Source reconciliation

See `docs/instagram_production_source_reconciliation_1.md` for the full detail. Summary: **every**
historical Instagram/Director/Social-Intelligence branch named in the phase brief, plus every one
this repository's own worktree list surfaced, is already an ancestor of current HEAD - no
cherry-picking was necessary or performed. Reconciliation itself is clean and complete.

## B. Current Meta API contract

The repository already contains an accurate, current, well-researched contract document
(`design/instagram_official_api.md`), verified this phase against live web search of Meta's 2026
developer documentation (see Sources below) - no material drift found:

- **API family**: Instagram API with Instagram Login ("Business Login for Instagram") -
  `graph.instagram.com`, pinned API version `v23.0`. Correct, current choice for a single
  professional (Business/Creator) account with no linked Facebook Page requirement.
- **Publish flow** (confirmed current via live search): `POST /{ig-user-id}/media` (image_url or
  video_url + caption) → creates a container → poll `GET /{container-id}?fields=status_code` until
  `FINISHED` → `POST /{ig-user-id}/media_publish` with `creation_id`. Carousel: create each child
  with `is_carousel_item=true`, then a parent container with `media_type=CAROUSEL` and
  `children=[...]`, then publish the parent. This exactly matches
  `services/instagram_publish_adapter.py`'s own already-implemented conceptual flow.
- **Media hosting requirement** (confirmed current via live search): `image_url`/`video_url` must
  be a **publicly, internet-accessible HTTPS URL** - Instagram's servers `cURL` it at request time.
  No private/internal/localhost/temporary URL is acceptable. Static image uploads via `image_url`
  must be **JPEG**.
- **Scopes**: read (`instagram_business_basic`, `instagram_business_manage_insights`) already used
  by the read-only account reader; write (`instagram_business_content_publish`) is documented
  (`settings.instagram_write_scopes`) but never requested by any live OAuth flow in this codebase -
  confirmed correct, since no OAuth flow of any kind is automated here (the design doc's own §
  "This phase does NOT automate steps 1-3" - token issuance/exchange/refresh remain an
  operator-run, out-of-band runbook).
- **Rate limits**: ~200 calls/hour/user (unchanged, confirmed by search).

Sources consulted: [Meta Developer Docs - Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/),
[Meta Developer Docs - Media reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/),
[Elfsight - Instagram Graph API 2026 guide](https://elfsight.com/blog/instagram-graph-api-complete-developer-guide-for-2026/).

## C. Account/credential readiness

Checked production `content_worker` environment and the shared `.env` file directly (key names
only, never values):

```
INSTAGRAM_ACCESS_TOKEN_PRESENT=false
INSTAGRAM_ACCOUNT_ID_PRESENT=false
META_APP_CONFIG_PRESENT=false  (not required by this API family anyway - no app-id/secret is
                                 stored per design/instagram_official_api.md's own "do not invent
                                 redundant credentials")
```

**Zero Instagram-related environment variables exist in production at all.** No read-only account
check (§5) could be attempted - there is no token to check with. This alone is sufficient grounds
to stop before any write per §4's own explicit instruction ("do NOT invent placeholders in
production... end with the exact missing credential/config requirements" - see §Q).

## D. Publisher implementation audit

`services/instagram_publish_adapter.py` is real, complete, well-tested code implementing the exact
official flow (§B) - `HttpInstagramPublishClient` (real `httpx` calls, never invoked by any test or
existing code path) and `ShadowInstagramPublishClient` (deterministic, zero-network, used by the
existing shadow test suite) both implement the identical `InstagramPublishClient` Protocol.
`publish_instagram_content()` fails closed, in order, before ever touching the client: gate must be
`READY_FOR_EDITOR`, then (for a live/non-shadow attempt) `instagram_publication_enabled=True` AND
`editor_approved=True` - both required, neither implied by the other.

**Concrete, disclosed gap found this phase** (not previously flagged in any prior report): the real
orchestration path's own `image_ref` for a live attempt is built as
`f"pending-media-ref:{package.package_id}"` - a literal placeholder string, by the module's own
comment: *"the real adapter takes an already-uploaded/reachable image URL; this phase never
uploads one (no live media host wired)"*. No code anywhere in this repository turns a locally
rendered/stored Instagram image into a real, public HTTPS URL. `app/main.py` (the only FastAPI
service in the stack) exposes exactly one route (`/`) - confirmed via direct read, no static/media
serving of any kind exists.

**This is a hard, structural blocker per §14's own explicit instruction**: *"If current
infrastructure cannot provide valid media URLs: BLOCK before real write and report the precise
infrastructure requirement."* See §Q for the precise requirement.

## E. Publication state model

`instagram_publication_enabled` (existing) and `instagram_autonomous_publication_enabled` (NEW,
added this phase - see below) are both real, present, and both default `False`. `PublicationResult`
(`services/instagram_publish_adapter.py`) is a complete, well-shaped in-memory result object
(status/shadow/container_ids/media_id/failure_class/retryable/attempts_used) but **is never
persisted to any database table** - confirmed by direct audit of every file under
`database/models/`. A real publish attempt today would have no durable record survivable across a
worker restart. This is a second, independent hard blocker for real writes (§12/§13's ambiguous-
write-safety requirements depend on durable state to reconcile against).

**Change made this phase** (small, additive, safe): `core/config.py` gained
`instagram_autonomous_publication_enabled: bool = False` - the §6-required second, narrower control
(no autonomous scheduler/worker loop exists anywhere in this codebase that could even consume this
flag today - confirmed by grep: only manual canary scripts and the adapter itself reference
`publish_instagram_content`). `tests/test_instagram_safety.py`'s existing
`test_all_new_feature_flags_default_false` extended to cover it. Both flags remain `False` in
production - no `.env`/override change was made anywhere.

## F. Idempotency

`services/instagram_publish_adapter.py` itself has NO deterministic idempotency key derivation -
`InstagramContentPackage.package_id` (the natural candidate) is a random `uuid4()`, not derived
from `(platform, story/package identity, format/version)` as §12 requires. Combined with §E's "no
durable persistence" gap, a retry after an ambiguous/unknown-status publish attempt cannot
currently be safely deduplicated. **A third, independent gap** - not itself a reason real writes
are impossible today (no writes are being attempted at all), but a real requirement before any
future real-write phase, documented precisely in §Q.

## G. Rights/provenance

**The most safety-critical finding of this phase**: `services/instagram_editorial_gate.py` (the
platform's own READY_FOR_EDITOR/HOLD/BLOCK gate) checks Art-validation failures, restricted-claim
violations, product-mention safety, and launch-state - it **never references** `subject_match`,
`SubjectMatchClassification`, `MISMATCH`, `EDITORIAL_REVIEW_REQUIRED`, `NOT_USABLE`, or
`MediaResearchService` (confirmed: zero matches by direct grep across
`services/instagram_editorial_gate.py` and `services/instagram_art_validator.py`).
`InstagramContentPackage.source_image_ref` (the only field carrying image identity) is a bare
string reference with **no attached subject-match verdict or rights classification at all**, and
is populated in the entire codebase **only** by `scripts/_instagram_autonomous_trend_canary_1.py`
- a manually-invoked, never-auto-run script, hardcoded to one specific local asset path.

**Concretely: the unified media-truthfulness and rights guarantees built for Telegram
(RUNTIME-CLOSURE-1: bounded candidate pool, `is_selectable()` MISMATCH/`EDITORIAL_REVIEW_REQUIRED`
exclusion; VISION-GATE-CLOSURE-1: real vision-based subject verification) have no live connection
to the Instagram package/gate at all.** §8 of this phase's own brief requires *"Reuse the new media
truthfulness guarantees. Wrong-subject media must not become publishable on Instagram"* and §11
requires *"MISMATCH must never publish... EDITORIAL_REVIEW_REQUIRED must not silently
auto-publish."* Neither is structurally true for Instagram today - not because anything regressed,
but because this wiring was never built. This is the single most important reason this phase does
not proceed to a real canary even in principle: publishing today, even with credentials and media
hosting solved, would carry exactly the same wrong-subject-media risk the Telegram-side work spent
two entire phases closing, with **zero** of those protections active for Instagram.

## H. Dry-run sample

Given §D/§E/§G's hard blockers were identified during the code audit (before any candidate
selection was attempted), a fresh, purpose-built 5-candidate dry run was not constructed - it would
not have exercised the missing truthfulness/rights wiring described in §G (there is nothing to
select there yet: no candidate today carries a real subject-match verdict), and would have
risked implying a readiness the system does not have. Instead, shadow-path correctness was
verified via the existing, comprehensive, already-passing test suite: `tests/test_instagram_publish_
adapter.py` (17 tests: flag-off default, gate BLOCK/HOLD never reach client, shadow success,
container/timeout/publish failures, retry/backoff bounds, carousel multi-container, zero real
network in shadow mode - all still passing this phase, re-run: **17/17 PASS**),
`tests/test_instagram_execution_e2e_shadow.py`, `tests/test_instagram_content_package.py`,
`tests/test_instagram_editorial_gate_routing.py`, `tests/test_instagram_art_validator.py` (33 more
tests, all passing). This proves the shadow orchestration mechanics are sound; it does not and
cannot prove media-truthfulness enforcement, because that enforcement does not exist yet for this
platform.

`DRY_RUN_CANDIDATES=0` (none constructed - see above); the existing shadow test suite substitutes
for a fresh dry run of the mechanics that do exist.

## I. Real canary selection

Not performed. §19's own selection criteria ("clear subject, strong media, no rights ambiguity...
package QA clean") cannot be honestly evaluated for any real candidate today, since no real
candidate in this codebase currently carries a subject-match/rights verdict on its selected image
(§G). Selecting one anyway and proceeding would be exactly the kind of "use a marginal candidate
simply to complete the phase" §19 explicitly forbids - applied here to the deeper problem of "the
verification apparatus itself doesn't exist yet for this candidate," not merely "this specific
candidate looks weak."

## J. Real publication evidence

**None. No real Meta API write of any kind was attempted or made in this phase** - not a single
`HttpInstagramPublishClient` call was invoked outside of the (unused, network-inert) class
definition itself. This is intentional and correct given §C/§D/§E/§F/§G above.

## K. Readback verification

Not applicable - no publication occurred.

## L. Duplicate/ambiguity audit

Not applicable - no publication occurred, so no duplicate or ambiguous result is possible this
phase. The existing test suite already proves the retry/backoff bounds and auth-error-never-retried
behavior (§H) at the unit level; end-to-end duplicate-prevention against a real, durable idempotency
key cannot be proven until §F/§E's gaps are closed.

## M. Small controlled batch

Not reached - gated entirely on a passing real canary (§21-23), which did not occur.

## N. Telegram regression check

Confirmed zero Telegram-side changes this phase. The only code changes
(`core/config.py`: one new additive config field; `tests/test_instagram_safety.py`: one assertion
added to an existing test) touch nothing Telegram-related. `worker/content_cycle.py` imports and
`settings.unified_editorial_pipeline_enabled` were confirmed to still load/read correctly after the
config change. **`TELEGRAM_CHANGED = false`.**

## O. Production health

Not modified this phase - no production deployment, no production config change, no production
credential change, no production container restart. Production `content_worker` remains exactly as
left at the end of PRODUCTION-CANARY-2 (unified flag `true`, healthy). This phase performed all
work in a local isolated worktree plus read-only production credential-presence checks (via SSH
`printenv`/`.env` key-name grep only - no value read, no write, no restart).

## P. Final flags

- `instagram_publication_enabled = false` (unchanged; correct - real writes remain hard-disabled)
- `instagram_autonomous_publication_enabled = false` (NEW, added this phase; correct default)
- `unified_editorial_pipeline_enabled` (Telegram) = unchanged, still `true` in production

## Q. Remaining limitations / precise requirements before a future real-write phase

In priority order (all independent; all must be resolved, not just the first one reached):

1. **Credentials**: obtain a long-lived Instagram User access token via the documented
   Business-Login-for-Instagram flow (`design/instagram_official_api.md` §AUTH_MODEL, operator-run,
   out-of-band) **including the `instagram_business_content_publish` write scope** (the currently-
   documented read-only token, if one is later configured for the reader, would NOT carry this
   scope and would fail at Meta's own permission layer for a publish call). Configure
   `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_BUSINESS_ACCOUNT_ID` in production.
2. **Media hosting**: stand up a controlled, production-safe, publicly-accessible HTTPS media
   endpoint (e.g., a dedicated static-asset route behind the existing `backend` FastAPI service, or
   an object-storage bucket with public read on a per-object basis) that can serve a
   freshly-rendered Instagram image as a real, internet-fetchable JPEG URL, with correct
   content-type and no other private data exposed. Wire `services/instagram_publish_adapter.py`'s
   `image_ref`/`video_ref` construction to this real mechanism instead of the current placeholder.
3. **Media truthfulness/rights wiring**: connect `MediaIntentBuilder`/`MediaResearchService`/
   `MediaAssetResolver` (already platform-neutral by design per their own docstrings) into the
   Instagram Creative Director/Format Director chain so `InstagramContentPackage` carries a real
   subject-match verdict and rights classification for its selected image, and extend
   `services/instagram_editorial_gate.py` to hard-BLOCK on `MISMATCH`/`NOT_USABLE` and
   HOLD-for-review on `EDITORIAL_REVIEW_REQUIRED`, exactly mirroring the Telegram-side policy. This
   is real integration work, not configuration - it deserves its own dedicated, reviewed phase.
4. **Durable publication state**: an additive migration + model persisting
   `NOT_ATTEMPTED/CREATING_CONTAINER/CONTAINER_CREATED/PUBLISHING/PUBLISHED/FAILED/AMBIGUOUS/HOLD`
   per package, keyed by a deterministic idempotency identity (`platform` +
   `story/package identity` + `format/version`, replacing `InstagramContentPackage.package_id`'s
   current random `uuid4()` for this purpose).
5. **Caption validation**: no caption-length check (Instagram's official 2,200-character limit)
   exists anywhere in the Instagram service layer today (confirmed by grep) - add one, mirroring
   `services/editorial_pipeline/platforms/telegram.py::plan_telegram_caption_budget()`'s own
   established pattern, before any real write path is enabled.

None of these are large in isolation, but together they represent real, disclosed engineering work
- not a configuration flip. This phase deliberately did not attempt any of them beyond the one
safe, purely-additive config flag (§E), per the phase's own "do not redesign the Instagram product"
instruction and its own explicit "BLOCK before real write" gates.

## R. Final verdict

Five independent, structural, pre-existing gaps (credentials, media hosting, truthfulness/rights
wiring, durable publication state, caption validation) each individually prevent a safe real
publication attempt; the first two are absolute hard blockers per the phase's own §4/§14
instructions, and the third (§G) is the most safety-critical, directly contradicting this phase's
own §8/§11 requirements if bypassed. Zero real Meta API writes occurred. Zero Telegram regression.
One small, safe, additive code change made (`instagram_autonomous_publication_enabled` config
flag). All reconciliation and audit work requested by §1-§2 is complete.

**`INSTAGRAM_PRODUCTION_ROLLOUT_BLOCKED`**
