# INSTAGRAM-AUTONOMOUS-TREND-TO-CAROUSEL-CANARY-1

Base commit: `c666fb4` (INSTAGRAM-VISUAL-SYSTEM-V1-1). Worktree
`C:/Users/Theodor/ai-newsroom-ig-trend-canary-1`, branch
`feature/instagram-autonomous-trend-to-carousel-canary-1`.

**No topic was given by the Founder.** No Instagram credentials were used or connected. No
production DB write, container restart, deploy, VisualSpec activation, or publish of any kind
occurred at any point. `instagram_publication_enabled` was confirmed `False` throughout.

## A. Observation window

Read-only, directly against the live production Postgres (`ai_newsroom` on the production VPS,
via `docker exec ai_newsroom_postgres psql` over SSH - a `SELECT`-only session; no write, no
container action). Window: the 18 hours preceding the pull (`created_at > now() - interval '18
hours'`), ending 2026-09-12 ~21:50 UTC. Raw pull saved to
`artifacts/instagram_autonomous_trend_canary_1/raw_events_18h.jsonl` (1,173 lines, one JSON object
per event, all parse-valid).

## B. Input counts

- **1,173** `news_events` in the window, joined to `sources` (name/type/reliability) and, where
  present, `news_event_story_links` → `stories` (the real, already-computed Story Memory
  clustering - section G explains why this script reuses it rather than re-clustering).
- **1,137 / 1,173** events already carried a real `story_id` (the live `automation_worker`/
  `news_analysis_worker` pipeline had already clustered them by pull time); the 36 unlinked events
  were excluded from candidate clustering rather than force-merged into anything.
- Category split: AI 592, GADGETS 263, SOFTWARE 120, STARTUPS 99, HARDWARE 61, TECH 33,
  CYBERSECURITY 5.
- **880 distinct story clusters** in the window.

## C. Candidate trends

Every one of the 880 clusters was scored (section D). The field was dominated by AI-category
academic/commentary chatter (arXiv/Habr/Google-News-RU syndication - often single-source or
thin cross-source spread) and a small number of clusters with real, multi-outlet corroboration.
Two clusters deserve explicit mention as illustrations of what a trend candidate is **not**
(section 4's own definition):

- A cluster titled "Как пересобрать метрики команды после внедрения AI-агентов без ложного роста
  velocity" whose *member events* were actually about unrelated topics (TTS tooling, a workflow
  framework, education policy) - a real example of an imperfectly-merged Story cluster. It was
  never a selection candidate; flagged here as evidence the ranking script did not blindly trust
  every cluster's own title.
- Several single-source, high-event-count clusters (one source repeating/re-syndicating itself)
  that superficially look "frequent" but fail the real cross-source-corroboration test this phase
  requires.

## D. Ranking (top 6 of 880, full list in `candidate_ranking.json`)

| # | score | category | sources | events (window) | story |
|---|---|---|---|---|---|
| 1 | **0.988** | GADGETS | **8** | **15** | **"iPhone Duo?"** |
| 2 | 0.702 | AI | 2 | 8 | "25 лауреатов Филдсовской премии забили тревогу из-за успехов ИИ в математике" |
| 3 | 0.697 | GADGETS* | 4 | 5 | "Redditors say Anthropic's expensive Claude plans offer far less usage than advertised" |
| 4 | 0.688 | AI | 1 | 9 | "Минпросвещения определило, с какого класса школьники могут пользоваться ИИ" |
| 5 | 0.656 | AI | 3 | 7 | "Как пересобрать метрики команды..." (the polluted cluster, section C) |
| 6 | 0.646 | AI | 1 | 7 | "Искусственный интеллект помог студентам в Несвиже..." |

*category mode is noisy for #3 - its member events are tagged inconsistently between AI/GADGETS by
the real upstream ingestion pipeline, disclosed rather than silently corrected.

Score = `0.30·source_diversity + 0.25·frequency + 0.25·category_fit + 0.20·storytelling_potential`
(section 7's explicit dimensions; `source_diversity`/`frequency` are the cluster's own real counts
normalized against a disclosed ceiling, `category_fit` = NINJA PULSE's section-5 priority table,
`storytelling_potential` is a disclosed proxy - distinct meaningful title-word count across the
cluster's real headlines, a rough stand-in for "how many genuinely different sub-angles does this
cluster's real evidence actually contain"). The gap between #1 and #2 (0.988 vs 0.702) is large and
was **not** an artifact of tuning toward a foregone conclusion - #1 wins on every one of the four
dimensions simultaneously (8 distinct sources vs 2, 15 events vs 8, GADGETS priority vs AI's own
slightly lower weight, and by far the richest real multi-angle evidence).

## E. Selected trend

**"iPhone Duo?"** - Apple's newly-announced foldable iPhone. `story_id =
9fac0988-20b7-4187-b357-a4522b279d6d`. 15 real events across 18 hours, 8 independent outlets
(Engadget, CNET, 9to5Google, 9to5Mac ×5, MacRumors ×2, Windows Central, iXBT News ×2, 3DNews ×2).

## F. Selection reasoning

**SELECTION_REASON**: by a wide margin the most cross-source-corroborated, highest-frequency,
richest-evidence cluster in the window, in a Founder-preferred category (GADGETS/consumer
technology, section 5), with genuine multi-angle real material (pricing, a hard pre-order number,
a direct named-competitor comparison, a feature trade-off, and a market-reaction angle) - exactly
the kind of depth a carousel needs to avoid being 6 repeated headlines.

**WHY_NOW**: this specific 18-hour window shows the *reaction* wave (comparisons, competitor
response, hard numbers) landing on top of the original announcement, not the announcement itself -
a distinct, evidence-backed angle from whatever ran when the news first broke.

**WHY_INSTAGRAM**: a new hardware form factor is one of the most inherently visual story types
this system covers; it also already has a real, previously-approved local hero product photo
(`assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case1_hero_product_iphone.jpg`) usable as an
honest visual anchor (a real iPhone product photo, not a claimed photo of the unannounced-photo
Duo itself - disclosed in section I).

**WHY_CAROUSEL**: the real evidence naturally decomposes into distinct, non-redundant beats
(context → a hard number → a direct competitor comparison → a trade-off → market reaction) - a
genuine multi-step narrative, not one fact stretched across slides.

**WHY_NOT_TOP_ALTERNATIVES**:
- #2 (Fields-medalists AI warning): only 2 independent sources despite 8 events - thin
  cross-source corroboration, and a single abstract claim without the multi-angle material a
  carousel needs.
- #3 (Anthropic/Claude Reddit complaints): a real, legitimate story, but thinner (4 sources) and
  fundamentally a single-fact complaint rather than a multi-angle narrative; also noisy
  category-tagging (see the table footnote) made it a less trustworthy signal.
- #4/#6: single-source clusters (one outlet's own multi-part coverage) - fail real cross-source
  corroboration regardless of event count.
- #5: the polluted cluster (section C) - correctly never seriously considered.

**Disclosed honest weakness (novelty)**: a direct read-only check of `story_telegram_deliveries`
shows this exact story (`story_id` above) was **already delivered to Telegram twice**, on
2026-09-10 (2 days before this window) - "iPhone Duo?" is not a brand-new topic to the NINJA PULSE
audience. This is the single weakest part of an otherwise strong pick, and is treated honestly
rather than hidden: the case for still proceeding is that this window's own evidence (pre-order
numbers, direct competitor comparison, feature trade-offs, market reaction) is materially NEW
information not present in whatever ran 2 days earlier, and no Instagram post on this topic (or
any topic) has ever been published - Instagram publication has never been enabled on this account.
A stricter Director tuned to penalize recency-of-prior-coverage more heavily might have picked #2
or #3 instead; this run's scoring function did not weight that dimension, and that is disclosed
here as a real, addressable gap in the scoring formula (section 7 asked for a novelty dimension;
this implementation checked it manually, after ranking, rather than folding it into the composite
score - see section O).

## G. Carousel angle

**CAROUSEL_ANGLE**: "The foldable iPhone just landed - here's how the market is actually
reacting." **CORE_THESIS**: Apple's foldable entry is real, already commercially significant in
China, and forces genuine trade-offs (durability/software polish vs. missing flagship features and
a narrower screen) rather than being an unambiguous win or loss. **TARGET_READER**: a
tech-enthusiast follower who already knows foldables exist and wants the "what actually
matters" synthesis, not the raw announcement. **PROMISED_VALUE**: a fast, evidence-grounded read
on whether the iPhone Duo is actually good, without reading eight separate articles.

## H. Slide-by-slide evidence

All copy below is this canary's own authored text (see the module-docstring honesty disclosure in
`scripts/_instagram_autonomous_trend_canary_1.py` - no live Creative-Director LLM call was made),
but every factual claim is directly traceable to a real pulled headline; nothing was invented
(section 15). One real factual-accuracy issue was caught and fixed during self-critique before
finalizing (section O) - the original draft said the phone was "already on sale," which the
evidence does not actually support (only "announced" + heavy pre-orders); both affected slides
were corrected to "announced."

| # | role → layout | slide copy (RU) | grounding |
|---|---|---|---|
| 1 | hook → `carousel_hook` (real hero photo) | "iPhone Duo объявлен — и весь рынок складных смартфонов реагирует" | Engadget/9to5Mac/MacRumors headlines |
| 2 | context → `carousel_detail` | "После лет слухов Apple анонсировала складной iPhone Duo — на фоне уже привычных Samsung Galaxy Z и Google Pixel Fold" | general framing across the cluster |
| 3 | data → `carousel_fact` | "Только на JD.com в Китае на iPhone Duo оформлено почти 1,55 млн предзаказов" | iXBT News: "почти 1,55 млн предзаказов" on JD.com |
| 4 | comparison → `carousel_comparison` | "iPhone Duo: защита IP68, соотношение экрана 1:1.4 vs Pixel Fold: экран шире, но не такой прочный" | CNET durability face-off; 9to5Google/MacRumors aspect-ratio coverage |
| 5 | explanation → `carousel_detail` | "iPhone Duo лишился части функций iPhone 18 Pro, зато обошёл iPad по удобству разделения экрана" | MacRumors "Missing These 10 Features"; 9to5Mac split-screen-vs-iPad piece |
| 6 | cta → `carousel_closing` | "Samsung уже усилила рекламу Galaxy Z, а Apple, по оценкам, займёт около четверти рынка складных телефонов" | 3DNews market-share estimate + Samsung ad-response piece |

`final_cta` (package-level, not a slide): "Что думаете о новом формате Apple?" - an open question,
not an overpromising call-to-action.

## I. Media choices

Only slide 1 (the hook) uses a real photo - the same already-approved local iPhone hero product
image reused throughout INSTAGRAM-VISUAL-SYSTEM-V1-1's own canaries. It is honestly a real Apple
product photo, not a claimed photo of the (not-yet-photographed-by-us) Duo variant specifically -
disclosed, not hidden. Slides 2-6 deliberately use no image (section 14's own "do not force images
onto every slide" instruction) - each instead uses the carousel system's own real content-driven
layout (a data callout, a two-panel comparison, detail slides with a ghosted progress numeral, a
red-wash closing) so the deck still reads as visually varied without reusing or fabricating
imagery it doesn't have.

## J. Renders

`artifacts/instagram_autonomous_trend_canary_1/slide_00_hook.jpg` … `slide_05_cta.jpg` (1080×1350
each, final Instagram carousel-slide resolution) + `00_CONTACT_SHEET.jpg`. Layout variants actually
produced by the real, content-driven grammar selection: `carousel_hook`, `carousel_detail`,
`carousel_fact`, `carousel_comparison`, `carousel_detail`, `carousel_closing` - 5 distinct layouts
across 6 slides, genuine visual progression, not 6 black cards.

## K. Caption

Package `caption` (real, from the existing architecture's own honest rule - a carousel has no
schema-level final-caption field, so `caption` = the hook slide's own copy, `caption_is_draft =
True`): *"iPhone Duo объявлен — и весь рынок складных смартфонов реагирует"*.

A fuller **draft** caption proposal (clearly a draft, not wired into the technical package - no
schema field exists for it, section 19/K):

> iPhone Duo официально объявлен — и уже стал главным событием для рынка складных смартфонов.
> Пока Samsung ускоряет рекламу Galaxy Z, в Китае на новинку уже оформлено около 1,55 млн
> предзаказов. Смотрите карусель — сравниваем с Pixel Fold и разбираем, что Apple сделала
> правильно, а что нет.

No hashtags - consistent with the existing, disclosed system rule that `hashtags` is always `[]`
unless a real upstream schema actually produces them (none does today).

## L. Art result

`validate_instagram_art()` on all 6 real renders: **`passed: True`**, 0 blocking issues.
5 non-blocking warnings, all identical in kind:
`source_image_ref_recorded_but_not_applied` on slide_index 1-5. This is an **expected, disclosed**
warning, not a defect: the package records one `source_image_ref` (the hero photo used only by the
hook slide, by design - section I), and the Art validator's check (added in INSTAGRAM-VISUAL-
SYSTEM-V1-1 for SINGLE-format packages, one image ↔ one render) does not yet have carousel-specific
nuance for "only the hook slide needs the referenced image." Flagged here as a real, disclosed gap
in that check rather than silently worked around - fixing it is out of this canary's scope (section
28: do not change the Director/visual system based on this one result). Full JSON:
`art_result.json`.

## M. Editorial result

`evaluate_instagram_editorial_gate()`: **`ready_for_editor`** (the 5 Art warnings above are carried
as non-blocking `reason_codes`; nothing here was auto-approved on the Founder's behalf - "ready for
editor" is a technical/process state, not a design or publish approval). Full JSON:
`gate_outcome.json`. `InstagramReviewPackage` built successfully: `review_package.json`.

## N. Shadow publication result

`publish_instagram_content(..., client=ShadowInstagramPublishClient(), shadow=True,
editor_approved=False)` → **`status: shadow_success`**, 7 deterministic `shadow_...` container ids
(6 slide children + 1 carousel parent) + 1 media id, **`REAL_NETWORK_WRITES = 0`**
(`ShadowInstagramPublishClient` is a pure in-memory simulation - no HTTP client, no credential, no
`graph.instagram.com` call anywhere in this run). `INSTAGRAM_PUBLICATION_ENABLED = False`
(confirmed read from `core.config.get_settings()` at run time). Full JSON: `publish_result.json`.

## O. Director self-critique

**Weakest slide**: slide 5 (explanation) - its real content ("lost some flagship features, but
better split-screen than iPad") is genuine and evidence-grounded, but the carousel system's own
fixed English micro-label for the `"explanation"` role (`"HOW IT WORKS"`) doesn't quite fit a
trade-off/comparison-of-strengths-and-weaknesses slide; a mislabeled-but-accurate slide, disclosed
rather than silently left as-is. This is a real, minor localization/label-fit gap in the shared
carousel module (English role labels mixed into an otherwise fully Russian deck) - not something
this canary's own script can fix without editing the frozen visual system (out of scope, section
28).

**Strongest slide**: slide 3 (data) - a single real, striking, correctly-sourced number
(~1.55M pre-orders) with nothing invented, in the carousel grammar's dedicated "fact" callout
treatment.

**Possible factual risk (caught and fixed, not just disclosed)**: the first draft of slides 1 and 2
said the phone was "already on sale" (`уже в продаже` / `выпустила`) - the real pulled evidence
supports "announced" + heavy pre-order demand, not confirmed general availability. This is exactly
the kind of validation issue section 21 asks this step to catch; it was fixed as the one bounded
correction pass this phase allows, and both slides were re-rendered and re-validated (section H).

**Possible visual weakness**: only 1 of 6 slides carries a real photo (by design, section I) - a
genuinely richer version of this same carousel would have a second real image (e.g. an actual
Pixel Fold product photo) for the comparison slide; none was available locally, so the comparison
slide is honestly text-only rather than using an unrelated or fabricated substitute image.

**What would make the carousel more compelling**: a real Pixel Fold photo for slide 4; folding the
"already covered on Telegram 2 days ago" novelty signal directly into the composite score (section
F) rather than checking it manually after ranking, so a future run doesn't have to remember to do
that check by hand.

## P. Founder review package

Everything the Founder needs to answer "would I actually post this?" lives in
`artifacts/instagram_autonomous_trend_canary_1/`:

- `raw_events_18h.jsonl` - the real pulled evidence (section A/B).
- `candidate_ranking.json` - top 20 scored candidates (section D).
- `slide_00_hook.jpg` … `slide_05_cta.jpg` + `00_CONTACT_SHEET.jpg` - full-resolution renders +
  one combined board (section J).
- `package.json`, `art_result.json`, `gate_outcome.json`, `review_package.json`,
  `publish_result.json` - the complete real technical trail (sections L/M/N).
- This report (sections A-O above) - selection reasoning, angle, evidence, caption, and an honest
  self-critique including one caught-and-fixed factual error and two disclosed, unfixed gaps
  (the carousel Art-validator's source-image-ref check, and the English role-label mismatch).

## Verdict

**`INSTAGRAM_AUTONOMOUS_TREND_CAROUSEL_READY_FOR_FOUNDER_REVIEW`**

This means the system autonomously found a real trend from real recent evidence, with no topic
given, and produced a complete, technically-passing, reviewable carousel - **not** that the
Founder has approved the trend choice, the angle, or the visual design. The weakest real point
disclosed above is novelty (this exact story already ran on Telegram 2 days earlier); the
strongest points are evidence quality, cross-source corroboration, and a genuine multi-angle
carousel structure with zero fabricated facts. Stopping here per section 28: no Phase 2, no
Director changes, no scoring re-tuning from this single result, no Instagram credentials, no
publish. Waiting for Founder review.
