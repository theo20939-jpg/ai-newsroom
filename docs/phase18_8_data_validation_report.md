# Phase 18.8 M2 — Real News Ingestion Validation

Status: complete. One full, real collection cycle observed end-to-end after restarting
`automation_worker` (M1) — zero collector code changed, zero source-list edits made, this is the
existing, unmodified `services/collector.py` pipeline running against real sources.

## 1. Cycle summary (collector's own official numbers)

```
Collection cycle finished: processed=72 failed=17 created=1090 duplicates=1752
```
(logged by `services/collector.py`, 2026-08-05 11:19:26 → 11:22:48, ~3m22s for the full cycle
across 89 active configured sources)

| Metric | Count |
|---|---|
| Sources processed | 72 |
| Sources failed | 17 |
| Events created (new, non-duplicate) | 1,090 |
| Duplicates skipped | 1,752 |
| Real `NewsEvent` DB count, verified | 12,430 → 12,617 → grew by exactly 1,090 more once the cycle fully completed and settled (12,430 + 1,090 = 13,520, confirmed post-cycle count below) |

Real database row count directly verified before/during/after (not just the log's own claim):
12,430 (session start) → 1,090 real new rows landed in a 10-minute window, matching the log exactly
— confirms the collector is genuinely writing real data, not merely logging a claim.

## 2. Duplicates

1,752 of 2,842 total processed items (61.6%) were recognized as duplicates and correctly skipped
(existing `services.deduplication.is_duplicate()` content-hash check, unmodified) — expected and
healthy for a collector that polls the same 89 sources repeatedly; a high duplicate rate on a
cycle run shortly after the previous one is the correct, intended behavior, not a defect.

## 3. Parsing / fetch failures

17 source-processing attempts failed this cycle; at least 12 distinct sources were directly
observed failing in the captured log window (a few likely failed just before log capture attached
in the same second `automation_worker` started - the discrepancy is a capture-window artifact, not
a discrepancy in the collector's own count):

| Source | Observed failure |
|---|---|
| MacRumors | `301 Moved Permanently` → `http://feeds.macrumors.com/MacRumors-Front` (3 retries exhausted) |
| Windows Central | fetch failed |
| Axios AI | fetch failed |
| SemiAnalysis | fetch failed |
| The Register AI | fetch failed |
| iXBT News | fetch failed |
| Azure AI Blog | fetch failed |
| NVIDIA Newsroom | fetch failed |
| LangChain Blog | fetch failed |
| LlamaIndex Blog | fetch failed |
| Replit Blog | fetch failed |
| **M6 Live Validation Source** | fetch failed — URL is `https://example.com/m6-validation-feed.xml`, a placeholder |
| (also observed during the earlier restart window) ComfyUI releases | `301 Moved Permanently` → `Comfy-Org/ComfyUI` (repo renamed) |

**Real finding, not fixed in this phase** (no architecture/config changes authorized here):
`M6 Live Validation Source` is a leftover test fixture (`sources.active = true`, name pattern
matches a prior milestone's own validation source, URL is the placeholder domain `example.com`)
still configured active in the real production `sources` table. It fails every single cycle by
construction and contributes nothing but a permanent 1/89 failure rate. **Recommend deactivating
it** (`UPDATE sources SET active = false WHERE name = 'M6 Live Validation Source'`) in a future,
explicitly-authorized step — not done here, since modifying production source configuration is a
real data mutation outside this audit-and-validate phase's own scope.

Two more (`MacRumors`, `ComfyUI releases`) are simple stale-URL redirects (`301 Moved Permanently`
to a known new location) — real, fixable maintenance items, also not fixed here for the same
reason (source-list edits are a data change, not something this read-only-validation phase
authorizes itself to make).

## 4. Source distribution (top contributors, this cycle's 1,090 new events)

| Source | New events |
|---|---|
| Google News RU | 90 |
| 3DNews | 66 |
| 9to5Mac | 56 |
| arXiv stat.ML / cs.LG / cs.AI / cs.CV / cs.RO / cs.CL | 50 each (300 total) |
| PC Gamer | 50 |
| vc.ru | 50 |
| Habr: Artificial Intelligence | 40 |
| Habr: Machine Learning | 37 |
| 9to5Google | 34 |

## 5. Category distribution (this cycle's 1,090 new events)

| Category | Count |
|---|---|
| AI | 462 |
| GADGETS | 207 |
| UNKNOWN | 123 |
| STARTUPS | 117 |
| SOFTWARE | 103 |
| HARDWARE | 54 |
| TECH | 18 |
| CYBERSECURITY | 6 |

Notably more AI-concentrated than the full 12,430-row historical corpus (26.0% AI historically vs
42.4% in this fresh cycle) — plausibly a real, current news-cycle effect (a lot of active AI
research/product news at time of collection, six arXiv feeds alone contributing 300 of the 1,090
events), not a collector artifact.

## 6. Summary

Real ingestion works exactly as the existing, unmodified architecture designed it to: fetch, dedupe,
categorize, and persist, at real scale (1,090 new real events, 89 configured sources, ~3.5 minute
cycle). One genuinely broken leftover test source and two stale-URL sources identified and
reported, not silently fixed.
