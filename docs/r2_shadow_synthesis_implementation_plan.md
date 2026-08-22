# R2 Shadow Synthesis — Implementation Plan

**Status: PLAN ONLY — no code written. Waiting for confirmation, same discipline as every prior
R2 Shadow round.** Reflects the fully-updated `docs/r2_shadow_synthesis_contract.md` after this
round's four owner-required refinements: (1) checked `services/event_recap.py` is avoidable
entirely — confirmed, via the existing `gateway` dependency-injection interface; (2) `max_tokens`/
`max_chars` output safety; (3) a formalized Human Review Protocol; (4) causal-connective detection
reconfirmed as flag-only metadata, never a rewrite/reject/block.

## 1. Design decisions (resolving the contract's own §9 open questions)

1. **New script**: `scripts/_recap_r2_shadow_synthesize.py`. Same reasoning R2 Shadow v1 already
   established for itself over extending an older tool — this stage has its own output vocabulary
   (`evaluation_status`, `quality_notes`) the pre-existing `scripts/_recap_r2_event_shadow.py` was
   never designed to carry.
2. **`services/event_recap.py` is not touched, at all, for any reason, at this stage** — confirmed
   this round by checking the existing interface first, not by assumption. `synthesize_event_recap()`
   already takes `gateway: LLMGateway` as a caller-supplied parameter; `GenerateRequest` is an
   immutable pydantic model supporting `.model_copy(update={...})`; `call_generate()` forwards the
   built request to `gateway.generate()` directly. The new script's own Gateway wrapper intercepts
   the request there and applies `max_tokens`/`reasoning_effort` — verified by direct execution this
   round (`request.model_copy(update={"max_tokens": 1000, "reasoning_effort": "none"})` produces a
   correct, independent copy; confirmed empirically, not assumed). Zero existing-file changes
   required for cost safety.
3. **`--from-shadow-run <dir>` is a hard requirement** (contract §3a) — the script refuses to run
   (exit 2, before any DB connection) unless `--from-shadow-run <dir>/story_<story-id>.json` exists.
4. **`max_chars=4000`** (contract §4b) is enforced as a **flag, not a hard failure** — added to
   `quality_notes`, which already escalates `evaluation_status` to `NEEDS_REVIEW` via the existing
   rule. Measured against the rendered `render_event_recap_telegram_preview()` output text
   (resolving the contract's own §9.4 — the rendered text is what a human would actually read, more
   meaningful than summing raw field lengths, and reusing the already-built renderer costs nothing
   extra).
5. **Starting `max_tokens`/`reasoning_effort` values**: `1000`/`"none"` — closest real precedent
   `capabilities/executor.py::_MAX_OUTPUT_TOKENS_BY_CAPABILITY["research"]`/
   `_REASONING_EFFORT_BY_CAPABILITY["research"]`, both explicitly starting points, not final.
6. **Causal-connective term list** (contract §4c): a small, explicit, hand-curated starter list —
   `("because", "as a result", "this led to", "in response to", "due to", "потому что", "в
   результате", "это привело к", "в ответ на", "из-за")`.
7. **The old script's own behavior is untouched** — `scripts/_recap_r2_event_shadow.py`'s existing
   `--with-llm` call to `synthesize_event_recap()` is not modified in any way; moot regardless of
   decision 2, since nothing in `services/event_recap.py` changes.

## 2. Files to touch — final list

**Two new files. Nothing else. No existing file is modified, added to, or otherwise touched.**

### `scripts/_recap_r2_shadow_synthesize.py` (new)

- CLI: `--story-id` (required, `type=UUID`), `--from-shadow-run` (required, `type=Path`),
  `--output-dir` (default: same as `--from-shadow-run`).
- **No `--limit` argument exists at all** — structurally single-Story.
- **Human Review Protocol precondition** (contract §3a, item 1): before any DB connection,
  `(--from-shadow-run / f"story_{story_id}.json")` must exist — else print the missing path and
  exit 2.
- **Human Review Protocol reinforcement** (§3a, item 3): once that file is confirmed to exist, its
  own `readiness_state`, `evaluation_status`, `announcement_count`, and every `quality_notes` entry
  are read and re-printed to stdout **before** the DB connection opens — the operator sees the
  R2.11 caveat and every other flag again, at the exact moment before spend, not just whenever they
  may have originally opened the file.
- Read-only DB guard (`ReadOnlyGuardError`/`_verify_read_only()`), duplicated verbatim.
- Build the deterministic candidate: `build_event_recap_candidate(session, story, force_shadow=True,
  now=now)`.
- **Transaction closed** (rollback, connection close, engine dispose) — **before** any Gateway
  import or call (contract §6).
- Build `RuntimeContext` (`capability_name="event_recap_synthesis_shadow_v2"`, distinguishing this
  from the old script's own `"event_recap_synthesis_shadow"` in observability/cost dashboards).
- Build the single-attempt Gateway wrapper (duplicated `_SingleAttemptGateway`-equivalent, extended
  with the one-line `model_copy(update={"max_tokens": 1000, "reasoning_effort": "none"})`
  interception inside its own `generate()` method — decision 2 above).
- Call `synthesize_event_recap(candidate, gateway, prompt_repository, runtime=runtime)` — the real,
  **unmodified** function signature, no new parameters.
- On success: render `render_event_recap_telegram_preview(synthesized_candidate)`, measure its
  length against `max_chars=4000` (flag only, per decision 4), compute the extended
  `quality_notes` (media/announcement-count checks + the new causal-connective flag) and
  `evaluation_status`; write `story_<id>_synthesis.json` (all fields per contract §7,
  `readiness_state`/`publishable` carried through read-only, never recomputed) and
  `story_<id>_synthesis.txt` (the rendered preview text, verbatim).
- On `EventRecapSynthesisError`: print the error, write neither artifact, exit non-zero.
- Print cost-visibility lines matching `scripts/_recap_r2_event_shadow.py`'s own established
  format (`LLM_ENABLED=True`, `SINGLE_ATTEMPT=True`, `MAX_PROVIDER_ATTEMPTS=1`,
  `physical_provider_attempts=`/`fallback_attempts=`/`same_candidate_retries=`).

### `tests/test_recap_r2_shadow_synthesize.py` (new)

See §5. Fully self-contained — covers the Gateway-wrapper `model_copy` interception, the Human
Review Protocol precondition/reinforcement, `max_chars` flagging, causal-connective detection, the
`readiness_state`/`publishable` passthrough invariant, and every structural safety guard. No
existing test file is touched.

## 3. Files reused, unchanged

| Reused unchanged | From |
|---|---|
| `EventRecapCandidate`, `build_event_recap_candidate()`, `render_event_recap_bundle_text()`, `render_event_recap_telegram_preview()`, `synthesize_event_recap()`, `EventRecapSynthesisError` | `services/event_recap.py` — real, unmodified signatures throughout |
| `evaluate_fact_safety()` (transitively, via `_verify_synthesis_facts()`) | `services/fact_safety.py` (frozen) |
| `assemble_ai_integration_layer()` | `integrations/llm_gateway/boot.py` |
| `RuntimeContext` | `schemas/capability.py` |
| `GenerateRequest.model_copy()` | `integrations/llm_gateway/protocol.py` — standard pydantic API, not a new mechanism |

**Deliberately duplicated, not imported** (mirrors this codebase's own established per-script-
private-helper convention):

- `ReadOnlyGuardError` / `_verify_read_only()` — every R2 script duplicates this.
- `_SingleAttemptGateway`/`_build_single_attempt_gateway()`-shaped logic — **not imported across
  scripts**, unlike `scan_story_readiness()`/`CandidateScanRow` in R2 Shadow v1 (ordinary evaluation
  logic, legitimately shared). This is the entire mechanism behind "at most one physical provider
  attempt" plus the new `max_tokens`/`reasoning_effort` interception — the single most safety-
  critical piece of code in this contract. Duplicated so each script's own safety guarantee stays
  fully self-contained and independently auditable; a future change to the old script's copy can
  never silently affect this new script's own safety property.
- `_compute_quality_notes()`-shaped logic — this script needs an *extended* version (the new
  causal-connective and `max_chars` checks) R2 Shadow v1's batch script has no reason to carry;
  duplicated with the extension rather than imported and monkey-patched.

## 4. Safety checks

| Check | Mechanism |
|---|---|
| `services/event_recap.py` untouched | Confirmed via `git diff --check`/`git status` showing only the two new files |
| No batch execution | No `--limit` argument exists in the parser at all (AST-verified) |
| Human Review Protocol | `--from-shadow-run`/`--story-id` precondition file-existence check, checked before any DB connection; prior artifact's key fields re-printed before spend (contract §3a) |
| Read-only DB | Duplicated guard, verified via `SHOW transaction_read_only` |
| No DB writes | Structural (only `select`/`session.get`), plus a zero-write invariant test |
| Transaction closed before Gateway | Structural ordering in `main()`, matching contract §6 |
| At most 1 physical attempt | Duplicated single-attempt Gateway wrapper (`max_same_candidate_retries=0`, `max_fallback_attempts=1`) |
| `max_tokens`/`reasoning_effort` always set | The wrapper's own `generate()` always applies `model_copy(update={...})` — structurally impossible to omit |
| `max_chars=4000` | Flag-only via `quality_notes` — never blocks writing the artifact, never truncates the text |
| Causal-connective detection | Flag-only via `quality_notes` — no rewrite, no reject, no block, verified by a dedicated test asserting the synthesized text itself is never modified |
| No Telegram/worker/bot import | Self-contained AST guard in the new test file |
| `readiness_state`/`publishable` never recomputed | Carried through read-only; dedicated invariant test |
| Neither artifact written on failure | `EventRecapSynthesisError` caught at the top level, both writes skipped, non-zero exit |

## 5. Tests to add

1. `test_gateway_wrapper_applies_max_tokens_and_reasoning_effort` — the new script's own Gateway
   wrapper, given a `GenerateRequest` with `max_tokens=None`, produces a forwarded request with
   `max_tokens=1000, reasoning_effort="none"` (unit test against the wrapper's `generate()` logic
   with a fake downstream routing engine — no real network).
2. `test_shadow_synthesize_requires_prior_shadow_run_output` — missing `story_<id>.json` in
   `--from-shadow-run` → exit 2, no DB connection attempted (verified via a fake/absent DB URL that
   would fail loudly if ever reached).
3. `test_shadow_synthesize_reprints_prior_artifact_fields_before_spend` — given a real
   `story_<id>.json`, the precondition step re-prints `readiness_state`/`evaluation_status`/
   `announcement_count`/`quality_notes` to stdout before proceeding.
4. `test_shadow_synthesize_has_no_limit_argument` — AST-parsed `add_argument` calls.
5. `test_shadow_synthesize_has_no_bot_worker_or_gateway_import_at_module_level` — module-level-only
   AST guard (deferred Gateway import inside the actual call path is expected).
6. `test_build_synthesis_report_writes_separate_artifacts` (DB-backed + `FakeLLMGateway`) —
   `story_<id>_synthesis.json`/`.txt` written; a pre-existing `story_<id>.json` fixture file in the
   same directory is never modified (byte-for-byte unchanged).
7. `test_readiness_state_and_publishable_carried_through_unchanged` — written synthesis JSON's
   `readiness_state`/`publishable` equal the pre-synthesis candidate's own values exactly, for a
   fixture whose `fact_verification.status` ends up `"review"` — direct proof of contract §7a.
8. `test_synthesis_error_writes_no_artifacts` — `FakeLLMGateway` raises/returns malformed output →
   `EventRecapSynthesisError` propagates, neither output file exists afterward.
9. `test_max_chars_over_limit_flags_but_does_not_block` — a `FakeLLMGateway` response long enough to
   exceed 4000 rendered characters still gets both artifacts written; `quality_notes` contains the
   length flag; `evaluation_status` becomes `NEEDS_REVIEW`.
10. `test_causal_connective_detection_flags_unevidenced_claim_never_rewrites` — a `FakeLLMGateway`
    response containing an explicit causal connective whose stated cause is absent from the evidence
    bundle → `quality_notes` contains the flag, **and the synthesized text field itself is byte-for-
    byte identical to what the fake gateway returned** (proves no rewrite occurred). A companion
    test proves an evidenced causal connective does NOT get flagged.
11. `test_shadow_synthesize_zero_db_writes` — `session.new`/`session.dirty` unchanged across the
    full deterministic-build phase.
12. `test_shadow_synthesize_cli_help_works` — `--help` smoke test.
13. Ruff + mypy clean on both new files.

## 6. Explicitly out of scope for this stage (unchanged from the contract)

Batch/looped synthesis, automatic Story selection, any Telegram/RECAP-renderer work, any change to
`prompts/event_recap/v2.yaml`, `services/recap_event.py`, or `services/event_recap.py`.

## 7. Final list of files to be changed

```
NEW   scripts/_recap_r2_shadow_synthesize.py
NEW   tests/test_recap_r2_shadow_synthesize.py
```

No other file — existing or otherwise — is touched by this implementation.

## 8. Sequencing after this document

1. Owner reviews this plan and the fully-updated `docs/r2_shadow_synthesis_contract.md`.
2. On confirmation: implement exactly as scoped here — exactly the two files in §7.
3. Run the test suite, ruff, mypy, `git diff --check` — report before committing (same checkpoint
   discipline as R2 Shadow v1).

No implementation begins before step 1's explicit confirmation.
