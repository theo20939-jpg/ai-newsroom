# Phase 11 — Telegram Editorial Inbox Architecture Contract

## 1. Status and Authority

**Status: frozen amendment specification, pending adversarial audit.** This document converts
`docs/phase11_telegram_editorial_inbox_discovery.md` ("Discovery") and
`docs/phase11_decision_resolution.md` ("Decision Resolution") into binding form. No production
code, test, or migration was modified to produce this document. Every important claim about
current architecture was independently re-verified against live source this session — not
inherited from Discovery/Decision Resolution without checking — and cited by file:line below.

**Source-of-truth order**: this Contract (once approved) > `docs/phase11_decision_resolution.md`
(the approved decisions this Contract codifies, not reinterprets) >
`docs/phase11_telegram_editorial_inbox_discovery.md` (the evidence both documents share) > the
frozen Phase 5–10 contracts, all of which remain in force, unamended.

Every statement is tagged **FACT** (repository evidence, re-verified this session), **DECISION**
(frozen, binding choice), **INFERENCE** (reasoned conclusion), or **RECOMMENDATION**
(non-binding).

**No source contradiction was found.** Every technical assumption in Decision Resolution was
independently re-checked against current source (§4) and confirmed feasible exactly as decided —
this Contract does not reinterpret any decision.

**Revision note**: this Contract has been revised twice, both targeted. **Pass 1** followed
`docs/phase11_telegram_editorial_inbox_contract_audit.md`'s adversarial audit (3 MAJOR findings,
CRITICAL = 0): `news_url` escaping (§13, finding F-1), a post-escape message-length algorithm
(§14, finding F-2), and a factual correction to forum-topic destination semantics (§10, finding
F-3). **Pass 2** followed `docs/phase11_telegram_editorial_inbox_contract_reaudit.md`'s targeted
re-audit, which found F-1/F-3 fully resolved and surfaced one new MAJOR (N-1: §14's length check
used Python `len()` — Unicode code points — instead of Telegram's actual UTF-16-code-unit measure,
undercounting astral characters including the card template's own `📰`) and one MINOR (N-2: §14's
terminal fallback did not explicitly cite which §16 case governs it). Both are corrected in §14/§16
(this revision). **No architecture, scope, or previously-approved decision was changed by either
revision.**

---

## 2. Purpose

**DECISION — why Phase 11 exists**: to give the SMM team a way to see AI-generated editorial
output — already produced and persisted by Phase 10's frozen pipeline — without a manual database
query. Phase 11 introduces exactly one new capability: a **read-only, pull-based Telegram
Editorial Inbox**.

**Core path, frozen**:
```
Telegram user
    → /news
        → bot handler
            → editorial inbox query service
                → persisted ContentDraft / EditorialTask / NewsEvent (read-only)
            → Telegram editorial cards (HTML, escaped)
```

**DECISION, binding, restated three times for emphasis because each is a distinct failure mode a
future implementer could otherwise introduce by accident**:
- Phase 11 **MUST NOT** trigger AI generation, in any form, from any code path.
- Phase 11 **MUST NOT** mutate editorial workflow state (`EditorialTask.status`, `ContentDraft`,
  or any other persisted record) — it reads, and only reads.
- Phase 11 **MUST NOT** publish content publicly, in any form, to any audience beyond the chat a
  command was invoked from.

---

## 3. Scope

**DECISION — IN SCOPE** (Decision Resolution §3, §4, §6–§9, §22, unchanged):
- `/news` becomes the Editorial Inbox entry point (extending the existing placeholder handler,
  §9).
- Pull-based retrieval only — the bot never initiates contact.
- The 5 most recent eligible `ContentDraft` rows (§6), newest-first.
- Read-only access — zero write path anywhere in this phase.
- Telegram rendering as HTML cards (§12–§13).
- Empty-state and failure UX (§16).
- Robust HTML escaping of all dynamic content (§13).
- Automated tests (§24).
- One manual live-Telegram smoke as the final Definition-of-Done gate (§25) — not executed during
  Contract writing.

**DECISION — OUT OF SCOPE, binding**:
- Approve, Reject, Rework/Regenerate (§19).
- Any callback, inline action keyboard, or FSM (§10, §19).
- Any persisted editorial-review state (§19, §22).
- Push delivery, scheduler, delivery worker (§20).
- Any sent/delivered marker (§15, §22).
- Public publication of any kind (§20).
- Meme/image generation of any kind (§21).
- Any application-level authorization/RBAC (§11).
- Any schema migration (§22).

---

## 4. Existing Architecture

Every claim below was re-read directly this session, not copied from Discovery without checking.

**`/news` handler — FACT** (`bot/handlers/news.py:1-15`, full file re-read): a `Router(name="news")`
with one handler, `handle_news(message: Message) -> None`, registered via
`@router.message(Command("news"))`, body: `await message.answer(PLACEHOLDER_TEXT)` where
`PLACEHOLDER_TEXT = "This functionality will be implemented in the next development phases."`
Zero DB access, zero service calls. **This is placeholder scaffolding, not production
functionality** — described precisely as such, not overstated.

**Router/bootstrap ownership — FACT** (`bot/handlers/__init__.py:1-18`, `bot/main.py:1-42`,
`bot/loader.py:1-31`, all re-read in full): `bot/handlers/__init__.py` already imports and
registers `news_router` into the root `Router(name="root")` (`bot/handlers/__init__.py:5,12`) —
**`/news` is already wired end-to-end into the dispatcher; no router-registration change is
needed for Phase 11.** `bot/main.py::main()` creates the bot/dispatcher via
`bot/loader.py::create_bot()`/`create_dispatcher()`, includes the root router, and calls
`dp.start_polling(bot)` — **long-polling only, no webhook code exists anywhere.**
`create_dispatcher()` returns a bare `Dispatcher()` (`bot/loader.py:28-30`) — **no dependency
injection of any kind exists in the bot layer** (no injected `AsyncSession`, no injected service).
`create_bot()` sets `DefaultBotProperties(parse_mode=ParseMode.HTML)` (`bot/loader.py:24`) — HTML
is this bot's only configured parse mode.

**Correction to Discovery's own speculative file list** (Discovery §19 guessed
`bot/handlers/__init__.py` might need "register one new/extended router" — re-verified this
session and found **unnecessary**: `/news` is being *extended*, not newly added, and its router
is already registered). This narrows, not contradicts, Discovery's own scope estimate — see §23.

**`ContentDraft` model — FACT** (`database/models/content_draft.py:1-48`, full file re-read):
columns `id` (UUID, PK), `task_id` (UUID, FK → `editorial_tasks.id`, `nullable=False`, **no
index**), `type` (`ContentType` enum), `title`/`body` (`Text | None`), `hashtags` (`JSON | None`),
`version` (`int`, always `1`), `status` (free-text `String | None`), `created_at`/`updated_at`
(`DateTime`, **`created_at` has no index**). No `relationship()` is declared (confirmed by
re-grep: `grep -n "relationship(" database/models/*.py` returns nothing across the entire
`database/models/` directory).

**`EditorialTask` model — FACT** (`database/models/editorial_task.py:1-54`, full file re-read):
columns `id`, `event_id` (FK → `news_events.id`), `priority`, `workflow` (JSON), `status`
(`TaskStatus` enum: `CREATED`/`RUNNING`/`WAITING`/`COMPLETED`/`FAILED`, **`index=True`**,
`editorial_task.py:45-46`), `retry_count`, `created_at` (**`index=True`**, `editorial_task.py:50`),
`updated_at`.

**`NewsEvent`/`NewsSource` models — FACT** (`database/models/news_event.py:1-68`,
`database/models/news_source.py:1-41`, both fully re-read): `NewsEvent` has `title` (`Text`,
non-null), `category` (`EventCategory` enum, indexed), `url` (`Text | None`), `published_at`
(`DateTime | None`, indexed), `source_id` (FK → `sources.id`). `NewsSource` has `name` (`String`,
non-null).

**`ContentDraftRead` — FACT** (`schemas/content_draft.py:16-30`, full file re-read): a frozen
Pydantic model with `id`, `task_id`, `type`, `title`/`body` (`str | None`), `hashtags`
(`list[str] | None`), `version`, `status`, `created_at`/`updated_at`. Returned only by
`ContentDraftService.create_from_result()` — **Phase 11 does not reuse `ContentDraftRead` as its
view model** (§8 explains why).

**`ContentDraftService` — FACT** (re-confirmed unchanged from Phase 10): the sole writer of
`ContentDraft` rows, via `create_from_result()`. Phase 11 never calls this class, never imports
it for any write purpose.

**DB session pattern — FACT** (`database/session.py:14`, re-confirmed): `async_session_factory =
async_sessionmaker(engine, expire_on_commit=False)`. Since the bot layer has **no DI** (above),
Phase 11's handler must open its own session directly, mirroring
`scripts/run_content_generation.py`'s own established pattern (`async with async_session_factory()
as session:`) — the only precedent available, since no other bot handler has ever needed a
session before.

**Telegram configuration — FACT** (`core/config.py:44`, re-confirmed): `telegram_bot_token:
SecretStr | None = None` is the only Bot-API-relevant setting. No `chat_id`, no
`editorial_chat_id`, no destination config of any kind exists in `Settings`.

**Callback/FSM/keyboards — FACT** (re-confirmed by fresh grep this session):
`bot/keyboards/__init__.py` and `bot/middlewares/__init__.py` are both docstring-only, empty
placeholders. `grep -rln "callback_query\|CallbackQuery"` across the entire repository returns
zero files. No FSM storage or state group is configured anywhere.

| Component | Classification |
|---|---|
| `/news` router registration | **EXISTING**, unchanged |
| `/news` handler body | **NEW IN PHASE 11** (replaces placeholder) |
| Bot bootstrap (`main.py`/`loader.py`) | **UNCHANGED** |
| `ContentDraft`/`EditorialTask`/`NewsEvent`/`NewsSource` models | **EXISTING**, unchanged |
| `ContentDraftService` | **EXISTING**, unchanged, never called by Phase 11 |
| A new query/service module | **NEW IN PHASE 11** (§7) |
| A new DTO/view model | **NEW IN PHASE 11** (§8) |
| A new HTML formatting helper | **NEW IN PHASE 11** (§13) |
| `bot/keyboards/`, `bot/middlewares/` | **UNCHANGED**, remain empty |

---

## 5. Data Flow

**DECISION, binding — the exact read path**, mirroring `CapabilityExecutor._build_context()`'s
own two-hop, no-ORM-relationship lookup convention (`capabilities/executor.py:69-74`, re-confirmed
this session unchanged):

```
ContentDraft.task_id
    → EditorialTask.id      (session.get(EditorialTask, draft.task_id))

EditorialTask.event_id
    → NewsEvent.id           (session.get(NewsEvent, task.event_id))

NewsEvent.source_id
    → NewsSource.id          (session.get(NewsSource, event.source_id), only if source name is used)
```

No `relationship()` is added anywhere — confirmed unnecessary (§4) and explicitly forbidden as an
unneeded abstraction (Decision Resolution §21).

**DECISION — fields required for the view model** (§8), all confirmed available with zero schema
change (§4):
- `ContentDraft.id`, `.title`, `.body`, `.hashtags`, `.created_at`.
- `EditorialTask.status` (used only for the eligibility filter, §6 — not rendered on the card).
- `NewsEvent.title`, `.category`, `.url` (nullable — §12 defines missing-value behavior),
  `.published_at` (nullable).
- `NewsSource.name` — **not included in the MVP card** (Decision Resolution §7 explicitly
  excludes it for MVP simplicity); the data path above lists the hop for completeness/future
  reference only, not because Phase 11 uses it.

No field is invented that isn't already a real, existing column.

---

## 6. Eligibility Query

**DECISION, binding**: a `ContentDraft` row is eligible for display if and only if its linked
`EditorialTask.status == TaskStatus.COMPLETED`. Eligible rows are ordered
**`ContentDraft.created_at DESCENDING`**, with **`ContentDraft.id DESCENDING`** as a deterministic
tie-break (UUIDs carry no chronological meaning; this is purely for stable, reproducible ordering
if two rows ever share an identical `created_at` timestamp). The result is limited to the **5**
most recent eligible rows.

**DECISION, binding — terminology**: these are referred to as **"latest editorial drafts"** (or
equivalent product-facing language) — never **"pending"**, since no persisted review state exists
anywhere (Decision Resolution §6 explicitly forbids inventing this concept).

**DECISION, binding**: drafts belonging to a `FAILED` (or `CREATED`/`RUNNING`/`WAITING`)
`EditorialTask` **MUST NOT** appear. In practice this is currently a no-op guarantee — Contract
§7.1 (Phase 10) already ensures a `ContentDraft` row is only ever created after a `COMPLETED`
result — but the query filter is still explicit and binding, not left implicit, so it remains
correct even in the already-disclosed, rare edge case of a future data anomaly.

**INFERENCE — query shape**: since `ContentDraft.task_id` has no FK index and `ContentDraft
.created_at` has no index (§4), and `EditorialTask.status` *is* indexed, the most efficient query
shape filters `EditorialTask` by `status == COMPLETED` first (using the real index), then joins to
`ContentDraft`. At Phase 11's expected data volume this is not a performance blocker (§27 Risks
names it explicitly, not silently accepted).

---

## 7. Query Service

**DECISION, binding — new module**: `services/editorial_inbox_service.py`, a **plain-function
module** (not a class) — mirroring the more common convention in this repository's `services/`
layer (`services/workflow_service.py`, `services/triage_orchestrator.py`, `services/collector.py`
are all plain-function modules; `ContentDraftService`'s class shape is the deliberate exception
for a single-purpose *writer*, not the norm this read-only service should copy).

**DECISION, binding — ownership**:
```
bot/handlers/news.py (handler)
    → services/editorial_inbox_service.py (query service)
        → AsyncSession (opened by the handler, passed in)
    → schemas/editorial_inbox.py (DTO, §8)
    → bot/formatting.py (renderer, §13)
```

**DECISION, binding — the service MAY**:
- Query the latest eligible `ContentDraft` rows (§6).
- Load each row's linked `EditorialTask`/`NewsEvent` (§5).
- Construct and return `EditorialInboxCard` DTOs (§8) — never a raw ORM object crossing back to
  `bot/`.

**DECISION, binding — the service MUST NOT**:
- Send any Telegram message (no `aiogram` import of any kind in this module — verified as
  achievable, since every operation it performs is plain SQLAlchemy).
- Trigger AI generation, in any form.
- Invoke `WorkflowRunner`, `CapabilityExecutor`, or any `Capability`.
- Mutate `ContentDraft`, `EditorialTask`, or any workflow state.
- Publish anything publicly.

**DECISION, binding — session ownership**: the **handler** (§9) opens the `AsyncSession` (via
`async_session_factory()`, mirroring `scripts/run_content_generation.py`'s own pattern, §4) and
passes it into the service function as a parameter — the service never constructs its own session
or engine. **The service performs no commit** — every operation is a `session.get()`/`select()`
read. This is a binding invariant, not an implementation detail: a read-only query service that
commits would be a scope violation on its own, since a commit implies a write-transaction boundary
this phase has no business opening.

**CONSEQUENCES**: fully unit/integration-testable against a real test database with zero
`aiogram`/Telegram mocking needed for the service layer itself (§24).

---

## 8. DTO / View Model

**DECISION, binding — new module**: `schemas/editorial_inbox.py`, containing one frozen Pydantic
model, **`EditorialInboxCard`**, mirroring `schemas/content_draft.py`'s `ContentDraftRead` pattern
(`model_config = ConfigDict(frozen=True, extra="forbid")`).

**DECISION, binding — fields** (every one already confirmed reachable, §4/§5; no field invented):
```python
class EditorialInboxCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    draft_id: UUID
    draft_title: str | None
    draft_body: str | None
    hashtags: list[str] | None
    draft_created_at: datetime
    news_title: str
    news_category: str        # EventCategory enum value, as its string
    news_url: str | None
    news_published_at: datetime | None
```

**DECISION, binding — why `ContentDraftRead` is insufficient, stated explicitly per instruction**:
`ContentDraftRead` (§4) carries only `ContentDraft`'s own columns — it has no field for
`NewsEvent.title`/`.category`/`.url`/`.published_at`, all of which the card (§12) requires. Adding
these as optional fields onto `ContentDraftRead` would conflate two different concerns
(Phase 10's own persistence-return-value contract vs. Phase 11's joined, presentation-oriented
view) and risk future confusion about which producer is responsible for populating the joined
fields. A new, Phase-11-owned DTO is therefore the correct choice, not a convenience shortcut.

**CONSEQUENCES**: `schemas/content_draft.py` is **not modified** by Phase 11, in any way (§4, §18).

---

## 9. /news Handler

**DECISION, binding — semantics**:
```
/news
    → open a database session (async_session_factory(), mirroring scripts/run_content_generation.py)
    → call services/editorial_inbox_service.py's query function with that session, limit=5
    → for each returned EditorialInboxCard, render via bot/formatting.py (§13)
    → send each rendered card via message.answer(html, parse_mode=ParseMode.HTML) — 5 separate messages (§15)
    → close the session
```

**DECISION, binding — the handler MUST NOT**:
- Create an `EditorialTask`, in any form.
- Run content generation, in any form (no import of `scripts.run_content_generation`,
  `WorkflowRunner`, `CapabilityExecutor`, or any Capability).
- Modify any `ContentDraft` row.
- Mark anything "delivered" or "read" (no such state exists, §15/§22).
- Perform approval or rejection, in any form.
- Call any public-channel publishing API (none exists, §21, but stated explicitly regardless).

**DECISION, binding — dependency ownership**: the handler owns the `AsyncSession`'s lifecycle
(opens it, passes it to the service, closes it via the `async with` context manager) — it does
**not** construct raw SQL or `select()` statements itself; all query construction lives in
`services/editorial_inbox_service.py` (§7), keeping `bot/handlers/news.py` a thin orchestration
layer, consistent with this repository's own established "keep DB query logic in the service
layer, not the edge caller" convention (§7's own rationale).

**File affected**: `bot/handlers/news.py` only (§4's correction — `bot/handlers/__init__.py`
needs no change).

---

## 10. Destination Semantics

**DECISION, binding**: the response is sent to `message.chat.id` — the exact Telegram context
`/news` was invoked from (private chat or a group/supergroup the bot is already a member of).
**No persisted destination configuration of any kind is added**: no `destination_chat_id`, no
`message_thread_id` routing table, no editorial-channel config.

**DECISION, binding — chat-type behavior, corrected this revision (audit finding F-3)**: private
chats and groups/supergroups both work identically via the existing `message.answer()` call — no
new code path is needed for either. **Forum-topic behavior**: under the currently pinned/installed
`aiogram` version (`3.29.1`, confirmed via direct `inspect.getsource(Message.answer)` inspection
during the adversarial audit), `Message.answer()` itself already, automatically, unconditionally
sets `message_thread_id=self.message_thread_id if self.is_topic_message else None` on the outgoing
`SendMessage` it constructs — **meaning a reply sent via `message.answer()` from within a forum
topic already preserves that topic thread, at zero additional code cost.** Phase 11's handler (§9)
uses exactly this method for every send, so **this preservation is inherited for free**; no new
code, decision, or destination-routing mechanism is required to obtain it.

**Correction to this Contract's own original claim**: an earlier draft of this section stated
"Phase 11 does not guarantee topic-thread preservation... no code in this repository has ever set
`message_thread_id` on an outgoing message." That statement was **factually incorrect** — it
conflated "no code in *this repository* has explicitly set `message_thread_id`" (true, narrowly)
with "the effective behavior is therefore unguaranteed" (false): `aiogram`'s own library code,
which every existing handler already calls through `.answer()`, performs this automatically. This
section is corrected accordingly; no design change was required to fix the defect, only the
Contract's own description of already-existing behavior.

**INFERENCE, scoped precisely to avoid overclaiming**: this guarantee holds for the **currently
pinned `aiogram==3.29.1`** dependency, verified by direct source inspection this session — not as a
guarantee about `aiogram`'s API contract across arbitrary future versions. Should a future
`aiogram` upgrade change `Message.answer()`'s internal construction of `message_thread_id`, this
Contract's destination-semantics assumption would need re-verification at that time; Phase 11 does
not add any code of its own to enforce or re-implement this behavior, and must not be read as
guaranteeing it independent of the underlying library. No persisted thread configuration, manual
`message_thread_id` storage, or destination-routing table is introduced to achieve this — it is a
property of the existing call, not new Phase 11 code.

---

## 11. Authorization / Security Assumption

**DECISION, binding, exact human decision** (Decision Resolution §10, reproduced verbatim in
substance): **NO IN-APP AUTHORIZATION ENFORCEMENT IN PHASE 11.** `User`/`UserRole`
(`database/models/user.py`, re-confirmed this session still wired into nothing — zero middleware,
zero handler, zero service references it) **remain completely unwired** for the duration of Phase
11.

**DECISION, binding — Phase 11 MUST NOT add**: `User` bootstrap logic; automatic `User` row
creation; allowlist logic against the `User` table; RBAC/authorization middleware; `OWNER`
bootstrap; any role/permission enforcement anywhere in `bot/`; any authorization-related
migration; any hardcoded owner/admin Telegram ID, in config or code.

**BINDING SECURITY ASSUMPTION, stated exactly, not softened**: **Phase 11 provides no
application-level authorization boundary for `/news`. Anyone who can reach and invoke the bot may
access the Phase 11 inbox, unless access is restricted operationally at the Telegram/deployment
level.** This Contract does not, and must not be read to, describe the bot as
application-level access-controlled during Phase 11.

**DECISION, binding — future security gate** (frozen invariant, applies to every future
milestone, not just Phase 11): before any editorial write action is introduced — Approve, Reject,
Rework/Regenerate, Publish, or any administrative editorial mutation — a dedicated
authorization/security design step **MUST** occur, resolving at minimum: `User` creation/
bootstrap; `telegram_id` → `User` mapping; `OWNER` bootstrap; role semantics; permissions;
unauthorized-user behavior; callback authorization; replay/stale-action protection. **This system
is not designed here and is not Phase 11 implementation scope** — naming it only freezes that it
is a required prerequisite for write actions, nothing more.

---

## 12. Telegram Card

**DECISION, binding — frozen MVP card**, field order and content exactly:

```
📰 <b>{news_category}</b>  ·  {news_published_at:%Y-%m-%d}    (published_at line omitted if null)
{news_title}
{news_url}                                                     (omitted entirely if null)

<b>{draft_title}</b>

{draft_body}

{hashtags, space-separated}                                    (omitted entirely if hashtags is null/empty)
```

**DECISION, binding — required vs. optional**:
- **Always rendered** (never null per §4's model constraints): `news_category`, `news_title`.
- **Rendered only if present**: `news_published_at`, `news_url`, `hashtags`. `draft_title`/
  `draft_body` are nullable on the model (§4) — if either is `null` (a real, if rare, possibility
  given `ContentDraft.title`/`.body` are `Text | None`), render an explicit placeholder (e.g.
  "(no title generated)"/"(no body generated)") rather than an empty line, so the card never looks
  broken or truncated by accident.

**DECISION, binding — internal IDs**: `ContentDraft.id`/`EditorialTask.id`/`NewsEvent.id` are
**never rendered** to the Telegram user — no product value identified for exposing internal
database identifiers, and doing so would be the first place this repository ever surfaces a raw
UUID to an end user.

**DECISION, binding — card usefulness without source metadata**: since `news_url` is the only
source-linking field on the card and it is explicitly optional (§4: `NewsEvent.url` is nullable),
the card remains fully readable and useful with it omitted — title, category, generated
title/body/hashtags are always present.

**DECISION, binding — `news_url` rendering, resolved explicitly this revision (audit finding
F-1)**: `news_url` is rendered as **plain, HTML-escaped text** — not as a clickable HTML anchor
(`<a href="...">`). No `<a>` tag is introduced by this Contract for Phase 11. This means only
generic text-escaping (§13) applies to `news_url` — there is no separate href-attribute-escaping
rule to freeze here, because no href attribute is ever constructed. A future phase that decides a
clickable link is worth the added escaping surface (visible-link-text escaping and href-attribute
escaping are two different rules that must not be conflated) is a new, explicitly-governed decision
for that future phase, not Phase 11 — this Contract does not pre-authorize it.

---

## 13. Formatting / Escaping

**DECISION, binding**: `parse_mode = HTML` (matching the bot's existing, already-configured
default, `bot/loader.py:24`, §4) — no Markdown/MarkdownV2 parsing is introduced.

**DECISION, binding, the single most important invariant in this section, corrected this revision
(audit finding F-1)**: **all dynamic content — every one of `draft_title`, `draft_body`,
`hashtags`, `news_title`, `news_category`, and `news_url` — MUST be HTML-escaped (`<`, `>`, `&` at
minimum, via Python's standard-library `html.escape` or equivalent) before being interpolated into
the card string. This applies without exception to every DB-derived or AI-generated dynamic field
the card renders, including `news_url` (real, externally-sourced data — Phase 4's Source Collector,
unmodified — which routinely contains literal `&` characters in query strings; Telegram's HTML
parser rejects the entire message if any interpolated field contains an unescaped `&`, `<`, or
`>`). `ContentDraft.body`/`.title` (AI-generated, free-form text) and `NewsEvent.title`/`.category`/
`.url` (externally-sourced) are all treated as fully untrusted Telegram markup input, exactly as if
they came from an external, unvalidated source — never assumed safe.** Only the card's own literal
structural markup (`<b>...</b>` around labels) is trusted, unescaped HTML, since it is a
Python-authored string constant, never user-, AI-, or source-derived.

**DECISION, binding — no href-attribute escaping rule is needed**: since `news_url` is rendered as
plain escaped text, not as an `<a href="...">` anchor (§12), only the single, generic text-escaping
rule above applies to it. No separate visible-text-vs-href-attribute escaping split is introduced,
because no href attribute exists anywhere in this Contract's frozen card (§12).

**DECISION, binding — new module**: `bot/formatting.py`, a pure function (or small set of
functions), e.g. `render_editorial_card(card: EditorialInboxCard) -> str`, taking an
`EditorialInboxCard` and returning a plain Python `str` (the fully-escaped, ready-to-send HTML) —
**no `aiogram`/`Bot`/`Message` type appears in this module's signature or logic**, so it is
testable with zero Telegram mocking (§24).

**DECISION, binding — a single flat module, not a new subpackage**: unlike `bot/handlers/`/
`bot/keyboards/`/`bot/middlewares/` (each a subpackage with its own `__init__.py`), one new flat
module (`bot/formatting.py`) is authorized — a single pure function does not warrant a new
subpackage layer, and this Contract explicitly rejects inventing one merely for structural
symmetry with existing subpackages.

---

## 14. Message Length

**FACT (general Telegram Bot API constraint, not repository-specific, cited from established
platform knowledge, not repository source since no code currently enforces it)**: Telegram text
messages are capped at 4096 UTF-16 code units for `sendMessage`.

**DECISION, binding, corrected this revision (audit findings F-2 and N-1)**: **the final rendered
payload — after every character it will actually contain is present — is what must be proven to
fit, and it must be proven to fit using Telegram's own applicable measurement unit: UTF-16 code
units, not Python's built-in `len()`** (which counts Unicode code points). These two quantities
differ for any character outside the Basic Multilingual Plane (code point `> U+FFFF`) — the
overwhelming majority of emoji, including the card template's own static `📰` character (§12) —
each of which occupies **one** Python code point but **two** UTF-16 code units. `len(text) <= 4096`
therefore does **not** prove `telegram_utf16_length(text) <= 4096`; the two quantities can diverge,
and this is not merely theoretical: the frozen template itself introduces one such character on
every single card, before any AI-generated emoji in `draft_title`/`draft_body`/`hashtags` are even
considered (a realistic possibility for social-media-style generated text). Separately, HTML-
escaping (`&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`) strictly expands length; a pre-escape
truncation budget chosen without accounting for this expansion (e.g. a flat "3500 characters"
cutoff) is not provably safe against a worst-case, escaping-heavy `draft_body` either. This
Contract therefore replaces any "truncate raw text to N, then escape, then hope it still fits"
design with a **render → verify (in UTF-16 code units) → shrink → re-render → re-verify**
algorithm, frozen below. Per Decision Resolution §8: **truncate, do not split** — one card remains
one Telegram message in every case.

**DECISION, binding — frozen measurement semantics**: define
```
telegram_utf16_length(text) = the number of UTF-16 code units required to encode text
```
A conceptually valid, illustrative implementation is `len(text.encode("utf-16-le")) // 2` — this
Contract freezes the **semantic invariant**, not this exact helper's internal syntax; any
equivalent, correctly-tested UTF-16-code-unit-counting implementation satisfies this Contract.
**Python's built-in `len()` MUST NOT be used as the sole, authoritative Telegram-length safety
check.** `len()` may still be used internally for non-safety-critical purposes (e.g. picking the
next candidate truncation cut point while shrinking `draft_body`, step 3 below) — but the binding
pass/fail decision on whether a rendered card is safe to send **MUST** use
`telegram_utf16_length`, never `len()` alone.

**DECISION, binding — frozen safe ceiling**: `SAFE_LIMIT = 4096` **UTF-16 code units** (Telegram's
own hard limit — no separate, softer internal margin is needed, because the algorithm below
verifies the actual final rendered length, in the correct unit, directly, rather than estimating it
or measuring it in the wrong unit).

**DECISION, binding — what "final rendered" means for measurement purposes**: the string passed to
`telegram_utf16_length` MUST be the exact string that will be sent to Telegram — including every
dynamic value after HTML-escaping (§13), all static structural markup (e.g. `<b>...</b>`, the
`📰` category-line decoration, separators, line breaks), the hashtags line, any optional metadata
line rendered (§12), and the truncation marker if present. No component of the card may be
measured in isolation or omitted from the measured string.

**DECISION, binding — algorithm, deterministic, owned by `bot/formatting.py` (§13)**, corrected
this revision:
1. Render the full card (§12 template) with **every field HTML-escaped** (§13) and the complete,
   untruncated `draft_body`.
2. If `telegram_utf16_length(rendered) <= SAFE_LIMIT`: send as-is. Done — no truncation occurred.
3. Else, shorten only `draft_body` — **never** `news_title`, `news_category`, `hashtags`,
   `news_url`, or any structural markup. Cut the **raw, pre-escape** `draft_body` string at the
   last complete word boundary before a shrinking character budget (an internal, non-authoritative
   estimate MAY be used here purely to pick the next candidate cut point — it is not the safety
   check), append exactly one trailing truncation-marker character (`"…"`) to the raw
   (still-unescaped) text — ordinary Python string slicing operates on whole Unicode code points, so
   this cut cannot split a code point or produce invalid Unicode — **then** re-escape and re-render
   the entire card from scratch.
4. Re-check `telegram_utf16_length(rendered) <= SAFE_LIMIT`. If still too long, reduce the raw-body
   budget further (a fixed step or a binary search over the raw-body length are both acceptable,
   deterministic choices left to Planning) and repeat step 3.
5. The loop terminates the first time a re-rendered card's `telegram_utf16_length` fits, or when
   the raw `draft_body` budget reaches zero (rendering `draft_body` as the truncation marker alone,
   or as nothing at all). **Terminal fallback, corrected this revision (audit finding N-2)**: if the
   card, even with `draft_body` fully exhausted, still exceeds `SAFE_LIMIT` in
   `telegram_utf16_length`, the renderer (`bot/formatting.py`) **MUST NOT** return that oversized
   string for sending. This is treated as exactly one concrete trigger of §16 **Case E** ("One
   card's formatting fails... a genuinely malformed `EditorialInboxCard`"), not a new, competing
   failure policy: the renderer raises a dedicated, well-defined rendering-failure signal (e.g. a
   specific exception type) instead of returning a string; the handler's already-frozen per-card
   try/except (§16 Case E) catches it, logs it with safe diagnostic context (no stack trace or
   internal detail ever reaching the Telegram user, per §16's logging/user-facing boundary), skips
   sending that one card, and continues processing the remaining cards in the same `/news`
   invocation. No `EditorialTask`/`ContentDraft`/workflow state is touched by this path (§16/§17 — no
   write path exists to reach through regardless), and a `COMPLETED` workflow remains `COMPLETED`.

**DECISION, binding — why this is safe by construction**: truncation always operates on the
**raw**, pre-escape `draft_body` string, never on already-escaped HTML, so the algorithm can never
cut in the middle of an HTML entity (e.g. `&am` from `&amp;`) — escaping is re-applied fresh, in
full, to the complete (already-shortened) raw string on every iteration. Ordinary Python string
slicing on a `str` operates on whole Unicode code points, so truncation cannot produce invalid
Unicode (e.g. an unpaired surrogate); a cut may visually separate a multi-code-point grapheme
cluster (e.g. an emoji-plus-modifier sequence), but this still yields valid Unicode and valid HTML —
acceptable for this MVP, and no grapheme-cluster-aware truncation is required or authorized. Because
the length check is performed on the **actual, fully-rendered string**, measured in the **correct
unit** (`telegram_utf16_length`, not Python `len()`) — not an estimate and not the wrong unit — the
result is provably `<= SAFE_LIMIT` before being sent, in every case that does not hit the terminal
fallback above, which itself has a fully deterministic, never-oversized-send outcome.

**DECISION, binding — field priority preserved**: `news_category`, `news_title`, `hashtags`, and
`news_url` are never shortened or dropped by this algorithm — only `draft_body` shrinks, and title/
metadata remain rendered ahead of the body exactly as §12 already orders them.

**DECISION, binding — one card remains one Telegram message**: this algorithm truncates; it does
**not** split a card across multiple `sendMessage` calls. Multi-message splitting is not authorized
by Decision Resolution §8 and is not introduced here.

**RATIONALE**: `CopywritingCapability`'s prompt already instructs a short body (Phase 10,
unchanged), so the shrink loop (steps 3–5) and its terminal fallback are expected to execute zero
or one iteration, and to never reach the terminal fallback at all, in practice — this is a
defensive, provably-correct safeguard for the worst case, not an anticipated common path.

---

## 15. Navigation / Idempotency

**DECISION, binding**: **no callback pagination, no inline Previous/Next, no FSM, no command-page
arguments** (e.g. `/news 2`) for Phase 11. `/news` always returns up to 5 cards, sent as 5
separate sequential `message.answer()` calls (Decision Resolution §9).

**DECISION, binding — repeated invocation**: calling `/news` again intentionally returns the
current latest 5 eligible drafts — which may be identical to a prior invocation's result if no new
`ContentDraft` has been created since. **This is correct, intended pull-mode behavior, not a
duplicate-delivery bug.** There is no persisted delivery state (§16) to make this any different.

---

## 16. Failure Semantics

**DECISION, binding, per case**:

| Case | Behavior |
|---|---|
| **A. No eligible drafts** | Reply with one short, static, friendly message (e.g. "No recent editorial drafts yet.") — never an empty response, never silence. |
| **B. DB/query failure** | The exception is allowed to propagate out of the query call; the handler catches it at its own top-level boundary and replies with one generic, static message (e.g. "Something went wrong — please try again.") — **never** a stack trace, exception message, SQL text, or connection detail. |
| **C. Missing optional `NewsEvent`/source metadata** | Handled entirely by §12's card contract — the affected field/line is simply omitted, never rendered as `None`, empty, or broken. |
| **D. Telegram send failure** (e.g. `aiogram` raises on `message.answer()`) | Logged; does not raise further into anything that could reach `EditorialTask`/`ContentDraft` state (there is no such path in this design regardless, §5/§7/§9 — no write capability exists to protect *from*, but the boundary is stated explicitly per instruction). |
| **E. One card's formatting fails** (a genuinely malformed `EditorialInboxCard`, e.g. an escaping bug, **or** the §14 terminal length-safety fallback: the rendered card still exceeds `SAFE_LIMIT` even after `draft_body` is fully exhausted) | The single affected card's send is skipped/logged; **it must not abort the remaining, already-successfully-rendered cards in the same `/news` invocation** — a defensive per-card try/except in the handler's send loop. |

**CRITICAL INVARIANT, binding, restated exactly per instruction**: **a Telegram display/send
failure MUST NOT mutate `EditorialTask.status`, `ContentDraft`, or any workflow state, and MUST
NOT convert a `COMPLETED` AI workflow to `FAILED`.** This holds **by construction** for Phase 11's
design (§5/§7/§9 give this phase no write path to either model at all), not merely by discipline —
there is no code path through which a Telegram-layer failure could reach `WorkflowRunner`'s
exclusive `EditorialTask.status`-writing authority (Phase 5's frozen invariant, unchanged).

**DECISION, binding — logging vs. user-facing boundary**: full exception detail is logged
server-side (standard `logging`, matching every other component in this repository); only the
short, generic, static message reaches the Telegram user, in every failure case (B/D/E above).

---

## 17. Transaction Semantics

**DECISION, binding**: the Editorial Inbox reads persisted state only. **No commit is performed
anywhere in Phase 11's new code** — not in the handler, not in the query service. The session
opened by the handler (§9) is used exclusively for `session.get()`/`select()` reads and is closed
(via its `async with` context manager) at the end of the request, with no explicit
`session.commit()` call anywhere in the new code path.

**INFERENCE**: ordinary SQLAlchemy async-session read behavior (no pending changes to flush,
nothing to commit) means the existing `async_session_factory()`/`expire_on_commit=False` pattern
(§4, `database/session.py:14`) already fully owns whatever implicit rollback/close semantics are
needed on scope exit — **no new transaction machinery of any kind is invented or required.**

---

## 18. Frozen Architecture Boundaries

**DECISION, binding — MUST NOT MODIFY**, unless a future session finds direct, cited evidence
proving otherwise (none was found this session):

`workflows/runner.py` (`WorkflowRunner`), `capabilities/executor.py` (`CapabilityExecutor`),
`capabilities/registry.py` (`CapabilityRegistry`), `integrations/llm_gateway/protocol.py`
(`LLMGateway` Protocol), every file under `integrations/llm_gateway/providers/` (provider
adapters), `integrations/prompts/**` (`PromptRepository`), `capabilities/research_capability.py`,
`capabilities/intelligence_capability.py`, `capabilities/copywriting_capability.py`,
`capabilities/quality_capability.py`, `capabilities/scoring_capability.py`,
`services/content_draft_service.py` (`ContentDraftService`'s write behavior),
`scripts/run_content_generation.py`, `workflows/definitions/content_generation.py`, every file
under `database/models/`, every Alembic migration file, `database/session.py`,
`schemas/content_draft.py`, `schemas/editorial_task.py`, `services/workflow_service.py`,
`integrations/sources/telegram_source.py` (the unrelated Telethon source collector, §4 of
Discovery), `bot/main.py`, `bot/loader.py`, `bot/handlers/__init__.py` (§4's correction),
`bot/handlers/{start,digest,status,settings}.py`, `bot/keyboards/__init__.py`,
`bot/middlewares/__init__.py`, `database/models/user.py` (the model itself is untouched; only its
*wiring* is deferred, §11).

**No evidence surfaced this session that any of the above requires amendment.** If a future
implementation session believes otherwise, this Contract requires that belief be documented as a
source contradiction and escalated, not silently acted on (per this Contract's own governing
instruction).

---

## 19. Deferred Editorial Actions

**DECISION, binding — all three explicitly absent, no placeholder, no hidden field**:

- **APPROVE**: not implemented. No button, no callback, no state field, no future-state
  placeholder of any kind.
- **REJECT**: not implemented. Same.
- **REWORK**: not implemented. Same.

**DECISION, binding — no placeholder callback pretending any of these exist**: Phase 11 does not
ship a disabled/greyed-out button, a "coming soon" callback handler, or any code that implies
these actions exist in any partial form.

**BINDING SEMANTIC INVARIANT** (Decision Resolution §14, restated exactly): **human rejection,
when eventually implemented, MUST NOT retroactively redefine a successfully completed AI workflow
as `FAILED`, unless a future, explicitly governed architecture change deliberately redefines that
semantic model.** `WorkflowRunner` remains the sole writer of `EditorialTask.status` (§4, §16) —
this invariant is not new to Phase 11, only restated for a phase that, for the first time, gives a
human a UI surface from which they might otherwise expect to affect it.

**For future Rework, one already-known architectural fact is noted, nothing more**: a `COMPLETED`
`EditorialTask` cannot simply be rerun (`workflows/runner.py`'s `TaskAlreadyCompletedError` guard,
re-confirmed unchanged this session, `workflows/runner.py:113-117`). **No regeneration system is
designed here.**

---

## 20. Push / Scheduler / Publication

**DECISION, binding — push/scheduler, frozen absent**: automatic push on `ContentDraft` creation;
any scheduler; any polling/watcher worker; any delivery queue; any background Telegram publisher;
any "temporary" background loop of any kind, however small.

**DECISION, binding**: Phase 11 is exclusively **user-triggered pull**. No code path in this phase
runs without a human first sending `/news`.

**DECISION, binding — publication**: **Editorial Inbox ≠ Publication.** Phase 11 MUST NOT publish
to any public Telegram channel; MUST NOT interpret a user merely *viewing* a card as approval;
MUST NOT interpret any future approval action as automatic publication; MUST NOT store any
"published" state. Publication requires its own, future, explicitly governed phase — **FACT**, no
publishing mechanism to any public-facing Telegram channel/audience exists anywhere in this
repository today (re-confirmed this session).

---

## 21. Meme / Image Boundary

**DECISION, binding — meme/image**: no meme generation, no image generation, no `LLMGateway`
amendment for image output, no media-sending architecture added for memes, in any form. **FACT**,
re-confirmed this session (`grep -rln "generate_image\|image_generation\|MemeCapability"` across
every `.py` file returns nothing) — Phase 11 is text-only editorial inbox delivery, exactly as
Phase 10 Contract §11 already established for the pipeline itself. Meme/image generation remains a
wholly separate, unstarted future phase.

---

## 22. Database / Migration

**DECISION, binding**: **NO MIGRATION.** Every field the MVP card (§12) needs already exists,
confirmed reachable with zero schema change (§4/§5).

**DECISION, binding — explicitly prohibited during Phase 11**, regardless of any perceived
convenience: adding an approval/rejection status column or enum; a `delivered_at` column; a
`telegram_message_id` column; a `destination_chat_id` column; a review-state enum; a revision
table; a delivery table.

**If a future implementation session discovers a migration is genuinely necessary**: STOP, do not
improvise one, and return to architecture review — this Contract does not pre-authorize any
migration under any circumstance for Phase 11's own scope.

---

## 23. Authorized File Scope

**DECISION, binding — exhaustive.**

**Existing files authorized for narrow edit**:
- `bot/handlers/news.py` — replace the placeholder handler body with the real query → format →
  send flow (§9).

**New files authorized to create**:
- `schemas/editorial_inbox.py` — the `EditorialInboxCard` DTO (§8).
- `services/editorial_inbox_service.py` — the read-only query service (§7).
- `bot/formatting.py` — the pure HTML rendering/escaping helper (§13).

**Test files** (exact names an implementer should use, not frozen beyond this level of
specificity — file organization within `tests/` may vary slightly at Planning's discretion):
- A test file for the query service (e.g. `tests/test_editorial_inbox_service.py`), mirroring
  `tests/test_content_draft_service.py`'s real-database conventions.
- A test file for the formatting/escaping helper (e.g. `tests/test_editorial_card_formatting.py`),
  pure unit tests, no DB, no Telegram.
- A test file for the handler (e.g. `tests/test_news_handler.py`), calling the handler function
  directly with a constructed `Message` and a fake/mock `Bot`, mirroring Phase 10's "test the
  function, not the thin wrapper" discipline.

**Files explicitly frozen** (§18's full list, restated here as this section's own binding
boundary — not a lesser restatement, the same one).

**No broad directory is authorized.** No file outside this exhaustive list may be created or
edited to implement Phase 11's MVP.

---

## 24. Testing Requirements

Binding minimums for whichever future implementation phase builds against this Contract:

**Query/service tests** (`services/editorial_inbox_service.py`, real test database):
- Returns only `ContentDraft` rows linked to a `COMPLETED` `EditorialTask`.
- Excludes drafts linked to `FAILED`/`CREATED`/`RUNNING`/`WAITING` tasks.
- Newest-first ordering (§6), with the `id`-based tie-break exercised if practical to construct.
- Limit of 5 is enforced when more than 5 eligible rows exist.
- Empty-result behavior (zero eligible drafts) returns an empty list, not an error.
- Joined `NewsEvent` metadata (title/category/url/published_at) is correctly attached to each
  card.
- A draft whose `NewsEvent.url` is `null` is handled without error, `news_url` is `None` on the
  DTO.

**Renderer tests** (`bot/formatting.py`, pure, no DB, no Telegram):
- HTML-escaping is applied to `draft_title`.
- HTML-escaping is applied to `draft_body`.
- HTML-escaping is applied to `news_title`/`news_category` (and any other interpolated dynamic
  value).
- HTML-escaping is applied to `news_url` (audit finding F-1) — including a case where `news_url`
  contains a literal `&` (a realistic query-string character).
- `news_url` is never rendered inside an `<a href="...">` anchor — confirmed rendered as plain
  escaped text only (§12/§13).
- Hashtag rendering (joined, space-separated; empty/`None` hashtags omit the line entirely).
- **Worst-case escaping expansion** (audit finding F-2): a `draft_body` constructed to be dense
  with `&`/`<`/`>` characters, long enough that pre-escape length would appear to fit but
  post-escape length would not, is truncated such that the **final, fully-rendered payload**
  (post-escape, post-template-assembly) satisfies `telegram_utf16_length(payload) <= 4096` —
  proving §14's render-verify-shrink algorithm end to end, not merely the pre-escape truncation
  step in isolation.
- Truncation never produces a malformed HTML entity or a broken tag — the final rendered string
  contains no partial/dangling entity sequence (e.g. no trailing `&`, `&a`, `&am`, or `&amp`
  without a closing `;`) and no unclosed `<b>` tag.
- A body that fits without truncation is sent byte-for-byte as rendered — the shrink loop performs
  zero iterations and does not alter title/category/hashtags/`news_url`.
- **UTF-16 length semantics** (audit finding N-1):
  - A BMP-only (no astral characters) payload's `telegram_utf16_length` equals its Python `len()` —
    confirming the two measures agree in the ordinary case.
  - A payload containing astral-plane characters (e.g. emoji such as the template's own `📰`, or an
    emoji injected into `draft_title`/`draft_body`/`hashtags`) is measured by `telegram_utf16_length`
    as **2 code units per astral character**, not 1 — confirming astral characters are not
    undercounted.
  - A constructed payload for which `len(payload) <= 4096` but `telegram_utf16_length(payload) >
    4096` (achievable by padding with enough astral-plane characters) is correctly detected as
    **oversized** by the renderer's safety check — proving `len()` alone would have wrongly passed
    this case and the corrected check catches it.
  - The static card emoji (`📰`, §12) is included in every length measurement — no component of the
    template is measured in isolation or excluded.
  - HTML-escaping expansion and UTF-16 astral-character counting are both correctly accounted for
    **together** in at least one combined worst-case test (a `draft_body` that is both
    escaping-heavy and astral-character-heavy).
  - Every card the renderer returns for sending (i.e. every non-error render) satisfies
    `telegram_utf16_length(payload) <= 4096` — a general invariant check, not only a targeted
    worst-case example.
- **Terminal fallback** (audit finding N-2): a `draft_body` engineered so that even fully exhausted
  (empty/marker-only) the card still exceeds `SAFE_LIMIT` causes the renderer to raise its
  dedicated rendering-failure signal — **never** a returned oversized string — proving §14 step 5's
  terminal-fallback path maps to §16 Case E as frozen.

**Handler tests** (`bot/handlers/news.py`'s handler function, called directly):
- `/news` calls the query service with the frozen limit (5).
- Empty-inbox response matches §16 case A.
- Sends exactly the expected number of card messages for a given query result.
- No AI-generation or workflow-mutation code path exists to test the *absence* of — verified by
  the mechanical import-boundary check below, not by a runtime assertion of "nothing happened."
- DB/service failure produces the safe, generic user-facing response (§16 case B), never a raw
  exception message.
- A message constructed with `is_topic_message=True` and a `message_thread_id` set (simulating
  `/news` invoked inside a forum topic) is sent via the same `message.answer()` call used for every
  other chat type — the handler does not override, strip, or otherwise interfere with `aiogram`'s
  own automatic `message_thread_id` propagation (§10, audit finding F-3). This test targets the
  handler's own code (that it does not fight the library's default), not `aiogram`'s internal
  behavior itself, which the audit already verified directly against the pinned version
  (`aiogram==3.29.1`).
- Given 5 eligible drafts where one card's render raises the §14 terminal-fallback rendering-
  failure signal (audit finding N-2), the handler's per-card try/except catches it, logs it, skips
  sending only that one card, and still sends the other 4 — proving §16 Case E's multi-card
  behavior governs this path, with no second/competing failure mechanism.

**Mechanical/regression check**: a dedicated test (mirroring this repository's own established
"AST-based import check" convention, e.g. `tests/test_capability_testing_convention.py`'s
approach) confirming `services/editorial_inbox_service.py` and `bot/formatting.py` import neither
`workflows.runner` nor `capabilities.executor` nor any `capabilities.*_capability` module nor
`scripts.run_content_generation` — proving the "no AI generation, no workflow mutation" invariant
mechanically, not only by code review.

**Existing-command regression**: `/start`, `/digest`, `/status`, `/settings` remain unaffected —
verified by re-running their existing (currently trivial) placeholder behavior unchanged, since
none of their files are touched (§18/§23).

**No live Telegram API call is part of the automated suite**, matching Phase 7 §15.5's unbroken
no-real-network-call discipline.

---

## 25. Manual Live Validation

**DECISION, binding — one manual, out-of-band live-Telegram smoke test**, the final Definition-of-
Done gate (§26), **not executed during Contract writing or by this document**:

Must verify: the real bot starts in a provisioned environment (real `TELEGRAM_BOT_TOKEN`); `/news`
reaches the real handler; real, DB-backed drafts (from a real, previously-completed
`CONTENT_GENERATION` run — e.g. Phase 10's own M6 validation data) are retrieved; cards render
successfully in a real Telegram client (HTML is accepted and displays correctly, not as literal
tags); no `EditorialTask`/`ContentDraft`/workflow state is mutated by the invocation (verified by
a database check before/after, mirroring Phase 10's own M6 verification discipline).

**Explicitly not required for this gate**: public-channel publishing; any callback; Approve/
Reject/Rework; any scheduler; any meme/image content.

---

## 26. Definition of Done

Phase 11 MVP is complete only when every one of the following holds:

1. `/news` is no longer placeholder behavior — it executes the real query → format → send flow.
2. `/news` returns up to 5 latest eligible editorial drafts.
3. Only drafts linked to a `COMPLETED` `EditorialTask` appear.
4. Ordering is deterministic, newest-first, with the frozen tie-break.
5. Telegram cards conform exactly to §12's frozen contract.
6. All dynamic content is HTML-escaped before sending (§13) — proven by the renderer tests (§24).
7. The empty-inbox state is handled per §16 case A.
8. DB/service failures are handled per §16 case B — no internal detail ever reaches a Telegram
   user.
9. No database mutation of any kind is introduced by any Phase 11 code path (§17) — proven by the
   mechanical import-boundary check (§24).
10. No schema/migration change exists anywhere in this diff (§22).
11. Every frozen Phase 5–10 component (§18) remains byte-for-byte unchanged.
12. Every mandatory automated test (§24) exists and passes.
13. The full repository regression suite (`python -m pytest -q`) passes, including every
    pre-existing test, unmodified.
14. `python -m ruff check .` passes clean.
15. Targeted `mypy` passes clean on every changed/new Python file.
16. `python -m scripts.validate_architecture` reports 0 violations.
17. Secret/security hygiene passes (no credential committed, `.env` remains untracked, no debug
    bypass).
18. The one manual live-Telegram smoke (§25) passes.
19. No Approve/Reject/Rework/push/scheduler/publication/meme/image functionality exists anywhere
    in the shipped diff (§19/§20/§21).
20. No in-app authorization exists, and the Contract's binding security assumption (§11) is
    reproduced, unsoftened, in whatever final documentation accompanies the shipped feature.

---

## 27. Risks

- **No application-level authorization** (§11): `/news` is reachable by anyone who can message the
  bot for the duration of Phase 11. Mitigation: this is an explicit, documented, human-decided
  tradeoff (Decision Resolution §10), not an oversight — mitigated entirely by
  operational/deployment access control outside this repository's own code.
- **`ContentDraft.created_at` and `ContentDraft.task_id` carry no index** (§4/§6): the eligibility
  query's `ORDER BY created_at DESC` and the `task_id` join both currently rely on an unindexed
  column. At Phase 11's realistic data volume (Phase 10's own pipeline is manually, not
  automatically, triggered — §20 of this Contract, §6 of Decision Resolution) this is not expected
  to be a real performance problem, but it is named here honestly rather than assumed away; adding
  an index later, if ever needed, is a narrow, low-risk, backward-compatible migration, not an
  architecture change.
- **Direct FK joins without ORM `relationship()`** (§5): consistent with this repository's own,
  already-established convention throughout Phase 9/10 — not a new risk Phase 11 introduces, but
  named because it means every future maintainer must continue the same manual-lookup discipline,
  not assume an ORM relationship exists.
- **Repeated `/news` display is by design, not a bug** (§15): named explicitly so a future
  bug report isn't filed against intended pull-mode behavior.
- **Telegram availability is fully independent from persisted AI-workflow state** (§16): this is
  the single most important isolation property this Contract establishes for Phase 11, verified as
  holding by construction, not by discipline alone — a Telegram outage, rate limit, or malformed-
  message error can never retroactively affect `TaskStatus.COMPLETED` or a persisted
  `ContentDraft` row, because no code path in this phase can reach either as a write target.
- **HTML-escaping is a genuinely new concern for this repository** (§13): the first time any bot
  handler formats dynamic, LLM-generated text into an HTML-parse-mode message. Mitigated by the
  binding escaping invariant (§13) and its dedicated test coverage (§24), not left to convention
  alone.

---

## 28. Canonical Rules

1. Phase 11 is **read-only** — no code path writes to `ContentDraft`, `EditorialTask`, or any
   other persisted model.
2. Phase 11 is **pull-only** — no code runs without a human first invoking `/news`.
3. `/news` is the Editorial Inbox entry point; no new command is introduced.
4. The default and maximum result count is **5**.
5. Only drafts linked to a `COMPLETED` `EditorialTask` are eligible for display.
6. Phase 11 performs **no** workflow or content mutation, anywhere, under any circumstance.
7. Phase 11 adds **no** database migration.
8. Phase 11 adds **no** in-app authorization; the binding security assumption (§11) governs
   instead.
9. All dynamic Telegram HTML content is **always** escaped before sending — no exception.
10. **No** Approve, Reject, or Rework functionality exists in Phase 11, in any form, including
    placeholders.
11. **No** push delivery, scheduler, or background worker exists in Phase 11.
12. **No** public publication exists in Phase 11.
13. **No** meme or image generation exists in Phase 11.
14. Every frozen Phase 5–10 component (§18) remains unchanged.
15. Any future editorial write action requires a dedicated authorization/security design step
    first — this is a binding prerequisite on all future work, not merely a Phase 11 note.

---

## 29. Acceptance Checklist

Self-audited before this Contract is submitted for review, per the governing instruction's own
12-question self-audit:

1. **Did I accidentally introduce a write path?** No — §7/§9/§17 each explicitly forbid any
   commit or mutation; the mechanical import-boundary test (§24) proves this, not just prose.
2. **Did I accidentally imply authorization exists?** No — §11 states the binding security
   assumption exactly as decided, unsoftened; §4/§18 confirm `User`/`UserRole` remain unwired.
3. **Did I accidentally introduce callbacks/actions?** No — §10/§15/§19 explicitly and repeatedly
   exclude any callback, keyboard, or FSM.
4. **Did I accidentally require a migration?** No — §22 states NO MIGRATION with evidence, and
   explicitly prohibits every plausible speculative column.
5. **Did I accidentally couple Telegram to `WorkflowRunner`?** No — §7's ownership model and §18's
   frozen-file list both exclude `workflows/runner.py` entirely; §5's read path never touches it.
6. **Did I accidentally make Telegram failure affect AI workflow success?** No — §16's critical
   invariant states this holds by construction, and explains exactly why (no write path exists to
   violate it through).
7. **Did I accidentally introduce push/scheduler behavior?** No — §20 explicitly freezes both
   absent.
8. **Did I accidentally imply public publishing?** No — §21 explicitly distinguishes inbox from
   publication and confirms no publishing mechanism exists.
9. **Did I accidentally absorb meme/image generation?** No — §21 re-confirms zero such
   infrastructure exists and explicitly excludes it.
10. **Is the implementation file scope exhaustive enough to be actionable?** Yes — §23 names every
    file precisely (one existing edit, three new production files, three test files), with no
    broad directory authorized.
11. **Are all test obligations deterministic?** Yes — §24's obligations are all concrete,
    checkable conditions (exact filter, exact ordering, exact escaping behavior), not vague
    aspirations.
12. **Can Planning implement this Contract without making a new architectural decision?** Yes —
    every module name, DTO shape, ownership boundary, query filter, card format, escaping rule,
    and file scope is frozen at implementation-actionable precision; the only items explicitly
    left to Planning's own discretion are cosmetic (exact test file naming within `tests/`) or
    genuinely deferred to a future Contract (Approve/Reject/Rework/authorization design, §19/§11).

**No self-audit question surfaced a defect requiring correction before this Contract is
submitted.**

---

PHASE 11 CONTRACT READY FOR AUDIT
