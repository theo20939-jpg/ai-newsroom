# Phase 11 — M5 Failure Investigation Report

Investigation only. No production code, test, database record, or Telegram/BotFather configuration
was modified to produce this report. All evidence below comes from read-only DB queries, static
code inspection, and the running bot's own log — no fix was applied.

---

## Issue 1 — Thread/Topic Failure

### 1. Observed behavior
`/news` sent from a Telegram Forum Topic produced a response in **General** instead of the
originating topic.

### 2. Expected behavior
Contract §10 (corrected, finding F-3): every response `/news` produces from within a forum topic
must carry the originating `message_thread_id`, via `aiogram`'s `Message.answer()`.

### 3. Reproduction / evidence
The bot's own runtime log for the live session:
```
01:34:56 | Run polling for bot @nnj_newsroombot id=7688429343 - 'Ninja Newsroom'
01:36:31 | Update id=837679364 is handled.      Duration 650 ms
01:36:58 | Update id=837679365 is handled.      Duration 116 ms
01:42:23 | Update id=837679366 is NOT handled.  Duration 0 ms
01:42:46 | Update id=837679367 is NOT handled.  Duration 0 ms
01:42:46 | Update id=837679368 is NOT handled.  Duration 0 ms
01:44:41 | Update id=837679369 is NOT handled.  Duration 0 ms
01:44:54 | Update id=837679370 is handled.      Duration 557 ms
01:45:24 | Update id=837679371 is handled.      Duration 515 ms
```
Confirmed via `Get-CimInstance Win32_Process`: **exactly one** `python -m bot.main` process was
running — no second bot instance was competing for updates. The default `aiogram` event logger does
not record `chat_id`, `message_thread_id`, `is_topic_message`, or message text — so this log cannot,
by itself, prove which specific update corresponds to the topic test, or what the real incoming
`is_topic_message`/`message_thread_id` values were on that update. **This is a genuine
observability gap** (see item 7).

### 4. Exact data/code path
`bot/handlers/news.py::handle_news()` never reads or sets `message_thread_id` itself — it calls
`await message.answer(html, parse_mode=ParseMode.HTML)` and nothing else touches the outgoing
send parameters. `aiogram.types.Message.answer()`'s real, installed source (re-confirmed this
session, unchanged since the Contract's F-3 correction):
```python
return SendMessage(
    chat_id=self.chat.id,
    message_thread_id=self.message_thread_id if self.is_topic_message else None,
    ...
)
```
This is **entirely** dependent on the *incoming* `message.is_topic_message`/`.message_thread_id`
already being correctly populated when the update reaches the handler — Phase 11's own code has no
mechanism to set, override, or interfere with either field, in either direction.

### 5. Root cause — evidence-backed hypothesis (not confirmed with certainty)
The automated forum-topic test (`tests/test_news_handler.py::
test_forum_topic_message_thread_id_is_preserved_automatically`) constructs an `aiogram.types.Message`
object **directly**, by hand, with `is_topic_message=True` and `message_thread_id=777` already set,
and calls `handle_news(message)` **directly as a Python function** — it never goes through
`aiogram`'s real `Dispatcher`/router/update-parsing pipeline at all. It proves: *"if the incoming
`Message` object already has these two fields set correctly, the outgoing reply preserves them"* —
a true and useful proof, but it does **not** prove *"a real Telegram update, delivered through real
long-polling, actually arrives with these two fields set correctly for this specific chat."* That
second half was asserted in the Contract (§10) based on reading `aiogram`'s source and Telegram's
Bot API documentation, never validated against a real forum-enabled supergroup — this is precisely
the class of gap M5 live validation exists to catch, and (most likely) did.

Two concrete, evidence-consistent possibilities, not yet disambiguated by available evidence:
- **(a) Environment/configuration**: the "topic" used in the test chat was not a genuine Telegram
  Forum Topic (e.g., the supergroup does not actually have `is_forum` enabled, or the test used a
  reply-thread/normal group feature that only visually resembles a topic). In this case Telegram
  itself never sets `is_topic_message`/`message_thread_id` on the incoming message, and
  `message.answer()`'s documented, verified logic *correctly* routes to `None` (General) — not a
  code defect at all.
- **(b) Routing gap**: the cluster of four "not handled" updates (01:42:23–01:44:41) sits
  immediately before the topic test's likely timeframe — if the actual `/news` sent from the topic
  is among the "not handled" events (rather than one of the two later "handled" ones), the command
  never reached `handle_news` at all from the topic, and what the user saw in General may be a
  **different, earlier** invocation's response rather than a duplicate/misrouted one. This would
  point to a filter/registration issue upstream of the handler body itself, not examined
  in the original Contract at all (Contract §10/§16 assume the message reaches the handler; neither
  document ever verified that a forum-topic-originated `/news` is *matched by the command filter
  and routed* in the first place — the aiogram `Command` filter itself does not check topic-related
  fields, so this is unlikely to be the true explanation, but cannot be ruled out from current
  evidence).

**No evidence found implicating a bug inside `bot/handlers/news.py`, `bot/formatting.py`,
`services/editorial_inbox_service.py`, or `schemas/editorial_inbox.py`** — all four files were
re-read this session and none contains any topic/thread-related logic beyond the single,
already-verified `message.answer()` delegation.

### 6. Root-cause classification
**Test coverage gap** (the automated test proved the handler's own logic correctly forwards
already-set fields, but never proved real Telegram delivers those fields as expected for this
environment) — with a live-environment-configuration explanation as the leading, evidence-favored
hypothesis, not yet fully confirmed.

### 7. Why automated tests missed it
The network-free `FakeSession`/direct-function-call technique (correctly used to keep the test
suite fast and deterministic, per Contract §24/§25) constructs the incoming `Message` synthetically
— it cannot, by construction, validate that a *real* Telegram forum topic produces the exact field
values the test assumes. Only M5's real-chat validation could have caught this, and did. No
automated test can close this gap without either (a) a documented, verified confirmation that the
test chat is genuinely forum-enabled, or (b) capturing and asserting on the *raw* incoming
`is_topic_message`/`message_thread_id` values for the specific real update that triggered the
observed behavior — neither of which existed before this investigation.

### 8. Files/components likely requiring changes
**None identified yet** in Phase 11's own authorized files. If hypothesis (a) is confirmed (chat
configuration), no code change is needed at all — only re-validation in a genuinely forum-enabled
chat. If hypothesis (b) is confirmed (a real routing gap), the affected file would still be
`bot/handlers/news.py` or `bot/handlers/__init__.py`'s router wiring — but this is not yet
evidenced, only a named possibility.

### 9. Tests required before any fix can be accepted
- A diagnostic capable of capturing the raw incoming `message.is_topic_message`/
  `.message_thread_id`/`.chat.id`/`.chat.type` for a live `/news` invocation (e.g., temporary debug
  logging at the handler's entry, added only with explicit authorization) to determine, with
  certainty, what the real incoming update actually contained.
- Independent confirmation (outside this codebase) that the test supergroup has `is_forum=True` and
  that the specific topic tested is not "General."
- If a routing gap is confirmed: a new automated test that constructs a full `Update` object (not
  just a `Message`) and feeds it through `Dispatcher.feed_update()` for a forum-topic scenario, to
  close the exact gap the current unit test cannot reach.

### 10. Recommended minimal remediation scope
Not yet determinable — remediation scope depends entirely on which hypothesis the additional
evidence in item 9 confirms. Recommend gathering that evidence (with explicit authorization for any
temporary diagnostic logging) before scoping a fix.

---

## Issue 2 — Duplicate News Failure

### 1. Observed behavior
The `/news` result contains the same news item more than once.

### 2. Expected behavior
The user-facing `/news` result must not contain repeated copies of the same story.

### 3. Reproduction / evidence
Re-ran the exact production query (`services.editorial_inbox_service.get_latest_editorial_cards`)
live, read-only, this session:
```
Eligible cards found (fresh query): 1
  draft_id=2190d42d-e6e6-4f10-bc94-2a20520d1382
    draft_title='OpenAI GPT-5.6 Unifies Enterprise Multimodal Workflows'
    news_title='[M6 VALIDATION] OpenAI GPT-5.6 family adds native multimodal reasoning to enterprise tier'
    created_at=2026-07-21 12:09:08.476500+00:00
```
Full read-only inventory of the entire `content_drafts` table (not just the eligible-filtered
view): **exactly 1 row total, in the whole database.** (The `editorial_tasks` table has 3,133 rows,
almost all `CREATED` — an unrelated, pre-existing bulk-triage batch dated 2026-07-19, not COMPLETED,
therefore not eligible and not relevant to this investigation.)

The bot's own log shows **4 separate "handled" updates** across the live session (01:36:31,
01:36:58, 01:44:54, 01:45:24) — consistent with the user invoking `/news` multiple times during the
test session (as the M5 instructions themselves required: private chat, group, forum topic, etc.),
not one single invocation.

### 4. Exact data/code path
`get_latest_editorial_cards()`'s query is `SELECT ... FROM content_drafts JOIN editorial_tasks ON
content_drafts.task_id = editorial_tasks.id WHERE editorial_tasks.status = 'COMPLETED' ORDER BY
... LIMIT 5`. `ContentDraft.task_id → EditorialTask.id` is many-to-one from `ContentDraft`'s side
(each draft has exactly one task) — this join cannot multiply rows; a single `ContentDraft` row can
appear **at most once** in any one call's result set, by construction, regardless of data
volume.

### 5. Root cause — evidence-backed hypothesis
With only one `ContentDraft` row existing in the entire database, **duplication within a single
`/news` call is not possible** given the current query and schema (confirmed both by direct query
re-execution and by the join's cardinality). The far more likely explanation, strongly supported by
the log's 4 separate "handled" events: the user sent `/news` multiple times during the test session,
and each independent, correctly-functioning invocation deterministically returned the same (only)
eligible draft — which, viewed together across a chat's scrollback (or across the different chats/
topics tested), presents as "the same news item appearing more than once." **This is the exact,
explicitly documented, intentional pull-mode behavior already frozen in Contract §15**: *"calling
`/news` again intentionally returns the current latest 5 eligible drafts — which may be identical
to a prior invocation's result if no new `ContentDraft` has been created since. This is correct,
intended pull-mode behavior, not a duplicate-delivery bug."*

Also ruled out: a second, competing bot process. `Get-CimInstance Win32_Process` confirmed exactly
one `python -m bot.main` process was running for the entire session.

**This hypothesis is strong but not 100% certain** without knowing precisely how many times `/news`
was sent and in which chats/topics — see item 9 for what would fully confirm it.

### 6. Root-cause classification
**Bad/legacy test data misread as a defect**, most likely — with a secondary, unconfirmed
possibility of **test coverage gap** if it turns out duplication occurred *within* a single
invocation's message batch (which current evidence argues strongly against, given the 1-row table
and the join's cardinality).

### 7. Why automated tests missed it
Every automated test that exercises multi-invocation "pull again" behavior
(`tests/test_editorial_inbox_service.py`) already correctly predicts and accepts this exact
scenario — repeated calls returning the same row is the *expected*, tested behavior, not something
tests would ever flag as a failure. If the true cause is "multiple invocations look like duplicates
to a human observer," no unit test *should* catch it, because it isn't a defect — this is a UX/
observation nuance, not a correctness gap.

### 8. Files/components likely requiring changes
**None identified.** No evidence of an actual defect in `services/editorial_inbox_service.py`,
`bot/formatting.py`, or `bot/handlers/news.py`.

### 9. Tests required before any fix can be accepted
Not applicable unless the alternative (within-single-invocation duplication) is confirmed. To fully
confirm the "multiple invocations" explanation rather than assume it: ask the user to reproduce
with a single, isolated `/news` invocation in one chat and count the cards received in that one
reply batch — if exactly 1 card arrives (matching the 1 eligible row), the hypothesis is confirmed
and this is not a defect.

### 10. Recommended minimal remediation scope
**None recommended** pending the confirmation in item 9. If confirmed as expected pull-mode
behavior, no code change is warranted — Contract §15 already governs this exact scenario
deliberately.

---

## Issue 3 — Language Failure

### 1. Observed behavior
`/news` content is displayed in English; the user expects Russian.

### 2. Expected behavior
(As stated by the user) user-facing editorial news cards must be in Russian.

### 3. Reproduction / evidence
The single real `ContentDraft` row's `title`/`body` are in English (`"OpenAI GPT-5.6 Unifies
Enterprise Multimodal Workflows"` / body starting `"OpenAI's GPT-5.6 family brings native
reasoning..."`). Its linked `NewsEvent.title` is also English, and is explicitly labeled
`"[M6 VALIDATION] ..."` — i.e., it is Phase 10's own M6 live-validation smoke-test record, not
organically produced editorial content.

Traced the language-selection mechanism across the entire AI pipeline (Phase 6, frozen,
unmodified):
```
schemas/capability.py:61        BusinessContext.language: str = "en"   (the field's only default)
capabilities/executor.py:137    BusinessContext(news_event=..., workflow_state=...)  (language
                                  is never passed explicitly here - always falls back to "en")
capabilities/research_capability.py, intelligence_capability.py, copywriting_capability.py,
quality_capability.py, scoring_capability.py:
                                  each interpolates f"Language: {context.business.language}"
                                  literally into its prompt - always "Language: en" today
```
Searched every prompt file and every Phase 6–11 frozen document for any Russian-language
requirement or any code path that ever sets `language` to anything other than `"en"`: **none
found.**

### 4. Exact data/code path
`NewsEvent` (English, from Phase 4's Source Collector) → `EditorialTask` (no language field) →
`CapabilityExecutor._build_context()` constructs `BusinessContext` **without** passing `language`,
so it silently defaults to `"en"` → every Capability's prompt literally states `"Language: en"` →
`CopywritingCapability` generates English `title`/`body` → `ContentDraftService.create_from_result()`
persists them verbatim → Phase 11's `EditorialInboxCard.draft_title`/`.draft_body` are populated
directly from these same, already-English, `ContentDraft` columns → `bot/formatting.py` renders
them as-is, with no translation step anywhere (Phase 11 has never claimed to translate — its
Contract describes it as a read-only *display* of already-generated content, never a
content-transformation layer).

### 5. Root cause — evidence-backed conclusion
**Confirmed, not merely hypothesized**: `BusinessContext.language` defaults to `"en"` and is never
overridden anywhere in the current, frozen, unmodified Phase 6–10 codebase — every single
AI-generated `ContentDraft` this repository has ever produced (there is only one) was generated in
English by this unconditional default, entirely independent of Phase 11. Phase 11 does not read raw
source-language fields "instead of" a Russian editorial field — there is only one `title`/`body`
pair per draft, and it is English because the upstream generation step has only ever run in
English. No Russian content exists anywhere in this database to select instead.

### 6. Root-cause classification
**Incomplete contract/specification — pre-existing, upstream of Phase 11, not introduced by it.**
Russian output was never specified as a requirement in Discovery, Decision Resolution, or the
Architecture Contract for Phase 11, nor in any Phase 6–10 document found by this search. This is a
genuine, real gap — but it is a **Phase 6 (`BusinessContext`/Capability prompt) specification gap**,
not a Phase 11 defect: Phase 11's Contract accurately describes itself as displaying whatever
`ContentDraft` already contains, and does not claim or attempt translation.

### 7. Why automated tests missed it
No automated test in Phase 11 (or Phase 6–10) ever asserted a specific output language, because no
frozen document ever specified one as a requirement — there was nothing for a test to check against.
This is a specification gap, not a test-coverage gap: tests correctly verify the code does what the
Contract says: display `ContentDraft.title`/`.body` verbatim, escaped and length-bounded, regardless
of language.

### 8. Files/components likely requiring changes
**Not Phase 11.** If Russian output becomes a binding requirement, the change belongs entirely to
Phase 6–10's frozen architecture: `schemas/capability.py`'s `BusinessContext.language` default
and/or `capabilities/executor.py`'s `_build_context()` (to pass a non-default language), and/or
every Capability's prompt files (`prompts/*/v*.yaml`, versioned additively per Phase 6 §8's
prompt-immutability discipline — never edited in place). **This is squarely outside Phase 11's
authorized scope** (Contract §18 explicitly freezes all of these files) and would require its own,
separately governed architecture decision — not something this investigation, or any Phase 11
milestone, may act on.

### 9. Tests required before any fix can be accepted
Entirely dependent on a future, separate Phase 6-scoped specification: what language(s) are
required, whether it's configurable per-source/per-category, whether existing English drafts need
backfilling or coexist alongside Russian ones, etc. — none of this is decidable from Phase 11's own
scope or this investigation's evidence.

### 10. Recommended minimal remediation scope
**None within Phase 11.** Recommend treating this as a new, explicitly-scoped requirement for a
future Phase 6/10-amendment (governed by its own Discovery → Decision Resolution → Contract cycle,
per this repository's own established discipline) — not a Phase 11 bug to fix. Phase 11's own
scope boundary (§18) explicitly prohibits touching any of the implicated files without exactly this
kind of separate authorization.

---

## Investigation Integrity

- **Files changed during investigation**: zero (`git status --short` before and after this
  investigation is identical to the end-of-M4 state — only pre-existing untracked docs, the
  previously-modified `bot/handlers/news.py` from M3, and the previously-new M1–M4 production/test
  files; nothing new).
- **Database data modified**: no. Every query executed was a read-only `SELECT` (via
  `services.editorial_inbox_service.get_latest_editorial_cards` and direct `select()` inventory
  queries). No `INSERT`/`UPDATE`/`DELETE` was issued anywhere in this investigation.
- **Telegram/BotFather configuration modified**: no. The only Telegram-side action taken was
  starting the existing, unmodified bot process (`python -m bot.main`, the real production entry
  point, already started prior to this failure report) — no bot settings, commands, webhook, or
  BotFather configuration was changed.
- **Bot process state**: the same single `python -m bot.main` background process from the earlier
  live-validation attempt is still running (PID 16840, confirmed via `Get-CimInstance
  Win32_Process`) — it has not been stopped or restarted during this investigation.

---

## Summary

| Issue | Classification | Phase 11 defect? |
|---|---|---|
| 1. Thread/topic | Test coverage gap (environment-configuration hypothesis favored, not fully confirmed) | Not evidenced |
| 2. Duplicate news | Bad/legacy-data misread as defect (multiple manual invocations of a single-row DB), not fully confirmed | Not evidenced |
| 3. Language | Incomplete upstream (Phase 6) specification, confirmed | No — out of Phase 11's scope entirely |

No code, test, data, or configuration change has been made. Awaiting explicit authorization before
any further action.
