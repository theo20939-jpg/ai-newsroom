# NEWS STABILITY FIX CHECKPOINT

Status: **narrow stability-fix phase complete, validated. Not committed. Not deployed. No canary
started.** Implements the 8 evidence-backed fixes authorized in response to
`docs/news_output_stability_forensic_report.md`. Every fix is scoped exactly as labeled in that
report's own §13 remediation taxonomy (`[WIRING ONLY]`/`[NARROW FIX]`/`[PROMPT VERSION]`) —
nothing broader was implemented, and two places where deeper investigation revealed the narrow fix
alone is *not* fully sufficient are disclosed honestly in §13/§9 below rather than papered over.

## 1. Exact files changed

**Production code:**
- `services/content_draft_service.py` — Case C wiring, Case D wiring
- `services/article_acquisition.py` — Case A, Case H
- `services/editorial_treatment.py` — Case A (weak-evidence status set)
- `capabilities/copywriting_capability.py` — Case F (version whitelist fix)
- `services/content_quality_gates.py` — Case D (new gate)
- `services/story_memory.py` — CD Projekt duplicate-story fix
- `worker/content_cycle.py` — Case E (URL-origin dedup signal)
- `services/image_persistence.py` — Case E (`final_url` field exposed)
- `services/telegram_routing.py` — Case G (link-preview suppression)
- `scripts/_phase23_1o_2h_combined_news_canary.py`, `scripts/_phase23_1p_2h_canary.py`,
  `scripts/_phase23_1q_2h_canary.py`, `scripts/_phase23_1q_video_shadow_canary.py` — Case F
  (v8.6 activation). `scripts/_phase23_1n_golden_replay.py` deliberately **untouched** (named,
  version-specific historical replay tooling, not a live-canary entry point).

**New test files:** `tests/test_content_draft_update_repetition_check.py`,
`tests/test_content_draft_quote_self_containment_integration.py`.

**Modified test files:** `tests/test_article_acquisition.py`,
`tests/test_article_acquisition_fetch.py`, `tests/test_editorial_treatment.py`,
`tests/test_story_memory.py`, `tests/test_copywriting_v6_context_seam.py`,
`tests/test_content_quality_gates.py`, `tests/test_router_media_integration.py`,
`tests/test_telegram_editorial_routing.py`.

## 2. Fix mapped to each forensic case

| Case | Fix | Label |
|---|---|---|
| A — headline/evidence mismatch | Google News redirect-shell detection → `REDIRECT_UNRESOLVED`, added to weak-evidence set | `[NARROW FIX]` |
| B — insufficient evidence | Not implemented — forensic report's own explicit finding (§13 item 9) that this is a genuine, undecided product-policy question, not a bug | `[POLICY / PRODUCT DECISION]`, not implemented |
| C — UPDATE repeats root | `check_update_not_repeating_root()` wired with real `is_update`/`root_body` | `[WIRING ONLY]` |
| D — bad quote | New `check_quote_is_self_contained()` gate, enforced at the same fail-closed point `verify_quote()` already uses | `[NEW CAPABILITY]` |
| E — duplicate media | New same-normalized-origin URL signal, combined with a narrower, evidence-calibrated same-origin Hamming threshold | `[NARROW FIX]` |
| F — uncertainty filler | v8.6 activated on every live-canary entry point; a real, blocking version-whitelist gap in `copywriting_capability.py` found and fixed as part of activation | `[PROMPT VERSION]` + `[NARROW FIX]` |
| G — link preview | `link_preview_options=LinkPreviewOptions(is_disabled=True)` on the one `bot.send_message()` call | `[NARROW FIX]` |
| H — low-content article | Interstitial/consent-wall line-stripping before status classification | `[NARROW FIX]` |
| CD Projekt duplicate story (§10 bonus finding) | `_strip_leading_determiner()` entity-extraction fix | `[NARROW FIX]`, partial — see §9 |

## 3. Before/after behavior for Cases A–H

**Case A:** Before — a Google News redirect-shell URL's own incidental page text (11 chars,
"Google News") was silently classified `HEADLINE_ONLY` and correctly-but-coincidentally treated as
weak evidence. After — `is_google_news_redirect_host()` detects the shell; two general resolution
signals (off-host canonical link, meta-refresh) are tried first; when neither resolves, the
acquisition is honestly classified `REDIRECT_UNRESOLVED` (now added to `_WEAK_COMPLETENESS_
STATUSES`) instead of relying on incidental-text-length coincidence. 23/23 real `HEADLINE_ONLY`
rows in the forensic dataset were Google News sources — a clean, systemic target.

**Case B:** No code change. Confirmed the forensic report's own finding still holds: acquisition
worked, Research was accurate, Copywriting followed the hedge instruction — the gap is that
`evidence_completeness` measures fetch success, not fact density, and deciding whether that should
gate publication is a genuine product question, not a bug this phase should silently resolve.

**Case C:** Before — `is_story_update`/root text were computed *after*
`evaluate_content_quality_gates()` ran, so `check_update_not_repeating_root()` always received
`is_update=False` and could never fire, for any draft, ever. After — the story-link lookup moved
earlier; a real update now receives `is_update=True` and (when a root was actually SENT to
Telegram) the real root body, and a rewritten-root-plus-tiny-delta draft now visibly fails the
gate (logged, matching this repo's existing non-blocking quality-gate policy — see §9's own note
on why this is not newly made blocking).

**Case D:** Before — `verify_quote()` (verbatim-match) and `check_quote_has_attribution()`
(non-empty/non-generic speaker) were the only two quote checks; the real Discord/BBC fragment
("thoughtfully reviewing") passed both. After — `check_quote_is_self_contained()` is a third,
independent, required condition at the exact same fail-closed drop point — the real fragment now
fails (word-count floor + no recognizable subject/finite-verb token) and the draft renders
normally with no quote; a genuinely short-but-complete quote ("We take this seriously.") still
passes.

**Case E:** Before — the Honor Robot Phone UPDATE's two "duplicate" images (real Hamming distance
9, above the existing `<=4` threshold) were both selected into the same album, because they were
served from different hosts (`9to5google.com` directly vs. `i0.wp.com` via WordPress/Jetpack's
Photon CDN proxy) with no shared hash-based signal strong enough to catch them. After — normalized
image-origin matching (Photon-proxy-aware) plus a narrower, real-evidence-calibrated same-origin
Hamming threshold (`10`, not the global `4`) now excludes it; a real Guardian pair sharing the same
base file but a genuinely different crop (measured distance 36) is confirmed to remain unaffected.

**Case F:** Before — every one of the 32 real deliveries in the forensic dataset, and every
canary script that would generate the *next* one, was pinned to v8.5; v8.6 had never been
exercised live. After — the four live-canary entry points now select v8.6; a real, independently
discovered blocking gap (v8.6 missing from `copywriting_capability.py`'s version-gated
EDITORIAL PLAN/PRIOR COVERAGE context-injection tuple — would have silently degraded v8.6's
context richness the moment it went live) was found and fixed as part of this activation, not
left for the next live run to discover.

**Case G:** Before — every real text-only NEWS send let Telegram auto-expand the first link found
in the message body, which was always the NINJA PULSE footer link, into a large NINJA VPN preview
card. After — `link_preview_options=LinkPreviewOptions(is_disabled=True)` on the one
`bot.send_message()` call; the link itself remains clickable. Photo/media-group sends are
confirmed structurally unaffected (Telegram never generates link previews for captions at all,
with or without this parameter).

**Case H:** Before — a LinkedIn Pulse page whose extracted text was ~92% real, substantive article
prose (confirmed by direct inspection of the real 20,000-character extraction — the forensic
report's own characterization as "boilerplate" was directly checked and found imprecise; see §9)
mixed with ~8% cookie-consent/sign-in-wall chrome near the top classified `FULL_TEXT`. After — a
new `estimate_substantive_char_count()` strips recognized interstitial-line patterns
(cookie-consent, sign-in-wall, access-denied, challenge-page, navigation-shell — a closed,
hand-curated, non-blacklist lexicon) before status classification; a genuinely gated page (little
to no real content beyond the wall) now classifies correctly thin; a real article with only
incidental cookie-banner chrome remains `FULL_TEXT`, unaffected.

**CD Projekt duplicate story:** Before — `_extract_entities()`'s capitalized-run regex captured
"The Witcher" as one glued token when a headline's own phrasing happened to capitalize "The",
while the same entity appeared bare ("Witcher") in a different headline about the identical
layoffs event — `entity_overlap = 0.0`, both events classified `new_story`, completely
disconnected. After — `_strip_leading_determiner()` normalizes both to `"witcher"`; measured
`entity_overlap` improves to `0.333` on the real pair. See §9 for the honest, measured limit of
this fix.

## 4. Effective prompt version for next validation

`copywriting_prompt_version = "8.6"` on all four live-canary entry points
(`_phase23_1o_2h_combined_news_canary.py`, `_phase23_1p_2h_canary.py`, `_phase23_1q_2h_canary.py`,
`_phase23_1q_video_shadow_canary.py`). `v8.5.yaml`/every earlier version file is unmodified
(prompt-immutability preserved). `_phase23_1n_golden_replay.py` (a named, version-specific
historical replay/regression tool, not a live entry point) remains pinned to v8.5 by design —
untouched. `core/config.py`'s own code default remains `"4"` (unrelated to this fix — no canary
run has ever relied on the code default).

## 5. Google News acquisition regression result

`pytest tests/test_article_acquisition.py tests/test_article_acquisition_fetch.py
tests/test_article_acquisition_integration.py` → **30 passed, 7 skipped** (pre-existing,
unrelated skip markers). Includes 6 new real-local-HTTP-server tests: shell-with-no-signal →
`REDIRECT_UNRESOLVED`; shell-with-off-host-canonical-link → resolves the real article
(`FULL_TEXT`); shell-with-meta-refresh → resolves; canonical pointing to *another* Google News
host → never followed, stays `REDIRECT_UNRESOLVED`; bounded to a single extra hop (no infinite
loop). Plus 2 pure unit tests for `is_google_news_redirect_host()` (host-suffix-safe, rejects a
lookalike domain the same way `video_discovery.py`'s own YouTube-lookalike test does). Plus 2 new
`tests/test_editorial_treatment.py` tests proving `REDIRECT_UNRESOLVED` is now treated as weak
evidence, mirroring the real Case A signal shape (hedged, non-keyword-matching recommendation →
downgrades away from STANDARD/MAJOR, exactly like `HEADLINE_ONLY` already did).

## 6. Consent/interstitial detection result

4 new pure tests in `tests/test_article_acquisition.py` (pure-interstitial page → near-zero
substantive count; real-shaped article-with-cookie-banner → count ≈ unaffected; empty text → 0;
end-to-end status flips to `HEADLINE_ONLY` only for the pure-shell case) plus 2 new real-server
tests in `tests/test_article_acquisition_fetch.py` (a genuinely-gated hard-paywall shape →
never `FULL_TEXT`; a real article with only incidental cookie-banner chrome → stays `FULL_TEXT`).
**Honest disclosure:** re-running this exact detector against the real BAD_GARBAGE.c/LinkedIn
acquisition text found only 11 of 401 extracted lines (≈400 of 20,000 characters) matched the
interstitial lexicon — this specific real draft would still classify `FULL_TEXT` even with this
fix, since it was never actually a pure interstitial (see §9's own deeper finding on what the real
root cause for that specific draft actually was).

## 7. UPDATE repetition-check wiring result

`pytest tests/test_content_draft_update_repetition_check.py` → **4 passed**, 0 errors (real
Postgres, `db_session` SAVEPOINT fixture, no teardown-FK noise). Covers: genuine update with new
material passes; rewritten-root-plus-tiny-delta fails (observable via the existing
`content_quality_gate_failures` log line); `NEW_STORY` unaffected regardless of text similarity;
update with no successfully-delivered root follows the existing safe default (root_body stays
`None`, check trivially passes, per `check_update_not_repeating_root()`'s own pre-existing
design — never invented a new, stricter policy for this case).

## 8. CD Projekt duplicate regression result

`pytest tests/test_story_memory.py` → **33 passed** (26 pre-existing + 7 new). Covers: leading
"The" stripped from a captured multi-word entity; bare and "The"-prefixed mentions of the same
entity now normalize identically; a standalone determiner (Checkpoint 6's own pre-existing case)
remains fully excluded, unaffected; the real CD Projekt pair's `entity_overlap` measurably
improves (0.0 → 0.333, both real headline texts, both real event categories); an unrelated
same-company-different-event pair stays well below the confident-match threshold; a genuine,
easily-matched update (shares both a leading-"The" entity and real title-wording overlap) still
clears `_HIGH_THRESHOLD`. **Honest disclosure — this fix does NOT achieve full merge for the real
CD Projekt pair itself**, see §9.

## 9. Quote completeness result

`pytest tests/test_content_quality_gates.py tests/test_content_draft_quote_self_containment_integration.py`
→ **36 passed**, 0 unexpected errors. Pure-function coverage: the real Discord fragment and its
real Russian `translated_text` both fail; a short-but-grammatically-complete quote and a full
meaningful quote both pass; no-quote-at-all trivially passes. Integration coverage (real Postgres,
full `ContentDraftService.create_from_result()` path): a self-contained verbatim quote persists; the
real fragment shape is dropped and the draft still renders normally with no quote; a self-contained
quote with a missing speaker still persists (proves this fix is orthogonal to attribution — the
existing, unrelated policy for missing speakers is unaffected).

## Honest disclosures (deeper findings this phase's own investigation surfaced)

**Case H's real root cause, found during implementation, is architectural, not a classification
bug:** the real BAD_GARBAGE.c draft's Research step explicitly reported *"the main article text is
absent"* even though the acquisition layer had, in fact, fetched ~18,000 characters of genuine
article prose. Tracing this precisely: `article_acquisition_mode=shadow` in the real `.env` (not
`enforce`) — under `shadow`, `content_draft_service.py` never upgrades `source_content` beyond the
original RSS excerpt (a one-line "Comments" link, in this case), while `editorial_treatment.py`'s
SKIP gate separately, and by original design, *does* consult the shadow-populated acquisition
status. This means the gate and the actual generation input are two independent consumers of the
same acquisition attempt — a real, disclosed decoupling, not fixed in this phase (fixing it would
mean either changing `article_acquisition_mode`'s effective value more broadly, or making
`editorial_treatment.py` aware of whether the fetched text was actually supplied to Research/
Copywriting — both bigger changes than "add an interstitial detector," and explicitly outside
"Do NOT redesign architecture"). **Flagged here as a [POLICY / PRODUCT DECISION] for a future
phase**, not silently left unmentioned.

**The CD Projekt fix is real, evidenced, and measurably improves matching — but does not, on its
own, achieve "no second independent root" for the specific pair the report cited.** Precise
measurement: `entity_overlap` improves 0.0 → 0.333 (real data), but `title_overlap` between these
two independently-worded real headlines is genuinely low (0.09), so `combined = 0.286` — still
below `_LOW_THRESHOLD` (0.35), let alone `_HIGH_THRESHOLD` (0.65) required for a confident
`STORY_UPDATE`/`SUPPORTING_SOURCE` merge. Even reaching the `RELATED_STORY` band would not have
changed the outcome — `services/triage_orchestrator.py`'s own Phase 20 M11.1 design deliberately
makes `RELATED_STORY` **always** create its own separate Story (a documented, intentional
decision from an earlier phase, not a bug). Achieving a full merge for headline pairs this
differently worded would require either loosening `_LOW_THRESHOLD`/`_HIGH_THRESHOLD` or reweighting
`score_candidate()`'s entity/title balance — explicitly forbidden this phase without broader
calibration evidence than one real pair provides. **Flagged here as a [POLICY / PRODUCT DECISION]**:
is `RELATED_STORY`-with-no-merge an acceptable outcome for same-event-different-wording pairs, or
does this warrant a calibration pass against a larger real sample?

## 10. Honor resize-duplicate result

`pytest tests/test_router_media_integration.py` (relevant subset) → all new tests pass (confirmed
individually; the full 1533-line file run separately due to size — see §12). Real evidence
gathered before implementation: 4 real same-normalized-origin genuine-duplicate pairs in the
dataset measured Hamming distances 1, 2, 4, 9; the real same-base-file-but-different-crop pairs
(Guardian) measured 22–36 — a wide, clean gap. `_SAME_ORIGIN_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE =
10` sits just above the highest confirmed duplicate and well below the lowest confirmed distinct
crop. The global `_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE = 4` (imported from `services/
media_ranking.py`) is completely unchanged, including for cross-story reuse
(`find_story_reused_image_signatures()`/`is_perceptually_reused()`, never touched).

## 11. Link-preview result

`pytest tests/test_telegram_editorial_routing.py` → **25 passed** (18 pre-existing + 7 new,
including updating the one pre-existing exact-kwargs assertion that would otherwise have broken).
Covers: text-only sends now disable the preview, for every destination, not only NEWS; dry-run
never calls Telegram at all; `send_photo_to_editorial_destination()`/`send_media_group_to_
editorial_destination()` confirmed structurally to never receive a `link_preview_options` kwarg at
all (there is nothing to disable there); UPDATE reply-threading (`reply_to_message_id`) and the
source-button `reply_markup` are both confirmed independent of and unaffected by this fix.

## 12. Tests / Ruff / mypy / architecture results

- `python scripts/validate_architecture.py` → **clean, 0 forbidden-dependency violations.**
- `ruff check` across every production file touched this phase (9 files) and every test file
  touched (13 files) → **all clean.**
- `mypy` across every production file touched this phase (9 files) → **all clean, 0 issues.**
- `mypy` on touched test files → clean, except pre-existing, unrelated gaps already present in
  those files before this phase (`test_router_media_integration.py`'s own established `test_
  source: object` typing pattern, 9 pre-existing instances; `test_telegram_editorial_routing.py`'s
  own pre-existing `RouteTarget | None` union-attr note, 5 pre-existing instances) — neither
  touched or worsened by this phase's own edits.
- Consolidated regression run — `tests/test_content_draft_update_repetition_check.py
  tests/test_article_acquisition.py tests/test_article_acquisition_fetch.py
  tests/test_article_acquisition_integration.py tests/test_editorial_treatment.py
  tests/test_story_memory.py tests/test_story_memory_integration.py
  tests/test_copywriting_v6_context_seam.py tests/test_copywriting_v86_uncertainty_fix.py
  tests/test_content_quality_gates.py tests/test_content_draft_quote_self_containment_integration.py
  tests/test_content_draft_quote_integration.py tests/test_content_draft_service.py
  tests/test_telegram_editorial_routing.py tests/test_rich_media_notifier.py` → **215 passed, 9
  skipped (pre-existing stale skip markers, unrelated), 1 failed.**
- The 1 failure (`test_content_draft_is_durable_to_a_genuinely_independent_connection`) is
  confirmed pre-existing and unrelated: fails identically in isolation on completely unmodified
  code, via a different table (`content_draft_editorial_plans`) than anything this phase touched.
- `tests/test_router_media_integration.py` (full file, run separately for its size) → **38
  passed, 31 errors** — every error is the same, already-documented teardown-only FK cleanup
  pattern (confirmed via isolated re-runs throughout this project's history), not a real failure.
- `tests/test_video_discovery.py tests/test_video_discovery_integration.py
  tests/test_video_discovery_persistence.py` → **57 passed**, confirming the Case A/H acquisition
  changes do not disturb the (still-paused, still-unwired) video discovery pipeline downstream of
  `acquire_article()`.
- `tests/test_story_identity_invariant.py tests/test_phase20_m1_harness_fixes.py
  tests/test_editorial_content_type.py` → **40 passed**, confirming the Story Memory entity fix
  does not disturb the broader Story Identity/Delta Engine test surface.
- **Newly discovered during this sweep, pre-existing, unrelated:** `tests/test_content_worker_
  cycle.py::test_run_content_cycle_dry_run_never_calls_bot_send_message` and `::test_run_content_
  cycle_sequential_no_gather_and_notifies_after_draft_creation` both fail — root-caused precisely:
  both hardcode an assumption (`content_generation_dry_run is True` /
  `editorial_delivery_mode == "legacy"`) that no longer matches this real dev environment's own
  `.env` (`CONTENT_GENERATION_DRY_RUN=false`, delivery mode `router`, both set in earlier phases of
  this same extended session for live-canary work). Neither test file was touched by this phase;
  neither setting is referenced by any of the 8 fixes. Not repaired, per the explicit "do not spend
  time on unrelated pre-existing environment failures" instruction — reported here as newly found.

## 13. Remaining unresolved correctness issues

- **Case B** — no fact-density/verifiability signal exists independent of fetch-completeness;
  whether hedged, thin-but-honest posts belong in NEWS at all remains an open product question.
- **Case H's true root cause** — the `article_acquisition_mode=shadow` vs. `editorial_treatment.py`'s
  own shadow-aware evidence gate decoupling (§9) — is not fixed by the interstitial detector alone.
- **CD Projekt** — the entity-extraction fix is real and measured but insufficient alone to merge
  differently-worded real-world headline pairs about the same event (§9); a threshold/weighting
  recalibration (out of this phase's scope) would be required, or `RELATED_STORY`-without-merge
  needs an explicit product decision on whether it's an acceptable outcome.
- **`HardDeliveryCap` does not wrap `bot.send_media_group()`** — a pre-existing, previously
  disclosed (media-quality corrective phase) safety gap, not addressed here, out of scope.
- **`_is_negative_recommendation()` remains keyword-only** — the forensic report's own §13 item 5,
  explicitly labeled `[POLICY / PRODUCT DECISION]`, not implemented per that report's own
  recommendation not to decide it unilaterally.
- **`tests/test_content_worker_cycle.py`'s two newly-observed pre-existing failures** (§12) — a
  genuine environment/test-assumption drift, worth a future narrow fix (parametrize or monkeypatch
  the two settings those tests depend on) but out of this phase's own scope.
- Two stale `pytest.mark.skip` markers (`tests/test_content_draft_story_link_integration.py`,
  `tests/test_content_draft_quote_integration.py`) claim migrations that are, in fact, already
  applied in this environment (confirmed via direct table-existence checks during this phase) —
  noted, not fixed, to stay narrowly scoped; new coverage for the same functionality was added in
  fresh files instead so this phase's own fixes are genuinely exercised.

## 14. Proposed acceptance-canary configuration

Not started this phase, per explicit instruction. For the next authorized run:
- `copywriting_prompt_version="8.6"` (already wired into every live-canary script — no further
  change needed to activate it).
- Same established safety controls as every prior canary this session (`HardDeliveryCap`,
  cost cap, max-analyzed cap, destination-route assertion, in-process-only settings overrides with
  restore-on-exit).
- Recommend a bounded window sufficient to observe: at least a few real Google-News-sourced events
  (to confirm `REDIRECT_UNRESOLVED` fires correctly and SKIP/BRIEF gating responds), at least one
  multi-image event (to confirm the Photon-CDN dedup signal holds up against fresh real-world
  URLs, not just the 4 already-audited historical examples), and enough volume to sample the new
  v8.6 filler-ending rate against this report's own 31% TEXT_QUALITY_FAILURE baseline.
- Recommend a follow-up forensic-style audit (lighter-weight than the full original report) of
  that run's own real output, specifically checking: filler-ending rate under v8.6, any new
  `REDIRECT_UNRESOLVED` events reaching the treatment gate, any dropped quotes (via the
  `quote_failed_verification_dropped` log line, now firing for two independent reasons instead of
  one), and whether any genuinely-duplicate image pair still slips past the recalibrated threshold.

Nothing was committed. Nothing was deployed. No canary was started. Stopping here per explicit
instruction.
