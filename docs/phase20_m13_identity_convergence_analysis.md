# Phase 20 M13 — Identity Convergence Analysis (full Story-cluster context)

Uses the CP4-final replay's own rich diagnostics (`known_case_pool_diagnostics` /
`known_case_results` in `artifacts/phase20_checkpoint4_final_replay_results.json`) - full ranked
candidate scoring, complete winning/true-sibling Story detail (every linked event, not just the
root), for all 4 mandatory cases. **No algorithm change was made based on this analysis** - per
explicit instruction, findings are reported, not acted on, except where noted as already fixed in
Checkpoint 4.

---

## A. AI Olympiad — events 4, 8, 14

**The real dataset contains at least 3 independent, genuinely-overlapping Russian-language
articles clusters about the same underlying event** (multiple outlets, `Google News RU: ИИ`
aggregator variants), not one clean cluster the 3 calibration events should trivially join:

| Cluster (root title, abridged) | Members | 
|---|---|
| `c2c6e167…` "7 золотых и 1 бронзовую медаль... IOAI 2026" (root: Хабр) | root event, **event 4** (uncertain_match 0.5), one more uncertain_match (0.41) |
| `f36c031a…` "Российский бигтех ужесточил правила защиты данных" (root: BeInCrypto - **unrelated topic, data protection**) | root event, 3 unrelated uncertain_matches, **event 8** (uncertain_match 0.5) |
| `abd8e1c6…` "Школьная сборная России третий год подряд стала абсолютным чемпионом" (root: a Related-Story-created provisional root) | root event, 2 corroborating uncertain_matches (0.63, 0.58), **event 14** (semantic_duplicate 0.827, its actual best match, confirmed correct in Checkpoint 4 §1) |

**Per-event classification:**

- **Event 4** (`0223f966`): attached to `c2c6e167…`, a genuinely related candidate (combined 0.5,
  in the uncertain band) — plausible, conservative, not obviously wrong given the real ambiguity.
  **EXPECTED_UNCERTAINTY.**
- **Event 8** (`7370d474`): attached to `f36c031a…` — **a topically unrelated "data protection
  rules" story** — instead of its own genuinely closer sibling `c2c6e167…` (which *was* present in
  Stage 2, ranked 4th, and scored 0.30). The unrelated candidate won only because generic,
  high-frequency Russian AI-news words (*"российский"*, *"ии"*) inflated its score above the
  genuinely related candidate's. **This is a real, reproducible defect** — demonstrated with exact
  scores and full story detail above, not inferred. Classification: **SCORING_MISS**. Per this
  checkpoint's own scope (human suppression review + identity documentation, not further algorithm
  changes), **this is reported, not fixed** — a candidate for a future, explicitly-authorized
  precision pass (e.g., a stop-word/generic-token discount in `score_candidate()`'s keyword
  overlap, evidence-grounded by this exact case).
- **Event 14** (`747aa0cc`): attached to `abd8e1c6…`, its own correct best match (confirmed
  Checkpoint 4 §1). **NO_ISSUE.**

None of the 3 root events for these clusters trace back to calibration events 4/8/14 themselves -
they are all *other*, real, independently-discovered articles. The calibration dataset's own
3-event slice was simply incomplete relative to the real news ecosystem that day - not a defect in
the matcher.

## B. Moscow student pair

- **Event 10** (`db8e85f2`): attached to `51f0657e…` ("Школьники из РФ третий год подряд берут
  золото..."), yet another real, closely-adjacent Olympiad-cluster article (itself already holding
  2 linked events) - genuinely ambiguous given the topical density of same-day Olympiad coverage.
  **EXPECTED_UNCERTAINTY** - directly consistent with the calibration dataset's own pre-existing
  `NEEDS_HUMAN_LABEL` annotation on this case's relationship to the broader Olympiad cluster.
- **Event 11** (`660a5e88`): attached via `RELATED_STORY` to `df35805f…` ("Собянин рассказал о
  внедрении ИИ на московских промышленных предприятиях") - a **different, real Sobyanin/AI story**
  (Moscow industrial AI adoption, not the Olympiad win) that shares the same real spokesperson
  entity. Correctly *not* merged - this is exactly what `RELATED_STORY` exists to do.
  **NO_ISSUE** for this event's own dispatch.
- **Net effect**: events 10 and 11 do not converge with *each other*, because each independently
  (and defensibly) attached to a different, genuinely-adjacent real story rather than to one
  another. **EXPECTED_UNCERTAINTY**, compounded by real topical density - not a clean algorithmic
  failure. The mandatory invariant ("must not silently become a wrong confident merge") holds:
  neither event reached a `SAME_STORY` outcome with anything.

## C. Kitesurf — a necessary correction to Checkpoint 3/4's own reporting

Both Kitesurf events land under the same story (`f8217dcf…`) - reconfirmed. **However, closer
inspection of that story's full detail (only available via this M13 pass) shows it is NOT a
dedicated "Kitesurf" story** - its root event is *"Cloudflare open sources a new version of
Cloudflare OS, an AI agentic workspace for enterprises..."* (Techmeme), a **different, adjacent
Cloudflare product announcement** (a company AI-agent-tooling platform, not the "Kitesurf" browser
specifically), also holding a Russian corroborating article about the same Cloudflare OS release.
Both real Kitesurf articles (`12b1736c`, `5bb6f3e3`) attached to this adjacent story as
`UNCERTAIN_MATCH` (0.44, 0.41) rather than ever creating their own dedicated "Kitesurf" story.

**Correction, stated plainly**: Checkpoint 3/4's "Kitesurf converges" claim is technically true
(both events share one story) but was previously reported without this nuance. Whether "Kitesurf"
and "Cloudflare OS" are the same real editorial announcement (Kitesurf as a named component of a
broader Cloudflare OS launch) or genuinely adjacent-but-separate products cannot be resolved from
headlines alone - a real, disclosed ambiguity, not fabricated either way.

Classification: **IDENTITY_BOOTSTRAP_GAP** (no dedicated Kitesurf-rooted story was ever created;
both events instead attached to a topically-adjacent pre-existing story) combined with
**EXPECTED_UNCERTAINTY** about the underlying real-world relationship. The *acceptance condition*
as literally worded ("Kitesurf remains fixed" = both events land under one story) still holds.

## D. GTA negative control

- **Event 1** (`15a5ff78`, preorders/sales): attached to `cdc95315…` (detail not captured this
  pass - not a diagnosed pairwise entry, no earlier sibling existed to compare against).
- **Event 5** (`3635f3ce`, Netflix marketing remark): attached to `ffce75dd…` ("The first GTA 6
  gameplay reveal will debut on Netflix later this month...", PC Gamer) - a real, genuinely
  GTA-6-and-Netflix-adjacent article, plausibly a defensible (if not certain) match, **not** a
  match with its own calibration sibling.
- **Net effect**: the two calibration events land on two different stories
  (`all_events_landed_under_same_story_id: false`) - the mandatory requirement ("preorders story
  and Netflix-marketing story must never merge") holds cleanly. **NO_ISSUE** for the negative
  control's own pass/fail criterion; the specific adjacent story event 5 attached to is a
  reasonable real match, not confirmed wrong.

## Summary table

| Case | Event | Classification | Action this checkpoint |
|---|---|---|---|
| AI Olympiad | 4 | EXPECTED_UNCERTAINTY | None |
| AI Olympiad | 8 | **SCORING_MISS (reproducible defect, demonstrated)** | **Reported only, not fixed - out of this checkpoint's scope** |
| AI Olympiad | 14 | NO_ISSUE | None |
| Moscow | 10 | EXPECTED_UNCERTAINTY | None |
| Moscow | 11 | NO_ISSUE | None |
| Kitesurf | both | IDENTITY_BOOTSTRAP_GAP + EXPECTED_UNCERTAINTY | Correction to prior reporting only, no code change |
| GTA | both | NO_ISSUE | None |

**No algorithm change was made.** One reproducible defect (Event 8's scoring collision with a
generic-word-driven unrelated candidate) was found and is disclosed precisely, with full evidence,
for a future explicitly-authorized precision pass - consistent with "do not change the algorithm
unless a reproducible defect is demonstrated" (a defect *was* demonstrated, but fixing it was not
this checkpoint's goal, which is scoped to human suppression review and identity documentation
only).
