# UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1: Source-of-Truth Reconciliation

Read-only investigation, performed before any architectural implementation, per this phase's own
hard gate (§1). No `git reset`, `git clean`, `stash drop`, `rebase`, or `commit --amend` was used
anywhere in this phase - only `git worktree add` (new, isolated) and ordinary `git merge` (into that
new branch only).

## Investigation method

`git status`, `git worktree list`, `git branch -vv`, `git branch -r`, `git log --oneline --graph`,
targeted `git merge-base` / `git merge-base --is-ancestor` pairwise checks across every commit named
in the phase brief plus every local worktree's own branch tip, `git fsck --no-reflogs --unreachable`
(read-only dangling-object listing), and direct SSH/`docker ps`/`docker inspect` reads against the
live production host for the actual deployed image tags.

## Finding: the GitHub default branch is NOT production truth

`origin/HEAD -> origin/feature/phase19-editorial-depth-upgrade`. Its remote tip is `324a57a`
(2026-08-30). The local copy of the same branch (the primary working directory, `C:/Users/Theodor/
ai-newsroom`) is 5 days further ahead at `d6c6505` (2026-09-04, `324a57a` confirmed an ancestor - not a
divergence, just unpushed local commits) and currently carries a large set of **uncommitted** in-progress
changes (a meme-generation feature, `bot/`, `capabilities/meme_*`, `services/meme_*`, etc. - unrelated
to this phase, left untouched).

Critically: **`d6c6505` (and everything on this branch) predates every real production fix this project
has shipped since 2026-09-08** - `d2dea2c` (production baseline, 2026-09-08), `d0a0377` (Telegram
Visual V8, 2026-09-10), `a41c02d` (Story Continuity P0 enforcement, 2026-09-10), and `6f56aec` (arXiv
clustering, 2026-09-12) are **not ancestors of `d6c6505`/`feature/phase19-editorial-depth-upgrade`
at all** - confirmed via `git merge-base --is-ancestor`, all three return false. The default branch is a
genuinely separate, older fork point, not a stale-but-compatible mainline.

## CANONICAL_TELEGRAM_SOURCE

`b5d5276` (branch `feature/telegram-text-only-visual-fallback-repair-1`, worktree
`C:/Users/Theodor/ai-newsroom-v8-release`, pushed to origin). Lineage: `d2dea2c` (production baseline)
-> `d0a0377` (Founder-approved Visual V8, dependency-pinned as `d0a03773-pinned`) -> `8eabc93` +
`b5d5276` (this session's own TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1, PASS, **currently deployed
to production `content_worker`** as of this phase's start). This is the exact, currently-running
Telegram source.

## CANONICAL_INSTAGRAM_SOURCE

`0379ff2` (branch `feature/instagram-autonomous-trend-to-carousel-canary-1`, worktree
`C:/Users/Theodor/ai-newsroom-ig-trend-canary-1`, **local-only, never pushed to origin**). Lineage:
`d2dea2c` -> `c2ecc6f` (INSTAGRAM-DIRECTOR-STATE-RECONCILIATION-1, read-only audit) -> `00016fe`
(INSTAGRAM-EXECUTION-FOUNDATION-1: `InstagramContentPackage`, native renderer, Art validator, shadow
publish adapter) -> [`feature/instagram-growth-engine-v1`'s own commit chain, `07b0ac7` and its
ancestors - persistent intelligence memory, Creative Director shadow generation, CreativePlan
persistence, calendar wiring - confirmed via `git merge-base --is-ancestor 07b0ac7 c666fb4` = true, i.e.
fully contained, not a sibling] -> `c666fb4` (INSTAGRAM-VISUAL-SYSTEM-V1-1: the real premium visual
families for NEWS/BREAKING/DATA/QUOTE/CAROUSEL/REEL) -> `0379ff2` (the autonomous trend-to-carousel
canary plus its own self-caught iPhone-Duo wrong-photo fix, itself dependent on a manually cross-ported
result from the media-research branch below). Instagram publication stays hard-disabled
(`instagram_publication_enabled = false`) throughout this entire lineage - confirmed, not assumed.

## CANONICAL_CROSS_PLATFORM_MEDIA_RESEARCH_SOURCE

`9fc7b1e` (branch `feature/cross-platform-media-research-selection-1`, worktree
`C:/Users/Theodor/ai-newsroom-media-research-1`, **local-only, never pushed**). Base: `d6c6505` (the
*old* default-branch tip - this module was built independently of both the Telegram and Instagram
production lineages, then its *result* was manually cross-ported as a standalone fix onto the
Instagram branch as `0379ff2`; the module's own source code itself was never previously merged onto
either the Telegram or Instagram lineage until this phase). Contains: `MediaIntent`, bounded web
discovery, a new vision-LLM subject-match capability (`EXACT_SUBJECT`/`STRONG_CONTEXT`/
`GENERIC_CONTEXT`/`MISMATCH`), and dominance-by-construction selection scoring - exactly the primitives
phase §11-13 asks for, not reimplemented from scratch in this phase.

## CANONICAL_STORY_MEMORY_SOURCE

`6f56aec` (branch `release/arxiv-story-clustering-production-1`, worktree
`C:/Users/Theodor/ai-newsroom-arxiv-clustering-prod-1`, pushed to origin, **currently deployed to
production `automation_worker`**). Lineage: `d2dea2c` -> `a41c02d` (Story Continuity P0 constrained
enforcement, confirmed via `git merge-base --is-ancestor a41c02d 6f56aec` = true) -> `6f56aec` (arXiv/
DOI stable-identity clustering repair). The enforcement predicate is frozen per this phase's own §29 -
this reconciliation only locates and preserves the source, changes nothing in it.

## MISSING_OR_UNPUSHED_COMMITS

| Lineage | Tip | Pushed to origin? |
|---|---|---|
| Instagram (all of it) | `0379ff2` | **No** - `feature/instagram-autonomous-trend-to-carousel-canary-1` has no upstream configured at all |
| Instagram visual system | `c666fb4` | No |
| Instagram execution foundation | `00016fe` | No |
| Instagram growth engine | `07b0ac7` | No (local tip `07b0ac7` is ahead of the stale `origin/feature/instagram-growth-engine-v1` at `05585ae`) |
| Cross-platform media research | `9fc7b1e` | No |
| Telegram Directors (visual+growth intelligence persistence) | `8c68109` | No (`feature/telegram-directors-2` has no upstream; superseded/contained by later merges anyway) |
| Launch-readiness visual/recap audit | `c2ecc6f` | No |

None of these are lost - every one was located as a live local branch tip on an existing worktree and
preserved via `git merge` (never recreated from memory, per the phase's own explicit instruction).
`a9908e8` (the specific commit the phase brief named for the first canary) is itself superseded by, and
fully contained within, `0379ff2` on the same branch - also not lost, just an older point on the same
line.

## ACTIVE_WORKTREES (as found, all preserved untouched)

`ai-newsroom` (primary, `feature/phase19-editorial-depth-upgrade` @ `d6c6505`, dirty - meme feature
in progress, untouched), `ai-newsroom-v8-release` (`feature/telegram-text-only-visual-fallback-repair-1`
@ `9fe0297`), `ai-newsroom-arxiv-clustering-prod-1` (`release/arxiv-story-clustering-production-1` @
`6f56aec`), `ai-newsroom-ig-exec-1` (`feature/instagram-execution-foundation-1` @ `00016fe`),
`ai-newsroom-ig-growth-v2` (`feature/instagram-growth-engine-v1` @ `07b0ac7`), `ai-newsroom-ig-visual-1`
(`feature/instagram-visual-system-v1-1` @ `c666fb4`), `ai-newsroom-ig-trend-canary-1`
(`feature/instagram-autonomous-trend-to-carousel-canary-1` @ `0379ff2`), `ai-newsroom-media-research-1`
(`feature/cross-platform-media-research-selection-1` @ `9fc7b1e`), `ai-newsroom-director-control-plane`
(`feature/director-control-plane-v1` @ `d2dea2c` - identical tree to `d2dea2c` itself, no divergent
content), `ai-newsroom-launch-visual-recap-1` (`feature/launch-readiness-visual-recap-parallel-1` @
`c2ecc6f`), plus 11 more worktrees for other, unrelated-to-this-phase lines of work (social intelligence,
R2 announcement/recap, telegram directors, visual brand mark, production reconciliation, meta-forensics)
- all listed via `git worktree list`, all left exactly as found. **This phase's own new worktree**:
`C:/Users/Theodor/ai-newsroom-unified-pipeline-1`, branch `feature/unified-editorial-production-pipeline-1`.

## PRODUCTION_SERVICE_SHA_MAP (live, read via SSH at reconciliation time)

| Service | Image | Source | Restarts |
|---|---|---|---|
| `content_worker` | `ai-newsroom-content_worker:b5d5276-pinned` | `b5d5276` | 0 |
| `telegram_bot` | `ai-newsroom-telegram_bot:d2dea2c` | `d2dea2c` | 0 |
| `backend` | `ai-newsroom-backend:d2dea2c` | `d2dea2c` | 0 |
| `automation_worker` | `ai-newsroom-automation_worker:6f56aec` | `6f56aec` | 0 |
| `news_analysis_worker` | `ai-newsroom-news_analysis_worker:d2dea2c` | `d2dea2c` | 0 |
| `postgres` | `postgres:16-alpine` | n/a | 0 |
| `redis` | `redis:7-alpine` | n/a | 0 |

Alembic head in production: `4a1b7c9d2e3f`. Instagram publication: `instagram_publication_enabled=false`
(confirmed unset/false in the reconciled source, never checked against prod `.env` since Instagram has
never been deployed).

## Integration branch construction (this phase)

`feature/unified-editorial-production-pipeline-1`, created via `git worktree add` from `b5d5276`
(CANONICAL_TELEGRAM_SOURCE), then three ordinary, non-destructive `git merge --no-ff` operations, each
verified conflict-free (`git diff --name-only --diff-filter=U` empty) and committed separately:

1. `6f56aec` (Story Memory / arXiv) - only `core/config.py` overlapped with the Telegram base;
   auto-merged mechanically.
2. `0379ff2` (Instagram, full lineage) - 13 files overlapped with the Telegram base including the
   render-critical `services/brand_renderer.py`, `services/nnj_master_news_overlay.py`, `services/
   presentation_director.py`, `services/render_evidence.py` - all four confirmed **byte-identical** to
   the pre-merge Telegram-only state after the merge (`git diff HEAD -- <file>` empty), so V8's own
   rendering is untouched. The two lineages' independently-created alembic migration graphs already
   converge to a **single head**, `4a1b7c9d2e3f` - identical to the live production head - confirmed via
   `alembic.script.ScriptDirectory.get_heads()` returning exactly one value after the merge.
3. `9fc7b1e` (cross-platform media research) - purely additive, only `core/config.py` overlapped.

A bounded post-merge regression check (`test_visual_fallback_hold_repair_1.py`, `test_story_
continuity.py`, `test_story_identity_guard.py`, `test_media_research_selection.py`, `test_media_
subject_match_capability.py`) passed 76/76 - the reconciliation itself introduces no regression.

## Hard-gate conclusion

Both the required current Telegram source and the required current Instagram source have been located,
identified with evidence (not memory), and are now both physically present - together with Story Memory
and cross-platform media research - in one clean integration branch. Architectural implementation may
proceed.
