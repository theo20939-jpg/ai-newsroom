# Phase 14.5 — Real News End-to-End Validation Report

## Status: SUCCESS — one real news event processed end-to-end, one Telegram message sent

## Selected source

| Field | Value |
|---|---|
| source | `vc.ru` |
| event_id | `9420a3c1-ef14-4f7f-8ebf-b8a809db183e` |
| news title | «Робототехнический стартап Atoms сооснователя Uber Трэвиса Каланика привлёк $1,7 млрд. Оценку компании не раскрыли.» |
| url | `https://t.me/vcnews/62532` |
| published_at | 2026-07-23 10:15:15+00:00 |
| Selection method | read-only SQL, see `docs/phase14_5_real_news_validation_plan.md` |
| Approved by user | yes, explicit "PHASE 14.5 REAL NEWS VALIDATION — CANDIDATE APPROVED" |

## Workflow results

### NEWS_ANALYSIS (task `10d30deb-2a45-4770-a3bd-68ab35c13675`, direct invocation — pre-existing
`CREATED` task, no eligibility scan)

- **Preflight**: confirmed still `CREATED` immediately before execution.
- **Status**: `COMPLETED`, `iterations_used=1`, elapsed **35.66s**
- Steps, all `SUCCESS` on attempt 1: `research`, `intelligence`, `engagement_analysis`, `scoring`
- No retries occurred.

### CONTENT_GENERATION (new task `a5fa760b-9563-4841-9166-afe85acf76f7`, created by
`run_content_generation_for_event()`, unmodified production entry point)

- **Status**: `COMPLETED`, elapsed **11.25s**
- `ContentDraft` created: `491db283-8ea0-4719-860c-2fc02ee9ab2b`

## Provider calls

**8 total real provider calls**, both workflows combined:

| # | Stage | elapsed (s) | ok |
|---|---|---|---|
| 1 | NEWS_ANALYSIS: research | 10.39 | yes |
| 2 | NEWS_ANALYSIS: intelligence | 12.64 | yes |
| 3 | NEWS_ANALYSIS: engagement_analysis | 7.63 | yes |
| 4 | NEWS_ANALYSIS: scoring | 4.88 | yes |
| 5 | CONTENT_GENERATION: research | 0.008 | yes |
| 6 | CONTENT_GENERATION: intelligence | 0.007 | yes |
| 7 | CONTENT_GENERATION: copywriting | 4.62 | yes |
| 8 | CONTENT_GENERATION: quality | 6.43 | yes |

**Observation (not a bug, not fixed)**: calls 5 and 6 (CONTENT_GENERATION's `research`/
`intelligence` steps) returned in ~7-8 milliseconds instead of several seconds. `CONTENT_
GENERATION` re-derives `research`/`intelligence` independently from the same `NewsEvent` fields
`NEWS_ANALYSIS` had just used seconds earlier — with identical prompts, the AI integration
layer's `CacheCoordinator` (`integrations/llm_gateway/boot.py`) served these two calls from
cache rather than hitting the provider again. This is expected behavior of an already-existing,
unmodified caching layer — recorded here as an observation, not investigated or changed further
(out of scope).

All 8 calls succeeded; zero errors, zero retries beyond what `WorkflowRunner` already performs
internally (none were needed here).

## Generated draft

- `draft_id`: `491db283-8ea0-4719-860c-2fc02ee9ab2b`
- `type`: `POST`, `status`: `draft`, `version`: `1`

**Title**: «Atoms привлёк $1,7 млрд до выпуска первого продукта»

**Body**:
> Робототехнический стартап Atoms, связанный с сооснователем Uber Трэвисом Калаником, привлёк
> $1,7 млрд. Раунд возглавил Andreessen Horowitz, среди инвесторов — Uber. Компания разрабатывает
> системы промышленной автоматизации, но пока не выпустила ни одного продукта. Оценка стартапа не
> раскрывается.

**Hashtags**: `#робототехника #стартапы #венчурныеинвестиции #автоматизация`

## Editorial quality assessment

- **(A) Real news topic?** Yes — a real funding round for the robotics startup Atoms, matching
  the source headline.
- **(B) Explains what happened / why it matters, no hallucination, no internal/test wording,
  SMM-suitable?**
  - What happened: clearly stated ($1.7B raised, lead investor Andreessen Horowitz, Uber among
    investors, no product shipped yet, valuation undisclosed).
  - Why it matters: partially present (frames it as a major raise for a pre-product company) but
    does not editorialize further on industry significance — acceptable for a short SMM post
    format, on the thin side for deeper "why it matters" framing.
  - Hallucination check: the core facts (amount, founder link to Uber, no product yet, valuation
    undisclosed) match the source title directly. Two added specifics — "Andreessen Horowitz led
    the round" and "Uber is among the investors" — are **not present in the source title** and
    were not independently fact-checked against the original article by this validation (the
    `research`/`intelligence` capabilities may have drawn on real external content, but this
    procedure did not verify those two claims against a primary source). **Flagged as an
    unverified-but-plausible enrichment, not confirmed hallucination-free.**
  - No internal/test wording present anywhere in title, body, or hashtags.
  - Format/tone: suitable for an SMM channel — short, factual, hashtagged.
- **(C) Russian output preserved?** Yes — title, body, and hashtags are entirely in Russian, no
  language drift.

## Telegram delivery

- Chat re-verified immediately before send via fresh `bot.get_chat(5507703201)`:
  `chat.id == 5507703201`, `chat.type == "private"` — **PASS**.
- Exactly one `bot.send_message()` call made (captured via a temporary, instance-local wrapper,
  no production code modified).
- **`message_id`**: `12`
- **Timestamp**: `2026-07-23 18:25:53+00:00`
- `NotificationOutcome`: `sent=True`, `chat_id=5507703201`

**Rendered payload actually sent** (news card header + generated draft):
```
📰 UNKNOWN · 2026-07-23
Робототехнический стартап Atoms сооснователя Uber Трэвиса Каланика привлёк $1,7 млрд. Оценку компании не раскрыли.
https://t.me/vcnews/62532

Atoms привлёк $1,7 млрд до выпуска первого продукта

Робототехнический стартап Atoms, связанный с сооснователем Uber Трэвисом Калаником, привлёк $1,7 млрд. Раунд возглавил Andreessen Horowitz, среди инвесторов — Uber. Компания разрабатывает системы промышленной автоматизации, но пока не выпустила ни одного продукта. Оценка стартапа не раскрывается.

#робототехника #стартапы #венчурныеинвестиции #автоматизация
```

**Observation (not a bug, not fixed)**: the card header shows `UNKNOWN` instead of a category
label. This is because `NewsEvent.category` for this event is literally the enum value
`NewsCategory.UNKNOWN` — this event was never assigned a specific category upstream (Triage/
Collector territory, out of scope). `bot/formatting.py` renders whatever `event.category.value`
is, unmodified; this is not a formatting defect introduced or touched by this validation.

## `dry_run`/`chat_id` override discipline

Same pattern as Phase 14 M6: `settings.content_generation_dry_run` and `settings.
editorial_chat_id` were overridden **in-process only**, for the duration of the one
`send_editorial_card(..., dry_run=False)` call, and reverted in a `finally` block. Confirmed
reverted within the same run's final log line: `dry_run_reverted=True`,
`editorial_chat_id_reverted=None`. `.env` was not opened or modified.

## Post-validation audit

| Check | Result |
|---|---|
| Events processed | exactly 1 (`9420a3c1-ef14-4f7f-8ebf-b8a809db183e`) |
| New `EditorialTask` rows created | exactly 1 (`CONTENT_GENERATION`, `a5fa760b-...`) — the pre-existing `NEWS_ANALYSIS` task was reused, not duplicated |
| `ContentDraft` rows for this task | exactly 1 (`491db283-...`) |
| `CONTENT_GENERATION` duplicates for this event | none — audit query confirmed `content_generation_task_count=1` |
| Channel publishing | none — target was the verified private chat only |
| Approval flow invoked | none |
| Worker processes left running | none — `docker ps` shows only `ai_newsroom_postgres`/`ai_newsroom_redis`, unchanged before and after |
| Backlog scanned/processed | no — this run operated only on the two pre-identified IDs, no eligibility query was executed during execution (only during the earlier, separate selection step) |
| `.env` changed | no |

## Limitations discovered (reported per task requirement, NOT fixed — out of scope)

1. **Malformed titles from several RSS-derived sources**: `NewsEvent.title` for many events from
   "Google News RU: ИИ", "Google News: Artificial Intelligence", "Techmeme", "Lobsters",
   "Tproger", "Habr: Artificial Intelligence", "GamesIndustry.biz", and "PyTorch Releases" is
   literally a truncated HTML fragment (`'<a'`, `'<img src="..."'`, `'<p>...'`) rather than the
   real headline. A pre-existing Collector/feed-parsing defect (Phase 12 territory). Excluded
   from candidate selection for this validation; not investigated or fixed further.
2. **Uncategorized events render as "UNKNOWN" in the Telegram card header**: when
   `NewsEvent.category == NewsCategory.UNKNOWN` (this event's actual value), the rendered card
   shows the literal string "UNKNOWN" instead of a human-friendly label or a blank/omitted
   header segment. Not a defect in this validation's own code — `bot/formatting.py` and
   `NewsEvent.category` are both pre-existing and unmodified. Worth a future, separately-scoped
   look at either upstream categorization coverage or the card's fallback display for uncategorized
   events.
3. **Unverified secondary claims in generated content**: the generated draft's body includes two
   specific factual claims (lead investor Andreessen Horowitz; Uber among investors) not present
   in the source `NewsEvent.title` used for selection. This validation did not independently
   fact-check these claims against a primary source — flagged for awareness, not confirmed as
   hallucination, not fixed (would require Capability/prompt-level changes, out of this
   validation's scope).

## What was NOT done (frozen boundaries respected)

- No backlog was scanned or processed beyond the one approved event.
- No worker was started; no autonomous loop was enabled.
- No architecture, workflow contract, capability, or Collector code was modified.
- No second Telegram message was sent.
- No channel or approval flow was touched.
- `.env` was not opened or modified.

---

PHASE 14.5 REAL NEWS VALIDATION COMPLETE
