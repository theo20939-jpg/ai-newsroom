# Phase 11 — Telegram Delivery & Editorial Inbox Discovery

**Status: discovery document only.** No production code, test, migration, or model was modified.
Current repository source is treated as authoritative; where older product documents disagree,
this is stated explicitly, not smoothed over.

---

## 1. Executive Summary

**FACT**: the Telegram bot layer (`bot/`) is pure scaffolding — five commands, every one a
hardcoded placeholder string, zero database access, zero service calls, zero interactive UI
(no keyboards, no callbacks, no FSM, no webhook). **FACT**: `ContentDraft` already carries
everything needed for a useful, read-only editorial card (title/body/hashtags) with zero schema
change, reachable via two existing FK hops (task_id → EditorialTask.event_id → NewsEvent) using
the same manual-`session.get()` pattern already established throughout Phase 9/10. **FACT**: a
real `User` model with `telegram_id`/`role` (`OWNER`/`ADMIN`/`SMM_MEMBER`/`VIEWER`)/`permissions`
already exists but is wired into nothing — no middleware, no handler, no service references it.
**FACT**: no delivery/idempotency marker, no editorial-approval state, no destination-chat
configuration, and no meme/image-generation infrastructure exist anywhere in the repository.

**RECOMMENDATION**: Phase 11's MVP should be a **pull-mode, read-only editorial inbox** (Option A,
§16/§17) — a `/drafts` (or extended `/news`) command that queries pending `ContentDraft` rows and
renders them as cards, using the dormant `User`/`UserRole` model for the first real authorization
check this repository will ever perform. This requires zero schema change, zero new production
service beyond one query + one formatter, and zero scheduler. Approve/Reject/Rework are real,
architecturally non-trivial questions (§9–§11) that should NOT be bundled into this same MVP.

---

## 2. Current Telegram Architecture

**FACT** — concrete file/module map, `bot/`:

| Concern | File | State |
|---|---|---|
| Bootstrap | `bot/main.py` | `python -m bot.main` — creates `Bot`/`Dispatcher`, includes the root router, calls `dp.start_polling(bot)`. **Long-polling only** — no webhook code exists anywhere (`grep -rn "webhook"` across all `.py` files returns nothing). |
| Bot/Dispatcher factory | `bot/loader.py` | `create_bot()` reads `settings.telegram_bot_token`, raises `RuntimeError` if unset (fail-fast, not lazy-degraded); `DefaultBotProperties(parse_mode=ParseMode.HTML)` — **HTML is the default parse mode for every outgoing message**, not Markdown. `create_dispatcher()` returns a bare `Dispatcher()`, no injected dependencies. |
| Routers | `bot/handlers/__init__.py` | One root `Router(name="root")` aggregating five per-command sub-routers (`start`, `news`, `digest`, `status`, `settings`), each its own file/router instance. |
| Handlers | `bot/handlers/{start,news,digest,status,settings}.py` | Five files, **structurally identical**: one `Router`, one `PLACEHOLDER_TEXT = "This functionality will be implemented in the next development phases."` constant, one handler that does `await message.answer(PLACEHOLDER_TEXT)` and nothing else. |
| Commands | `CommandStart()` (`/start`), `Command("news")`, `Command("digest")`, `Command("status")`, `Command("settings")` | All five registered; none does real work (§3). |
| Keyboards | `bot/keyboards/__init__.py` | Docstring only: `"Telegram keyboards package, reserved for future development phases."` — **empty**. |
| Middleware | `bot/middlewares/__init__.py` | Docstring only: `"Telegram middlewares package, reserved for future development phases."` — **empty**. No auth middleware, no logging middleware, nothing. |
| Telegram integration/service wrappers | none | No `integrations/telegram/` directory exists (`find integrations -iname "*telegram*"` finds only `integrations/sources/telegram_source.py`, which is a **completely different system** — see below). No `services/telegram_*.py` file exists. |
| Configuration | `core/config.py:44` | `telegram_bot_token: SecretStr | None = None` — the only Bot-API-relevant setting. No `chat_id`, no `editorial_chat_id`, no destination config of any kind exists anywhere in `Settings`. |
| Send/edit methods | none beyond aiogram's own `message.answer()` | No custom send/edit wrapper exists; every handler calls the raw aiogram `Message.answer()` directly. |
| Callback-query handling | **none** | `grep -rln "callback_query\|CallbackQuery"` across the entire repo returns zero files. No `@router.callback_query(...)` handler exists anywhere. |
| User/role/permission logic | model exists, **unused** | `database/models/user.py` defines `User`/`UserRole` (`OWNER`/`ADMIN`/`SMM_MEMBER`/`VIEWER`) with `telegram_id` (unique `BigInteger`) and `permissions` (JSON) — but `grep -rln "from database.models.user\|UserRole"` finds only the model file itself and `database/models/__init__.py`'s export. **Zero consumer anywhere.** |
| Chat/thread/topic support | **none** | `grep -rln "thread_id\|message_thread"` across all `.py` files returns zero results. No forum/topic support exists in any form. |

**INFERENCE**: this is Phase 3's original scaffolding (per `CLAUDE.md`'s own roadmap: "Phase 3
Telegram Bot"), never revisited since — every handler's identical placeholder text and the
`"reserved for future development phases"` docstrings are the scaffolding's own, explicit
self-description, not something this discovery is inferring loosely.

**FACT — a second, unrelated Telegram system exists**: `integrations/sources/telegram_source.py`
is a **Telegram Client API** (Telethon) adapter for the Source Collector — it *reads* public
channels as a news source. Its own docstring is explicit: *"This is completely separate from the
Telegram Bot API used by bot/ (aiogram, TELEGRAM_BOT_TOKEN) - different credentials, different
client, no shared imports between the two."* `Settings.telegram_api_id`/`telegram_api_hash`/
`telegram_session_string` belong to this system, not the bot. **Phase 11 must not confuse or
couple these two systems** — this discovery only concerns the Bot API side (`bot/`).

---

## 3. Existing Bot Commands

All five commands independently verified by direct read (`bot/handlers/*.py`, above). Every one
is **structurally identical**:

| Command | Handler file | DB access | Service calls | Output | Placeholder or production? | Exposes NewsEvent/EditorialTask/ContentDraft? |
|---|---|---|---|---|---|---|
| `/start` | `bot/handlers/start.py:11-14` | none | none | `message.answer(PLACEHOLDER_TEXT)` | **Placeholder** | No |
| `/news` | `bot/handlers/news.py:11-14` | none | none | `message.answer(PLACEHOLDER_TEXT)` | **Placeholder** | No |
| `/digest` | `bot/handlers/digest.py:11-14` | none | none | `message.answer(PLACEHOLDER_TEXT)` | **Placeholder** | No |
| `/status` | `bot/handlers/status.py:11-14` | none | none | `message.answer(PLACEHOLDER_TEXT)` | **Placeholder** | No |
| `/settings` | `bot/handlers/settings.py:11-14` | none | none | `message.answer(PLACEHOLDER_TEXT)` | **Placeholder** | No |

**OPEN QUESTION** (genuinely undecidable from source, a real product/naming choice): should Phase
11 extend `/news` (name already suggests "editorial content") or `/digest` (also plausible), or
introduce a new, purpose-named command (e.g. `/drafts` or `/inbox`)? Nothing in the current code
or product docs commits to either — this is a Decision Resolution question, not resolved here.

---

## 4. Current ContentDraft Data Path

**FACT** (`database/models/content_draft.py`, re-read this session): `ContentDraft` columns —
`id`, `task_id` (FK → `editorial_tasks.id`, `nullable=False`), `type` (`ContentType`: `POST`/
`SHORT`/`ANALYSIS`/`MEME`/`VIDEO_SCRIPT`), `title`/`body` (`Text | None`), `hashtags`
(`JSON | None`), `version` (`int`, always `1` — `services/content_draft_service.py:90`, never
incremented anywhere in this repository), `status` (free-text `String | None` — the model's own
comment says *"not enumerated in the project documentation"*), `created_at`/`updated_at`.

**FACT**: no `relationship()` is declared anywhere in `database/models/*.py` (`grep -n
"relationship("` across all model files returns nothing) — every cross-table link in this
repository, including `ContentDraft.task_id`, is a raw FK column, traversed by manual
`session.get()`/`select()` calls, exactly the pattern `CapabilityExecutor`/`ContentDraftService`
already use. Phase 11 would follow the identical convention, not invent a new one.

**Answer: YES — a useful Telegram editorial card can be built from current persisted state with
zero schema change.** Exact data path, all fields already present, no migration:

```
ContentDraft (title, body, hashtags, created_at, status)
    task_id
        ↓
EditorialTask.event_id
        ↓
NewsEvent (title, category, url, published_at)
```

Concretely: `draft = await session.get(ContentDraft, draft_id)` →
`task = await session.get(EditorialTask, draft.task_id)` →
`event = await session.get(NewsEvent, task.event_id)` — three simple lookups, no join syntax even
required (though a single `select(...).join(...)` would also work), mirroring
`CapabilityExecutor._build_context()`'s own two-hop lookup pattern exactly
(`capabilities/executor.py:69-74`).

**What is available through this path**: draft title/body/hashtags (the generated content
itself); the event's original title, category (`EventCategory` enum — `AI`/`GADGETS`/`TECH`/
`STARTUPS`/`SOFTWARE`/`HARDWARE`/`CYBERSECURITY`/`UNKNOWN`), source URL (`NewsEvent.url`,
nullable), and `published_at`. **Source name** (e.g. "TechCrunch") requires one further hop to
`NewsSource` (`NewsEvent.source_id` → `NewsSource.name`) — also zero-migration, same pattern.

**What is NOT directly available on `ContentDraft` itself**: the Quality Capability's editorial
judgment (`passed`/`issues`) and the Scoring Capability's score (`score`/`rationale`, only
produced by `NEWS_ANALYSIS`, a workflow `CONTENT_GENERATION` never runs) live inside
`EditorialTask.workflow`'s `step_results` JSON blob, not copied onto `ContentDraft`. Reachable
(same task_id hop, parse `workflow["step_results"]` for the `"quality"` entry's `result` dict),
but requires JSON-blob parsing, not a plain column read — see §8.

---

## 5. Delivery Ownership Analysis

**FACT (governing precedent)**: Phase 10's own Contract §7 is unambiguous and already
mechanically enforced (a test proves no file under `capabilities/` imports `ContentDraft`):
*"Capabilities MUST NOT create, update, or hold any reference to a ContentDraft row... The only
component ever authorized to create a ContentDraft row is ContentDraftService."* `WorkflowRunner`
and `CapabilityExecutor` are both explicitly barred from this responsibility, and Phase 10's own
`scripts/run_content_generation.py` treats `ContentDraftService`'s own failure as a *disclosed,
survivable, non-fatal* gap — the workflow's `COMPLETED` status is never retroactively undone by a
downstream persistence failure.

**INFERENCE, directly by analogy to that precedent**: Telegram delivery is even further downstream
than `ContentDraft` persistence, and the same isolation discipline applies with *at least* equal
force. A Telegram delivery failure must not be allowed to gate, retry-block, or invalidate either
`TaskStatus.COMPLETED` or the `ContentDraft` row — exactly the way `ContentDraftService`'s own
failure already doesn't invalidate `TaskStatus.COMPLETED`.

**Ownership model comparison**:

| Model | Separation of concerns | Transaction boundary | Failure isolation | Retry | Testability | aiogram coupling | AI workflow depends on Telegram? |
|---|---|---|---|---|---|---|---|
| **A. `WorkflowRunner` sends** | Violates Phase 5's frozen engine-mechanics boundary directly | Would need to happen inside/adjacent to the workflow's own commit | **Fails the isolation discipline outright** — a `WorkflowRunner` that can be blocked by Telegram violates the whole point of §5's finding above | N/A, forbidden | Would require `WorkflowRunner`'s frozen tests to grow Telegram fakes | Total — pollutes a frozen Phase 5 file with aiogram | **Yes — exactly the coupling to avoid** |
| **B. `ContentDraftService` sends** | Blurs "persist a row" with "deliver a message" — two different concerns Phase 10 deliberately kept apart from Capabilities | Same session/transaction as the draft's own commit, or a second one immediately after | Better than A, but still couples a frozen-scope Phase 10 file to a new external dependency | Unclear | Would require `ContentDraftService`'s existing, small, single-purpose test suite to grow Telegram fakes | Direct | Partial — depends on whether the caller treats it as fatal |
| **C. A separate Editorial Inbox / Delivery reader, invoked independently, reading already-persisted `ContentDraft` rows** | **Clean** — a new, narrowly-scoped component, structurally analogous to how `ContentDraftService` itself is a narrowly-scoped addition on top of `WorkflowRunner` | None needed — read-only queries against already-committed data | **Complete** — this component can fail, retry, or simply not run yet, and nothing about the AI pipeline is affected, since it never touches `EditorialTask`/`ContentDraft` write paths | Freely retryable, since it's idempotent-by-design if pull-based (§13) | Fully unit-testable against a fake `PromptRepository`-style read layer, no aiogram coupling needed for the data-access half | Isolated to a thin presentation layer only | **No — fully decoupled**, matching the Phase 10 precedent's own spirit |
| **D. A worker/job sends** | Same benefits as C, plus a process-lifecycle question (what runs it, how often) | N/A, read-only | Same as C | Depends on worker design | Same as C, plus worker-scheduling tests | Isolated | No |
| **E. The bot retrieves only on request (pull)** | Simplest possible — the bot handler itself *is* the reader, no separate service needed for an MVP this small | None needed | Complete, trivially — nothing runs until a human asks | N/A — no delivery to retry, only a query | Directly testable as a bot handler test (aiogram's own test conventions, if any — see §15) | Confined to the handler | No |

**RECOMMENDATION**: **Model E for the MVP** (the bot handler reads `ContentDraft` directly, on
request), which is a specific, minimal instance of the general Model C pattern (a read-only
component decoupled from the write path) — not Model A or B, both of which would violate Phase
10's own established isolation discipline. Model D (a worker) is unnecessary complexity for an
MVP that has no push requirement (§6). This keeps `WorkflowRunner`, `CapabilityExecutor`,
`CapabilityRegistry`, `LLMGateway`, `PromptRepository`, and `ContentDraftService` **entirely
untouched** — Phase 11 adds a new, thin, additive read/presentation layer only.

---

## 6. Push vs Pull vs Hybrid

| | Architecture complexity | Scheduler required? | Reliability | Duplicate-delivery risk | UX | MVP suitability | Compatible with current code? |
|---|---|---|---|---|---|---|---|
| **Push** (auto-send on `ContentDraft` creation) | Requires a new trigger point — either inside `ContentDraftService`'s caller (Model B/A above, already rejected) or a separate poller watching for new rows, which is itself a lightweight scheduler | **Yes**, in the "poller" variant — and Phase 10's Contract explicitly excludes "any scheduler or automatic-execution mechanism" (§2) as out of scope, a boundary this discovery has no evidence has been lifted | Depends entirely on retry/idempotency machinery that doesn't exist yet (§13) | **High**, without new delivery-state persistence (§13) | Best — zero-effort discovery for the SMM team | Poor — the highest-complexity option, requiring the most net-new architecture | **No** — would require either violating §5's ownership finding or introducing the scheduler Phase 10 explicitly deferred |
| **Pull** (`/command` retrieves pending drafts) | Minimal — one query, one formatter, one handler | **No** | High — nothing to retry, a query either succeeds or the user tries again like any other command | **None** — reading is naturally idempotent; nothing is "sent" to duplicate | Requires the user to remember to check | **Excellent** — smallest possible working slice | **Yes** — fits the existing command-router pattern exactly |
| **Hybrid** (push new, pull for history) | Push's complexity plus pull's | Yes, for the push half | Push half inherits push's reliability problem | Push half inherits push's risk | Best of both | Reasonable **post-MVP** target, not MVP | Partially — the pull half is trivial, the push half is not |

**RECOMMENDATION**: **Pull for Phase 11 MVP.** This is not merely a preference — it is the only
option of the three that requires **no scheduler**, matching Phase 10's own explicit,
still-standing exclusion, and it is the only option requiring no new delivery-state persistence
(§13 elaborates why).

---

## 7. Telegram Destination Model

**FACT**: no destination-addressing support of any kind is currently configured or persisted.
`grep -n "telegram\|chat_id\|editorial"` across `core/config.py` finds only `telegram_bot_token`
(auth) and the unrelated Telethon settings (§2). No `chat_id`, `editorial_chat_id`, or any
multi-chat/multi-tenant concept exists in `Settings`, in any model, or in any migration.

**FACT**: `grep -rn -i "separate folder\|forum\|topic"` across `docs/*.md` surfaces only two
unrelated hits — `docs/06_Functional_Specification.md:902` and
`docs/08_Database_Schema_Data_Models.md:1079` — both are a `NewsEvent`'s **editorial content
topic** (e.g. `"topic": "AI hardware"`), not a Telegram forum/topic feature. **No product document
in this repository ever specified a Telegram forum-topic or "separate folder" delivery mechanism**
— any such idea, if it exists, was only ever product-language from a conversation outside this
repository's own documentation, never translated into a technical requirement here. This
discovery states this precisely per instruction, rather than inventing a mapping that doesn't
exist.

**RECOMMENDATION — smallest safe destination model for Phase 11 MVP**: since the pull model (§6)
means the bot only ever replies inside the chat the command was issued from
(`message.chat.id`, already available on every aiogram `Message` for free), **no new destination
configuration is needed at all** for a pull-mode MVP. The "destination" is simply wherever the
SMM team member typed the command — private chat or a group they're already in. A dedicated
"editorial chat" concept (a fixed `chat_id` setting) only becomes necessary if/when Phase 11 later
adds push delivery, and even then, a single fixed chat ID (not a forum topic, not
multi-tenant routing) would be the minimal next step — not designed further here, per instruction.

---

## 8. Editorial Card UX

**FACT**: `bot/loader.py:24` sets `DefaultBotProperties(parse_mode=ParseMode.HTML)` as the bot's
default — **HTML, not Markdown**, is this repository's established convention. Any Phase 11 card
should follow this existing default rather than introducing Markdown parsing.

**FACT**: no message-formatting helper, no length-splitting utility, and no escaping utility
exists anywhere in `bot/` — every current handler sends a short, static, pre-safe string. Phase 11
would be the first place in this repository to format dynamic (LLM-generated) content into HTML,
meaning **HTML-escaping AI-generated text before sending is a new concern Phase 11 must handle
carefully** (Telegram's HTML mode requires escaping `<`, `>`, `&` in any literal text, since
`copywriting`'s output is free-form LLM text that could coincidentally contain characters HTML
would misinterpret).

**INFERENCE (general Telegram Bot API constraint, not repository-specific)**: Telegram messages
are capped at 4096 characters. `CopywritingCapability`'s prompt (`prompts/copywriting/v1.yaml`/
`v2.yaml`) instructs *"Keep the title concise and the body suitable for a short social post"* —
by design intent the body should comfortably fit in one message, but nothing in the schema
enforces a hard length ceiling (`ContentDraft.body` is an unbounded `Text` column) — a Phase 11
implementation should defensively truncate or split, not assume the prompt's soft guidance always
holds.

**FACT**: inline keyboards are supported by the installed `aiogram` library (a general library
capability) but **zero keyboard is currently built anywhere** (`bot/keyboards/__init__.py` is an
empty placeholder) — Phase 11 (or a follow-up) would be the first to actually construct one.
Since `bot/handlers/__init__.py` already establishes 1 router per command, a first
`callback_query` handler would be entirely new code, not an extension of anything existing.

**Recommended MVP card shape**, built only from data already confirmed available in §4 (no
score/quality data, since that requires the extra JSON-parsing hop and adds no MVP value for a
**read-only** card):

```
📰 <b>{news_event.category}</b>  ·  {news_event.published_at:%Y-%m-%d}
{news_event.title}
{news_event.url}   (only if not null)

<b>{content_draft.title}</b>

{content_draft.body}

{hashtags joined with spaces}
```

No buttons for the MVP (§16 Option A is explicitly read-only) — inline keyboards, `callback_data`
design, and edit-message-on-click behavior are deferred to whichever future MVP option adds
Approve/Reject/Rework (§9–§11), since none of that is needed for a read-only inbox.

---

## 9. Approve Semantics

**FACT**: `ContentDraft.status` is a **free-text `String`**, not a constrained enum — its own
model comment states this explicitly: *"not enumerated in the project documentation."*
`ContentDraftService.create_from_result()` (`services/content_draft_service.py:90`) writes exactly
one literal value, `"draft"`, and Contract §7.1 states Phase 10 *"never transitions a ContentDraft
row to any other status."* **No code anywhere currently writes any status value other than
`"draft"`.**

**FACT**: no `approved`/`accepted`/`rejected`/`review`/`published` field or enum exists on
`ContentDraft`, `EditorialTask`, or any other model (`grep -rn -i
"approved\|accepted\|rejected\|published"` across `database/models/*.py` finds nothing matching
an editorial-review concept — `EventStatus.REJECTED` exists, but describes **NewsEvent
triage rejection**, Phase 9's own, unrelated concept, not editorial-draft approval).

**Answer: Approve CANNOT be represented with the current schema as a persisted state.** Since
`status` is already a free-text `String` column, a new *value* (e.g. `"approved"`) could be
written into it **without a migration** — the column itself needs no schema change — but this
would be a **new, currently-undocumented convention**, and nothing today reads or branches on
`ContentDraft.status` at all, so writing a new value has zero effect on any existing code path
(safe to introduce, but also currently meaningless without new reader logic).

**MVP meaning comparison**:
- **A. UI-only acknowledgement** (e.g. edit the Telegram message to show "✅ Approved by
  @username", no DB write) — zero schema impact, zero new persisted state, but not durable/
  auditable outside Telegram itself.
- **B. Persisted editorial approval state** (write `ContentDraft.status = "approved"`) — no
  migration needed (free-text column), but is a new, undocumented status convention this
  discovery does not freeze.
- **C. Trigger for future publication** — presumes a publication mechanism that does not exist
  (§18) — out of scope to design here.
- **D. Another existing model** — none found; no existing model represents this concept.

**RECOMMENDATION**: this is a genuine Decision Resolution question, not resolved by discovery
alone — but if Approve is included in a future Phase 11 milestone (not the read-only MVP this
discovery recommends), **Option B** (a new free-text status value, no migration) is the
minimal-footprint choice consistent with the column's existing, already-free-text design.

---

## 10. Reject Semantics

Same investigation process as §9, same finding: no existing field represents this. `status` could
again absorb a new free-text value (e.g. `"rejected"`) with no migration.

**FACT, critical rule, directly verified**: `workflows/runner.py`'s own class docstring states
*"Only WorkflowRunner ever changes an EditorialTask's status — services.workflow_service never
does."* This is an absolute, load-bearing invariant, not a convention with exceptions. **A human
rejecting a `ContentDraft` MUST NOT mutate `EditorialTask.status`** — doing so would require either
a new writer bypassing this stated invariant (a real architecture violation) or `WorkflowRunner`
itself somehow being invoked again, which it structurally cannot be for a task already `COMPLETED`
(`TaskAlreadyCompletedError`, confirmed `workflows/runner.py:117`). **Rejection, if implemented,
belongs to `ContentDraft` alone** — never to `EditorialTask`/workflow state, which is exactly what
Contract §7's Capability-isolation discipline already implies by keeping `ContentDraft` a
downstream, independently-owned record.

**Auditability/accessibility**: since no delete mechanism exists anywhere for `ContentDraft`
(confirmed — no `session.delete(ContentDraft...)` call exists in this repository), a rejected
draft would naturally remain accessible/queryable by default; nothing needs to be added to
*prevent* deletion, since nothing currently deletes.

---

## 11. Rework / Regeneration Semantics

This is the most architecturally consequential question in this discovery — traced carefully
against real guards, not assumed.

- **Can the existing `COMPLETED` `CONTENT_GENERATION` task be rerun?** **No.**
  `WorkflowRunner.run()` (`workflows/runner.py:113-117`) checks `task.status` before doing
  anything else: `RUNNING` → `TaskAlreadyRunningError`; `COMPLETED` or `FAILED` →
  `TaskAlreadyCompletedError`. There is no code path that resets a terminal task back to a
  runnable state.
- **Would regeneration require a new `EditorialTask`?** **Yes**, necessarily, given the above.
- **Would it require a new `ContentDraft`?** **Yes** — `ContentDraftService.create_from_result()`
  always does `session.add(ContentDraft(...))`, an unconditional insert; there is no update-in-
  place path.
- **Can `workflow_service.create_task()` create a second `CONTENT_GENERATION` task for the same
  `NewsEvent`?** **Yes.** `_find_active_task()` (`services/workflow_service.py:89-106`) only
  checks `ACTIVE_STATUSES = (CREATED, RUNNING)` (`services/workflow_service.py:24`) for
  uniqueness — a task that has already reached `COMPLETED` does **not** block a new one for the
  same `(event_id, workflow_type)` pair. This was independently confirmed live during Phase 10's
  own M6 validation session (the same `NewsEvent` already carried one `FAILED` `CONTENT_GENERATION`
  task, and creating a second one for it succeeded without error).
- **Is there a version/revision concept for `ContentDraft`?** **No** — `version` is hardcoded to
  `1` everywhere it's written (`services/content_draft_service.py:90`), confirmed never
  incremented anywhere in this repository.
- **Could regeneration accidentally overwrite history?** **No** — since every regeneration
  necessarily creates a brand-new `EditorialTask` + `ContentDraft` pair (both inserts, never
  updates), the original rows remain untouched and queryable, by construction, not by any new
  safeguard that needs building.

**Approach comparison**:
- **A. Rerun the same task** — **architecturally impossible**, blocked by `TaskAlreadyCompletedError`
  (frozen Phase 5 code this discovery is instructed not to touch).
- **B. Create a new `EditorialTask`** (full new run: research → intelligence → copywriting →
  quality again) — **fully supported today, zero new code needed for the workflow half** — this
  is exactly what `scripts/run_content_generation.py` already does for any event; "rework" would
  just be "run the same script again for the same `event_id`." The real new work is only in the
  Telegram-facing trigger, not the pipeline.
- **C. Create a draft revision** (bump `version`, keep one `ContentDraft` row's identity) — **not
  supported today**; `version` is never incremented, and nothing queries "the latest version for
  this task" — would require new logic (not a migration, since the column exists, but new,
  currently-nonexistent query/update logic).
- **D. Targeted Copywriting-only regeneration** (rerun just the `copywriting` step, reusing
  Research/Intelligence's already-committed `step_results`) — **not supported by any existing
  mechanism**: `WorkflowRunner` has no concept of "resume from step N," and Phase 9.5's own
  disclosed limitation (still standing, Contract §13 item 9: "Crash recovery or a resume
  mechanism") explicitly excludes this. Would require new `WorkflowRunner` capability — a real,
  non-trivial architecture change this discovery is instructed not to authorize.
- **E. Defer regeneration entirely from the Phase 11 MVP** — **fully consistent** with the
  read-only recommendation in §16.

**RECOMMENDATION**: **Option B (new `EditorialTask`) is the smallest architecture-safe path if
regeneration is ever implemented** — it requires zero change to `WorkflowRunner`,
`CapabilityExecutor`, or any Capability; "Rework" becomes, at the trigger layer only, "invoke
`run_content_generation_for_event(event_id)` again." Options C and D both require real,
currently-nonexistent capability and should not be assumed available. **For the Phase 11 MVP
itself, Option E (defer) is recommended** — Rework's only architecture-safe implementation (B)
still requires a live OpenAI call triggered from inside a Telegram callback handler, a materially
larger scope than a read-only inbox.

---

## 12. Authorization & Callback Security

**FACT**: `database/models/user.py` defines a real `User` model — `telegram_id` (unique
`BigInteger`), `username`, `role` (`UserRole`: `OWNER`/`ADMIN`/`SMM_MEMBER`/`VIEWER`),
`permissions` (JSON) — but is consumed **nowhere** (§2). No middleware, no handler, no service
references `User` or `UserRole` at all. **This repository currently has zero enforced
authorization on any bot command** — anyone who can message the bot can invoke any of the five
existing placeholder commands.

**Who is allowed to view/approve/reject/request-rework, per current code**: **everyone, currently
— there is no gate.** A real answer requires either (a) building the first-ever authorization
middleware/dependency against the existing, dormant `User`/`UserRole` model, or (b) explicitly
deciding Phase 11's MVP ships with no authorization at all (acceptable only if the SMM Telegram
workspace itself is already access-controlled at the Telegram level — a product/deployment
question, not something source code can answer).

**Callback-query trust boundaries** (all currently moot for a read-only MVP, since no callback
exists yet, but assessed for whichever future milestone adds buttons): `callback_data` tampering
(a malicious/curious user editing the callback payload to reference another draft's ID) and
arbitrary draft IDs both require the *future* handler to independently re-verify the requesting
user's authorization against the *specific* draft/action, not just trust that a button was shown
to them — the same discipline as any web app's IDOR (insecure direct object reference) defense.
Replay/double-click and duplicate callbacks require idempotent handling at that time (e.g.
checking current `ContentDraft.status` before acting, so a second "Approve" click on an
already-approved draft is a no-op, not a double-write) — a small, standard defensive pattern, not
a new subsystem.

**RECOMMENDATION**: do not build new RBAC infrastructure — wire the *existing* `User`/`UserRole`
model into one minimal authorization check (e.g. "does a `User` row exist for this
`message.from_user.id` with `role != VIEWER`?") the first time Phase 11 needs one. This is
appropriately minimal, not over-engineered, and reuses rather than duplicates existing schema.

---

## 13. Delivery Idempotency

**FACT**: no delivery marker exists anywhere. `grep -rn
"telegram_message_id\|sent_at\|external_id"` across `database/models/*.py` and
`schemas/content_draft.py` returns nothing. `ContentDraft` has no field recording whether, when,
or to which chat/message it was ever delivered.

**Duplicate-delivery risk, by model**:
- **Pull mode**: **no risk at all** — a read query has no side effect; running `/drafts` twice
  just shows the same drafts twice. Idempotency is structural, not something that needs to be
  engineered.
- **Push mode**: **high risk** without new persistence — a process restart mid-delivery, a retry
  after a Telegram timeout, or a second manual trigger would all re-send the same draft with no
  way to detect "already delivered," since no such marker exists.

**This directly and materially supports §6's push-vs-pull recommendation**: pull-mode's MVP
requires building **zero** new delivery-state persistence, while push-mode cannot be built safely
without first adding exactly the kind of new column/table this discovery is instructed not to
propose without evidence of necessity. The evidence here is that necessity is a **push-mode-only**
cost, avoidable entirely by choosing pull for the MVP.

---

## 14. Failure Semantics

**FACT/INFERENCE**: none of Telegram-API-unavailable / bot-removed-from-group / invalid-`chat_id`
/ blocked-bot / rate-limit / malformed-Markdown / callback-failure currently have any handling
code, since no Telegram-sending code beyond `message.answer(static_string)` exists yet — there is
nothing to fail in a delivery sense today.

**Evaluated invariant** (per instruction, explicitly assessed, not blindly frozen): *"a Telegram
delivery failure must not invalidate a successfully completed AI workflow or destroy a persisted
`ContentDraft`."* **This is fully consistent with, and already structurally guaranteed by, current
architecture** — since (a) `ContentDraft` rows are never deleted by any existing code path, (b)
`EditorialTask.status` can only ever be written by `WorkflowRunner` (§10's cited invariant), which
a Telegram-layer failure has no path to reach, and (c) a pull-mode MVP has no "delivery" step to
fail in the first place — the invariant holds *by construction* for the recommended MVP, not
merely by discipline. It would need active enforcement (e.g. `try`/`except` boundaries around any
future push-send call, mirroring `scripts/run_content_generation.py`'s own documented pattern of
isolating `ContentDraftService`'s failure from the workflow's already-committed `COMPLETED`
status) only once push delivery is ever added.

---

## 15. Testing Architecture

**FACT**: zero bot tests exist. `find tests -iname "*bot*" -o -iname "*telegram*" -o -iname
"*handler*"` returns nothing. No aiogram test pattern, no fake `Bot`, no handler test, no callback
test exists anywhere in this repository today — Phase 11 would be the first to establish this
convention.

**RECOMMENDATION**: aiogram supports unit-testing handlers by calling them directly as plain
async functions with a constructed `Message`/`CallbackQuery` object and a fake/mock `Bot` (the
same "test the function directly, not the framework wiring" discipline this repository already
applies everywhere else — e.g. Phase 10's own CLI tests exercise
`run_content_generation_for_event()` directly, never the thin `main()` wrapper). For a read-only
MVP, the query/formatting logic (§4/§8) should be tested exactly like any other service function
— against a real test database (mirroring `tests/test_content_draft_service.py`'s own
conventions), with the handler itself kept thin enough that it needs minimal separate testing.
**No live Telegram API call should be part of the automated suite**, mirroring Phase 7 §15.5's
already-established, unbroken no-real-network-call discipline.

**Manual live-validation gate** (mirroring Phase 10's own M0 live-OpenAI-smoke precedent): one
manual, out-of-band run of the actual bot against a real Telegram bot token and a real chat,
confirming a real card renders correctly (HTML formatting, escaping, length) — this cannot be
meaningfully faked and should not be attempted automatically.

---

## 16. MVP Options Comparison

| | Files likely affected | Schema impact | Architecture impact | Risk | Product value | Dependencies |
|---|---|---|---|---|---|---|
| **A. Read-only inbox** (`ContentDraft` → command → card) | New: 1 handler extension/new file, 1 query/formatter module. Existing: none required to change. | **None** | **Minimal** — one new, additive, read-only presentation layer; zero touch to `WorkflowRunner`/`CapabilityExecutor`/`ContentDraftService`/any Capability | **Low** | **Immediate** — SMM team can see AI output today, zero manual DB query needed | None beyond what exists |
| **B. Inbox + Approve/Reject** | A above, plus: keyboard construction, one new callback handler, a status-write path | **None** (free-text `status` column absorbs new values) | **Moderate** — first callback-query handler, first write path from `bot/` into `ContentDraft`, first authorization check (§12) | **Medium** — new write path, new security surface (§12), no existing pattern to mirror | High — closes the human-in-the-loop product intent | A, plus a real authorization decision |
| **C. Inbox + Approve/Reject/Rework** | B, plus: a rework trigger calling `run_content_generation_for_event()` from a callback handler | **None** | **High** — Rework triggers a real, billed, potentially-slow (Phase 10's own `120`s budget) OpenAI pipeline run from inside a Telegram callback, a materially different latency/UX/cost profile than a simple DB write | **Medium-High** — long-running callback handling, cost exposure, needs its own UX design (can't just "await" a 2-minute pipeline inside a callback handler) | Highest, if the team wants full control | B, plus solving the long-running-callback problem (not investigated further here — out of MVP scope) |
| **D. Automatic push + full actions** | Everything in C, plus a poller/trigger mechanism | New delivery-marker persistence required (§13) | **Highest** — reintroduces the scheduler Phase 10 explicitly deferred (§6), plus B/C's own impact | **High** — duplicate-delivery risk without new persistence, scheduler scope creep | High, if reliable | C, plus a scheduler decision explicitly out of Phase 10's own established scope |

---

## 17. Recommended Phase 11 Boundary

**RECOMMENDATION: Option A — read-only Editorial Inbox.** Grounded directly in §5's ownership
finding (only a read-only, decoupled layer avoids re-violating Phase 10's own established
isolation discipline), §6/§13's push-vs-pull finding (pull needs no scheduler and no new
persistence), and §11's finding that Rework's only architecture-safe form still requires solving a
real, non-trivial long-running-callback UX problem this discovery has deliberately not designed.
Option A is buildable entirely from already-persisted data, requires no schema change, touches no
frozen Phase 5/6/7/8/9/10 file, and gives the SMM team real, immediate value (seeing AI-generated
drafts without a manual database query) — a genuinely useful, minimal slice, not a token first
step.

---

## 18. Schema / Migration Assessment

**NOT REQUIRED**, for the recommended Option A MVP. Evidence: §4 shows the complete card data
path exists today (`ContentDraft` → `EditorialTask` → `NewsEvent`, all raw FK columns, zero new
column needed); §9/§10 show `ContentDraft.status`'s existing free-text design already
accommodates a future new value with no migration, if/when Approve/Reject are added later; §13
shows delivery-idempotency persistence is a push-mode-only cost this discovery recommends
avoiding entirely by choosing pull. **If a future milestone adds push delivery, a migration would
become necessary at that point** (a delivery-marker column/table) — not for the MVP recommended
here.

---

## 19. Files Likely Affected

**Existing files likely edited** (for Option A):
- `bot/handlers/__init__.py` — register one new/extended router.
- Either `bot/handlers/news.py` (extend) or a new file (§3's open naming question).

**New files likely needed** (for Option A):
- One new handler file (if a new command is chosen over extending `/news`).
- One new query/formatting module (likely under a new `bot/` subpackage or `services/`, mirroring
  existing service-layer conventions — exact location a Decision Resolution question, not
  answered here).
- Test file(s) for the above, per §15's recommended pattern.

**Files that MUST remain untouched** (per the Critical Architectural Rule and this discovery's own
findings, none of which surfaced a real blocker requiring otherwise):
`workflows/runner.py`, `capabilities/executor.py`, `capabilities/registry.py`, every
`capabilities/*_capability.py` file, `integrations/llm_gateway/**`, `integrations/prompts/**`,
`services/content_draft_service.py`, `services/workflow_service.py`, `schemas/content_draft.py`,
`scripts/run_content_generation.py`, `database/models/content_draft.py`,
`database/models/editorial_task.py`, `database/models/news_event.py`, every Phase 10-frozen file,
`integrations/sources/telegram_source.py` (the unrelated Telethon-based source collector).

---

## 20. Architectural Risks

- **HTML-escaping of LLM-generated content is a genuinely new concern** (§8) — the first time
  this repository formats untrusted/unpredictable text into an HTML-parse-mode Telegram message;
  a missed edge case (an unescaped `<`/`>`/`&` in generated body text) would break message
  rendering, not silently corrupt data, but should be handled deliberately, not assumed safe.
- **The dormant `User`/`UserRole` model has never been exercised** (§12) — wiring it into a real
  authorization check for the first time carries the ordinary risk of any first real use of
  previously-inert schema (undiscovered edge cases in how `telegram_id` gets populated, e.g. no
  existing code path creates a `User` row at all — `grep` found zero writers).
  **OPEN QUESTION** in §21.
- **Rework, if ever added, requires solving a long-running-callback UX problem** (§16 Option C)
  this discovery has explicitly not designed — a real architectural risk for whichever future
  phase attempts it, flagged here so it isn't underestimated later.
- **No existing bot test convention** (§15) — Phase 11 establishes a new testing pattern from
  scratch; risk is process/convention risk (getting the pattern wrong early), not a functional
  risk to existing code.

---

## 21. Open Questions

Only genuine, source-unanswerable questions:

1. **Should Phase 11 extend `/news` or introduce a new command name (e.g. `/drafts`)?** (§3) —
   a naming/product decision, not resolvable from source.
2. **No code path currently creates a `User` row.** How would an SMM team member's `telegram_id`
   ever get inserted into the `users` table before Phase 11's authorization check could use it —
   a manual DB seed, an admin command, or a first-`/start`-creates-a-`VIEWER`-row convention?
   This is a real product/ops decision needed before §12's recommendation is actionable.
3. **Should an MVP with zero authorization (open to anyone who can message the bot) be acceptable
   for Phase 11**, on the assumption the SMM Telegram workspace is itself already
   access-controlled at the Telegram level — or must in-app authorization (§12) be part of even
   the read-only MVP? This is a risk-tolerance decision, not something source code determines.

---

## 22. Phase 12 / Future Boundaries

- **Meme/image generation**: **FACT**, re-verified this session — `grep -rln
  "generate_image\|image_generation\|MemeCapability\|meme_capability"` across every `.py` file
  returns nothing. No image-generation infrastructure of any kind exists. This matches Phase 10
  Contract §11's own finding exactly (`LLMGateway.generate()` has no image-output method; `
  ContentType.MEME` exists on the enum but is never written by any code path). Phase 11's own
  scope (a text-only editorial inbox for already-generated `ContentDraft` rows) cannot and does
  not absorb this — meme generation remains a wholly separate, unstarted phase.
- **Public-channel publication**: **FACT** — no publishing mechanism to any public-facing Telegram
  channel/audience exists anywhere in this repository. `bot/` only ever replies inside the chat a
  command was issued from; there is no `PublisherService`, no "publish to channel" API call, no
  public-channel configuration. Phase 10 Contract §10 already conceptually sketched a *future*
  `PublisherService` (never built, never authorized) as the eventual, opposite-direction analog of
  `services/collector.py`'s inbound role — Phase 11's "Approve" (§9) must not be silently conflated
  with this. **RECOMMENDATION: public publishing stays deferred** to a phase that explicitly
  designs and authorizes it — consistent with this repository's own `CLAUDE.md` MVP rule
  ("Automatic publication without human involvement" is explicitly forbidden in MVP).
- **Scheduler/automatic delivery**: deferred per §6's own recommendation — no evidence justifies
  introducing one for Phase 11's MVP; would only become relevant if/when push delivery (§16
  Option D) is later authorized.

---

## 23. Final Discovery Verdict

PHASE 11 DISCOVERY COMPLETE — READY FOR DECISION RESOLUTION
