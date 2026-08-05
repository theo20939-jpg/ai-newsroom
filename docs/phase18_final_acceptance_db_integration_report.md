# Phase 18 Final Acceptance — DB Integration Report

All tests in this report ran against real PostgreSQL 16.14 (`phase18_validation_db`, a dedicated
disposable database) and real Redis, via `tests/conftest.py`'s `db_session` fixture (rolled back
per test) and, where noted, `redis_client`. No mocked session objects were used anywhere in this
stage.

## 1. Executor hook validation (`tests/test_phase18_db_integration.py`)

Mirrors `tests/test_phase17_m5_integration.py`'s exact proven shape (real `CapabilityExecutor` +
`WorkflowRunner`, real DB). 9 tests, all passing:

- `_attach_meme_opportunity` (M1): off-mode writes nothing; shadow-mode attaches and *persists*
  into `EditorialTask.workflow`'s durable JSON (re-read from a fresh `db_session.get()`, not just
  the in-memory result); a hook failure (monkeypatched to raise) does not fail the parent "quality"
  step — the step still returns `SUCCESS` with its own real output intact; a genuinely sensitive
  story (swatting/shooting) reaches `SENSITIVE_BLOCK` through the real executor path end-to-end.
- `_attach_meme_safety_originality` (M3): identical four-part coverage (off/shadow/persisted/
  failure-isolated), against a real `MemeConceptCapability`-shaped fake output at the
  "meme_concept" step of a `MEME_GENERATION`-typed workflow.
- **Zero `AIExecution` rows written by either hook** — both are zero-LLM-call by design (M1/M3's
  own reports); proven directly by counting `AIExecution` rows after running both hooks together,
  not merely asserted from source reading.

## 2. MemeCandidateService validation

6 additional tests plus the offline E2E suite (§3) exercise every method:

- `create_from_concept`, `get_by_id`, `add_cost` (accumulation + negative-rejection), `record_
  editor_decision` (idempotency + missing-row handling), `build_feedback_summary` — all covered in
  the migration report §5 and not repeated here.
- **Real finding, documented not silently fixed**: `record_editor_decision()` does not merge
  `reasons`/`notes` across repeated calls — a second call that omits `notes` clears a previously
  recorded value (`test_repeated_decision_without_notes_overwrites_prior_notes`). This matches the
  method's own documented "overwrites the prior decision fields" contract; it is flagged here
  because no production caller passes partial updates today, but a future caller (e.g. a UI that
  lets an editor add notes after the fact in a separate step) must supply the full desired state
  on every call, not a delta. Not changed - this is intended, disclosed behavior, not a bug.
- **Five new persistence methods added during acceptance** (`attach_safety_assessment`,
  `attach_copy`, `attach_image_result`, `attach_render_result`, `attach_quality_assessment`) —
  each M3-M7 milestone report disclosed "no persistence method yet" as a deferred gap; this
  acceptance pass closes it, using only columns M2's migration already reserved (zero new
  migration). A genuine status-taxonomy gap was found and resolved while doing so: M7's
  `MemeQualityDecision` has 5 values but `MemeCandidateStatus` (designed at M2, before M7 existed)
  has only 3 quality-stage values plus `PENDING_EDITOR` - no dedicated status exists for
  "needs a new concept" or "needs a new image." Resolved with a documented mapping
  (`_QUALITY_DECISION_TO_STATUS` in `services/meme_candidate_service.py`) rather than a new enum
  value/migration: a regenerate recommendation reverts `status` to the stage that must actually be
  redone (`CONCEPT_GENERATED` or `COPY_GENERATED`), which is more informative to a future
  orchestrator than a single generic "needs regeneration" state would be.
- Real foreign-key enforcement proven (§ migration report §5).

## 3. Complete offline end-to-end pipeline (`tests/test_phase18_meme_pipeline_offline_e2e.py`)

See `docs/phase18_final_acceptance_offline_e2e_report.md` for full detail — summarized here since
it is also, structurally, a DB integration test (every persistence call in it hits real Postgres).

## 4. Cost-accounting integration — Stage E.3 finding

**Requirement**: prove the connection between `AIExecution`/`RedisCostTracker` (capability-call
cost tracking) and `MemeCandidate.cumulative_cost_usd` (per-candidate cost accounting), or
document explicitly why it is deferred.

**Finding: these two systems remain genuinely disconnected, and this is correctly classified as
(B) intentionally deferred live-orchestrator work, not (A) an acceptance blocker.**

Reasoning:
- `AIExecution` rows are written by `capabilities/executor.py::_record_cost()`, which only runs
  when a `CapabilityExecutor` is constructed with real `cost_tracker`/`pricing_catalog`
  instances — i.e., only inside a real, running `WorkflowRunner` execution. No such execution of
  `MEME_GENERATION` has ever happened outside of this acceptance session's own tests (which
  construct `CapabilityExecutor` *without* those two arguments, matching every other Phase 18/
  Phase 17 shadow-hook test's own established convention of not exercising cost recording
  incidentally).
- `MemeCandidate.cumulative_cost_usd` is written only by `MemeCandidateService.add_cost()`, called
  directly by test/script code in this acceptance session (§ offline E2E report) — never by
  `capabilities/executor.py` itself, since no code anywhere calls `add_cost()` after a real
  `meme_concept`/`meme_copywriting` capability call completes.
- **The offline E2E test proves each system works correctly in isolation** (a real
  `MemeConceptCapability`/`MemeCopywritingCapability` call happens with a `FakeLLMGateway`; a real
  `add_cost()` call happens with the image generation's own real, zero cost) but does **not** prove
  they are wired to fire *together* automatically from one real LLM call, because no code triggers
  that pairing today.
- **This is correctly deferred, not a blocker**, because: (1) no `MEME_GENERATION` task is ever
  created automatically (§ inertness audit) — there is no live call site this wiring could even
  attach to yet; (2) building that wiring would mean deciding *where* the cost-attribution call
  belongs (inside `capabilities/executor.py` generically for any future capability with a
  `MemeCandidate` counterpart, or inside a not-yet-built meme-specific orchestrator) — a real
  design decision the brief's own M2-M9 milestones never made and this acceptance pass should not
  invent unilaterally under an audit mandate that explicitly excludes "expand the scope of Phase
  18 with unrelated functionality."
- **No double-charging risk exists today** for the same reason: since nothing calls both systems
  for the same event, there is no code path that could double-count. This will need a real design
  (idempotency key, or a single call site owning both writes in one transaction) once an
  orchestrator is built — flagged here as a known future requirement, not solved speculatively now.

**Conclusion**: cost tracking is **implemented and tested** at the level of each individual
system (`AIExecution` via the existing, unmodified Phase 17 cost-recording path; `MemeCandidate.
cumulative_cost_usd` via `add_cost()`), but **not yet integrated** into one automatic flow. This
is accurately reflected in the acceptance matrix (main report §16) as two separate rows, not one
overstated "cost integration: done" claim.

## 5. Bot handler validation

`bot/handlers/meme_preview.py` requires a live Telegram `Bot`/`CallbackQuery` object to exercise
directly (its DB reads/writes go through the same `MemeCandidateService` already validated above,
but its own routing logic is untested against a real callback dispatch in this session — no
Telegram network connection was made or attempted, per the operating rules). What *was* validated:
every pure/DB-adjacent piece it depends on:
- `bot/keyboards/meme_preview.py` + `bot/keyboards/meme_feedback.py`: callback_data encode/parse
  round-trips for every documented action (25 + 18 tests, `tests/test_phase18_m8_meme_telegram_
  preview.py` / `tests/test_phase18_m9_meme_feedback.py`, unchanged from the M8/M9 development
  session, still passing).
- `services/meme_preview_notifier.py::send_meme_preview()`: dry-run contract proven with a bot
  double (`_NeverCalledBot`) that raises on any attribute access — reused directly inside the
  offline E2E test (§3) with a real `MemeCandidateService`-backed candidate, not just synthetic
  fixture data.
- `MemeCandidateService.record_editor_decision()`/`get_by_id()`: the exact methods the handler
  calls, now proven against real Postgres (§2).

Building a true `CallbackQuery`/aiogram-dispatcher-level test (mocking Telegram's own wire
protocol rather than the `Bot` object) was assessed and deferred — it would require either a real
Telegram Bot API test double library not currently a dependency of this project, or extensive new
aiogram-internals mocking disproportionate to what this acceptance pass's own "minimal fixes"
mandate calls for. This is disclosed as a real, remaining gap (main report §15), not silently
treated as covered.
