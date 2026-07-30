# Phase 16 M5 — Persistence and Retention — Report

Branch: `feature/phase16-image-intelligence`
Checkpoint: `checkpoint/phase16-m5` (created at the end of this milestone)
Prior checkpoint: `checkpoint/phase16-m4`

## 1. M5 objective

Give M1–M4's fully-computed, purely in-memory `ImageIntelligenceResult` a durable home: a bounded
audit table for every candidate that reaches the per-event result, and bounded on-disk byte storage
for only the top-ranked finalists a future milestone (M6, "Telegram Editorial Preview") will need to
show a human editor. Add a lifecycle that reclaims both the bytes and the audit rows on independent
schedules. Zero OpenAI/LLM/vision/embedding/OCR/paid-API calls, zero Telegram sends, zero public
URLs, zero S3 — all explicit M5 non-goals — anywhere in this milestone.

## 2. Starting M4 architecture

M4 left every `ImageCandidate` with a final `RelevanceValidation` (`relevance_score`, `rank`,
`eligible_for_editorial`) and `ImageIntelligenceResult.top_candidate_ids`
(docs/phase16_m4_relevance_ranking_report.md §29 - "M5 starting point"), but nothing was persisted
anywhere: the M4 task brief's own explicit non-goal. `services/image_intelligence.py::
run_shadow_discovery()` remained the single per-event orchestration entry point;
`capabilities/executor.py::_attach_image_intelligence` remained the only call site, attaching the
result to `structured_output["image_intelligence"]` and nothing else. `IMAGE_INTELLIGENCE_MODE`
(`off`/`shadow`) stayed the single top-level gate.

## 3. Persistence-mode gate

`core/config.py::image_candidate_persistence_mode: Literal["off", "metadata", "finalists"] = "off"`
- a second, independent three-state gate, matching `image_intelligence_mode`'s own established
off/shadow precedent exactly:

- **`off`** (default): zero database writes, zero file writes - byte-for-byte identical to
  pre-M5 behavior. The rollback path; no code change is required to disable M5.
- **`metadata`**: persists a bounded audit row per candidate (provenance, technical/quality/
  relevance fields, no image bytes).
- **`finalists`**: additionally stores bytes for up to `image_max_stored_per_event` top-ranked
  finalists, bounded by `image_max_total_stored_bytes_per_event`.

Only consulted when `image_intelligence_mode == "shadow"` - M5 has nothing to persist when M1-M4
never ran. `.env` is untouched; both settings stay at their dormant defaults in production.

## 4. Why one table, not two

`database/models/image_candidate_record.py::ImageCandidateRecord` (table `image_candidates`) is the
single durable model. A second `image_assets` table (bytes metadata keyed separately from candidate
rows) was considered and rejected: the realistic query pattern is always "does this candidate have
stored bytes, and where" (a single row lookup), never "which candidates share this asset" at scale
- and storage is already content-addressed (§7), so a live reference-count query against
`image_candidates.storage_key` at cleanup time answers the one question a separate table would
otherwise need to. One table keeps the upsert/idempotency story (§17) in one place.

## 5. Durable row shape

Every M1-M4 field the M4 report's own `RelevanceValidation`/`QualityValidation`/
`TechnicalValidation` contracts already computed is carried across as a plain column - never a JSON
blob for the fields cleanup/lookup/audit need to filter or sort on (`quality_status`,
`relevance_status`, `rank`, `eligible_for_editorial`, `sha256`, `storage_status`, `expires_at`,
`bytes_expire_at` are all indexed columns); the free-form component/penalty/coverage dicts remain
JSON, since nothing queries into them. `ImageQualityStatus`/`ImageRelevanceStatus`/
`ImageStorageStatus` are separate DB-native enums (not the M3/M4 Pydantic ones) so this table's own
migration history can evolve independently of the in-memory schema (`schemas/image_candidate.py`
§9's own `_enum_values()` helper keeps the stored strings identical to the Pydantic `.value`s used
everywhere else - logs, `step_results` - never a `.name`-vs-`.value` mismatch).

Never contains image bytes (`storage_key` is an internal reference only, §7); never contains
Telethon session/access_hash material, cookies, or authorization headers (M1's own
`TelegramReference` never carries those in the first place).

## 6. Migration

`database/migrations/versions/893fa1b75748_add_image_candidates_table.py` - one new, purely
additive table plus its three new enum types (`image_quality_status`, `image_relevance_status`,
`image_storage_status`). `source_type` reuses the already-existing Postgres enum owned by the
`sources` table's own migration (`create_type=False` - creating it again would fail with "type
already exists"). No existing table, column, or enum is touched or rewritten. Applied cleanly to
the dev database (`alembic_version == 893fa1b75748`, `image_candidates` present) with zero downtime
and zero data migration (the table starts empty).

## 7. Storage abstraction

`integrations/storage/image_storage.py` - not a public file server; no method anywhere in this
module returns or accepts a public URL, and nothing here is reachable from Telegram or any HTTP
route. `ImageStorage` (ABC) is the interface every future backend implements;
`LocalImageStorage` is the only backend this milestone ships - no S3/MinIO client exists in this
repository, and none is added here (an explicit M5 non-goal, confirmed nothing new was added to
`requirements.txt`/`pyproject.toml` for this).

`build_storage_key(sha256, image_format)` produces a fully deterministic, content-addressed key
(`images/<sha256[:2]>/<sha256>.<ext>`) derived exclusively from M2's own decode-confirmed
`sha256`/`format` - never from a source filename or URL path, and never containing any part of the
original remote URL. Sharding by the first two hex characters keeps any single directory from
holding an unbounded number of files as the table grows.

## 8. Storage safety

`LocalImageStorage.store_validated_image()`:

- **Idempotent**: a file already present at the deterministic key with a matching size is a safe
  no-op (the same content, discovered again for a different event/candidate, is never re-written);
  a size mismatch raises `StorageError("hash_key_conflict", ...)` rather than silently overwriting -
  a real conflict (two different byte strings hashing to the same key) is a defensive impossibility
  under SHA-256, but treated as a hard error rather than assumed away.
- **Hash-verified before write**: `hashlib.sha256(data)` is recomputed and compared against the
  caller-declared `sha256` - the caller's own claim about the bytes is never trusted blindly, even
  though it is always M2's own decode-confirmed hash in practice.
- **Byte-budget enforced**: `len(data) > max_bytes` raises before any filesystem write.
- **Atomic write**: written to a temp file inside a `.tmp` subdirectory of the storage root, then
  `os.replace()`d into place - no partially-written file is ever visible at the final path, even on
  a crash mid-write.
- **Path-injection-proof**: every method resolves `storage_key` through `_safe_path()`, which
  rejects an absolute path, a leading path separator, and any `..` traversal segment, then verifies
  the resolved path is still inside the storage root - defense in depth even though
  `build_storage_key()`'s own output is always trusted-generated, never taken from user/network
  input.

## 9. Docker volume

`docker-compose.yml` adds a dedicated named volume (`image_storage_data`), mounted only into
`content_worker` (least privilege - it is the only service that writes finalist bytes in M5), never
bind-mounted into the repo, never committed to Git. `core/config.py::image_storage_root` (default
`/data/image_storage`) is a container-internal path only; the actual persistent location is the
named volume. A future M6 preview-serving service will need its own mount added explicitly when
that need is real, not preemptively here.

## 10. Per-event persistence flow

`services/image_persistence.py::persist_image_intelligence_result()` - the sole M5 write entry
point, called once per event from `run_shadow_discovery()` (§19) immediately after the M4-finalized
`ImageIntelligenceResult` is built:

1. **Always** (whenever this function is called at all - the `"off"` gate lives one level up,
   §19): upsert one audit row per candidate in `result.candidates`, regardless of technical/
   quality/relevance outcome - a rejected/ineligible candidate is persisted too, with its full
   reason trail, never silently dropped (mirrors M4's own "every candidate remains in the result"
   discipline).
2. **Only when `mode == "finalists"`**: additionally attempt byte storage for up to
   `image_max_stored_per_event` candidates with `relevance_validation.eligible_for_editorial`,
   ordered by `rank`, bounded by a running `image_max_total_stored_bytes_per_event` byte budget per
   event - a finalist that would exceed the remaining budget simply stays `not_requested`; nothing
   is ever fabricated or silently truncated to force the configured count (mirrors M4's own
   documented "never fabricated toward the configured count" precedent, §17 of the M4 report).

Reuses the exact same in-memory bytes M2 already fetched for technical/quality validation - never a
second network request or re-fetch for storage purposes. The bounded, transient
`image_bytes_by_candidate_id: dict[str, bytes]` handle lives only inside
`run_shadow_discovery()`'s own local scope (§19); it is never attached to any Pydantic model, never
logged, and goes out of scope the moment the function returns.

## 11. Finalist storage eligibility (defense in depth)

`services/image_persistence.py::_is_storage_eligible()` - deliberately redundant with M4's own
`eligible_for_editorial` flag, since this function is the last line of defense before bytes are
ever written to disk. Every condition must hold independently of the M4 flag: `status ==
VALIDATED`; `quality_validation` present and not `rejected_quality`/`duplicate_exact`/
`duplicate_near`; `deduplication.is_representative is not False`; `relevance_validation` present and
`eligible_for_editorial`; `technical_validation` present, not `animated`, format in the
supported-storage set (`JPEG`/`PNG`/`WEBP`/`GIF` - mirrors `integrations.storage.image_storage`'s
own supported-format set exactly); `sha256` present. A non-representative duplicate or an animated
image can never reach disk here even under a hypothetical upstream mis-flagging.

## 12. URL sanitization

`services/image_persistence.py::sanitize_url()` - every `*_url` column (`article_url`, `source_url`,
`remote_url`, `final_url`) is passed through this before being written. Strips a small, explicit,
case-insensitive set of query-parameter names that commonly carry temporary/signed credentials
(`token`, `auth`, `key`, `secret`, `sig`, `signature`, `session`, `access_token`, the AWS
SigV4/CloudFront query-string family) - every other parameter, and the full path, is kept
unmodified (a blind "strip everything" would make a stored URL useless for future provenance/
debugging, the opposite of what an audit row is for). Applied uniformly regardless of
`image_candidate_persistence_mode` - even a rejected/ineligible candidate's URLs are sanitized
before being written in `metadata` mode.

## 13. Idempotent upsert

`services/image_persistence.py::_upsert_metadata_row()` - a single `INSERT ... ON CONFLICT
(news_event_id, candidate_id) DO UPDATE`, keyed on the table's own `UniqueConstraint`. The `SET`
clause deliberately excludes `storage_status`/`storage_key`/`stored_byte_size`/`stored_at`/
`storage_error_code`/`content_draft_id` - a metadata-only rerun (e.g. `run_shadow_discovery` called
again for the same event, or `image_candidate_persistence_mode` later flipped from `finalists` down
to `metadata`) must never reset a previously-`stored` row's storage fields back to
`not_requested`, and must never clobber a future (M6) editor-assigned `content_draft_id`. Verified
directly (`tests/test_image_persistence.py::test_idempotent_upsert_never_resets_prior_storage_
state`): persisting the same candidate first under `finalists` mode, then again under `metadata`
mode with no bytes supplied, leaves `storage_status == stored` and `storage_key` unchanged.

## 14. Two independent expiry clocks

Deliberately separate columns, separate settings, separate reclaim logic (`services/
image_retention.py`):

- **`bytes_expire_at`** (`image_bytes_retention_days`, default 7): stored finalist bytes are
  speculative disk usage - an unselected finalist's bytes are the more expensive, more
  reclaimable resource, so they expire first.
- **`expires_at`** (`image_metadata_retention_days` default 30 / `image_finalist_metadata_
  retention_days` default 90, whichever applies): the durable audit row itself - cheap to keep,
  and a materially more valuable long-lived record for a finalist than for the overwhelming
  majority of never-selected candidates (M4's own backtest measured ~1.04 finalists per event
  against 2-6 discovered candidates typically, §17 of the M4 report) - hence the two-tier
  metadata retention, finalist rows kept 3x longer than non-finalist rows.

`bytes_expire_at` is always configured shorter than `expires_at`, so the common case is "bytes
reclaimed first, metadata row survives and is reclaimed later" - but `delete_expired_metadata()`
does not assume this ordering: it defensively reclaims any still-`stored` bytes before deleting a
row whose `expires_at` has passed, regardless of `bytes_expire_at` (§15, `tests/
test_image_retention.py::test_delete_expired_metadata_defensively_reclaims_still_stored_bytes`) -
storage keys are content-addressed, so a metadata row is the only way to ever find its own bytes
again; deleting it while bytes are still marked `stored` would leak an unreclaimable file.

## 15. Cleanup integration

`services/image_retention.py::run_retention_cleanup()` - the sole M5 cleanup entry point, hooked
into `worker/content_main.py`'s existing `_run_enabled_loop()` poll loop, gated by
`core/config.py::image_cleanup_every_n_cycles` (default 20): "least coupled existing owner, no new
worker/scheduler" - reuses `content_worker`'s own established cadence instead of a dedicated timer
or cron process. Runs unconditionally on schedule, regardless of the *current*
`image_candidate_persistence_mode` value - a row persisted while a prior mode was active must still
expire on schedule even after the mode later changes; a table with nothing due is a cheap, bounded
no-op scan either way. Both scans (`expire_stored_bytes`, `delete_expired_metadata`) are limited to
`image_cleanup_batch_size` (default 200) rows per call - a large backlog is drained gradually across
several cycles rather than in one unbounded pass (`tests/test_image_retention.py::
test_expire_stored_bytes_batch_size_bound` proves the cap is enforced). Every failure is logged and
swallowed exactly like `run_content_cycle()`'s own established "must not affect delivery"
discipline - a failed cleanup cycle simply retries on the next scheduled call, never crashes the
worker or blocks a content cycle.

## 16. Module boundaries

`services/image_persistence.py` is the sole place SQLAlchemy writes for image candidates happen -
`services/image_relevance.py`, `services/image_quality.py`, `services/image_deduplication.py`, and
`integrations/http/safe_fetch.py` remain entirely database-free, unchanged since their own
milestones (enforced for M3's two modules by the updated `tests/test_image_intelligence_m3.py::
test_m3_modules_never_touch_the_database`, §22). `services/image_retention.py` is a distinct
module for the batch-scan/delete concern - a different access pattern (periodic, bulk) from
`image_persistence.py`'s per-event upsert, kept separate rather than combined into one file.

## 17. M6 read contract

`services/image_persistence.py::get_editorial_image_candidates()` - the bounded read query a future
M6 ("Telegram Editorial Preview") will call: returns `eligible_for_editorial` rows for one event (or
one `content_draft_id`, once M6 assigns one), ordered by `rank`, each flagged `is_expired` (whether
`expires_at` has already passed, even if the row has not yet been physically cleaned up by the next
scheduled cleanup cycle - M6 should treat `is_expired=True` as unusable regardless). Exposes an
internal `storage_key` reference only - never a filesystem path or public URL; M6's own future code
is responsible for resolving it through `integrations.storage.image_storage` when it actually needs
the bytes (e.g. to build a Telegram upload). This module never performs that resolution itself -
kept out of scope for M5, per the M5 brief's own explicit non-goal list (no Telegram send, no
inline keyboard, no editorial confirmation).

## 18. Executor wiring

`capabilities/executor.py::_attach_image_intelligence()` now passes its own already-open
`self._session`/`self._task_id` through to `run_shadow_discovery()` as the new, additive, optional
`session`/`editorial_task_id` keyword parameters - both `None`-defaulting, so every pre-M5 caller
(existing scripts/tests) keeps working unchanged. This is the only call site that ever triggers
persistence in production; every M1-M4 offline script/backtest that calls `run_shadow_discovery()`
without a `session` continues to run in pure memory, exactly as before.

## 19. Persistence trigger inside `run_shadow_discovery()`

`services/image_intelligence.py::run_shadow_discovery()` computes the final, M4-ranked
`ImageIntelligenceResult` exactly as M4 left it, then - only when a caller passed a real `session`
AND `image_candidate_persistence_mode != "off"` - calls `persist_image_intelligence_result()` with
the bounded `image_bytes_by_candidate_id` map collected during M2 validation (§10). A persistence
failure is logged and swallowed; it never fails the "copywriting" step and never changes the
`ImageIntelligenceResult` already computed and returned to the caller - mirrors `apply_fact_safety`'s
and M1-M4's own "must not affect delivery" discipline exactly. `run_shadow_discovery()`'s own return
type is completely unchanged (`ImageIntelligenceResult`) - persistence is a pure side effect.

## 20. Files changed

- `core/config.py` - `image_candidate_persistence_mode`, `image_storage_root`,
  `image_max_stored_per_event`, `image_max_total_stored_bytes_per_event`,
  `image_bytes_retention_days`, `image_metadata_retention_days`,
  `image_finalist_metadata_retention_days`, `image_cleanup_batch_size`,
  `image_cleanup_every_n_cycles` (new settings)
- `database/models/image_candidate_record.py` (new, 205 lines) - `ImageCandidateRecord` ORM model,
  `ImageQualityStatus`/`ImageRelevanceStatus`/`ImageStorageStatus` DB-native enums
- `database/models/__init__.py` - registers `ImageCandidateRecord`
- `database/migrations/versions/893fa1b75748_add_image_candidates_table.py` (new) - the
  `image_candidates` table and its three new enum types
- `integrations/storage/image_storage.py` (new, 171 lines) - `ImageStorage` ABC,
  `LocalImageStorage`, `build_storage_key()`, `StorageError`
- `services/image_persistence.py` (new, ~325 lines) - `persist_image_intelligence_result()`,
  `sanitize_url()`, `_is_storage_eligible()`, `get_editorial_image_candidates()`
- `services/image_retention.py` (new, ~134 lines) - `expire_stored_bytes()`,
  `delete_expired_metadata()`, `run_retention_cleanup()`
- `services/image_intelligence.py` - `run_shadow_discovery()` gains `session`/`editorial_task_id`
  keyword parameters; threads validated bytes through to the new persistence call
- `capabilities/executor.py` - passes `self._session`/`self._task_id` through to
  `run_shadow_discovery()`
- `worker/content_main.py` - hooks `run_retention_cleanup()` into the existing poll loop every
  `image_cleanup_every_n_cycles` cycles
- `docker-compose.yml` - new `image_storage_data` named volume, mounted only into `content_worker`
- `tests/test_image_storage.py` (new, 14 tests), `tests/test_image_persistence.py` (new, 11 tests),
  `tests/test_image_retention.py` (new, 8 tests)
- `tests/test_image_intelligence_m3.py` - `test_no_database_migration_added` (an M3-era assertion
  that no migration existed anywhere in the repo) replaced with
  `test_m3_modules_never_touch_the_database`, which checks the real, still-true M3 invariant (M3's
  own production modules stay DB-free) instead of a blanket repo-wide scan that a later, legitimate
  milestone was always going to invalidate - exactly mirroring how the M4 report itself updated an
  M3-era `version == "m3"` expectation for the same reason (§19 of the M4 report).

## 21. Tests and exact results

- `tests/test_image_storage.py`: 14 passed
- `tests/test_image_persistence.py`: 11 passed
- `tests/test_image_retention.py`: 8 passed
- M5 subtotal: **33 passed**
- Combined `-k image` selection across M1-M5 image-intelligence test files: **342 passed** (309
  M1-M4 + 33 M5)
- `tests/test_capability_executor_image_intelligence.py`: 6 passed (unchanged behavior confirmed
  after the executor wiring change - `image_candidate_persistence_mode` defaults to `"off"` in
  every one of these tests, so persistence never triggers and every pre-existing assertion holds
  byte-for-byte)
- `ruff check .` (full repository): all checks passed
- `mypy` on every new/modified M5 production file (`core/config.py`,
  `database/models/image_candidate_record.py`, `services/image_persistence.py`,
  `services/image_retention.py`, `integrations/storage/image_storage.py`,
  `services/image_intelligence.py`, `capabilities/executor.py`, `worker/content_main.py`,
  `database/models/__init__.py`): no issues found
- Full repository suite (`python -m pytest -q`): see §22

## 22. Full-suite baseline

Re-confirmed the exact pre-existing baseline the M3/M4 reports already documented, unrelated to
Phase 16: `test_capability_executor.py`, `test_content_generation_integration.py`,
`test_content_worker_cycle.py`, `test_editorial_scoring.py`, `test_fact_safety.py` - shared-test-
database pollution/environment mismatch predating this branch. `tests/test_content_worker_main.py`'s
timing-sensitive assertions (`content_generation_poll_interval_seconds = 0.01` real wall-clock
sleeps racing against real DB-backed fixture setup elsewhere in the same full-suite run) reproduced
the identical class of flake the M4 report already documented for a different test in the same
file (§19 of the M4 report) - confirmed a load-related flake, not an M5 regression, by three
consecutive clean, isolated reruns of the entire file (9/9 passed each time).

## 23. Deployment

Migration `893fa1b75748` applied cleanly to the running dev Postgres
(`alembic_version == 893fa1b75748`, `image_candidates` table present, zero downtime, table starts
empty). `docker-compose.yml`'s new `image_storage_data` named volume is additive - `docker compose
up -d` recreates only `content_worker` with the new mount; every other service is untouched.
`IMAGE_INTELLIGENCE_MODE` and `IMAGE_CANDIDATE_PERSISTENCE_MODE` both remain unset in `.env`
(defaulting to `"off"`) - the deployed container performs zero image-related database or file
writes until both are explicitly enabled.

## 24. Zero-AI / non-goal confirmation

No OpenAI SDK, no LLM/vision/embedding/OCR provider, no networking library beyond what M2 already
established, imported anywhere in `database/models/image_candidate_record.py`,
`services/image_persistence.py`, `services/image_retention.py`, or
`integrations/storage/image_storage.py`. No Telegram send, no inline keyboard, no editorial
confirmation flow, no public URL/route, no S3/MinIO client, no change to `services/image_relevance.py`
`services/image_quality.py`, `services/fact_safety.py`, or `services/editorial_scoring.py` - every
M5 non-goal from the task brief held.

## 25. Known limitations

- **No reconciliation pass for out-of-band deletion**: `ImageStorageStatus.MISSING` is a defined,
  reserved state (a row that was `stored` but whose file is confirmed gone at some future
  reconciliation check), but no code path sets it yet in M5 - only `expire_stored_bytes()`'s own
  scheduled expiry currently transitions a row out of `stored`. A file manually removed from the
  named volume out-of-band (e.g. manual disk cleanup) would leave its row incorrectly showing
  `stored` until a future milestone adds an explicit reconciliation scan.
- **Single-process cleanup cadence assumption**: `image_cleanup_every_n_cycles` is a per-process
  cycle counter (`worker/content_main.py`'s own in-memory `cycle_count`), not a distributed lock -
  correct today (one `content_worker` process), but would run redundant (still safe, still
  idempotent) cleanup cycles per replica if `content_worker` were ever horizontally scaled -
  documented as a known limitation, not attempted here, matching M2's own identical documented
  limitation for its per-process concurrency limiter (docs/phase16_m2_secure_fetch_and_validation_
  report.md §17).
- **No filesystem-level orphan scan**: a file that somehow exists on disk with no corresponding DB
  row (should not occur given every write path goes through `persist_image_intelligence_result()`,
  but not exhaustively proven against every conceivable crash window between a successful
  `store_validated_image()` call and its corresponding DB commit) is never found or reclaimed by
  this milestone's cleanup - out of scope, matching the M5 brief's own bounded retention-design
  scope.

## 26. M6 starting point

M5 leaves every editorial-eligible candidate durably stored: a full audit row via
`get_editorial_image_candidates()` and, when `image_candidate_persistence_mode == "finalists"`,
its bytes resolvable through `integrations.storage.image_storage` via `storage_key`. M6 ("Telegram
Editorial Preview") is the natural next step: read the top candidate(s) for a `ContentDraft`,
resolve their bytes, and present them to a human editor for confirmation before send - none of
which is attempted here, per this milestone's own explicit non-goal list.

## 27. Rollback instructions

`IMAGE_CANDIDATE_PERSISTENCE_MODE` stays `"off"` by default - no rollback action is required to
keep M5 fully dormant in production; `IMAGE_INTELLIGENCE_MODE` staying `"off"` (M1's own default)
already made this doubly true. To fully revert the M5 code: `git revert` the M5 commits (or reset
the branch to `checkpoint/phase16-m4`) and rebuild `content_worker`. Because the migration is purely
additive and the table starts empty, a code-only rollback leaves an unused, harmless `image_
candidates` table - `alembic downgrade` remains available if the table itself should also be
removed, dropping its three new enum types after the table (never touching the pre-existing,
M3/M4-unrelated `source_type` enum it reuses).

## M5 verdict

**PHASE 16 M5 COMPLETE — PERSISTENCE AND RETENTION READY**
