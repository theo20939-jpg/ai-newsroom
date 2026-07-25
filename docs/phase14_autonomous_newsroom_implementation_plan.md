# Phase 14 — Autonomous Newsroom Loop: MVP Implementation Plan

Planning only. No code has been written or modified to produce this document. No migration was
created. No new architectural decision beyond what is explicitly proposed and flagged below was
made unilaterally.

## 0. Authority and frozen decisions

Builds directly on `docs/phase14_autonomous_newsroom_discovery.md`'s own findings — this plan
does not re-derive them, only turns them into an exact, file-level implementation order.

Frozen (given, not renegotiated by this plan): do not modify the `NEWS_ANALYSIS` workflow; do not
modify the `CONTENT_GENERATION` workflow contract; no event bus; no new database table; a
dedicated `content_worker` (`worker/content_main.py` + `worker/content_cycle.py`); reuse existing
content-generation infrastructure unmodified; duplicate protection covering `COMPLETED` history,
not merely active tasks; Telegram notification only after `ContentDraft` creation; no
autopublishing; no approval system; no images/memes.

**Approved with four clarifications** (this revision incorporates all four; each is marked at its
own point in the document below):

1. `content_generation_freshness_cutoff_hours` is **approved and now frozen** — with its own
   purpose explicitly reframed: it is a **technical safety boundary**, not an editorial
   "is this still newsworthy" judgment. Its only two jobs are (a) giving tests the same safe
   isolation lever Phase 13's own `news_analysis_freshness_cutoff_hours` already provides (Phase
   13's M3 milestone hit a real, disclosed incident from exactly this gap — `docs/phase13_m3_
   analysis_cycle_report.md`), and (b) bounding the cost of re-enabling `content_worker` after any
   pause, so it never attempts to process the entire historical `COMPLETED` backlog at once. It
   must not be read, tuned, or documented as an editorial-freshness control — that framing belongs
   to `content_generation_min_score` (a real editorial-quality gate) and to the underlying `NEWS_
   ANALYSIS` freshness cutoff (already frozen in Phase 13), not to this one. Default: **24 hours**
   — no existing config convention in this codebase calls for a different value, so the plan's own
   original default stands, now as an accepted, not merely proposed, value.
2. SQL-side `content_generation_scan_limit` — **approved, and strengthened into an explicit,
   named guarantee**, not just an implementation detail of one query (§3, §4.1).
3. Telegram delivery — **two explicit modes added**: `dry-run` (render the exact outgoing payload,
   never call the Telegram API) and `live` (requires an explicit, separate human confirmation of
   the target chat) (§5, §6, §8).
4. Notification failure behavior — **defined explicitly**: no duplicate-notification protection
   for MVP; a failed send is logged and the cycle moves on; if a future reprocessing of the same
   event were ever to occur, a duplicate notification is an accepted, non-blocking outcome, not a
   defended-against one (§5).

No other renegotiation of frozen decisions occurred. No code was written to produce this revision.

## 1. Exact file scope

| File | Status | Milestone | Why |
|---|---|---|---|
| `worker/content_main.py` | NEW | M4 | Entry point — mirrors `worker/analysis_main.py` exactly |
| `worker/content_cycle.py` | NEW | M2/M3 | Eligibility query + sequential orchestration |
| `services/telegram_notifier.py` | NEW | M3 | One function, reuses existing render/bot code |
| `core/config.py` | MODIFY (narrow, append only) | M1 | New `Settings` fields (§6) |
| `docker-compose.yml` | MODIFY (narrow, append only) | M4 | One new service, mirrors `news_analysis_worker` |
| `tests/test_settings_phase7.py` | MODIFY (append only) | M1 | New field tests |
| `tests/test_content_worker_cycle.py` | NEW | M2/M3 | Eligibility + duplicate-prevention + orchestration tests |
| `tests/test_telegram_notifier.py` | NEW | M3 | Pure render/send tests, mocked `Bot`, no real Telegram call |
| `tests/test_content_worker_main.py` | NEW | M4 | Enabled/disabled loop, cancellation — mirrors `tests/test_analysis_worker_main.py` |
| `tests/test_content_generation_integration.py` | NEW | M5 | Full offline chain: `NEWS_ANALYSIS COMPLETED` → `content_cycle` → `ContentDraft` → notifier called (mocked `Bot`) |

**Not touched, explicitly frozen unmodified**: `scripts/run_content_generation.py`,
`services/content_draft_service.py`, `workflows/definitions/content_generation.py`,
`workflows/definitions/news_analysis.py`, `workflows/runner.py`, `worker/analysis_main.py`,
`worker/analysis_cycle.py`, `bot/handlers/news.py`, `services/editorial_inbox_service.py`,
`bot/formatting.py`, `bot/loader.py`. Reused by import, not by copy or modification.

**Total**: 3 new production files + 2 narrow modified production files = 5 production; 4 new test
files + 1 narrow modified test file = 5 test. **10 files total.**

## 2. Milestone order

```
M0  Baseline re-verification (no code)
      ↓
M1  Settings — 8 new fields, config-only, zero behavior yet
      ↓
M2  Eligibility query — worker/content_cycle.py::_select_eligible_events()
      (duplicate-prevention lives here — see §3)
      ↓
M3  Telegram notifier + cycle orchestration
      (worker/content_cycle.py::run_content_cycle(), services/telegram_notifier.py)
      ↓
M4  Runtime entry point + Docker
      (worker/content_main.py, docker-compose.yml)
      ↓
M5  Offline integration test (full chain, mocked Bot, real Postgres)
      ↓
M6  Full regression gate (mirrors Phase 13's own M6 exactly: focused + full pytest +
    ruff + mypy + architecture validator + secret hygiene + git scope + migration
    audit + DB pollution audit)
      ↓
STOP — human authorization required
      ↓
M7  Live validation (one controlled event, real provider calls, real Telegram send
    to a human-confirmed test chat)
```

M2 before M3 is deliberate: the eligibility query (including duplicate prevention) is the one
piece of new logic with real correctness risk (an error here means either missed content or,
worse, duplicate `CONTENT_GENERATION` tasks) — proving it correct in isolation, with its own
dedicated tests, before wiring it into the orchestration loop, mirrors exactly how Phase 13
ordered its own M2 (atomic claim) ahead of M3 (cycle orchestration) for the identical reason.

## 3. Duplicate prevention strategy

**Requirement (frozen decision 7)**: no `CONTENT_GENERATION` task may be created twice for the
same `NewsEvent`, including when the previous one is already `COMPLETED` — not merely "no two
active ones at once" (that weaker guarantee already exists, for free, in `workflow_service.
create_task()`'s own `_find_active_task()`, confirmed by direct read this Discovery session to
check only `CREATED`/`RUNNING`).

**Mechanism, entirely SQL-side, no new column, no new table**: a correlated `NOT EXISTS`
subquery against the same `editorial_tasks` table, keyed on the shared `event_id` — the identical
relationship `_find_active_task()` already uses, just checking existence unconditional on status
instead of restricted to active statuses:

```python
from sqlalchemy import select, exists
from sqlalchemy.orm import aliased

ContentGenTask = aliased(EditorialTask)

_duplicate_check = exists(
    select(1)
    .select_from(ContentGenTask)
    .where(
        ContentGenTask.event_id == EditorialTask.event_id,
        ContentGenTask.workflow["workflow_name"].as_string() == WorkflowType.CONTENT_GENERATION.value,
    )
)
```

This one subquery is the entire duplicate-prevention mechanism. It is evaluated by Postgres, per
candidate row, before any Python code sees the row — a task that already has *any*
`CONTENT_GENERATION` sibling (`CREATED`, `RUNNING`, `COMPLETED`, or `FAILED` — every status, not a
subset) is excluded at the SQL level, not filtered out afterward. There is no window where the
same event could be selected twice by two different cycles of the same worker running
sequentially (each cycle re-evaluates the subquery fresh against then-current data).

**What this does NOT protect against, disclosed honestly**: two *concurrent* `content_cycle`
invocations (e.g., two worker processes/replicas running at once) racing on the same event —
between one cycle's `SELECT` and its own `workflow_service.create_task()` `INSERT`, another
concurrent cycle could run the same `SELECT`, also see no existing `CONTENT_GENERATION` task yet,
and also attempt to create one. `workflow_service.create_task()`'s own `_find_active_task()` check
is a plain `SELECT` followed by `INSERT`, not an atomic conditional `UPDATE` the way Phase 13's
`WorkflowRunner.run()` claim is — so this specific race is **not** atomically closed by this
design. **Accepted limitation for MVP, exactly mirroring how Phase 13 M2's own atomic-claim
guarantee was scoped**: this is only correct as long as exactly one `content_worker` instance
runs at a time, sequentially, with no `asyncio.gather`/concurrent replica — the same operating
assumption `worker/analysis_main.py`/`worker/main.py` already carry today (single instance, per
`docker-compose.yml`, one container each). If multiple replicas become a real requirement later,
closing this race properly (e.g., an atomic claim on `NewsEvent` itself, or a unique constraint)
is new work, out of this MVP's scope — flagged here, not solved here.

**Freshness bound (§0 clarification 1 — frozen, technical safety boundary only, not an editorial
control)**: the eligibility query additionally requires the candidate `NEWS_ANALYSIS` task's own
`updated_at` (the moment it became `COMPLETED`) to be within `content_generation_freshness_
cutoff_hours` (default 24h). This exists solely to bound initial-enablement backlog-processing
cost and to give tests a safe isolation lever — it must not be tuned or reasoned about as "how
stale can news be before it's not worth writing about"; that editorial judgment, to the extent
Phase 14 makes one at all, lives entirely in `content_generation_min_score` (§4.1/§6).

**Scan-limit guarantee (§0 clarification 2 — explicit, load-bearing, not merely incidental)**:
`content_generation_scan_limit` (§4.1, §6) is a **hard, unconditional cap enforced by Postgres
itself via `LIMIT`**, evaluated *before* any row is materialized into Python and *before* the
score-threshold check runs. The worker **never** loads an unbounded number of `NEWS_ANALYSIS`
tasks into memory, regardless of how large the real `COMPLETED`-and-not-yet-content-generated
backlog grows — the same structural guarantee Phase 13's own `news_analysis_batch_size` `LIMIT`
already provides for its own eligibility query, applied here one layer earlier (bounding the
*candidate scan*, not only the *final batch*, since this query has an extra Python-side filtering
step — §4.1 — that Phase 13's own query does not need). `content_generation_scan_limit` must be
`>= content_generation_batch_size` (§6) — enforced by a test (§7), not merely documented.

## 4. Worker design

### 4.1 `worker/content_cycle.py::_select_eligible_events()`

```python
async def _select_eligible_events(session: AsyncSession) -> list[UUID]:
    """SQL-side: status, workflow-name match, duplicate exclusion, freshness bound, ordering,
    and a scan-limit cap are all evaluated by Postgres. Only the final, capped result rows are
    materialized into Python for the score-threshold check below (§4.1's own note on why score
    cannot be expressed in this same SQL statement)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.content_generation_freshness_cutoff_hours)
    ContentGenTask = aliased(EditorialTask)

    stmt = (
        select(EditorialTask.id, EditorialTask.event_id, EditorialTask.workflow)
        .where(
            EditorialTask.status == TaskStatus.COMPLETED,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
            EditorialTask.updated_at >= cutoff,
            ~exists(
                select(1).select_from(ContentGenTask).where(
                    ContentGenTask.event_id == EditorialTask.event_id,
                    ContentGenTask.workflow["workflow_name"].as_string() == WorkflowType.CONTENT_GENERATION.value,
                )
            ),
        )
        .order_by(EditorialTask.updated_at.asc(), EditorialTask.id.asc())
        .limit(settings.content_generation_scan_limit)
    )
    rows = (await session.execute(stmt)).all()

    # Score threshold applied here, in Python, over the already SQL-capped candidate set only -
    # NOT an unbounded backlog scan. Why not SQL-side: score lives at
    # workflow["step_results"][i]["result"]["score"] for the entry whose step_name == "scoring" -
    # locating an array element by a sibling field's value, then reading a nested key, inside a
    # generic (non-JSONB) JSON column is not cleanly expressible with this stack (unlike Phase
    # 13's own top-level `.as_string()` key match) - re-verify this constraint empirically at
    # implementation time before accepting it as final, do not assume it without re-checking.
    eligible: list[UUID] = []
    for task_id, event_id, workflow in rows:
        score = _extract_scoring_result(workflow)
        if score is not None and score >= settings.content_generation_min_score:
            eligible.append(event_id)
        if len(eligible) >= settings.content_generation_batch_size:
            break
    return eligible
```

`_extract_scoring_result(workflow: dict) -> int | None` — a small, pure helper: iterate
`workflow["step_results"]`, find the entry with `step_name == "scoring"` and `status ==
"SUCCESS"`, return `result["score"]`; `None` if absent (defensively excludes a task whose scoring
step somehow never ran or was skipped, rather than crashing or defaulting to "pass").

**Returns `event_id`, not `task_id`** — deliberate: `run_content_generation_for_event()` (§4.2)
takes `event_id` as its own primary input, matching its existing signature exactly; no adapter
needed.

### 4.2 `worker/content_cycle.py::run_content_cycle()`

```python
async def run_content_cycle(
    capability_registry: CapabilityRegistry,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> ContentCycleResult:
    result = ContentCycleResult()

    async with session_factory() as session:
        event_ids = await _select_eligible_events(session)
    result.eligible_found = len(event_ids)

    # Sequential, no asyncio.gather - identical convention to worker/analysis_cycle.py, and for
    # the same reason: bounded, predictable work per cycle; no refill if one is skipped/fails.
    for event_id in event_ids:
        outcome = await run_content_generation_for_event(  # scripts/run_content_generation.py,
            event_id, capability_registry=capability_registry, session_factory=session_factory,
        )  # UNMODIFIED - imported, not copied (frozen decision 6)
        if outcome.content_draft is None:
            result.failed += 1
            continue
        result.completed += 1

        async with session_factory() as session:
            event = await session.get(NewsEvent, event_id)
        notification = await send_editorial_card(
            bot, settings.editorial_chat_id, outcome.content_draft, event,
            dry_run=settings.content_generation_dry_run,
        )  # never raises (§5) - always returns a NotificationOutcome, dry-run or live
        if settings.content_generation_dry_run:
            result.dry_run_rendered += 1  # expected outcome in dry-run mode, not a failure
        elif notification.sent:
            result.notified += 1
        else:
            result.notification_failed += 1
            # ContentDraft already committed - a failed notification is never rolled back and
            # never actively retried (§5.1: no duplicate-notification protection for MVP;
            # /news remains the durable fallback for a lost push notification).

    return result
```

`run_content_generation_for_event()` is imported and called **exactly as-is** — zero changes,
same `capability_registry`/`session_factory` injection seam its own docstring already documents
as designed for reuse by other production code, not only the CLI script.

### 4.3 `worker/content_main.py`

Byte-for-byte structural mirror of `worker/analysis_main.py`: `_run_enabled_loop()` (assembles the
real AI layer **and** a real `Bot` once at startup, then `while True: run_content_cycle(...);
sleep(poll_interval)`), `_run_disabled_idle()`, the same `SIGTERM`/`SIGINT`/`NotImplementedError`
signal-handling block, the same `except Exception: logger.exception(...)` cycle-level-failure
tolerance. No new pattern invented.

## 5. Telegram sender design

`services/telegram_notifier.py` — one new file, one function, now with an explicit `dry_run`
parameter (§0 clarification 3):

```python
@dataclass(frozen=True)
class NotificationOutcome:
    """Always returned, in both modes - makes the exact outgoing payload directly inspectable by
    the caller/tests, not merely logged (mirrors ContentGenerationOutcome's own
    directly-inspectable-result convention, scripts/run_content_generation.py)."""
    chat_id: int
    rendered_html: str
    sent: bool  # False in dry-run mode, or if the live send itself failed


async def send_editorial_card(
    bot: Bot, chat_id: int, draft: ContentDraftRead, event: NewsEvent, *, dry_run: bool
) -> NotificationOutcome:
    """Builds the exact same EditorialInboxCard shape services/editorial_inbox_service.py's own
    _to_card() already builds (not a new shape), renders it with the existing, unmodified
    bot/formatting.py::render_editorial_card().

    dry_run=True: renders and returns the exact payload (chat_id + HTML) that WOULD be sent -
    bot.send_message() is never called, no Telegram API contact of any kind. Logged at INFO for
    human inspection (content_notification_dry_run).

    dry_run=False (live): actually calls bot.send_message(). A CardTooLongError (rendering) or a
    TelegramAPIError (the live send itself) is caught here, logged
    (content_notification_failed), and returned as NotificationOutcome(sent=False) - never
    raised past this function, mirroring bot/handlers/news.py's own established per-card error
    handling exactly, so one bad card/send never aborts the caller's own loop (§4.2)."""
    card = EditorialInboxCard(
        draft_id=draft.id, draft_title=draft.title, draft_body=draft.body,
        hashtags=draft.hashtags, draft_created_at=draft.created_at,
        news_title=event.title, news_category=event.category.value,
        news_url=event.url, news_published_at=event.published_at,
    )
    try:
        html = render_editorial_card(card)  # bot/formatting.py - unmodified
    except CardTooLongError:
        logger.error("content_notification_render_failed", extra={"draft_id": str(draft.id)})
        return NotificationOutcome(chat_id=chat_id, rendered_html="", sent=False)

    if dry_run:
        logger.info(
            "content_notification_dry_run",
            extra={"draft_id": str(draft.id), "chat_id": chat_id, "html": html},
        )
        return NotificationOutcome(chat_id=chat_id, rendered_html=html, sent=False)

    try:
        await bot.send_message(chat_id, html, parse_mode=ParseMode.HTML)
    except TelegramAPIError:
        logger.exception("content_notification_failed", extra={"draft_id": str(draft.id)})
        return NotificationOutcome(chat_id=chat_id, rendered_html=html, sent=False)

    return NotificationOutcome(chat_id=chat_id, rendered_html=html, sent=True)
```

`Bot` is constructed once, at `content_main.py` startup, via the existing, unmodified
`bot/loader.py::create_bot()` — the same "assemble expensive resources once, reuse across cycles"
convention `assemble_ai_integration_layer()` already follows in every worker. **Constructed
identically regardless of `dry_run`** — dry-run mode skips only the `send_message()` call itself,
not `Bot` construction, so switching modes never requires a different startup path.

**Mode selection (§0 clarification 3, `live` requires explicit human confirmation)**:
`content_generation_dry_run: bool = True` (§6) is the single switch, defaulting to the safe
value. Flipping it to `False` is, by itself, the "explicit human verification" step this
clarification requires — there is no separate silent path to live sending; a human must
deliberately change this one setting (and `editorial_chat_id` must already be set — §6's own
validation makes `dry_run=False` with no `editorial_chat_id` a startup-time configuration error,
not a silent no-op). §8's live validation procedure exercises dry-run first, unconditionally,
before ever flipping to live.

### 5.1 Notification failure behavior (§0 clarification 4, defined explicitly)

**No duplicate-notification protection exists or is planned for this MVP.** This is a deliberate
scope decision, not an oversight: building it would require either a new tracked "notified"
state (a new column, explicitly out of scope per the frozen "no new database tables" decision,
and a new column carries its own migration/scope questions this MVP does not open) or a
retry/queue mechanism (explicitly excluded, §5's own "explicitly not built" list, retained below).

**Behavior, precisely**: if `ContentDraft` creation succeeds but the subsequent
`send_editorial_card()` call fails (`sent=False`, whether from render failure or a live
`TelegramAPIError`), this is logged (`content_notification_failed`/`content_notification_render_
failed`) and `run_content_cycle()` (§4.2) proceeds to the next event in its batch — the `Content
Draft` itself is never rolled back, never deleted, never marked in any special "notification
failed" state (no such state exists to mark it in).

**Why "retry on next cycle is acceptable" does not require new machinery**: because §3's own
duplicate-prevention `NOT EXISTS` check excludes any event whose `NEWS_ANALYSIS` task already has
*any* `CONTENT_GENERATION` sibling, a `ContentDraft` that was successfully created (even if its
own notification failed) will **not** be naturally reprocessed by `_select_eligible_events()` on
a later cycle under normal operation — the durable fallback for a lost push notification is the
already-existing, unmodified `/news` command, which reads `ContentDraft` directly and
unconditionally on notification history (§1's "not touched" list). If some future change ever
causes the same event to be reprocessed regardless (a deliberate re-scope, a manual DB
intervention, a bug), a second notification attempt for what is by then a *second, separate*
`ContentDraft` row is an accepted outcome, not a case this MVP defends against — consistent with
"duplicate notification protection is NOT implemented."

**Explicitly not built** (retained from the original design, still accurate): a retry queue for
failed sends, delivery-confirmation tracking, a second worker/table for "pending notifications,"
any notified-state tracking column.

## 6. Configuration changes (`core/config.py`, M1, append only)

```python
content_generation_enabled: bool = False
content_generation_poll_interval_seconds: int = Field(default=300, gt=0)
content_generation_batch_size: int = Field(default=5, gt=0)
content_generation_scan_limit: int = Field(default=50, gt=0)  # must be >= batch_size; validated
content_generation_min_score: int = Field(default=70, ge=0, le=100)
content_generation_freshness_cutoff_hours: float = Field(default=24.0, gt=0)  # frozen, §0 cl.1 -
# technical safety boundary only, not an editorial-freshness control
content_generation_dry_run: bool = True  # §0 cl.3 - safe default; live requires an explicit,
# separate human flip, exactly mirroring content_generation_enabled's own fail-safe-off default
editorial_chat_id: int | None = None  # renamed from an earlier draft's telegram_notification_
# chat_id - aligns with this codebase's own existing "Editorial Inbox"/EditorialInboxCard naming
```

`content_generation_min_score` default (`70`) is a placeholder for review, not empirically
derived — flagged explicitly as a value a human should confirm or override, same as Phase 13's
own `news_analysis_freshness_cutoff_hours` default was presented and accepted during that Plan's
own review. `content_generation_freshness_cutoff_hours` (`24.0`) is now a frozen, accepted
default per §0 clarification 1 — not open for the same "please reconsider" framing, since its
purpose is technical, not editorial.

`editorial_chat_id` has no safe default (`None`); `content_generation_dry_run` defaults to
`True`. **Both must be deliberately set for a live send to ever occur**: `content_generation_
dry_run=False` while `editorial_chat_id` is `None` is a startup-time configuration error (fail
loud, mirroring this codebase's own established `RuntimeError`/fail-fast convention for missing
required config — e.g. `bot/loader.py::create_bot()`'s own `TELEGRAM_BOT_TOKEN` check — not a
silent no-op). With the safe defaults, `content_generation_enabled=true` alone creates real
`ContentDraft` rows (visible via the unmodified `/news` command) and logs dry-run payloads, but
sends nothing.

**No `max_daily_ai_cost`, no new cost-tracking field** — consistent with Phase 13's own frozen
decision (Decision Resolution Human Decision B): cost exposure remains workload-bounded
(`batch_size`, `scan_limit`, `freshness_cutoff_hours`, `min_score`), never monetary.

## 7. Tests required

| Test file | Proves |
|---|---|
| `tests/test_settings_phase7.py` (append) | 8 new fields: defaults (including `content_generation_dry_run` defaulting `True` and `editorial_chat_id` defaulting `None`), env overrides, validation (`gt=0` rejects zero/negative); `content_generation_scan_limit >= content_generation_batch_size` is enforced (§3's own scan-limit guarantee) — either a `Settings`-level validator if implemented that way, or a dedicated non-Settings test asserting the *default* relationship holds, whichever the implementation settles on, but the relationship itself must be tested, not merely documented |
| `tests/test_content_worker_cycle.py` | `_select_eligible_events()`: `COMPLETED`+`NEWS_ANALYSIS` matched; **duplicate exclusion is the load-bearing case** — a test-owned event whose `NEWS_ANALYSIS` task is `COMPLETED` AND already has a `CONTENT_GENERATION` task in **each** of `CREATED`/`RUNNING`/`COMPLETED`/`FAILED` (four separate test cases, not one) must be excluded every time; score threshold enforced (below-threshold excluded, at-threshold included — exact boundary tested); freshness cutoff enforced (technical-boundary framing, §3); **scan-limit enforced as its own dedicated test** — more real/test-owned `COMPLETED` candidates exist than `content_generation_scan_limit`, and the query must never return more rows than that limit even before score filtering runs (proves the "never load an unbounded number" guarantee directly, not only via the smaller `scan_limit` vs `batch_size` distinction); `run_content_cycle()` orchestration: sequential (no `gather`, static grep mirrors Phase 13's own check), one failed `run_content_generation_for_event()` call does not abort the remaining batch, notifier called only after a real `ContentDraft` exists (mocked `send_editorial_card`, asserted called with the right `draft`/`event`, and with `dry_run` set to whatever `settings.content_generation_dry_run` was at call time) |
| `tests/test_telegram_notifier.py` | `send_editorial_card()`: correct `EditorialInboxCard` field mapping from `ContentDraftRead`+`NewsEvent` (mirrors `_to_card()`'s own shape exactly — a direct equality/field-by-field comparison test, not merely "doesn't crash"); **`dry_run=True`**: `bot.send_message` is asserted **never called**, `NotificationOutcome.sent is False`, `rendered_html` equals what `render_editorial_card()` itself would produce for the same card (a direct, non-tautological comparison), and the dry-run payload is logged; **`dry_run=False`**: `bot.send_message` called exactly once with the correct `chat_id`/`html`/`parse_mode`, `NotificationOutcome.sent is True`; `CardTooLongError` and `TelegramAPIError` (live mode only) both caught, logged, returned as `sent=False`, never raised past the function — both are separately tested, not merged into one case |
| `tests/test_content_worker_main.py` | Enabled loop + interval, ordinary exception survival, cancellation during cycle, cancellation during sleep, disabled mode touches nothing (`assemble_ai_integration_layer` AND `create_bot` both asserted not called), disabled mode logs once, no bare/`BaseException` catch, starts without crashing on this platform, cycle-level infrastructure failure logs and continues — mirrors `tests/test_analysis_worker_main.py`'s own 9-test shape exactly, `assemble_ai_integration_layer`/`create_bot`/`run_content_cycle` all mocked at the module boundary |
| `tests/test_content_generation_integration.py` | Real Postgres (`independent_session_factory()`), `FakeLLMGateway`-backed real `CapabilityRegistry` (mirrors `tests/test_news_analysis_integration.py`'s own pattern), a mocked `Bot` (no real Telegram call, regardless of `dry_run` value — this test file never contacts Telegram either way): full chain — test-owned `NEWS_ANALYSIS COMPLETED` task (fresh, high score) → `run_content_cycle()` → real `CONTENT_GENERATION` task reaches `COMPLETED` → real `ContentDraft` row exists → `send_editorial_card` was called exactly once with matching data, run once with `dry_run=True` (asserts `sent is False`, mocked `bot.send_message` not called) and once with `dry_run=False` (asserts `sent is True`, mocked `bot.send_message` called once). A second test: a duplicate-guarded event (pre-existing `CONTENT_GENERATION` task of any status) is never touched by a second `run_content_cycle()` call. **Isolation**: same `_isolated_freshness_window`-style technique Phase 13 M3/M5 established, applied to `content_generation_freshness_cutoff_hours` instead — mandatory, not optional, given the M3 incident this exact class of bug already caused once |

**No live OpenAI/Telegram call in any automated test** — `FakeLLMGateway` for AI, a mocked/fake
`Bot` object for Telegram, in every test file above.

## 8. Live validation procedure (M7, human-authorized only, after M6 is green)

Structurally mirrors `docs/phase13_m7_live_validation_plan.md` exactly, extended by one new
concern (a real, external Telegram send) `docs/phase13_m7_authorization_check.md`
did not need to consider:

1. **Pre-flight (read-only)**: confirm `settings.editorial_chat_id` is set to a chat the human
   operator actually controls and has verified is private/non-public.
2. **Controlled artifact creation**: exactly as Phase 13 M7 — a fresh, synthetic, clearly-labeled
   `NewsSource`/`NewsEvent`, then a `NEWS_ANALYSIS` `EditorialTask` created and run to `COMPLETED`
   via the same direct `WorkflowRunner.run()` invocation Phase 13 M7 already proved — **except
   this time the synthetic content should be realistic enough to score above `content_generation_
   min_score`**, otherwise M7 cannot exercise the actual generation+notification path at all (the
   Phase 13 M7 artifact itself scored near-zero by design, since its own synthetic content was
   explicitly and repeatedly self-disclosing as fake — a new, separate synthetic event, still
   honestly labeled as a validation artifact but with genuinely analyzable content, is needed
   here).
3. **Baseline counts**: `EditorialTask` status counts, `CONTENT_GENERATION` task count,
   `ContentDraft` count — recorded before, diffed after (identical technique to Phase 13 M7 §7/§10).
4. **Live execution (generation)**: direct call to `run_content_generation_for_event(event_id,
   ...)` for the one recorded `event_id` — **not** `run_content_cycle()`'s own eligibility query,
   for the exact same structural-isolation reason Phase 13 M7 bypassed `run_analysis_cycle()`: no
   selection step means no possibility of an unrelated real event being processed.
5. **Notification, dry-run first (§0 clarification 3 — mandatory, not optional)**: call
   `send_editorial_card(bot, editorial_chat_id, draft, event, dry_run=True)` for this one
   `ContentDraft`. Inspect the returned `NotificationOutcome.rendered_html` and the logged
   `content_notification_dry_run` entry directly — this is the "explicit human verification of
   `editorial_chat_id`" the clarification requires: a human reads the exact payload that *would*
   be sent and confirms both the content and the target `chat_id` are correct **before** any live
   call is made. **Do not proceed to step 6 without this explicit confirmation.**
6. **Notification, live**: only after step 5's explicit confirmation, call `send_editorial_card(
   ..., dry_run=False)` for the same `ContentDraft`, to the same `editorial_chat_id`.
7. **Post-execution verification**: `CONTENT_GENERATION` task reaches `COMPLETED`; `ContentDraft`
   exists with real, sensible `title`/`body`/`hashtags`; `NotificationOutcome.sent is True`; message
   actually arrived in the target chat (human confirms by looking at Telegram — this is the one
   verification step that cannot be automated via a DB query); zero other
   `EditorialTask`/`ContentDraft` rows touched.
8. **Rollback/cleanup**: mirrors Phase 13 M7's own policy — preserve, clearly labeled, as the
   durable evidence M7 succeeded. The one residual risk the dry-run-first step (5) specifically
   exists to eliminate: if the wrong `chat_id` had been used, the sent Telegram message itself
   cannot be reverted by this codebase, only manually by the human — which is exactly why step 5
   is mandatory and step 6 may never be reached without it.

## 9. Explicitly not addressed by this plan

Everything Discovery §6 already excluded (approval workflow, buttons, autopublishing, memes,
images, new DB table, workflow-contract changes, event bus) remains excluded here too, unchanged.
Additionally, out of THIS plan's own scope specifically: the concurrent-multi-replica race
disclosed in §3; retry/backoff for failed Telegram sends; propagating the original `NEWS_ANALYSIS`
task's own `priority` into the new `CONTENT_GENERATION` task (uses `run_content_generation_for_
event()`'s own default, `TaskPriority.B`, unconditionally).

---

PHASE 14 IMPLEMENTATION PLAN READY FOR REVIEW
