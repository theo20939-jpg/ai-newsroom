# Phase 11 — Implementation Plan Adversarial Audit

Independently verifies `docs/phase11_telegram_editorial_inbox_implementation_plan.md` ("the Plan")
against current repository source and the frozen, approved Architecture Contract. The Plan is
treated as untrusted; every load-bearing claim below was re-derived from source or proven by direct
execution this session, not accepted from the Plan's own text. No file other than this audit
document was created or modified.

---

## 1. Executive Verdict

The Plan is **sound and implementable exactly as written**. Every high-risk area the audit was
asked to scrutinize — file scope, session ownership, query correctness, UTF-16 length semantics,
multi-card failure handling, forum-topic propagation, and (most consequentially) the feasibility of
this repository's *first-ever* bot-handler test — was independently re-verified, in several cases
by direct code execution rather than by reading, and held up. The eligibility query was compiled
against the real ORM models and produces exactly the expected SQL. The forum-topic guarantee was
proven empirically: a constructed `Message(is_topic_message=True, message_thread_id=777)` sent via
`.answer()` through a fake, network-free `aiogram` session produces an outgoing `SendMessage` with
`message_thread_id=777` — not merely read from source, but observed. The same fake-session
technique was proven sufficient to drive a full `handle_news()` test with zero network access and
zero production-code changes. **One MINOR finding**: the Plan describes handler/forum-topic testing
only as "a constructed `Message` and a fake/mock `Bot`," without naming the specific, standard
`aiogram` interception technique (subclassing `BaseSession`, overriding `make_request()`) — a real,
narrow precision gap for a first-of-its-kind test file, fully closed by this audit's own
demonstration, not a blocker. **CRITICAL = 0, MAJOR = 0, MINOR = 1.**

---

## 2. Repository Baseline

Independently re-verified this session (not inherited from the Plan's own §3):
```
HEAD: 7d3ae81a4666dfddf80c3b399e2a6596a749ac48 (unchanged since Contract approval)
Recent commits: 7d3ae81, c8131fc, 2ba004d, 89e111d, 07c6b51 — identical to every prior audit
aiogram: 3.29.1 (unchanged)
sqlalchemy: 2.0.51
```
`git status --short` shows the Plan document as the only new file added by the planning session;
every other untracked file predates it (Phase 9/9.5/10/11 process documents already present before
this task). **No schema/migration file exists anywhere in the working tree.** Phase 11 production
implementation has not started — none of the four production files or three test files the Plan
names exist yet (`schemas/editorial_inbox.py`, `services/editorial_inbox_service.py`,
`bot/formatting.py`, `tests/test_editorial_inbox_service.py`,
`tests/test_editorial_card_formatting.py`, `tests/test_news_handler.py` all confirmed absent by
direct filesystem check; `bot/handlers/news.py` confirmed still in its placeholder form).

---

## 3. File Scope Audit

Independently traced `bot bootstrap → router → /news handler → session access → query service →
renderer → Message.answer()`:

- **`bot/__init__.py`**: docstring only, no `__all__` — no change needed for a new flat
  `bot/formatting.py` module.
- **`bot/middlewares/__init__.py`, `bot/keyboards/__init__.py`**: both docstring-only, "reserved for
  future development phases" — confirmed still empty, no middleware exists to modify or extend.
- **`bot/handlers/__init__.py`**: already imports and registers `news_router` — re-confirmed
  unchanged; no router-registration edit needed.
- **`schemas/__init__.py`, `services/__init__.py`**: both docstring-only, no explicit re-export
  list — a new flat module in either package requires no package-`__init__` edit.
- **`pyproject.toml`**: `packages = ["app", "core", "database", "bot", "integrations", "services",
  "schemas", "scripts", "capabilities"]` — `bot`/`services`/`schemas` already listed; no packaging
  change needed for new flat modules within them.
- **Test discovery**: `pytest`'s default rootdir-based discovery requires no `conftest.py` or
  package-init change for three new files dropped into the existing `tests/` directory.

**Independently derived minimum scope**: identical to the Plan's claimed 4 production files (1 edit
+ 3 new) + 3 test files. **No additional production file is objectively necessary.** No `bot`
bootstrap edit, no middleware, no router change, no package-export change. File scope is exhaustive
and correctly derived, not merely copied from the Contract without re-checking.

---

## 4. Session Ownership Audit

Re-traced actual runtime code (`bot/main.py`, `bot/loader.py`, `database/session.py`):
`create_dispatcher()` returns a bare `Dispatcher()` — **confirmed, independently, still no
dependency injection of any kind in the bot layer.** The Plan's design (handler opens
`async_session_factory()` directly, in one `async with` block spanning the whole request, passes
the live session to the query service as a parameter, closes it on block exit) requires **zero**
change to `bot/loader.py`/`bot/main.py` and **invents no hidden session-middleware**. This is not a
new pattern: `scripts/run_content_generation.py:99` uses the identical `async with
session_factory() as session:` shape today. Session scope surviving multiple `SELECT`s within one
`async with` block is ordinary SQLAlchemy `AsyncSession` usage, not a novel concern. **The Plan does
not assume any DI that doesn't exist — it correctly identifies that none exists and designs
around that fact**, exactly as Contract §7/§9 requires.

---

## 5. Query / DTO Audit

**Query**: independently reconstructed the Plan's exact eligibility query from the real ORM models
and compiled it — not merely read, executed:
```
SELECT content_drafts.id, ... FROM content_drafts
JOIN editorial_tasks ON content_drafts.task_id = editorial_tasks.id
WHERE editorial_tasks.status = 'COMPLETED'
ORDER BY content_drafts.created_at DESC, content_drafts.id DESC
LIMIT 5
```
This is exactly Contract §6's frozen filter/order/limit. `TaskStatus.COMPLETED` resolves to the
correct enum value (`"COMPLETED"`, confirmed against `database/models/editorial_task.py`).
Ordering columns (`ContentDraft.created_at`, `ContentDraft.id`) both exist. No `relationship()` is
used — the `.join()` call is an explicit, hand-written join condition inside a `select()`
statement, a category the Contract's "no `relationship()`" prohibition does not reach (that
prohibition targets the ORM's lazy-loading declarative-attribute feature, not ordinary explicit
joins). **Observation, not a finding**: this is the first explicit SQLAlchemy `.join()` used
anywhere in this repository's production code (five existing services use `select().where()`, none
use `.join()`) — a new *pattern*, not a new *architecture decision*, since it's ordinary, standard
SQLAlchemy 2.0 syntax (confirmed against the installed `sqlalchemy==2.0.51`) applied to a
Contract-frozen filter. No commit, no mutation anywhere in the query plan.

**Duplicate semantics**: the Plan explicitly declines to add deduplication logic, citing that
`ContentDraft.task_id` carries no uniqueness constraint but `ContentDraftService` is only ever
constructed from `scripts/run_content_generation.py`, which always creates a fresh `EditorialTask`
per call — re-confirmed via the same grep this session (`ContentDraftService(` appears only in that
one production file). This matches Contract §6's own OBSERVATION-level treatment exactly; no silent
deduplication was introduced.

**DTO**: `EditorialInboxCard`'s 9 fields match Contract §8 verbatim — type-checked against the real
models field by field (`draft_id: UUID` ↔ `ContentDraft.id`; `news_published_at: datetime | None`
↔ `NewsEvent.published_at`, nullable; etc.). No `aiogram` type appears. No Telegram markup leaks
into the DTO layer (escaping happens only in the renderer, §7). The one non-obvious data
transformation — `hashtags=draft.hashtags  # type: ignore[arg-type]`, needed because
`ContentDraft.hashtags` is imprecisely typed `Mapped[dict | None]` while actually storing a list at
runtime — is explicitly named and cited to its exact precedent
(`services/content_draft_service.py:56-59`), not a hidden transformation Planning glossed over.

---

## 6. Renderer Audit

`bot/formatting.py`'s planned ownership is exhaustive: `_escape()` (HTML escaping), `_telegram_
utf16_length()` (the frozen UTF-16 measurement), `render_editorial_card()` (template assembly +
truncation loop), `CardTooLongError` (terminal-fallback signal). The Plan's algorithm sketch
preserves `telegram_utf16_length(rendered) <= SAFE_LIMIT` as the sole gating check at every
decision point and explicitly states `len()` is prohibited as the authoritative check — matching
Contract §14/§15 exactly, with no regression to the pre-N-1 defect. Truncation-marker application,
raw-body-only shrinkage, re-escape-and-re-render-from-scratch on every iteration, and the terminal
`CardTooLongError` path are all specified concretely enough that an implementer does not need to
invent any of them — only two **numeric tuning constants** (`_SHRINK_STEP`, the initial budget) are
left open, and the Contract itself explicitly permits this ("a fixed step or a binary search... are
both acceptable, deterministic choices left to Planning") — not a substantive architecture gap.

**`quote=False` choice, independently assessed**: the Plan's `_escape()` uses
`html.escape(value, quote=False)`, reasoned as correct because no card field is ever interpolated
into an HTML attribute (Contract §13 confirms no `href` exists anywhere in the frozen card).
Verified this reasoning is technically sound: Telegram's HTML parse mode requires escaping only
`<`, `>`, `&` — matching `quote=False`'s exact output — and quote-escaping (`&quot;`/`&#x27;`)
would be unnecessary transformation of visible text with no attribute context to protect. A sound,
correctly-justified implementation choice, not a gap.

---

## 7. Handler / Runtime Audit

The Plan's `handle_news()` sketch was traced statement by statement against Contract §16: query
exception → `except Exception` at the handler's own top-level boundary → generic text (Case B);
empty `cards` list → empty-state text (Case A); per-card `CardTooLongError` → log + `continue`
(Case E via N-2); per-card `TelegramAPIError` → log + `continue` (Case D, combined with Case E's
per-card isolation). `TelegramAPIError` was confirmed to be a real, importable symbol
(`aiogram.exceptions.TelegramAPIError`) in the installed package, with `TelegramBadRequest`
(the exception a still-malformed/oversized payload would actually raise) confirmed as its subclass
— so the `except TelegramAPIError` clause genuinely catches the failure mode it's meant to catch,
not a guessed exception name. Forum-topic preservation requires no handler code at all — inherited
automatically via `message.answer()` (§16 below proves this empirically, not just by citation). No
callback, no auth, no write path, no AI/workflow import appears anywhere in the handler sketch or
its stated "forbidden responsibilities" list.

---

## 8. Test Architecture Audit

**File scope**: independently searched the entire `tests/` directory for any reference to `bot.*`
of any kind (`grep -rln "import bot\|from bot" tests/`) — **zero matches**. This is a stronger
result than the Plan's own §3 claim ("no existing bot handler tests exist") — not only do no
handler tests exist, **no test anywhere in this repository imports anything from the `bot` package
at all**, including the placeholder text string (also independently grepped, zero matches in
`tests/`). This conclusively confirms Audit 12's question: **no existing test requires mechanical
modification** because `/news`'s behavior is changing. The Plan's 3 new test files are sufficient;
no hidden fourth test file (snapshot/router-registration/import test) is needed.

**Handler-test feasibility (the highest-risk area)**: the Plan states handler tests use "a
constructed `Message` and a fake/mock `Bot`" without naming the exact interception mechanism. This
audit independently built and ran a minimal proof, subclassing `aiogram.client.session.base.
BaseSession` and overriding `make_request()` to return canned `Message` objects with zero network
access:
```
sent count: 1
result text: hello world
```
This confirms handler tests (M3) **can** be written without live Telegram, network, new production
test hooks, or any `bot/loader.py`/`bot/main.py` modification — using `aiogram`'s own standard,
public `BaseSession` extension point, not an invented seam. See Finding MINOR-1 for the precision
gap in how the Plan documents this.

**Service/renderer test obligations**: independently cross-checked the Plan's §16 test matrix
against every Contract-frozen behavior enumerated in the final Contract re-audit's own 11-point
UTF-16 checklist and the original Contract's escaping/failure-semantics obligations — no gap found;
every item maps to a named planned test.

---

## 9. Milestone Order Audit

Independently verified the dependency claims: M1's `services/editorial_inbox_service.py` has no
import of anything M2 or M3 introduces (confirmed by the Plan's own per-file dependency column,
cross-checked against §7's "no `aiogram` import" requirement — a query service that needed the
renderer would violate this, and it doesn't). M2's `bot/formatting.py` imports only
`schemas/editorial_inbox.py` — no handler dependency. M3 imports both M1 and M2's public symbols
only. M4 requires all three. M5 is explicitly gated on M4's automated checkpoint (Plan §11: "no
manual Telegram validation occurs until M4's full automated gate is green"). **Dependency order is
safe and correctly justified**, including the Plan's own explicit note that M1/M2 have no
compile-time dependency on each other and could theoretically be built in parallel — accurate.

---

## 10. Verification Gate Audit

Each of M1/M2/M3 is specified with a focused `pytest` run, `ruff check .`, targeted `mypy` on that
milestone's own files, `scripts.validate_architecture`, and a git-scope diff review (Plan §17) —
matching the audit's required per-milestone gate list exactly. The final pre-M5 checkpoint requires
the full suite, full `ruff`, full targeted `mypy`, the architecture validator, secret hygiene, and a
full git-scope review — matching the audit's required final-gate list exactly, and explicitly
gating M5 behind it. `scripts/validate_architecture.py` was independently re-read this session:
it is a hand-curated rule table that requires no edit for Phase 11 (no provider-adapter file is
touched) — confirmed, not assumed.

---

## 11. Risk Audit

Cross-checked the Plan's 12-row risk register (§18) against this audit's own "high-value candidate"
list: missing session injection (covered — "Session injection mismatch" row), first handler-test
architecture (**not explicitly covered** — see Finding MINOR-1), oversized metadata even with empty
body (covered — "Oversized static metadata" row), partial Telegram delivery (covered — "Telegram
send partial failure" row), duplicate drafts (covered — "Query duplicate-draft semantics" row),
topic routing (covered — "Forum-topic behavior" row), bot startup mismatch (covered — "Bot
runtime/bootstrap assumptions" row). Eleven of twelve candidate risks are already present; the one
gap (first-handler-test-architecture risk) is the same root cause as MINOR-1. No invented,
unrealistic risk was found needing removal from the register.

---

## 12. Definition of Done Audit

The Plan's §19 reproduces Contract §26's 26-item DoD **verbatim**, with no item softened, removed,
or reworded. Cross-referencing each item against the Plan's milestone/test structure: items 1–14
map to M1–M3's test obligations (§16's matrix); items 15–19 map to the Plan's explicit
"forbidden responsibilities" per file (§12) plus §21's out-of-scope list; items 20–24 map to §17's
verification gates; item 25 maps to M5; item 26 maps to M4's before/after row-check plus M5's DB
verification step. **No DoD item is left unmapped.**

---

## 13. Phase 5–10 Isolation

Independently re-scanned the Plan's entire file scope (§4/§4-table): `bot/handlers/news.py`,
`schemas/editorial_inbox.py`, `services/editorial_inbox_service.py`, `bot/formatting.py`, and three
test files. **None** of these appear in Contract §18's frozen list (`workflows/runner.py`,
`capabilities/executor.py`, `capabilities/registry.py`, `integrations/llm_gateway/**`,
`integrations/prompts/**`, any `capabilities/*_capability.py`, `services/content_draft_service.py`,
`scripts/run_content_generation.py`, `workflows/definitions/content_generation.py`, any
`database/models/*.py`, any migration). **Zero Phase 5–10 file requires modification anywhere in
this Plan.**

---

## 14. Findings

### MINOR-1
**SEVERITY**: MINOR
**PLAN LOCATION**: §9 (`tests/test_news_handler.py` description) and §11 ("A message constructed
with `is_topic_message=True`..."); also absent from §18's Risk Register.
**SOURCE / CONTRACT EVIDENCE**: this repository has zero existing bot-handler tests and zero
existing tests importing anything from the `bot` package (independently confirmed, §8 above) — so
there is no established in-repo idiom for constructing a network-free `aiogram` `Message`/`Bot`
pair. `aiogram` itself ships no official test/mock module (confirmed: `aiogram.__meta__`,
`client`, `dispatcher`, `enums`, `exceptions`, `filters`, `fsm`, `handlers`, `loggers`, `methods`,
`types`, `utils`, `webhook` — no `test`/`mock` submodule).
**PROBLEM**: the Plan says handler/forum-topic tests use "a constructed `Message` and a fake/mock
`Bot`" without naming the specific interception mechanism. For a first-of-its-kind test file, this
leaves the exact technique (which of several plausible approaches: patching `Bot.__call__`,
patching `Message.answer` directly, or subclassing `aiogram.client.session.base.BaseSession` and
overriding `make_request()`) unspecified.
**IMPACT**: low — this audit independently built and ran the standard `BaseSession`-subclass
technique this session and confirmed it works cleanly for both a plain send and a forum-topic send
(`message_thread_id` propagated correctly with zero network access, zero production change). The
gap is a documentation/precision matter, not a genuine fork in the design space requiring a
judgment call — there is exactly one idiomatic, low-risk way to do this in `aiogram` 3.x, and this
audit has now demonstrated it concretely.
**REQUIRED CORRECTION** (non-blocking): name the `BaseSession`-subclass-with-overridden-
`make_request()` technique explicitly in Plan §9/§16 as the intended handler-test construction
method, and add one Risk Register row for "first-handler-test-architecture risk" (mitigated by this
now-proven technique). Neither correction changes any milestone's scope, file list, or dependency
order.

---

## 15. Observations

- The eligibility query (§5 above) is this repository's first production use of an explicit
  SQLAlchemy `.join()` — a new *pattern*, not a new *architecture decision*; five existing services
  already use `select().where()`, and `.join()` is ordinary, standard SQLAlchemy 2.0 syntax for the
  installed version. Worth noting for a future reader, not a defect.
- The renderer's `html.escape(value, quote=False)` choice is well-reasoned and independently
  confirmed correct against Telegram's actual HTML-escaping requirement (only `&`/`<`/`>`) — a
  strength of the Plan, not a gap.
- The Plan's claim "no existing bot handler tests exist" (§3) is accurate but understates the
  actual finding: **zero tests anywhere import the `bot` package at all**, a stronger and even more
  favorable fact this audit surfaced independently.
- The two truncation-loop numeric constants left to implementation discretion (`_SHRINK_STEP`,
  initial budget) are explicitly Contract-permitted (§14: "a fixed step or a binary search... are
  both acceptable, deterministic choices left to Planning") — correctly not over-specified by the
  Plan.

---

## 16. Readiness Score

**9/10.** Every high-risk area named in the audit's own instructions — file scope, session
ownership, query determinism, UTF-16 length safety, multi-card failure semantics, and forum-topic
propagation — was independently re-verified against real source and, in the two highest-uncertainty
cases (query correctness, forum-topic propagation, and network-free handler testability), proven by
direct code execution rather than accepted from the Plan's prose. No CRITICAL or MAJOR defect
exists anywhere. The single MINOR finding is a documentation-precision gap in an already-correct,
already-proven-workable test technique, not a genuine unresolved design question — it costs nothing
to close and blocks nothing while open.

---

## 17. Final Verdict

PHASE 11 IMPLEMENTATION PLAN APPROVED — READINESS SCORE: 9/10
