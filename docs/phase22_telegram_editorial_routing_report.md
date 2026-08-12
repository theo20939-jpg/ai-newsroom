# PHASE 22 — TELEGRAM EDITORIAL ROUTING FOUNDATION

**Status: foundation only, not wired into any live/automated path.** No media generation, meme
pipeline, Telegraph pipeline, Instagram carousel, Reels generation, server deployment, Story
Memory/duplicate-suppression/story-update enforce, permanent worker start, or real Telegram send
was started or changed this phase.

## 1. Current Telegram architecture

- **Bot construction** (`bot/loader.py`): `create_bot()` builds a single aiogram `Bot` from
  `settings.telegram_bot_token`, HTML parse mode by default. Created on demand at application
  startup, not at import time - this module is always safely importable even without a configured
  token.
- **Interactive commands** (`bot/handlers/*.py` - `news.py`, `digest.py`, `settings.py`,
  `status.py`, `start.py`, plus the media-preview handlers `image_preview.py`/`meme_preview.py`):
  registered on an aiogram `Dispatcher`/`Router` (`bot/handlers/__init__.py`), reply via
  `message.answer(...)`.
- **Automated content delivery** (the production path this phase does not touch):
  `worker/content_cycle.py` drives one automation cycle - for each completed `ContentDraft`, it
  calls `services/telegram_notifier.py::send_editorial_card()` (or, when an eligible image
  candidate exists, `services/image_preview_notifier.py::send_news_with_image_preview()`), always
  targeting the single `settings.editorial_chat_id` (currently configured: `5507703201`, real
  value, unchanged this phase). `send_editorial_card()` calls `bot.send_message(chat_id, html,
  parse_mode=HTML, reply_to_message_id=...)` - `reply_to_message_id` is used for Story-thread
  replies (Phase 18.10/19's own reply-routing work, `services/story_telegram_delivery.py`), a
  structurally different mechanism from a forum `message_thread_id`.
- **Delivery-adjacent entities that exist but are not a fit for this phase's routing concept**:
  `database/models/telegram_channel.py::TelegramChannel` (a dormant, never-referenced-outside-
  `__init__.py` model from early planning, modeling a distinct *channel*, not a topic inside one
  supergroup); `database/models/story_telegram_delivery.py` (tracks reply-thread delivery per
  Story, unrelated to content-type/destination routing).
- **`ContentDraft.type`** (`database/models/content_draft.py::ContentType`): `POST`, `SHORT`,
  `ANALYSIS`, `MEME`, `VIDEO_SCRIPT` - a real, native Postgres enum column. This describes *draft
  format*, a different axis from *delivery destination* (this phase's `EditorialDestination`) -
  the two are not interchangeable and no automatic mapping between them exists or was built (§3).

## 2. Investigation results

**1. How are Telegram messages currently sent?** Exclusively through `bot.send_message()` /
`message.answer()` calls inside `services/telegram_notifier.py`, `services/
image_preview_notifier.py`, and the `bot/handlers/*.py` command handlers - all targeting either
`settings.editorial_chat_id` (automated delivery) or the chat a command was issued from
(interactive commands). No forum-topic-aware send exists anywhere in production code today.

**2. Is forum topic support already implemented?** No, for *outbound* routing. `grep -rn
message_thread_id` across the entire repository (excluding this phase's own new files) matches
**zero production code** - only documentation. A real, thorough Phase 11 investigation
(`docs/phase11_telegram_topic_diagnostic_closure.md`, three escalating diagnostic passes down to a
raw-HTTP-versus-parsed-model capture) *did* investigate topic support - but for a structurally
different mechanism: propagating *inbound* topic context (`message.is_topic_message`/
`message.message_thread_id` on an incoming Update, so a command reply lands back in the same topic
it was issued from). That investigation's proven, closed root cause was upstream: for the
reproduced case, `api.telegram.org`'s own raw HTTP response did not contain `message_thread_id`/
`is_topic_message` at all - a limitation confirmed to originate entirely outside this repository's
code, with an explicit ban on any workaround for it. **This limitation does not apply to or block
Phase 22**: Phase 22 routing never reads topic identity from an incoming Update - it sets
`message_thread_id` on an *outbound* send from *pre-configured settings* (§6), a mechanism the
Phase 11 investigation never touched and that has no dependency on Telegram supplying inbound
topic fields at all. This is stated explicitly, not assumed, because the phase brief itself warns
"do not repeat the previous Telegram topic bug" - the previous bug and this phase's mechanism are
different enough that repeating it is not structurally possible here, and the new regression tests
(§8) prove the outgoing call shape directly rather than relying on that argument alone.

**3. Where is the safest routing point?** A new, standalone send boundary
(`services/telegram_routing.py::send_to_editorial_destination()`), parallel to - not replacing -
`send_editorial_card()`. It resolves an explicitly-supplied `EditorialDestination` to a
`(chat_id, topic_id)` target via settings, then calls `bot.send_message()` directly. This is safest
because it introduces zero coupling to `ContentDraft` persistence, zero schema change, and zero
change to the existing, already-in-production `editorial_chat_id`/`send_editorial_card()` path -
acceptance criterion E ("existing Telegram behavior preserved") is satisfied by construction, not
by a separate regression pass.

**4. Should routing happen before or after ContentDraft creation?** After, and out-of-band:
routing is a delivery-time concern only. `EditorialDestination` is passed explicitly to
`send_to_editorial_destination()` by its caller - it is **not** read from or written to
`ContentDraft`, and no migration/column was added this phase. The phase brief's own §7 example
(`ContentDraft: {destination: NEWS}`) is illustrative of the *concept*, not a literal schema
requirement - "no automatic decision making" (§7 of the brief) means nothing yet computes a
destination for a real draft, so persisting an always-null/always-manually-set column now would be
premature schema surface with no consumer. Revisit once a real caller (manual admin action or a
future, separately-authorized auto-classifier) needs to persist its choice.

**5. Does current architecture already have delivery entities?** Two exist, neither fits (§1) -
confirmed by direct read, not assumed. Building one new, small, config-driven module was the
correct, minimal choice - not a redesign of either existing entity.

## 3. Chosen routing design

```
EditorialDestination (schemas/editorial_route.py)
        |
        v
resolve_route()  (services/telegram_routing.py - settings-driven lookup, one dict, no if/else chain)
        |
        v
RouteTarget(chat_id, topic_id | None)
        |
        v
send_to_editorial_destination()  ->  bot.send_message(chat_id, text, message_thread_id=topic_id)
```

`EditorialDestination` (`str, enum.Enum`): `NEWS`, `MEME`, `TELEGRAPH`, `INSTAGRAM`, `REELS` -
exactly the five topics named in the target NINJA NEWSROOM structure, no speculative additions.
`parse_editorial_destination(value: str) -> EditorialDestination | None` is the safe string->enum
lookup for any future caller that only has a raw string (e.g. a not-yet-added `ContentDraft`
column) - never raises.

`_DESTINATION_TOPIC_SETTING: dict[EditorialDestination, str]` maps each destination to the *name*
of its settings attribute (`"news_topic_id"`, etc.) - not a topic id value. No topic id is
hardcoded anywhere in this module or in any caller; adding a sixth destination later means one new
enum member + one new settings field + one new dict entry, never a new `if destination == ...`
branch.

`resolve_route(destination) -> RouteTarget | None`: pure, zero I/O. Returns `None` only when
`settings.newsroom_telegram_chat_id` itself is unconfigured (no chat at all - no safe target
exists for any destination). A destination whose own topic id is unset still resolves
successfully, to `RouteTarget(chat_id=..., topic_id=None)` - sending to the chat's root is a
legitimate, deliberate outcome, not a misconfiguration.

`send_to_editorial_destination(bot, destination, text, *, dry_run=True, parse_mode=HTML) ->
RoutingOutcome`: the one send boundary. `dry_run` defaults to `True` (mirrors
`send_editorial_card`'s own established safe default - a caller that forgets to pass
`dry_run=False` can never accidentally send). `RoutingOutcome` mirrors `NotificationOutcome`'s own
directly-inspectable-result shape (`destination`, `chat_id`, `topic_id`, `sent`, `reason`,
`message_id`) - `reason` is one of `"dry_run"`, `"unknown_destination"`,
`"unconfigured_destination"`, `"telegram_api_error"`, or `None` (only when `sent=True`).

## 4. Files changed

**Created**:
- `schemas/editorial_route.py` - `EditorialDestination` enum, `parse_editorial_destination()`.
- `services/telegram_routing.py` - `RouteTarget`, `resolve_route()`, `RoutingOutcome`,
  `send_to_editorial_destination()`.
- `tests/test_telegram_editorial_routing.py` - 14 tests (§8).
- `docs/phase22_telegram_editorial_routing_report.md` - this report.

**Modified**:
- `core/config.py` - 6 new optional settings fields (§5), all defaulting to `None`. Nothing else
  in this file changed.

**Not touched**: `bot/loader.py`, `bot/handlers/*.py`, `services/telegram_notifier.py`, `services/
image_preview_notifier.py`, `worker/content_cycle.py`, `database/models/content_draft.py`, every
Story Memory/Fact Safety module from Phases 20/21. No migration created or applied (zero schema
change - `EditorialDestination` is never persisted this phase). No `.env`/`.env.example` edit.

## 5. Configuration changes

Investigated the existing pattern first (per the brief's own §11 instruction): `editorial_chat_id:
int | None = None` is a real precedent already in `core/config.py` - a Settings field added with a
safe `None` default, **never added to `.env`/`.env.example`** (confirmed: neither file mentions
it) - the real environment only picks it up if a deployment's own `.env` sets
`EDITORIAL_CHAT_ID=...`, pydantic-settings' default case-insensitive env-var matching. Phase 22
follows this exact precedent, not a new pattern:

```python
newsroom_telegram_chat_id: int | None = None
news_topic_id: int | None = None
meme_topic_id: int | None = None
telegraph_topic_id: int | None = None
instagram_topic_id: int | None = None
reels_topic_id: int | None = None
```

`newsroom_telegram_chat_id` is deliberately **separate** from `editorial_chat_id` - the NINJA
NEWSROOM supergroup this phase targets is a distinct destination from the existing, already-in-
production single-topic delivery path, which is left completely untouched. Field names map to env
vars `NEWSROOM_TELEGRAM_CHAT_ID` / `NEWS_TOPIC_ID` / `MEME_TOPIC_ID` / `TELEGRAPH_TOPIC_ID` /
`INSTAGRAM_TOPIC_ID` / `REELS_TOPIC_ID` by pydantic-settings' own default rule - matching the
brief's own §11 proposed naming exactly. **Neither the real `.env` nor `.env.example` was edited**
- confirmed via `git status --short .env .env.example` (empty) - matching `editorial_chat_id`'s
own precedent of living in code only until a real deployment chooses to set it.

## 6. Topic support implementation

`send_to_editorial_destination()` always passes `message_thread_id=route.topic_id` explicitly to
`bot.send_message()` (never via `**kwargs` unpacking - an earlier draft used conditional kwargs
injection to omit the parameter entirely for a plain-chat destination, but Mypy correctly flagged
the `**dict[str, object]` unpacking against aiogram's precisely-typed `send_message()` signature;
passing `message_thread_id=None` explicitly is functionally identical - aiogram's own signature
already defaults this parameter to `None`, meaning "no thread" - and keeps the code fully
type-checked). Correct behavior, verified directly by test assertions on the recorded mock call
(not merely inferred):

- **Forum topic destination** (`topic_id` configured, e.g. `NEWS -> 11`): `bot.send_message(...,
  message_thread_id=11)` - a real topic id reaches the call.
- **Normal/unconfigured destination** (`topic_id` is `None`): `bot.send_message(...,
  message_thread_id=None)` - never a stray topic id, matching "send without thread ID."

## 7. Security considerations

- **No hardcoded topic IDs**: every id (`chat_id` and all five `topic_id`s) is read from
  `core.config.settings` at call time via `_DESTINATION_TOPIC_SETTING`'s name-lookup indirection -
  grepping this module or any caller for a literal integer topic id finds none.
- **No accidental production sends during testing**: every test in `tests/
  test_telegram_editorial_routing.py` uses `unittest.mock.AsyncMock()` as `bot` - the same,
  already-established convention `tests/test_telegram_notifier.py` uses - never a real aiogram
  `Bot`, never a real `TELEGRAM_BOT_TOKEN`, never network I/O of any kind, in either `dry_run=True`
  or `dry_run=False` mode (the mock has no transport to reach).
- **Safe default**: `send_to_editorial_destination()`'s `dry_run` parameter defaults to `True` -
  identical to `content_generation_dry_run`'s own existing safe-default precedent
  (`core/config.py`) - a caller that omits the argument can never accidentally send live.
- **Fail-safe on misconfiguration**: an unrecognized destination string, or a recognized
  destination with no chat id configured, both resolve to a logged, returned `sent=False` outcome
  - never an exception that could crash a calling task, and never a Telegram call.
- **Fail-safe on live-send failure**: `TelegramAPIError` is caught and returned, never raised past
  this function - mirrors `send_editorial_card`'s own established per-call error-handling
  discipline, so one bad destination/send can never abort a caller's batch loop.
- **Not wired into any live/automated path**: `send_to_editorial_destination()` is called from
  nowhere in `worker/content_cycle.py`, `capabilities/executor.py`, or any handler - the only
  callers that exist are this phase's own tests. This is itself the strongest production-safety
  property of this phase: even a latent bug in the new module cannot affect the real, currently
  operating delivery path, because nothing currently invokes it.

## 8. Tests

`tests/test_telegram_editorial_routing.py`, 14 tests, all passing:

- 5 pure unit tests for `parse_editorial_destination()`/`resolve_route()` (recognizes all 5
  destinations; rejects unknown/empty/wrong-case strings; `None` only when chat id is
  unconfigured; an unconfigured per-destination topic id is a valid target, not an error; each
  destination maps to its own configured topic).
- **CASE 1** (`test_case_1_news_draft_sent_to_news_topic`): exact `bot.send_message` call
  assertion - `chat_id`, text, `parse_mode=HTML`, `message_thread_id=11` (the NEWS topic).
- **CASE 2** (`test_case_2_meme_draft_sent_to_meme_topic`): `message_thread_id=22` (the MEME
  topic).
- **CASE 3**: two tests - an unrecognized destination string (`"PODCAST"`) and a recognized
  destination with no chat id configured - both assert `bot.send_message.assert_not_called()` and
  a specific `reason`.
- **CASE 4** (`test_case_4_forum_topic_delivery_includes_message_thread_id`): the recorded call's
  `message_thread_id` kwarg equals the configured topic id.
- **CASE 5** (`test_case_5_normal_chat_delivery_omits_message_thread_id`): the recorded call's
  `message_thread_id` kwarg is `None` when the destination's own topic id is unconfigured - never
  a stray topic id.
- **CASE 6**: two tests - `dry_run` defaulting to `True` never calls `bot.send_message` even
  without an explicit argument; an explicit assertion that every test in this file uses
  `AsyncMock`, never a real aiogram `Bot`.
- One additional test for live-send failure handling (`TelegramAPIError` caught, never raised,
  `reason="telegram_api_error"`) - not one of the 6 named cases but the natural regression guard
  for `send_editorial_card`'s own established error-handling convention, reused here.

## 9. Regression results

Ran the full combined Telegram/workflow/ContentDraft/Phase 20/Phase 21 test set:

```
python -m pytest tests/ -k "telegram or workflow or content_draft or phase20 or phase21 or
  fact_safety or story_memory or story_delta or story_suppression or editorial_content_type or
  story_identity or human_reviewed_calibration or bot_router or docker_compose" -q
550 passed, 5 skipped, 7 failed, 1 error (2514 deselected)
```

All 7 failures + 1 error are **pre-existing, confirmed via `git stash` to reproduce byte-
identically on fully unmodified code** (not caused by this phase's changes):
`test_content_draft_service.py::test_content_draft_is_durable_to_a_genuinely_independent_
connection`, `test_fact_safety.py::test_off_mode_leaves_quality_step_result_completely_unchanged`,
`test_fact_safety.py::test_shadow_mode_enriches_quality_result_and_detects_unsupported_claim`,
`test_phase10_workflow_integration.py::test_content_generation_reaches_completed_in_exact_step_
order`, `test_run_content_generation.py` (3 tests), and `test_content_cycle_story_delivery.py`'s
teardown error. Root cause is consistent across all of them and was already identified during
Phase 21's own regression pass: an accumulated, real local Postgres test database carrying leftover
rows (`AIExecution` counts in the thousands; `news_events` rows still referenced by
`news_event_article_acquisitions`/`content_draft_editorial_plans` at teardown time) from the many
manual/replay scripts run against this environment across this session - not scoped to any
individual test's own transaction, and unrelated to any code this phase (or Phase 21) touched. This
is a pre-existing local-environment condition, not a code regression - each failing test's own
assertions are about the same real-DB row-count/FK-cleanup issue, never about anything this phase
added.

Ruff (`schemas/editorial_route.py`, `services/telegram_routing.py`, `tests/
test_telegram_editorial_routing.py`, `core/config.py`): **all checks passed**. Mypy (same three
source files - the test file is not type-checked, matching this project's existing Mypy scope):
**Success: no issues found in 3 source files**.

## 10. Known limitations

1. **Not wired into any live path** - by design this phase (§7's own strongest safety property,
   also a limitation: nothing in production can use this yet). Wiring it into
   `worker/content_cycle.py` or a future admin/moderation flow is explicitly deferred, matching the
   brief's own "only create the routing capability" scope.
2. **No automatic destination decision-making** - `EditorialDestination` must be supplied by the
   caller; no classifier, heuristic, or AI decision exists or was requested this phase (explicitly
   out of scope per the brief's §7/§8).
3. **No persisted destination on `ContentDraft`** - no migration, no schema change (§2 answer 4).
   A future phase that wants to *record* a chosen destination durably will need to add this,
   separately authorized.
4. **No admin preview/moderation UI** - the brief's §8 explicitly scoped this to a *future*
   workflow ("Publish"/"Edit"/"Reject" buttons); nothing of that kind was built this phase.
5. **Real NINJA NEWSROOM chat/topic IDs are not configured** - every new setting defaults to
   `None`; the real `.env` was not touched, so this capability is inert in the current deployment
   until a human deliberately configures it (a separate, explicit, future step, not part of this
   phase's scope).
6. **Pre-existing local-environment test pollution** (§9) continues to grow across this session's
   many manual/replay runs against the same local Postgres instance - worth a dedicated cleanup in
   a future, separately-scoped maintenance pass; does not affect the correctness of anything shipped
   this phase.

## 11. Next recommended phase

Per the brief's own explicit STOP condition, no further work (media, memes, Telegraph, Instagram,
Reels, server deployment) was started this phase. **PHASE 23 — SERVER DEPLOYMENT + LIVE NEWSROOM
PREPARATION** is the user-designated next phase, pending review of this report.

---

**STOP condition met.** Waiting for review before Phase 23.
