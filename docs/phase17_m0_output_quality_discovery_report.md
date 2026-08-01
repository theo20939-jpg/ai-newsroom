# Phase 17 M0 — Editorial Output Quality Discovery — Report

Branch: `feature/phase17-editorial-intelligence`, created from `checkpoint/phase16-callback-runtime-fix`
(`9c2cdeb`, tip of `feature/phase16-image-intelligence` at the time of branching — verified live,
not assumed: `git status` clean except the preserved `scripts/_phase15_m4_final_cutover_samples.json`,
all 7 containers `Up`/`healthy` with `RestartCount=0`, `editorial_scoring_version=v1` and
`fact_safety_mode=shadow` both still at their config defaults, `image_intelligence_mode=shadow`/
`image_candidate_persistence_mode=finalists`/`image_editorial_preview_enabled=true` unchanged in
`.env`).

**Scope discipline**: this is a discovery/measurement/design milestone only. No production prompt,
capability, scoring, threshold, Fact Safety, LLM Gateway routing, Image Intelligence, Telegram UX,
or source-collector code was changed. The only new files are a read-only analysis script, its test
coverage, and this report.

## 1. Executive summary

The two problems the user separated - **(A) editorial output quality** and **(B) channel/topic
relevance** - are architecturally almost entirely independent, and the real data confirms both are
real, distinct, and currently unaddressed by anything in the pipeline:

- **(A) Quality**: every one of 269 real, non-synthetic `ContentDraft` rows currently in the
  database has a body between 20 and 55 words (median 33) - a band roughly **3-4× narrower** than
  even the most conservative length this task's own proposed adaptive ranges would assign to the
  *simplest* news (90-140 words). 100% are a single paragraph. The root cause is not the prompt's
  wording so much as the pipeline's own data flow: `CopywritingCapability` never sees
  `NewsEvent.content` - only `ResearchCapability`'s already-paraphrased `facts: list[str]` - and for
  roughly a third of the manually audited sample, that underlying source content is itself
  degenerate (a bare headline repeated, or literally the word "Comments").
- **(B) Relevance**: there is no channel profile, no allowed/forbidden topic list, no channel-fit
  score, and no article-level topic classification anywhere in this codebase. `NewsEvent.category`
  is assigned once, deterministically, entirely from the **source's** static config tags
  (`services/event_category.py::categorize_from_tags()`) - never from the article's actual content.
  The user's real Netflix/Walking Dead example is exactly this: Engadget is tagged
  `[gadgets, consumer-tech, ai]`, so *every* Engadget article - including a streaming-rights deal
  story with nothing to do with gadgets - inherits `GADGETS`. In the 32-draft manual audit, this
  same category-inheritance mechanism produced a measurable, non-isolated problem: 25% of manually
  audited drafts (8/32) had some form of category/relevance issue.

Both problems are real, both are measurable today from already-collected data, and this report's
recommended Phase 17 ordering (§18) deliberately **decouples** them, pulling a dedicated
channel/topic-relevance milestone earlier than the user's own draft ordering implied, because it
requires no new memory/history infrastructure and directly fixes the single clearest failure mode
found.

## 2. Current production pipeline

Traced by direct code inspection (`capabilities/*.py`, `workflows/definitions/*.py`,
`services/collector.py`, `services/event_category.py`, `bot/formatting.py`), not assumed:

```
NewsEvent (title, content, summary[dead], url, category, published_at)
  -> NEWS_ANALYSIS: research -> intelligence -> engagement_analysis -> scoring
  -> EditorialTask (workflow="CONTENT_GENERATION", reuses research+intelligence results)
  -> CONTENT_GENERATION: research(reused) -> intelligence(reused) -> copywriting -> quality
  -> ContentDraft (title, body, hashtags)
  -> bot/formatting.py::render_editorial_card() -> Telegram (photo caption or text message)
```

**1-2. Fields passed to generation / what NEWS_ANALYSIS results reach CopywritingCapability**:
`CopywritingCapability._build_request()` (`capabilities/copywriting_capability.py:111-130`) builds
its prompt context from exactly four things: `news_event.title`, `news_event.category`,
`context.business.language`, plus `step_results["research"]` (`{facts, confidence, gaps}`) and
`step_results["intelligence"]` (`{significance, angle, audience_relevance, recommendation}`).
`news_event.content` and `news_event.url` are **never** read by Copywriting directly - a deliberate,
documented rule ("MUST NOT hold a direct reference... never re-extract", mirrored from
`IntelligenceCapability`). `news_event.summary` is likewise never read by Copywriting or Research.

**3. Facts lost before generation**: everything in `news_event.content` that
`ResearchCapability`'s single LLM call does not choose to put in its `facts: list[str]` array is
permanently unavailable to every later step - Intelligence, Copywriting, and Quality all only ever
see Research's paraphrase, never the original text again. There is no second read of `content`
anywhere downstream. This is the single largest architectural bottleneck found in this discovery.

**4. Active prompt versions** (`prompts/*/vN.yaml`, resolved by each Capability's own
`PROMPT_VERSION` constant): `research` v2, `intelligence` v2 (not separately audited here, same
title/category/research-only input shape), `copywriting` **v3**, `quality` **v3**. `engagement`
v1 and `scoring` v2 exist but belong to `NEWS_ANALYSIS`, not `CONTENT_GENERATION` - irrelevant to
the copywriting path.

**5. Where length/structure/language/style/headline/hashtags/context limits are set**:
- **Length**: nowhere at generation time beyond "Keep the title concise and the body suitable for
  a short social post" (`prompts/copywriting/v3.yaml` rule 2) - no word count, sentence count, or
  paragraph target anywhere. The only length *enforcement* anywhere in the pipeline is post-hoc
  truncation in `bot/formatting.py::render_editorial_card()` (`SAFE_LIMIT=4096` UTF-16 units
  text-only, `CAPTION_SAFE_LIMIT=1024` when a photo is attached, Phase 16 UX fix) - a safety net for
  Telegram's own hard limits, never a generation-time target.
- **Structure**: not specified. `body` is a single `string` schema field with no
  paragraph/section guidance - and empirically (§4) 100% of real output is one paragraph.
- **Language**: explicit and versioned (`copywriting` v3's own addition) - "Always write... entirely
  in the language given by 'Target output language'... never mix languages."
- **Headline/hashtags**: `title`/`hashtags` are separate schema fields; hashtags rule: "relevant to
  the event's category and content, no more than a handful" - no explicit count limit.
- **Context limits**: none explicit in the prompt; the real limiting factor is architectural (§3).

**6. Full article vs. excerpt vs. title-only**: confirmed by adapter code, not assumed.
`integrations/sources/rss_source.py::_to_raw_item()` uses `entry.get("summary") or entry.get(
"title")` from `feedparser` - the RSS/Atom feed's own `<description>`/`<summary>` element (a
publisher-controlled teaser), **never a fetch of the actual article page**. No adapter anywhere in
this codebase fetches full article HTML/text. `integrations/sources/telegram_source.py` uses the
full Telegram message text (`message.text`), which for a channel post genuinely is the whole
original content, not a teaser of something longer.

**7. Limits/truncation causing lost context**: two, structurally different: (a) the RSS-teaser
ceiling above - `NewsEvent.content` is frequently already truncated *at the source*, before this
codebase ever sees it, and there is no code path to go get the rest; (b) `render_editorial_card()`'s
Telegram-side shrink/truncate, which only ever operates on Copywriting's own already-short output
and in practice almost never triggers given how far under the limit real output already sits (§4).

**8. What Quality checks**: `prompts/quality/v3.yaml`'s four rules are: flag a draft that
contradicts/invents/omits key facts vs. the given title/category/summary; flag missing or vague
titles, missing summaries, and factual-sounding claims with no supporting detail; don't invent
issues; keep each issue under 30 words. Output schema is `{passed: bool, issues: list[str]}` -
free-text, unstructured. It does **not** check, as distinct structured dimensions: completeness of
subject explanation, background context, why-it-matters, what's-next, beginner-friendliness, or
whether the draft is a headline rewrite. It also cannot meaningfully check "missing summaries" in
its own stated rule, because (§9 below) `NewsEvent.summary` is populated in 0 of the 269 real drafts
audited - the rule fires against a field that is, in production, always absent. Separately: nothing
in the pipeline gates delivery on Quality's `passed` result at all -
`services/content_draft_service.py` builds the `ContentDraft` from Copywriting's output
unconditionally once the workflow completes (confirmed by `services/fact_safety.py`'s own docstring,
which cites this exact gap as its own motivating root cause).

**9. Where category is determined**: `services/collector.py:199`,
`category=categorize_from_tags(definition.tags if definition is not None else None)` -
`services/event_category.py`, a fully deterministic, priority-ordered mapping from a **source's**
static `tags: list[str]` (authored once per source in `config/newsroom_sources_v1/sources/*.yaml`)
to the `EventCategory` enum. No capability in `NEWS_ANALYSIS` or `CONTENT_GENERATION` produces a
category/topic/classification field (confirmed by inspecting every capability's
`output_schema`) - this was already true and already documented as of Phase 15 M2, and remains true
today.

**10. Category inheritance**: **entirely** source-level, never per-article. Confirmed directly:
Engadget's pack entry (`config/newsroom_sources_v1/sources/media.yaml:93-107`) carries
`tags: [gadgets, consumer-tech, ai]` - fixed at source-registration time, completely blind to any
individual article's real subject. Every Engadget article gets `GADGETS`, forever, regardless of
topic.

## 3. Data sample

`python -m scripts.phase17_m0_output_quality_audit` (read-only, zero LLM calls, zero mutations) ran
against the live production database on 2026-07-31, joining `ContentDraft` → `EditorialTask` →
`NewsEvent` → `NewsSource` for every real draft present.

- Raw population: **272** rows.
- **3 excluded** as synthetic/test fixtures discovered *during this task's own audit*, not assumed
  up front - `source.name` = "M6 Live Validation Source" (1) and
  "phase14-m6-live-validation-b249afe0-..." (2), one with a title literally prefixed
  `[M6 VALIDATION]`. Per this task's own "no synthetic production events" instruction, the script
  now excludes any row matching `"validation"`/`"backtest"` in the source name or
  `"[m6 validation]"`/`"[test"` in the event title (`scripts/phase17_m0_output_quality_audit.py`,
  data-hygiene exclusion block) - a minimal, safe, analysis-tooling-only fix, disclosed here per
  this task's own allowance for "minimal safe fixes in analytical tooling when data would otherwise
  be unreliable."
- **Final sample: 269 real, production-generated `ContentDraft` rows** (exceeds the 150-200
  preferred range - the *entire* real population was used rather than an arbitrary subsample, since
  269 rows is still trivially analyzable and avoids sampling bias).
- Date range: 2026-07-22 to 2026-07-31 (10 days of live production).
- Source type: **RSS 233 (86.6%), TELEGRAM 27 (10.0%), NEWS_API 9 (3.3%)**. Note on "NEWS_API":
  this codebase has no literal newsapi.org-style integration - `SourceType.NEWS_API` is the type
  label for the GitHub/Hacker News/arXiv API adapters (`services/adapter_keys.py`) - the report uses
  the term as the codebase itself defines it, not as the M0 task prompt's phrasing might imply.
  Confirmed by direct inspection rather than assumed.
- Category: AI 80, GADGETS 69, TECH 44, STARTUPS 32, UNKNOWN 30, HARDWARE 10, SOFTWARE 4.
- Exact sample IDs persisted to `scripts/_phase17_m0_output_quality_samples.json` (untracked, not
  committed - matches the existing, preserved `scripts/_phase15_m4_final_cutover_samples.json`
  precedent) for reproducibility.
- **Manual audit subsample: 32 drafts** (exceeds the 30 minimum), selected by a documented,
  deterministic stratified rule (fixed per-category quota, evenly spaced within each category by
  `created_at`, plus the global shortest/longest body outliers, plus a floor on NEWS_API/TELEGRAM
  representation) - IDs persisted to `scripts/_phase17_m0_manual_audit_ids.json`. The real
  Netflix/Walking Dead/Engadget/GADGETS draft (`fa60525c-fce6-44c1-b8ed-5e2de7e22973`) was pinned
  into the sample explicitly, as required. One stratified pick landed on the synthetic
  `2190d42d` M6-validation fixture (§3) and was swapped for the next real `AI`-category draft by
  `created_at` order, keeping the selection rule deterministic.

## 4. Output-length distribution

All numbers from the 269-row population (`body_word_count` = words in `ContentDraft.body`):

| Metric | Value |
|---|---|
| Min | 20 |
| P25 | 29 |
| Median | 33 |
| Mean | 33.4 |
| P75 | 37 |
| Max | 55 |

**Bucket histogram** (of the buckets this task specified): `<50 words`: **266 (98.9%)**;
`50-89`: **3 (1.1%)**; `90-139` / `140-219` / `220-319` / `320+`: **0 (0.0%) each**. No draft in the
entire real population has ever reached even the lower bound of the proposed "Simple news:
90-140 words" band.

Title word count: median 7, mean 7.5, min 4, max 14. Sentence count: median 2, mean 2.5 (range 2-4).
**Paragraph count: median 1, min 1, max 1 - literally 100% of the 269 real drafts are a single
paragraph** (confirmed by a direct newline-character search in the database, not just the word-count
heuristic: `SELECT count(*) FILTER (WHERE body LIKE '%'||chr(10)||'%')` = 0).

By source type (body word count): RSS median 33 (n=233), NEWS_API median 35 (n=9), TELEGRAM median
37 (n=27) - narrow variation, no source type breaks meaningfully out of the ~30-37 word band.

By category (body word count): AI median 30 (n=80, the shortest), TECH median 38.5 (n=44, the
longest), all others cluster 32-36.5. The spread across categories (30 to 38.5) is smaller than the
spread within any single category's P25-P75 range - **category has almost no effect on generated
length**; the pipeline is producing an essentially fixed-length output regardless of topic.

**Source-content length available at generation time** (chars, `NewsEvent.content`, HTML included):
NEWS_API mean 180, RSS mean 472, TELEGRAM mean 299. **Output/source word-count ratio**: median
**133%**, mean 157.5%, min 31%, max 1750% - for a large share of drafts (anything above 100%), the
*generated* text is verbally longer than the *entire* source material it was built from, which is
architecturally expected once one recalls Copywriting's context also includes Intelligence's
synthesized judgment, not just Research's facts - but it does mean length is not simply "compressing
the source," and the extreme high end (up to 1750%) corresponds to the near-empty degenerate sources
in §7 below, where almost any generated sentence outweighs the one-line source.

**Per this task's own instruction, no conclusion that "longer is always better" is drawn here.**
The finding is narrower and more specific: current length shows **no measurable adaptation to
story complexity or available material** (§4's category/source-type breakdowns) - a 55-word ceiling
applies equally to a bare one-line Hacker News title and a four-paragraph Reuters/Guardian teaser.

**Telegram-limit calibration** (real numbers, not the task's assumed bands taken on faith): median
real body is 248 characters (≈7.5 chars/word in this Cyrillic-heavy corpus). Extrapolating that
ratio to the four proposed word bands: 90 words ≈ 676 chars (fits both limits comfortably); **140
words ≈ 1052 chars - already over the 1024-unit photo-caption limit**; 220 words ≈ 1653 chars (66%
over the caption limit); 320 words ≈ 2405 chars (well under the 4096 text-only limit, far over the
caption limit). See §15 for the resulting adaptive-length recommendation.

## 5. Completeness audit

Two genuinely deterministic proxies were computed script-side across the full 269-row population
(regex/set-overlap, zero LLM calls - `scripts/phase17_m0_output_quality_audit.py`); the more
semantic dimensions (subject_explained, background_context, why_it_matters, what_next,
beginner_friendly, event_explained) were **not** attempted deterministically - a regex cannot
reliably judge those, and pretending otherwise would be exactly the kind of fabricated precision
this task explicitly warns against. Those come from the 32-draft manual audit (§18/§6) instead.

- **`concrete_details_count`** (numbers + currency/amount markers + years + percentages + distinct
  capitalized proper-noun-like tokens): median **2**, mean 3.5, P25 1, P75 5, range 0-25. A
  non-trivial fraction of drafts (P25=1) carry at most one concrete, checkable detail.
- **`headline_overlap_ratio`** / **`headline_rewrite_flag`** (body shares ≥60% of its unique
  vocabulary with the title AND is ≤45 words): **0.0% (0/269) flagged by the automated proxy** -
  see §6, this undercounts real headline-rewrite cases significantly; treated here as a known-noisy
  signal, not a finding on its own.
- **`unsupported_numeric_flag`** (a number in the body that does not appear, in any form, in the raw
  source content): **10.4% (28/269)**. Manually spot-checked 4 of the 28: **2 were real matches with
  no issue found on inspection, 2 were false positives** caused by locale number-format mismatches
  the proxy doesn't normalize (`5.2 billion` in English source vs. `5,2 млрд` in the Russian draft -
  comma-vs-period decimal separator, `billion`→`млрд` word substitution; `$342.89` vs. `$342,89`).
  **This flag should be read as a noisy upper bound (~10%), not a hallucination-rate finding** -
  fixing the normalization (or replacing it with an LLM-judge check) is future M4/M5 tooling work,
  not something to trust as-is.
- **`event_zero_summary_count`**: **269/269 (100%)**. `NewsEvent.summary` is set nowhere in
  `services/collector.py` (confirmed by grep across the entire codebase: zero assignments to
  `.summary` anywhere) - a dead column. Across the *entire* `news_events` table (11,943 rows, not
  just this sample), only 2 rows have a non-null `summary` (0.017%). `QualityCapability`'s own
  prompt context line, `Summary: {news_event.summary or '(none)'}`, is therefore "(none)" in
  effectively every real invocation - the rule that references it ("flag... missing summaries") is
  checking a field that structurally cannot be present.
- **`event_zero_content_count`**: 0/269 - `content` itself is never NULL by the time a
  `ContentDraft` exists, but (§7) it is frequently *degenerate* (headline-only), which a NULL check
  cannot detect.

## 6. Headline-rewrite rate

**Automated proxy: 0.0% (0/269).** **Manual audit (32 real drafts, §18): 6 of 32 (18.75%)** were
judged primarily a headline rewrite with no materially new information -
`8ef14299` (AI immigration tool), `dfca74b1` (Nvidia CEO on jobs), `cc5dcb84` (Tatarstan AI school
clubs), `b0d0f1f3` (Tile stalking risk), `d9c0b32c` (swatting lawsuit), `4f5e589e` (Zuckerberg
superintelligence strategy) - plus one more, `acc80872` (AI divinity doctorate), judged `WEAK`
primarily for source-thinness with a secondary rewrite character, for **7/32 (21.9%)** on a broader
reading. **The automated proxy is materially uncalibrated against real editorial judgment** - it
missed every one of these. Root cause, found by inspecting the actual overlap ratios: a genuine
rewrite can swap most of its *words* (paraphrase) while adding zero new *information* - word-overlap
alone cannot distinguish "the same fact in different words" from "the same fact plus something new."
This is flagged as a concrete tooling gap for M4/M5, not fixed here (out of M0's scope).

The common pattern behind every one of these 7: the underlying `NewsEvent.content` was itself
headline-only or near-headline-only (§7) - Research had nothing beyond the headline to extract, so
Copywriting, however good the prompt, structurally could not add anything either. This is a source-
material problem surfacing as an output-quality symptom, not a copywriting-prompt problem per se.

## 7. Beginner-friendliness findings

From the manual audit: beginner-friendliness correlates almost perfectly with whether a
`subject_explanation`-shaped field would even be answerable from available material. Two clear
patterns:

- **Domain jargon with zero definition**: `6612ee70` (arXiv MLIP paper) uses "SO(2)", "MLIP",
  "Clebsch-Gordan Tensor Products" throughout with no explanation - correctly compressed for a
  specialist reader, but opaque to a general "AI/Gadgets" channel reader. This is a genuine
  specialist-source case, not a generation defect - it shows the *ceiling* on how beginner-friendly
  a draft can be made without either dropping the story or adding real (risky) explanatory content.
- **No context on "why this name/thing matters"**: the Netflix/Walking Dead draft (§12) never
  explains what AMC+ is or why a streaming-rights split matters commercially - reasonable for an
  entertainment audience, meaningless to a gadgets/AI audience, which is really a relevance problem
  wearing a beginner-friendliness costume (§12's own point: these two problems look similar from the
  output alone and must not be conflated).

No draft in the 32-sample fabricated an explanation to compensate for missing background - the
pipeline's current behavior when it doesn't know something is consistently to say so (§8), not to
invent a bridge. This is a real strength worth preserving explicitly as a constraint on M1/M3 (§16).

## 8. Missing-specifics findings

Concrete positive counter-examples exist and are worth naming, because they show the pipeline
*can* produce specific, well-grounded output whenever the source material actually contains
specifics: `1cdfbf19` (Apple Q3 earnings - four distinct segment figures, all directly traceable to
source), `7352db1a` (UMC fab expansion - Singapore/Taiwan, correctly hedges on timeline/investment),
`715cf6ed` (Dili funding round - amount, lead investor, three named participants, all correct).

The missing-specifics failures are concentrated, almost without exception, in drafts whose source
`NewsEvent.content` was itself specifics-free (§7's jargon cases aside). This is the same underlying
mechanism as the headline-rewrite rate (§6): **when source material is thin, no downstream step can
add real specifics without either fabricating (which, per §7/§8, this pipeline currently does not
do) or explicitly flagging the gap (which it does, consistently and honestly).**

## 9. Unsupported-claim risks

See §5's `unsupported_numeric_flag` (10.4% raw, noisy - real false-positive rate ≈50% in the small
spot-check performed). No case of outright fabrication (a number/date/entity with **no** relationship
to the source, as opposed to a same-value-different-format number) was found in the 32-draft manual
read. This is a genuinely encouraging finding, but it is a 32-draft read, not a guarantee - it is
exactly the gap `services/fact_safety.py` (Phase 15 M5, currently `shadow` mode, deterministic
claim-extraction against the raw `NewsEvent` directly, not Research's paraphrase) already exists to
catch systematically, and §17 recommends how M1's Editorial Brief should interact with it rather
than duplicate or bypass it.

## 10. Source-content limitations

The single most consequential, previously-undocumented (for Phase 17's purposes) finding in this
report. Of the 32 manually audited drafts, **10 (31.25%)** had source `NewsEvent.content` that was
itself headline-only or content-free in every practical sense:
- Google News RSS entries where `<description>` is just the headline text repeated with the outlet
  name appended (`8ef14299`, `dfca74b1`, `cc5dcb84`, `7acf32e8`, `4f5e589e`, `acc80872` - 6 of the
  10, all `Google News: Artificial Intelligence` / `Google News RU: ИИ` feeds specifically -
  worth flagging: this is a single, identifiable source-configuration issue affecting a whole feed
  family, not a general RSS problem).
- Hacker News front-page items, whose `RawNewsItem.text` (`integrations/sources/hacker_news_source.py`
  not separately inspected in depth here, but confirmed via real content in this sample) is just the
  submission title (`b0d0f1f3`, `d9c0b32c`).
- Degenerate RSS teaser fields that are a caption, not a summary: PC Gamer's `"Is that good?"`
  (`073437a9`) and `"'Beyond 2029, it is hard to say...'"` (`ec2f2c76`, a real quote but the *only*
  content given), Lobsters' `"Comments"` (`f0a6ec38` - literally the word "Comments," the RSS feed's
  own generic comment-link label, not article content at all).

None of this is a bug in this codebase's collection logic - §2's answer to "full article vs.
excerpt" already establishes that **no adapter anywhere fetches full article text**; RSS/Atom
sources get exactly what the publisher's feed chooses to expose, by design (`entry.get("summary")`).
This is a hard, structural ceiling on output quality for roughly a third of real drafts that no
prompt change, length policy, or completeness gate can lift - it can only be worked around (shorter
target length + honest uncertainty framing for thin sources, §15/§16) or fixed at a different layer
(a full-article-fetch capability, explicitly **not** proposed here - out of M0's scope, and a much
larger fact-safety surface than this report is chartered to open).

## 11. Category and channel-fit findings

No channel profile, allowed/forbidden topic list, channel-fit score, or article-level topic
classifier exists anywhere in this codebase (`grep` across every `.py` file for
`channel_profile|allowed_topics|forbidden_topics|channel_fit|ChannelFit|topic_classif`: zero
matches). `NewsEvent.category` is the *only* topic-adjacent signal that exists, and §2/§10's finding
already established it is 100% source-inherited, never article-level.

From the 32-draft manual audit, categorization issues break into three distinct failure modes,
**8/32 (25%) affected overall**:
- **Wrong bucket, still on-topic** (5/32, 15.6%): `57f828e9` (a Warhammer 40K game trailer filed
  `GADGETS` - there is no `GAMING` bucket in `EventCategory` at all), `b0d0f1f3`/`d9c0b32c`
  (a stalking-risk story and a swatting-lawsuit story, both filed `STARTUPS` purely because they
  came via the Hacker News adapter, which has no topic signal of its own to assign a better one),
  `0e7e5f0c` (a workplace-AI-usage study filed `STARTUPS`, thematically closer to `AI`),
  `073437a9` (an AI-safety story filed `HARDWARE` because it came via PC Gamer).
- **Under-classified as `UNKNOWN` despite being clearly on-topic** (2/32, 6.3%): `eae93502`
  (Moonshot AI's real $3.5B funding round) and `491db283` (Kalanick's Atoms robotics $1.7B round) -
  both genuinely `AI`/`STARTUPS`-relevant, both landed in `UNKNOWN` because their Telegram source
  (`vc.ru`) isn't tag-mapped richly enough. This is the mirror-image failure of over-broad
  inheritance: real, on-topic content losing its category rather than off-topic content gaining one.
  Note `6612ee70` (an arXiv ML paper, also `UNKNOWN`) is **not** counted here - its source genuinely
  carries no bucket-matching tag, and `categorize_from_tags()`'s own documented design principle
  ("correct-but-unclassified is preferred over a wrong guess") is working as intended there.
- **Off-topic regardless of category** (1/32, 3.1%): the Netflix/Walking Dead case (§12) - no
  category reassignment fixes this; the story itself does not belong in the channel.

**Recommendation on the future boundary** (design only, per this task's explicit "do not implement
in M0" instruction): `NewsEvent → Article Topic Classification → Channel Fit → Editorial Decision →
Generation`. §18 elevates this ahead of the user's own implied ordering (see there for the
data-driven justification) precisely because it requires no new memory/history infrastructure - a
per-article classification is a stateless function of that article's own text, unlike
`difference_or_change` (§16), which genuinely cannot be answered without persistent state.

## 12. Netflix/Walking Dead incident analysis

- **Draft**: `fa60525c-fce6-44c1-b8ed-5e2de7e22973`.
- **Source**: Engadget (RSS), title *"Netflix pays $500 million to share 'The Walking Dead'
  streaming rights with AMC+"*, content *"Netflix has ponied up a half billion dollars to extend
  its streaming rights to The Walking Dead and the show's six spinoffs."*
- **Assigned category**: `GADGETS`.
- **Generated draft**: title *"Netflix заплатила $500 млн за права на «Ходячих мертвецов»"*, body
  *"Netflix продлила права на потоковую трансляцию «Ходячих мертвецов» и шести спин-оффов за
  $500 млн. Права распределяются совместно с AMC+, однако срок и условия соглашения пока не
  раскрыты."*
- **Writing-quality read (dimension A)**: genuinely **GOOD** on its own terms - every fact in the
  one-sentence source is used correctly ($500M, show name, 6 spinoffs, AMC+ partner), it adds the
  AMC+ detail from the title correctly, and it honestly flags what isn't known (terms/timeline).
  Nothing is fabricated. If this were the intended channel, this draft would pass.
- **Channel-fit read (dimension B)**: **REJECT**. This is a media/entertainment streaming-rights
  story. It has nothing to do with gadgets, AI, hardware, or software. It was categorized `GADGETS`
  for exactly one reason: Engadget's source-registry tags are `[gadgets, consumer-tech, ai]`
  (`config/newsroom_sources_v1/sources/media.yaml:104-107`), and `categorize_from_tags()` has no
  mechanism to look at the article itself.
- **Why this is the canonical regression case**: it is the cleanest possible demonstration that A
  and B are orthogonal. A perfect completeness/length/beginner-friendliness pass on this draft would
  never catch the actual problem, and a channel-fit rejection would never require touching the
  copywriting prompt at all. Any future metric that conflates the two (e.g., a single "quality
  score" that channel-fit feeds into) would either wrongly penalize this well-written draft's prose,
  or wrongly reward it for being well-written despite being wrong for the channel. Pinned as
  `regression_cases[0]` for all future M1-M6 tooling (§18's Definition of Done requires it stay
  pinned).

## 13. Root causes

Ranked by how many of the observed symptoms trace back to each, most consequential first:

1. **`CopywritingCapability` never sees `NewsEvent.content`, only `ResearchCapability`'s
   already-paraphrased `facts: list[str]`** (§2, items 1-2). Single bottleneck for all downstream
   richness; explains why no amount of copywriting-prompt tuning alone can fix missing specifics.
2. **A meaningful share of source content is itself headline-only or content-free at collection
   time** (§10, 31% of the manual sample) - no adapter fetches full article text (§2 item 6); a
   structural ceiling independent of everything downstream.
3. **No explicit length/structure target exists anywhere in the generation prompt** (§2 item 5) -
   output length is prompt-invariant regardless of story complexity or source richness (§4);
   directly explains the 20-55-word, 100%-single-paragraph uniformity.
4. **`NewsEvent.summary` is a dead field** (§5, §9) - 0% populated in production, silently
   contributing nothing to `QualityCapability`'s own stated checks.
5. **`QualityCapability`'s output schema has no structured completeness/relevance/beginner-
   friendliness dimension** (§2 item 8) - it cannot flag what it was never asked to check for, and
   even its `passed` result is not read by anything gating delivery.
6. **`NewsEvent.category` is 100% source-inherited, never article-level** (§2 items 9-10, §11) -
   both over-broad inheritance (Netflix) and under-classification (Moonshot AI, Atoms) trace to
   this single mechanism.
7. **No channel-fit/topic-relevance gate exists at any pipeline stage** (§11) - `NEWS_ANALYSIS`'s
   scoring measures newsworthiness, not topical fit; a well-written, newsworthy, off-channel item
   like the Netflix case has nothing anywhere to catch it.
8. **No storyline/cross-event memory exists** - `difference_or_change` (§16) is architecturally
   unanswerable today; the system has no persisted notion of a story's prior state.

## 14. Proposed EditorialBrief

**Design only - not implemented, not wired into any production Capability.** Proposed placement:
a new `schemas/editorial_brief.py` Pydantic schema plus a new `editorial_brief` workflow step
inserted into `CONTENT_GENERATION` between `intelligence` and `copywriting` - reusing the *exact*
existing integration pattern every other Capability already uses (`context.business.workflow_state.
step_results["research"]`/`["intelligence"]` in, `step_results["editorial_brief"]` out for
`CopywritingCapability` to read exactly as it already reads `["research"]`/`["intelligence"]` today
- no new coupling mechanism, no direct import of one Capability by another, per the same binding
rule already enforced across the whole `capabilities/` package).

| Field | Filled from | Deterministic or LLM? | Thin-source behavior |
|---|---|---|---|
| `headline_fact` | `research.facts[0]` / `news_event.title` | Deterministic (pick, not generate) | Falls back to title verbatim |
| `subject_explanation` | New - general/background knowledge, not the specific event | **LLM, explicitly separated** (§17) | Omitted entirely, never invented, when the subject isn't independently well-known |
| `event_details` | `research.facts` (filtered/deduped) | Deterministic | Empty list is valid and expected (§10's 31%) |
| `background_context` | New - same separated background channel as `subject_explanation` | LLM, same discipline as above | Omitted, not fabricated |
| `difference_or_change` | Would need prior-state memory | **Cannot be filled today** (§13 item 8) | Always "unknown" until M6+ storyline memory exists |
| `why_it_matters` | `intelligence.significance` + `intelligence.angle` | LLM (already exists, just needs surfacing/reshaping) | Falls back to a generic "under evaluation" marker rather than inventing stakes |
| `what_next` | `research.gaps` (partially) + `intelligence.recommendation` | Mixed | Often empty - honest, matches current behavior (§7/§8) |
| `uncertainties` | `research.gaps` directly | **Deterministic - already exists, just unused by Copywriting today** | This is the cheapest, highest-value field to wire up first |
| `recommended_format` | `event_content_word_count`, `concrete_details_count`, image-candidate presence | **Fully deterministic** (§15) | Thin source → forced short format regardless of category |
| `target_word_range` | Same inputs as `recommended_format` | **Fully deterministic** | Thin source → floor of the applicable band, never the ceiling |

**Hallucination-prevention rule for `subject_explanation`/`background_context`** (the two fields
that structurally require the LLM to draw on pretrained world knowledge *beyond* the source text,
unlike everything else in this table): they must never be validated against - or implied to come
from - `NewsEvent.content`, because by definition they don't. §17 details how Fact Safety should
treat them as a distinct claim category instead of force-matching them against source text (which
would always spuriously fail).

**Thin-source policy** (source word count below a data-derived threshold - §10's 31% is the
relevant population): `recommended_format`/`target_word_range` clamp to the shortest band
regardless of category or `intelligence.significance`; `subject_explanation`/`background_context`
may only state durable, non-time-sensitive background (e.g., "arXiv is a preprint repository"),
never anything about the specific event's undisclosed specifics.

## 15. Proposed adaptive-length policy

The user's four proposed bands, checked against §4's real calibration data rather than accepted on
faith:

| Band | Words | ≈ Chars (7.5 chars/word, this corpus) | Fits 1024-unit photo caption? | Fits 4096-unit text limit? |
|---|---|---|---|---|
| Simple | 90-140 | 676-1052 | Yes at 90, **borderline/no at 140** | Yes |
| Normal | 140-220 | 1052-1653 | **No** | Yes |
| Complex | 220-320 | 1653-2405 | **No** | Yes |
| Follow-up | 180-300 | 1350-2250 | **No** | Yes |

**Finding: three of the four proposed bands' upper (and often lower) bounds exceed Telegram's
1024-unit photo-caption limit.** Per Phase 16's own live data (this session's own earlier
validation), the large majority of drafts get an eligible image candidate and are sent as a photo
with a caption, not a text-only message - so this collision is not an edge case, it is close to the
common case. Recommendation: **the adaptive-length policy must branch on whether the draft will
carry a photo, not just on story complexity** - either (a) cap the effective target at the
caption-safe ceiling (~130-140 words) whenever an eligible image candidate exists, accepting that
"Complex" stories with an image get compressed further than a text-only complex story would, or
(b) make "has an eligible image" one of the deterministic inputs to `recommended_format` (§14) so a
genuinely complex story with a strong image candidate is still allowed to drop the image rather than
truncate the text - a real product decision, not one this discovery task should make unilaterally.
Either way, the existing `render_editorial_card()` shrink-to-fit/`CardTooLongError` machinery
(Phase 16 UX fix) remains the correct terminal safety net regardless of which policy is chosen -
this is a recommendation about the *target*, not a request to change that mechanism.

The bands themselves (90-140-220-320) are not rejected by this data - they are reasonable *relative
to each other* and to the 4096 text-only ceiling - but the "simple news" floor is still ~2.7× the
current real median (33 words), confirming (§4) that today's output is short across the board, not
just for simple stories.

## 16. Proposed completeness gate

Design only, for a future `M4` shadow rollout - reusing `QualityCapability`'s existing step
position (`capabilities/quality_capability.py`, already reads `step_results["copywriting"]`) rather
than adding a new pipeline stage, extending its output schema from the current unstructured
`{passed, issues}` to include the structured per-dimension booleans/counts this task enumerated
(`event_explained`, `subject_explained`, `concrete_details_count`, `background_context`,
`difference_or_change`, `why_it_matters`, `what_next`, `uncertainties`, `beginner_friendly`,
`headline_rewrite_only`, `unsupported_claim_risk`). Recommended validation approach before any
enforcement: run it in shadow against this same 269-draft real population, compare its per-dimension
verdicts against this report's own manual-audit table (§18) as a held-out calibration set - the
same discipline that caught the automated `headline_rewrite_flag` proxy's 0%-vs-19% miscalibration
in §6, which a real gate must not repeat.

## 17. Fact Safety interaction

`services/fact_safety.py` (Phase 15 M5, `fact_safety_mode` defaults to `shadow`, confirmed still
the live setting - §0) already does deterministic claim extraction/classification (`money`,
`percentage`, `date`, `entity`, `quote`) directly against the **raw** `NewsEvent` snapshot, not
Research's paraphrase - specifically built to catch what Research/Copywriting might invent or
amplify, per its own docstring's root-cause statement. This is architecturally the *correct* existing
seam for validating anything §14's Editorial Brief adds to Copywriting's output.

**The one required extension**: `subject_explanation`/`background_context` (§14) must be
classified as a **new, distinct claim category** - general/background knowledge, not tied to
today's specific `NewsEvent` - rather than run through the existing money/date/quote/entity
extractor as-is, which would force-match them against source text they were never supposed to come
from and generate constant false "unsupported" findings. `difference_or_change`/`why_it_matters`,
whenever LLM-synthesized rather than deterministic, should run through the *existing* extractor
unchanged - these are exactly the kind of claims-about-this-event Fact Safety already exists to
catch.

**Recommendation**: keep `fact_safety_mode=shadow` through M1-M3 (not touched by this task - §0
confirms it is untouched). Only revisit `enforce` alongside/after M4's Completeness Gate lands in
its own shadow phase, so both quality dimensions mature together before either can affect live
delivery - avoids a scenario where Fact Safety enforcement starts blocking drafts before the new
Editorial Brief fields it needs to understand even exist.

## 18. Recommended Phase 17 milestone plan

The user's own draft ordering (M1 Brief → M2 Adaptive Length → M3 Beginner-Friendly → M4
Completeness Gate → M5 Live Comparison → M6+ Storyline+Channel Memory) is **not accepted as-is**.
One adjustment, directly justified by this report's own data: **channel/topic relevance is pulled
out of the "M6+" bucket and given its own milestone at M2**, ahead of Adaptive Length, because
(a) §11/§12 show it is the single clearest, highest-confidence failure mode found (25% of the
manual sample, and the one case - Netflix - no amount of length/completeness work would ever catch),
and (b) unlike storyline memory, it requires **no new persistent state** - it's a stateless
per-article classification against a fixed channel profile, cheap to build and validate in shadow
independently of everything else. Bundling it with storyline memory (which genuinely does need new
infrastructure, §13 item 8) would delay the cheaper, higher-confidence fix for no architectural
reason.

- **M1 — Editorial Brief**: build §14's schema and deterministic fields
  (`uncertainties`/`event_details`/`recommended_format`/`target_word_range`) as a shadow-only step -
  computed, logged, not yet read by production Copywriting. Cheapest fields first
  (`uncertainties` = `research.gaps`, already exists, zero new cost).
- **M2 — Channel/Topic Relevance (elevated from the user's implicit M6+)**: article-level topic
  classification + channel-fit score, shadow-only, validated against §11/§12's real
  category-issue/off-topic findings including the pinned Netflix regression case.
- **M3 — Adaptive Length**: implement §15's policy, calibrated against real caption-limit math, with
  the has-image branch as an explicit, product-reviewed decision rather than an implementation
  afterthought.
- **M4 — Beginner-Friendly Copywriting**: depends on M1's Brief because `subject_explanation`'s
  hallucination-prevention discipline (§14/§17) must exist before beginner-friendly prose is allowed
  to lean on it.
- **M5 — Editorial Completeness Quality Gate, shadow**: §16's extended `QualityCapability` schema,
  calibrated against this report's own manual-audit table before any enforcement discussion.
- **M6 — Live Comparison**: old vs. new pipeline, human-reviewed real sample, same discipline as
  this M0 report's own manual audit.
- **M7+ — Storyline memory**: genuinely deferred - the only Brief field that structurally requires
  it (`difference_or_change`) can stay honestly "unknown" through M1-M6 without blocking any of that
  work, and building cross-event persistent state is the single most architecturally expensive item
  in this entire plan.

## 19. Risks and non-goals

- **Non-goal (confirmed out of scope for all of M0)**: no production prompt, capability, scoring
  weight, threshold, Fact Safety mode, LLM Gateway/model routing, Image Intelligence behavior,
  Telegram UX, or source-collector logic was changed by this task.
- **Risk - full-article fetching**: the obvious-looking fix for §10's 31% thin-source finding (fetch
  the real article page) is explicitly **not** proposed anywhere in this report - it would open a
  much larger Fact Safety surface (arbitrary web content) than this discovery task is chartered to
  evaluate, and deserves its own dedicated discovery, not a footnote here.
- **Risk - deterministic-proxy overconfidence**: §6/§9 both show this report's own automated
  heuristics under- or over-fire relative to real editorial judgment (0% vs. 19-22% headline-rewrite;
  10.4% raw vs. ~5% real on the unsupported-numeric spot check). Any future M1-M5 tooling that
  reuses these proxies must recalibrate against a manual sample first, not trust them at face value -
  this report deliberately did not smooth over that gap.
- **Risk - small-N categories**: `SOFTWARE` (n=4) and `HARDWARE` (n=10) in the 269-row population
  are too small for the by-category length breakdown (§4) to be more than indicative.
- **Risk - live database kept growing during this analysis**: `content_worker` remained running
  throughout M0 (per this checkpoint's own restart-safety guarantee); the exact 269/32-row samples
  are pinned by ID (§3) specifically so later re-runs of the same script against a larger population
  don't silently change what this report's own numbers refer to.

## 20. Definition of Done for M1

M1 ("Editorial Brief") is done when, and only when:

- `schemas/editorial_brief.py` exists, matching §14's field table exactly (deterministic fields
  implemented, LLM fields stubbed/flagged if not yet built).
- A new `editorial_brief` step is inserted into `CONTENT_GENERATION` between `intelligence` and
  `copywriting`, populating `step_results["editorial_brief"]` - **shadow only**: computed and
  persisted/logged, `CopywritingCapability`'s actual prompt/behavior unchanged, confirmed by the
  same "-k image"-style regression discipline Phase 16 already established (no change to delivered
  Telegram content).
- Deterministic fields (`uncertainties`, `event_details`, `recommended_format`,
  `target_word_range`) run with **zero new LLM calls**, verified against the real 269-draft (or by
  then larger) population via a read-only backtest script mirroring this M0 script's own convention.
- `subject_explanation`/`background_context`'s hallucination-prevention rule (§14/§17) is
  implemented and has dedicated tests proving it never validates against, or claims to come from,
  `NewsEvent.content`.
- Fact Safety's claim classifier (§17) recognizes the new background-knowledge category as distinct
  from event-specific claims - `fact_safety_mode` stays `shadow`, unchanged.
- Regression fixtures include the pinned Netflix/Walking Dead case (§12) and at least 10 of this
  report's own 32 manually audited drafts (§18) as a fixed, named comparison set for M2-M5 to reuse.
- Targeted tests, Ruff, and Mypy pass on every new/changed file; full regression suite shows zero
  new failures beyond the already-documented pre-existing baseline (same discipline as every prior
  Phase 15/16 report).
- A follow-up discovery-style report documents the shadow Brief's real output against the same real
  population before any M2+ milestone reads from it in production.

---

*Real numbers throughout this report come from `scripts/phase17_m0_output_quality_audit.py`
(269-row population) and a manual read of 32 real drafts' full text (§3), both reproducible from the
pinned IDs in `scripts/_phase17_m0_output_quality_samples.json` /
`scripts/_phase17_m0_manual_audit_ids.json` (both untracked, matching the existing
`scripts/_phase15_m4_final_cutover_samples.json` precedent).*
