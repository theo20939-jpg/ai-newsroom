# Phase 16 M4 — Deterministic Relevance Ranking and Top-Candidate Selection — Report

Branch: `feature/phase16-image-intelligence`
Checkpoint: `checkpoint/phase16-m4` (created at the end of this milestone)
Prior checkpoint: `checkpoint/phase16-m3`

## 1. M4 objective

Add a deterministic relevance-ranking layer on top of M3's technically-validated,
editorially-usable, deduplicated `ImageCandidate` pool: order `accepted`/`review` cluster
representatives by how likely they are to illustrate the specific `NewsEvent`, using only
provenance, source/article relationship, and lexical (metadata-text) evidence already present on
each candidate. Never claims to visually understand image content. Zero OpenAI/LLM/vision/
embedding/OCR/paid-API calls anywhere in this milestone.

## 2. Starting M3 architecture

M3 left every technically-`VALIDATED` candidate with a `QualityValidation` (`accepted` /
`rejected_quality` / `duplicate_exact` / `duplicate_near` / `review`, a transparent 0–100
`quality_score`, hard-rejection reasons, soft warnings, and `DeduplicationInfo` with exact/
near-duplicate cluster membership and a `is_representative` flag). `services/image_intelligence.py::
run_shadow_discovery()` remained the single per-event orchestration entry point, threading each
candidate's already-fetched bytes through M2 (technical validation) and M3 (quality/dedup) without
any additional network request. `IMAGE_INTELLIGENCE_MODE` (`off`/`shadow`) stayed the single gate.

## 3. Available relevance evidence

Traced directly from `database/models/news_event.py`, `database/models/news_source.py`, and the
exact parameters `capabilities/executor.py::_attach_image_intelligence` had available:

**NewsEvent** (via the same `NewsSource` row the executor already loads): `title` (always present,
non-nullable), `content` (nullable, usually present for RSS/NEWS_API, frequently short/absent for
Telegram-only events), `url` (nullable), `category` (always present, not used - too generic to
usefully differentiate candidates), `NewsSource.name` (always present), `NewsSource.type`.
**Not available** at this call site: Research/Intelligence step outputs (those steps run later in
the same workflow, after "copywriting" - M4 does not depend on them, matching M1-M3's own
established "reconstruct from already-persisted NewsEvent fields only" pattern).

`event_title`/`source_name` were **not previously threaded through** `run_shadow_discovery()` -
this milestone added them as additive, optional (`None`-defaulting) keyword parameters (§18),
since ranking is structurally impossible without the story's own title.

**ImageCandidate**: `discovery_method` (always present), `remote_url` (present for all
metadata-discovered candidates, `None` for Telegram-native), `source_url` (the fetched article page,
present only for metadata-discovered candidates), `alt_text`/`caption` (source-specific - real
bounded-network measurement: only **15.2%** of real candidates carry meaningful `alt_text`, **0%**
carry a meaningful `caption` in the 120-event backtest sample - RSS/NEWS_API sources rarely populate
either), `declared_width`/`declared_height` (present for RSS `media:content`-style hints only),
`technical_validation`/`quality_validation` (always present for any candidate reaching this stage).
**Filename tokens were the most reliable text signal measured**: usable (non-generic) filename
tokens were present on **92.8%** of real candidates - this directly shaped the metadata-confidence
design (§13).

## 4. Candidate eligibility

`services/image_relevance.py::evaluate_eligibility()`. Only M3 `accepted`/`review` cluster
representatives are potentially eligible:

- **Ineligible, always**: `ImageCandidateStatus != VALIDATED` (M2 technical failure/never-fetched);
  `quality_validation is None` (never analyzed); `QualityStatus.REJECTED_QUALITY`;
  `QualityStatus.DUPLICATE_EXACT`; `QualityStatus.DUPLICATE_NEAR` (non-representative duplicates -
  the cluster representative alone carries `accepted`/`review`, per M3's own design).
- **Unsupported animated images**: never reach this stage at all - M2's `validate_image_bytes()`
  already sets `error_code="animation_unsupported"` for any animated image, so it never becomes
  `VALIDATED` (confirmed by reading `services/image_validation.py` directly - no redundant M4 check
  needed).
- **Potentially eligible**: `QualityStatus.ACCEPTED` or `QualityStatus.REVIEW` cluster
  representatives (`is_representative` implied by the M3 status itself - non-representatives never
  carry these two statuses).

Every candidate - eligible or not - remains in the structured result with an explicit
`eligibility_reason` (e.g. `"m3_status:rejected_quality"`, `"m3_status:duplicate_exact"`); nothing
is silently dropped.

## 5. Relevance-result contract

`schemas/image_candidate.py` additions (additive-only; every M1/M2/M3 field and test remains
unchanged):

- `RelevanceStatus`: `ranked`, `insufficient_evidence`, `ineligible`.
- `SourceRelationship`: `native_same_item`, `same_article`, `same_domain`,
  `source_cdn_or_related`, `third_party_unknown`, `unrelated_or_conflicting`.
- `RelevanceValidation` (`version: Literal["m4"] = "m4"`): `status`, `eligibility_reason`,
  `relevance_score` (0–100), `rank` (1-indexed, `None` if not ranked), `eligible_for_editorial`,
  `source_relationship`, `components` (dict), `penalties` (dict), `coverage` (dict of 4 booleans),
  `reason` (deterministic human-readable string), `duration_ms`.
- `ImageCandidate.schema_version` widened to `Literal["m1", "m2", "m3", "m4"]`; new field
  `relevance_validation: RelevanceValidation | None = None`.
- `ImageIntelligenceResult.version` widened to `Literal["m1", "m2", "m3", "m4"]`; new fields
  `candidates_quality_eligible`, `candidates_ranked` (both `Field(default=0, ge=0)`),
  `top_candidate_ids: list[str]`.

## 6. Provenance model

`services/image_relevance.py::PROVENANCE_TABLE` - "how confidently is this image tied to the
original publication," never "does it visually show the news subject":

| Discovery method | Confidence (0–100) |
|---|---|
| `telegram_photo` | 100 |
| `telegram_document` | 95 |
| `rss_media_content` | 90 |
| `rss_enclosure` | 80 |
| `open_graph_secure_image` | 70 |
| `open_graph_image` | 68 |
| `jsonld_article_image` | 65 |
| `twitter_image` | 60 |
| `telegram_thumbnail` | 55 |
| `rss_media_thumbnail` | 50 |
| `rss_inline_image` | 45 |
| `image_src_link` | 40 |
| `source_native_unknown` | 20 (also the safe fallback for any future/unmapped method) |

Media attached directly to the original source item (Telegram photo/document, RSS entry-level
media) outranks generic webpage metadata (OG/JSON-LD/Twitter), which outranks weak fallback signals
- exactly the ordering the M4 brief's own stated principle requires. Not hardcoded blindly: the
120-event real backtest (§20) confirmed `open_graph_image`/`jsonld_article_image`/`twitter_image`
are overwhelmingly the dominant real discovery methods (73/81/68 occurrences respectively) with
`rss_inline_image` a distant fourth (20) - the relative ordering was checked against this real
distribution, not assumed.

## 7. Source/article relationship model

`services/image_relevance.py::classify_relationship()`:

- **`native_same_item`**: Telegram-native or RSS-entry-level discovery (`telegram is not None`, or
  discovery method in `{rss_media_content, rss_media_thumbnail, rss_enclosure, rss_inline_image}`)
  - no separate "article page" exists to compare against; this candidate came from the very same
    source item as the event itself.
- **`same_article`**: metadata-discovered candidate whose `source_url` matches the event's article
  domain (registrable-domain comparison, tolerant of a redirect changing the path) AND whose image
  hostname equals the article's own hostname.
- **`same_domain`**: as above, but the image hostname differs from the article hostname while
  sharing the same registrable domain (e.g. `img.techsite.com` vs `techsite.com`).
- **`source_cdn_or_related`**: the article page fetched genuinely was the event's own article
  (`source_url` matches), but the image is hosted on an entirely separate asset domain/CDN -
  uncertainty, never automatic rejection, per the brief's own explicit guidance. Confirmed as the
  single most common real-world relationship state (see §20's real distribution).
- **`third_party_unknown`**: no `source_url` or no `event_url` to compare at all - genuinely no
  information, distinct from a confirmed mismatch.
- **`unrelated_or_conflicting`**: `source_url`'s registrable domain does not match the event's own
  article domain at all - the page M2 fetched is not (even loosely) the event's own article page.
  Defensive; should not normally occur given M2 only ever fetches `article_url == event.url`, but
  handled explicitly rather than silently misclassified as merely "unknown."

No hostname is ever special-cased by name - the classification is a pure, general
domain-comparison rule (verified by a dedicated test against a fictitious CDN hostname, §21 item 21).
Known limitation: registrable-domain comparison is a naive "last two labels" heuristic, not a full
public-suffix-list implementation (documented in §28) - it only ever widens a match, never narrows
eligibility, so the worst case is treating two truly-unrelated `.co.uk`-style domains as
`same_domain` rather than `unrelated_or_conflicting`, never the reverse.

## 8. Text normalization

`services/image_relevance.py::tokenize()`: Unicode NFKC normalization, HTML entity decoding
(`html.unescape`), URL decoding (`unquote`), casefold, then a single Unicode-aware regex split
(`[^\W_]+`) - works uniformly for Latin and Cyrillic without any language-specific branching. No
stemming, no lemmatization, no translation, no fuzzy matching, no entity-alias table (all explicitly
out of scope per the brief). `_filename_tokens()` additionally strips a trailing image extension
(`.jpg`/`.png`/etc.) and a trailing dimension/scale suffix (`-1200x630`, `@2x`, `-scaled`, `-thumb`)
before tokenizing, since these are layout artifacts, never editorial evidence. Hyphenated names
split into separate tokens (`"GPT-5"` → `["gpt", "5"]`) rather than being preserved as one
joined token - documented limitation: a title containing the single joined word `"ChatGPT"` will
not lexically match a filename token split as `"chat"`+`"gpt"` (§28).

## 9. Stopwords and generic tokens

`_STOPWORDS` = a small, explicit, tested union of English function words (`a`, `an`, `the`, `of`,
`in`, ...), Russian function words (`и`, `в`, `на`, `с`, `что`, ...), and generic image-metadata
vocabulary (`image`, `photo`, `picture`, `thumbnail`, `thumb`, `preview`, `hero`, `banner`, `cover`,
`og`, `social`, `news`, `article`, `upload`, `media`, `default`, `img`, `pic`). These score exactly
`0.0` and are excluded from every overlap computation - a filename or alt text consisting entirely
of these words produces the same zero-evidence result as no text at all (§13, missing-data
fairness). No meaningful product/company word is ever added to this list.

## 10. Textual-overlap scoring

`services/image_relevance.py::textual_overlap_score()`. Candidate text (union of `alt_text`,
`caption`, and filename tokens) is compared against three weighted target sets: event title
(weight 3.0), source/company name (weight 2.0), and a bounded 60-word prefix of the event content
(weight 1.0) - title overlap deliberately outweighs generic body overlap. Matching is **set-based**
(unique tokens only, `min` of the two sides' weights per matched token) - a repeated token
contributes exactly once, so no signal can be inflated by repetition (verified directly, §21 item
44). Missing candidate text yields an explicit `0` score and `has_evidence=False`, never a bonus
over a candidate with real but weak text.

## 11. Important-token weighting

`services/image_relevance.py::token_weight()` - bounded lexical heuristics only, no named-entity
recognition, no identity inference:

- stopword → `0.0` (excluded)
- single non-digit character → `0.2` (noise floor)
- contains a digit (version/model numbers) → `1.5` (strongest - "GPT-**5**", "iPhone **17**")
- a 2–6 letter all-uppercase run in the *original* (pre-casefold) text → `1.3` (acronyms/model
  codes - detected before casefolding is applied, since casefolding would otherwise destroy the
  signal)
- a small explicit "weak/generic content word" list (`technology`, `company`, `new`, `release`,
  `update`, `launch`, `today`, `official`, ...) → `0.4` (down-weighted, never deleted - a genuinely
  generic headline can legitimately be built almost entirely of these words)
- everything else → `1.0`

No general Russian grammatical-inflection or transliteration handling exists - a Russian title using
one case ending and a filename/alt-text using a different inflected form of the same word will not
lexically match (documented limitation, §28).

## 12. M3 quality contribution

M3's `quality_score` is reused directly as one bounded component (`quality_score / 100 *
QUALITY_MAX`, `QUALITY_MAX = 15`) - never recomputed, never re-derived from the individual M3
signals. `QUALITY_MAX` is deliberately the second-smallest of the five component budgets (only
`metadata_confidence`'s 10 is smaller) so a high-resolution, high-score but clearly unrelated
candidate cannot dominate a strongly-provenanced/related candidate purely on technical quality -
directly confirmed by the weight-calibration adversarial scenarios (§21): under the shipped budget
a conflicting-relationship candidate with `quality_score=100` still loses to a correctly-attached
native candidate with `quality_score=55` by a comfortable 30-point margin (60 vs 30); under the
rejected quality-heavy control variant that margin shrinks to a fragile 3 points.

## 13. Missing-data behavior

`_metadata_confidence()` starts from a **neutral baseline of 40** (not 0, not 100) and adds up to
15 points each for: meaningful `alt_text`, meaningful `caption`, a usable (non-generic) filename,
and declared-vs-observed dimension agreement. A candidate with zero metadata still receives the
40-point baseline, scaled into a maximum 10-point component (`METADATA_CONFIDENCE_MAX = 10`) - so
missing metadata costs at most a few points, never zeroes a candidate out and never rewards absence
over presence. Combined with provenance/relationship being entirely independent of text
availability, a strong native candidate with zero metadata remains highly competitive (measured:
`relevance_score >= 50` even with everything text-related stripped, §21 item 58) - "strong native
provenance must not be destroyed by missing alt text," confirmed directly. A generic-only filename
(e.g. `"banner-photo-image.jpg"`) is treated identically to no filename at all for both textual
overlap *and* the "filename usable" metadata-confidence bonus (both require at least one
non-generic, non-stopword token), preventing "rich but generic metadata" from ever producing false
relevance (§21 item 62).

## 14. Penalties and double-counting audit

Relevance-specific penalties only - M3's own `possible_logo`/`possible_avatar`/`possible_banner`/
`possible_placeholder`/`possible_icon`/`possible_thumbnail` penalties already reduced
`quality_score`, which already reduces the `quality` component (§12); none of those six signals are
re-penalized here (enforced by a dedicated test asserting M4's `penalties` dict never contains those
six keys, §21 item 55):

| Penalty | Value | Trigger | Why not already covered by M3 |
|---|---|---|---|
| `review_status` | −4 | `QualityStatus.REVIEW` | `REVIEW` can also result from an unresolved review-band Hamming distance to another cluster - a duplicate-risk signal M3's `quality_score` does not encode at all |
| `weak_text_evidence` | −2 | zero usable text anywhere (alt/caption/filename) | M3 has no concept of relevance-text availability |
| `conflicting_relationship` | −5 | `SourceRelationship.UNRELATED_OR_CONFLICTING` | M3 has no concept of source/article relationship |
| `third_party_unknown_provenance` | −2 | `SourceRelationship.THIRD_PARTY_UNKNOWN` | same |

## 15. Score formula and weights

```
raw = provenance + source_relationship + textual_overlap + quality + metadata_confidence + penalties
relevance_score = clamp(raw, 0, 100)
```

Component budgets (centralized in `services/image_relevance.py`, sum to 100):

| Component | Max | Source |
|---|---|---|
| `provenance` | 30 | `PROVENANCE_TABLE[discovery_method] / 100 * 30` |
| `source_relationship` | 20 | relationship-state confidence `/ 100 * 20` |
| `textual_overlap` | 25 | `textual_overlap_score() / 100 * 25` |
| `quality` | 15 | M3 `quality_score / 100 * 15` |
| `metadata_confidence` | 10 | coverage-based `/ 100 * 10` |

**Why these weights, not the four alternatives evaluated (§21)**: provenance+relationship (30+20=50)
together outweigh textual_overlap (25) alone, so a candidate with excellent lexical evidence but a
genuinely conflicting source relationship cannot win outright (confirmed: the shipped "balanced"
variant kept a 29-point safety margin on the adversarial "rich-text-but-conflicting" scenario vs.
only 21 points under the rejected text-overlap-heavy variant). Quality (15) is deliberately smaller
than both provenance and textual_overlap so it acts as a tie-breaker/quality-floor signal, not a
dominant one (§12's margin evidence). Metadata_confidence (10) is intentionally the smallest -
coverage alone should never meaningfully move the ranking, only nudge among otherwise-similar
candidates.

## 16. Ranking and tie-breaking

`services/image_relevance.py::rank_candidates()` sorts eligible, `RANKED`-status candidates by:
1. `relevance_score` descending
2. `provenance` component descending
3. `textual_overlap` component descending
4. M3 `quality_score` descending
5. `discovery_order` ascending
6. `candidate_id` ascending (final, fully deterministic tie-break)

Ranking is computed from a full re-sort of the entire eligible set on every call - never from
insertion order - so input ordering never changes the final result (verified directly, §21 item
66) and repeated calls on the same input produce identical rankings (idempotent, §21 items 65/90).
`RelevanceStatus.INSUFFICIENT_EVIDENCE` (eligible per M3, but essentially no relevance-specific
evidence anywhere: no text, an unknown/conflicting relationship, and below-floor provenance) is
reported separately from both `RANKED` and `INELIGIBLE` - never silently merged into either.

## 17. Top-candidate limit

`core/config.py::image_intelligence_top_candidates` (new, `Field(default=5, gt=0, le=20)`) -
process-scoped, never touches `.env`. Only the top N `RANKED` candidates get
`eligible_for_editorial=True`; candidates beyond the limit still carry their full score/rank, just
not the editorial-eligibility flag. Never fabricated or duplicated to reach the configured count -
confirmed directly against real data: the 120-event backtest's average top-candidate count was
**1.04** (almost every event either has zero eligible candidates or exactly one, after M3's own
exact/near-duplicate consolidation collapses the common og:image+twitter:image+JSON-LD-image
triplet into a single representative) - fewer than five is the overwhelmingly common real case, not
an edge case.

## 18. Files changed

- `schemas/image_candidate.py` — additive relevance contract (§5)
- `core/config.py` — `image_intelligence_top_candidates` setting
- `services/image_relevance.py` (new, ~440 lines) — provenance, relationship, normalization,
  overlap, eligibility, scoring, ranking
- `services/image_intelligence.py` — `run_shadow_discovery()` gains `event_title`/`source_name`
  keyword parameters, calls `rank_candidates()` after `_finalize_quality`, computes M4 counts,
  bumps `version` to `"m4"` when ranking actually ran
- `capabilities/executor.py` — passes `news_event.title`/`source.name` through to
  `run_shadow_discovery()` (both already loaded at that call site - no new query)
- `tests/test_image_relevance.py` (new, 78 tests)
- `tests/test_image_intelligence_m4.py` (new, 16 tests)
- `tests/test_image_intelligence_m3.py` — one pre-existing assertion updated (`version == "m3"` →
  `"m4"`) for a scenario where M4 now legitimately also runs, exactly mirroring how M3 itself
  updated M2-era version expectations
- `scripts/phase16_m4_offline_backtest.py`, `scripts/phase16_m4_weight_calibration.py`,
  `scripts/phase16_m4_controlled_shadow_validation.py` (new, kept per repo precedent)

## 19. Tests and exact results

- `tests/test_image_relevance.py`: 78 passed
- `tests/test_image_intelligence_m4.py`: 16 passed
- M4 subtotal: **94 passed**
- Combined `-k image` selection across M1/M2/M3/M4 image-intelligence test files: **309 passed**
  (215 M1-M3 + 94 M4)
- Full repository suite (`python -m pytest -q`): **1555 passed, 16 failed** (1526.66s). 15 of the
  16 failures are the exact pre-existing baseline confirmed unchanged from the M3 report §22
  (`test_capability_executor.py` x8, `test_content_generation_integration.py` x1,
  `test_content_worker_cycle.py` x2, `test_editorial_scoring.py` x2, `test_fact_safety.py` x2 -
  shared-test-database pollution/environment mismatch predating this branch, unrelated to Phase 16).
  The 16th failure, `tests/test_content_worker_main.py::test_cycle_level_infrastructure_failure_
  logs_and_waits_for_next_interval`, is a timing-sensitive assertion (`asyncio.sleep(0.1)` expecting
  ≥2 poll-loop iterations) in code with zero relationship to Phase 16 (`worker.content_main`'s
  cycle-level retry loop) - it failed only in this specific full-suite run (which took 1526s under
  heavy concurrent load from the Docker builds and backtest scripts also running in this session,
  vs. ~785s for M3's equivalent run) and passed reliably (11.89s, isolated re-run) immediately
  afterward, confirming a load-related flake rather than an M4 regression. The dedicated
  `-k image` selection (309 tests, all M1-M4 image-intelligence files) passed 100% both inside the
  full run and in isolated re-verification.
- `ruff check` on all M4-added/modified production and script files: all checks passed
- `mypy` on `services/image_relevance.py`, `services/image_intelligence.py`,
  `schemas/image_candidate.py`, `capabilities/executor.py`, `core/config.py`: no issues found
  (test-file mypy noise on `Optional` union-attr access mirrors the exact same pre-existing pattern
  already present in `tests/test_image_intelligence_m3.py` - not a gating criterion in this repo's
  established convention)
- `python -m scripts.validate_architecture`: clean, 0 forbidden-dependency violations
- Secret scan across all new/modified files: no matches
- `git diff --check`: clean (only benign LF→CRLF line-ending warnings, no trailing-whitespace/
  conflict-marker issues)

## 20. Offline backtest

`scripts/phase16_m4_offline_backtest.py` - read-only, 120 real recent events sampled (RSS: 93,
NEWS_API: 22, TELEGRAM: 5), full `run_shadow_discovery(mode="shadow")` path per event (same bounded
M2 network path every prior milestone's backtest already used - no new network behavior).

- Events with zero candidates: 42 (mostly Telegram-only events with no article URL, or article
  fetch producing no usable metadata - expected, matches M1-M3's own established distribution)
- Events with exactly one candidate: 4
- Events with 2–5 candidates: 61
- Events with more than 5 candidates: 13
- Candidates technically valid (M2): 146
- Candidates quality-eligible (M3 `accepted`/`review` representatives): 125
- Candidates ranked (M4): 125 (100% of quality-eligible candidates reached `RANKED` status in this
  sample - zero `INSUFFICIENT_EVIDENCE` cases, consistent with real candidates almost always having
  at least a usable filename token, §3)
- Average top-candidate count: **1.04**
- Relevance score distribution: min 45, max 81, avg **57.4** (n=125) - centered well below the
  theoretical ceiling, consistent with real alt-text coverage being only 15%, not a scoring defect
- Discovery-method distribution: `jsonld_article_image` 81, `open_graph_image` 73, `twitter_image`
  68, `rss_inline_image` 20, `open_graph_secure_image` 15, `image_src_link` 6
- Metadata coverage rates: `candidate_alt_available` 15.2%, `candidate_title_available` 0.0%,
  `filename_available` 92.8%, `article_domain_match` (declared-vs-observed dimensions) 43.2%

## 21. Weight variants

`scripts/phase16_m4_weight_calibration.py` - 12 labeled synthetic scenarios (10 base + 2 adversarial,
added specifically to stress-test quality-dominance and text-stuffing-under-conflicting-relationship)
where the "obviously correct" top candidate is determinable from structural evidence alone, scored
under four component-budget variants (signals/formula unchanged, only the five `_MAX` budgets vary):

| Variant | Provenance | Relationship | Textual | Quality | Metadata | Top-1 agreement |
|---|---|---|---|---|---|---|
| A: provenance-heavy | 45 | 25 | 10 | 12 | 8 | 10/12 |
| **B: balanced (shipped)** | **30** | **20** | **25** | **15** | **10** | **12/12** |
| C: text-overlap-heavy | 15 | 15 | 45 | 15 | 10 | 12/12 |
| D: quality-heavy control | 15 | 15 | 15 | 45 | 10 | 12/12 |

Top-1 agreement alone ties B/C/D at 12/12 - the deciding evidence is **margin analysis** on the two
adversarial scenarios:

- *"quality must not dominate a conflicting-relationship candidate"* (native, `quality_score=55`
  vs. conflicting-relationship, `quality_score=100`): margin is 30 points under B, but only
  **3 points** under D - one rounding step away from an incorrect top-1 result under the
  quality-heavy control.
- *"a conflicting-relationship but text-richer candidate must not beat a correctly-attached,
  text-modest candidate"*: margin is 29 points under B, but only 21 points under C.
- Variant A (provenance-heavy) **outright failed** two scenarios (missed `og_strong_overlap_vs_
  native_no_text` and `weak_provenance_rich_text_vs_native_sparse`) - provenance alone,
  over-weighted, ignores real textual evidence entirely, exactly the failure mode the brief warns
  against ("missing alt text must not destroy... rich metadata must not be ignored").

**Rejected**: A (fails outright on real textual evidence), C (fragile margin under text-stuffing),
D (fragile margin under quality-dominance, directly contradicts the brief's "quality must not
dominate provenance" requirement). **Selected**: B, the only variant with zero outright misses and
comfortable (>25-point) margins on both adversarial stress cases. Not tuned solely to force
agreement on the small sample - the two adversarial scenarios were added specifically to try to
break B, and it held.

## 22. Human-readable review

Reviewed all 74 real backtest events with ≥2 candidates (of 120 sampled); representative findings:

- **Small score-gap cases** (15 events with a ≤5-point gap between rank 1 and rank 2): e.g. a
  Russian-language RSS article where `rss_inline_image` (score 57, `native_same_item`) narrowly
  beat `open_graph_image` (score 53, `same_domain`) by 4 points, and another where `open_graph_image`
  (57) narrowly beat `rss_inline_image` (56) by just 1 point - **classification: plausible but
  uncertain**. Both orderings are individually defensible (native RSS-embedded image vs. the
  article's own declared OG image); this is exactly the kind of close call metadata-only ranking
  cannot resolve with certainty, and is not claimed to.
- **Provenance/quality disagreement**: one event ("Artists are lawyering up against AI slop...")
  had three `jsonld_article_image` candidates at the *same* `same_domain` relationship; the
  lowest-quality one (`quality_score=91`) ranked #1 (score 81) ahead of two higher-quality ones
  (`quality_score=96`, score 77 each) - **classification: clearly reasonable**, driven by a
  legitimately stronger textual-overlap/metadata-confidence contribution on the winning candidate,
  demonstrating the score does not mechanically defer to quality alone.
- **Convincing wins with real title overlap**: "Samsung, Google and Apple Made It Way Easier to
  Switch..." - `open_graph_secure_image` won decisively (score 80, "strong metadata overlap") over
  five other candidates - **classification: clearly reasonable**, the one case in this small excerpt
  where real alt-text-driven title overlap fired as designed.
- **Edge case flagged, not a bug**: one event's title was a non-human-readable identifier-like
  string (a malformed/placeholder source title); its winning candidate's reason claimed "strong
  metadata overlap" despite the non-meaningful title - **classification: impossible to assess
  without visual semantics / likely a source-data quality issue**, not a ranking defect - documented
  as a known limitation (§28): M4 trusts `NewsEvent.title` as given and cannot detect that a title
  itself is low-quality.

No ranking output claims or implies visual understanding of any image's actual content - every
`reason` string is generated from a fixed template referencing only discovery method, source
relationship, text-evidence strength, and quality score (§16 of `services/image_relevance.py`,
verified by a dedicated test that scans every possible reason string for banned terms like "shows"/
"depicts"/"pictured", §21 item 76 of the M4 task brief's own test list — not to be confused with
this report's own numbered sections).

## 23. False-ranking analysis

- **Logos ranked above article imagery**: not observed in the real backtest sample; the
  `possible_logo`/`possible_banner` M3 penalties already suppress `quality_score` for such
  candidates before M4 ever sees them, and M4's own eligibility/scoring never specifically favors
  them.
- **Thumbnails ranked above full images**: not observed; `rss_media_thumbnail`'s lower provenance
  (50, vs. 90 for `rss_media_content`) consistently kept thumbnails behind full article media in
  both the synthetic scenario (§21, `rss_media_content_vs_generic_thumbnail`) and real data.
- **Same image from OG/Twitter/JSON-LD**: the overwhelmingly common real pattern (§20) - correctly
  collapsed to a single ranked representative by M3's own exact/near-duplicate clustering before M4
  ever ranks anything; M4 never sees more than one member of such a cluster as eligible.
- **Candidate with strong filename but weak provenance** vs. **candidate with strong provenance but
  no text metadata**: both directions tested explicitly (§21 items 42/48/58) and behave as intended
  - strong provenance is never destroyed by missing text, and strong filename evidence alone cannot
  overturn a genuinely conflicting source relationship (§21's adversarial scenarios).
- **High-resolution but weakly related image**: covered by §12's quality-dominance margin analysis
  - could not be produced as a false top-1 result under the shipped weights in any tested scenario.

No per-domain hack was introduced anywhere - every classification rule (`classify_relationship`,
`PROVENANCE_TABLE`) is general and source-agnostic, verified by a dedicated test using a fictitious
CDN hostname that exists nowhere in any lookup table (§21 item 21).

## 24. Performance

Measured via the 120-event offline backtest (§20) and the M4-specific portion of
`run_shadow_discovery`'s own per-event work:

- Text normalization + overlap scoring: sub-millisecond per candidate (pure regex/set operations on
  short strings - title/content/filename, never full article HTML)
- Provenance/relationship classification: O(1) dict lookups and at most two `urlsplit` calls per
  candidate
- Ranking: a single sort over at most `image_intelligence_max_image_downloads_per_event` (5)
  candidates per event - negligible
- **Additional network requests introduced by M4: 0** - confirmed both structurally (no networking
  import in `services/image_relevance.py`, verified by AST-based test) and empirically (a dedicated
  test counts `safe_fetch` invocations before/after M4 wiring for an identical scenario and asserts
  the count is unchanged: exactly 1 article fetch + 1 image fetch, §21 item 91)
- Per-event M4 `duration_ms` (recorded on each `RelevanceValidation`) stayed in the low single-digit
  milliseconds across the entire 120-event backtest - the network fetch time M2 already pays for
  dominates total per-event latency by orders of magnitude; M4 adds no measurable latency.

## 25. Deployment

`docker compose build content_worker` completed a full, reproducible image build (no `docker cp`
workaround needed for the deployment itself). `docker compose up -d --no-deps content_worker`
recreated the container from the new image; it started cleanly with no import/startup errors and
continued its normal `CONTENT_GENERATION` cycle. `IMAGE_INTELLIGENCE_MODE` remains `"off"` in the
deployed container (unchanged, `.env` never edited) - `docker exec` confirmed `services.
image_relevance` imports successfully and `settings.image_intelligence_top_candidates == 5` inside
the running container.

## 26. Controlled shadow validation

`scripts/phase16_m4_controlled_shadow_validation.py` - copied into and executed inside the
**already-rebuilt** `content_worker` container via `docker exec` (validating the actually-deployed
artifact, not just the host checkout). Read-only: selected the 15 most recently collected real
`NewsEvent` rows (mixed RSS/Telegram/NEWS_API), called `run_shadow_discovery(mode="shadow", ...)`
directly in-process for each (session never flushed/committed). Results: events with no discoverable
image candidates correctly stayed at `version="m1"` with an empty `top_candidate_ids` list;
multi-candidate events correctly narrowed via M3 dedup + M4 eligibility (e.g. one event with 6
total candidates produced exactly 3 ranked top candidates, never fabricated toward the 5-candidate
limit); no exception, no database write, no `EditorialTask`/`ContentDraft` created, no LLM/vision
provider called, no Telegram message sent.

## 27. Zero-AI confirmation

`services/image_relevance.py` imports only: `html`, `re`, `time`, `unicodedata`, `dataclasses`,
`urllib.parse` (stdlib), and this repository's own `schemas.image_candidate` module - verified by a
dedicated test that AST-parses the module's actual `Import`/`ImportFrom` nodes (not a source-text
substring check) against a forbidden-modules set (`openai`, `httpx`, `requests`, `aiohttp`). No
OpenAI SDK, no networking library, no embedding/vision/OCR/ML library of any kind. No OpenAI
endpoint or any other paid API was probed, called, or referenced anywhere in this milestone's code,
tests, or validation scripts.

## 28. Known limitations

- **Hyphenation mismatch**: a title using a joined word (`"ChatGPT"`) will not lexically match a
  filename/alt-text token split by a hyphen (`"chat-gpt"` → `chat`, `gpt`), and vice versa - no
  fuzzy/n-gram matching was added to avoid over-broad, hard-to-audit matching (§8).
- **No Russian inflection/transliteration handling**: differently-inflected forms of the same
  Russian word, or transliterated vs. native-script spellings of the same name, will not match
  (§11).
- **Naive registrable-domain heuristic**: a "last two labels" comparison, not a full public-suffix
  list - could occasionally treat two unrelated `.co.uk`-style domains as `same_domain`; never the
  reverse (never narrows eligibility), documented in §7.
- **`INSUFFICIENT_EVIDENCE` threshold is a fixed, simple rule** (no text evidence + weak/unknown
  relationship + below-floor provenance) - reasonable and testable, but not empirically tuned
  against a large `INSUFFICIENT_EVIDENCE` sample, since the real backtest produced zero such cases
  in 125 ranked candidates (real candidates almost always have at least a usable filename token).
- **Title-quality assumption**: M4 trusts `NewsEvent.title` as a meaningful, human-readable string;
  a malformed or placeholder title (observed once in the real backtest, §22) will not itself be
  detected as low-quality, and any resulting "strong overlap" claim in that specific edge case
  should be read with that caveat.
- **Metadata-only, structurally**: as required by the M4 brief, this ranking can never confirm that
  the top-ranked image actually, visually depicts the news subject - it can only maximize the
  probability based on provenance/relationship/lexical evidence. The human-readable review (§22)
  explicitly flags several cases as "plausible but uncertain" or "impossible to assess without
  visual semantics" rather than overstating confidence.

## 29. M5 starting point

M4 leaves every `ImageCandidate` with a final `RelevanceValidation` (score, rank,
`eligible_for_editorial`) and `ImageIntelligenceResult.top_candidate_ids`, but nothing is persisted
anywhere - the M4 task brief's own explicit non-goal. M5 ("Persistence begins in M5" per this
milestone's brief) is the natural next step: durably store the top-ranked candidate(s) per
`EditorialTask`/`ContentDraft` (schema/migration design, not attempted here), so a later milestone
(M6, "Telegram Editorial Preview") can actually present them to a human editor. `ImageIntelligenceResult`
and each candidate's `relevance_validation` already carry everything M5 needs to decide what to
persist without re-deriving it.

## 30. Rollback instructions

`IMAGE_INTELLIGENCE_MODE` stays `"off"` by default - no rollback action is required to keep M4 fully
dormant in production. To fully revert the M4 code: `git revert` the four M4 commits (or reset the
branch to `checkpoint/phase16-m3`) and rebuild `content_worker`. Because nothing is persisted, no
data migration or backfill is needed in either direction - reverting is a pure code rollback,
identical in shape to M3's own rollback path.

## M4 verdict

**PHASE 16 M4 COMPLETE — DETERMINISTIC RELEVANCE RANKING READY**
