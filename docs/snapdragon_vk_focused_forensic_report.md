# SNAPDRAGON C + VK STORY MEMORY FOCUSED FORENSIC REPORT

Forensic-only. No code changed. Both cases reconstructed entirely from real, persisted rows produced during the post-acceptance targeted live validation run (`article_acquisition_mode=enforce`, committed HEAD `c308d45f6d55dc895eabe24b1901e1f99f855bbe` plus the working tree's post-acceptance follow-up fixes).

## 1. Executive summary

| | Severity | First divergence point | One-sentence root cause |
|---|---|---|---|
| **Case 1 — Snapdragon C** | Moderate (a real, informative, freely-available spec set was omitted; not fabricated, not contradicted — an omission, not a hallucination) | `RESEARCH` (the CONTENT_GENERATION-stage Research step) | The successfully-acquired, spec-rich article text never reached a real Research LLM call — the pre-existing NEWS_ANALYSIS→CONTENT_GENERATION result-reuse optimization silently substituted a stale, pre-acquisition Research result instead, and Copywriting/Quality only ever saw that stale result. |
| **Case 2 — VK earnings** | Moderate (a real duplicate publication of already-known information, not fabricated content) | `ENTITY EXTRACTION` (the Story Memory matching input) | A leading common noun ("Отчёт" — "Report") got captured as part of the entity string instead of being stripped, zeroing entity overlap against the identical prior story and pulling a would-be 0.97 confident-match score down to 0.37 (`uncertain_match`), which — by itself, precisely and quantifiably — was enough to keep every already-built duplicate-suppression mechanism from ever being consulted. |

Both cases were independently reconstructed from real `NewsEvent`/`EditorialTask`/`ContentDraft`/`AIExecution`/`NewsEventArticleAcquisition`/`NewsEventStoryLink`/`Story`/`StoryTelegramDelivery` rows — no synthetic reproduction was used anywhere in this report.

## 2. Snapdragon C — real identifiers and timeline

- **NewsEvent**: `e6e51045-ead1-4234-bb5a-3908577ffc68` — "Быстрее и лучше Intel N250: Qualcomm раскрыла детали процессоров Snapdragon C для недорогих ноутбуков" — source **3DNews** (RSS), category `GADGETS`, `published_at` 2026-08-13 07:26:00 UTC, `collected_at` 09:06:35.
- **NEWS_ANALYSIS EditorialTask**: `924da4df-9c65-4160-9991-ba05cd3c4da3` — Research step ran **09:22:28–09:22:30 UTC**.
- **NewsEventArticleAcquisition**: `canonical_url = https://3dnews.ru/1146746/...`, `acquisition_status = FULL_TEXT`, `raw_extracted_text` = 8,867 chars, `cleaned_text` column = **NULL** (still never populated by any write path — matches the already-disclosed, already-confirmed gap from the post-acceptance checkpoint), acquisition row `created_at` = **09:45:06.125501 UTC**.
- **CONTENT_GENERATION EditorialTask**: `3565969f-8f5e-48ae-aee9-d11d99052038` — Research step: **09:45:06.898–09:45:06.998 UTC** (100ms); Copywriting: 09:45:07.155–09:45:16.494; Quality: 09:45:16.506–09:45:19.085.
- **ContentDraft**: `4973a912-b63f-48f2-ae5c-93f718fd5964`, created 09:45:19.127944.
- **Telegram delivery**: message `200`, `delivery_type=root`, sent 09:45:19.539450.
- **AIExecution rows for this event**: RESEARCH $0.001279 (09:22:28, the only Research charge), INTELLIGENCE $0.001708, ENGAGEMENT $0.001886, SCORING $0.000598 (all NEWS_ANALYSIS-stage), COPYWRITING $0.007774, QUALITY $0.001287 (CONTENT_GENERATION-stage) — **no second RESEARCH charge exists**, confirming the CONTENT_GENERATION-stage "research" step never made a real LLM call.

**Critical timing fact**: the NEWS_ANALYSIS-stage Research call (09:22:28) ran **22 minutes and 38 seconds before** the article was ever acquired (09:45:06). At the moment Research first ran, the only input available was the bare RSS excerpt (`news_event.content`, 227 characters — "Qualcomm раскрыла некоторые подробности... он ориентирован на ноутбуки стоимостью около $300... Источник изображений: Qualcomm").

## 3. Snapdragon C — source fact inventory

The real specifications are present in `raw_extracted_text` as **ordinary prose paragraphs** (not a table, list, definition list, card, or structured/embedded data) — plain narrative sentences from the 3DNews article body:

- 8 Qualcomm Kryo cores; single-core clock up to 3 GHz; multi-core up to 2 GHz (with the article's own fine-print caveat: 3 active cores → up to 2.6 GHz, 4 active cores → up to 2 GHz; simultaneous 8-core operation not confirmed).
- Total cache: 2 MB.
- Adreno GPU at 900 MHz.
- Qualcomm Hexagon NPU (performance unspecified by the source itself).
- A detailed benchmark comparison against an Acer TravelMate (Intel N250, same 8GB RAM): Cinebench +67% multi-thread / +50% single-thread on battery, up to 2.1× better energy efficiency; Geekbench +44% single-core / +24% multi-core; Speedometer 3.1 +39%; Netflix-on-battery efficiency +106%; web browsing +68%; Teams video call +74%.
- Announced/promised OEM partners: HP, Acer, Asus, Lenovo; the only concretely announced laptop so far: Acer **Aspire Go 15** (8GB RAM, 512GB storage).
- The $300 figure is explicitly the **target laptop price**, not the chip's own price ("он ориентирован на ноутбуки стоимостью около $300" — "it [Snapdragon C] is aimed at laptops costing around $300").

## 4. Snapdragon C — fact propagation matrix

| Fact | Source (raw_extracted_text) | Cleaned evidence (on-the-fly, per the post-acceptance fix) | Research output (actual, as used) | Copywriting input | Final post |
|---|---|---|---|---|---|
| 8 Kryo cores, up to 3 GHz | Present | Present (prose kept by conservative cleaning rules — none of the removal rules target ordinary spec paragraphs) | **Absent** | **Absent** | Absent — ending instead states specs are undisclosed |
| 2 MB cache, Adreno 900 MHz, Hexagon NPU | Present | Present | **Absent** | **Absent** | Absent |
| Full benchmark comparison vs. N250 | Present | Present | **Absent** | **Absent** | Vaguely contradicted: body says "no confirmed test results yet" |
| OEM partners + Aspire Go 15 | Present | Present | **Absent** | **Absent** | Absent — ending says laptop models undisclosed |
| $300 = target laptop price (not chip price) | Present, correctly disambiguated | Present | Present (bare RSS excerpt already contained this one line) | Present | **Correct** — headline/body both grammatically bind "$300" to "ноутбуков" (laptops), never to the chip |

The evidence-package fix from the post-acceptance checkpoint is independently confirmed working here too: a direct re-run of `build_evidence_package()` against this exact event (same method used in the targeted validation report) returns `extraction_method = full_article_acquisition` with the full spec-bearing text. **The fix's own code path is not the problem — it is simply never reached for this event's Research step**, per §5.

## 5. Snapdragon C — first divergence/root cause

**The `$300` grounding check passes.** The claim is a laptop-price target, not a chip price, in both the source and the final post — no misattribution occurred.

**First divergence point: `RESEARCH`.** Precisely: the CONTENT_GENERATION-stage "research" workflow step never executed a real capability call. `capabilities/executor.py::_try_reuse()` (`services/analysis_reuse.py`, "API cost optimization") found the event's already-`COMPLETED` NEWS_ANALYSIS task's own `research` result and returned it directly (`reused_output = await self._try_reuse(...)`; when non-`None`, `structured_output = reused_output` and the freshly-assembled `context` — which *did* correctly carry the new `article_evidence_text` from `build_evidence_package()`, per the enforce-mode gate `if step.capability == "research" and settings.article_acquisition_mode == "enforce":` — is discarded unused, because `capability.execute(context)` is only ever called in the `else` branch). The reused result is bit-for-bit identical between the NEWS_ANALYSIS and CONTENT_GENERATION step-results in the real workflow JSON, and its own timing (100ms) is consistent with a DB read, not an LLM round-trip (contrast with the 2-3 second durations of every real LLM call in this same workflow).

`services/analysis_reuse.py`'s own module docstring states the premise this reuse is built on: *"that prior task's research/intelligence step results are the exact same evidence, for the exact same NewsEvent, that a fresh call would (re)produce."* That premise is true when article acquisition state hasn't changed between the two calls — and false here, since acquisition succeeded in the 23-minute gap between them. `_try_reuse()` has no awareness of `article_acquisition_mode` or of whether a fresh acquisition became available since the NEWS_ANALYSIS-stage call ran.

Given the reused Research result, Copywriting was never grounding-inconsistent with what it actually saw: its ending ("Конкретные характеристики... не раскрыты") is a near-verbatim restatement of Research's own `gaps` field ("В тексте не указаны технические характеристики Snapdragon C..."), which was itself an honest description of the bare 227-character RSS excerpt Research was actually given at 09:22:28. **Copywriting is not the divergence point — it faithfully reflects a stale, pre-acquisition Research result it had no way to know was stale.** Quality's own fact-safety check (6/6 claims supported) is consistent with this: every claim actually made in the draft *was* supported by the (stale) evidence it was checked against; the check has no mechanism to notice an *omission* relative to text it was never shown.

**Classification: `OTHER`** — not a defect in Acquisition, Extraction, Cleaning, Evidence Packaging, the Research capability's own reasoning, Copywriting, or Quality individually. The defect is in the **capability-result reuse orchestration** (`services/analysis_reuse.py` + `capabilities/executor.py::_try_reuse()`), which sits structurally between a correctly-functioning Evidence Packaging layer and a correctly-reasoning-given-its-input Research capability, and silently defeats the newly-activated `enforce` mode for exactly the "research" step it's supposed to benefit from.

## 6. VK — real identifiers and timeline

| | Event 1 (first post) | Event 2 (second post) |
|---|---|---|
| NewsEvent ID | `9e6c9afb-27d5-4a11-be14-37f987e7bad0` | `4beec79f-e228-4536-824e-849d0b8d1496` |
| Source | vc.ru Telegram channel (`@vcnews`), type `TELEGRAM` | "vc.ru AI" RSS feed, type `RSS` |
| URL | `https://t.me/vcnews/62926` | `https://vc.ru/money/3076319-...?from=rss` (the same underlying vc.ru article event 1's own Telegram post links to) |
| Category | `UNKNOWN` | `STARTUPS` |
| `published_at` | 2026-08-13 08:45:34 UTC | 2026-08-13 08:30:13 UTC (the RSS article predates the Telegram summary of it) |
| `collected_at` | 09:03:59 | 09:06:26 |
| Story Memory outcome | `new_story` (first event for this real-world story), score 0.746 | **`uncertain_match`**, score **0.37**, against event 1's own Story |
| Story created | `bf926578-0d4e-40e5-bb2c-bdd55fdf3d08`, `entities=["vk"]` | `454ef7c0-85e9-4579-9590-c9decf734e9d` (its own, separate story — `uncertain_match` never merges), `entities=["отчёт vk"]` |
| ContentDraft | `5e22971d-58b1-4ab9-82d3-872c8c691ddd` | `b0b8922f-7ec4-44e1-9b7a-06c92b07ca3e` |
| Telegram delivery | message `193`, root, 09:16:44 | message `197` (album), root, 09:44:57 |
| Article acquisition | none (no `NewsEventArticleAcquisition` row — this event's URL is a Telegram permalink, not an article) | `FULL_TEXT`, 2,094 raw chars, acquired 09:44:xx |

## 7. VK — factual overlap/delta comparison

**Facts in Post/Source 1** (the Telegram-channel post, which is also `event_1.content` verbatim): quarterly revenue +17% to 43.5bn RUB; net profit 328m RUB; net debt at H1-2026 end down 27% to 60.2bn RUB.

**Facts in Post/Source 2** (the real, acquired vc.ru article — far richer than what actually reached the second post, see §9): everything in Source 1, **plus** EBITDA +41% YoY to 7.6bn RUB; H1 revenue 81bn RUB (+12% YoY); per-segment breakdown (Social Platforms & Media 57.3bn RUB, +13%; EdTech 4.9bn RUB, +26%; VK Tech 9bn RUB, +35%; Ecosystem/other 13.7bn RUB, +7%); operating cash flow up to 15.4bn RUB (from negative the prior year); FY2024 net loss 95bn RUB and a related planned secondary share issuance; FY2025 loss 25.4bn RUB (3.7× smaller than FY2024).

**Intersection** (facts already known from Post 1, before Post 2 was published): quarterly revenue 43.5bn/+17%, net profit 328m, **net debt 60.2bn/-27%**.

**Genuine delta available in the real source but never used**: EBITDA, H1 revenue, all four segment breakdowns, cash flow, historical losses, the share-issuance context — a substantial, genuinely new set of facts.

**What the second post actually published**: title = "Чистый долг VK за первое полугодие снизился на 27%"; body = "...чистый долг VK составил 60,2 млрд рублей — на 27% меньше... задолженности остаётся значительным." **Every concrete fact in the second post's actual headline and body is already present, verbatim, in the first post — the net debt figure and percentage.** Being strict: **the second source contains a large, genuine material delta relative to the first post, but the second *publication* itself contains no delta at all** — it republishes exactly the one fact-set the two events already had in common.

## 8. VK — Story Memory decision reconstruction

Reconstructed by calling the real, unmodified `services/story_memory.py::score_candidate()` directly against the two real, persisted titles/signatures/Story rows (not inferred from the Telegram UI):

```
extract_story_signature(event_1.title, UNKNOWN)   → entities=['vk']
extract_story_signature(event_2.title, STARTUPS)  → entities=['отчёт vk']

score_candidate(event_2.title, sig_2, STARTUPS, event_1.title, story_1)
  → combined=0.37, entity_overlap=0.0, title_overlap=0.8
```

This reproduces the real persisted `match_score = 0.37` exactly. Decomposed against the real weights (`_ENTITY_WEIGHT=0.6`, `_TITLE_WEIGHT=0.4`, `_CATEGORY_BONUS=0.05`, `_TOPIC_BONUS=0.05`, `_LOW_THRESHOLD=0.35`, `_HIGH_THRESHOLD=0.65`):

`0.6 × 0.0 (entity_overlap) + 0.4 × 0.8 (title_overlap) + 0.05 (topic_bucket both "financial") + 0.0 (category UNKNOWN≠STARTUPS) = 0.37`

- **Title similarity is very high** (0.8 symmetric Dice overlap — both titles share nearly every substantive token: "квартал", "выручка", "млрд", "рублей", "чистая", "прибыль", "328", "млн").
- **Entity overlap is exactly zero** — `{"vk"}` vs. `{"отчёт vk"}` share no common set element under the Jaccard measure `_extract_entities()` produces.
- No Story Memory V2 delta/confidence/suppression diagnostics exist for this pair — `services/story_duplicate_guard.py::check_duplicate_story_delivery()` only ever invokes the V2 layer when the *V1* match_type is already in `{SEMANTIC_DUPLICATE, SUPPORTING_SOURCE}`; `uncertain_match` never reaches that check at all, so no V2 diagnostic of any kind was computed for this pair, not merely logged and ignored.

**Counterfactual, computed with the same real function**: had entity extraction correctly produced `{"vk"}` for event 2 (matching event 1 exactly, `entity_overlap=1.0`), the combined score would have been `0.6 + 0.32 + 0.05 = 0.97` — well clear of the `0.65` confident-match threshold. **The single entity-extraction defect accounts for the entire 0.60-point gap between a would-be confident match and the actual uncertain one.**

**Why it didn't collapse — precisely**: `_ENTITY_RUN_RE` (`[A-ZА-ЯЁ][\w\-.]*(?:\s+[A-ZА-ЯЁ][\w\-.]*)*`) greedily captures runs of consecutive capitalized words. Event 2's title opens "**Отчёт VK** за квартал..." — "Отчёт" ("Report") is capitalized only because it is sentence-initial in Russian, not because it is part of a proper name, but it sits immediately before "VK" and gets captured as one combined run. `_strip_leading_determiner()` (the exact fix built for the earlier, already-resolved CD Projekt/"The Witcher" case) would strip a leading word from that run — but only if the word is in `_GENERIC_DETERMINER_ENTITIES = {"this", "that", "these", "those", "it", "if", "a", "an", "the", "это", "этот", "эта", "эти"}`, a deliberately narrow, explicitly "never hardcoded from any calibration case" set of grammatical determiners/demonstratives. "Отчёт" is a genuine common noun ("report"), not a determiner — it was never in scope for that fix, and the current mechanism has no way to distinguish "a real second entity word" from "an ordinary noun that happens to open the sentence."

**This is a real, precise, quantifiable Story Matching precision failure (Failure Mode A)**, not a case of the architecture correctly, intentionally allowing a separate story and then failing to suppress it afterward (Failure Mode B) — `uncertain_match` is not `RELATED_STORY`; it is Story Memory's own "not confident enough" bucket, and it landed there because of a specific, reproducible entity-extraction defect, not because of a deliberate policy choice about story granularity.

## 9. VK — downstream novelty/suppression reconstruction

Two independent things happened, both making the outcome worse:

1. **The same reuse-vs-enforce defect from Case 1 recurs here.** Event 2's CONTENT_GENERATION-stage "research" step (09:44:48.282–.330, 48ms) is, exactly as in Case 1, a reused NEWS_ANALYSIS-stage result (09:18:18, 26 minutes before the article was acquired) — `facts` contains only the two net-debt-related sentences, and its own `gaps` field explicitly (and, at that moment, correctly) states "Заголовок также заявляет выручку... но эти показатели не раскрыты в основном тексте" (true only of the bare RSS teaser it was actually given). Copywriting for event 2 therefore never had access to the EBITDA/segment/cash-flow/historical-loss facts from §7 at all — a second, independent instance of the exact mechanism identified in §5.
2. **Copywriting had zero mechanism to know event 1 had already been published, regardless of the above.** `EvidencePackage.previous_coverage_summary` exists as a field but is documented as "populated only when available; never fabricated" and — per that module's own docstring — the Phase 19 M7 Story Timeline digest that would populate it "is not yet built." It was `None` for this event, as it is for every event today. Even if Story Memory had correctly matched with high confidence, this specific field would still have contributed nothing.
3. **The two already-built quality/suppression gates that exist for exactly this situation were both structurally unreachable for this pair**, purely because of the §8 entity-extraction gap, not because of any defect in the gates themselves:
   - `services/story_duplicate_guard.py::check_duplicate_story_delivery()` — blocks `SEMANTIC_DUPLICATE`/`SUPPORTING_SOURCE` matches against a Story with a prior root delivery; `uncertain_match` is outside its `_NO_MATERIAL_UPDATE_MATCH_TYPES` set by explicit design ("false suppression is worse than a duplicate" — confirmed via the existing `test_uncertain_match_is_never_blocked` regression test) — never even consulted for this pair's actual match type.
   - `services/content_quality_gates.py::check_update_not_repeating_root()` (the Case C fix from the earlier NEWS Stability Fix phase) — only evaluated when `is_update = is_story_update_match(match_type)` is `True`; `uncertain_match` returns `False` from that shared predicate — this real, already-built repetition check was never invoked for this draft either.

Reconstructed counterfactual: at the corrected `combined=0.97`, this pair would very plausibly classify as `SEMANTIC_DUPLICATE` (extremely high title+entity overlap, near-identical facts) with `has_prior_root_delivery=True` (event 1 was already delivered by the time event 2 was processed) — the exact condition `check_duplicate_story_delivery()`'s V1 check blocks, and nothing in the actual delta between the two posts (§7's "genuine publication delta" is zero) would have caused the V2 delta-engine layer to override that block. **Fixing the entity-extraction defect alone would very likely have prevented this exact duplicate publication through mechanisms that already exist today — no new suppression capability would even be required for this specific pair.**

## 10. VK — first divergence/root cause

**First incorrect boundary: `ENTITY EXTRACTION`.** A precise, reproducible, quantified defect in `_extract_entities()`'s capitalized-run heuristic — a leading, sentence-initial-capitalized common noun ("Отчёт") is captured as part of the entity string because it isn't covered by the deliberately narrow `_GENERIC_DETERMINER_ENTITIES` exclusion set, which is scoped to grammatical determiners/demonstratives, not ordinary nouns. This is a genuine sibling case to the already-fixed CD Projekt/"The Witcher" pattern, in a word-category that fix's own deliberately narrow scope does not cover.

This is primarily a **Story Memory precision failure (Failure Mode A)**, not an architecture-intentionally-allowed-separate-story-then-failed-to-suppress case (Failure Mode B) — though a secondary, compounding architectural characteristic is also real and worth naming precisely: the current design provides **zero** downstream novelty/suppression protection for any pair that lands in `uncertain_match`, regardless of why it landed there. That is a deliberate design choice ("false suppression is worse than a duplicate"), not a bug, but it does mean this class of entity-extraction precision defect has no safety net once it occurs.

## 11. Shared-root-cause assessment

**Not fully shared — one exact mechanism is genuinely shared, but it does not explain either case's decisive outcome by itself.**

- The **reuse-vs-enforce orchestration defect** identified in §5 is independently, exactly confirmed to have occurred in **both** cases (Case 1's Snapdragon Research step, and Case 2's own second-post Research step) — same code path (`capabilities/executor.py::_try_reuse()` + `services/analysis_reuse.py`), same timing signature (a sub-100ms "research" step result identical to one computed 20+ minutes earlier), same consequence (the newly-activated `enforce`-mode evidence never reaches a real LLM call).
- For **Case 1**, this defect is the *entire* explanation — nothing else needs to be true for the omission to occur.
- For **Case 2**, this defect only explains why the second post's content was thin (missing EBITDA/segments/etc.) — it does **not** explain why the post was published as a duplicate at all. That is a fully independent defect (§10, entity extraction) at a completely different layer (Story Memory matching, not evidence sourcing). Fixing the reuse-vs-enforce defect alone would not have prevented the duplicate publication; fixing the entity-extraction defect alone would very plausibly have prevented it via already-existing mechanisms (§9), with or without the reuse defect also being fixed.

**A real, honest, narrower shared theme does hold across both**, matching the first of the three example framings offered: **evidence exists (in the fully acquired article, in both cases) but a downstream mechanism does not reliably consume it** — for Case 1 this is the entire story; for Case 2 it is a real, independently-confirmed, but secondary contributor. The other two example framings offered ("novelty/evidence semantics remain diagnostic rather than enforcing" and "Quality validates prose style but not contradiction/novelty") do not fit cleanly: Case 2's actual suppression mechanisms are not diagnostic-only where they apply — they are fully enforcing, just never reached due to the upstream match-type misclassification; and Quality's fact-safety layer performed correctly given what it was shown in both cases (it is not itself under-strict, it is evidence-starved, same as Research). No single unified root cause is manufactured here — two independent defects, one shared secondary mechanism, honestly reported as such.

## 12. Existing reusable/dormant components

| Component | State | Relevance |
|---|---|---|
| `services/evidence_package.py::build_evidence_package()` (incl. the post-acceptance on-the-fly cleaning fix) | **Working correctly** | Confirmed independently in this report (§4) to return the right, spec-rich text for Case 1 when actually invoked — the problem is it's never reached, not that it's wrong. |
| `capabilities/executor.py::_try_reuse()` / `services/analysis_reuse.py` | **Working exactly as designed for its own original purpose** (avoiding redundant identical LLM calls) | Its own stated premise is silently violated by `article_acquisition_mode=enforce`; this is a new interaction, not a pre-existing bug in the reuse logic itself. |
| `services/story_duplicate_guard.py::check_duplicate_story_delivery()` (V1 + Story Memory V2 delta layer) | **Fully built, fully wired, correctly enforcing** for the match types it's scoped to | Never reached for the VK pair because of the upstream entity-extraction defect — not itself dormant or broken. |
| `services/content_quality_gates.py::check_update_not_repeating_root()` (Case C fix, prior phase) | **Fully built, fully wired** | Same story — gated on `is_story_update_match()`, never reached for `uncertain_match`. |
| Story Memory V2 (`story_delta_engine.py`/`story_confidence.py`/`story_suppression.py`) | Still log-only/gated exactly as previously disclosed | Confirmed again here: never invoked at all for an `uncertain_match` pair (not merely logged and ignored — literally never called), consistent with prior-phase findings. |
| `EvidencePackage.previous_coverage_summary` / Phase 19 M7 Story Timeline digest | **Genuinely not yet built** (disclosed in the field's own docstring) | A real, independent, unbuilt capability — would help even a correctly-matched pair; irrelevant to why this specific pair was misclassified. |
| `_strip_leading_determiner()` / `_GENERIC_DETERMINER_ENTITIES` (CD Projekt fix, prior phase) | **Working correctly for its own deliberately narrow scope** | The Case 2 defect is a sibling case just outside that scope, not evidence the existing fix is broken. |

## 13. Minimal remediation options

**Not implemented. For evaluation only.**

### For Case 1 / the shared reuse-vs-enforce mechanism

- **Option A — make Research-reuse acquisition-aware.** Skip `_try_reuse()` for the `"research"` capability specifically whenever `article_acquisition_mode == "enforce"` and a successful acquisition (`FULL_TEXT`/`PARTIAL_TEXT`) exists for the event, so a fresh call (with the correct `article_evidence_text`) always happens in that case. **Label: `NARROW FIX`.** Risk: no correctness/false-positive risk identified — the only cost is more frequent real Research calls (and their token cost) under `enforce` mode specifically, which is the entire point of turning `enforce` on. `"intelligence"` reuse is unaffected (it doesn't consume acquired-article evidence at all today).
- **Option B — acquire the article earlier, before NEWS_ANALYSIS's own Research runs**, so the *original* NEWS_ANALYSIS result is already correct and reuse remains valid. **Label: `POLICY DECISION`** (moves article acquisition — currently deliberately scoped to CONTENT_GENERATION only — earlier in the pipeline, meaning every event reaching NEWS_ANALYSIS would trigger a real network fetch, not just the smaller set that reach CONTENT_GENERATION; a materially larger cost/footprint/latency change requiring explicit authorization, not a narrow fix).

### For Case 2 / entity extraction

- **Option A — broaden the generic-word-stripping exclusion set** beyond grammatical determiners to also cover common leading nouns ("отчёт", "обзор", "анонс", and English equivalents). **Label: `POLICY DECISION`.** The existing mechanism's own docstring deliberately commits to "never hardcoded from any calibration case" and "no new lexicon" — broadening it is exactly the kind of decision that precedent reserves for a deliberate call, not an ad hoc addition. Real false-positive/over-suppression risk if done carelessly: a poorly-scoped exclusion list could strip the first word of a real, meaningful multi-word entity name that happens to start with a common word, silently merging two genuinely different stories.
- **Option B — replace the capitalized-run heuristic with a real NER pass** (deterministic dictionary-assisted or LLM-assisted). **Label: `NEW CAPABILITY`.** Materially larger scope, cost, and latency; would fix this whole class of defect more durably but is not a narrow change.
- **Option C — loosen the "never suppress uncertain_match" policy**, e.g. give a high-title-overlap `uncertain_match` pair a second look via the delta engine instead of a blanket pass-through. **Label: `POLICY DECISION`**, with **high** false-positive/over-suppression risk — this is the specific, deliberately-chosen design principle ("false suppression is worse than a duplicate") the whole `uncertain_match` bucket exists to protect; loosening it broadly risks suppressing genuinely distinct stories that happen to share generic financial-report phrasing (a real, common pattern in this exact `topic_bucket="financial"` category).

### Cross-cutting

- **Build the Phase 19 M7 Story Timeline digest** (`previous_coverage_summary`) so Copywriting has some prior-coverage awareness independent of match confidence. **Label: `NEW CAPABILITY`.** No correctness risk identified (purely additive context), but a real, previously-scoped, still-unbuilt engineering project, not a quick fix.

No prompt changes, no quality-check version bump, and no wiring change is proposed as a `WIRING ONLY` item for either case this phase — the closest candidate (Option A for Case 1) is classified `NARROW FIX` rather than `WIRING ONLY` because it changes a real decision condition (`_try_reuse()`'s own gating logic), not merely a connection between two already-correct components.

## 14. Recommended next action

Case 1's most direct remediation (reuse Option A) is narrow, low-risk, and could reasonably proceed on its own. Case 2's most direct remediation (entity-extraction Option A) sits squarely on the existing, deliberate "no new lexicon without calibration" precedent this same codebase already established for the sibling CD Projekt fix — broadening it is a real design decision, not a mechanical patch, and the alternative options (B/C) carry either materially larger scope or real over-suppression risk. Since a defensible, narrow fix cannot be finalized for both cases without at least one explicit policy call:

### `POLICY DECISION REQUIRED BEFORE FIX`

STOP after this report. Not committed. Not deployed. Video and source-pack work not resumed.
