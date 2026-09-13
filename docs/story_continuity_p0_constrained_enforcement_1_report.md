# STORY-CONTINUITY-P0-CONSTRAINED-ENFORCEMENT-1 — Report

**Verdict:** `STORY_CONTINUITY_P0_CONSTRAINED_ENFORCEMENT_ROLLED_BACK`

The Founder-approved constrained enforcement predicate was implemented, replayed clean over the
production shadow sample (57 would-suppress, 0 false), deployed to `automation_worker`, and
enabled for a **1 h 54 m / 127-decision canary**. It suppressed **2 editorial tasks, both
confirmed TRUE_DUPLICATE**, with **zero false or uncertain suppressions and zero hard-invariant
violations**. It was then **disabled** because enforcement surfaced a **runtime-wiring defect**
(a §18 auto-rollback trigger): a suppressed event is left in `PROCESSING` with a committed
`NewsEventStoryLink` but no task, so every stale-recovery re-processing of it hits a
`news_event_story_links_pkey` `UniqueViolation` (`phase9_triage_phase_b_failed`). The predicate
logic is sound; the task-suppression wiring needs a small dev fix before re-enablement.

Suppression is **OFF**. The code (`f98f583`) stays deployed but inert
(`enforcement=fail_open:flag_disabled` for every decision — runtime-identical to the prior
shadow). No image rollback (the flag-off runtime is not faulty). No P1/P2. No clustering repair.

---

## FOUNDER QUICK METRICS

| metric | value |
|---|---|
| **FINAL VERDICT** | `STORY_CONTINUITY_P0_CONSTRAINED_ENFORCEMENT_ROLLED_BACK` |
| `BASE_SHA` | `c6694b9` |
| `FINAL_SHA` | `f98f583` (code) + `<report commit>` (docs) |
| `FEATURE_FLAG` | `story_continuity_p0_constrained_enforcement_enabled` — default **False**; enabled `2026-09-10T12:11:40Z`, **disabled `2026-09-10T14:05:20Z`** |
| `SHADOW_REPLAY_WOULD_ACTUALLY_SUPPRESS_COUNT` | **57** (35 same-arXiv-ID + 22 exact-normalized-title) |
| `SHADOW_REPLAY_FALSE_SUPPRESSION_FOUND` | **0** |
| `CANARY_DURATION` | 1 h 54 m |
| `CANARY_TOTAL_DECISIONS` | **127** (target ≥100 met) |
| `CANARY_ACTUALLY_SUPPRESSED` | **2** |
| `CANARY_SUPPRESSED_BY_EXACT_TITLE` | 2 |
| `CANARY_SUPPRESSED_BY_STABLE_IDENTITY` | 0 (both also had exact title) |
| `CANARY_FALSE_SUPPRESSION` | **0** |
| `CANARY_UNCERTAIN` | **0** |
| hard-invariant violations (non-DUP / score<0.99 / guard-forced / polluted / conflict / would_suppress≠true / delta≠NONE suppressed) | **0 / 0 / 0 / 0 / 0 / 0 / 0** |
| `RUNTIME_ERRORS_CAUSED_BY_ENFORCEMENT` | **1 class** — `phase9_triage_phase_b_failed` / `UniqueViolation news_event_story_links_pkey` on stale-recovery re-processing of a suppressed event |
| `ACTUALLY_SUPPRESSED` after flag disable | **0** |
| only `automation_worker` changed | **yes** — 6 other containers byte-identical, 0 restarts throughout |
| `MIGRATION_REQUIRED` | **false** (DB head `4a1b7c9d2e3f`, unchanged) |
| publication / Telegram / Instagram / Director / Recap behaviour | **unchanged** |
| Redis | `role:master`, 6379 private — unchanged |

---

## A. Base SHA

`c6694b9` — the P0.1 shadow release currently running in production
(`ai-newsroom-automation_worker:c6694b9`, `STORY_CONTINUITY_P0_1_ARXIV_SHADOW_PASS`). Its
runtime tree is identical to the crash-recovery report commit; `f98f583` branches directly off
it.

## B. Final SHA

`f98f583` (`feat(story-continuity): P0 constrained enforcement …`) — 3 runtime files changed vs
`c6694b9` (`core/config.py` +14, `services/story_continuity.py` +113,
`services/triage_orchestrator.py` +114) + one new test file. No other runtime file. This report
adds a docs commit on top.

## C. Exact enforcement predicate

`services/story_continuity.py :: evaluate_constrained_enforcement()` — pure, no I/O. A decision
is `suppress=True` **only when every gate holds** (first failing gate is recorded as the
fail-open reason):

1. `enabled` (the feature flag)
2. `continuity.outcome == DUPLICATE_NO_DELTA`
3. `continuity.suppression_eligible is True`
4. `continuity.delta_class == NO_DELTA`
5. `continuity.match_score >= 0.99`
6. `would_suppress_flag is True` (the P0 diagnostic already agreed)
7. `continuity.guard_forced_fail_open is False`
8. identity-guard verdict is `SAFE` (`identity_assessment.verdict == GUARD_SAFE`)
9. **not** an identity conflict (`stable_identity_status != STABLE_IDENTITY_CONFLICT` and no
   `stable_identity_conflict` reason code)
10. **not** a polluted Story (`polluted_multi_document_story` not in the reason codes)
11. positive identity evidence: `stable_identity_status == STABLE_IDENTITY_MATCH`
    **OR** `exact_normalized_title_match`

`exact_normalized_title_match` is recomputed **deterministically in `_apply_story_memory`**
against the matched Story's own prior `(title)` rows — `" ".join(title.split()).casefold()` on
both sides, byte-identical to `services/story_memory.py`'s own exact-title short-circuit; **no
fuzzy/semantic equivalence, no word stripping, no number removal** (spec §2). It is deliberately
**not** the score-based `match_is_exact_title_identity`, which a capped-at-1.0 near-verbatim
*scored* match could also satisfy.

`MATERIAL_UPDATE_CANDIDATE`, `AMBIGUOUS`, `NEW_STORY`, different-base-arXiv-ID matches, polluted
Stories, guard-forced decisions, score < 0.99, and any non-`NO_DELTA` all fail open and create
the normal editorial task.

## D. Feature flag

`core/config.py :: story_continuity_p0_constrained_enforcement_enabled: bool = False`. Default
`False` in code and every config template. Independent of `story_memory_mode` (its own
`"enforce"` value is a different, broader Story Memory concept and is wired to no suppression).
Production enables it via `/opt/ai-newsroom-ops/.env`
(`STORY_CONTINUITY_P0_CONSTRAINED_ENFORCEMENT_ENABLED=true`) + `automation_worker` recreate;
disabling is the same line flipped to `false` + recreate — the preferred first rollback (§18).

## E. Persistence / audit semantics

"Suppress" means **only**: `_run_phase_b` skips `create_task()` for that event and commits the
transaction explicitly (`create_task()` normally commits it), so the `NewsEventStoryLink` + the
`stories` row still persist. **The NewsEvent, Story membership, Story history, and prior
editorial tasks are untouched. No publication behaviour changes.**

Every suppressed decision records `ACTUAL_SUPPRESSION_REASON` in three places (no migration):

- `NewsEventStoryLink.material_delta` (json list) gains `"actually_suppressed"` +
  `"enforced:p0_constrained_v1"`.
- `NewsEventStoryLink.decision_reason` gains
  `actually_suppressed=True enforcement=actually_suppressed:DUPLICATE_NO_DELTA score=1.0
  basis=EXACT_NORMALIZED_TITLE_MATCH delta=NO_DELTA guard_forced_fail_open=False
  polluted_story=False identity_conflict=False policy=p0_constrained_v1
  exact_norm_title_match=True`.
- A dedicated `story_continuity_task_suppressed` structured log line carries the full
  `evidence` dict (classification, score, delta_class, would_suppress, guard_forced_fail_open,
  stable_identity_status, identity_verdict, identity_namespace, stable_identity_match,
  exact_normalized_title_match, polluted_story, identity_conflict, reason_codes,
  policy_version).

`TriageCycleReport.story_tasks_suppressed` counts them per cycle; the cycle-end log carries it.

## F. Shadow replay counts

Replayed `evaluate_constrained_enforcement` structurally over the persisted production shadow
rows (`decision_source='story_continuity_p0'`, `created_at >= 2026-09-09 11:22:50Z`; 1586
decisions at replay time, 100 `DUPLICATE_NO_DELTA`, 101 `would_suppress=true`), reconstructing
every predicate input from `final_decision`, `match_score`, `would_suppress`, `decision_reason`
(`guard_forced_fail_open`, `identity_status`), `material_delta` (reason codes), and a SQL
exact-normalized-title join against each row's own matched Story.

| result | value |
|---|---|
| `WOULD_ACTUALLY_SUPPRESS_COUNT` | **57** |
| via `STABLE_IDENTITY_MATCH` + exact title | 35 (all arXiv — same base ID re-collected in the burst) |
| via exact-normalized-title only | 22 (non-arXiv) |
| via stable-ID only (no exact title) | 0 |
| clean `DUPLICATE_NO_DELTA` @ ≥0.99 @ would_suppress with **no** stable-ID and **no** exact-title twin → **excluded** | 30 |
| C2 Guardian "US allies lack resources…" qualifies | **0** (score 0.785 < 0.99) |
| any polluted / conflict / guard-forced in the 57 | **0 / 0 / 0** |
| all 57 at `score = 1.0000` | yes |

## G. Review of replay suppressions — `FALSE_SUPPRESSION_FOUND = 0`

- **35 arXiv (`STABLE_IDENTITY_MATCH` + exact title, score 1.0, `NO_DELTA`)** — the same paper
  re-collected within the Sep-10 arXiv burst (the API returns the same recent 50 papers each
  cycle). Several appear 2–3× (same paper, later copies are exact duplicates). All
  `TRUE_DUPLICATE`.
- **22 non-arXiv (exact-normalized-title equality with a prior event in the same Story, score
  1.0, `NO_DELTA`)** — spot-checked the six most generic-titled ("Every Millisecond Counts",
  "Decoding the NEC V20 Microcode", "Bespoke: A Programming Language…", "Why Emacs Consult…",
  "Automattic CEO … Leave of Absence", "UNT to open new college of AI $20M gift"): **every pair
  is the identical canonical URL** — a genuine re-delivery (HN re-post, Google-News RSS wrapper,
  dual-feed pickup). The one exact-title twin on a *different* domain ("OpenAI says its
  next-generation processors could be made at Samsung…") is the Tom's-Hardware headline
  re-delivered via a Google-News wrapper — same story, byte-identical specific headline. All
  `TRUE_DUPLICATE`.
- Re-checks: 66 shadow "confirmed true duplicates" → 57 qualify (the predicate is *stricter*: 9
  of the 66 were sub-0.99 `supporting_source` or their exact-title twin was not in the same
  matched Story → they fail open); **all 174 identity conflicts, all polluted-Story cases, all
  guard-forced, C2 → 0 qualify**; clean same-base-arXiv-ID → the 35 qualify.

## H. Tests — `NEW_FAILURES = 0`

`tests/test_story_continuity_constrained_enforcement.py` — **25 pass** (22 pure predicate + 3
DB-integration). Covers the full §11 matrix: exact-title/stable-id eligible; score 0.989999 not;
0.99 needs identity; fuzzy-1.0-without-identity not; `AMBIGUOUS` / `MATERIAL_UPDATE_CANDIDATE` /
`NEW_STORY` not; different-arXiv-ID (`STABLE_IDENTITY_CONFLICT`) not; polluted-Story-at-1.0 not;
guard-forced not; same-arXiv-id-no-delta eligible; same-id-with-delta not; flag-off not;
`would_suppress` must be True; identity-guard verdict must be SAFE; narrow normalization
(numbers/words preserved, paraphrase ≠); evidence record always complete; **DB-integration**:
suppress persists the audit codes + preserves the NewsEvent and bumps Story `event_count`;
flag-off never suppresses; low-score fails open.

Regression (story + triage + worker surface, 17 files): **432 passed, 1 failed, 1 skipped**.
The single failure is the pre-existing
`test_story_memory_v2_shadow_isolation.py::test_only_expected_files_import_the_v2_modules`
(offenders `scripts/_phase23_1p_post_run_analysis.py` — tracked at `b45e384` — and the untracked
`scripts/_meta_ai_duplicate_forensics_1_repro.py`); red since before P0.1, unrelated to this
change (which adds no new V2-module importer).

## I. Static checks — `NEW_STATIC_ERRORS = 0`

`ruff check` on all four changed files → **All checks passed**. `mypy` on the three changed
runtime modules → **2 errors, both in the untouched `services/story_delta_engine.py`** (lines
170/178, `call-overload`) — the same pre-existing errors documented in every P0.1 report; **0
in any file this phase changed**.

## J. Production preflight (`2026-09-10T11:21Z`)

`automation_worker` container `2efc4c8b319d`, image `sha256:f592398c…`
(`ai-newsroom-automation_worker:c6694b9`), `RestartCount=0`, up 24 h. DB revision
`4a1b7c9d2e3f`. Redis `role:master`, `connected_slaves:0`, `PortBindings=map[]` (6379 not
published). Prod `.env`: `STORY_MEMORY_MODE=enforce`; **no `*CONSTRAINED_ENFORCEMENT*` key** →
the new flag was code-default `False`. `.env` byte-identical to the pre-P0.1 backup; compose =
the single `…:b45e384 → …:c6694b9` line. All 7 containers healthy.

## K. Backups (`BACKUP_TIMESTAMP = 20260910T112212Z`, `/opt/ai-newsroom-ops/backups/`)

| artifact | file | validation |
|---|---|---|
| DB dump (custom fmt) | `ai_newsroom_pre_p0_constrained_enforcement_1_20260910T112212Z.dump` (43.26 MB) | `pg_restore --list` → 530 TOC entries, `DB_BACKUP_VALID = true` |
| `.env` | `env.pre_p0_constrained_enforcement_1_20260910T112212Z.bak` | — |
| ops compose | `docker-compose.yml.pre_p0_constrained_enforcement_1_20260910T112212Z.bak` | — |
| `.env` at flag enable | `env.pre_flag_enable_p0ce_20260910T121134Z.bak` | — |
| `.env` at flag disable | `env.at_flag_disable_p0ce_20260910T140520Z.bak` | — |

Rollback image tag `ai-newsroom-automation_worker:rollback-pre-p0-constrained-enforcement-1` →
`sha256:f592398c…` (the pre-deploy `c6694b9` image) — **verified equal**.
`OLD_AUTOMATION_IMAGE_ID = sha256:f592398c…`, `OLD_AUTOMATION_CONTAINER_ID = 2efc4c8b319d`.

## L. Deployment scope

`automation_worker` **only**. Built `ai-newsroom-automation_worker:f98f583`
(`NEW_AUTOMATION_IMAGE_ID = sha256:5d3f9ae5…`, `linux/amd64`) from a `git bundle`-transferred
`/opt/ai-newsroom-release-f98f583` checkout (`RELEASE_SOURCE_MATCH = true` — the 3 runtime files
byte-match the `f98f583` blobs in the checkout **and** inside the image; Dockerfile identical to
the `c6694b9` release). `_apply_story_memory` calls no LLM/network/embedding; the predicate is
pure. Compose line 23 `…:c6694b9 → …:f98f583`; `docker compose up -d --no-deps
automation_worker`. Deploy at `2026-09-10T11:27:35Z`, **flag still OFF**.

## M. Before / after container matrix

| container | before | after (deploy) | after (flag enable) | after (flag disable) |
|---|---|---|---|---|
| `automation_worker` | `2efc4c8b` / `:c6694b9` | `8903c1a8` / `:f98f583` | `2309e6d2` / `:f98f583` | `389a7200` / `:f98f583` |
| `news_analysis_worker` | `a722b21f` / `:d2dea2c` | `a722b21f` | `a722b21f` | `a722b21f` |
| `content_worker` | `b416b1c0` / `:d2dea2c` | `b416b1c0` | `b416b1c0` | `b416b1c0` |
| `telegram_bot` | `aff0902c` / `:d2dea2c` | `aff0902c` | `aff0902c` | `aff0902c` |
| `backend` | `bcdbab62` | `bcdbab62` | `bcdbab62` | `bcdbab62` |
| `postgres` | `6d7c65f7` | `6d7c65f7` | `6d7c65f7` | `6d7c65f7` |
| `redis` | `db6fc18c` | `db6fc18c` | `db6fc18c` | `db6fc18c` |

**Only `automation_worker` ever changed. `RestartCount=0` on every container at every step.**

## N. Flag enablement

Health gate after the `f98f583` deploy (flag OFF): clean startup, 28 continuity decisions
through the new code, **all `actually_suppressed=False enforcement=fail_open:flag_disabled`**, 0
non-collector errors, 0 triage-B failures — runtime byte-identical to the prior shadow.

Flag enabled `2026-09-10T12:11:34Z` (append to `.env` + `docker compose up -d --no-deps
--force-recreate automation_worker`). Effective runtime verified in-container:
`settings.story_continuity_p0_constrained_enforcement_enabled == True`;
`story_memory_mode == "enforce"` (unchanged). All 6 other containers unchanged.
`FLAG_ENABLED_AT ≈ 2026-09-10T12:11:40Z` = canary start.

## O. Canary duration / sample

`12:11:40Z → 14:05:20Z` = **1 h 54 m**, **127** continuity decisions (`NEW_STORY` 65,
`AMBIGUOUS` 44, `MATERIAL_UPDATE_CANDIDATE` 12, `DUPLICATE_NO_DELTA` 6; `guard_forced_fail_open`
0). Ended by the §18 auto-rollback (below), after the ≥100-decision target was already met.

## P. Every actual suppression — reviewed against source evidence

| # | event | matched-Story evidence | classification |
|---|---|---|---|
| 1 | "President Trump Sold 2 Popular Artificial Intelligence (AI) Stocks. Wall Street Says Investors Should Buy Both. - The [Motley Fool]" (`7edc07d8`, Google-News RSS, published `09:08:31Z`), `DUPLICATE_NO_DELTA` score 1.0, `NO_DELTA`, basis `EXACT_NORMALIZED_TITLE_MATCH`, not guard-forced/polluted/conflict | Story `491e1202` already held a **byte-identical-headline** copy of the same Motley Fool article, delivered via Google-News RSS **`08:57:31Z`** (11 min earlier). | **TRUE_DUPLICATE** |
| 2 | "«Погибнет большинство людей»: новый эксперт OpenAI по безопасности предрёк катастрофу…" (`dc259b32`, Google-News RSS, published `09:50:00Z`), `DUPLICATE_NO_DELTA` score 1.0, `NO_DELTA`, basis `EXACT_NORMALIZED_TITLE_MATCH`, not guard-forced/polluted/conflict | Story `245ea62e` already held the **byte-identical-headline** 3dnews.ru article (`3dnews.ru/1148282`) **and** another Google-News wrapper of it, all `09:50:00Z`. | **TRUE_DUPLICATE** |

Both: `material_delta` carries `actually_suppressed` + `enforced:p0_constrained_v1`;
`decision_reason` carries the full `ACTUAL_SUPPRESSION_REASON`; a `story_continuity_task_suppressed`
log line was emitted. Side-effect checks: suppressed events with an editorial task = **0**;
NewsEvent rows still present = **2/2**; Story rows still present = **2/2**; no prior task
mutated.

## Q. False / uncertain counts

`CANARY_FALSE_SUPPRESSION = 0`. `CANARY_UNCERTAIN = 0`. Hard-invariant checks over the 127-row
flag window: non-`DUPLICATE_NO_DELTA` suppressed **0**, score < 0.99 suppressed **0**,
guard-forced suppressed **0**, polluted suppressed **0**, `STABLE_IDENTITY_CONFLICT` suppressed
**0**, `would_suppress ≠ true` suppressed **0**, `delta ≠ NO_DELTA` suppressed **0**.

## R. Parity

Non-`automation_worker` services: container IDs unchanged, `RestartCount=0`, no new
ORM/schema errors, normal operation. Every `ERROR`-level line in `automation_worker` during the
canary is `services.collector` (RSS 403/404/429/timeout noise) — **except** the one enforcement
error class in §S. With the flag OFF (before enable and after disable), the enforcement code is
inert and runtime is byte-identical to the `c6694b9` shadow. Publication, Telegram, Instagram,
Art/Campaign Director, and Recap behaviour: **unchanged** (§20 — nothing in those paths was
touched). Redis: `role:master`, 6379 private throughout.

## S. Runtime defect that triggered the rollback

**`phase9_triage_phase_b_failed` → `asyncpg.UniqueViolationError` on
`news_event_story_links_pkey`** (`Key (news_event_id)=(…) already exists`). First seen
`2026-09-10 13:33:12Z`.

**Root cause (a wiring defect in this change, not the predicate):** the primary key of
`news_event_story_links` is `news_event_id`. When the constrained predicate suppresses an event,
`_run_phase_b`'s suppress branch commits the freshly-added `NewsEventStoryLink` and **skips
`create_task()`**, but does **not** advance the event out of `EventStatus.PROCESSING`. Per
`_select_recovery_candidates` (Contract §7.6) an event that is `PROCESSING` **and** has **no
EditorialTask (any status)** **and** is stale is a recovery candidate — which a suppressed event
now permanently is. Each stale-recovery pass re-runs `_apply_story_memory`, which
unconditionally `session.add(NewsEventStoryLink(news_event_id=event.id, …))` → the second insert
for that `news_event_id` violates the pkey → the transaction is cleanly rolled back
(`_run_phase_b`'s existing `except Exception`), the event stays `PROCESSING`, and it is retried
again after the next staleness interval. Net effect: **≈ 1 `phase9_triage_phase_b_failed` per
suppressed event per staleness interval (~15 min), indefinitely.** No data corruption, no
legitimate editorial-task loss (the suppressed events correctly have none), but it is a
"runtime error caused by enforcement" — a §18 hard auto-rollback condition — and it leaves
suppressed events in a non-terminal state.

**Action:** flag **disabled** `2026-09-10T14:05:20Z` (`.env` → `false` + `automation_worker`
recreate). Effective `settings.story_continuity_p0_constrained_enforcement_enabled == False`
verified in-container. **0** new `actually_suppressed=True` rows since (no new stuck events can
be created). No image rollback — with the flag off, `f98f583` is runtime-identical to `c6694b9`
(`evaluate_constrained_enforcement` returns `fail_open:flag_disabled` before touching anything;
`_run_phase_b` gets `suppress=False` → `create_task()` runs exactly as before). An image
rollback to `c6694b9` would **not** help: its `_apply_story_memory` also inserts the link
unconditionally, so re-processing the 2 already-stuck events would raise the same
`UniqueViolation`.

**Residual state — ONGOING until the 2 events are remediated.** The 2 suppressed events
(`7edc07d8`, `dc259b32`) remain `PROCESSING` with a committed link and no task, and they are
therefore still stale-recovery candidates *regardless of the flag*. Post-disable, production
continues to emit ≈ **12 `phase9_triage_phase_b_failed` / hour** from these two events alone
(observed 4 in a 20-min window at `15:15–15:34Z`). Each is a clean rollback — no corruption, no
crash, the session recovers per the Contract §7.4 binding invariant, and **no other event is
affected** — but it is real error-log noise that will not stop on its own. The fix is either the
operator `UPDATE` (§U) or the dev fix (§U). A targeted production `UPDATE` to move the 2 events
to `EventStatus.ANALYZED` was attempted during this phase and **blocked by the environment's
safety classifier**; it is left for an operator.

## T. Final production source state

```
automation_worker    = f98f583   (constrained-enforcement code; FLAG OFF -> inert / shadow-equivalent)
news_analysis_worker = d2dea2c   (unchanged)
content_worker       = d2dea2c   (unchanged)
telegram_bot         = d2dea2c   (unchanged)
backend              = (unchanged)
DB head              = 4a1b7c9d2e3f   (unchanged, no migration)
```

`STORY_CONTINUITY_P0_CONSTRAINED_ENFORCEMENT_ENABLED=false` in `/opt/ai-newsroom-ops/.env`
(line kept for auditability). `STORY_MEMORY_MODE=enforce` (unchanged). Suppression **OFF**;
`would_suppress` diagnostic only; all decisions create editorial tasks again. Public
publication OFF; Telegram editorial enforcement OFF; Redis master / 6379 private. Rollback tags
`rollback-pre-p0-constrained-enforcement-1` (→ `c6694b9` image) and the earlier P0/P0.1
rollback tags all in place. On-box read-only tooling: `/opt/ai-newsroom-ops/.p0ce_*.sql`,
`.p0ce_canary_snap.sh`, `.p0ce_canary.log`, `.p0ce_inspect.sql`.

## U. Next recommendation

**IMMEDIATE — operator remediation for the 2 stuck events** (independent of the code fix; stops
the ongoing ~12 errors/hour described in §S):

```sql
UPDATE news_events SET status = 'ANALYZED', updated_at = now()
WHERE id IN ('7edc07d8-269f-4f18-bada-fa332d9f3358',
             'dc259b32-29cd-4e54-a3ea-7330cb445757')
  AND status = 'PROCESSING';   -- expect: UPDATE 2
```

Both are confirmed true duplicates whose redundant editorial task was correctly not created;
`ANALYZED` is the terminal state a working suppress-path would have left them in, and it removes
them from `_select_recovery_candidates` (which only selects `status == PROCESSING`).

**Do NOT re-enable the flag until the wiring defect is fixed.** The predicate itself is
validated safe — 57/57 clean on the shadow replay, 2/2 `TRUE_DUPLICATE` in the live canary, 0
false, 0 uncertain, 0 invariant violations, and no policy expansion is warranted (spec §22).

**Dev fix (small, out of scope for this phase):** in `_run_phase_b`'s suppress branch, advance
the event to a terminal status before/at the commit — mirror the invalid-title path
(`event.status = EventStatus.ANALYZED; await session.commit()`) so a suppressed event is never a
recovery candidate. Belt-and-suspenders: make `_apply_story_memory` idempotent — if a
`NewsEventStoryLink` already exists for `event.id`, treat the event as already-processed (no
second insert). Add a regression test that recovers a suppressed event and asserts no
`UniqueViolation` and a terminal status. Then re-run this constrained-enforcement canary
(deploy → flag on → ≥100 decisions / 6 h → audit every suppression).

**Operator remediation for the 2 stuck events (independent of the code fix):**
`UPDATE news_events SET status='ANALYZED', updated_at=now() WHERE id IN
('7edc07d8-269f-4f18-bada-fa332d9f3358','dc259b32-29cd-4e54-a3ea-7330cb445757') AND
status='PROCESSING';` — both are confirmed true duplicates whose redundant task was correctly
not created.

---

## FINAL VERDICT

**`STORY_CONTINUITY_P0_CONSTRAINED_ENFORCEMENT_ROLLED_BACK`**

The constrained enforcement predicate is **correct and safe**: shadow replay found 57
would-suppress with **0 false**; the live canary (1 h 54 m / 127 decisions) suppressed **2
editorial tasks, both `TRUE_DUPLICATE`** (Google-News RSS re-deliveries of byte-identical
headlines, `NO_DELTA`), with **0 `FALSE_SUPPRESSION`, 0 `UNCERTAIN`, 0 hard-invariant
violations**, only `automation_worker` changed, no migration, no publication/flag/Redis change.

Enforcement was **disabled** (§18) because it surfaced a **runtime-wiring defect** — a suppressed
event is left in `PROCESSING` with a committed `NewsEventStoryLink` and no task, so
stale-recovery re-processing of it raises a `news_event_story_links_pkey` `UniqueViolation`
(`phase9_triage_phase_b_failed`). No data corruption, no legitimate task loss, but a §18
auto-rollback trigger. Suppression is now OFF; `f98f583` stays deployed but inert
(shadow-equivalent). A small dev fix (advance a suppressed event to a terminal status) + a
re-run canary are required before re-enablement. No P1/P2, no clustering repair, no policy
change.
