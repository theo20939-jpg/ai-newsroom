# Phase 17 Stage 1 — Human Acceptance Packet

**Source of truth: only existing stored data from the completed Stage 1 retry canary**
(`checkpoint/phase17-stage1-shadow-canary-validated`, HEAD `223df5a`). Nothing below was
regenerated, reconstructed, or inferred as a human verdict — every field is either a stored
`NewsEvent`/`ContentDraft`/`EditorialTask.workflow` value, or explicitly labeled `NOT AVAILABLE`.

## Summary

- **Canary size:** 5 real, fresh `NewsEvent`s → 5 `ContentDraft`s (production pipeline, unchanged).
- **Technical result:** 30/30 Phase 17 shadow hooks executed, 0 failures, 0 incremental LLM calls,
  0 incremental cost, 0 duplicate drafts/messages, 0 mutation of `ContentDraft`/task state by any
  shadow component.
- **Decision distribution:** Channel fit — ACCEPT ×3, REVIEW ×2, REJECT ×0. Completeness — REVIEW
  ×3, NOT_READY ×1, INSUFFICIENT_SOURCE ×1, READY ×0.
- **Known limitation carried into this packet:** READY ×0 across all 5 — this matches the
  already-disclosed M5 completeness-gate calibration gap (`docs/
  phase17_m5_editorial_completeness_gate_shadow_report.md` §23/§27), not a new finding specific to
  these 5 events. Whether this makes the shadow assessments still useful (as a REVIEW-focusing
  signal) or just noisy is one of the questions this packet asks you to judge.
- **Exact human questions this packet needs answered:** see the per-event "Human review form"
  (§K) and the Decision Matrix at the end. In short: is each channel-fit/completeness call
  correct, too strict, or too permissive; is the NOT_READY case a real defect or a calibration
  false positive; is INSUFFICIENT_SOURCE justified; is the existing production text itself
  acceptable; would any of this shadow metadata actually help an editor.
- **Stage 2 remains disabled** regardless of what this packet's review concludes — no code in
  this repository enables Stage 2 automatically, and this document does not authorize it.

---

## Event 1 — `2d35bad8` (NOT_READY case — see Special Focus §1)

### A. Identification
- Category: **AI**
- Source: Google News: Artificial Intelligence (RSS)
- Source sufficiency: **partial**
- Image present: **no** (2 candidates discovered, 1 technically/quality-accepted, but ranked
  `ineligible` — `generic_aggregator_asset`, i.e. a generic Google-News thumbnail, not judged fit
  for editorial use)
- Telegram preview created: **yes** (production `content_worker`'s own unconditional single-send
  path; `dry_run=false`; per-message delivery confirmation is NOT itself stored in the database —
  labeled here on the basis of the code path, not a separately verified receipt)

### B. Source summary
- Google made it possible, for one day, to spoof satellite imagery (per an NYT article, RSS-fed
  via Google News — the RSS payload itself is just the headline/attribution, no body text).
- No detail is available on the mechanism, timeframe, or how Google resolved it.

### C. Existing production output (sent to the private editorial chat)
> **Google на один день упростил подделку спутниковых снимков**
>
> Как сообщает The New York Times, кратковременная уязвимость или функция Google позволила легко
> создавать поддельные спутниковые изображения. Ситуация вновь поднимает вопросы доверия к
> визуальным доказательствам и рисков дезинформации. Детали механизма и масштаба требуют
> дополнительной проверки.
>
> #ИИ #Кибербезопасность #OSINT #Дезинформация

(35 words. Source button/URL handled separately by the existing Telegram formatting layer, not
shown in body text.)

### D. EditorialBrief
- Main fact: "Заголовок сообщает, что в течение одного дня Google сделал простым создание
  поддельных спутниковых изображений."
- Confirmed event details (3): the headline claim itself; publisher is The New York Times;
  category AI.
- Subject explanation required: no.
- Background context requirement: none available (`background_context: []`).
- Why-it-matters available: yes (trust in visual evidence / disinformation risk).
- What-next available: yes (recommends cautious editorial framing, verify mechanism/timeline).
- Uncertainty requirements: yes — mechanism, timing, and Google's own remediation are all
  unknown; full article text isn't in the RSS payload, only the linked headline.
- Source sufficiency reason: `word_count=17`, `sentence_count=1`, `concrete_details=33`,
  `below_sufficient_threshold`.

### E. Channel fit
- Decision: **REVIEW**
- Confidence: medium
- Matched topics: AI
- Reason codes: `matched_topic_but_confidence_not_high`
- Threshold-sensitive: **yes** — fit_score 0.65 landed just past the ACCEPT/REVIEW boundary on
  confidence alone, not a topic mismatch.

### F. Adaptive length
- Format recommendation: `short_update`
- Ideal range: 140–220 words (target 160)
- Safe range: 90–140 words (target 115) — narrower than ideal, per the plan's own
  `partial`-source constraint
- Actual production word count: **35**
- Range status: **below both ranges** — the production draft is roughly a quarter of even the
  safe-range floor.

### G. Beginner-friendly plan
- Explanation required: no
- Terms requiring explanation: none listed as required; `unexplainable_terms` flagged
  (`New`, `The`, `Times`, `York` — a known regex-fragmentation artifact of "The New York Times",
  not real jargon, already disclosed as a limitation in the M4/M5 reports)
- Context requirement: background context budget = 0
- Complexity level: normal, jargon risk **high**
- Safe glossary usage: none needed for this case

### H. Completeness
- Recommendation: **NOT_READY**
- Completeness score: **0.591**
- Required criteria: 11 total — 5 pass, 3 partial, **3 fail**
- FAIL: `headline_fact_covered` (0.0 — the brief's own main-fact sentence isn't found, verbatim or
  via fuzzy match, in the 35-word production body), `what_next_covered` (0.0), `uncertainty_covered`
  (0.0)
- PARTIAL: `event_details_covered` (0.33), `safe_length_compliance` (0.4 — below range),
  `structure_adequate` (0.6 — 1 paragraph vs. target 2)
- Missing available information: the what-next/uncertainty *text* the brief itself generated is
  not literally echoed in the body — see Special Focus §1 for whether this is a real gap or a
  paraphrase the matcher missed.
- Headline-rewrite risk: **low** (pass) — the draft does add information beyond the headline.
- Safe-length result: below range.
- Reason codes: `main_fact_not_covered`.

### I. Fact Safety
- Raw status: **pass**
- Calibrated status: **pass**
- Unresolved flags: none
- Suppressed false positives: none
- Human review required: **no**
- Serious unsupported claim: **no**

### J. Delivery
- Image/no-image: no-image (see §A)
- Mode: text message (not photo caption — `adaptive_length_plan.delivery_mode = text_message`)
- Character count: 295 chars (35 words)
- Truncation: NOT AVAILABLE (not recomputed against the real Telegram render for this packet;
  well under any known limit at this length)
- Duplicate delivery: no (0 duplicate `ContentDraft` rows, verified directly)
- URL visible in body: no (the production card format keeps the source URL out of the body text)
- Source button present: NOT AVAILABLE (governed by the existing, unmodified Telegram formatting
  layer; not re-verified per-message for this packet)

### K. Human review form

Channel fit:
[ ] Correct
[ ] Too strict
[ ] Too permissive

Completeness:
[ ] Correct
[ ] Too strict
[ ] Too permissive

Production text:
[ ] Acceptable as-is
[ ] Needs minor edit
[ ] Needs major rewrite

Source classification:
[ ] Correct
[ ] Incorrect

Final human decision:
[ ] Approve for Stage 2 comparison
[ ] Keep shadow only
[ ] Block and tune first

Human notes:
____________________________

---

## Event 2 — `12ce8e52` (INSUFFICIENT_SOURCE case — see Special Focus §2)

### A. Identification
- Category: **STARTUPS**
- Source: Hacker News Front Page (NEWS_API)
- Source sufficiency: **headline_only**
- Image present: **NOT AVAILABLE / effectively no** (`article_fetch_error: internal_fetch_error`,
  0 candidates discovered — the article fetch itself failed, so image discovery never got real
  data to work with)
- Telegram preview created: **yes** (same basis as Event 1)

### B. Source summary
- The entire source content **is** the headline: "EU rules on AI models become enforceable.
  What's going to change?" (`event_content == event_title`, no body text at all).
- No details on which rules, timing, affected models, or practical impact.

### C. Existing production output
> **Правила ЕС для моделей ИИ становятся обязательными**
>
> Нормы ЕС для моделей искусственного интеллекта переходят от требований к обязательному
> исполнению. Для AI-стартапов это может повлиять на запуск продуктов и соблюдение требований, но
> детали о сроках, затронутых моделях и последствиях пока не уточнены.
>
> #ИИ #Стартапы #ЕС #AI

(34 words.)

### D. EditorialBrief
- Main fact: EU AI-model rules become enforceable (literally the headline, restated).
- Confirmed event details (2): the headline claim; the fact that the source itself poses "what
  will change" as an open question.
- Subject explanation required: no.
- Background context: none available.
- Why-it-matters available: yes, but itself hedged ("without data on specific rules... impossible
  to determine scope").
- What-next available: yes — explicitly recommends *not* expanding past a short, cautious update.
- Uncertainty requirements: yes, extensive — brief's own `uncertainties` list includes a literal
  "source material is limited (source_sufficiency=headline_only); most specifics are unconfirmed"
  entry.
- Source sufficiency reason: `content_equals_title`.

### E. Channel fit
- Decision: **REVIEW**
- Confidence: medium
- Matched topics: AI
- Mismatch reason: `category_mismatch` (source's own category is STARTUPS; content classifier
  detected AI as the real topic) + `headline_only_capped_to_review` (a thin source is never
  allowed to reach ACCEPT on its own, by design)
- Threshold-sensitive: **partially** — the category mismatch is real evidence, not a borderline
  score; the "capped to REVIEW" behavior is a deliberate policy, not a threshold artifact.

### F. Adaptive length
- Format recommendation: `insufficient_source`
- Ideal/safe range: 40–90 words (target 65) — both ranges are identical (no separate "safe"
  narrowing possible below an already-thin floor)
- Actual production word count: **34**
- Range status: **below range** (34 vs. floor 40) — but only by 6 words, and the plan's own
  `safety_constraints` explicitly forbid padding a thin source to hit the floor artificially.

### G. Beginner-friendly plan
- Explanation required: no; jargon risk **low**
- No terms flagged
- `complexity: insufficient` — the lowest complexity bucket, matching `headline_only`

### H. Completeness
- Recommendation: **INSUFFICIENT_SOURCE**
- Completeness score: **0.55**
- Required criteria: 10 total — 4 pass, 3 partial, 3 fail (`why_it_matters_covered`,
  `what_next_covered`, `uncertainty_covered` — all fail on literal-text matching, see Special
  Focus §2)
- `headline_rewrite_avoided`: **not_applicable** (thin sources are never scored on rewrite risk,
  by design — see the M5 report's own §9)
- `unsupported_claims_absent`: **partial** (0.5 — reflects the calibrated Fact Safety REVIEW
  status below, not a FAIL)
- Reason code for the overall verdict: `insufficient_source_honestly_handled`.

### I. Fact Safety
- Raw status: **review**
- Calibrated status: **review**
- True-positive flags (3): `uncertain:Правила ЕС`, `unsupported:Нормы ЕС`,
  `unsupported:Для AI-стартапов` — all entity-type flags on paraphrased forms of "EU rules"/"AI
  startups", not fabricated facts (no invented number, date, or quote)
- Suppressed false positives: none
- Human review required: **yes**
- Serious (FAIL-tier) unsupported claim: **no** — severity capped at `medium`, entity-type only

### J. Delivery
- Image/no-image: no-image (fetch failed upstream)
- Mode: text message
- Character count: 251 chars (34 words)
- Truncation: NOT AVAILABLE (not re-verified; well under any limit)
- Duplicate delivery: no
- URL visible in body: no
- Source button present: NOT AVAILABLE

### K. Human review form

Channel fit:
[ ] Correct
[ ] Too strict
[ ] Too permissive

Completeness:
[ ] Correct
[ ] Too strict
[ ] Too permissive

Production text:
[ ] Acceptable as-is
[ ] Needs minor edit
[ ] Needs major rewrite

Source classification:
[ ] Correct
[ ] Incorrect

Final human decision:
[ ] Approve for Stage 2 comparison
[ ] Keep shadow only
[ ] Block and tune first

Human notes:
____________________________

---

## Event 3 — `17389223` (REVIEW case — see Special Focus §3)

### A. Identification
- Category: **AI**
- Source: Habr: Machine Learning (RSS)
- Source sufficiency: **sufficient**
- Image present: **yes** (2 eligible candidates ranked; top pick is the article's own Open Graph
  image, 1200×630, quality score 98)
- Telegram preview created: **yes**

### B. Source summary
- Bottleneck Labs gave an autonomous agent ("Saul", on "GPT-5.6 Sol") real business
  infrastructure (a live iOS app, a real bank account, a computer with full access) for 24 hours.
- In that time: 320.7M input tokens used, 1,129 tool calls, 5 new users acquired, $0 revenue,
  $99.50 spent (balance $350→$250.50), estimated business value down $447.
- The source article itself questions whether the agent or the experiment's own design is really
  what "failed."
- **Note:** this is the *same underlying Habr article* as Event 4 below, picked up independently
  by two different RSS feeds (`Habr: Machine Learning` here, `Habr: Artificial Intelligence` for
  Event 4) as two separate `NewsEvent` rows — not a duplicate `ContentDraft` (each has its own
  `event_id`/`task_id`/`draft_id`), but worth reading together.

### C. Existing production output
> **ИИ-агент за сутки не спас бизнес, а снизил его стоимость**
>
> В эксперименте Bottleneck Labs автономный агент Saul получил доступ к реальному
> iOS-приложению, банковскому счету и компьютеру. За 24 часа он привлек пять пользователей, не
> заработал денег, потратил $99,50, а оценочная стоимость бизнеса снизилась на $447. Исследователи
> отмечают: результат мог зависеть и от постановки эксперимента — это стресс-тест, а не
> окончательный вердикт об ИИ-агентах.
>
> #ИИ #ИИагенты #Автоматизация #Технологии

(53 words.)

### D. EditorialBrief
- Main fact: Bottleneck Labs published the experiment report.
- Confirmed event details: 9 items (full financial/usage figures, agent name, token/tool-call
  counts, the source's own "who really failed" framing).
- Subject explanation required: no.
- Background context: none available.
- Why-it-matters available: yes, explicitly hedged (result may reflect experiment design, not
  just model capability).
- What-next available: yes — recommends publishing as analysis, separating confirmed results from
  evaluative conclusions, disclosing experiment-design limitations.
- Uncertainty requirements: yes (4 items — exact dates, app/agent-action detail, computer-access
  scope, valuation methodology).
- Source sufficiency reason: `word_count=118`, `sentence_count=5`, `concrete_details=29`.

### E. Channel fit
- Decision: **ACCEPT**
- Confidence: high, fit_score 0.9
- Matched topics: SOFTWARE, AI, BUSINESS_TECH, SCIENCE_TECH
- Reason codes: `category_mismatch` present but **non-blocking** here (source's own category is
  AI; classifier's primary topic is SOFTWARE) — still ACCEPT because match confidence is high and
  multiple topics matched.
- Threshold-sensitive: no — this is a clear multi-topic match, not a borderline score.

### F. Adaptive length
- Format recommendation: `explainer`
- Ideal range: 220–320 words (target 270)
- Safe range: 258–308 (target 283) — for the *Beginner-Friendly* plan specifically; the
  Adaptive-Length plan's own range is the ideal range above (no separate narrowing recorded)
- Actual production word count: **53**
- Range status: **far below range** — roughly one-fifth of even the lower bound.

### G. Beginner-friendly plan
- Explanation required: no (despite `jargon_risk: high`)
- Unexplainable terms flagged: `Bottleneck`, `GPT`, `Labs`, `Saul`, `Sol` (proper nouns/model
  names, correctly left unexplained per the plan's own no-fabrication rule)
- Complexity: **complex**

### H. Completeness
- Recommendation: **REVIEW**
- Completeness score: **0.591**
- Required criteria: 11 — 5 pass, 3 partial, **3 fail**
- FAIL: `why_it_matters_covered` (0.0), `what_next_covered` (0.0), `structure_adequate` (0.0 — 1
  paragraph vs. target 3)
- PARTIAL: `event_details_covered` (0.44), `uncertainty_covered` (0.25), `safe_length_compliance`
  (0.4)
- Fact Safety criterion: **pass** (1.0)
- Headline-rewrite risk: **low**
- Reason code: `other_required_criteria_failed`.

### I. Fact Safety
- Raw status: **pass**
- Calibrated status: **pass**
- Unresolved / suppressed: none
- Human review required: **no**

### J. Delivery
- Image/no-image: **image** (top-ranked Open Graph image, 1200×630, quality 98/100)
- Mode: per `adaptive_length_plan.delivery_mode` — text message (plan's own reason code:
  `exceeds_photo_caption_recommend_text_over_truncation`)
- Character count: 392 chars (53 words)
- Truncation: NOT AVAILABLE
- Duplicate delivery: no
- URL visible in body: no
- Source button present: NOT AVAILABLE

### K. Human review form

Channel fit:
[ ] Correct
[ ] Too strict
[ ] Too permissive

Completeness:
[ ] Correct
[ ] Too strict
[ ] Too permissive

Production text:
[ ] Acceptable as-is
[ ] Needs minor edit
[ ] Needs major rewrite

Source classification:
[ ] Correct
[ ] Incorrect

Final human decision:
[ ] Approve for Stage 2 comparison
[ ] Keep shadow only
[ ] Block and tune first

Human notes:
____________________________

---

## Event 4 — `847618cd` (REVIEW case — see Special Focus §3; same story as Event 3)

### A. Identification
- Category: **SOFTWARE**
- Source: Habr: Artificial Intelligence (RSS)
- Source sufficiency: **sufficient**
- Image present: **yes** (same 2 eligible candidates as Event 3 — identical underlying article)
- Telegram preview created: **yes**

### B. Source summary
Identical underlying story to Event 3 (§B above) — same Habr article, picked up via a different
RSS feed. Research/EditorialBrief were independently rebuilt for this separate `NewsEvent` row and
are near-identical in substance, with minor extraction differences (see below).

### C. Existing production output
> **Автономный ИИ-агент протестировал реальный бизнес — и ушёл в минус**
>
> В эксперименте Bottleneck Labs агент Saul получил на 24 часа доступ к iOS-приложению,
> банковскому счёту и бизнес-инфраструктуре. Он привлёк пять пользователей, но не заработал денег:
> со счёта ушло $99,50, а оценка бизнеса снизилась на $447. Заявления о лжи и спаме пока не
> подтверждены представленными данными.
>
> #ИскусственныйИнтеллект #ИИагенты #БезопасностьИИ #Стартапы

(45 words — a genuinely different production text from Event 3's, despite the same source
article; different hashtags too.)

### D. EditorialBrief
- Main fact: same Bottleneck Labs report fact.
- Confirmed event details: 8 items (near-identical to Event 3, includes the agent's name derived
  as its own separate detail item here).
- Why-it-matters: same hedge (result may reflect experiment design).
- What-next: recommends publishing as an analysis/case study on autonomous-agent reliability,
  explicitly separating confirmed results from the headline's own "lied and spammed" framing.
- Uncertainty requirements: 4 items, including explicitly "whether the agent or the experiment
  failed remains an open question, not an established fact."
- Source sufficiency reason: same as Event 3 (`word_count=118`, `sentence_count=5`,
  `concrete_details=29`).

### E. Channel fit
- Decision: **ACCEPT**
- Confidence: high, fit_score 0.9
- Matched topics: SOFTWARE, AI, BUSINESS_TECH, SCIENCE_TECH
- Reason codes: **none** (`category_match: true` here — this event's own source category
  (SOFTWARE) already matches the classifier's own primary topic, unlike Event 3's cross-category
  match)
- Threshold-sensitive: no.

### F. Adaptive length
- Format recommendation: `explainer`
- Ideal range: 220–320 (target 270); Beginner-Friendly safe range 230–280 (target 255)
- Actual production word count: **45**
- Range status: **far below range**.

### G. Beginner-friendly plan
- Same unexplainable terms as Event 3 (`Bottleneck`, `GPT`, `Labs`, `Saul`, `Sol`); complexity
  **complex**.

### H. Completeness
- Recommendation: **REVIEW**
- Completeness score: **0.636** (higher than Event 3's 0.591, despite being a shorter draft) —
  driven by `why_it_matters_covered` passing here (Event 3's did not) and one fewer FAIL
- Required criteria: 11 — 5 pass, 4 partial, **2 fail** (`what_next_covered`,
  `structure_adequate`)
- `unsupported_claims_absent`: **partial** (0.5, reflecting the calibrated REVIEW status below —
  see Special Focus §3 for the specific flag)
- Headline-rewrite risk: **low**

### I. Fact Safety
- Raw status: **review**
- Calibrated status: **review**
- True-positive flag: `unsupported:Автономный ИИ-агент` — the production title's own opening
  phrase ("Автономный ИИ-агент...") flagged as an unsupported entity mention (a generic descriptive
  phrase, not a specific fabricated fact)
- **Note:** the underlying raw baseline Fact Safety audit (Phase 15 M5, not the calibrated M5
  layer) recorded this claim at `status: "block"` / `highest_risk: "high"` before calibration —
  the calibration layer downgraded it to `review`/`medium`. This is disclosed, not hidden — see
  Special Focus §3 for discussion of whether this is a correct calibration or a risk worth a
  second look.
- Human review required: **yes**

### J. Delivery
- Image/no-image: **image** (same 2 eligible candidates as Event 3)
- Mode: text message
- Character count: 310 chars (45 words)
- Truncation: NOT AVAILABLE
- Duplicate delivery: no (separate `ContentDraft`/`event_id` from Event 3, confirmed)
- URL visible in body: no
- Source button present: NOT AVAILABLE

### K. Human review form

Channel fit:
[ ] Correct
[ ] Too strict
[ ] Too permissive

Completeness:
[ ] Correct
[ ] Too strict
[ ] Too permissive

Production text:
[ ] Acceptable as-is
[ ] Needs minor edit
[ ] Needs major rewrite

Source classification:
[ ] Correct
[ ] Incorrect

Final human decision:
[ ] Approve for Stage 2 comparison
[ ] Keep shadow only
[ ] Block and tune first

Human notes:
____________________________

---

## Event 5 — `ac1f1ff5` (REVIEW case — see Special Focus §3)

### A. Identification
- Category: **AI**
- Source: Google News RU: ИИ (RSS)
- Source sufficiency: **partial**
- Image present: **no** (1 candidate found, ranked `ineligible` — `generic_aggregator_asset`,
  same generic-thumbnail pattern as Event 1)
- Telegram preview created: **yes**

### B. Source summary
- A Chinese AI model, "Kimi K3" (claimed 2.8 trillion parameters), had its weights published in
  open access.
- The headline itself claims the model's cost is one-third that of top competitors — no pricing,
  competitor names, benchmarks, or license terms are given.

### C. Existing production output
> **Kimi K3: 2,8 трлн параметров и открытые веса**
>
> Китайская ИИ-модель Kimi K3 стала доступна в открытом доступе с опубликованными весами.
> Источник заявляет, что её стоимость втрое ниже, чем у топовых конкурентов. Данные о цене,
> производительности, лицензии и условиях использования требуют проверки.
>
> #ИИ #KimiK3 #ИскусственныйИнтеллект

(33 words.)

### D. EditorialBrief
- Main fact: the model is named Kimi K3.
- Confirmed event details (6): Chinese origin, 2.8T parameters, open access, weights published,
  the headline's own "one-third cheaper" claim, source is ixbt.com.
- Why-it-matters: hedged (methodology/competitors/specs all unverified).
- What-next: explicitly recommends framing availability/parameters as the *source's own claims*,
  not a confirmed breakthrough; verify weight provenance, license, price comparison, performance,
  publication date before any expanded coverage.
- Uncertainty requirements: 3 items (cost/competitor/spec/date detail; who published the weights
  and what the cited price means; only headline+link available, no full article).
- Source sufficiency reason: `word_count=23`, `sentence_count=1`, `concrete_details=41`,
  `below_sufficient_threshold`.

### E. Channel fit
- Decision: **ACCEPT**
- Confidence: high, fit_score 0.9
- Matched topics: AI
- Reason codes: none (clean category match)
- Threshold-sensitive: no.

### F. Adaptive length
- Format recommendation: `short_update`
- Ideal range: 140–220 (target 160); Beginner-Friendly safe range 170–220 (target 195)
- Actual production word count: **33**
- Range status: **far below range**.

### G. Beginner-friendly plan
- Explanation required: no; jargon risk **medium**
- Unexplainable term flagged: `Kimi` (product name, correctly left unexplained)
- Complexity: **normal**

### H. Completeness
- Recommendation: **REVIEW**
- Completeness score: **0.682** (the highest of the 3 REVIEW cases)
- Required criteria: 11 — 5 pass, 5 partial, **1 fail**
- `headline_rewrite_avoided`: **partial** (0.5, `headline_rewrite_risk_medium`) — the only event
  of the 5 where rewrite risk is not clearly LOW; worth a specific look (Special Focus §3).
- `unsupported_claims_absent`: partial (0.5, reflecting calibrated REVIEW below)
- Reason code: `other_required_criteria_failed`.

### I. Fact Safety
- Raw status: **review**
- Calibrated status: **review**
- True-positive flag: `unsupported:Китайская ИИ-модель Kimi K3` — an entity-type flag on the
  production body's own opening descriptive phrase, medium severity, no specific number/date
  fabricated (the 2.8T-parameter figure itself is *not* flagged — it matches research facts).
- Human review required: **yes**

### J. Delivery
- Image/no-image: no-image
- Mode: text message
- Character count: 249 chars (33 words)
- Truncation: NOT AVAILABLE
- Duplicate delivery: no
- URL visible in body: no
- Source button present: NOT AVAILABLE

### K. Human review form

Channel fit:
[ ] Correct
[ ] Too strict
[ ] Too permissive

Completeness:
[ ] Correct
[ ] Too strict
[ ] Too permissive

Production text:
[ ] Acceptable as-is
[ ] Needs minor edit
[ ] Needs major rewrite

Source classification:
[ ] Correct
[ ] Incorrect

Final human decision:
[ ] Approve for Stage 2 comparison
[ ] Keep shadow only
[ ] Block and tune first

Human notes:
____________________________

---

## Special Focus

### 1. The NOT_READY case (`2d35bad8`)

Three required criteria failed: `headline_fact_covered`, `what_next_covered`,
`uncertainty_covered` — all scored **0.0**, all with `matched_evidence: []`.

Distinguishing what actually happened:
- **This is not "missing information that existed in the source"** — the source (a bare RSS
  headline via Google News) never had a body to draw from; Research/EditorialBrief already built
  their own `why_it_matters`/`what_next`/`uncertainties` text entirely from the headline plus the
  model's own editorial judgment, not from withheld source facts.
- **It is not obviously a production copy defect either** — reading the actual body (§C above),
  it *does* express uncertainty in its own words ("Детали механизма и масштаба требуют
  дополнительной проверки" — "details of the mechanism and scope require further verification").
  That sentence is a real, honest uncertainty statement. It simply doesn't literally match, word-
  for-word or via fuzzy overlap, the specific `uncertainties` list items the shadow brief
  generated (which are longer, more specific sentences than the production copy's own compressed
  version).
- **This does look like a deterministic matching/calibration gap** — the completeness gate's
  evidence-matching (fuzzy phrase/claim overlap, `services/editorial_completeness.py`) apparently
  did not recognize the production body's own shorter paraphrase as covering the brief's longer
  uncertainty/what-next sentences. This is the same class of gap already disclosed in the M5
  report (§23: "a real, still-imperfect evidence-matching gap").
- `headline_fact_covered` failing is more concerning on its face — the brief's main fact
  ("Google made spoofing satellite imagery easy for a day") *is* substantively present in the
  production body's own first sentence, just phrased differently and attributed to NYT rather
  than restating "Google" as the grammatical subject. Whether a human reader would call this
  "covered" is exactly the judgment call this packet is asking you to make.

**Question for you:** is this NOT_READY verdict catching a real gap the production copy has, or
is it a calibration false positive against genuinely-present-but-differently-phrased content?

### 2. The INSUFFICIENT_SOURCE case (`12ce8e52`)

- **Why the source was insufficient:** the entire `NewsEvent.content` literally equals the
  headline (`content_equals_title` reason code) — there was never a body to extract from. This is
  a real, structural thinness, not a collector/extraction bug.
- **Did the production text handle uncertainty honestly?** Yes — the body explicitly states that
  timing/scope/consequences are unclear ("детали о сроках, затронутых моделях и последствиях пока
  не уточнены"), directly matching the brief's own uncertainty list in substance.
- **Would a longer candidate risk fabrication?** Very likely yes — there is no additional real
  evidence to expand into; a longer draft at this source-sufficiency level would need to either
  repeat itself or invent detail. The `adaptive_length_plan`'s own `safety_constraints` explicitly
  forbid padding, precisely to avoid this.
- **Is INSUFFICIENT_SOURCE preferable to NOT_READY here?** By this milestone's own design, yes —
  the distinguishing question is "did copywriting fail to use available evidence" (NOT_READY,
  Event 1's own case, arguably) vs. "was there structurally nothing more to use" (this case). The
  classification looks correctly applied.

### 3. The three REVIEW cases (`17389223`, `847618cd`, `ac1f1ff5`)

- **`17389223`/`847618cd` (same underlying story, two `NewsEvent` rows):** REVIEW came from
  `other_required_criteria_failed` — specifically `why_it_matters_covered`/`what_next_covered`/
  `structure_adequate` failing on literal-text matching (the production copy paraphrases the
  brief's own longer sentences rather than restating them), the same evidence-matching gap as
  Event 1's NOT_READY case (§1) — **not** channel ambiguity (both ACCEPTed cleanly), **not** a
  length issue in the sense of "too short to be safe" (both are simply well below the *ideal*
  range while still being coherent, complete-sounding short items), and **not** primarily Fact
  Safety (Event 3 is calibrated `pass`; Event 4 is calibrated `review` on one entity-type flag,
  discussed below).
- **`847618cd`'s Fact Safety detail worth a second look:** the *raw*, pre-calibration Phase 15 M5
  baseline audit flagged this case at `status: "block"` / `highest_risk: "high"` (the most severe
  tier that audit has) on the claim `"Автономный ИИ-агент"` ("autonomous AI agent" — the
  production title's own opening words). The M5 calibration layer downgraded this to
  `review`/`medium`. Read literally, "autonomous AI agent" is a generic descriptive phrase, not a
  specific invented fact (no fabricated number, name, or quote) — but a `block`→`review` downgrade
  on the *raw* audit's own highest-severity tier is exactly the kind of case this packet should
  put in front of a human rather than accept on the calibration layer's say-so alone.
- **`ac1f1ff5` is the only case with headline-rewrite risk above LOW** (`medium`, partial credit
  0.5) — reading the actual body (§C, Event 5), it does add real information beyond the headline
  (explicitly flags that price/performance/license claims are the *source's own claims*, not
  confirmed) — this looks more like the deterministic rewrite-risk heuristic being conservative on
  a short body than a genuine "just repeats the headline" case, but is flagged here for your own
  read.

---

## Decision Matrix

| Event | Category | Source sufficiency | Channel fit | Completeness | Fact Safety | Production text quality | Suspected false positive | Human decision | Stage 2 eligibility |
|---|---|---|---|---|---|---|---|---|---|
| `2d35bad8` | AI | partial | REVIEW | NOT_READY | pass | _(your read)_ | main_fact/what_next/uncertainty matching (suspected) | | |
| `12ce8e52` | STARTUPS | headline_only | REVIEW | INSUFFICIENT_SOURCE | review | _(your read)_ | none suspected | | |
| `17389223` | AI | sufficient | ACCEPT | REVIEW | pass | _(your read)_ | why_it_matters/what_next matching (suspected) | | |
| `847618cd` | SOFTWARE | sufficient | ACCEPT | REVIEW | review | _(your read)_ | raw block→review Fact Safety downgrade (flagged for review) | | |
| `ac1f1ff5` | AI | partial | ACCEPT | REVIEW | review | _(your read)_ | headline-rewrite-risk=medium (suspected conservative) | | |

(Human-decision and Stage 2-eligibility columns intentionally left blank.)

---

## Stage 2 Readiness Rule

Stage 2 is **not** recommended automatically merely because Stage 1 was technically stable (30/30
hooks executed, 0 invariant violations). Two possible conclusions are laid out below — this
document does not choose between them on your behalf:

**A. APPROVE STAGE 2** — suitable if, after your own review above, at least 4/5 decisions are
judged correct and no dangerous false positive or false READY is found. Note that 0/5 events
reached READY in this sample, so "false READY" is trivially absent here — the real question is
whether REVIEW/NOT_READY/INSUFFICIENT_SOURCE were each *correctly* assigned.

**B. TUNE BEFORE STAGE 2** — suitable if you judge that: NOT_READY (Event 1) is a false positive
driven by evidence-matching rather than a real gap; REVIEW is systematically too strict across
Events 3-5 (the same matching pattern recurs in 3 of 5 cases); Fact Safety remains noisy (the
raw `block`→calibrated `review` downgrade on Event 4 is a specific case worth resolving one way or
the other); or you find the shadow assessments, as currently calibrated, would not actually help
an editor make a faster/better decision than reading the production text alone.

Both conclusions are consistent with the technical result (30/30 hooks, 0 invariant violations) —
this packet's job is only to surface the *editorial* judgment, not the engineering one.
