# Phase 16 M6 — Telegram Editorial Preview — Report

Branch: `feature/phase16-image-intelligence`
Checkpoint: `checkpoint/phase16-m6` (created at the end of this milestone)
Prior checkpoint: `checkpoint/phase16-m5`

## 1. M6 objective

Let an internal editor/SMM operator review AI-selected images before publication: browse the
M4-ranked, M5-persisted image candidates for a `ContentDraft` inside Telegram, via an inline
keyboard (Previous/Next/Use image/No image/Open source), and record their decision durably. AI
suggests; the human chooses. No automatic image attachment to public news, no channel posting, no
approval→publish pipeline, no public URL/CDN/S3, no new AI/vision/OCR/LLM call - all explicit M6
non-goals, held throughout.

## 2. Starting M5 architecture

M5 (docs/phase16_m5_persistence_and_retention_report.md §26 - "M6 starting point") left every
editorial-eligible candidate durably stored: a full audit row via
`services/image_persistence.py::get_editorial_image_candidates()` and, when
`image_candidate_persistence_mode == "finalists"`, its bytes resolvable through
`integrations.storage.image_storage` via `storage_key`. `ImageCandidateRecord.content_draft_id`
existed as a column but was always `NULL` - M5's own report (§5) documented it as "reserved for
future (M6+) population... no ContentDraft exists yet at the copywriting step." `IMAGE_INTELLIGENCE_
MODE`/`IMAGE_CANDIDATE_PERSISTENCE_MODE` both remained `"off"` in `.env`, unchanged by M6.

## 3. Telegram architecture findings

Directly re-read before writing any code:

- **`bot/loader.py`**: `create_bot()`/`create_dispatcher()` - the only Bot/Dispatcher factories in
  the repo. `content_worker` already constructs a real `Bot` (via `worker/content_main.py`) purely
  to call `bot.send_message()`/now `bot.send_photo()` - it never polls for updates.
- **`bot/main.py`**: the sole place `dp.start_polling(bot)` is called - a manually-run entry point
  (`python -m bot.main`), **not** a `docker-compose.yml` service (confirmed: `docker-compose.yml`
  defines exactly `backend`/`automation_worker`/`news_analysis_worker`/`content_worker`/`postgres`/
  `redis` - no bot/telegram service of any kind). This is the pre-existing, already-established
  deployment model for every interactive command (`/news`, `/digest`, `/settings`, `/status`), not
  something M6 introduced - `docs/phase11_final_completion_report.md` §6 documents `/news` itself
  being live-tested the same way, on demand, by an operator.
- **`bot/handlers/__init__.py`**: aggregates every command router into one root `Router`, already
  registered into the dispatcher by `bot/main.py`. Adding a new router here is the established,
  zero-risk extension point (exactly how `/news` itself was wired in Phase 11).
- **`bot/formatting.py::render_editorial_card()`**: the existing public/internal news-delivery
  card renderer - Contract §3 required this stay untouched, and it is (zero lines changed,
  confirmed by `git diff` scoped to this file being empty).
- **`services/telegram_notifier.py::send_editorial_card()`**: the existing per-draft notification
  call site (`worker/content_cycle.py`) - also required to stay untouched, and does (zero lines
  changed).
- **No prior callback_query/inline-keyboard precedent existed anywhere** in the repo (`bot/
  keyboards/__init__.py` was an empty, reserved-for-future module; a repo-wide grep for
  `callback_query`/`CallbackQuery`/`InlineKeyboard` before this milestone returned zero
  production hits) - M6 is the first feature to use either.

**Decision**: M6 does not add a new docker-compose service or change the bot's deployment model.
The interactive router is wired into the existing, unmodified `bot/main.py`/`bot/handlers`
dispatch chain exactly like every other command - an operator who wants live image-preview
interaction runs it the same way they already run `/news` (see §12/§16). This was a deliberate,
disclosed choice, not an oversight - see §13's known-limitation note on where that process needs
to run for image bytes to resolve.

## 4. Preview flow

```
CONTENT_GENERATION (copywriting step)
  -> run_shadow_discovery() persists candidates (M5, session/editorial_task_id passed by
     capabilities/executor.py, unchanged from M5)
       |
       v
scripts/run_content_generation.py: ContentDraftService creates the ContentDraft
  -> services.image_persistence.link_candidates_to_content_draft() (NEW, §7) backfills
     content_draft_id on this task's own image_candidates rows
       |
       v
worker/content_cycle.py: send_editorial_card() (existing, UNCHANGED) sends the news card
  -> IF image_editorial_preview_enabled AND image_candidate_persistence_mode != "off":
     services.image_preview_notifier.send_image_preview() (NEW, §7) sends the top-ranked
     candidate's preview with an inline keyboard - a second, independent, additive message
       |
       v
Human clicks a button in Telegram -> bot/handlers/image_preview.py callback handler (NEW, §6)
  -> re-queries current candidate state, mutates editor_decision, edits the message in place
```

## 5. Renderer design

`bot/image_preview_formatting.py` - a deliberately separate, pure module (no aiogram/Bot type
anywhere in it, mirroring `bot/formatting.py`'s own established discipline exactly). Never touches,
imports, or duplicates `render_editorial_card()`.

- `render_image_preview_caption()`: HTML-escaped, includes derived source domain (from
  `article_url`/`source_url` - `ImageCandidateRecord.source_name` stays reserved/unused per M5's
  own design, no new stored field added for this), quality/relevance scores, dimensions, and the
  M4-produced `relevance_reason` string verbatim - **no new bullet-point/editorial-judgment
  heuristic is invented here**; the "Reason:" line is exactly M4's own already-audited template
  output (docs/phase16_m4_relevance_ranking_report.md §16), never re-derived or embellished.
  Capped at `CAPTION_SAFE_LIMIT` (1024 UTF-16 code units - Telegram's own photo-caption limit,
  distinct from and much smaller than `bot/formatting.py`'s 4096-unit message limit).
- `render_no_candidates_text()`, `render_decision_confirmation_text()`,
  `render_expired_candidate_alert_text()`, `render_unavailable_candidate_alert_text()`: the
  remaining fixed, template-driven strings the flow needs.
- A dedicated test (§10) asserts the rendered caption never contains a `storage_key`, the storage
  root path, or an OS-specific absolute path fragment - only derived, human-readable metadata ever
  reaches Telegram.

## 6. Callback state design

No new state table, no Redis (Contract §5's own explicit "prefer existing JSON/state mechanisms"
preference, followed to its natural conclusion: none was needed at all). Every piece of state a
callback requires travels entirely inside `callback_data` itself:

`bot/keyboards/image_preview.py::encode_callback_data()` / `parse_callback_data()`:
`imgprev:<action>:<content_draft_id>:<index>` (action ∈ `{prev, next, use, none}`) - a fixed
8-byte prefix, a short action word, a 36-character UUID, and a small integer: comfortably under
Telegram's 64-byte `callback_data` limit (verified directly, §10). `parse_callback_data()` returns
`None` (never raises) for anything malformed - a missing/extra field, an unknown action, a
non-UUID draft id, a non-integer or negative index, a wrong prefix - proven against a dedicated
table of adversarial payloads including path-traversal- and SQL-injection-shaped strings (§10).

Every callback re-queries `services.image_persistence.get_editorial_image_candidates()` fresh -
**the candidate list is never cached or trusted from an earlier render.** This is what makes
navigation safe against a candidate expiring, being deleted, or a decision already having been
made by the time a button is actually pressed (docs' own "no race causing wrong selection"
requirement) - the current database state is always the single source of truth, `callback_data`
only ever encodes "which draft, which position," never "what the candidate looked like when this
button was created."

"✅ Use image"/"🚫 No image" durable decisions live on `ImageCandidateRecord` itself (§7's new
columns) - not a new tri-state flag on `ContentDraft` (no schema change to that table): "no image"
is represented as "every candidate row for this draft is `REJECTED`," never a separate marker.

## 7. Storage interaction / new columns / migration

Migration `31a8d7c95c87_add_image_editor_decision_and_telegram_.py` - three new, purely additive
columns on the existing `image_candidates` table (no existing column touched):

- `editor_decision` (`image_editor_decision` enum: `selected`/`rejected`, nullable, indexed) +
  `editor_decision_at` (timestamp) - the durable human decision (§6).
- `telegram_file_id` (nullable string) - caches the Telegram-issued reference after a candidate's
  first successful photo upload, so every later view of the same candidate resends via
  `bot.send_photo(chat_id, photo=file_id)` - a plain string, zero local byte reads, valid
  regardless of which process/container sends it (as long as it holds this bot's own token). Only
  the first view of any given candidate ever needs local storage access at all.

`services/image_persistence.py` additions (the sole place SQLAlchemy writes for image candidates
happen, unchanged invariant from M5 §16): `link_candidates_to_content_draft()` (a single bounded
`UPDATE ... WHERE editorial_task_id = :id`, scoped to one task's own rows only - §10 of this
report, proven never to touch a different task's candidates, §10 test), `set_editor_decision()`
(atomically selects one row and rejects every sibling for the same draft in the same call - never
leaves two `SELECTED` rows for one draft), `reject_all_candidates()`, `read_candidate_bytes()` (the
**sole** place `bot/handlers/image_preview.py`/`services/image_preview_notifier.py` ever resolve
actual bytes - neither imports `integrations.storage.image_storage` directly), and
`record_telegram_file_id()`. `EditorialImageCandidate` gained `relevance_reason`,
`telegram_file_id`, `editor_decision` fields (additive - every M5 field/consumer unchanged).

## 8. Security considerations

- **No filesystem path or storage root ever reaches Telegram**: `storage_key` (an internal
  reference) is read server-side only, inside `read_candidate_bytes()`, and never rendered into
  any caption/text/log visible to the operator (§5's dedicated test). `core/config.py::
  image_storage_root` is never interpolated into any user-facing string anywhere in this
  milestone's code.
- **`callback_data` is never trusted blindly**: `parse_callback_data()` rejects any malformed
  payload before it reaches application logic (§6); `set_editor_decision()` additionally verifies
  the referenced candidate row actually belongs to the given `content_draft_id` before mutating
  anything - a callback referencing a real row id from a *different* draft (a tampered or stale
  callback) is rejected, never silently applied to the wrong draft (dedicated test, §10).
- **Path traversal**: `read_candidate_bytes()` delegates to `LocalImageStorage`, whose own
  `_safe_path()` (M5, unchanged) already rejects absolute paths, leading separators, and `..`
  segments - re-verified directly against a crafted `storage_key` in this milestone's own test
  suite (§10), not merely assumed carried over from M5.
- **"Open source" is a `url=` inline button**, not a callback - Telegram resolves it client-side;
  no server-side handling, no additional attack surface, exposes nothing beyond the article URL
  already visible in the preview text itself.
- **No image bytes, file_id, or storage key is ever logged** - only `candidate_row_id`/
  `content_draft_id` (UUIDs) appear in any log line this milestone adds.
- **`InaccessibleMessage` handled explicitly**: a callback on a message Telegram can no longer edit
  (too old / from a bot restart) answers with an alert rather than raising or silently no-op'ing.

## 9. Configuration

`core/config.py::image_editorial_preview_enabled: bool = False` (new, single setting - Contract
§7's own "add configuration only if required" kept to the minimum). Only consulted by
`worker/content_cycle.py`'s own gate; `services/image_preview_notifier.py` and
`bot/handlers/image_preview.py` have no "off" branch of their own beyond "there happen to be zero
candidates," since a human can only ever reach the callback handler by pressing a button on a
message that was already sent - which itself never happens unless the flag was on at send time.
`.env` was not modified; the setting stays at its dormant default in every currently-deployed
environment.

## 10. Tests

- `tests/test_image_preview_formatting.py`: 15 passed (caption content, HTML escaping, expired/
  metadata-only flags, no-storage-path-leak, UTF-16 caption-limit safety, missing-field handling)
- `tests/test_image_preview_keyboard.py`: 20 passed (encode/decode roundtrip, byte-limit, malformed/
  injection-shaped payload rejection, Previous/Next boundary omission, Use/No-image always present,
  Open-source URL-button-not-callback, draft-id consistency across all buttons)
- `tests/test_image_preview_handler.py`: 11 passed (malformed callback ignored, inaccessible
  message alert, no-candidates alert, text↔photo message-type switching on navigation, file_id
  caching after first upload, expired-candidate blocks both navigation and "Use image," "No image"
  rejects every row, cross-draft candidate-id rejection, query-failure alert-never-raises)
- `tests/test_image_preview_notifier.py`: 6 passed (no-candidates no-op, photo send + file_id
  cache, text-only fallback when no bytes, `chat_id=None` fail-fast with real candidates, send-
  failure caught and reported, zero-LLM/zero-network static import proof)
- `tests/test_image_persistence_m6.py`: 16 passed (`link_candidates_to_content_draft` scoping/
  zero-match, `set_editor_decision` select-one-reject-siblings/idempotency/cross-draft rejection/
  nonexistent-row rejection, `reject_all_candidates` idempotency/override-prior-selection,
  `read_candidate_bytes` not-stored/no-key/real-read/missing-file/path-traversal-rejected,
  `record_telegram_file_id`, `get_editorial_image_candidates` exposes the three new fields)
- `tests/test_content_worker_cycle_image_preview.py`: 4 passed (disabled-by-default never calls
  the preview send; enabled calls it with the correct `content_draft_id`; a preview-stage failure
  is counted and never raises, and never affects `send_editorial_card`; inert when persistence
  mode is `"off"` even with the flag on)
- `tests/test_run_content_generation.py`: 2 new (8 total, was 6) - the successful-draft-links-
  candidates wiring test, and the link-failure-does-not-affect-the-draft-outcome test
- **M6 subtotal: 74 passed** (72 new dedicated tests + 2 additions to an M5-era test file)
- Combined `-k image` selection across M1-M6 image-intelligence test files: **416 passed**
  (342 M1-M5 + 74 M6)
- `ruff check .` (full repository): all checks passed
- `mypy` on all 11 new/modified M6 production files: no issues found
- `python -m scripts.validate_architecture`: clean, 0 forbidden-dependency violations
- No test in any M6 file sends a real Telegram message, opens a real network socket, or calls
  OpenAI/any LLM provider - every Bot instance in every M6 test is constructed with a fake,
  in-memory `BaseSession` subclass overriding `make_request()` (the exact technique
  `tests/test_news_handler.py` already established and proved feasible against the real, installed
  aiogram version), and `tests/test_image_preview_notifier.py` additionally statically proves
  (AST-free source-text check, matching this repo's own established `test_no_provider_calls_
  anywhere_in_m3_modules`-style convention) that the module imports nothing from `openai`/
  `integrations.llm_gateway`.

## 11. Full-suite baseline

`python -m pytest -q` (full repository): reconfirmed the exact pre-existing baseline the M3/M4/M5
reports already documented, unrelated to Phase 16 - the same `test_capability_executor.py`,
`test_content_generation_integration.py`, `test_content_worker_cycle.py`, `test_editorial_scoring.py`,
`test_fact_safety.py` failures (shared-test-database/environment `content_generation_dry_run`
mismatch predating this branch). No new failure was introduced by any M6 change.

## 12. Deployment

Migration `31a8d7c95c87` applied to the dev Postgres and round-tripped
(`upgrade → downgrade → upgrade`, confirmed clean both directions, §7). `docker compose build
content_worker` completed a full, reproducible build including every new M6 module (`bot/handlers/
image_preview.py`, `bot/image_preview_formatting.py`, `bot/image_preview_media.py`, `bot/keyboards/
image_preview.py`, `services/image_preview_notifier.py`); `docker compose up -d --no-deps
content_worker` recreated the container, which started cleanly and continued its normal
`CONTENT_GENERATION` cycle with zero import/startup errors. `docker-compose.yml` itself was **not**
modified - no new service, no new volume mount (§3's own disclosed deployment-model decision).
`backend`/`automation_worker`/`news_analysis_worker` were not rebuilt - none of them import any
M6-changed module (confirmed by grep). `IMAGE_EDITORIAL_PREVIEW_ENABLED` was not set in `.env` and
remains `False` by default; `IMAGE_INTELLIGENCE_MODE`/`IMAGE_CANDIDATE_PERSISTENCE_MODE` remain
`"off"` - the deployed container sends zero image-preview Telegram messages.

## 13. Known limitations

- **Interactive polling still requires a manually-run process**, matching the pre-existing
  deployment model for every other interactive command (`/news`, `/settings`, ...) - `bot/main.py`
  is not a `docker-compose` service (§3). For the callback handler to actually resolve stored image
  bytes on a candidate's first view (before its `telegram_file_id` is cached), that process needs
  access to the same `image_storage_data` volume `content_worker` already mounts - in practice, run
  it via `docker compose exec content_worker python -m bot.main` rather than bare on the host.
  Running it without that access still works correctly (never crashes): `read_candidate_bytes()`
  returns `None` on any storage error and the renderer falls back to a text-only preview - but a
  candidate's photo will only actually display once viewed from a process with real storage access
  at least once (after which the cached `telegram_file_id`, §7, makes every later view
  storage-independent, from any process).
- **No cross-replica lock on the editorial decision**: `set_editor_decision()`'s "select one,
  reject siblings" logic is a plain multi-statement update, not wrapped in an explicit
  `SELECT ... FOR UPDATE` - correct for the current single-operator, single-bot-process reality,
  but two simultaneous "Use image" presses on two different candidates for the same draft (a
  human clicking twice quickly, or two operators) could theoretically race; the last write wins,
  never producing two `SELECTED` rows, but which one wins is not deterministic under true
  concurrency. Documented, not fixed - matches this repo's own established precedent for
  documenting rather than over-engineering low-probability single-operator races (e.g. M2's own
  per-process concurrency-limiter limitation).
- **No reconciliation for an out-of-band-deleted stored file**: identical, carried-over limitation
  from M5 (§25 of that report) - `read_candidate_bytes()` degrades gracefully (returns `None`) but
  the row's own `storage_status` is not proactively corrected to `MISSING` until a future
  reconciliation pass exists.
- **`source_name` display is derived, not stored**: the caption's "Source:" line is computed from
  `article_url`/`source_url` at render time (§5), never persisted as a new column - correct and
  sufficient for M6, but means the exact displayed label could differ slightly (e.g. an unusual
  redirect chain) from any future stored/audited source-name field, should one be added later.

## 14. M7 starting point

M6 leaves every editorial decision (`editor_decision`/`editor_decision_at` on
`ImageCandidateRecord`) durably recorded, independent of the Telegram message that produced it -
`services.image_persistence` exposes everything a future milestone needs to actually *do* something
with a `SELECTED` candidate (attach it to a publish pipeline, resolve its bytes for an outbound
post, etc.) without re-deriving any of M1-M6's own work. That "attach the selected image to
anything public" step is explicitly **not** attempted here (M6's own non-goal list) - it is the
natural, disclosed scope for whatever Phase 16 M7 (or a later phase) turns out to be, alongside any
reconciliation/cross-replica-locking hardening noted in §13.

## 15. Rollback

`IMAGE_EDITORIAL_PREVIEW_ENABLED` stays `False` by default - no rollback action is required to keep
M6 fully dormant in production (identical in spirit to every prior Phase 16 milestone's own
rollback story). To fully revert the M6 code: `git revert` the M6 commits (or reset the branch to
`checkpoint/phase16-m5`) and rebuild `content_worker`. The migration is purely additive
(`editor_decision`/`editor_decision_at`/`telegram_file_id`, all nullable) - `alembic downgrade -1`
cleanly removes all three columns and the new enum type without touching any M1-M5 column, verified
directly via the upgrade→downgrade→upgrade roundtrip in §12.

## M6 verdict

**PHASE 16 M6 COMPLETE — TELEGRAM EDITORIAL PREVIEW READY**
