# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2 + 3 — Product Lane + Reel Scripts Rollout 1

**Verdict: integration complete and tested; production deployment BLOCKED before any build/deploy
step — no existing controlled-rollout gate for the PRODUCT lane.**

## 1. Current production base

Read-only snapshot immediately before creating the integration branch:

```
PROD_TELEGRAM_IMAGE=ai-newsroom-telegram_bot:conversational-director-phase1-05cf8c7
PROD_TELEGRAM_IMAGE_ID=sha256:9bca24af28ad5fffbc0627cde6411c9d596d54d98616c1fd9cc95f367bc0e020
PROD_TELEGRAM_SOURCE_SHA=05cf8c7

PROD_CONTENT_WORKER_IMAGE=ai-newsroom-content_worker:instagram-auto-trigger-1be8162
PROD_CONTENT_WORKER_IMAGE_ID=sha256:b575d3779afabb1d5624d079eae9dc9f20b1d684a4f879e0bd9674ed1542f02d
PROD_CONTENT_WORKER_SOURCE_SHA=1be8162

PROD_DB_REVISION=a3f7c1d9e042
```

`git ls-remote` confirmed `release/conversational-active-director-phase1-1`'s remote HEAD is
still exactly `05cf8c7` — matches production's running telegram_bot image tag exactly, no drift.
`git merge-base 1be8162 05cf8c7` returns `1be8162` itself — content_worker's running commit is a
clean ancestor of the current Phase-1 release lineage, fully compatible.

## 2. Integration lineage

New isolated worktree (`C:/Users/Theodor/ai-newsroom-phase23-release-1`), branch
`release/instagram-product-reels-phase23-1`, created directly from `05cf8c7` (not from `93f40d3`,
`0900da2`, `347fdb1`, or the old V2 branch tip).

```
git cherry-pick 0238ac9   ->  6d140bc  (Phase 2)
git cherry-pick 87ca8b9   ->  cbbd469  (Phase 3)
```

Both cherry-picks applied cleanly with **zero conflicts**. `diff <(git show 0238ac9) <(git show
6d140bc)` and the equivalent for Phase 3/`cbbd469` show **zero content differences** beyond commit
metadata — the two source commits touch a completely disjoint file set from everything Phase 1's
hotfixes changed, so this is a byte-identical transplant, not a manual re-implementation.

## 3. Phase-1 hotfix preservation proof

`PHASE1_HOTFIXES_PRESERVED=true` — nothing from the Phase-1 lineage was touched, reverted, or
conflicted:

- Founder role-map / auth expectations (`business_context_roles.py`) — untouched
- Short-answer contextual reply fix (`bot/handlers/business_context.py` question-vs-confirmation
  ordering) — untouched
- OpenAI strict-schema correction (`prompts/business_context_parser/v3.yaml`) — untouched
- Conversational proposal presenter + v4 prompt (no fabricated campaign/milestone) — untouched
- Natural correction flow — untouched
- Human confirmation UX / keyboard labels — untouched

## 4. Phase 2 diff (source: `0238ac9`)

- `services/director_execution_service.py`: new `_product_opportunities_from_context()` —
  produces a real PRODUCT `ContentOpportunity` (`campaign_plan=None`) from a Product's own
  **CONFIRMED** `current_features`, with zero LaunchCampaign requirement. A product with no
  confirmed features produces **zero** opportunities here — never fabricated. Merged with the
  pre-existing `_product_opportunities_from_campaigns()` output before `generate_growth_strategy()`
  ranks them in `run_instagram_growth_strategist()` — confirmed by direct code read, not assumed.
- `services/instagram_automatic_trigger.py`: new `evaluate_and_submit_instagram_opportunity()` —
  a general sibling entrypoint accepting an already-built, already-ranked `ContentOpportunity` of
  any `source_type`, running it through the same real format/creative/render/QA/delivery chain the
  NEWS lane uses. `evaluate_and_submit_instagram_candidate()` (NEWS) is byte-identical, untouched.
  Delivers into the existing Telegram review path (`deliver_instagram_package`) — no Instagram API
  write call anywhere in this function.
- `worker/content_cycle.py`: new `_run_instagram_product_lane()`, wired as a third, independent
  lane in `run_content_cycle()` (never coupled to the NEWS lane or the main NEWS loop), capped at
  1 opportunity/cycle.

## 5. Phase 3 diff (source: `87ca8b9`)

- `schemas/instagram_creative.py`: `InstagramReelCreative` gains `visual_direction`,
  `asset_requirements`, `adaptation_notes` — all optional, byte-identical construction for every
  pre-existing call site.
- `services/instagram_creative_director.py` / `prompts/instagram_creative_director_reel/v2.yaml`:
  the 3 new fields folded into the existing fact-safety check; `v1.yaml` left untouched.
- `services/instagram_reel_script_readiness.py` (new): `unresolved_required_facts()` +
  `compute_reel_script_readiness()` → `CONCEPT_SCRIPT`/`PRODUCTION_SCRIPT`, computed from the
  existing 5-state Product fact model. A **PLANNED** feature is explicitly never "unresolved" (can
  be discussed truthfully as upcoming); only UNKNOWN/UNDECIDED block the premise — read directly
  from source, matches the Founder's own truth-safety requirement exactly.
- `services/instagram_telegram_package_presenter.py::present_reel()`: already renders a fully
  human/editorial brief (Хук / Сценарий / Кадры / Визуал / Voiceover / Текст на экране / Audio /
  Длительность / Нужно / readiness badge 🟢 ГОТОВ К ПРОДАКШЕНУ / 🟡 КОНЦЕПТ-СКРИПТ) — no raw
  JSON/schema dump, matching the Founder's requested UX shape essentially verbatim. **No changes
  were needed here** - the original Phase 3 author already built this the way the Founder now
  wants it.
- **Disclosed in the original commit message itself**: the live automatic PRODUCT trigger hardcodes
  format to `SINGLE` (`assert format_decision.recommended_format is ContentFormat.SINGLE`) — REEL
  is never auto-selected by the real automatic path today. See §12 (Step 16) below.

## 6. Service impact map

Proven from actual `import` grep, not assumed:

```
TELEGRAM_BOT_CODE_AFFECTED=true   (bot/handlers/instagram_editorial_review.py -> services/instagram_telegram_package_presenter.py, a Phase-3-changed file)
CONTENT_WORKER_CODE_AFFECTED=true (worker/content_main.py -> worker/content_cycle.py -> director_execution_service.py / instagram_automatic_trigger.py / instagram_content_package.py / instagram_creative_director.py / instagram_reel_script_readiness.py / instagram_telegram_package_presenter.py)
NEWS_ANALYSIS_WORKER_CODE_AFFECTED=false
AUTOMATION_WORKER_CODE_AFFECTED=false
BACKEND_CODE_AFFECTED=false
```

## 7. Phase 4-6 exclusion proof

```
grep -rlE "NEWS_DIGEST|digest_schedule_state|trend_fingerprint|trend_cluster|trend_observation|
           TrendSourceNotConfigured|instagram_news_digest|YouTubeTrendSourceAdapter|
           BlueskyTrendSourceAdapter" --include="*.py" .
```
→ one match, `services/instagram_automatic_trigger.py`, and it is a **comment** ("later phases,
NEWS_DIGEST/TREND all flow through HERE via generate_growth_strategy()'s already-..."), not
runtime code. `ls database/migrations/versions/` shows only `a3f7c1d9e042`; `alembic heads` → a
single head, `a3f7c1d9e042`.

```
PHASE_2_INCLUDED=true
PHASE_3_INCLUDED=true
PHASE_4_INCLUDED=false
PHASE_5_INCLUDED=false
PHASE_6_INCLUDED=false
MIGRATION_2_PRESENT=false
MIGRATION_3_PRESENT=false
```

## 8. Tests

| Chunk | Result |
|---|---|
| Phase 2 + Phase 3 focused | 40/40 pass |
| Phase-1 conversational Director + proposal/roles/registry | 91/91 pass |
| Instagram package/art-validator/delivery/automatic-trigger | 54/54 pass |
| Telegram routing | 99/99 pass |
| Story Memory + arXiv + Vision Gate + Unified Editorial Pipeline (frozen) | 190/191 pass — 1 failure is the **known, pre-existing, already-disclosed** Story Memory V2 isolation gap (`scripts/_phase23_1p_post_run_analysis.py`), proven to predate this branch's base entirely; explicitly out of scope, not touched |

`ruff check` on all 8 Phase 2+3 changed/integrated source files: clean. `mypy`: zero findings in
those 8 files (the only output is the same pre-existing, unrelated, transitively-imported findings
already disclosed in every prior audit this session).

**NEW_FAILURES=0**

## 9. Runtime feature-gate audit — BLOCKER

```
PRODUCT_LANE_SCHEDULER_CALL_SITE = worker/content_cycle.py::run_content_cycle(), unconditional
PRODUCT_LANE_RUNTIME_GATE = _run_instagram_product_lane()'s only guard is
    `gate_gateway is None or gate_prompt_repository is None`
```

`worker/content_main.py:50` passes real, non-None `gate_gateway=ai_layer.gateway,
gate_prompt_repository=prompt_repository` **unconditionally** — the exact same gate the
already-live NEWS Instagram lane uses. `grep -in "product_lane\|instagram_product" core/config.py`
→ no matches; no dedicated feature flag for this lane exists anywhere in the codebase.

**This means deploying this content_worker image would activate the PRODUCT lane automatically, on
the very first cycle, with no controlled-rollout mechanism at all** — exactly the condition this
runbook's own Step 8 names and requires a STOP for.

```
CONTROLLED_PRODUCT_ROLLOUT_GATE_MISSING
```

Per explicit instruction ("Do not solve this by adding a new scheduler"; the STOP condition itself
is unconditional on a missing safe gate), no new flag was added, no image was built, no service was
deployed. Reported here rather than resolved unilaterally.

## 10. LLM routing health preflight

Not executed as a formal read-only check this pass, since deployment itself is blocked upstream of
this step - recording that explicitly rather than fabricating a result. The most recent known state
(from the prior Phase-1 hotfix rollout): `gpt-5.6-luna` was confirmed routable via a real bounded
probe; `gpt-5.6-terra`/`gpt-5.6-sol` may still carry stale pre-hotfix latches, deliberately left
untouched pending a decision (per that rollout's own report). Re-verify at the point a real
controlled-rollout gate is authorized and deployment is about to proceed.

## 11. Build/deploy

**Not performed.** No image was built for either service; no `docker-compose.override.yml` change
was made; no container was touched. Production remains exactly as recorded in §1.

## 12. Canary

**Not executed** — deployment is the prerequisite and did not happen. For context/planning only,
read-only production Product Truth was checked ahead of time:

```
ninja_ai:    current_features=None, planned_features=['Релиз Ninja AI в Telegram']
ninja_store: current_features=None, planned_features=['Запуск веб-магазина Ninja Store']
```

Both real products currently have **only PLANNED facts, zero CONFIRMED facts**.
`_product_opportunities_from_context()` (as designed and integrated, unchanged from the original
Phase 2 approval) only builds a PRODUCT opportunity from **CONFIRMED** `current_features` — a
deliberate truth-safety choice in the original design (an evidence line literally reads "confirmed
feature: X"; using a merely-planned fact there would misstate it). Given real current data, **the
very first PRODUCT-lane cycle would almost certainly HOLD with zero opportunities** once deployed,
not produce a real candidate — a legitimate, honest, disclosed outcome per this runbook's own
"HOLD is a valid result" allowance, not a defect.

Separately, and independent of the above: the live automatic trigger hardcodes format to `SINGLE`
(§5) — REEL is never selected by the real automatic PRODUCT path as currently designed. No existing
safe manual/editor override path to force a REEL format for a live opportunity was identified in
the time available for this pass.

```
REEL_LIVE_CANARY_DEFERRED=true
```

## 13. Rollback

Not applicable — nothing was deployed.

## 14. Remaining blockers before this can go live

1. **Primary blocker**: no controlled-rollout gate for the PRODUCT lane in `content_worker`. Needs
   a Founder decision: authorize a minimal, explicit, default-off config flag (the smallest
   possible guard, not a new scheduler/pipeline) gating `_run_instagram_product_lane()`
   independently of the NEWS lane's own gate, or another safe mechanism the Founder prefers.
2. Once deployable: real Product Truth currently only supports a HOLD outcome for the PRODUCT lane
   (§12) — this is expected and correct, not something to route around by lowering thresholds.
3. REEL format is never auto-selected by the live path today (hardcoded `SINGLE` in Phase 2's own
   `evaluate_and_submit_instagram_opportunity()`) — a live REEL canary needs either a real
   evidence-driven trigger to naturally prefer REEL, or an explicit, separately-authorized manual
   override mechanism (not built as part of this rollout).
4. LLM health state for `gpt-5.6-terra`/`gpt-5.6-sol` should be re-verified at actual deploy time.
