# Phase 11 — Decision Resolution
## Telegram Editorial Inbox

**Status: decision document only.** No production code, test, migration, or Architecture Contract
was produced by this document. Every decision below is grounded in
`docs/phase11_telegram_editorial_inbox_discovery.md` ("Discovery"), cited by section. Where a
choice genuinely cannot be resolved from source or existing product direction, it is marked
**HUMAN DECISION REQUIRED**, not guessed.

---

## 1. Executive Decision Summary

Phase 11 MVP is a **read-only, pull-mode Telegram Editorial Inbox**: an extended `/news` command
that queries already-persisted `ContentDraft` rows and renders them as cards, in the chat the
command was invoked from. No schema change, no scheduler, no push delivery, no Approve/Reject/
Rework actions, no callbacks or keyboards, no public publication, no meme/image generation. It
adds exactly one new, thin, additive read/presentation layer on top of Phase 10's frozen pipeline
— `WorkflowRunner`, `CapabilityExecutor`, `CapabilityRegistry`, every Capability, `LLMGateway`,
`PromptRepository`, `ContentDraftService`, and every database model remain untouched.

**§10 (Authorization) was the one item requiring human product/risk-tolerance input; it has now
been resolved** — Phase 11 MVP ships with **no in-app authorization enforcement**. `User`/
`UserRole` is not wired into the bot during Phase 11. Access is assumed to be controlled
operationally, outside this application, at the Telegram/deployment boundary — a binding security
assumption the Architecture Contract must state explicitly, not imply away. A dedicated
authorization/security design step is a mandatory prerequisite for any future editorial write
action (Approve/Reject/Rework/Publish/administrative mutation) — frozen as an invariant (§24),
not designed here.

---

## 2. Phase Name

**DECISION**: **Phase 11 — Telegram Editorial Inbox** (drop "Delivery" from the original working
name).

**RATIONALE**: "Delivery" implies a push/send mechanism. The resolved MVP (§3–§4) is exclusively
pull-mode — the bot never initiates contact, it only responds to a command. Naming the phase
"Delivery" would misdescribe its own frozen scope from the title down.

**CONSEQUENCES**: future phases that add push delivery should carry their own, separately-named
milestone (e.g. "Phase 11.x — Push Delivery") rather than being silently folded into "Phase 11"
after the fact.

**OUT OF SCOPE**: renaming any existing file, doc, or commit from earlier phases.

---

## 3. MVP Scope

**DECISION**: **Option A — Read-only Editorial Inbox** (Discovery §16/§17).

### In Scope
- One command (§5) that queries recent/relevant `ContentDraft` rows (§6) and renders each as a
  formatted card (§7) in the invoking chat (§11).
- The query/formatting logic as a new, thin, additive layer (§20/§21).
- Automated tests for the query/formatting logic + one manual live-Telegram smoke (§22).

### Out of Scope
- Approve (§13), Reject (§14), Rework/Regenerate (§15) — no buttons, no callbacks, no write path
  from `bot/` into any model.
- Push/automatic delivery, any scheduler (§16).
- Public-channel publication (§17).
- Meme/image generation (§18).
- Any database migration (§19).
- Pagination beyond the simplest possible mechanism (§9).
- Multi-chat routing, forum/topic support (§11).

**RATIONALE**: Discovery §5 (ownership), §6/§13 (push requires a scheduler and new persistence
Phase 10 already excluded), and §11 (Rework's only safe form still needs a long-running-callback
UX problem nobody has designed) all independently converge on the same minimal slice. Options B/C/D
each require at least one genuinely new architectural capability (a write path, an authorization
system, or a scheduler) that Option A needs none of.

**CONSEQUENCES**: the SMM team gets real, immediate value (seeing AI-generated drafts without a
manual DB query) with the smallest possible new surface area. Approve/Reject/Rework become
well-scoped future milestones, not "maybe partially implemented" ambiguity.

**OUT OF SCOPE**: no action button of any kind ships in this MVP, full stop.

---

## 4. Delivery Model

**DECISION**: **PULL**.

**RATIONALE**: Discovery §6 — pull is the only one of the three models requiring no scheduler
(Phase 10 Contract §2 already excludes "any scheduler or automatic-execution mechanism," and no
evidence in this repository lifts that boundary) and no new delivery-state persistence (§13: reads
are naturally idempotent; nothing is "sent," so nothing can be duplicate-sent).

**UX at the product level**:
```
SMM team member sends /news in a chat with the bot
    ↓
bot queries the N most recent ContentDraft rows (whose EditorialTask is COMPLETED)
    ↓
bot renders each as a card (§7), in that same chat
```

**CONSEQUENCES**: the SMM team must actively check the bot; nothing is pushed to them. This is an
accepted, explicit tradeoff for MVP simplicity, not an oversight.

**OUT OF SCOPE**: any poller, watcher, or background process of any kind.

---

## 5. Command / Entry Point

**DECISION**: **extend `/news`** to become the inbox entry point. Do not introduce a new `/inbox`
or `/drafts` command for the MVP. `/digest` remains unrelated and untouched.

**RATIONALE**: Discovery §3 flagged this as a genuine, source-unanswerable naming question (open
question 1). Resolved here per the project's own stated product direction: `/news` already
signals "editorial/news content" to a user, and this repository's convention is one router per
command (`bot/handlers/__init__.py`) — extending an existing, already-registered command avoids a
second near-duplicate entry point for the same concept. `/digest` is left alone since nothing in
Discovery or product intent ties it to per-draft review (it more plausibly maps to a future
aggregate/summary view, not this MVP's scope).

**CONSEQUENCES**: `bot/handlers/news.py`'s current placeholder handler is replaced with the real
query+render logic (§19/§26). The command's help text/description (if any is ever added) should
describe "recent AI-generated drafts," not raw `NewsEvent` listings, to avoid confusing the two
concepts Discovery §4 distinguishes.

**OUT OF SCOPE**: renaming `/news` itself, adding a second command that duplicates the same
function, or touching `/start`/`/digest`/`/status`/`/settings`'s existing placeholder behavior.

---

## 6. Inbox Query Semantics

**DECISION**: show the **N most recently created `ContentDraft` rows whose owning `EditorialTask`
has `status == COMPLETED`**, ordered **newest-first** by `ContentDraft.created_at`, with **N = 5**
as the default limit. No "pending" persisted state is introduced or implied — "recent" is a
derived, computed-at-query-time concept, not a stored one.

**RATIONALE**: Discovery §9/§10 confirm no editorial-review state exists yet, so there is no
persisted concept of "pending" to filter on — inventing one would be exactly the kind of
speculative state machine this session is instructed to avoid. Filtering to `COMPLETED` tasks
only (via the `task_id` → `EditorialTask.status` hop, §4) excludes the disclosed,
accepted-as-rare `COMPLETED`-with-no-draft gap by construction (a task with no draft simply
produces no row to show) and naturally excludes any hypothetical future non-`COMPLETED`-sourced
draft. A small, fixed limit (5) keeps the MVP's single Telegram response well within message-count
and length norms without needing pagination (§9) for a first release.

**CONSEQUENCES**: drafts from `FAILED` tasks never appear (there are none — Contract §7.1 already
guarantees a draft only exists for a `COMPLETED` task). Once more than 5 drafts exist, older ones
become invisible to `/news` without pagination (§9) or a time-window/history view — an accepted
MVP limitation, not a defect.

**OUT OF SCOPE**: any "mark as seen"/"pending" persisted state; any time-window filter beyond the
simple "most recent N."

---

## 7. Editorial Card Contract

**DECISION**: freeze the MVP card to Discovery §8's recommended shape, using only already-reachable
fields:

**Required fields** (always present or explicitly handled if null):
- `NewsEvent.category`, `NewsEvent.published_at`
- `NewsEvent.title` (the original, pre-AI headline)
- `ContentDraft.title`, `ContentDraft.body` (the generated content)
- `ContentDraft.hashtags` (joined, space-separated)

**Optional fields** (rendered only if present):
- `NewsEvent.url` — omitted entirely from the card if `null`, never rendered as an empty/broken
  link.

**Explicitly excluded from the MVP card**: `QualityCapability`'s `passed`/`issues` and
`ScoringCapability`'s `score`/`rationale` (Discovery §4/§8) — both require an extra JSON-blob
parsing hop into `EditorialTask.workflow["step_results"]` for zero read-only-MVP value; source
name (`NewsSource.name`, one further FK hop) is likewise excluded for MVP simplicity, not because
it's unreachable.

**Body length**: send the **full `ContentDraft.body`** as-is for the MVP; do **not** truncate.
`CopywritingCapability`'s prompt already instructs the model to keep the body "suitable for a
short social post" (Discovery §8), so truncation is not expected to be needed in practice — but a
defensive split/truncate-if-over-4096-characters safeguard must still exist at the formatting
layer (§8 below), since nothing in the schema enforces this at write time.

**RATIONALE**: every included field is confirmed reachable with zero migration (Discovery §4);
excluding score/quality/source-name keeps the MVP's query to the simple two-hop pattern already
established (`ContentDraft` → `EditorialTask` → `NewsEvent`), avoiding new JSON-parsing logic for
a first release.

**CONSEQUENCES**: a future milestone could add the quality/score line to the card without any
schema change — purely additive.

**OUT OF SCOPE**: any new column to cache these fields onto `ContentDraft` itself; a migration
"for richer cards" is explicitly rejected per instruction (§19 below already prohibits this).

---

## 8. Telegram Formatting

**DECISION**: **HTML** parse mode (matching the existing, already-configured bot default —
Discovery §8, `bot/loader.py:24`). All dynamic (LLM-generated or NewsEvent-sourced) text fields
(`ContentDraft.title`, `.body`, `NewsEvent.title`) **must be HTML-escaped** (`<`, `>`, `&` at
minimum) before insertion into the message string; only the card's own literal structural markup
(e.g. `<b>...</b>` around field labels) is trusted, unescaped HTML.

**Message-length behavior**: if the fully-rendered card would exceed Telegram's 4096-character
limit, **truncate the body** (not the title/hashtags) with a trailing indicator (e.g. "…"), never
silently drop the message or crash the handler. Do not implement multi-message splitting for the
MVP — a single, defensively-truncated message is sufficient.

**RATIONALE**: Discovery §8 confirms HTML is this repository's only established convention (no
Markdown parsing exists anywhere), and that no escaping utility exists yet — Phase 11 is the first
place dynamic content meets this bot's HTML-parse-mode default, so escaping must be handled
deliberately, not assumed safe. Truncation is preferred over splitting for MVP simplicity — an
SMM reviewer opening a truncated card can still identify and act on it externally if needed;
message-splitting adds complexity (message-count tracking, edit-coordination) with no MVP-level
product value.

**CONSEQUENCES**: one new, small, dedicated escaping/formatting helper is required — the first of
its kind in `bot/` (§21/§26).

**OUT OF SCOPE**: MarkdownV2, multi-message splitting, rich media (images, attachments).

---

## 9. Pagination / Navigation

**DECISION**: **Option A — return the latest N (=5, §6) cards in one command response**, sent as N
separate, sequential messages (one `message.answer()` call per card) rather than one giant
concatenated message. No inline Previous/Next pagination, no command arguments (`/news 2`).

**RATIONALE**: Discovery §8/§20 confirm zero keyboard/callback infrastructure exists today
(`bot/keyboards/__init__.py` is an empty placeholder) — introducing inline pagination (Option B)
would require building the first-ever callback handler in this repository purely for navigation,
a real new architectural surface (state per user/session, callback_data design) for a feature
whose entire product value is "see the last few drafts." Command-argument pagination (Option C)
adds parsing complexity for the same marginal benefit. Five separate messages is simple, requires
zero new UI primitive, and is trivially replaceable by real pagination later once Approve/Reject
(which do need callbacks) are added anyway.

**CONSEQUENCES**: a user invoking `/news` when 5 drafts exist receives 5 messages in sequence, not
one; this is an accepted MVP tradeoff, not a bug.

**OUT OF SCOPE**: any inline keyboard, any callback_data design, any command-argument parsing.

---

## 10. Authorization

**RESOLVED — HUMAN DECISION PROVIDED.**

**DECISION**: **NO IN-APP AUTHORIZATION ENFORCEMENT for Phase 11.** Phase 11 remains a read-only
Editorial Inbox. Access is assumed to be controlled **operationally**, through the Telegram
deployment/workspace boundary (who has the bot token; who is in the chat the bot operates in) —
**not** by any application-level check.

**Explicitly, none of the following are added in Phase 11**:
- `User` bootstrap logic of any kind.
- Automatic `User` row creation (e.g. on first `/start`).
- Allowlist logic against the `User` table.
- RBAC/authorization middleware.
- `OWNER` bootstrap.
- Any role/permission enforcement, anywhere in `bot/`.
- Any authorization-related migration.
- Any hardcoded owner/admin Telegram ID, in config or code.

`User`/`UserRole` (Discovery §12: exists, `telegram_id`/`role`/`permissions`, wired into nothing)
**is not wired into the bot during Phase 11**, in any form.

**RATIONALE**: Phase 11 contains no write-side editorial action — it only reads persisted
`ContentDraft` data and renders it via `/news`. Wiring `User`/`UserRole` in now would force Phase
11 to also solve a cluster of lifecycle problems that don't belong to a read-only inbox: how
`User` rows get created, first-`OWNER` bootstrap, Telegram-identity onboarding, role assignment,
and permissions lifecycle (Discovery §12's own open questions 2/3) — each a real, non-trivial
design problem that would materially expand this MVP's scope for a feature (view-only access) that
doesn't yet justify that cost. Deferring authorization entirely, until a real write action exists,
keeps Phase 11 exactly as small as §3 already commits to.

**BINDING SECURITY ASSUMPTION** (the Architecture Contract must state this explicitly, verbatim in
substance, not imply it away): **Phase 11 provides no application-level authorization boundary for
`/news`. Anyone who can reach and invoke the bot may access the Phase 11 inbox, unless access is
restricted operationally at the Telegram/deployment level.** The Contract must not describe the
bot as application-level access-controlled, and must not imply `User`/`UserRole` currently
protects `/news` — it does not, and will not, for the duration of Phase 11.

**FUTURE SECURITY GATE, frozen as a binding invariant** (§24): before any editorial write action
is introduced — Approve, Reject, Rework/Regenerate, Publish, or any administrative editorial
mutation — the project **MUST** perform a dedicated authorization/security design step, resolving
at minimum: `User` creation/bootstrap; Telegram `telegram_id` → `User` mapping; `OWNER` bootstrap;
role semantics; permissions; unauthorized-user behavior; callback authorization; stale/replayed-
action protection where applicable. That system is explicitly **not** designed or implemented now
— naming it here only freezes that it must happen first, before write actions, not what it looks
like.

**CONSEQUENCES**: `/news` ships reachable by anyone who can message the bot for the duration of
Phase 11. This is an accepted, explicitly-documented risk, not an oversight — mitigated entirely
by operational/deployment controls outside this repository's own code.

**OUT OF SCOPE**: everything in the explicit "none of the following are added" list above, without
exception, for the duration of Phase 11.

---

## 11. Destination Semantics

**DECISION**: **no persisted destination-chat configuration is needed or added.** The bot replies
in `message.chat.id` — whatever chat the command was invoked from (private chat or a group the bot
is already a member of) — exactly as every existing placeholder handler already implicitly does
via `message.answer()`.

**Supported chat types for MVP**: private chat and group/supergroup (both work identically via
`message.answer()`, no new code needed for either). **Forum/topic (`message_thread_id`) support is
explicitly not added.**

**RATIONALE**: Discovery §7 confirms zero destination-addressing configuration exists anywhere
(`Settings` has no `chat_id`/`editorial_chat_id`), and confirms — precisely, per instruction —
that no product document in this repository ever specified a Telegram forum-topic or "separate
folder" delivery mechanism as a technical requirement; any such idea, if discussed elsewhere, was
never translated into a requirement here. Since delivery is pull-mode (§4), "destination" is
structurally just "wherever the command was typed" — no routing decision exists to make.

**CONSEQUENCES**: if a future phase adds push delivery, a destination concept (most simply, one
fixed `editorial_chat_id` setting) becomes necessary at that point — explicitly not designed
further here, per Discovery §7's own recommendation.

**OUT OF SCOPE**: any multi-chat routing, any forum/topic support, any per-user delivery
preference.

---

## 12. Delivery Idempotency

**DECISION**: **no delivery persistence of any kind is added.** Phase 11 MVP does not require an
answer to "has this `ContentDraft` already been sent to Telegram" — because nothing is ever
"sent" in the push sense; `/news` is a read query, explicitly and intentionally repeatable.

**Explicit statement, per instruction**: repeated `/news` invocations showing the same draft(s)
again is **intended behavior, not a bug** — pull-mode has no concept of "already delivered."

**RATIONALE**: Discovery §13 — this is a direct, load-bearing consequence of choosing pull over
push (§4): duplicate-delivery risk is a push-mode-only cost, and building the persistence needed
to avoid it (a `telegram_message_id`/`sent_at` marker) would be exactly the kind of speculative
schema addition this session must avoid, since pull-mode has no use for it at all.

**CONSEQUENCES**: none beyond the above — this is a non-decision in the sense that pull-mode makes
the question moot, not merely deferred.

**OUT OF SCOPE**: any `telegram_message_id`, `sent_at`, `delivered`, or similar column/table.

---

## 13. Approve Decision

**DECISION**: **DEFERRED.**

**RATIONALE**: Discovery §9 — no persisted editorial-approval state exists anywhere
(`ContentDraft.status` is free-text and currently only ever written as `"draft"`; Contract §7.1
already states Phase 10 "never transitions a `ContentDraft` row to any other status"). Critically,
"Approve" must not be implicitly conflated with "publish" — no publication mechanism exists (§17)
— so even the *meaning* of Approve requires a real design decision (UI-only acknowledgement vs. a
new persisted status value vs. a future publication trigger, per Discovery §9's own comparison),
not something this MVP should freeze incidentally while building an unrelated read-only feature.

**CONSEQUENCES**: a future milestone designing Approve should decide, deliberately: which of
Discovery §9's four candidate meanings it implements, and — if a persisted status value is
chosen — the exact new free-text value written (no migration needed for this, since the column is
already free-text, but the *value* and *who reads it* are new, undocumented surface that deserves
its own Decision Resolution, not an incidental choice here).

**OUT OF SCOPE for Phase 11 MVP**: any button, callback, or write path for Approve, in any form.

---

## 14. Reject Decision

**DECISION**: **DEFERRED.**

**Frozen invariant, binding for whichever future milestone implements Reject** (Discovery §10,
directly cited from `workflows/runner.py`'s own class docstring — *"Only `WorkflowRunner` ever
changes an `EditorialTask`'s status — `services.workflow_service` never does"*): **human rejection
of a `ContentDraft` MUST NOT mutate `EditorialTask.status`**, ever, under any future design. A
successfully `COMPLETED` AI workflow remains `COMPLETED` regardless of a human's later editorial
judgment on its output. If Reject is ever implemented, it belongs to `ContentDraft` alone (e.g. a
new free-text `status` value), never to workflow/task state.

**RATIONALE**: this is not a stylistic preference — `WorkflowRunner` is the *sole* writer of
`EditorialTask.status` by an absolute, mechanically-unenforced-elsewhere architectural invariant;
any future code that mutated task status from a Telegram callback would be a real, load-bearing
architecture violation, not a convenience shortcut.

**CONSEQUENCES**: a rejected draft remains queryable/accessible by default — no delete mechanism
exists anywhere for `ContentDraft` (Discovery §10), so nothing needs to be added to *prevent*
deletion; auditability is free.

**OUT OF SCOPE for Phase 11 MVP**: any button, callback, or write path for Reject, in any form.

---

## 15. Rework / Regeneration Decision

**DECISION**: **DEFERRED.**

**If implemented in a future milestone, it should be a new `EditorialTask`** (Discovery §11
Option B) — never an attempt to rerun the existing `COMPLETED` task (architecturally impossible,
`TaskAlreadyCompletedError`), never a draft-revision scheme (no version-increment mechanism
exists or should be invented here), and never a targeted Copywriting-only re-run (would require a
new "resume from step N" capability on `WorkflowRunner`, explicitly excluded — Contract §13 item
9's still-standing "no crash/resume mechanism" limitation). Concretely, if built: "Rework" would
mean invoking `run_content_generation_for_event(event_id)` again — the existing script's existing
function, unchanged — triggered from a future Telegram callback.

**RATIONALE**: Discovery §11 traced every option against real code guards, not assumption. Option
B is the only one requiring zero change to `WorkflowRunner`/`CapabilityExecutor`/any Capability.
It is still deferred from the *MVP* specifically because even this safest option requires solving
a real, undesigned problem: triggering a real, billed, ~120-second OpenAI pipeline run from inside
a Telegram callback handler, which cannot simply `await` synchronously inside that handler — a
materially larger scope than a read-only inbox, and not something to bolt on opportunistically.

**CONSEQUENCES**: whichever future milestone designs Rework must also design the long-running-
callback UX (e.g. immediate "Regenerating…" acknowledgement + a later edited/follow-up message
once the pipeline completes) — flagged here as real, unsolved scope, not underestimated.

**OUT OF SCOPE for Phase 11 MVP**: any button, callback, or trigger for regeneration, in any form.

---

## 16. Scheduler / Push Decision

**DECISION**: **OUT OF SCOPE.**

Explicitly, per instruction:
- **No scheduler is introduced.**
- **No delivery worker is introduced solely for Phase 11 MVP.**
- **No durable "sent" marker is required or added** (§12 above).

**RATIONALE**: Discovery §6 — push requires either violating the ownership finding (§5, having
`WorkflowRunner`/`ContentDraftService` send Telegram messages) or introducing a poller, itself a
lightweight scheduler, directly contradicting Phase 10 Contract §2's still-standing "no scheduler
or automatic-execution mechanism" exclusion, which no evidence in this repository has lifted.

**CONSEQUENCES**: none — this is a clean, zero-cost exclusion; pull-mode simply has no use for any
of these mechanisms.

**OUT OF SCOPE**: any poller, cron, background task, or "watch for new `ContentDraft` rows"
mechanism of any kind.

---

## 17. Publication Boundary

**DECISION**: **Editorial Inbox ≠ public publishing. Phase 11 MUST NOT publish to a public
Telegram channel. There is no Approve→Publish behavior in this phase, because there is no Approve
in this phase (§13).**

**RATIONALE**: Discovery §22 confirms no publishing mechanism to any public-facing Telegram
channel/audience exists anywhere in this repository — `bot/` only ever replies inside the
invoking chat; Phase 10 Contract §10 only ever *conceptually sketched* a future `PublisherService`,
never built or authorized. This repository's own `CLAUDE.md` MVP rule already forbids "automatic
publication without human involvement." Conflating a future "Approve" action with public
publishing would silently smuggle a much larger, ungoverned feature into what should remain a
deliberate, separately-authorized future phase.

**CONSEQUENCES**: none for Phase 11 itself. A future phase that designs public publication should
do so as its own, explicitly-scoped Architecture Contract, informed by but not preempted by
whatever Approve/Reject semantics (§13/§14) are eventually decided.

**OUT OF SCOPE**: any `PublisherService`, any "publish to channel" API call, any public-channel
configuration.

---

## 18. Meme / Image Boundary

**DECISION**: **OUT OF SCOPE.** Phase 11 remains text/editorial delivery only.

**RATIONALE**: Discovery §22 re-confirms, this session, zero image-generation infrastructure
exists anywhere (`grep` for `generate_image`/`image_generation`/`MemeCapability` returns nothing),
exactly matching Phase 10 Contract §11's own finding. `LLMGateway.generate()` has no image-output
method; `ContentType.MEME` exists on the enum but is never written by any code path. Phase 11's
own scope (rendering already-generated, text-only `ContentDraft` rows) structurally cannot and
does not touch this boundary.

**CONSEQUENCES**: none — this is a non-issue for Phase 11's actual scope, stated explicitly per
instruction rather than left silently assumed.

**OUT OF SCOPE**: any `LLMGateway` extension for image generation; any meme-workflow design of any
kind, here or implied.

---

## 19. Database / Migration Decision

**DECISION**: **NO MIGRATION.**

**Explicitly prohibited during Phase 11 MVP** (per instruction, verified against the frozen §3
scope): adding any of the following columns/tables —
- an approval status column,
- a rejection status column,
- a `delivered_at` column,
- a `telegram_message_id` column,
- a `destination_chat_id` column (or any destination-configuration table).

**RATIONALE**: §7 (card data), §12 (idempotency), §13/§14 (Approve/Reject deferred), and §16 (no
push) each independently eliminate the only reasons any of the above columns would ever be needed.
Discovery §18/§19 confirms the complete MVP card data path exists today with zero schema change.

**CONSEQUENCES**: if a future milestone adds Approve/Reject (a free-text `status` value — no
migration even then, per Discovery §9) or push delivery (which *would* need a delivery-marker
column — a real, future migration), those are each that future milestone's own, separately
authorized decision.

**OUT OF SCOPE**: any Alembic migration file of any kind for Phase 11.

---

## 20. Architecture Ownership

**DECISION**: a dedicated, thin **read/query layer** — conceptually `handler → query/service
function → DB → Telegram rendering` — owns Phase 11's entire new surface. Confirmed explicitly:
**`WorkflowRunner`, `CapabilityExecutor`, `CapabilityRegistry`, `LLMGateway`, `PromptRepository`,
and `ContentDraftService`'s own persistence method MUST NOT own delivery/rendering**, and none of
Phase 11's new code writes to any of them.

**RATIONALE**: Discovery §5's ownership comparison is unambiguous — Model E (bot handler reads
`ContentDraft` directly, on request) is the specific, minimal instance of the general "decoupled
read-only layer" pattern (Model C) that avoids re-violating Phase 10's own established isolation
discipline (Contract §7: only `ContentDraftService` may ever write a `ContentDraft` row; nothing
in Phase 11 writes one at all). Models A/B (WorkflowRunner or ContentDraftService sending Telegram
messages) were explicitly rejected in Discovery for coupling a frozen, single-purpose component to
a new external dependency and its failure modes.

**CONSEQUENCES**: aiogram-specific concerns (formatting, `Message`/HTML escaping) stay confined to
the bot edge (§21); the underlying query is plain, aiogram-free Python, testable exactly like any
other service function in this repository.

**OUT OF SCOPE**: any change to any of the six named frozen components, in any form.

---

## 21. Query Service Boundary

**DECISION**: **yes, introduce a dedicated read function/module** — not raw DB query logic inlined
directly inside the aiogram handler. Its responsibilities: query the latest N `ContentDraft` rows
whose task is `COMPLETED` (§6); load each row's `EditorialTask`/`NewsEvent` via the existing
manual-lookup pattern (§4, mirroring `CapabilityExecutor._build_context()`'s own two-hop lookup);
return a plain DTO/view model per card (title, body, hashtags, category, published_at, url,
news_title) — **not** a raw ORM object crossing into `bot/`, mirroring every existing
`schemas/*.py` read-schema convention in this repository (e.g. `ContentDraftRead`,
`EditorialTaskRead`).

It must **not**: generate AI content, mutate any workflow/task/draft state, or itself hold any
aiogram/`Bot` dependency — formatting into an HTML Telegram message string is a separate concern
(§8), kept at the bot edge, so the query layer stays independently testable against a real test DB
with zero Telegram mocking needed.

**RATIONALE**: this repository's own convention (Phase 9/10's `services/*.py` layer) consistently
keeps DB query logic out of thinner, edge-facing callers (compare `services/workflow_service.py`,
`services/content_draft_service.py`) — Discovery §21/§19 recommends the same discipline for
Phase 11 rather than inlining `select()` calls directly inside `bot/handlers/news.py`.

**CONSEQUENCES**: exactly one new module is needed for this responsibility (exact file location —
`services/` vs. a new `bot/`-local module — is a Contract-stage implementation detail, not frozen
here); it has no new dependency beyond an `AsyncSession`, matching every existing service
function's own constructor-injection-free, plain-function style.

**OUT OF SCOPE**: any repository-pattern abstraction, ORM `relationship()` addition, or generic
query-builder framework — plain `session.get()`/`select()` calls, exactly as everywhere else in
this repository.

---

## 22. Testing Strategy

**DECISION**: automated tests for the query/formatting layer (against a real test DB, mirroring
`tests/test_content_draft_service.py`'s own conventions — real Postgres, no fakes needed since
there's no external dependency to fake) + automated tests for the handler function called
directly (mirroring Phase 10's own "test the function, not the thin wrapper" discipline) with a
constructed `Message`/fake `Bot` — **no live Telegram API call anywhere in the automated suite**
(Phase 7 §15.5's unbroken discipline, unchanged). Plus **one manual, out-of-band live-Telegram
smoke test** before Phase 11 can be considered done — a real bot token, a real chat, confirming an
actual card renders correctly (HTML formatting, escaping, length behavior) — mirroring Phase 10's
own M0 live-OpenAI-smoke precedent exactly.

**Minimum coverage**: query ordering/limit correctness; empty-inbox behavior (§23); a draft with a
`null` `NewsEvent.url` renders without a broken/empty link; HTML-escaping of a title/body
containing `<`/`>`/`&`; over-length body truncation. **No unauthorized-user/authorization test is
required or written for Phase 11** — per §10's resolved decision, no in-app authorization exists
to test; any such test would only be meaningful once a future milestone's dedicated security
design step (§10, §24) actually builds an enforcement mechanism.

**RATIONALE**: Discovery §15 confirms zero bot tests exist today — Phase 11 establishes this
convention from scratch, deliberately following patterns already proven elsewhere in this
repository rather than inventing a new testing philosophy.

**CONSEQUENCES**: the one manual live-Telegram smoke is **not** added to the automated suite,
exactly matching the no-real-network-call discipline already governing the OpenAI Gateway.

**OUT OF SCOPE**: any live Telegram call inside CI/automated `pytest` runs; public-channel posting
of any kind, live or automated.

---

## 23. Error / Empty-State UX

**DECISION**:
- **No drafts exist**: reply with a short, friendly, static message (e.g. "No recent drafts yet.")
  — never an empty response, never a stack trace.
- **DB unavailable**: the handler lets the exception propagate to aiogram's own top-level error
  handling (no bespoke swallowing) but the SMM-facing message, if any is sent at all, must be
  generic ("Something went wrong, please try again.") — **never** expose an internal exception
  message, stack trace, SQL, or connection string to a Telegram user.
- **A draft with missing optional source metadata** (`NewsEvent.url` is `null`): render the card
  without that line entirely (§7) — never a broken/empty link, never a placeholder like "None."
- **Telegram message exceeds limits**: defensive truncation (§8) — never a crash, never a silently
  dropped card.

**RATIONALE**: these are the concrete, minimum UX guarantees needed for a tool the SMM team will
actually trust; none require new architecture, only careful handler-level error/edge-case
handling.

**CONSEQUENCES**: the handler needs at least one `try`/`except` boundary around the query call,
consistent with (not a new invention beyond) `scripts/run_content_generation.py`'s own precedent
of catching and distinctly handling a downstream failure without crashing the whole operation.

**OUT OF SCOPE**: structured error codes, retry-with-backoff UX, or any error-reporting mechanism
beyond a plain, generic user-facing message plus normal application logging.

---

## 24. Frozen Invariants

Restated here for the Architecture Contract to encode directly, not re-derive:

1. Telegram delivery/rendering failure **must never** invalidate a `TaskStatus.COMPLETED`
   `EditorialTask` or destroy/mutate a persisted `ContentDraft` row (Discovery §14 — already
   structurally guaranteed by construction for a read-only MVP, since nothing in Phase 11 writes
   to either).
2. **Only `WorkflowRunner` may ever change `EditorialTask.status`** — Phase 11 introduces zero
   exception to this, now or in any future Reject/Rework design (§14/§15).
3. **Only `ContentDraftService.create_from_result()` may ever create a `ContentDraft` row** — Phase
   11 introduces zero write path to this model in the MVP, and any future write path (Approve/
   Reject) must go through a comparably narrow, explicit, single-purpose component, never a
   generic ORM write scattered across handlers.
4. `WorkflowRunner`, `CapabilityExecutor`, `CapabilityRegistry`, `LLMGateway`, `PromptRepository`,
   every `capabilities/*_capability.py` file, and every Phase 5–10 frozen file remain **untouched**
   by Phase 11 MVP (§19/§20).
5. No scheduler, no push, no public publication, no meme/image generation (§16/§17/§18).
6. **Binding security assumption (§10)**: Phase 11 provides no application-level authorization
   boundary for `/news`. Anyone who can reach and invoke the bot may access the Phase 11 inbox,
   unless access is restricted operationally at the Telegram/deployment level. The Architecture
   Contract and any future documentation MUST state this explicitly and MUST NOT describe the bot
   as application-level access-controlled during Phase 11.
7. **Future security gate (§10)**: before any editorial write action (Approve, Reject, Rework/
   Regenerate, Publish, or any administrative editorial mutation) is introduced, a dedicated
   authorization/security design step MUST occur first, resolving at minimum `User` creation/
   bootstrap, Telegram `telegram_id` → `User` mapping, `OWNER` bootstrap, role semantics,
   permissions, unauthorized-user behavior, callback authorization, and stale/replayed-action
   protection. No write action may ship before this gate is satisfied.

---

## 25. Deferred Decisions

Explicitly not resolved in this document, each requiring its own future Decision Resolution pass.
(§10's authorization posture *for Phase 11 itself* is now resolved — no in-app enforcement, §10 —
but the *future* authorization/security system remains deferred, gated behind §24 item 7's frozen
invariant, and is listed here for that reason.)

- **Future authorization/security design** (§10, §24 item 7) — mandatory before any editorial
  write action ships: `User` creation/bootstrap, Telegram `telegram_id` → `User` mapping, `OWNER`
  bootstrap, role semantics, permissions lifecycle, unauthorized-user behavior, callback
  authorization, stale/replayed-action protection. Not designed here.
- Approve's exact meaning and persisted representation, if ever built (§13).
- Reject's exact persisted representation, if ever built (§14) — bound by the frozen invariant in
  §24 item 2 regardless of the exact design chosen.
- Rework's long-running-callback UX design, if ever built (§15).
- Push delivery's destination-configuration model and delivery-marker schema, if ever built
  (§11/§12/§16).
- Public publication's entire architecture, if ever authorized (§17).

---

## 26. Architecture Contract Inputs

The exact decisions the next Phase 11 Architecture Contract must encode, verbatim from this
document:

1. Scope = Option A only (§3) — no button/callback/write path of any kind.
2. `/news` (existing handler, `bot/handlers/news.py`) is extended, not replaced by a new command
   (§5).
3. Query: 5 most recent `ContentDraft` rows with `EditorialTask.status == COMPLETED`, newest-first
   by `ContentDraft.created_at` (§6).
4. Card fields, required vs. optional, exact rendering rules including the `url`-omission-if-null
   rule (§7).
5. HTML parse mode, mandatory escaping of all dynamic text, defensive truncation at 4096 characters
   (§8).
6. Five sequential messages, no pagination UI (§9).
7. **No in-app authorization enforcement** (§10) — the Contract must explicitly state Phase 11
   ships with zero application-level access control on `/news`, name every item on §10's "none of
   the following are added" list as explicitly unauthorized, and reproduce §10's binding security
   assumption verbatim in substance: *"Phase 11 provides no application-level authorization
   boundary for `/news`. Anyone who can reach and invoke the bot may access the Phase 11 inbox,
   unless access is restricted operationally at the Telegram/deployment level."* The Contract must
   not describe the bot as access-controlled or imply `User`/`UserRole` protects anything in
   Phase 11.
8. **Future security gate** (§10, §24 item 7) — the Contract must state, as a binding constraint on
   every future milestone (not just Phase 11), that no editorial write action may be authorized or
   implemented before a dedicated authorization/security design step resolves `User` creation/
   bootstrap, `telegram_id` → `User` mapping, `OWNER` bootstrap, role semantics, permissions,
   unauthorized-user behavior, callback authorization, and stale/replayed-action protection.
9. No destination config; reply in `message.chat.id` (§11).
10. No delivery-persistence columns (§12/§19).
11. Approve/Reject/Rework: explicitly named as excluded, with §24's frozen invariants stated
    as binding constraints on any future milestone, not just Phase 11.
12. No scheduler/push/publication/meme (§16/§17/§18).
13. New query/service module, DTO-returning, no aiogram dependency, mirroring existing
    `services/*.py` conventions (§21).
14. Test plan exactly as §22 — real-DB tests for the query layer, direct handler-function tests, no
    live Telegram call in CI, no authorization test (§10/§22), one manual live-Telegram smoke as
    the DoD gate.
15. Files that MUST remain untouched: the full list already given in Discovery §19, carried
    forward unchanged into the Contract's own authorized-file-scope section.

---

## Final Verdict

PHASE 11 DECISIONS RESOLVED — READY FOR ARCHITECTURE CONTRACT
