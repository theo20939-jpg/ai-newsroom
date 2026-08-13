# GOOGLE NEWS SIBLING EVIDENCE REUSE FIX CHECKPOINT

Implements the narrow fix identified by `docs/story_cluster_fragmentation_focused_forensic_report.md` (recommendation `READY FOR NARROW FIX`). Against committed HEAD `00618bd35db7c3da7775be2ab6c2de0d67c5ec33`. Not committed, not deployed.

## 1. Root cause recap

Both real Cluster A and Cluster B failures traced to the same structural gap: the identical 3DNews article was ingested twice — once via 3DNews's own direct RSS feed (rich excerpt, later fully acquirable) and once via a Google News RSS wrapper of the same article, whose redirect resolution structurally fails (`ACQUISITION_STATUS_REDIRECT_UNRESOLVED`, 0 characters). In both real cases, the direct-feed sibling was already fully, successfully acquired 48–62 seconds *before* the wrapper's own acquisition attempt ran — the richer evidence had already arrived and was never consulted. Story Memory itself, and downstream suppression/reply-routing, were not the primary defect (confirmed in the prior forensic report); this fix targets only the acquisition-layer gap.

## 2. Exact sibling-match criteria

Implemented in `services/article_acquisition.py::_find_acquisition_failure_sibling()`, called only after this event's own `acquire_article()` call has already returned `ACQUISITION_STATUS_REDIRECT_UNRESOLVED` — never runs speculatively, never precedes or replaces a real fetch attempt.

A candidate `NewsEventArticleAcquisition` row is reused only when **all** of the following hold (no single signal is sufficient alone, matching the required safety invariant):

1. **`published_at` proximity**: the candidate's own `NewsEvent.published_at` is within `_SIBLING_REUSE_PUBLISHED_AT_TOLERANCE_SECONDS` (5 seconds) of this event's own `published_at`. This is the decisive safety signal — both real cases share an *identical* `published_at` to the second; a coincidental identical-second match between two genuinely different articles is not realistic, unlike topic/category/entity similarity.
2. **Confident title match** (`_titles_confidently_match()`), one of:
   - Exact match after stripping a trailing Google News `" - {Publisher}"` suffix (the real Cluster A pattern — `"...традиционные ценности - 3DNews"` vs. the direct feed's bare `"...традиционные ценности"`).
   - One title (after the same suffix-stripping) is a genuine, substantial prefix of the other, at least `_SIBLING_REUSE_MIN_TITLE_LEN` (20) characters (the real Cluster B pattern — the wrapper's own RSS entry truncated the headline mid-sentence).
   - Deliberately **not** a fuzzy/loose similarity score of any kind.
3. **Trusted sibling tier**: the candidate's own `effective_completeness_status` is in `{FULL_TEXT, PARTIAL_TEXT}` — never promotes another weak or failed acquisition.
4. **Not itself a reuse row**, and carries real text — the same one-hop invariant `_find_reuse_candidate()` (the existing canonical-URL reuse path) already enforces.
5. **Within `article_acquisition_reuse_window_hours`** — reuses the existing staleness bound, introduces no new one.
6. **A different `NewsEvent`** — never matches itself.

## 3. Implementation

`services/article_acquisition.py` only — three additions, no existing function signature changed:

- `_SIBLING_REUSE_TRUSTED_STATUSES`, `_SIBLING_REUSE_PUBLISHED_AT_TOLERANCE_SECONDS`, `_SIBLING_REUSE_MIN_TITLE_LEN`, `_GOOGLE_NEWS_TITLE_SUFFIX_RE` — new module constants. `_SIBLING_REUSE_TRUSTED_STATUSES` is a deliberate literal value-copy of `services/evidence_package.py::TRUSTED_FULL_ARTICLE_STATUSES`, not an import — `evidence_package.py` itself imports from `article_acquisition.py`, so importing back would be circular; confirmed by direct `python -c "import services.article_acquisition"` after the change.
- `_strip_google_news_title_suffix()`, `_titles_confidently_match()` — pure helper functions.
- `_find_acquisition_failure_sibling()` — the async lookup, structurally parallel to the existing `_find_reuse_candidate()`.
- `get_or_acquire()` — one new branch: after `outcome = await acquire_article(...)`, if `outcome.status == ACQUISITION_STATUS_REDIRECT_UNRESOLVED`, call the new sibling lookup; on a match, construct the acquisition row **exactly** as the existing canonical-URL reuse path already does (`reused_from_news_event_id`, copied `canonical_url`/`acquisition_status`/`effective_completeness_status`/`cleaning_version`) — the same, existing `reused_from_news_event_id` pattern, per instruction, no parallel cache/reuse model introduced. On no match, falls through to the unchanged existing fallback (the thin/empty row, byte-identical to pre-fix behavior).

`get_effective_acquisition()` and `build_evidence_package()` — **both untouched**. They already follow `reused_from_news_event_id` one hop to the real text; this fix's new reuse rows are structurally indistinguishable from the existing canonical-URL reuse rows to every downstream consumer, so no downstream code needed to change for Research/Copywriting to see the reused rich text.

Story Memory (`services/story_memory.py`) — **untouched**, not imported by this change.

## 4. Real A/B case before/after

| | Before this fix | After this fix (verified via `tests/test_article_acquisition_sibling_reuse.py`, real titles/timing) |
|---|---|---|
| Cluster A (`ru_ai_values_wrapper_sibling_reuse`) | Wrapper event → `REDIRECT_UNRESOLVED`, 0 chars, Research sees only the bare RSS title | Wrapper event → `reused_from_news_event_id` = the direct-3DNews sibling, `effective_completeness_status = FULL_TEXT`; `build_evidence_package()` returns `extraction_method = full_article_acquisition` with the sibling's real text (confirmed: contains "Путин", not present in the thin wrapper excerpt) |
| Cluster B (`twitch_amazon_wrapper_sibling_reuse`) | Same shape, `REDIRECT_UNRESOLVED`, 0 chars | Same shape, reused via the **prefix-containment** branch (not suffix-stripping — the wrapper's title was RSS-truncated, not suffixed), `FULL_TEXT` |

Both confirmed via the exact real titles/URLs/timing from the forensic report, not synthetic approximations.

## 5. False-reuse safety controls

Every "must NOT reuse" scenario from the required test matrix is enforced and tested:

- **Loosely related sibling** (same category/topic, different article) → `_titles_confidently_match()` returns `False`, no reuse (`test_loosely_related_sibling_never_reused`, `test_titles_confidently_match_rejects_same_category_different_event`).
- **Same publisher, similar title, materially different article** → the shared-prefix/suffix check fails on the actual differing content, no reuse (`test_titles_confidently_match_rejects_same_publisher_similar_but_distinct_titles`).
- **Short/generic title fragment** → rejected by `_SIBLING_REUSE_MIN_TITLE_LEN` even if technically a substring (`test_titles_confidently_match_rejects_loosely_related_short_titles`).
- **Sibling's own acquisition is itself weak/failed** → excluded by the `_SIBLING_REUSE_TRUSTED_STATUSES` filter, never promoted (`test_weak_sibling_acquisition_never_promoted`).
- **No sibling exists** → falls through unchanged to the existing safe fallback, byte-identical to pre-fix behavior (`test_no_sibling_preserves_current_safe_fallback`).
- **Sibling outside the reuse window** → not reused, matching the existing canonical-URL reuse path's own staleness behavior (`test_stale_sibling_outside_reuse_window_not_reused`).

## 6. Tests

**10/10 required scenarios covered**, all passing:

| # | Scenario | Test |
|---|---|---|
| 1 | Unresolved wrapper + rich sibling exists → reuse | `test_unresolved_wrapper_reuses_rich_sibling_via_suffix_match` |
| 2 | Rich sibling predates wrapper by ~1 minute → reuse allowed | `test_rich_sibling_predates_wrapper_by_about_one_minute_reuse_allowed` |
| 3 | Loosely related sibling → no reuse | `test_loosely_related_sibling_never_reused` + pure `test_titles_confidently_match_rejects_loosely_related_short_titles` |
| 4 | Same publisher, similar title, different article → no reuse | `test_titles_confidently_match_rejects_same_publisher_similar_but_distinct_titles` |
| 5 | No sibling → current safe fallback preserved | `test_no_sibling_preserves_current_safe_fallback` |
| 6 | Sibling acquisition itself weak/failed → not promoted | `test_weak_sibling_acquisition_never_promoted` |
| 7 | Reuse lineage persisted via `reused_from_news_event_id` | `test_reuse_lineage_persisted_via_reused_from_news_event_id` |
| 8 | Downstream evidence package sees reused rich text | `test_evidence_package_sees_reused_rich_text` |
| 9 | Research receives rich evidence, not empty wrapper | same test (`build_evidence_package()` is Research's own evidence source) |
| 10 | No duplicate paid acquisition/Research work | `test_sibling_fallback_never_triggers_a_second_fetch` (`acquire_article` call count == 1) |

Plus 8 pure unit tests for the title-matching helpers (`tests/test_article_acquisition.py`, using the exact real A1/A2/B1/B2 titles) and 1 additional reuse-window test. **Results**: `tests/test_article_acquisition.py` — 23 passed (was 15). `tests/test_article_acquisition_sibling_reuse.py` (new file) — 9 passed. Combined with `tests/test_article_acquisition_fetch.py` + `tests/test_evidence_package_degradation.py` + `tests/test_analysis_reuse.py` — **70 passed, 1 pre-existing failed** (`test_build_evidence_package_raises_when_table_missing` — confirmed, again, to fail identically in complete isolation regardless of this change, the same environment/migration-state mismatch documented in the two immediately prior phases' own checkpoints). `tests/test_story_memory.py` — **41 passed, 0 regressions** (untouched file).

## 7. Golden corpus additions

Two new cases added to `tests/fixtures/news_golden_cases.json` (category `evidence_acquisition`, `failure_class: "real_regression"`): `ru_ai_values_wrapper_sibling_reuse` and `twitch_amazon_wrapper_sibling_reuse`, using the exact real titles/URLs/timing from both clusters. A new runner branch (`tests/golden/runners.py::_run_sibling_reuse_case()`) exercises the real, unmodified `get_or_acquire()` end to end (with `acquire_article()` itself faked to deterministically return `REDIRECT_UNRESOLVED`, matching the real failure mode — no real network fetch). The required invariant — **"a known duplicate wrapper acquisition failure must not discard richer evidence already collected for the same underlying article"** — is asserted directly (`reused_from_sibling: true`, `effective_completeness_status: "FULL_TEXT"`).

`python scripts/run_news_golden_suite.py`, run twice: **`GOLDEN SUITE: 39/39 PASS`** both times (was 37; +2 new cases, 0 regressions, fully deterministic).

## 8. Remaining limitations

- **Scoped narrowly to `ACQUISITION_STATUS_REDIRECT_UNRESOLVED` only**, per instruction. `ACQUISITION_STATUS_FETCH_FAILED` (a different weak-tier status) is not covered by this fallback — a disclosed, deliberate scope boundary, not evidenced as needed by either real case this phase responds to.
- **Title-matching is still a pattern-based heuristic**, not a content-fingerprint match — calibrated against exactly the two real patterns observed (suffix-stripping, prefix-containment) plus the `published_at`-exact-match safety gate. A third real pattern not yet observed could in principle require a third branch; none is added speculatively.
- **Does not address Cluster B's own secondary finding** (the prior forensic report's §6 graph-connectivity nuance — B1 and B2 did not score confidently against *each other* directly in Story Memory, only both against other cluster members) — out of this phase's acquisition-only scope, and Story Memory was explicitly not to be touched.
- **Does not implement Option 3** from the forensic report (collector-side pre-emptive dedup) — deliberately not chosen, per that report's own risk assessment (higher false-suppression risk than this acquisition-layer fallback).
- **The one clear false positive from the earlier shadow-bake report remains un-reconstructed** — still out of scope, unrelated to this fix.

## 9. Recommendation

Ten of ten required test scenarios pass, both real regression cases are now fixed and permanently pinned in the golden corpus, all false-reuse safety controls are enforced and tested, Story Memory and delivery semantics are structurally unaffected (this fix touches only `services/article_acquisition.py`), and the full validation suite (targeted tests, golden suite ×2, Ruff, mypy, architecture validation) is clean.

### `READY TO COMMIT`

Not committed automatically. Not deployed. Story Memory enforce not enabled. Video and source-pack work not resumed. STOP after this checkpoint.
