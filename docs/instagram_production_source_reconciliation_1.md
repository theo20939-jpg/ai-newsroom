# Instagram Production Rollout 1 — Source Reconciliation

**Phase**: INSTAGRAM-PRODUCTION-ROLLOUT-1
**Base**: `feature/unified-editorial-pipeline-vision-gate-closure-1` @ `39f764bfc64b8c4b311e3feb5431f26b0be09899`
**New branch**: `feature/instagram-production-rollout-1`, isolated worktree.

## Reconciliation method

Ran `git worktree list`, `git branch -a`, `git log --all --decorate --oneline`, then
`git merge-base --is-ancestor <sha> HEAD` for every historical Instagram/Director/Social-
Intelligence reference named in the phase brief plus every one this repository's own worktree list
surfaced.

## Result: everything historical is already integrated

| Historical ref | Branch | Ancestor of current HEAD? |
|---|---|---|
| `00016fe` | `feature/instagram-execution-foundation-1` | **YES** |
| `c666fb4` | `feature/instagram-visual-system-v1-1` | **YES** |
| `a9908e8` | `feature/instagram-autonomous-trend-to-carousel-canary-1` | **YES** |
| `0379ff2` | (fix on the trend-canary branch) | **YES** |
| `07b0ac7` | `feature/instagram-growth-engine-v1` | **YES** |
| `c2ecc6f` | `feature/launch-readiness-visual-recap-parallel-1` (Director state reconciliation) | **YES** |
| `feature/social-intelligence-integration-v1` | | **YES** |
| `feature/social-intelligence-ops-v1` | | **YES** |
| `feature/social-intelligence-prelaunch-1`(`a`) | | **YES** |
| `feature/social-business-context-v1` | | **YES** |
| `feature/director-control-plane-v1` | | **YES** |

Merge commits `725f891` ("merge: reconcile Instagram lineage (0379ff2) into the unified pipeline
integration base") and `de9e311`/`7a0436a` (Story Continuity/arXiv, cross-platform media research)
are visible directly in `git log`, confirming this was a deliberate, already-completed
reconciliation from an earlier phase - **no cherry-picking was necessary or performed this phase.**

## Current locations of every component named in §2

| Component | Path |
|---|---|
| `InstagramContentPackage` | `services/instagram_content_package.py` |
| Instagram renderer | `services/instagram_platform_renderer.py` (+ `instagram_carousel_layouts.py`, `instagram_editorial_layouts.py`, `instagram_data_layouts.py`, `instagram_quote_layouts.py`, `instagram_reel_layouts.py`) |
| Instagram Visual System V1 | `services/instagram_visual_profiles.py`, `services/instagram_visual_spec.py`, `services/instagram_design_tokens.py` |
| Shadow planner | `services/instagram_shadow_pipeline.py` |
| Format Decision | `services/instagram_format_director.py`, `services/instagram_format_director_v2.py` |
| Creative Director | `services/instagram_creative_director.py`, `schemas/instagram_creative.py` |
| Art validation | `services/instagram_art_validator.py` |
| Publication adapter/client | `services/instagram_publish_adapter.py` (`HttpInstagramPublishClient` real, `ShadowInstagramPublishClient` shadow) |
| Config flags | `core/config.py` (`instagram_publication_enabled`, NEW: `instagram_autonomous_publication_enabled`) |
| Tests | 30+ files matching `tests/test_instagram_*.py` + `tests/test_editorial_pipeline_instagram_adapter.py` |
| Account reader (read-only) | `services/instagram_account_reader.py` |
| Graph API integration | `services/instagram_graph_adapter.py` (read-only, per `design/instagram_official_api.md`) |
| Editorial/publication gate | `services/instagram_editorial_gate.py` |
| Review package | `services/instagram_review_package.py` |
| Publication audit | `services/instagram_publication_audit.py` |

## What is NOT yet integrated (confirmed by direct code audit, not assumption)

These are real, structural gaps in the CURRENT reconciled codebase - not a reconciliation problem
(nothing is missing due to an unmerged branch; the capability itself was never built):

1. **No live wiring from the unified media-truthfulness/rights pipeline
   (`MediaResearchService`/`SubjectMatchClassification`/`MediaUsageClassification`, built for
   Telegram in the runtime-closure-1/vision-gate-closure-1 phases) into the Instagram package or
   gate.** `InstagramContentPackage.source_image_ref` is populated only by
   `scripts/_instagram_autonomous_trend_canary_1.py`, a manually-invoked, never-auto-run script,
   with a hardcoded local asset path. `services/instagram_editorial_gate.py` and
   `services/instagram_art_validator.py` never reference `subject_match`, `MISMATCH`,
   `EDITORIAL_REVIEW_REQUIRED`, or `MediaResearchService` at all (confirmed by direct grep - zero
   matches). See the main report §D/§G for the full implication.
2. **No real, public media-hosting mechanism anywhere in this codebase.**
   `services/instagram_publish_adapter.py`'s own real orchestration code builds
   `image_ref = f"pending-media-ref:{package.package_id}"` for a real (non-shadow) call - a literal
   placeholder, by the module's own disclosed comment ("the real adapter takes an
   already-uploaded/reachable image URL; this phase never uploads one - no live media host
   wired"). `app/main.py` (the only FastAPI service in this repo) exposes exactly one route (`/`) -
   no static/media file serving of any kind.
3. **No DB persistence for Instagram publication state/idempotency.** `PublicationResult`
   (`services/instagram_publish_adapter.py`) is an in-memory dataclass only; no table exists to
   record `NOT_ATTEMPTED`/`CREATING_CONTAINER`/`PUBLISHED`/etc. durably (confirmed: no
   `database/models/*.py` file defines any such model).
4. **No credentials configured in production** - see main report §C.

These four gaps are independent of each other and independent of the reconciliation question
above - reconciliation itself is complete and clean.
