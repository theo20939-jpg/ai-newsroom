# Phase 23.1N — Image Editorial Quality Review

Real, persisted image_intelligence data from actual live canary runs (Phase 23.1M/23.1L/23.1K).
Full raw candidate data: `scripts/_phase23_1n_image_candidate_details.txt`,
`scripts/_phase23_1m_forensics_raw.json` (Flock/Venmo/Intel).

**Disclosed gap**: Armenia/Firebird was never delivered through a real live canary (golden-replay
only, per Phase 23.1J/K/M's own explicit "no Telegram sends" scope) - the image pipeline only runs
during a real analysis/content cycle, so no real image_intelligence data exists for it. Not
fabricated here.

---

## NEWS: AI agent hacked a gym booking system (Google News aggregator version, delivered)

**Selected image:** none (correctly fell back to text-only)

**Candidate list:**
1. `open_graph_image` (Google-hosted, 300×300, quality_score 66, status accepted) — a generic
   Google News thumbnail, not an article-specific photo
2. `twitter_image` (same remote URL) — rejected as `duplicate_within_event`

**Chosen because:** neither candidate was ranked eligible (`relevance_score=0` for both) — the
generic aggregator thumbnail never cleared the relevance bar, so the post correctly went out
text-only.

**Rejected candidates:** both (see above) — no story-specific image was ever discovered for this
particular source stub.

**Human verdict:** [ ] Excellent [ ] Acceptable [ ] Generic [ ] Wrong [ ] Low quality [ ] Prefer no image

---

## NEWS: AI agent hacked a gym booking system (3DNews full-article version, not delivered - cap-refused)

**Selected image (would have been):** `ai-hands.jpg` from 3dnews.ru's own article

**Candidate list:**
1. `open_graph_secure_image`, 800×533, quality_score 88, relevance_score 56, rank 1, eligible=True, `source_relationship=same_domain` — **selected**
2. `open_graph_image` (same URL) — rejected `duplicate_within_event`
3. `jsonld_article_image` (same URL) — rejected `duplicate_within_event`

**Chosen because:** the article's own Open Graph image, from the article's own domain, with high
technical quality - a genuine story-adjacent (if generic "AI hands" stock-style) visual, not a
logo or unrelated thumbnail.

**Human verdict:** [ ] Excellent [ ] Acceptable [ ] Generic [ ] Wrong [ ] Low quality [ ] Prefer no image

---

## NEWS: Long March 7A rocket explosion (gadget/tech story)

**Selected image:** `Long-March-7a.jpg` from 3dnews.ru

**Candidate list:**
1. `open_graph_secure_image`, 800×535, quality_score 73, relevance_score 79, rank 1, eligible=True, `source_relationship=same_domain` — **selected**
2. `open_graph_image` (same URL) — rejected `duplicate_within_event`
3. `jsonld_article_image` (same URL) — rejected `duplicate_within_event`

**Chosen because:** the article's own lead image, specific to the actual rocket, high relevance
score (79 - the highest of any candidate examined in this review).

**Human verdict:** [ ] Excellent [ ] Acceptable [ ] Generic [ ] Wrong [ ] Low quality [ ] Prefer no image

---

## NEWS: Anthropic's IPO courting (company story)

**Selected image:** a 142×72 Techmeme inline thumbnail

**Candidate list:**
1. `rss_inline_image`, 142×72, quality_score 65, quality_status **review**, relevance_score **50**, rank **1**, eligible=True, `source_relationship=native_same_item` — **selected**
2. `rss_inline_image` (Techmeme's own favicon, 11×12) — hard-rejected, `favicon_dimensions`
3. `open_graph_image`, **1280×640**, quality_score **98**, quality_status review, relevance_score **47**, rank 2, eligible=True, `source_relationship=source_cdn_or_related` (a WSJ hero image - the true underlying source article's own lead image)
4. `twitter_image` (same URL as #3) — rejected `duplicate_within_event`
5. `image_src_link`, 128×128, quality_score 45, relevance_score 43, rank 3, `source_relationship=same_article`

**Chosen because:** rank-1 by relevance score (50 vs 47) - a narrow margin favoring the small,
same-item Techmeme inline thumbnail over the much larger, higher-quality WSJ hero image.

**Disclosed finding, not fixed this phase**: this is a real, borderline ranking case where a tiny
(142×72), `quality_status=review` inline thumbnail narrowly outranked a large (1280×640),
high-quality (98) image from the true underlying source publication (WSJ), because
`native_same_item` proximity scored higher than `source_cdn_or_related`. Per Part H's own desired
priority ("1. ORIGINAL STORY IMAGE / ARTICLE LEAD IMAGE" ahead of "3. strongly relevant editorial
image"), the WSJ image arguably represents the truer "article lead image" here, since Techmeme is
an aggregator, not the original publisher. Not changed this phase (the ranking algorithm itself is
out of this phase's narrow implementation scope - a duplicate-image guard and this audit's own
findings, not a rescoring change) - reported as a real, evidence-grounded residual gap for a
future, narrowly-scoped ranking adjustment.

**Human verdict:** [ ] Excellent [ ] Acceptable [ ] Generic [ ] Wrong [ ] Low quality [ ] Prefer no image

---

## NEWS: Visa/Mastercard online payment warning (correct text-only fallback)

**Selected image:** none

**Candidate list:** none discovered (0 candidates found at all - not even a rejected one)

**Chosen because:** no image existed anywhere in the source material to discover - the router
correctly delivered text-only, no crash, no placeholder image.

**Human verdict:** [ ] Excellent [ ] Acceptable [ ] Generic [ ] Wrong [ ] Low quality [ ] Prefer no image

---

## NEWS: Flock / anti-recognition patterns (from Phase 23.1M forensics)

**Selected image:** `e2001460...` - an RSS inline image from vc.ru, 1300×731, quality_score 92, relevance_score 57, rank 1, `source_relationship=native_same_item`

**Candidate list:** 4 discovered, 2 ranked eligible (the RSS inline image at rank 1; a same-domain
Open Graph image, quality_score 98, at rank 2 - relevance score again favored the inline/native
candidate over the higher-raw-quality one, same pattern as the Anthropic case above); 2 rejected
as `duplicate_within_event`/exact-duplicate.

**Chosen because:** rank 1, native to the article's own content, high technical quality (92).

**Human verdict:** [ ] Excellent [ ] Acceptable [ ] Generic [ ] Wrong [ ] Low quality [ ] Prefer no image

---

## NEWS: Google Play / Venmo (plain product update)

**Selected image:** Engadget's own Open Graph gallery image, 1600×899, quality_score 98,
relevance_score 59, rank 1, `source_relationship=same_article`

**Candidate list:** 3 discovered, 1 ranked eligible (the others rejected as
`duplicate_within_event`).

**Chosen because:** the article's own lead image, high quality, high relevance - a clean, no-issue
case.

**Human verdict:** [ ] Excellent [ ] Acceptable [ ] Generic [ ] Wrong [ ] Low quality [ ] Prefer no image
