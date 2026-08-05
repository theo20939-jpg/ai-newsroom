# Phase 18 Final Acceptance — Feature Flags & Inertness Audit

Built directly from `core/config.py` (`grep -n "meme_" core/config.py`), not from any prior
report's claim. **Correction to the completion report**: the phrase "eight new mode flags" was
inaccurate - there are **5 Phase 18 settings total** (4 mode flags + 1 numeric byte limit), plus
3 module-level Python constants that are configuration values but not `Settings` fields. Corrected
in `docs/phase18_final_completion_report.md`.

## 1. Complete settings inventory

| Setting | Type | Allowed values | Default | Network effect | Cost effect | Telegram effect |
|---|---|---|---|---|---|---|
| `meme_opportunity_mode` | mode flag | `"off"`, `"shadow"` | `"off"` | none (zero-LLM classifier) | none | none |
| `meme_safety_gate_mode` | mode flag | `"off"`, `"shadow"` | `"off"` | none (zero-LLM classifier) | none | none |
| `meme_image_generation_mode` | mode flag | `"off"`, `"dry_run"` (no `"live"` value exists) | `"off"` | none — `dry_run` only ever reaches `MockImageAdapter`, a local, zero-network placeholder generator | `dry_run`: $0 (mock) | none |
| `meme_telegram_preview_mode` | mode flag | `"off"`, `"dry_run"` (no `"live"` value exists) | `"off"` | none — `dry_run` renders and logs, never calls `bot.send_*` | none | none — `send_meme_preview(dry_run=False)` is reachable only by a caller explicitly passing `dry_run=False`, and no production caller exists |
| `meme_image_max_bytes` | numeric limit | positive int | `10_000_000` | n/a | n/a | n/a |

## 2. Configuration constants (not `Settings` fields — code-level, require a code change to alter)

| Constant | Location | Value | Purpose |
|---|---|---|---|
| `MAX_CONCEPT_REGENERATIONS` | `services/meme_quality.py` | `1` | Bounds M7's REGENERATE_CONCEPT recommendation before forcing REJECT |
| `MAX_IMAGE_REGENERATIONS` | `services/meme_quality.py` | `1` | Bounds M7's REGENERATE_IMAGE recommendation before forcing REJECT |
| `_MAX_GENERATION_ATTEMPTS` | `services/meme_image_generation.py` | `2` | Bounds retries within one `generate_meme_image()` call |

## 3. Programmatic verification (evidence, not assertion)

All checks below were run against the actual repository state in this session; commands and
results are reproduced verbatim (no secrets touched — none of these settings are secret-typed).

**All Phase 18 modes default to `"off"`** — confirmed by direct field inspection above; also
independently confirmed by every live pytest run's own `Settings(...)` repr captured incidentally
in `test_content_generation_integration.py`'s failure output during full-suite regression:
`meme_opportunity_mode='off'` ... `meme_safety_gate_mode='off'`, `meme_image_generation_mode='off'`,
`meme_image_max_bytes=10000000`, `meme_telegram_preview_mode='off'` — this is the real,
loaded-from-`.env` settings object in this actual development environment, not a default-only
inspection of the Pydantic field declarations alone.

**No paid mode contains `"live"` unless explicitly intended** — neither `meme_image_generation_
mode` nor `meme_telegram_preview_mode` has a `"live"` `Literal` member at all. This is deliberate
(both settings' own docstrings state it) and structurally stronger than a runtime check: no code
path can select live behavior via these flags until a future, separately authorized commit adds
the value to the type itself.

**Default application startup cannot call a provider or send to Telegram** —
`grep -rln "meme" app/main.py bot/main.py worker/*.py` returns **zero matches**: no application
entry point imports or references any Phase 18 module at startup. (`bot/handlers/__init__.py`
does import `bot.handlers.meme_preview`'s router so the bot process can *recognize* a
`memeprev:`-prefixed callback if one ever arrives — this is a dormant listener registration, not
active behavior; nothing sends that callback data, and the router itself makes no outbound call
on its own.)

**No automatic `MEME_GENERATION` task is spawned** — `grep -rn "WorkflowType.MEME_GENERATION"`
across the entire repository (excluding tests) returns exactly 3 hits: the `_try_reuse()` guard
in `capabilities/executor.py`, a comment in `capabilities/registry.py`, and the workflow
definition's own `name=` field in `workflows/definitions/meme_generation.py`. **Zero hits in
`worker/` or `scripts/`** — no cycle, no script, creates an `EditorialTask` with this workflow
type. `grep -rn "create_task\|EditorialTask("` filtered to meme-related lines returns nothing —
task creation only ever happens for `NEWS_ANALYSIS`/`CONTENT_GENERATION` in this codebase today.

**Production workflows never reference meme capabilities** — `workflows/definitions/
content_generation.py` and `news_analysis.py` list only their original, pre-Phase-18 capability
names (`research`, `intelligence`, `copywriting`, `quality`, `engagement`, `scoring`). Neither
`meme_concept` nor `meme_copywriting` appears in either definition — registering both new
capabilities in the shared `CapabilityRegistry` (needed so they are resolvable and cost-tracked
at all) has zero effect on either production workflow's actual execution.

**No callback can silently trigger paid work** — `bot/handlers/meme_preview.py`'s
`_REGENERATE_ACTIONS` branch (`regen_concept`/`regen_image`/`regen_text`) only logs
`meme_preview_action_acknowledged_not_orchestrated` and calls `callback.answer(...)` - it never
calls `generate_meme_image()`, any Capability, or any Gateway. Verified by direct code reading
(§ this file's own module docstring) and exercised in `tests/test_phase18_m8_meme_telegram_
preview.py`'s keyboard/parsing tests (the handler itself is not DB/Bot-testable without live
infrastructure, but the code path performing zero calls is unambiguous from its own source).

**`APPROVE` records a decision only** — `grep -n "APPROVE"` shows `MemeCandidateStatus.APPROVED`
used exactly where `record_editor_decision()` sets `candidate.status`/`editor_decision` - no
adjacent call to any publish/send function exists in that method (`services/
meme_candidate_service.py`, read in full for this audit).

**No `STANDARD_NEWS_POST` auto-publish path exists** — `grep -rn "STANDARD_NEWS_POST"` returns
zero matches anywhere touching Phase 18 code; this term does not appear in this codebase at all
(it is not a symbol this project uses under any name).

**No direct SQL/bulk `update()`/`setattr()` bypasses model restrictions** — `grep -rn "update(\|
setattr("` filtered to meme-related files returns **zero matches**. Every `MemeCandidateService`
method mutates exactly one already-loaded ORM instance's named attributes directly
(`candidate.field = value`), then `session.commit()` - the same pattern `ContentDraftService`/
`services/image_persistence.py` already use throughout this codebase. No `sqlalchemy.update()`
construct, no `**kwargs` spread into a bulk update, appears anywhere in Phase 18 code.

**`MemeCandidate.published` has no setter anywhere** — `grep -rn "published"` across the entire
repository shows exactly one *write* site: the SQLAlchemy column declaration itself
(`published: Mapped[bool] = mapped_column(nullable=False, default=False)` in `database/models/
meme_candidate.py`) and the migration's matching `server_default=sa.false()`. Every other hit is
either a read (`services/meme_candidate_service.py::build_feedback_summary()`'s
`published=candidate.published`) or prose in a docstring/report. **No code path in this entire
phase ever assigns `True`** to this field - confirmed by exhaustive grep, not merely by author
intent.

**No background worker discovers and executes meme tasks automatically** —
`automation_worker`/`news_analysis_worker`/`content_worker`/`telegram_bot` containers were kept
stopped throughout this entire acceptance session (confirmed via `docker ps -a`, §Infrastructure
in the main acceptance report) - none of their own source files (`worker/analysis_main.py`,
`worker/content_main.py`, `worker/main.py`, `bot/main.py`) reference any Phase 18 symbol
(confirmed by the same `grep -rln "meme"` check above).

## 4. Summary

Every Phase 18 mode defaults to `"off"`. Two of the four mode flags (image generation, Telegram
preview) cannot even express a live/paid value in their current type. No code path - callback,
worker, script, or application startup - can reach a paid provider call, a live Telegram send, or
an automatic publish, without a future code change that does not exist in this branch. This
matches the completion report's own claim; the only correction needed was the flag *count*
("eight" → "five settings, 4 of them mode flags"), not the safety conclusion itself.
