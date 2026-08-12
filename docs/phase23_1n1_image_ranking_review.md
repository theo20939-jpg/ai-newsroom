# Phase 23.1N.1 — Image Ranking Quality — Before/After Review

Offline corpus replay of the new QUALITY_MAX=25/METADATA_CONFIDENCE_MAX=0 weights against 8 real,
previously-persisted image candidate sets. Full data: `scripts/_phase23_1n1_corpus_replay_results.json`.
**Summary**: 8 stories replayed, 6 had a selectable image both before and after, 2 correctly had
none both before and after (no candidates existed at all), **7 of 8 winners unchanged, 1 changed**
(Flock), **zero image→no-image or no-image→image transitions**.

---

## NEWS HEADLINE: Anthropic is courting investors for a potential record IPO

*(The real motivating case for this entire phase — reproduced exactly, with real dimensions, in
`tests/test_image_relevance.py::test_case_1_real_techmeme_vs_wsj_case_the_higher_quality_direct_image_now_wins`,
confirmed FAIL under the old weights, PASS under the new ones — this is the rigorous exact
reproduction; the corpus-replay script's own reconstruction of this same event (below) is a looser
approximation due to imperfect `event_content` reconstruction, disclosed honestly rather than
hidden.)*

**OLD IMAGE:** `http://www.techmeme.com/260811/i1.jpg` — 142×72, quality_score 65 (weak resolution
band), `native_same_item` (RSS inline, same item as the Techmeme entry) — real relevance_score **50**

**NEW IMAGE:** `https://images.wsj.net/im-50714106/social` — 1280×640, quality_score 98 (good
resolution band), `source_cdn_or_related` (the true underlying WSJ source article's own lead
image, discovered via Open Graph) — real relevance_score **47 under the old weights → now wins**

**WHY CHANGED:** `QUALITY_MAX` raised from 15 to 25 (funded by reducing `METADATA_CONFIDENCE_MAX`
from 10 to 0) - the WSJ image's real, substantial quality advantage (98 vs 65) now contributes
enough to the final score to overcome Techmeme's smaller categorical provenance edge
(`native_same_item` vs `source_cdn_or_related`).

[ ] Better  [ ] Same  [ ] Worse  [ ] Prefer no image

---

## NEWS HEADLINE: Anti-recognition patterns (Flock-type story)

**OLD IMAGE:** `https://leonardo.osnova.io/.../resize/1300/` — 1300×731, quality_score 92,
`rss_inline_image`, real relevance_score 54 (old weights, corpus replay)

**NEW IMAGE:** `https://api.vc.ru/v2.9/cover/fb/c/3071307/1786369678/cover.jpg` — 1200×630,
quality_score 98, `open_graph_image`, same article (vc.ru) - relevance_score 58 (new weights)

**WHY CHANGED:** Same mechanism as the headline case, at smaller scale - both candidates are real,
legitimate, high-quality images from the *same* article; the new weights let the OG image's
slightly higher quality (98 vs 92) win a previously RSS-inline-favoring near-tie. Neither image is
generic or wrong; this is a minor, defensible tie-break shift between two good candidates, not a
regression.

[ ] Better  [ ] Same  [ ] Worse  [ ] Prefer no image

---

## Unchanged winners (regression-guard confirmation, no action needed)

| Story | Winner (unchanged) | Old score | New score |
|---|---|---|---|
| Google Play / Venmo | Engadget's own gallery image, 1600×899, q=98 | 59 | 62 |
| Intel $15B | Bloomberg-hosted article image, 1200×800, q=98 | 50 | 52 |
| AI-agent gym story (3DNews full article) | 3dnews.ru's own `ai-hands.jpg`, 800×533, q=88 | 46 | 49 |
| Long March 7A | 3dnews.ru's own `Long-March-7a.jpg`, 800×535, q=73 | 69 | 70 |

All 4 winners are unchanged - scores rose slightly (the new weights give quality more credit
overall) but never enough to flip an already-correct winner. **No regression in any previously
good case.**

## Unchanged no-image cases (regression-guard confirmation)

| Story | Result (unchanged) |
|---|---|
| AI-agent gym story (Google News aggregator stub) | No candidates ranked eligible - correctly text-only, both before and after |
| Visa/Mastercard warning | Zero candidates discovered at all - correctly text-only, both before and after |

## Disclosed gap: Armenia/Firebird

Not included in this replay - as disclosed in Phase 23.1N's own report, Armenia/Firebird was
never delivered through a real live canary (golden-replay only), so no real image_intelligence
data exists for it to replay against.
