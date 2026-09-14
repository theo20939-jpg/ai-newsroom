# INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 — Final Report

Base: `b9c5c0e7444cb6c132665d0d79e7f11ebe0ee641`. Branch:
`feature/instagram-production-readiness-closure-1`. No real Instagram write attempted anywhere in
this phase. Both publication flags (`instagram_publication_enabled`,
`instagram_autonomous_publication_enabled`) remain `False` throughout.

---

## A. Gap matrix

See `docs/instagram_production_readiness_gap_matrix_1.md` for the full table. Summary of the 7
gaps identified from the prior INSTAGRAM-PRODUCTION-ROLLOUT-1 report plus one incidental finding:

| # | Gap | Status after this phase |
|---|---|---|
| 1 | Credentials (no write-scope token) | Founder-side — checklist issued, not code-closable |
| 2 | Media hosting (no public HTTPS) | Code path fully built+tested; public reachability Founder-side |
| 3 | Unified safety gate not wired into Instagram package creation | **CLOSED** |
| 4 | No durable/idempotent publication state | **CLOSED** |
| 5 | No ambiguous-write reconciliation | **CLOSED** |
| 6 | No live dry-run runtime evidence | **CLOSED** (8 real candidates) |
| 7 | (rollout report's own residual item — caption/format validation) | confirmed already covered by existing `FORMAT_REQUIREMENTS`/`PLATFORM_BUDGET` checks; no new gap found |
| incidental | Postgres `5432` bound to `0.0.0.0` | disclosed, out of scope, not fixed this phase |

---

## B. Meta API requirements

See `docs/instagram_meta_production_setup_1.md`. Verified this phase via live search: account
type (professional Business/Creator, no Facebook Page linkage required under Instagram API with
Instagram Login), API version `v23.0`, container-based publish flow, required write scope
`instagram_business_content_publish` (currently missing — only the two read scopes are in use
today), App Review requirement, and the exact non-secret env var names the code needs.

---

## C. Credential/account readiness

`INSTAGRAM_ACCOUNT_READY=false`, `INSTAGRAM_CREDENTIALS_READY=false`,
`INSTAGRAM_WRITE_PERMISSION_READY=false`. No credentials were invented, requested in chat, or
assumed. Per §17's explicit carve-out, this is classified as Founder manual setup, not a code
defect — see `docs/instagram_founder_manual_setup_checklist_1.md` Group A.
`InstagramAccountReader.check_connection()` (pre-existing) remains the correct, real verification
call once a token exists — no new competing verification path was built.

---

## D. Media hosting

`MEDIA_HOSTING_READY=false`, but the code-side mechanism is complete and tested:

- `services/instagram_media_hosting.py` — deterministic content-hash asset registration, exact-id
  lookup (no directory listing / no path traversal), MIME allowlist (`image/jpeg` only), size cap
  (8MB), TTL-bounded exposure (1 hour default), and `is_safe_public_base_url()` (HTTPS-only,
  rejects localhost/private/loopback/link-local IP literals and non-publicly-resolving hostnames).
- `app/routes/instagram_media.py` — `GET /media/instagram/{asset_id}.jpg`, serves exactly the
  registered asset or 404s, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`.
- `media_hosting_readiness()` is the single source of truth for the metric: `code_path_ready=true`
  always; `media_hosting_ready` is only `true` once a real safe public base URL is configured
  (confirmed `false` in every environment today — no TLS/domain/reverse-proxy exists in front of
  `backend:8000`, which is plain HTTP; no nginx/Caddy/Traefik container exists in the compose
  stack). This was deliberately NOT worked around by serving real images over unencrypted HTTP.
  27/27 tests pass (`tests/test_instagram_media_hosting.py`).

---

## E. Unified safety gate wiring

`INSTAGRAM_UNIFIED_SAFETY_GATE_WIRED=true`. `evaluate_instagram_package()`
(`services/editorial_pipeline/platforms/instagram.py`) now threads a real `media_selection` into
the shared `run_quality_gate()` instead of the previous hardcoded `None`, retroactively activating
the existing `VISUAL_TRUTHFULNESS`/`MEDIA_PROVENANCE` checks that already reject
MISMATCH/NOT_USABLE/EDITORIAL_REVIEW_REQUIRED for Telegram. `is_selectable()`
(`services/media_candidate_scoring.py`, fixed in a prior phase) already prevents those
classifications from ever becoming `.selected` in the first place — no new exclusion logic was
needed, only wiring. 9/9 new tests pass (`tests/test_instagram_unified_media_safety.py`), including
a defense-in-depth BLOCK test for a hand-constructed disallowed `selected` candidate.

---

## F. Same-asset identity (selected == packaged == QA == published)

Enforced via a new `QualityCheckName.SAME_ASSET_IDENTITY` check and
`_verify_same_asset_identity()` in `services/editorial_pipeline/platforms/instagram.py`: every
render whose `evidence.source_image_treatment` is not `"none"`/`"generated"` must carry an
`evidence.source_media_candidate_id` matching `InstagramContentPackage.media_candidate_id`.
Divergence BLOCKs the package alongside the other identity-critical checks. Trivially `True` when
no media was selected (text/generated-only packages), never fabricated as `True` otherwise.
Covered by `tests/test_instagram_unified_media_safety.py`.

---

## G. Publication state persistence

`PUBLICATION_STATE_PERSISTENCE_READY=true`. New `database/models/instagram_publication_job.py`
(`InstagramPublicationJob` ORM model, `InstagramPublicationState` enum:
NOT_ATTEMPTED/CREATING_CONTAINER/CONTAINER_CREATED/PUBLISHING/PUBLISHED/FAILED/AMBIGUOUS/HOLD) and
additive-only migration `d7e4a92f1b83_add_instagram_publication_jobs_table.py` (down_revision
`c48f6a1e9d02`). Applied only to the isolated local test DB
(`POSTGRES_DB=ai_newsroom_test python -m alembic upgrade head`) — **never applied to production**
this phase.

---

## H. Publication idempotency

`PUBLICATION_IDEMPOTENCY_READY=true`. `services/instagram_publication_state.py`:
`compute_idempotency_key(platform, package_identity, content_format, schema_version)` — a
deterministic sha256-based key derived from a stable content identity (never
`InstagramContentPackage.package_id`, which is a random `uuid4()` regenerated on every build,
closing the exact gap the prior rollout report disclosed). `InstagramPublicationStateService`
reuses the SAVEPOINT + `IntegrityError`-recovery concurrency pattern already established in
`services/editorial_pipeline/recovery_service.py::RecoveryService.create_or_retry()`, enforced by a
real partial-unique index on `(idempotency_key)` WHERE state is open. 5/5 tests pass including a
real concurrency race test (`tests/test_instagram_publication_state.py`).

---

## I. Ambiguous-write reconciliation

`AMBIGUOUS_WRITE_RECONCILIATION_READY=true`. `services/instagram_ambiguous_write_reconciliation.py`
implements readback-via-official-API-first reconciliation
(`reconcile_ambiguous_publish(reader, expected_caption_prefix, attempted_at, window_minutes)`),
matching on caption-prefix + time-window against real account media, returning
`confirmed_published`/`confirmed_absent`/`unknown` — never resolves to `confirmed_absent`
prematurely (before the window elapses), and never raises (a readback failure itself resolves to
`unknown`, so a network hiccup during reconciliation can never trigger a blind resend). 6/6 tests
pass.

---

## J. Dry-run runtime evidence

`DRY_RUN_RUNTIME_WIRED=true`, `DRY_RUN_CANDIDATES=8` (≥5 required),
`DRY_RUN_READY=6`, `DRY_RUN_HOLD=0`, `DRY_RUN_BLOCK=0` (the remaining 2 of the 8 had no resolvable
image candidate — `selected_candidate_id=null` — and correctly still reached a `READY` text-package
classification via the same honest no-fabrication path, never misreported as a false media match).

`services/instagram_dry_run.py` exercises the full real safety-critical chain (media discovery →
truthfulness/rights verification → package build → quality gate incl. `SAME_ASSET_IDENTITY` →
render → shadow publish via the pre-existing `ShadowInstagramPublishClient`, zero network writes)
against 8 real, recent (2026-09-14) production candidates pulled read-only via SSH+psql from
`content_drafts`/`news_events`/`image_candidates` — see
`artifacts/instagram_production_readiness_closure_1/dry_run_sample_1.json` for full per-candidate
detail (titles, subject-match classifications, QA check summaries, shadow-publish status). All 8
completed with `shadow_publish_status="shadow_success"` and zero fabricated readiness. 4/4 tests
pass including a hard proof that `HttpInstagramPublishClient` is never constructed during a dry run
(`tests/test_instagram_dry_run.py`).

---

## K. Real recent candidate sample

The 8 candidates span GADGETS/AI/STARTUPS/HARDWARE/TECH categories, real Russian- and
English-language titles, real image-candidate ids/dimensions — no synthetic titles or invented
facts. The only synthetic elements are structurally-honest placeholder
`ContentOpportunity`/`FormatDecision`/`ShadowPlanResult` objects needed to construct a package
outside the full autonomous Creative Director LLM chain, explicitly disclosed in
`services/instagram_dry_run.py`'s own docstring as scoped to the safety-critical chain, never
claimed to exercise the real LLM-based Creative Director.

---

## L. Telegram / Story Memory / arXiv / Telegram V8 freeze

`TELEGRAM_CHANGED=false`, `STORY_MEMORY_CHANGED=false`, `ARXIV_GUARD_CHANGED=false`,
`TELEGRAM_V8_CHANGED=false`. No file under Telegram/Story-Memory/arXiv-guard/Visual-V8 ownership
was modified this phase. Verified via a 40/40-passing freeze-verification run across
`tests/test_unified_pipeline_cutover_authority.py`,
`tests/test_unified_pipeline_same_asset_invariant.py`, `tests/test_unified_pipeline_vision_gate.py`,
`tests/test_editorial_pipeline_orchestrator.py`, `tests/test_editorial_pipeline_composition_quality.py`,
plus a clean `worker.content_cycle` import with `unified_editorial_pipeline_enabled=False`.

---

## M. Tests

- New/modified Instagram-readiness tests: 27 (`test_instagram_media_hosting.py`) + 9
  (`test_instagram_unified_media_safety.py`) + 5 (`test_instagram_publication_state.py`) + 6
  (`test_instagram_ambiguous_write_reconciliation.py`) + 4 (`test_instagram_dry_run.py`) = 51 new
  tests, all passing.
- Combined Instagram suite (new + all 7 pre-existing Instagram test files): **122 passed, 0
  failed**.
- Telegram/unified-pipeline freeze suite: **40 passed, 0 failed**.
- `NEW_FAILURES=0` across both runs.
- All Meta API interaction in tests is mocked (`ShadowInstagramPublishClient`, monkeypatched
  `HttpInstagramPublishClient.__init__` raising if ever constructed, monkeypatched
  `socket.getaddrinfo` for DNS-dependent hostname tests) — zero real network writes anywhere in
  pytest.
- `ruff check` clean on every new/modified file (one genuine unused-import fix applied; one
  pre-existing, unrelated F401 pattern in `database/models/__init__.py` explicitly left
  untouched as out of scope).

---

## N. Manual Founder actions remaining / final verdict

Remaining Founder-only actions are fully enumerated in
`docs/instagram_founder_manual_setup_checklist_1.md`:

- **Group A** — obtain Instagram write-scope credentials (Business Login for Instagram + Meta App
  Review for `instagram_business_content_publish`), complete the OAuth exchange, store the
  resulting token/expiry/account-id as non-secret-identified env vars.
- **Group B** — provision real public HTTPS ingress for Instagram media (domain + TLS in front of
  the already-built `/media/instagram/{asset_id}.jpg` route, or a managed object-storage
  alternative), then configure `INSTAGRAM_MEDIA_PUBLIC_BASE_URL`.

Neither of these was code-closable this phase, and neither was worked around unsafely. Every other
gap from the original rollout report — unified safety gate wiring, same-asset identity enforcement,
durable/idempotent publication state, ambiguous-write reconciliation, and live dry-run runtime
evidence with real candidates — is now closed, tested, and regression-clean, with both publication
flags still `false`.

### Final metrics

```
INSTAGRAM_ACCOUNT_READY=false
INSTAGRAM_CREDENTIALS_READY=false
INSTAGRAM_WRITE_PERMISSION_READY=false
MEDIA_HOSTING_READY=false
INSTAGRAM_UNIFIED_SAFETY_GATE_WIRED=true
PUBLICATION_STATE_PERSISTENCE_READY=true
PUBLICATION_IDEMPOTENCY_READY=true
AMBIGUOUS_WRITE_RECONCILIATION_READY=true
DRY_RUN_RUNTIME_WIRED=true
DRY_RUN_CANDIDATES=8
DRY_RUN_READY=6
DRY_RUN_HOLD=0
DRY_RUN_BLOCK=0
INSTAGRAM_PUBLICATION_ENABLED=false
INSTAGRAM_AUTONOMOUS_PUBLICATION_ENABLED=false
TELEGRAM_CHANGED=false
STORY_MEMORY_CHANGED=false
ARXIV_GUARD_CHANGED=false
TELEGRAM_V8_CHANGED=false
NEW_FAILURES=0
```

### Verdict

**INSTAGRAM_PRODUCTION_READINESS_READY_FOR_FOUNDER_SETUP**

Every code-closable readiness gap from the INSTAGRAM-PRODUCTION-ROLLOUT-1 report is closed and
tested. The two remaining `false` flags (credentials, media hosting) are both genuine Founder/ops
decisions, not code defects, per §17's explicit carve-out — a full manual setup checklist is
provided. No real Instagram write was attempted. STOP per §20.
