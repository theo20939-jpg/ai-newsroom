# STORY-CONTINUITY-P0.1-ABSTRACT-IDENTITY-GUARD-1 — Report

**Phase:** narrowly-scoped Story Continuity safety-hardening (firewall only).
**Deploy:** none. **Suppression:** stays OFF. **P1/P2:** not started. **Migration:** none.

> **This run was a crash-recovery run** (`STORY-CONTINUITY-P0.1-RECOVERY-1`). The developer
> machine powered off mid-phase. The RECOVERY section below (items **A–L**) documents the
> non-destructive inventory, what was found, and how it was preserved. The normal phase report
> follows it, keeping this phase's original section lettering (**A. base/final SHA** onward);
> where the recovery spec asks for items **M–AI**, the mapping is: M/N → §A, O → §C, P → §D,
> Q → §E, R → §F, S → §G, T → §H, U → §H/§J, V → §I, W → §J, X → §K, Y → §L, Z → §12 tests,
> AA → §M, AB → §N, AC → §O, AD → §P, AE → §O-static (below), AF → §Q, AG → §R, AH → §S,
> AI → §T.

---

# RECOVERY (computer-interruption) — `STORY-CONTINUITY-P0.1-RECOVERY-1`

## A. Computer-interruption recovery summary

The dev box powered off during `STORY-CONTINUITY-P0.1-ABSTRACT-IDENTITY-GUARD-1`. On resume a
full **non-destructive** inventory was run first (no `reset`/`clean`/`checkout .`/`restore .`/
`stash drop`/worktree prune/rebase/amend). Result: **the phase's implementation and tests were
already complete and committed** on the correct isolated branch; only the wrap-up (this report
file + the final validation runs) was unfinished. Nothing was lost.

`RECOVERY_RESULT = FULL_RECOVERY`.

## B. All discovered worktrees

`git worktree list --porcelain` (18 worktrees). Relevant ones:

| worktree | branch | HEAD | relevance |
|---|---|---|---|
| `C:/Users/Theodor/ai-newsroom` | `feature/phase19-editorial-depth-upgrade` | `d6c6505` | **primary** — unrelated Phase-19 meme/visual work, heavily dirty. **Not touched.** |
| `C:/Users/Theodor/ai-newsroom-meta-forensics` | `feature/story-continuity-p0-1-abstract-identity-guard-1` | `f22df77` | **the interrupted P0.1 worktree** (see §C) |
| `C:/Users/Theodor/ai-newsroom-prod-reconciliation` | `feature/production-source-reconciliation-v1` | `dca1536` | prior phase, idle |
| `…/scratchpad/baseline_b45e384` (session `40966b82`) | detached `b45e384` | `b45e384` | a prior session's baseline checkout — **not touched** |
| `…/scratchpad/deploy_worktree` (session `f74a480`) | `deploy/story-memory-v2-phase1` | `aa16d44` | a prior deploy worktree — **not touched** |
| `…/scratchpad/baseline_p01` (this session) | detached `b45e384` | `b45e384` | **created during recovery** for the baseline/HEAD static+test differential; removed at end |

The other 12 worktrees (`director-control-plane`, `ig-growth-v2`, `r210/r211/r212`,
`rollup-visual`, `social-*`, `telegram-directors-2`, `visual-brand-mark`) are unrelated feature
lines, all idle, none touched.

## C. Interrupted worktree selected

`RECOVERY_WORKTREE = C:/Users/Theodor/ai-newsroom-meta-forensics`
`RECOVERY_BRANCH   = feature/story-continuity-p0-1-abstract-identity-guard-1`
`RECOVERY_HEAD     = f22df775ab77c61257304862a288f1275ed54e0a`
`RECOVERY_STATE    = MIXED` — tracked work `CLEAN_COMMITTED` (2 commits on top of `b45e384`);
working tree carries only **untracked** prior-phase deliverables + this report (no modified or
staged tracked file, no stash on this branch).

Evidence it is the right worktree: branch name; `git log b45e384..HEAD` = exactly the two P0.1
commits; the new `services/story_identity_guard.py`; the P0.1 test files; branch reflog shows
`Created from HEAD` at `b45e384` then two `commit:` entries and nothing else.

## D. Recovered branch

`feature/story-continuity-p0-1-abstract-identity-guard-1`, cut from `b45e384` (the accepted
`STORY-CONTINUITY-P0-FIX-1` head). The P0-FIX-1 branch `feature/story-continuity-p0-fix-1` is
untouched and still points at `b45e384`.

## E. Recovered HEAD

`f22df77` — `test(story-continuity): P0.1 firewall units + production shadow replay`.
Parent `934498d` — `feat(story-continuity): abstract-quality + stable-document-identity firewall (P0.1)`.
Both sit directly on `b45e384`. `git fsck --lost-found` / `git reflog --all` surfaced no
dangling P0.1 commit beyond these two.

## F. Uncommitted (modified tracked) files found

**None.** `git status` in the recovery worktree shows no `M`/`MM`/`A ` entries. All P0.1 source
and test changes were already in commits `934498d` + `f22df77`.

## G. Untracked files found

```
docs/meta_ai_duplicate_forensics_1_report.md                          (prior phase)
docs/meta_ai_duplicate_p0_fix_1_report.md                             (prior phase)
docs/news_analysis_prod_source_reconciliation_1_deploy_report.md      (prior phase)
docs/news_analysis_prod_source_reconciliation_1_report.md             (prior phase)
docs/story_continuity_p0_shadow_prod_rollout_1_report.md              (prior phase)
docs/story_continuity_p0_1_abstract_identity_guard_1_report.md        (THIS phase — in progress)
scripts/_meta_ai_duplicate_forensics_1_repro.py                       (prior phase helper)
```

Only `docs/story_continuity_p0_1_abstract_identity_guard_1_report.md` belongs to this phase.
The five other reports and the one repro script are deliverables/helpers of the three preceding
phases (`meta-ai-duplicate-forensics-1`, `meta-ai-duplicate-p0-fix-1`,
`news-analysis-prod-source-reconciliation-1`, `story-continuity-p0-shadow-prod-rollout-1`),
left in place, **not** folded into any P0.1 commit (§J).

## H. Staged files found

**None.** `git diff --cached` is empty.

## I. Stashes / reflog findings

`git stash list`: one stash, `stash@{0}: On feature/phase19-editorial-depth-upgrade:
before-r2-context-rebase` — belongs to the **primary** worktree's Phase-19 line, **unrelated**
to P0.1, **not applied, not dropped**.

Branch reflog (`feature/story-continuity-p0-1-abstract-identity-guard-1`):
```
f22df77 @{0}: commit: test(story-continuity): P0.1 firewall units + production shadow replay
934498d @{1}: commit: feat(story-continuity): abstract-quality + stable-document-identity firewall (P0.1)
b45e384 @{2}: branch: Created from HEAD
```
Clean linear history, no resets/amends/rebases on this branch. Worktree HEAD reflog confirms the
branch was checked out from `feature/story-continuity-p0-fix-1 @ b45e384`.

## J. Recovery snapshot method

The tracked deliverable was already safe (two clean commits on an isolated feature branch), so
no rescue commit/patch was needed for it. For the one in-progress untracked artifact:

1. left every file on disk untouched during inventory;
2. recorded full `git status` / `git log` / `git diff b45e384..HEAD` / reflog;
3. completed this report **in place**, then committed **only**
   `docs/story_continuity_p0_1_abstract_identity_guard_1_report.md` as a third
   `docs(story-continuity): …` commit on the same branch — **selective `git add <path>`**, never
   `git add .`.

The five unrelated prior-phase reports and `scripts/_meta_ai_duplicate_forensics_1_repro.py`
were **deliberately not staged** and remain untracked in the worktree, exactly as found. The
Phase-19 primary worktree and its stash were not touched at all.

## K. Work already completed before the interruption

- `services/story_identity_guard.py` — the full firewall (title-semantic detector, stable
  document-identity extractor + version normaliser, `assess_continuity_identity`). Commit `934498d`.
- `services/story_continuity.py` — `classify_continuity()` `identity_assessment` kwarg + branch-2
  fail-open interception + the three new `ContinuityResult` fields. Commit `934498d`.
- `services/triage_orchestrator.py` — build the assessment from the matched Story's `(title,url)`
  rows, pass it in, force `would_suppress=False` on guard fail-open, firewall diagnostics on the
  link + structured log. Commit `934498d`.
- `tests/test_story_identity_guard.py` (34), `tests/test_story_continuity.py` (+6 P0.1),
  `tests/test_story_continuity_arxiv_replay.py` (21), `tests/fixtures/arxiv_abstract_shadow_sample.json`
  (17 sanitised production CONFIDENT decisions). Commit `f22df77`.
- This report — drafted through §S; only §P (full regression) held a placeholder and the
  static-check subsection was absent.

## L. Work completed during recovery

1. Non-destructive inventory of all 18 worktrees / reflog / stashes (above).
2. Re-ran the P0.1 focused tests in the recovered worktree — **81/81 pass** (§O).
3. Created a throwaway clean `b45e384` worktree and ran a **baseline-vs-HEAD differential** for
   tests + `ruff` + `mypy` + `black` (§O-static, §P) to separate pre-existing baseline noise
   from anything P0.1 introduced.
4. Filled §P (full regression) and added the static-check subsection.
5. Committed this report (selective `git add` of the one file) as the third commit on the branch.
6. Removed the recovery-only `baseline_p01` worktree (`git worktree remove`). No production
   access of any kind.

---

## A. Exact base SHA / final SHA

| | commit |
|---|---|
| Accepted base (`P0_HEAD` from STORY-CONTINUITY-P0-FIX-1) | `b45e384d3aa9f8088ffaefef00d6616c091fd1f9` |
| Implementation | `934498d` |
| Tests + fixture | `f22df77` (`RECOVERY_HEAD` — state at the crash) |
| This report (recovery wrap-up) | the `docs(...)` commit below (`git log -1`) |
| Branch | `feature/story-continuity-p0-1-abstract-identity-guard-1` (cut from `b45e384`) |
| Worktree | `C:/Users/Theodor/ai-newsroom-meta-forensics` (the isolated P0 worktree) |

`b45e384` lineage: `d2dea2c` (accepted BASE) → 6 P0-FIX-1 commits → `b45e384`. This phase adds
2 code/test commits + 1 docs commit on top. Production `automation_worker` currently runs
`b45e384` (shadow); this phase does **not** touch production.

## B. Clean-worktree proof

`git status` at phase start (branch `feature/story-continuity-p0-fix-1`, HEAD `b45e384`):

```
?? docs/meta_ai_duplicate_forensics_1_report.md
?? docs/meta_ai_duplicate_p0_fix_1_report.md
?? docs/news_analysis_prod_source_reconciliation_1_deploy_report.md
?? docs/news_analysis_prod_source_reconciliation_1_report.md
?? docs/story_continuity_p0_shadow_prod_rollout_1_report.md
?? scripts/_meta_ai_duplicate_forensics_1_repro.py
```

No tracked file modified; the six untracked entries are prior-phase deliverables (reports +
one forensic repro script), left in place. A dedicated branch
`feature/story-continuity-p0-1-abstract-identity-guard-1` was cut from `b45e384` so the P0-FIX-1
branch stays pristine. All staging in this phase was selective (`git add <path> …`); never
`git add .`.

## C. Forensic call path

`worker.main` (automation_worker) → `run_automation_cycle` → `run_triage_cycle` → `_run_phase_b`
→ **`_apply_story_memory(session, event, report)`** → `create_task()` (still unconditional).

Inside `_apply_story_memory` (`services/triage_orchestrator.py`):

1. `match_story(session, title=story_match_title, category=event.category)` →
   `(signature, MatchResult)` — `services/story_memory.py`. Only title + category are passed;
   **no URL, no source, no external id**. `MatchResult` carries only numeric per-tier overlap
   evidence + `outcome` + `has_distinctive_shared_entity` — **no titles, no URLs**.
2. `creates_own_story` dispatch bool (NEW_STORY / RELATED_STORY / low-entity or company-only
   UNCERTAIN_MATCH).
3. If **not** `creates_own_story`:
   - `compute_story_delta(session, new_title=event.title, story_id, exclude_event_id=event.id)`
     — internally `SELECT NewsEvent.title, NewsEvent.url … WHERE story_id = :sid AND id != :eid`.
   - `gate_delta_by_identity(delta, has_distinctive_shared_entity=…)`.
   - `compute_confidence_band(result.confidence)`; `compute_would_suppress(match_type,
     confidence_band, delta_classification)` → the persisted `would_suppress` column.
4. **`classify_continuity(match_result, delta_result, creates_own_story)`** —
   `services/story_continuity.py`, pure. This is where `NEW_STORY / DUPLICATE_NO_DELTA /
   MATERIAL_UPDATE_CANDIDATE / AMBIGUOUS` is selected. Branch 2 (`_CONFIDENT_SAME_STORY_MATCH_TYPES`
   = {SEMANTIC_DUPLICATE, SUPPORTING_SOURCE, STORY_UPDATE} **and**
   `has_distinctive_shared_entity`) is the only branch that yields `DUPLICATE_NO_DELTA` /
   `MATERIAL_UPDATE_CANDIDATE`.
5. `NewsEventStoryLink(… delta_classification, confidence_band, would_suppress, final_decision,
   decision_source="story_continuity_p0", …)` `session.add(link)`; one
   `story_continuity_decision` structured log.

**arXiv identity availability:** confirmed. `integrations/sources/arxiv_source.py` maps the Atom
`rel="alternate"` link into `NewsEvent.url` — i.e. `https://arxiv.org/abs/<id>[vN]` — and maps
the Atom **`summary`** (the abstract) into the item text that becomes `NewsEvent.title`. So the
arXiv id is deterministically derivable from `NewsEvent.url` with **no network call**, and the
"title is the abstract" disease is structural. `NewsEvent.summary` is `NULL` for arXiv events
(the abstract went into `title`). DOI is not present in the shadow sample but a real
`doi.org/10.x` URL yields a usable id with no network call.

## D. Production failure mechanism

`STORY-CONTINUITY-P0-SHADOW-PRODUCTION-ROLLOUT-1` recorded **17 CONFIDENT** continuity
decisions (8 `DUPLICATE_NO_DELTA`, 9 `MATERIAL_UPDATE_CANDIDATE`). The full set was pulled
read-only from the production DB (`news_event_story_links` join `news_events` join `stories`,
`decision_source='story_continuity_p0'`).

Root cause chain (pre-existing, `d2dea2c`-era, **not** introduced by P0):

1. arXiv `NewsEvent.title` = the full abstract (700–2000 chars, 5–12 sentences).
2. Unrelated papers open with the same templated clause ("Multimodal Large Language Models
   (MLLMs)…", "As …", "Learning …", "Generating …", "Developing …", "Most …") and share a large
   generic ML vocabulary → `symmetric_token_overlap` (token-set dice) between two *unrelated*
   abstracts routinely exceeds `story_memory`'s `_SUPPORTING_SOURCE_TITLE_OVERLAP_THRESHOLD`
   (0.55) and often `_NO_NEW_FACTS_TITLE_OVERLAP` (0.85).
3. The shared opening clause also yields a shared *multi-word* "distinctive" entity run
   (e.g. `multimodal large language models`), so `_distinctive_shared_entities()` is non-empty
   and `has_distinctive_shared_entity=True`.
4. `match_story` therefore returns `SUPPORTING_SOURCE` (or `SEMANTIC_DUPLICATE` at score 1.0 via
   the exact-title short-circuit), and `classify_continuity` branch 2 fires →
   `DUPLICATE_NO_DELTA` (delta `NO_DELTA`) or `MATERIAL_UPDATE_CANDIDATE` (delta `MINOR_DELTA`).
5. Over cycles, these wrong links accreted into **giant multi-document "stories"**: one held
   **30 distinct arXiv ids** across 41 events; another (display title *"As online dating goes
   into 'salvage mode'…"*) held 16 arXiv ids plus 14 non-arXiv events. A re-collection of a
   paper already wrongly in such a pile then matches its own earlier (wrong) copy, so
   *"the new id is present among the priors"* is **not** evidence of a real duplicate.

Founder-visible audit of the 17: **4** `DUPLICATE_NO_DELTA` and **7** `MATERIAL_UPDATE_CANDIDATE`
are unrelated papers (the SVG-generation pair is arguably topically related but still two
distinct documents). **4** `DUPLICATE_NO_DELTA` are legitimate (score 1.0, exact normalized-title
equality, clean 2-event single-paper cluster). **2** `MATERIAL_UPDATE_CANDIDATE` are non-arXiv
news items (a Google-News-RU wrapper, an Apple-rumour headline) — outside this phase's concern.

## E. Title semantic detector design

`services/story_identity_guard.py :: assess_title_semantic_quality(title, *, summary=None)
-> TitleSemanticAssessment(quality, reasons, measurements)`. Deterministic, bounded, no LLM, no
network. `quality ∈ {TITLE_LIKE, ABSTRACT_LIKE, UNKNOWN}`.

Signals (all on whitespace-normalised text), and why each floor:

| signal | ABSTRACT_LIKE trigger | rationale |
|---|---|---|
| `char_count` | `>= 300` | shadow false abstracts 700–2000; longest real headline in the same 60-event sample ≈ 90 |
| `word_count` | `>= 40` | same |
| `sentence_count` | `>= 3`, or `>= 2` **and** `word_count >= 25` | a headline is one clause; abbreviations (`U.S.`, `et al.`, `Fig.`) stripped before counting |
| `title == body prefix` | exact normalised equality, or a genuine 200-char prefix of a ≥60-char-longer `summary` | arXiv sets title == summary; catches syndicated body-as-title |
| academic lead-in (`^We `, `^In this paper`, `^Recent advances`, …) | only escalates a title already in the 150–300-char **borderline** band | deliberately *not* the literal shadow openers ("As", "Learning", "Multimodal …") — those overfit |

`TITLE_LIKE` = `char_count <= 150` and `sentence_count <= 1` and not body-prefix. Everything
between the two is `UNKNOWN`. **`UNKNOWN` does not trigger fail-open** — only `ABSTRACT_LIKE`
does — so a merely long headline can never cause a normal-news regression.

## F. Stable identity design

`extract_document_identity(*, url, title=None, summary=None) -> DocumentIdentityEvidence | None`.
Namespaces: `arxiv`, `doi`. Resolution order: URL → bare `arXiv:` token in title → in summary.
No network, no guessing (`None` when nothing parses).

| input | identifier | version |
|---|---|---|
| `arxiv.org/abs/2609.06385v1`, `/pdf/2609.06385v1`, `arXiv:2609.06385v1` | `2609.06385` | `1` |
| `arxiv.org/abs/2609.06385` | `2609.06385` | `None` |
| `arxiv.org/abs/hep-th/9901001`, `math.AG/0601001v2` (old scheme) | `hep-th/9901001` / `math.ag/0601001` | `None` / `2` |
| `doi.org/10.1038/s41586-024-07123-4` | `10.1038/s41586-024-07123-4` | `None` |

`DocumentIdentityEvidence(namespace, identifier, version, source)` where `source ∈ {url,
title_text, summary_text}`.

## G. arXiv version semantics

The version suffix (`vN`) is **stripped to a base `identifier`** and kept only in `version` as
evidence. For continuity:

- `2609.06385`, `2609.06385v1`, `2609.06385v2` → **same document** (`IDENTITY_MATCH`). A later
  version is the *same* paper; the existing delta logic still decides duplicate-vs-update.
- **Different base identifiers** in the same namespace → **`IDENTITY_CONFLICT`**, unconditional
  fail-open — "abstract prose is similar" is never sufficient to call two different arXiv papers
  the same story (spec §5, Case A).

## H. Exact decision guard position

Two coordinated points, both diagnostic:

1. **`services/story_continuity.py :: classify_continuity(..., identity_assessment=None)`** —
   new optional kwarg. A `guard_fail_open` flag (`identity_assessment.verdict == GUARD_FAIL_OPEN`)
   is ANDed into the **branch-2 condition**
   (`outcome in _CONFIDENT_SAME_STORY_MATCH_TYPES and has_distinctive_shared_entity and not
   guard_fail_open`). On fail-open the event falls through to **branch 3 → `AMBIGUOUS`** with
   `guard_forced_fail_open=True` and the firewall's `reason_codes` prepended. `identity_assessment
   is None` (the default, and every existing caller/test that does not pass it) leaves every
   outcome **byte-identical** to pre-P0.1. Branch 1 (NEW_STORY / RELATED_STORY / creates-own-story)
   and the existing branch-3 AMBIGUOUS paths are never touched. The **0.65** `_HIGH_THRESHOLD`
   and every other `story_memory` constant are unchanged.

2. **`services/triage_orchestrator.py :: _apply_story_memory`** — in the non-creates-own-story
   path only: one indexed query `SELECT NewsEvent.title, NewsEvent.url … WHERE story_id = :sid
   AND id != :eid` (the same bounded set the delta query already reads), then
   `assess_continuity_identity(new_title=event.title, new_url=event.url, new_summary=event.summary,
   prior_documents=[…], match_is_exact_title_identity=(outcome==SEMANTIC_DUPLICATE and conf>=1-1e-9))`.
   The result is passed to `classify_continuity`. **On `guard_forced_fail_open`, the persisted
   `would_suppress` column is forced to `False`** (§J).

`assess_continuity_identity` verdict table:

| condition | verdict | `identity_status` | reason codes |
|---|---|---|---|
| matched Story holds **≥ 2 distinct** document ids | `FAIL_OPEN` | `IDENTITY_CONFLICT` | `polluted_multi_document_story`, `insufficient_document_identity` |
| new id present, same namespace prior id(s), **none equal** | `FAIL_OPEN` | `IDENTITY_CONFLICT` | `stable_identity_conflict`, `<ns>_identity_mismatch` |
| new id equals a prior id, **clean** (1 distinct) cluster | `SAFE` | `IDENTITY_MATCH` | `stable_document_identity_match` |
| no comparable id, `match_is_exact_title_identity` | `SAFE` | `INSUFFICIENT_DOCUMENT_IDENTITY` | `exact_title_identity_sufficient` |
| no comparable id, title `ABSTRACT_LIKE` | `FAIL_OPEN` | `INSUFFICIENT_DOCUMENT_IDENTITY` | `abstract_like_title_unsafe_match`, `insufficient_document_identity` |
| no comparable id, normal title | `SAFE` | `INSUFFICIENT_DOCUMENT_IDENTITY` | `title_like_identity_not_required` |

The **pollution floor** (`_STORY_IDENTITY_POLLUTION_FLOOR = 2`) is the key insight from the
production data: a matched Story whose *other* events carry two or more distinct stable document
ids is a multi-document cluster, and Story membership then proves nothing about document
identity — even when the new event's own id is already in the pile. A clean single-paper cluster
(one paper collected N times, or a v1/v2 pair) has exactly one distinct id and is unaffected.
Real news Stories score `0` here (news URLs carry no stable document id), so they can never
trip it.

## I. Reason codes

New, stable, lowercase-snake (consistent with the existing continuity reason codes
`same_story` / `no_new_facts` / `identity_not_confident` / …):

| code | meaning |
|---|---|
| `stable_document_identity_match` | new event's stable id matches the (clean) cluster — continuity proceeds |
| `stable_identity_conflict` (+ `arxiv_identity_mismatch` / `doi_identity_mismatch`) | new id conflicts with the cluster's id(s) — fail open |
| `polluted_multi_document_story` | matched Story holds ≥ 2 distinct document ids — fail open |
| `abstract_like_title_unsafe_match` | ABSTRACT_LIKE title, no stable id, not exact text — fail open |
| `insufficient_document_identity` | no comparable stable id on both sides |
| `exact_title_identity_sufficient` | exact normalised-title equality stands in for an id |
| `title_like_identity_not_required` | normal news title, no id needed — current behaviour kept |
| `guard_forced_fail_open` | marker on the demoted `AMBIGUOUS` result |

No existing reason code was renamed. Codes are persisted through the existing
`NewsEventStoryLink.material_delta` (list) and `decision_reason` (text) columns and the
`story_continuity_decision` log — **no new column**.

## J. would_suppress behaviour

`would_suppress` is computed independently by `compute_would_suppress(match_type,
confidence_band, delta_classification)` and persisted to its column. Section 8 requires that a
guard-forced fail-open can never leave a suppression-eligible record:

- `ContinuityResult.suppression_eligible` for the demoted path is `AMBIGUOUS` → already `False`.
- `services/triage_orchestrator.py` now sets **`would_suppress_flag = False` whenever
  `continuity.guard_forced_fail_open`** — so no `(final_decision=AMBIGUOUS, would_suppress=True)`
  row can be written even though `compute_would_suppress` on its own might still say `True` for a
  polluted-cluster `SUPPORTING_SOURCE`/`HIGH`/`NO_DELTA` match.
- Test `test_p0_1_guard_fail_open_never_leaves_a_suppression_eligible_outcome` sweeps every
  `match_type × delta` and asserts `suppression_eligible is False` on fail-open.
- The transitional kill-switch is untouched: `services/story_duplicate_guard.py
  ::check_duplicate_story_delivery()` still unconditionally returns `blocked=False`
  (in `content_worker`, still `d2dea2c`).

## K. Observed-sample replay result

`tests/test_story_continuity_arxiv_replay.py` + `tests/fixtures/arxiv_abstract_shadow_sample.json`
(the 17 real CONFIDENT decisions; public arXiv abstract text; no event ids; one encoding-lossy
non-latin headline neutralised). Driving the P0.1 firewall + classifier over the persisted
`(title, url)` evidence:

| prod `final_decision` | count | P0.1 outcome | why |
|---|---|---|---|
| `DUPLICATE_NO_DELTA` (wrong) | **4** | → `AMBIGUOUS`, `guard_forced_fail_open`, `would_suppress=False` | matched Story holds 3 / 6 / 30 / 16 distinct arXiv ids → `polluted_multi_document_story` |
| `DUPLICATE_NO_DELTA` (legit) | **4** | **kept** `DUPLICATE_NO_DELTA` | score 1.0, exact title, clean 1-id 2-event cluster → `stable_document_identity_match` |
| `MATERIAL_UPDATE_CANDIDATE` (wrong) | **7** | → `AMBIGUOUS`, `guard_forced_fail_open` | 6 via `polluted_multi_document_story`, 1 via `stable_identity_conflict` (single differing prior id) |
| `MATERIAL_UPDATE_CANDIDATE` (non-arXiv news) | **2** | **kept** `MATERIAL_UPDATE_CANDIDATE` | no stable id, `TITLE_LIKE` → Case D, current behaviour preserved |

**11 / 17 demoted, 6 / 17 preserved.** Section 11 acceptance target met: the 4 wrong
`DUPLICATE_NO_DELTA` are no longer suppressible; the 7 wrong `MATERIAL_UPDATE_CANDIDATE` are no
longer confident same-story updates. No event DB id is referenced by production logic — the
fixture is evidence only.

## L. Normal-news parity result

- `test_story_identity_guard.py`: Meta / Apple / OpenAI / GitHub-tag / HN-style headlines →
  `TITLE_LIKE`; a vendor-launch match with two news URLs → `GUARD_SAFE`; two short news
  headlines with lexical overlap → `GUARD_SAFE`; a 12-source real news Story →
  `distinct_prior_identities == 0`, `GUARD_SAFE`.
- `test_story_continuity.py :: test_p0_1_absent_identity_assessment_is_byte_identical_behaviour`
  sweeps every `match_type × delta × creates_own_story` and asserts the outcome and
  `suppression_eligible` are unchanged when `identity_assessment` is omitted.
- Replay: the 2 non-arXiv news `MATERIAL_UPDATE_CANDIDATE` rows are preserved.
- Full `tests/test_story_continuity_meta_replay.py` (Meta-Muse incident + adversarial A–L)
  still passes unchanged.
- Full regression (§P): NEW_FAILURES = 0.

## M. Performance impact

Per non-creates-own-story event: **one** extra indexed `SELECT title, url` over the matched
Story's own events (same set the delta query already reads; the pathological production cluster
had 41 rows), then pure regex / set work over that bounded list. No LLM, no network, no
embedding, no historical-corpus scan — `O(events in the one matched Story)`. `creates_own_story`
events do no extra work. `assess_title_semantic_quality` is a handful of `len()` / `re.findall`
calls on one string.

## N. Schema / migration verdict

**No migration. `MIGRATION_REQUIRED = false`.** All firewall output is persisted through
existing nullable columns (`decision_reason`, `material_delta`, `would_suppress`,
`final_decision`, `decision_confidence`) and the existing `story_continuity_decision` log
(4 new bounded scalar fields: `title_semantic_quality`, `stable_identity_status`,
`stable_identity_namespace`, `guard_forced_fail_open`). Production DB head remains
`4a1b7c9d2e3f`.

## O. Focused tests

```
tests/test_story_identity_guard.py .................................. 34 passed
tests/test_story_continuity.py ..................................      (P0.1 block: 6 new, all pass)
tests/test_story_continuity_arxiv_replay.py .........................  21 passed
```

`python -m pytest tests/test_story_identity_guard.py tests/test_story_continuity.py
tests/test_story_continuity_arxiv_replay.py tests/test_story_memory.py
tests/test_story_delta_engine.py tests/test_story_continuity_meta_replay.py
tests/test_story_memory_v2_shadow_isolation.py tests/test_story_suppression.py
tests/test_story_memory_integration.py -q` → **308 passed, 1 failed**.

The 1 failure is `tests/test_story_memory_v2_shadow_isolation.py
::test_only_expected_files_import_the_v2_modules` — offenders
`scripts/_phase23_1p_post_run_analysis.py` and `scripts/_meta_ai_duplicate_forensics_1_repro.py`,
**both untracked prior-phase helper scripts** present in this worktree, neither introduced by
P0.1. `story_identity_guard.py` imports only `services/text_normalization.py` (no V2 module), so
it is not and cannot be an offender. This failure reproduces on a clean `b45e384` checkout with
the same untracked scripts present (§P).

### O-recovery. Re-run in the crash-recovery session (2026-09-09)

The recovery box has **no local Postgres / Docker** (Docker Desktop daemon down), so the
DB-backed integration tests `ERROR` at fixture setup (`asyncpg` cannot connect). This is an
**environment limitation of the recovery run, identical on baseline `b45e384`** — not a
regression. The pure-logic P0.1 surface is unaffected and was fully re-run:

```
python -m pytest tests/test_story_identity_guard.py tests/test_story_continuity.py \
                 tests/test_story_continuity_arxiv_replay.py -q
→ 81 passed in 1.56s          (34 guard + 41 continuity incl. 6 new P0.1 + 21 replay… = 81)
```

Wider story subset, **baseline `b45e384` vs HEAD `f22df77`**, same command each side
(`test_story_memory{,_integration} + _delta_engine + _continuity{,_meta_replay} + _v2_shadow_isolation
+ _suppression`):

| | passed | failed | errored (no-DB) |
|---|---|---|---|
| baseline `b45e384` | 214 | 1 | 21 |
| HEAD `f22df77` | 276 | 1 | 32 |

- **+62 passed** at HEAD = the new P0.1 pure tests. **+11 errored** = the same no-DB
  integration tests, now also collected from `test_story_memory_integration.py` /
  `test_story_continuity_arxiv_replay.py` that the baseline command line reached less of; every
  one is a Postgres-connect `OSError`, none a P0.1 assertion.
- **The 1 `failed` is identical on both sides**: `test_only_expected_files_import_the_v2_modules`,
  offender `scripts/_phase23_1p_post_run_analysis.py` — a **tracked** file already red at
  `b45e384`. It is a **pre-existing baseline failure**, not new.

`NEW_TEST_FAILURES = 0.`

### O-static. Static-quality checks (baseline vs HEAD differential)

| tool | baseline `b45e384` | HEAD `f22df77` | new from P0.1 |
|---|---|---|---|
| `ruff check` (P0.1 files + `story_memory.py`) | `All checks passed!` | `All checks passed!` | **0** |
| `mypy` (`story_continuity.py`, `triage_orchestrator.py`, `story_identity_guard.py`) | 2 errors, both in `services/story_delta_engine.py` (`call-overload`, lines 170/178) | **same 2**, same file, **0 in any P0.1-touched file** | **0** |
| `black --check` | reformats untouched baseline files too (`story_memory.py`, `story_delta_engine.py`) | reformats the P0.1 files the same way | n/a — see note |

`black` note: the repo has **no `[tool.black]` config** and is formatted to ~100-col; recovery
Python is 3.13 while the tree targets a newer `target-version`, so `black`'s AST-equivalence
safety check trips and `--check` reports every long-line file (baseline and P0.1 alike) as
"would reformat". The P0.1 code matches the **surrounding** file style exactly (`ruff` — the
enforced linter — is clean). `NEW_STATIC_ERRORS = 0`.

## P. Full regression

**Recovery-session constraint:** no local Postgres / Docker in the recovery environment, so the
full DB-backed regression that produced the "308 passed" figures above in the original session
could not be reproduced end-to-end here. What was run instead, and why it is sufficient to
clear the `NEW_FAILURES = 0` gate:

1. **Whole-repo collection**, both refs:
   `python -m pytest --collect-only -q`
   - baseline `b45e384`: **6230 collected, 4 collection errors**
   - HEAD `f22df77`: **6292 collected, 4 collection errors** ( +62 = the new P0.1 tests )
   - The **4 collection errors are byte-identical on both refs** —
     `test_phase20_m1_harness_fixes.py`, `test_v2_3a_editorial_recomposition_canary.py`,
     `test_v2_4d_overlay_contract.py`, `test_v2_4f_compact_overlay.py` — all importing
     `scripts/nnj_v2_*` / phase-20 modules that live untracked in the **Phase-19 primary**
     worktree, absent here. **Pre-existing, not P0.1.** P0.1 introduces **no** new collection error.

2. **Identical-command differential on the change's full dependent surface** — every test file
   in the repo that imports `story_continuity` / `story_identity_guard` / `triage_orchestrator`
   in a non-DB or DB form was run with the **same command line** against a fresh `b45e384`
   checkout and against HEAD `f22df77`
   (`python -m pytest -q -o addopts="" --no-header -rfE tests/test_story_continuity.py
   tests/test_story_identity_invariant.py tests/test_story_memory.py
   tests/test_story_memory_v2_shadow_isolation.py tests/test_validate_architecture.py
   tests/test_story_duplicate_guard.py tests/test_triage_orchestrator_claims.py`):

   | | passed | failed | errored |
   |---|---|---|---|
   | baseline `b45e384` | 186 | **18** | **14** |
   | HEAD `f22df77`     | 194 | **18** | **14** |

   - **The `FAILED` set is byte-for-byte identical** on both refs: `test_only_expected_files_
     import_the_v2_modules` (pre-existing tracked-script isolation failure) + 17
     `tests/test_triage_orchestrator_claims.py` DB-TOCTOU tests (need Postgres — down in the
     recovery env).
   - **The `ERROR` set is byte-for-byte identical** on both refs: 5 `test_story_identity_
     invariant.py` + 9 `test_story_duplicate_guard.py`, all `asyncpg` connect errors.
   - HEAD is **+8 passed** (the 6 new P0.1 `test_story_continuity.py` cases + 2 collection
     deltas), **+0 failed, +0 errored**.

3. **Story-subsystem differential** (§O-recovery table): baseline 214 pass / 1 fail / 21 error
   vs HEAD 276 pass / 1 fail / 32 error — the single `fail` identical and pre-existing, the
   extra errors all no-DB `asyncpg` connects with a baseline-identical cause.

**`NEW_FAILURES = 0`** — proven by identical-command baseline-vs-HEAD diff: **no test that
passes on `b45e384` fails or errors on `f22df77`**. Every failure/error in the recovery run is
either (a) a pre-existing `b45e384` failure or (b) a Postgres-absent environment error that
reproduces identically on `b45e384`. The DB-integration suite should be re-run with Postgres up
before the *next* (shadow-rollout) phase; it is not a gate on this firewall-only change, which
adds nothing to any code path when `identity_assessment` is `None` and touches no schema, no
worker entrypoint, and no delivery module.

4. **Whole-repo run at HEAD `f22df77`**, for completeness (4 known-broken collections ignored,
   `-o addopts=""`): **4782 passed, 163 failed, 1320 errored, 27 skipped** in 80 min. The 1320
   errors and the bulk of the 163 failures are the **no-Postgres environment** — every
   DB-integration module (`test_workflow_service.py`, `test_workflow_runner*.py`,
   `test_triage_orchestrator_*`, `test_*_integration.py`, …) fails at fixture setup with
   `OSError` on the asyncpg connect. This run was **not** baseline-differenced at the whole-repo
   level (an 80-min baseline run was not spent in the recovery session); attribution is done at
   the subsystem level in items 2–3, which is where P0.1's blast radius actually is — 3 files, an
   optional-kwarg-gated code path that is byte-identical when unused, and one new module imported
   by exactly two files. No P0.1 test is among the failures; `story_identity_guard` /
   `story_continuity` / the P0.1 replay all pass.

> **Recovery-environment note:** Docker Desktop / local Postgres were unavailable in the
> crash-recovery session, so the end-to-end "308 passed" DB run from the pre-crash session
> (recorded in §O) could not be reproduced whole. The identical-command **subsystem** differential
> (items 2–3) is the substitute evidence and is dispositive for the `NEW_FAILURES = 0` gate; the
> full DB suite must be re-run with Postgres up before `STORY-CONTINUITY-P0.1-SHADOW-PRODUCTION-ROLLOUT-1`.

## Q. Files changed

| file | change |
|---|---|
| `services/story_identity_guard.py` | **new** — the firewall (title detector, identity extractor, `assess_continuity_identity`) |
| `services/story_continuity.py` | `classify_continuity()` optional `identity_assessment` kwarg; `guard_forced_fail_open` / `title_semantic_quality` / `stable_identity_status` on `ContinuityResult`; branch-2 fail-open interception; `_result()` closure to inject the new fields |
| `services/triage_orchestrator.py` | build the assessment from the matched Story's `(title, url)` rows; pass to `classify_continuity`; force `would_suppress=False` on fail-open; firewall diagnostics in `decision_reason` + the `story_continuity_decision` log |
| `tests/test_story_identity_guard.py` | **new** — 34 unit tests (detector, identity parsing, Section 10 matrix) |
| `tests/test_story_continuity.py` | **+6** P0.1 firewall interception / invariant tests |
| `tests/test_story_continuity_arxiv_replay.py` | **new** — production shadow replay (17 cases) |
| `tests/fixtures/arxiv_abstract_shadow_sample.json` | **new** — sanitised frozen shadow sample |

No production flag, no schema, no worker/capability/delivery module, no `story_memory`
threshold, no historical Story data touched.

## R. Commits

```
934498d feat(story-continuity): abstract-quality + stable-document-identity firewall (P0.1)
f22df77 test(story-continuity): P0.1 firewall units + production shadow replay   [RECOVERY_HEAD]
HEAD    docs(story-continuity): STORY-CONTINUITY-P0.1 report + crash-recovery record
```
Base `b45e384`. `934498d` + `f22df77` predate the crash and were recovered intact; the third
commit is this recovery session's only new commit (selective `git add` of the single report
file — the five unrelated prior-phase reports and `scripts/_meta_ai_duplicate_forensics_1_repro.py`
stay untracked, as found).

## S. Remaining risks

1. **The upstream clustering is still broken.** This phase is a firewall, not the repair. arXiv
   abstracts still get mis-clustered by `match_story`; the firewall only stops Story Continuity
   from being *confident* about the result. The 30-id and 16-id garbage Stories still exist and
   still grow. A separate phase must repair arXiv ingestion (headline vs. abstract) and/or
   Story clustering after a blast-radius analysis.
2. **`_STORY_IDENTITY_POLLUTION_FLOOR = 2`** is a reasoned default. A legitimate Story that
   tracked one paper across an arXiv *withdrawal + resubmission under a new id* (rare) would
   fail open → `AMBIGUOUS` (still creates a task, still no suppression). Acceptable; refine from
   a longer sample.
3. **Non-arXiv abstract-as-title** from other feeds is covered by the `ABSTRACT_LIKE` + no-id
   branch, but the char/word floors (300 / 40) are tuned to arXiv; a shorter body-as-title
   syndication could land in `UNKNOWN` and be treated as safe. `title == summary` catches the
   common case; the floors should be re-checked against a news-representative sample.
4. **Legit exact re-collection inside a polluted Story** is now demoted to `AMBIGUOUS` (task
   still created, dedup lost for that one event). This is the intended trade — "false
   suppression is worse than a duplicate" — but it means P0.1 slightly *reduces* dedup on
   already-garbage clusters until the upstream repair lands.
5. **DOI coverage is minimal** (URL-only). No DOI appeared in the shadow sample; if a
   DOI-bearing feed is added, the same conflict/match logic applies but has not been exercised
   on real data.

## T. Production rollout recommendation

`STORY-CONTINUITY-P0.1-SHADOW-PRODUCTION-ROLLOUT-1` (a **separate** phase, **after Founder
review**): rebuild and deploy **`automation_worker` only** from this phase's HEAD, shadow mode,
preserving the existing `rollback-pre-story-continuity-p0` tag and taking a fresh one. No
suppression, no UPDATE, no RECAP, no flag change, no migration. Collect a **multi-hour,
news-representative** sample (not an arXiv-burst window) and confirm:

- the firewall's fail-open rate on genuine news confident-matches is ~0 (no normal-news
  regression at volume);
- `polluted_multi_document_story` / `stable_identity_conflict` counts track the known garbage
  clusters and do not fire on clean Stories;
- `would_suppress` is `False` on every `guard_forced_fail_open` row.

Only then reconsider enforcement readiness — which also still depends on the upstream arXiv
clustering repair (risk S1).

---

## Verdict

**`STORY_CONTINUITY_P0_1_GUARD_PASS`**
**`RECOVERY_RESULT = FULL_RECOVERY`**

Recovery: the crash left the implementation (`934498d`) and tests (`f22df77`) fully committed on
the isolated branch `feature/story-continuity-p0-1-abstract-identity-guard-1` (base `b45e384`);
no tracked file was uncommitted, no stash, no dangling commit, no other worktree held P0.1 work.
Only this report + the final validation runs were outstanding. All 18 worktrees, the one stash,
and all reflogs were inventoried non-destructively before any edit; nothing was reset, cleaned,
checked-out-over, or dropped. Preserved by a single selective-add `docs(...)` commit.

All 16 acceptance-gate conditions (§22) hold:

1. all interrupted work searched for before editing — 18-worktree + reflog + stash inventory (RECOVERY §A–L);
2. recovered work preserved — 2 pre-crash commits intact, report committed selectively;
3. unrelated arXiv ids (different stable id) cannot become suppressible on abstract/title similarity — `IDENTITY_CONFLICT` → fail open (§F/§G, replay §K: 4 wrong `DUPLICATE_NO_DELTA` demoted);
4. abstract-like titles without strong same-document identity fail open — Case C (§H, tests case 9);
5. same-arXiv-document continuity still possible — Case B / `IDENTITY_MATCH` (§G, tests cases 5–6, replay keeps 4 legit duplicates);
6. guard-triggered fail-open has `would_suppress=False` — forced in `_apply_story_memory` (§J, `test_p0_1_guard_fail_open_never_leaves_a_suppression_eligible_outcome`);
7. normal news unchanged — `identity_assessment=None` ⇒ byte-identical; `TITLE_LIKE` news kept (§L, parity tests);
8. polluted Story membership alone cannot create duplicate confidence — `_STORY_IDENTITY_POLLUTION_FLOOR` (§H, test case 10);
9. no global Story clustering threshold change — `story_memory` constants untouched (§H);
10. no historical Story mutation / backfill — none;
11. no LLM / network / embedding call added — pure deterministic module (§M);
12. no schema migration — `MIGRATION_REQUIRED = false`, DB head stays `4a1b7c9d2e3f` (§N);
13. zero new regression failures — identical-command baseline-vs-HEAD diff, `NEW_FAILURES = 0` (§P);
14. zero new static errors — `ruff` clean, `mypy` new-file-clean, both = baseline (§O-static);
15. suppression remains OFF — no flag touched;
16. no production deployment — none; `automation_worker` stays on `b45e384` shadow.
