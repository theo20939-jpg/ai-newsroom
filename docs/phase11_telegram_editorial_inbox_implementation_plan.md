# Phase 11 — Telegram Editorial Inbox Implementation Plan

Translates the **approved, frozen** Architecture Contract
(`docs/phase11_telegram_editorial_inbox_architecture_contract.md`, readiness 9/10, CRITICAL=0/
MAJOR=0/MINOR=0) into deterministic, milestone-based implementation steps. This document is
**planning only** — no production code, test, prompt, model, or migration was written or modified
to produce it, and the Contract itself was not modified.

---

## 1. Executive Summary

Phase 11 adds one new, read-only capability: `/news` returns the 5 most recent editorial drafts
whose workflow is `COMPLETED`, rendered as safely-escaped, length-bounded Telegram HTML cards. The
implementation touches exactly **one existing file** (`bot/handlers/news.py`) and creates exactly
**three new production files** plus **three new test files** — no more, no less, matching the
Contract's §23 exhaustive file scope precisely (independently re-derived and cross-checked in §4
below, not merely copied). Six milestones (M0–M5) implement this deterministically; every
architectural decision — session ownership, query shape, DTO fields, escaping rule, UTF-16 length
algorithm, terminal-failure mapping, forum-topic behavior — is already frozen in the Contract, so no
milestone requires inventing new architecture. No migration, no AI/LLM call, no WorkflowRunner/
Capability change, and no in-app authorization are introduced anywhere in this Plan.

---

## 2. Frozen Architecture Inputs

This Plan treats the following as **binding and non-negotiable**, reproduced from the Contract, not
reinterpreted:

- **Eligibility**: `ContentDraft` linked (via `task_id`) to an `EditorialTask` with
  `status == TaskStatus.COMPLETED`. (Contract §6)
- **Ordering**: `ContentDraft.created_at DESC`, `ContentDraft.id DESC` tie-break. **Limit 5. No
  pagination.** (Contract §6, §15)
- **Data path**: `ContentDraft.task_id → EditorialTask.id`, `EditorialTask.event_id →
  NewsEvent.id`, both via `session.get()`, mirroring `capabilities/executor.py`'s exact two-hop
  convention — no `relationship()` is added anywhere. (Contract §5)
- **DTO**: a new `EditorialInboxCard` Pydantic model (`schemas/editorial_inbox.py`), 9 frozen
  fields, `frozen=True, extra="forbid"`. (Contract §8)
- **Card template**: frozen field order and content, `news_url` rendered as plain escaped text
  (never `<a href>`). (Contract §12)
- **Escaping**: every one of `draft_title`, `draft_body`, `hashtags`, `news_title`,
  `news_category`, `news_url` MUST be HTML-escaped. (Contract §13)
- **Length**: `telegram_utf16_length(rendered) <= 4096` is the sole authoritative safety check —
  Python `len()` MUST NOT be the safety check. Render → verify → shrink `draft_body` only →
  re-render → re-verify, terminating either by fitting or via a dedicated rendering-failure signal
  when `draft_body` is fully exhausted and the card still doesn't fit. (Contract §14)
- **Failure semantics**: §16 Cases A (empty) / B (DB error) / C (missing optional metadata) / D
  (Telegram send failure) / E (one card's formatting fails, including the §14 terminal fallback) —
  all frozen, no invention required. (Contract §16)
- **Destination**: `message.answer()` on the invoking `Message`; forum-topic `message_thread_id` is
  preserved automatically by the pinned `aiogram==3.29.1` — no new code required for this. (Contract
  §10)
- **Session**: the handler opens `async_session_factory()` directly (no DI exists in the bot layer),
  mirroring `scripts/run_content_generation.py`'s exact pattern; the query service never opens its
  own session; **zero commits anywhere in this phase's new code.** (Contract §7, §9, §17)
- **Authorization**: none. `User`/`UserRole` remain completely unwired. (Contract §11)
- **Out of scope**: Approve/Reject/Rework, callbacks, push/scheduler, publication, memes/images,
  migration, any Phase 5–10 file modification. (Contract §3, §18–§21)

---

## 3. Repository Baseline

Re-verified directly against current source this session (not inherited from Discovery/Contract
without checking):

| Item | Verified state | Source |
|---|---|---|
| Git HEAD | `7d3ae81` (unchanged since Contract approval) | `git rev-parse HEAD` |
| Working tree | Only pre-existing untracked docs; no Phase 11 production code, no migration | `git status --short` |
| `bot/handlers/news.py` | Placeholder only — `Router(name="news")`, one handler, `await message.answer(PLACEHOLDER_TEXT)`, zero DB access | Full file re-read |
| `bot/handlers/__init__.py` | `news_router` already imported and `include_router`-ed into the root router | Full file re-read |
| `bot/loader.py` | `create_dispatcher()` returns bare `Dispatcher()` — no DI; `create_bot()` sets `DefaultBotProperties(parse_mode=ParseMode.HTML)` | Full file re-read |
| `bot/main.py` | Long-polling only via `dp.start_polling(bot)`, no webhook | Full file re-read |
| `database/session.py` | `async_session_factory = async_sessionmaker(engine, expire_on_compare=False)` (module-level singleton) | Full file re-read |
| `scripts/run_content_generation.py` | Confirms the exact `async with session_factory() as session:` precedent this Plan's handler mirrors | Full file re-read |
| `database/models/content_draft.py` | Schema matches Contract §4 exactly. **Note**: `hashtags: Mapped[dict \| None]` is imprecise ORM typing — the JSON column actually stores a list at runtime; `services/content_draft_service.py:59` already handles this with `# type: ignore[arg-type]` and an explanatory comment — the new query service will mirror this exact convention (§12 below) | Full file re-read + cross-read of `services/content_draft_service.py` |
| `database/models/editorial_task.py`, `database/models/news_event.py` | Schema matches Contract §4 exactly; `EditorialTask.status`/`.created_at` indexed, `NewsEvent.category`/`.published_at` indexed | Full file re-read |
| `aiogram` version | `3.29.1` — unchanged since the final re-audit's verification | `python -c "import aiogram; print(aiogram.__version__)"` |
| `aiogram.exceptions.TelegramAPIError` / `TelegramBadRequest` | Both exist in the installed package; `TelegramBadRequest` subclasses `TelegramAPIError` — this is the correct exception type for the handler's Telegram-send-failure boundary (§16 Case D) | `python -c "from aiogram.exceptions import TelegramAPIError, TelegramBadRequest; ..."` |
| Existing bot handler tests | **None exist yet** — `tests/` has no `test_*_handler.py` file of any kind. Phase 11's handler test (M3) will be this repository's first. Contract §23's "mirroring Phase 10's test discipline" therefore applies at the philosophy level (test the function directly, with a constructed `Message` and fake `Bot`) — there is no literal prior handler-test file to copy structure from | `ls tests/` |
| `tests/conftest.py` fixtures | `db_session` (real Postgres, SAVEPOINT-rolled-back), `real_news_event` (real `NewsSource`+`NewsEvent`). **No** `real_editorial_task`/`real_content_draft` fixture exists — M1's test file must construct `EditorialTask`/`ContentDraft` rows directly via the ORM, exactly as `tests/test_content_draft_service.py` already does for its own setup | Full file re-read |
| `tests/test_capability_testing_convention.py` | Confirms the exact AST-based import-check pattern (`ast.walk`, `ast.Import`/`ast.ImportFrom`) this Plan's mechanical no-AI-import test (M1/M2) will reuse | Full file re-read |
| Authorized-file existence check | `schemas/editorial_inbox.py`, `services/editorial_inbox_service.py`, `bot/formatting.py`, and all three planned test files — **none exist** | Direct filesystem check |

**No drift found.** Current source matches every claim the approved Contract makes. This Plan
proceeds without alteration to architecture.

---

## 4. Exact File Scope

Independently re-derived from the actual repository integration path (not copied from the
Contract's own list without verification), then cross-checked against Contract §23:

| File | Status | Purpose | Milestone | Dependencies | Risk | Test coverage |
|---|---|---|---|---|---|---|
| `bot/handlers/news.py` | Existing — narrow edit | Replace placeholder body with the real query→render→send flow | M3 | `services/editorial_inbox_service.py`, `bot/formatting.py`, `database/session.py` | Low — thin orchestration only, no new logic of its own | `tests/test_news_handler.py` |
| `schemas/editorial_inbox.py` | New | `EditorialInboxCard` DTO | M1 | none (pure Pydantic) | Low | `tests/test_editorial_inbox_service.py` (via construction) |
| `services/editorial_inbox_service.py` | New | Read-only eligibility query + DTO assembly | M1 | `schemas/editorial_inbox.py`, `database/models/{content_draft,editorial_task,news_event}.py`, SQLAlchemy | Medium — the only file with real query-correctness risk | `tests/test_editorial_inbox_service.py` |
| `bot/formatting.py` | New | HTML escaping, card rendering, UTF-16 length algorithm, rendering-failure exception | M2 | `schemas/editorial_inbox.py`, stdlib `html` | Medium — the length/escaping safety invariant lives here | `tests/test_editorial_card_formatting.py` |
| `tests/test_editorial_inbox_service.py` | New | Query/service tests (real DB) | M1 | `tests/conftest.py` fixtures | — | — |
| `tests/test_editorial_card_formatting.py` | New | Renderer/escaping/length tests (pure) | M2 | none | — | — |
| `tests/test_news_handler.py` | New | Handler tests (constructed `Message`, fake `Bot`) | M3 | `services/editorial_inbox_service.py`, `bot/formatting.py` | — | — |

**Total: 1 existing edit + 3 new production files + 3 new test files = 7 files.** This matches
Contract §23 exactly, file for file — **no additional production file is objectively required**;
this Plan does not expand scope. (No `PLAN BLOCKED` condition triggered.)

---

## 5. Dependency Graph

```
M0 (repository preparation / baseline verification — no code)
  ↓
M1 (schemas/editorial_inbox.py + services/editorial_inbox_service.py + its test)
  ↓
M2 (bot/formatting.py + its test)                    [independently reviewable from M1;
  ↓                                                    both M1 and M2 could technically be
M3 (bot/handlers/news.py + its test)                   built in parallel, but M3 depends on
  ↓                                                    both, so M1 → M2 → M3 is the safest
M4 (integrated read-only verification, real DB,        sequential review order — see note below]
    no external services)
  ↓
M5 (manual live Telegram smoke — human-authorized only)
```

**Note on M1/M2 ordering**: `services/editorial_inbox_service.py` (M1) and `bot/formatting.py`
(M2) have no compile-time dependency on each other — both only depend on
`schemas/editorial_inbox.py`. They could be implemented in either order or in parallel. This Plan
sequences them M1 → M2 anyway, for the safest reviewable order: the DTO's exact shape (M1) is
easiest to validate against real, joined DB data first, and M2's renderer tests then have a
concrete, already-tested DTO to construct fixtures against, rather than a DTO whose shape is still
only a plan-time sketch.

---

## 6. M0 — Repository Preparation

**No production implementation in this milestone.**

Readiness checklist (all independently re-verified in §3 above, restated here as the milestone's
completion gate):

- [x] All 7 authorized files (§4) confirmed either existing-and-editable or not-yet-created —
  none blocked, none already present with conflicting content.
- [x] Session path confirmed: `database.session.async_session_factory`, opened directly by the
  handler, mirroring `scripts/run_content_generation.py`.
- [x] Router path confirmed: `/news` already registered in `bot/handlers/__init__.py`; no router
  change needed.
- [x] Query data path confirmed: `ContentDraft` → `EditorialTask` (FK `task_id`) → `NewsEvent` (FK
  `event_id`), all columns present, no schema change needed.
- [x] No migration required — every field the card needs already exists (Contract §22,
  independently re-confirmed in the original audit's Data Path Audit).
- [x] No Phase 5–10 file requires modification — confirmed by tracing the full read path (§5 of the
  Contract) and finding it never touches `WorkflowRunner`/`CapabilityExecutor`/`CapabilityRegistry`/
  `LLMGateway`/`ContentDraftService`/any model file.
- [x] Pinned `aiogram==3.29.1` behavior matches Contract: `Message.answer()` auto-preserves
  `message_thread_id` for topic messages (re-verified via `inspect.getsource` during the final
  re-audit; unchanged this session).
- [x] Test infrastructure supports real-DB service tests: `tests/conftest.py`'s `db_session`
  fixture (SAVEPOINT-rolled-back real Postgres) is sufficient; `real_news_event` exists as a
  precedent for the new fixtures M1's test file will construct inline for `EditorialTask`/
  `ContentDraft`.
- [x] Manual Telegram smoke (M5) is feasible: `core.config.settings.telegram_bot_token` is the only
  required config; `bot/main.py` is a real, working entry point; Phase 10's own M6 live-validation
  data (real, previously-completed `CONTENT_GENERATION` runs) can supply real `ContentDraft` rows
  without any new AI spend.

**Completion criterion**: all boxes above are independently checked, not assumed —

**M0 PASSED — READY FOR M1**

---

## 7. M1 — Editorial Inbox Query + DTO

### `schemas/editorial_inbox.py`

Exact frozen shape (Contract §8, reproduced verbatim — no field invented, none omitted):
```python
class EditorialInboxCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    draft_id: UUID
    draft_title: str | None
    draft_body: str | None
    hashtags: list[str] | None
    draft_created_at: datetime
    news_title: str
    news_category: str
    news_url: str | None
    news_published_at: datetime | None
```

### `services/editorial_inbox_service.py`

**One exported async function** (plain-function module, mirroring `services/workflow_service.py`'s
shape per Contract §7 — not a class):
```python
async def get_latest_editorial_cards(
    session: AsyncSession, *, limit: int = 5,
) -> list[EditorialInboxCard]:
```

**Query plan** (see §14 below for full detail) — two stages, both read-only, zero commit:
1. One `select(ContentDraft)` joined to `EditorialTask` filtered on
   `EditorialTask.status == TaskStatus.COMPLETED`, ordered
   `ContentDraft.created_at DESC, ContentDraft.id DESC`, limited to `limit`.
2. For each of the (at most `limit`) resulting `ContentDraft` rows: `session.get(EditorialTask,
   draft.task_id)` then `session.get(NewsEvent, task.event_id)` — the exact two-hop convention
   Contract §5 freezes, mirroring `capabilities/executor.py:69-74` line for line in shape (not
   copied code, same pattern).
3. Assemble one `EditorialInboxCard` per row; `hashtags=draft.hashtags` with the same
   `# type: ignore[arg-type]` + explanatory comment `services/content_draft_service.py:56-59`
   already uses for the identical ORM-typing looseness.

**Duplicate-`ContentDraft`-per-task handling**: per Contract §6/the original audit's Query
Semantics Audit (OBSERVATION, not a finding), `ContentDraft.task_id` carries no uniqueness
constraint, but `ContentDraftService` is constructed only from
`scripts/run_content_generation.py`, which always creates a fresh `EditorialTask` per invocation —
this scenario is schema-permitted but not reachable through any current code path. **This Plan
invents no deduplication logic** — the frozen `created_at DESC, id DESC` ordering already handles
the case correctly if it ever occurred (both rows would simply appear, correctly ordered, as
distinct cards), consistent with the Contract not requiring uniqueness enforcement.

**Forbidden responsibilities** (Contract §7): no `aiogram` import; no AI/workflow call; no mutation;
no commit; no raw ORM object crossing into `bot/`.

### `tests/test_editorial_inbox_service.py`

Real-DB tests (`db_session` fixture), constructing `NewsSource`/`NewsEvent`/`EditorialTask`/
`ContentDraft` rows directly via the ORM (no `WorkflowRunner`/AI call needed — Phase 11's own tests
do not need to run a real workflow to produce a `COMPLETED` task; they set `status=TaskStatus
.COMPLETED` directly on a constructed row, exactly as `tests/test_content_draft_service.py`
constructs its fixtures at the ORM level before invoking the code under test):
- Returns only `ContentDraft` rows linked to `COMPLETED` `EditorialTask`.
- Excludes `FAILED`/`CREATED`/`RUNNING`/`WAITING`.
- Newest-first ordering; `id`-based tie-break (construct two rows with an identical `created_at` by
  passing an explicit `created_at` value on both, since the column's `server_default=func.now()`
  cannot itself produce two identical timestamps deterministically).
- Limit of 5 enforced against 6+ eligible rows.
- Empty result → `[]`, not an error.
- Joined `NewsEvent` metadata correctly attached.
- `NewsEvent.url is None` → `news_url is None` on the DTO, no error.
- Mechanical import-boundary test (AST-based, mirroring `test_capability_testing_convention.py`):
  `services/editorial_inbox_service.py` imports none of `workflows.runner`,
  `capabilities.executor`, any `capabilities.*_capability`, `scripts.run_content_generation`.

**Milestone owner**: M1. **Rollback scope**: deleting the two new files and their test file fully
reverts M1 with zero effect on any other module (nothing else imports them yet).

---

## 8. M2 — Telegram Renderer

### `bot/formatting.py`

**Exported symbols**:
```python
class CardTooLongError(Exception):
    """Raised when a card cannot be rendered within Telegram's UTF-16 length limit even after
    draft_body is fully exhausted (Contract §14 terminal fallback -> §16 Case E)."""

def render_editorial_card(card: EditorialInboxCard) -> str:
    """Returns the fully-escaped, ready-to-send HTML string. Raises CardTooLongError on the
    terminal-fallback condition. No aiogram/Bot/Message type in this module's signature."""
```

**Internal helpers** (not part of the module's public contract, named here only to remove
ambiguity, per the instruction allowing small sketches):
- `_escape(value: str) -> str` — thin wrapper over `html.escape(value, quote=False)` (`quote=False`
  because the card is never used inside an HTML attribute — Contract §13 confirms no href
  attribute exists anywhere in the frozen card, so quote-escaping `"`/`'` is unnecessary; using
  `quote=False` avoids over-escaping visible text with `&quot;`/`&#x27;` where Telegram's HTML
  subset does not require it).
- `_telegram_utf16_length(text: str) -> int` — the frozen semantic invariant (Contract §14):
  `len(text.encode("utf-16-le")) // 2`.
- `_render_once(card: EditorialInboxCard, body: str | None) -> str` — applies the frozen template
  (Contract §12) with every field escaped via `_escape`, given an already-decided (possibly
  truncated) raw body.

**Rendering/truncation algorithm** (Contract §14, reproduced as an implementation sketch, not
new architecture):
```python
def render_editorial_card(card: EditorialInboxCard) -> str:
    rendered = _render_once(card, card.draft_body)
    if _telegram_utf16_length(rendered) <= SAFE_LIMIT:
        return rendered

    budget = _INITIAL_BODY_BUDGET  # e.g. len(card.draft_body or "") to start; shrinks each pass
    while budget > 0:
        truncated = _truncate_at_word_boundary(card.draft_body or "", budget) + TRUNCATION_MARKER
        rendered = _render_once(card, truncated)
        if _telegram_utf16_length(rendered) <= SAFE_LIMIT:
            return rendered
        budget -= _SHRINK_STEP

    rendered = _render_once(card, None)  # empty body
    if _telegram_utf16_length(rendered) <= SAFE_LIMIT:
        return rendered
    raise CardTooLongError(f"draft_id={card.draft_id} exceeds SAFE_LIMIT even with empty body")
```
This sketch exists only to remove ambiguity about control flow — the exact `_SHRINK_STEP`/binary-
search choice is explicitly left to implementation discretion by the Contract itself (§14 step 4:
"a fixed step or a binary search... are both acceptable, deterministic choices left to Planning").
This Plan picks **a fixed step** (simplest to test deterministically) rather than binary search —
an implementation detail, not an architectural decision, since both are Contract-permitted.

**Forbidden**: `len(rendered)` as the authoritative safety check (only `_telegram_utf16_length` may
gate the pass/fail decision, per Contract §14's explicit prohibition); truncating the already-
escaped string; any `<a href>` construction; any multi-message split.

### `tests/test_editorial_card_formatting.py`

Pure unit tests, no DB, no Telegram — full obligation list from Contract §24 (already
audit-verified complete in the final re-audit, §7 there): per-field escaping including `news_url`
with a literal `&`; `news_url` never inside `<a href>`; hashtag joining/omission; worst-case
escaping-expansion truncation reaching `<= 4096` UTF-16 units; entity-safety (no dangling `&`/`&a`/
`&am`/`&amp`); BMP-vs-astral measurement parity; the `len()<=4096`-but-`telegram_utf16_length()
>4096` trap case; static-emoji inclusion; combined escaping+astral worst case; general
"every successful render satisfies the invariant" check; terminal-fallback `CardTooLongError`
case.

**Milestone owner**: M2. **Rollback scope**: deleting `bot/formatting.py` and its test fully
reverts M2; `bot/handlers/news.py` is not yet touched at this point (M3), so nothing else breaks.

---

## 9. M3 — /news Handler + Session Integration

### `bot/handlers/news.py` (rewrite of the placeholder body)

```python
@router.message(Command("news"))
async def handle_news(message: Message) -> None:
    async with async_session_factory() as session:
        try:
            cards = await get_latest_editorial_cards(session, limit=5)
        except Exception:
            logger.exception("news_query_failed")
            await message.answer(GENERIC_ERROR_TEXT)
            return

        if not cards:
            await message.answer(EMPTY_INBOX_TEXT)
            return

        for card in cards:
            try:
                html = render_editorial_card(card)
            except CardTooLongError:
                logger.error("news_card_render_failed", extra={"draft_id": str(card.draft_id)})
                continue
            try:
                await message.answer(html, parse_mode=ParseMode.HTML)
            except TelegramAPIError:
                logger.exception("news_card_send_failed", extra={"draft_id": str(card.draft_id)})
                continue
```
Single `async with` session scope spanning query + render + send, exactly matching Contract §9's
own pseudocode ordering (open → query → render-and-send loop → close). `parse_mode=ParseMode.HTML`
is passed explicitly even though it duplicates the bot's already-configured default
(`bot/loader.py:24`) — matching the Contract's own literal §9 pseudocode; harmless redundancy, not
a new decision. `TelegramAPIError` is `aiogram.exceptions.TelegramAPIError` (confirmed present in
the installed package, §3 above) — the correct base class for any Bot-API send failure, including
`TelegramBadRequest` (the specific exception a still-oversized or malformed-HTML payload would
raise).

**Preserved**: forum-topic `message_thread_id` — automatic via `message.answer()`, no code added for
it (Contract §10). No session is created outside this one `async with` block; no second session; no
raw SQL/`select()` written directly in the handler (Contract §9's ownership rule).

**Forbidden**: any `EditorialTask` creation; any import of `scripts.run_content_generation`,
`WorkflowRunner`, `CapabilityExecutor`, any Capability; any `ContentDraft` mutation; any "delivered"/
"read" marker; any approval/rejection; any public-channel publish call.

### `tests/test_news_handler.py`

Calls `handle_news()` directly with a constructed `Message` and a fake/mock `Bot` (this repository's
first handler test — no prior file to copy from, §3 above notes this explicitly):
- `/news` calls the query service with `limit=5`.
- Empty-inbox response matches §16 Case A's frozen text.
- Sends exactly the expected number of card messages for a given query result.
- Mechanical import-boundary check: `bot/handlers/news.py` (post-edit) imports none of
  `workflows.runner`, `capabilities.executor`, any `capabilities.*_capability`,
  `scripts.run_content_generation`.
- DB/service failure (a query function that raises) produces §16 Case B's generic text, never a raw
  exception message.
- A `Message` constructed with `is_topic_message=True` and a `message_thread_id` set is sent via
  the same `message.answer()` call as every other case — proving the handler does not fight
  `aiogram`'s automatic thread propagation (Contract §10/F-3).
- Given 5 eligible drafts where one card's render raises `CardTooLongError`, the handler skips only
  that card and still sends the other 4 (§16 Case E, N-2).
- Given 5 eligible drafts where one card's `message.answer()` raises `TelegramAPIError`, the handler
  logs it and continues with the remaining cards (§16 Case D, combined with Case E's per-card
  isolation).

**Milestone owner**: M3. **Rollback scope**: reverting `bot/handlers/news.py` to its placeholder
body and deleting its test fully reverts M3; M1/M2's files remain valid, unused-but-harmless
modules until M3 re-lands.

---

## 10. M4 — Integrated Verification

No new production code. A verification checkpoint exercising the real M1+M2+M3 stack together
against a real test database, with every external boundary controlled:

- **No OpenAI call, no API spend, no `WorkflowRunner`, no `ContentDraft` generation** — test data is
  constructed directly at the ORM level (`EditorialTask(status=TaskStatus.COMPLETED, ...)`,
  `ContentDraft(...)`), exactly as M1's own tests already do; Phase 11 needs no AI machinery to
  prove its own read path works.
- Prove: correct cards selected (COMPLETED-only, latest 5); correct order; correct joined metadata;
  safe HTML (escaping intact end to end through the real handler, not just the renderer in
  isolation); the UTF-16 invariant holds on real-shaped data; **zero writes** — a before/after
  row-count and row-content check on `content_drafts`/`editorial_tasks`/`news_events` confirms no
  mutation occurred anywhere in the invocation.
- **Regression**: `/start`, `/digest`, `/status`, `/settings` re-run unchanged (none of their files
  are touched by Phase 11) — confirms no cross-handler interference from the root router change
  (there is none, since `bot/handlers/__init__.py` itself is not edited).
- Full targeted test run: `python -m pytest tests/test_editorial_inbox_service.py
  tests/test_editorial_card_formatting.py tests/test_news_handler.py -v`, then the full suite
  (§17).

**Milestone owner**: M4. **Rollback scope**: this milestone adds no new file — a failed M4 means one
or more of M1–M3's files need a fix, not a rollback of M4 itself.

---

## 11. M5 — Manual Live Telegram Validation

**Human-authorized only. Not executed automatically as part of implementation.** Per Contract §25:

1. Verify `TELEGRAM_BOT_TOKEN` is configured, without printing its value.
2. Verify DB connectivity only (no Redis dependency exists in this read path — Phase 11 introduces
   no rate-limiting/caching component).
3. Start the real bot via the actual entry point: `python -m bot.main`.
4. Invoke `/news` from a controlled Telegram chat (private chat first).
5. If no real `COMPLETED` drafts exist yet, use Phase 10's own M6 live-validation data (already
   real, already `COMPLETED`, already persisted) — **do not spend new OpenAI budget merely to
   produce Telegram-display test data.**
6. Verify up to 5 cards are received.
7. Verify HTML renders correctly in a real Telegram client (bold text, no literal `<b>` tags
   visible, no "can't parse entities" error).
8. Verify no malformed-message error occurs.
9. Verify the reply lands in the same chat `/news` was invoked from.
10. If tested from within a forum topic (optional, only if a suitable supergroup is available):
    verify the reply lands in the same topic thread.
11. Verify via a direct DB check (before/after) that `content_drafts`/`editorial_tasks` rows are
    byte-for-byte unchanged after the invocation.

**Gate**: no manual Telegram validation occurs until M4's full automated gate (§17) is green.

**Milestone owner**: M5. **Rollback scope**: none — this milestone performs no write of any kind by
design (§16's critical invariant); a failed smoke means returning to M1–M3, not "rolling back" M5
itself.

---

## 12. Per-File Plan

(Consolidates §7–§9's per-file detail into the requested 10-point format; query/rendering mechanics
are not repeated here beyond a pointer, to avoid duplication — see §14/§15.)

### `bot/handlers/news.py`
1. **Responsibility**: thin orchestration — open session, call query service, render each card, send.
2. **Symbols**: `handle_news()` (existing name, rewritten body); no new symbols exported.
3. **Inputs**: `Message` (from aiogram dispatch).
4. **Outputs**: none (side-effecting via `message.answer()`).
5. **Dependencies**: `services.editorial_inbox_service.get_latest_editorial_cards`,
   `bot.formatting.render_editorial_card`/`CardTooLongError`, `database.session
   .async_session_factory`, `aiogram.exceptions.TelegramAPIError`.
6. **Forbidden**: raw SQL/`select()`; `EditorialTask`/`ContentDraft` mutation; AI/workflow import.
7. **Failure semantics**: §16 Cases A/B/D/E, exactly as §9 above.
8. **Test ownership**: `tests/test_news_handler.py`.
9. **Milestone**: M3.
10. **Rollback scope**: revert to placeholder body; zero blast radius on other files.

### `schemas/editorial_inbox.py`
1. **Responsibility**: transport-neutral, frozen view-model for one editorial card.
2. **Symbols**: `EditorialInboxCard`.
3. **Inputs**: constructor kwargs (9 fields, §2 above).
4. **Outputs**: itself (immutable).
5. **Dependencies**: `pydantic` only.
6. **Forbidden**: any `aiogram` import; any mutability (`frozen=True`).
7. **Failure semantics**: standard Pydantic validation error on construction with wrong types —
   not a Phase 11-specific failure mode.
8. **Test ownership**: exercised indirectly via `tests/test_editorial_inbox_service.py`.
9. **Milestone**: M1.
10. **Rollback scope**: deleting the file breaks only M1/M2/M3's imports of it — isolated.

### `services/editorial_inbox_service.py`
1. **Responsibility**: the sole read-only query/assembly boundary for the Editorial Inbox.
2. **Symbols**: `get_latest_editorial_cards(session, *, limit=5) -> list[EditorialInboxCard]`.
3. **Inputs**: an already-open `AsyncSession`, `limit`.
4. **Outputs**: `list[EditorialInboxCard]`, newest-first, length `<= limit`.
5. **Dependencies**: `sqlalchemy`, the three DB models, `schemas.editorial_inbox`.
6. **Forbidden**: `aiogram` import; commit; AI/workflow import; returning a raw ORM object.
7. **Failure semantics**: exceptions propagate uncaught to the caller (handler catches, §16 Case B)
   — this module does not itself translate exceptions into user-facing text.
8. **Test ownership**: `tests/test_editorial_inbox_service.py`.
9. **Milestone**: M1.
10. **Rollback scope**: isolated; only M3's handler depends on it (not yet wired until M3).

### `bot/formatting.py`
1. **Responsibility**: escaping, card templating, UTF-16 length safety, truncation.
2. **Symbols**: `render_editorial_card(card) -> str`, `CardTooLongError`.
3. **Inputs**: one `EditorialInboxCard`.
4. **Outputs**: a fully-escaped HTML `str`, or a raised `CardTooLongError`.
5. **Dependencies**: stdlib `html`, `schemas.editorial_inbox`.
6. **Forbidden**: `aiogram`/`Bot`/`Message` import; `len()` as the authoritative safety check;
   truncating already-escaped HTML; any `<a href>`.
7. **Failure semantics**: `CardTooLongError` on the terminal fallback (§16 Case E via §14).
8. **Test ownership**: `tests/test_editorial_card_formatting.py`.
9. **Milestone**: M2.
10. **Rollback scope**: isolated; only M3's handler depends on it (not yet wired until M3).

---

## 13. Session / Transaction Plan

- **Who creates the `AsyncSession`**: the handler (`bot/handlers/news.py`), via
  `database.session.async_session_factory()`, inside one `async with` block spanning the entire
  request (query + render + send).
- **Who closes it**: the same `async with` block, on normal completion or on any exception escaping
  the block (standard context-manager semantics — no explicit `session.close()` call needed).
- **Service receives session or factory**: **session** — `get_latest_editorial_cards(session, ...)`
  takes an already-open `AsyncSession` as its first parameter, exactly mirroring
  `ContentDraftService.__init__(self, session)`'s constructor-injection precedent in shape (a
  parameter, not a factory) even though this service is function-based, not class-based.
- **SELECT-only**: every operation inside `services/editorial_inbox_service.py` is `session.get()`
  or `session.execute(select(...))` — no `session.add()`, no `session.execute(update(...)/
  delete(...))` anywhere.
- **Zero commit requirement**: no `session.commit()` call exists anywhere in Phase 11's new code —
  confirmed as a design invariant in §7/§17 of the Contract, and enforced here structurally (no
  code path in M1's service or M3's handler ever calls it).
- **Zero workflow/content mutation**: no `ContentDraft`/`EditorialTask` row is ever constructed,
  added, or modified by any Phase 11 file.

**Trace**: `bot/main.py` (`dp.start_polling(bot)`) → dispatcher routes `/news` to
`bot/handlers/news.py::handle_news` → `handle_news` opens `AsyncSession` via
`database.session.async_session_factory()` → passes it to
`services/editorial_inbox_service.py::get_latest_editorial_cards` → session closes when
`handle_news`'s `async with` block exits. **No ambiguity remains** — every hop in this chain is
already a concrete, named symbol, not a placeholder.

---

## 14. Query Plan

Two-stage plan, deterministic, no `relationship()`, no migration, no index:

**Stage 1 — eligibility query** (one round trip, uses `EditorialTask.status`'s existing index per
Contract §6's own performance INFERENCE):
```python
stmt = (
    select(ContentDraft)
    .join(EditorialTask, ContentDraft.task_id == EditorialTask.id)
    .where(EditorialTask.status == TaskStatus.COMPLETED)
    .order_by(ContentDraft.created_at.desc(), ContentDraft.id.desc())
    .limit(limit)
)
drafts = (await session.execute(stmt)).scalars().all()
```
This `.join()` is an explicit, hand-written join condition inside a `select()` statement — **not**
the ORM's declarative `relationship()` feature, so it does not conflict with Contract §5/§21's "no
`relationship()`" prohibition (that prohibition targets the mapped, lazy-loading attribute pattern,
not ordinary explicit joins used for filtering).

**Stage 2 — per-row metadata hop** (Contract §5's frozen convention, applied to at most `limit`
rows — bounded, not unbounded N+1):
```python
cards: list[EditorialInboxCard] = []
for draft in drafts:
    task = await session.get(EditorialTask, draft.task_id)
    assert task is not None  # guaranteed by Stage 1's own join+filter (referential integrity)
    event = await session.get(NewsEvent, task.event_id)
    assert event is not None  # NewsEvent.id is a real FK target, never dangling in this schema
    cards.append(_to_card(draft, event))
```
(The `assert`s above are a defensive-documentation device, not new business logic — they encode
what Stage 1's own join already guarantees; `capabilities/executor.py`'s equivalent hop uses an
explicit `if task is None: raise ...` instead of `assert`, since that call site cannot rely on a
prior join having already proven existence. Whether the final implementation uses `assert` or an
explicit `None` check is a Planning-level style choice, not an architectural one — either is
Contract-consistent.)

**Tables/models**: `ContentDraft`, `EditorialTask`, `NewsEvent`. **Joins**: one explicit
`ContentDraft`⋈`EditorialTask` join (Stage 1); `NewsEvent` retrieved via `session.get()` (Stage 2),
never joined in SQL. **Filters**: `EditorialTask.status == COMPLETED`. **Ordering**:
`created_at DESC, id DESC`. **Limit**: parameterized, default 5. **DTO projection**: `_to_card()`
maps `(ContentDraft, NewsEvent)` → `EditorialInboxCard`, with `hashtags=draft.hashtags  # type:
ignore[arg-type]` mirroring `services/content_draft_service.py:59`'s exact convention.

**No ORM relationship added. No migration. No new index.**

---

## 15. Rendering Plan

- **Escaping helper ownership**: `bot/formatting.py::_escape()`, a thin wrapper over stdlib
  `html.escape(value, quote=False)`.
- **UTF-16 helper ownership**: `bot/formatting.py::_telegram_utf16_length()`, the frozen semantic
  invariant `len(text.encode("utf-16-le")) // 2` (Contract §14's illustrative reference
  implementation, adopted verbatim since it is correct and simple — re-verified this session and
  in the final re-audit).
- **Rendering-failure type ownership**: `bot/formatting.py::CardTooLongError(Exception)`.
- **Raw-field handling**: `draft_body` is the only field ever read in its raw (pre-escape) form for
  truncation purposes; every other field is escaped once, from its DTO value, with no truncation
  path.
- **Optional-field handling**: `draft_title`/`draft_body` render an explicit placeholder string if
  `None` (Contract §12); `news_published_at`/`news_url`/`hashtags` omit their line entirely if
  `None`/empty.
- **Truncation progression**: fixed-step shrink of the raw `draft_body` budget (§8 above), re-
  escape + re-render on every step, re-measured via `_telegram_utf16_length` every time — never the
  wrong unit, never the already-escaped string.
- **Termination**: budget strictly decreases each iteration, floored at zero, at which point the
  empty-body render is attempted once more and, if still oversized, `CardTooLongError` is raised.
  Bounded number of iterations — no infinite loop possible (independently re-proven in the final
  re-audit's §4).
- **Final invariant**: every non-exceptional return value of `render_editorial_card()` satisfies
  `_telegram_utf16_length(result) <= 4096` — this is the function's own postcondition, proven by
  construction, not merely by convention.

**`len(rendered)` as the sole Telegram safety check is explicitly prohibited** — only
`_telegram_utf16_length()` may gate the pass/fail decision anywhere in this module.

---

## 16. Test Matrix

Contract → Test mapping (every binding behavior maps to at least one planned test; ✓ = covered):

| Contract behavior | Test file | Covered |
|---|---|---|
| COMPLETED-only eligibility | `test_editorial_inbox_service.py` | ✓ |
| FAILED/CREATED/RUNNING/WAITING excluded | `test_editorial_inbox_service.py` | ✓ |
| Newest-first + `id` tie-break | `test_editorial_inbox_service.py` | ✓ |
| Limit 5 | `test_editorial_inbox_service.py` | ✓ |
| Empty result | `test_editorial_inbox_service.py` | ✓ |
| Joined metadata, optional `news_url` | `test_editorial_inbox_service.py` | ✓ |
| No AI/workflow import (service) | `test_editorial_inbox_service.py` (AST check) | ✓ |
| Escaping every dynamic field incl. `news_url` | `test_editorial_card_formatting.py` | ✓ |
| `news_url` never in `<a href>` | `test_editorial_card_formatting.py` | ✓ |
| Worst-case escaping expansion → `<=4096` UTF-16 | `test_editorial_card_formatting.py` | ✓ |
| Entity-safety of truncation | `test_editorial_card_formatting.py` | ✓ |
| BMP vs. astral UTF-16 measurement | `test_editorial_card_formatting.py` | ✓ |
| `len()<=4096` but UTF-16`>4096` trap | `test_editorial_card_formatting.py` | ✓ |
| Static + AI-generated emoji counted | `test_editorial_card_formatting.py` | ✓ |
| Terminal fallback → `CardTooLongError` | `test_editorial_card_formatting.py` | ✓ |
| Empty-inbox message (§16 Case A) | `test_news_handler.py` | ✓ |
| DB/query failure → generic message (§16 Case B) | `test_news_handler.py` | ✓ |
| Forum-topic thread preservation (handler side) | `test_news_handler.py` | ✓ |
| Card render failure → skip + continue (§16 Case E / N-2) | `test_news_handler.py` | ✓ |
| Telegram send failure → log + continue (§16 Case D) | `test_news_handler.py` | ✓ |
| No AI/workflow import (handler) | `test_news_handler.py` (AST check) | ✓ |
| Zero DB mutation end to end | M4 integrated check (before/after row check) | ✓ |
| Existing-command regression | M4 (`/start`/`/digest`/`/status`/`/settings`) | ✓ |
| No live Telegram call in automated suite | all three new test files (fake `Bot`/`Message` only) | ✓ |
| Manual live smoke | M5 (human-authorized) | ✓ |

**No gap found.** This mirrors the final re-audit's own 11-point checklist (§7 there) plus every
other Contract-frozen behavior not specific to the length/escaping correction rounds.

---

## 17. Verification Gates

**Per milestone** (M1, M2, M3 each independently, before proceeding to the next):
- Focused `pytest` run for that milestone's new test file(s).
- Relevant regression: re-run any test file that imports the newly-changed module transitively
  (none exist yet for M1/M2's brand-new modules; M3's change to `bot/handlers/news.py` requires
  re-running the (not-yet-existing-until-M3) existing-command smoke as part of M4, not a per-
  milestone regression at M1/M2).
- `python -m ruff check .`
- Targeted `mypy` on the milestone's changed/new files only.
- `python -m scripts.validate_architecture` (no rule table change expected or authorized — Phase 11
  touches no provider-adapter file).
- Git scope audit: `git status --short` / `git diff --stat` shows only the files that milestone's
  own plan (§4) authorizes — nothing else staged or modified.

**Final automated checkpoint, before M5** (after M4):
- Full `python -m pytest -q` (entire suite, including every pre-existing test, unmodified).
- `python -m ruff check .` clean.
- Targeted `mypy` clean on every changed/new Python file (the 4 production files).
- `python -m scripts.validate_architecture` reports 0 violations.
- Secret hygiene: no credential committed; `.env` remains untracked; no debug bypass introduced.
- `git diff`/scope review: confirms the diff touches exactly the 7 files in §4, nothing else.

**No manual Telegram validation (M5) until this final checkpoint is fully green.**

---

## 18. Risk Register

| Risk | Cause | Impact | Mitigation | Test/Verification |
|---|---|---|---|---|
| Session injection mismatch | No DI exists in the bot layer; handler must open its own session correctly | Handler could leak a session or use a stale one | Single `async with` block, mirroring the already-proven `scripts/run_content_generation.py` pattern exactly | `test_news_handler.py` exercises the full handler path with a real fixture-backed flow in M4 |
| Accidental DB write | A stray `session.add()`/`commit()` introduced by mistake | Violates the Contract's core read-only invariant | Mechanical AST import-boundary tests don't catch this directly — mitigated by code review + the M4 before/after row-count/content check | M4's zero-mutation check; manual code review at each milestone gate |
| Query duplicate-draft semantics | `ContentDraft.task_id` has no uniqueness constraint | A hypothetical duplicate draft could appear twice | Not reachable via any current code path (§7 above); ordering already handles it correctly if it ever occurred | `test_editorial_inbox_service.py`'s ordering tests implicitly cover this — no dedicated test needed since no invented logic exists to test |
| HTML escaping gap | A dynamic field added to the card template without updating the escaping list | Telegram "can't parse entities" failure or, worse, unintended markup injection | Contract §13's field list is exhaustive and frozen; this Plan does not add any new dynamic field beyond the 6 already named | `test_editorial_card_formatting.py`'s per-field escaping tests, one per field |
| UTF-16 undercount | Using `len()` instead of `_telegram_utf16_length()` anywhere in the safety check | Oversized message sent to Telegram, send failure | `len()` explicitly prohibited as the authoritative check (Contract §14, this Plan §15); code review at M2's gate | `test_editorial_card_formatting.py`'s `len()<=4096`-but-UTF16`>4096` trap test |
| Truncation non-termination | A bug in the shrink-budget decrement | Handler hangs on a single oversized card | Budget is a simple, strictly-decreasing, floored-at-zero loop variable — structurally bounded | `test_editorial_card_formatting.py`'s worst-case and terminal-fallback tests both exercise the full loop to completion |
| Oversized static metadata | `news_title`/`hashtags` unexpectedly very long (unbounded `Text`/`JSON` columns) | Even an empty-body card could exceed the limit | Contract §14's terminal fallback (`CardTooLongError` → §16 Case E) already handles this deterministically | `test_editorial_card_formatting.py`'s terminal-fallback test constructs exactly this scenario |
| Telegram send partial failure | One of 5 `message.answer()` calls raises `TelegramAPIError` | User receives fewer than 5 cards with no explanation | Per-card try/except, log-and-continue (§16 Case D/E) — accepted, frozen behavior, not a defect | `test_news_handler.py`'s send-failure test |
| Forum-topic behavior | Relies on `aiogram==3.29.1`'s current, unpinned-by-this-repo-but-pinned-by-`pyproject.toml` behavior | A future `aiogram` upgrade could silently change `message_thread_id` propagation | Contract §10 explicitly scopes the guarantee to the pinned version and requires re-verification on upgrade — out of Phase 11's own scope to defend against | `test_news_handler.py`'s forum-topic test pins current behavior; a future dependency-upgrade PR would need to re-run it |
| Bot runtime/bootstrap assumptions | `create_dispatcher()` has no DI; a future bootstrap change could break the handler's direct session-opening assumption | Handler could break silently if bootstrap changes without this assumption being re-checked | `bot/loader.py`/`bot/main.py` are frozen, unmodified files (§18 of the Contract) — this Plan does not touch them | M4's regression check exercises the real `bot/main.py` bootstrap path indirectly via the handler test's use of the real router/dispatch shape |
| Accidental scope creep into editorial actions | A future milestone tempted to add a "quick" Approve button | Silently violates the Contract's frozen out-of-scope list | Explicit "forbidden responsibilities" listed per file (§12); no callback/keyboard file is in the authorized scope (§4) at all | Git scope audit at every milestone gate (§17) — any unauthorized file appearing in the diff fails the gate |
| Accidental Phase 5–10 modification | A milestone reaches for a "small fix" in a frozen file | Violates Contract §18's frozen-boundary list | §4's file table is exhaustive; §17's git scope audit catches any file outside it | Git scope audit at every milestone gate |

---

## 19. Definition of Done

Reproduced from Contract §26, unchanged (this Plan does not weaken or reinterpret any item):

1. `/news` returns latest eligible completed drafts. 2. Maximum 5. 3. Ordering deterministic.
4. Query is read-only. 5. No migration. 6. Cards safely escape all dynamic values. 7. `news_url`
follows the frozen plain-text rule. 8. Every successful card satisfies
`telegram_utf16_length <= 4096`. 9. Terminal oversize is safely skipped under §16 Case E. 10. Multi-
card continuation works. 11. Empty state works. 12. DB error behavior works. 13. Telegram send
failure follows frozen behavior. 14. Forum-topic behavior matches pinned `aiogram` semantics.
15. No auth introduced. 16. No callbacks/write actions. 17. No scheduler/push/publication. 18. No
meme/image scope. 19. No `WorkflowRunner`/`Capability`/Gateway modification. 20. Full automated
suite green. 21. Ruff green. 22. Mypy green on changed production files. 23. Architecture validator
green. 24. Secret hygiene clean. 25. Manual live Telegram smoke passes. 26. DB verification confirms
`/news` caused no content/workflow state mutation.

---

## 20. Rollback / Checkpoint Strategy

- **Per milestone**: each of M1/M2/M3 adds a self-contained set of new files (M1: 2 production + 1
  test; M2: 1 production + 1 test; M3: 1 edited file + 1 test) with no cross-milestone file overlap
  except through explicit, one-directional imports (M3 imports M1+M2; M1/M2 import nothing from
  M3). A milestone can be reverted (`git checkout` / file deletion) without affecting an earlier
  milestone's already-merged work.
- **Commit discipline**: **no commit is authorized during this planning task or automatically during
  implementation.** Each milestone (M0–M5) **STOPS for human review** after completion — consistent
  with this session's established pattern across Phase 9/9.5/10/11 — unless a later, separate human
  instruction explicitly authorizes autonomous multi-milestone continuation (mirroring the exact
  "M0→M5 autonomous, M6 requires separate authorization" pattern already used for the OpenAI
  Structured Outputs remediation in this repository's history). This Plan does not itself grant
  that authorization.
- **M5 rollback**: not applicable — M5 performs no write by design; a failed smoke returns to
  M1–M3, not a "rollback" of M5's own (nonexistent) changes.

---

## 21. Explicit Out-of-Scope

Reproduced from the task's own "Absolute Scope Boundary" and Contract §3/§18–§21, unchanged, no
"future-ready" abstraction included for any of the following: Approve; Reject; Rework; Regenerate;
Publish; callback buttons; inline editorial actions; delivery persistence; read/unread state; review
state; destination persistence; chat configuration; authorization/RBAC; `User` bootstrap;
allowlists; scheduler; polling delivery worker; push delivery; automatic publication; channel
publishing; memes; image generation; image Gateway changes; migrations; crash recovery; workflow
resume; workflow-engine redesign.

---

## 22. Final Readiness Assessment

**Self-audit** (per the task's 12 questions):

1. Does every implementation file come from Contract-authorized scope? **Yes** — §4's 7-file table
   matches Contract §23 exactly; independently re-derived, not copied without checking.
2. Is session ownership deterministic? **Yes** — §13, one concrete, named symbol at every hop.
3. Is query behavior deterministic? **Yes** — §14, exact filter/order/limit/join, no ambiguity.
4. Is UTF-16 behavior deterministic? **Yes** — §15, one frozen semantic invariant, one reference
   implementation.
5. Is terminal oversize behavior deterministic? **Yes** — one exception type, one §16 Case E
   mapping, bidirectionally cross-referenced in the Contract itself.
6. Is multi-card failure behavior deterministic? **Yes** — per-card try/except, skip-and-continue,
   frozen by Contract §16 Case E.
7. Is forum-topic behavior deterministic? **Yes** — automatic via the pinned `aiogram` version,
   independently re-verified three times across this session's audits.
8. Does any step require migration? **No.**
9. Does any step require AI? **No** — M1/M4's tests construct `COMPLETED` fixtures directly at the
   ORM level; M5 reuses Phase 10's existing live-validation data.
10. Does any step modify Phase 5–10 architecture? **No** — §4's file table contains zero files from
    the Contract §18 frozen list.
11. Did the Plan accidentally introduce auth/write actions/push/memes? **No** — §21 confirms none.
12. Can implementation proceed milestone-by-milestone without inventing architecture? **Yes** —
    every decision point traced in §2/§12–§15 already has a frozen, Contract-sourced answer; the
    only choices left to this Plan's own discretion (fixed-step vs. binary-search truncation,
    `assert` vs. explicit `None`-check for Stage 2's hop) are explicitly Contract-permitted
    implementation style, not architecture.

**No Contract defect was exposed by this exercise.** No workaround was invented anywhere in this
Plan — every mechanism traces to a specific, cited Contract section.

---

PHASE 11 IMPLEMENTATION PLAN READY FOR AUDIT
