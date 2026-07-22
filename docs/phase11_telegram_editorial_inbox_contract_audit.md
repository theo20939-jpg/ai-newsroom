# Phase 11 — Architecture Contract Adversarial Audit

**Status: audit document only.** Independently re-verifies
`docs/phase11_telegram_editorial_inbox_architecture_contract.md` ("the Contract") against current
repository source and the installed runtime library, treating the Contract as untrusted. No
production code, test, migration, Discovery, Decision Resolution, or the Contract itself was
modified to produce this document.

---

## 1. Executive Verdict

The Contract is architecturally sound, internally consistent in its major decisions, and
correctly derives its ownership/scope/frozen-boundary structure from Discovery and Decision
Resolution. However, this audit found **three genuine, evidence-based MAJOR findings** — one of
which is a directly-verified factual error (the Contract's own claim about `aiogram`'s runtime
behavior is contradicted by the actual installed library source) and two of which are real,
concrete underspecifications in the HTML-escaping and message-length safety invariants that a
competent implementer could follow literally and still ship a bug. None of the three requires any
redesign — each is a narrow, precise correction to existing Contract text. **CRITICAL = 0, MAJOR
= 3.** Per the stated approval rule (CRITICAL = 0 AND MAJOR = 0), the Contract is **not yet
approved**.

---

## 2. Repository Baseline

**FACT**, re-verified this session:
```
HEAD: 7d3ae81a4666dfddf80c3b399e2a6596a749ac48
Recent commits: 7d3ae81 (Document Phase 10 completion...), c8131fc (Fix OpenAI structured
  output compatibility), 2ba004d (Implement Phase 10 production content pipeline), 89e111d
  (Document Phase 9 and Phase 9.5 completion)
```
All three Phase 10 implementation/remediation commits are present and confirmed on `HEAD`'s
ancestry. `git status --short` shows **zero modification to any tracked file** and **zero Phase
11 production code, test, or migration file** anywhere in the working tree — only pre-existing,
untracked Phase 9/9.5/10/11 process documentation (the same set present before this audit began).
**Phase 11 implementation has not started.** No migration exists for Phase 11.

---

## 3. Source Verification Matrix

| Contract claim | Verified against | Result |
|---|---|---|
| `/news` handler is placeholder-only, zero DB access | `bot/handlers/news.py:1-15` (re-read in full) | **CONFIRMED** — exactly `await message.answer(PLACEHOLDER_TEXT)`, nothing else |
| `/news` router already registered | `bot/handlers/__init__.py:1-18` (re-read) | **CONFIRMED** — `news_router` imported and `include_router`-ed already |
| Bot has no DI/middleware | `bot/loader.py:28-30` (`create_dispatcher()` returns bare `Dispatcher()`), `bot/middlewares/__init__.py` (empty) | **CONFIRMED** |
| HTML is the bot's default parse mode | `bot/loader.py:24` (`DefaultBotProperties(parse_mode=ParseMode.HTML)`) | **CONFIRMED** |
| `ContentDraft`/`EditorialTask`/`NewsEvent`/`NewsSource` field shapes | all four model files re-read in full this session | **CONFIRMED**, exact column names/types/nullability/indexes match the Contract's §4 table |
| No `relationship()` exists anywhere | `grep -n "relationship(" database/models/*.py` | **CONFIRMED**, zero matches |
| `ContentDraftService` construction site | `grep -rln "ContentDraftService("` (excluding tests) | **CONFIRMED** — only `scripts/run_content_generation.py`; each invocation creates a brand-new `EditorialTask`, so `create_from_result()` cannot currently be called twice for the same `task_id` |
| `bot/__init__.py` has no `__all__`/import restriction | re-read, docstring only | **CONFIRMED** — a new flat `bot/formatting.py` module needs no package-init change |
| `bot` is already a packaged module | `pyproject.toml`'s `packages = [...]` list | **CONFIRMED**, `bot` already listed |
| **Forum-topic thread preservation is NOT guaranteed by current code** | installed `aiogram==3.29.1`, `Message.answer()` source (`inspect.getsource`) | **CONTRADICTED** — see Finding F-3 below |

---

## 4. Data Path Audit

Independently re-traced `ContentDraft.task_id → EditorialTask.id`, `EditorialTask.event_id →
NewsEvent.id`, `NewsEvent.source_id → NewsSource.id`. Every column the Contract's §5 names is
confirmed present, with the exact nullability the Contract states (`ContentDraft.title`/`.body`
nullable; `NewsEvent.url`/`.published_at` nullable; `NewsEvent.title`/`.category` non-null;
`NewsSource.name` non-null). No `relationship()` exists (confirmed above), consistent with the
Contract's manual `session.get()` two/three-hop design, itself confirmed to mirror
`capabilities/executor.py::_build_context()`'s real, existing two-hop pattern
(`capabilities/executor.py:69-74`, re-read, confirmed identical shape). **No migration, model
change, or ORM relationship is required** — confirmed independently, not merely accepted from the
Contract's own claim.

---

## 5. Query Semantics Audit

**FACT, re-confirmed**: `ContentDraft.created_at` carries **no index**; `EditorialTask.status`
and `EditorialTask.created_at` both carry `index=True`. The Contract's own §4/§27 already discloses
this honestly (not silently assumed away) — no new finding here beyond what the Contract itself
states.

**FACT, newly confirmed this session**: `ContentDraft.task_id` has **no `unique` constraint** —
duplicate `ContentDraft` rows for the same `EditorialTask` are not schema-prohibited. However,
independently confirmed (§3 above): `ContentDraftService` is constructed only from
`scripts/run_content_generation.py`, and every invocation of that script creates a **new**
`EditorialTask` via `workflow_service.create_task()` (Phase 10, frozen, unmodified) — there is
currently no code path that could invoke `create_from_result()` twice against the same `task_id`.
**The Contract's eligibility query (§6) does not need explicit per-task deduplication logic for
Phase 11's own timeframe** — this is a real, verified conclusion, not an assumption the Contract
left unstated; classified as an **OBSERVATION** (§16), not a finding, since no actual gap exists
given current call patterns.

The `id`-based tie-break (§6) is a valid, portable secondary sort key for stable ordering — UUIDs
sort lexically/bytewise in every SQL backend this repository could plausibly use (confirmed
Postgres via `database/session.py`'s `postgresql+asyncpg://` URL), so this is technically sound,
if arbitrary (not chronologically meaningful, which the Contract itself already states plainly).

---

## 6. Session / Transaction Audit

**HIGH-SCRUTINY AREA, independently re-traced.** Confirmed: `create_dispatcher()` returns a bare
`Dispatcher()` (`bot/loader.py:28-30`) — no middleware, no DI container, no handler-data injection
of any kind exists anywhere in this repository's bot layer. The Contract's §9 design — the handler
opens its own `AsyncSession` directly via `async_session_factory()` (`database/session.py:14`,
re-confirmed), mirroring `scripts/run_content_generation.py`'s own real, existing pattern
(`scripts/run_content_generation.py`, re-read: `async with session_factory() as session:` inside
`run_content_generation_for_event()`) — **is a real, concrete, already-precedented mechanism, not
a hand-waved "handler → service → DB" gap Planning would have to invent.** This is the single
highest-risk audit area and it resolves cleanly: the Contract does not defer this decision, it
names the exact mechanism and the exact existing precedent to mirror. **No finding here.**

---

## 7. Telegram Runtime Audit

**FACT, independently verified via `inspect.getsource(Message.answer)` against the actual
installed `aiogram==3.29.1` package** (not aiogram's changelog or general web knowledge — the
literal installed source in this environment):

```python
return SendMessage(
    chat_id=self.chat.id,
    message_thread_id=self.message_thread_id if self.is_topic_message else None,
    ...
)
```

**`Message.answer()` — the exact method the Contract's own §9 handler design calls — already,
automatically, unconditionally threads `message_thread_id` when the invoking message was itself
inside a forum topic.** This directly contradicts the Contract's §10 claim ("no code in this
repository has ever set `message_thread_id` on an outgoing message... Phase 11 does not guarantee
topic-thread preservation"). See Finding F-3 (§15) for full detail. Private-chat and group/
supergroup behavior via `message.answer()` is confirmed correct as claimed (no forum-topic
concept applies to either, so the same call behaves identically to today's placeholder handlers).

---

## 8. Formatting / Length Audit

**Two findings surfaced here, both MAJOR** — see F-1 and F-2 (§15) in full. Summary:

- **F-1**: §13's binding "must be escaped" field list enumerates `draft_title`, `draft_body`,
  `hashtags`, `news_title`, `news_category` — but **omits `news_url`**, despite §12's card
  template directly interpolating `{news_url}` as a bare, unescaped placeholder. `NewsEvent.url`
  is real, external, DB-derived, untrusted data (RSS-sourced) that routinely contains literal `&`
  characters in query strings — Telegram's HTML parser requires these escaped or the `sendMessage`
  call fails outright ("can't parse entities"). The card renders as **plain text** (confirmed:
  no `<a href>` construct appears in §12's template — verified by direct re-read, not assumed), so
  there is no separate href-vs-visible-text escaping concern *once `news_url` is added to the
  escaping list* — but as written today, it is not in that list at all.
- **F-2**: §14's truncate-before-escape ordering is directionally correct (truncating already-
  escaped HTML risks cutting an entity mid-sequence, and the Contract correctly avoids this), but
  the stated "3500 characters for the body" budget is not proven safe against a worst-case,
  escaping-heavy input (e.g. AI-generated body text that happens to reference HTML/comparison
  operators, plausible for tech-news content). No post-escape length re-check or a mathematically
  conservative pre-escape bound is specified, so the final `sendMessage` call is not *provably*
  ≤4096 characters in every case, only in the typical case.

---

## 9. Authorization / Security Audit

Re-confirmed: `database/models/user.py`'s `User`/`UserRole` model is referenced by **zero** file
other than itself and `database/models/__init__.py`'s export (`grep -rln "from database.models.user\|UserRole"`,
re-run this session, same zero-consumer result as Discovery originally found). The Contract's §11
design (handler → query service → DB, §7/§9) never touches `User`/`UserRole` at any point — no
`session.get(User, ...)` or equivalent appears anywhere in the Contract's described flow. The
binding security-assumption wording in §11 matches Decision Resolution §10's exact substance
(reproduced, not paraphrased loosely). The future security gate (§11's second half) correctly
names every prerequisite Decision Resolution §10 itself named. **No finding.**

---

## 10. Failure Semantics Audit

§16's five-case table is concrete for cases A/B/C/D. **Case E (one card's formatting fails mid-
batch) is explicitly resolved** ("the single affected card's send is skipped/logged; it must not
abort the remaining, already-successfully-rendered cards") — this directly answers the audit's own
"does card #3 failing stop, continue, or log-and-continue" question: **log-and-continue is
frozen**, not left ambiguous. **No finding** — Planning does not need to invent this behavior.

---

## 11. File Scope Audit

Independently re-derived the minimum file set from scratch (not from the Contract's own §23 list):
one existing-file edit (`bot/handlers/news.py` — confirmed the only file requiring change, since
its router registration already exists, §3/§3-table), one new DTO module, one new query-service
module, one new formatting/escaping module, plus test files. **This matches the Contract's §23
list exactly, file for file.** No hidden bootstrap/router/config/DI file is required beyond what
§23 already authorizes (confirmed directly by §6's session-audit finding: no DI integration point
needs to be built, since the handler-opens-its-own-session pattern requires zero new
infrastructure file). **No finding — CRITICAL area cleared.**

---

## 12. Frozen Architecture Audit

Re-traced the Contract's own described data/control flow (§5, §7, §9) end to end: at no point does
it construct or call `WorkflowRunner`, `CapabilityExecutor`, `CapabilityRegistry`, any
`Capability`, `LLMGateway`, `PromptRepository`, `ContentDraftService` (not even for reads —
confirmed the Contract's service reads `ContentDraft` directly via `session.get()`/`select()`,
never through `ContentDraftService`'s own class), `scripts/run_content_generation.py`, any
`workflows/definitions/*.py` file, any DB model file, or any migration. **No finding.**

---

## 13. Test Obligation Matrix

| Contract-frozen behavior | §24 test obligation named? |
|---|---|
| Completed-only filter | Yes |
| Failed/incomplete excluded | Yes |
| Newest-first ordering | Yes |
| Deterministic tie-break | **Softly worded** ("exercised if practical to construct") — see Finding F-4 (MINOR) |
| Limit 5 | Yes |
| Empty result | Yes |
| Joined `NewsEvent` metadata | Yes |
| Optional metadata (`null` `url`) | Yes |
| No mutation (mechanical import-boundary check) | Yes |
| Title/body/hashtags/category escaping | Yes (but see F-1 — `news_url` escaping is not separately named as its own test obligation either, since it wasn't in the binding list to begin with) |
| Message-length/truncation behavior | Yes, but only the ordering, not a post-escape worst-case check (consistent with F-2) |
| Service invoked / empty state / cards sent / safe DB error | Yes |
| No AI/workflow call | Yes (mechanical check) |
| Existing-command regression | Yes |

Every behavior the Contract itself froze has a named test obligation, **except** the two direct
consequences of F-1/F-2 (a `news_url`-escaping test and a worst-case-length test aren't named,
because the underlying invariants themselves are incomplete) — these will resolve automatically
once F-1/F-2 are corrected, not a separate, independent gap.

---

## 14. Decision Resolution Consistency

Checked decision-by-decision against `docs/phase11_decision_resolution.md`: read-only (§3/§17
match §3 DR), pull (§4 DR matches §9 Contract), `/news` entry point (§5 DR matches §9 Contract),
latest-5 (§6 DR matches §6 Contract), HTML (§8 DR matches §13 Contract), no pagination (§9 DR
matches §15 Contract), no auth (§10 DR matches §11 Contract, including the exact "none of the
following are added" list), invocation-chat destination (§11 DR matches §10 Contract), no
idempotency state (§12 DR matches §16 Contract), Approve/Reject/Rework all deferred (§13/§14/§15
DR match §19 Contract), no scheduler (§16 DR matches §20 Contract), no publication (§17 DR matches
§20 Contract), no memes (§18 DR matches §21 Contract), no migration (§19 DR matches §22 Contract),
query-service boundary (§21 DR matches §7 Contract), testing strategy (§22 DR matches §24/§25
Contract), empty/error UX (§23 DR matches §16 Contract). **No silent drift found anywhere** — the
Contract faithfully encodes every Decision Resolution item, including the exact security-assumption
wording (§10/§11) and the future-security-gate invariant.

---

## 15. Findings

### F-1
**ID**: F-1
**SEVERITY**: MAJOR
**CONTRACT LOCATION**: §13 (Formatting / Escaping), binding escaping invariant paragraph
**SOURCE EVIDENCE**: §12's frozen card template directly interpolates `{news_url}` as a bare
placeholder (no `<a href>` wrapper — confirmed by direct re-read of the template); `NewsEvent.url`
(`database/models/news_event.py:48`) is a nullable `Text` column populated from external RSS/API
sources (Source Collector, Phase 4, unmodified), i.e. real, untrusted, externally-sourced dynamic
content, not a Python-authored constant.
**PROBLEM**: §13's binding "must be escaped" list names `draft_title`, `draft_body`, `hashtags`,
`news_title`, `news_category` — but does not include `news_url`, even though it is rendered
identically (as directly-interpolated dynamic text) alongside those fields.
**IMPACT**: a real-world URL containing an unescaped `&` (extremely common in query strings) sent
inside an HTML-parse-mode Telegram message can cause the Telegram Bot API to reject the entire
`sendMessage` call ("can't parse entities"), silently breaking the card for that draft — precisely
the class of bug the escaping invariant exists to prevent, left open by an incomplete enumeration.
**REQUIRED CORRECTION**: add `news_url` explicitly to §13's escaped-field list.

### F-2
**ID**: F-2
**SEVERITY**: MAJOR
**CONTRACT LOCATION**: §14 (Message Length)
**SOURCE EVIDENCE**: Telegram Bot API's `sendMessage` text limit is 4096 characters (platform
constraint, not repository-specific — no code in this repository currently enforces or tests
against it, confirmed by the absence of any length-handling code anywhere in `bot/`). HTML-escaping
expands certain characters (`&` → `&amp;`, a 1→5 character expansion; `<`/`>` → `&lt;`/`&gt;`, a
1→4 expansion).
**PROBLEM**: §14 freezes a truncate-then-escape *ordering* (correct) but not a *provably safe*
budget — "3500 characters for the body" plus an unspecified amount of static markup/escaping
overhead is sufficient for typical prose but not mathematically guaranteed for a worst-case input
(e.g., a body unusually dense with `&`/`<`/`>` characters, plausible for technology-news content
discussing code/comparisons/HTML). No post-escape length re-verification or fallback truncation is
specified.
**IMPACT**: in a rare but real worst-case input, the final escaped-and-assembled card could still
exceed 4096 characters despite the pre-escape truncation, causing an unhandled/unexpected
`sendMessage` failure the Contract's §16 failure table does not explicitly anticipate as a distinct
case.
**REQUIRED CORRECTION**: either (a) specify a mathematically conservative pre-escape budget (e.g.
sized against the theoretical worst-case 5x expansion factor), or (b) add an explicit post-escape
length check with a final safety truncation as a second, defensive layer — the Contract should
pick one and freeze it, not leave the choice to Planning.

### F-3
**ID**: F-3
**SEVERITY**: MAJOR
**CONTRACT LOCATION**: §10 (Destination Semantics)
**SOURCE EVIDENCE**: directly verified this session via `inspect.getsource(Message.answer)`
against the actually-installed `aiogram==3.29.1` package (not general/recalled knowledge) — the
real method signature/body auto-fills `message_thread_id=self.message_thread_id if
self.is_topic_message else None` on every outgoing `SendMessage` built via `.answer()`.
**PROBLEM**: §10 states, as a claimed fact, "no code in this repository has ever set
`message_thread_id` on an outgoing message" (true, narrowly) and concludes from this that "Phase
11 does not guarantee topic-thread preservation" (false) — but the Contract's own §9 handler
design calls exactly this `.answer()` method, which **already, automatically, guarantees** topic-
thread preservation for free, with zero additional code. The Contract's own conclusion does not
follow from its premise once the actual library behavior is checked.
**IMPACT**: benign in direction (the real behavior is *better* than what the Contract claims,
not worse), but this is still a factual error in a frozen document that a future reader/auditor
would reasonably rely on. It also means §11's "supported chat types" framing is incomplete —
forum/topic invocation is not merely "not addressed," it already works correctly by construction.
**REQUIRED CORRECTION**: correct §10's claim to state that `Message.answer()`'s own existing,
verified behavior already threads `message_thread_id` automatically when the invoking message was
itself inside a forum topic — no new code, decision, or exclusion is needed for this case; Phase 11
inherits topic-thread correctness for free via the same `.answer()` call it already uses for every
other chat type.

---

## 16. Observations

- **Duplicate-`ContentDraft`-per-task is schema-permitted but not currently reachable** (§5 above)
  — verified, not merely assumed; no correction needed, since no code path can trigger it today.
  Should Phase 11 or a later phase ever add a regeneration/rework path that writes a second draft
  for the same task (Decision Resolution §15 already commits any future Rework to a **new**
  `EditorialTask`, not a second draft on the same one), this remains a non-issue by construction,
  not by luck.
- **F-4 (MINOR)**: §24's tie-break test obligation is softly worded ("exercised if practical to
  construct") rather than a hard requirement — a real but low-stakes gap; a competent
  implementation could reasonably omit this one specific test without violating the Contract's
  letter. Recommend tightening to a firm obligation, but this alone would not block approval.
- The Contract's own self-audit (§29) did not catch F-1/F-2/F-3, despite explicitly asking
  "did I accidentally...?" — each of these three findings is a sin of *omission/incorrect claim*
  rather than *accidental scope expansion*, which is exactly the class of defect a first-party
  self-audit is least likely to catch and exactly what this second, adversarial pass exists for.

---

## 17. Readiness Score

**7/10.** The Contract's architecture, ownership boundaries, frozen-scope discipline, and
Decision-Resolution fidelity are all excellent — zero CRITICAL findings, and the file-scope/
session-injection/frozen-architecture audits (the areas with the highest potential for a
Contract-breaking defect) all cleared cleanly. The three MAJOR findings are each narrow, precisely
located, and correctable with a small, targeted text edit apiece — none requires reopening any
architectural decision. The score reflects that real, adversarially-found defects exist (not zero,
as a rubber-stamp pass would report) but are shallow and fully specified for correction, not
evidence of a flawed design.

---

## 18. Final Verdict

PHASE 11 CONTRACT NOT READY — CORRECTIONS REQUIRED
