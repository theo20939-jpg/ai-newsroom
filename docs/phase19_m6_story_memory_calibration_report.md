# Phase 19 M6 — Story Memory Calibration Report

Status: **calibration complete for this run. Real/human-review packet awaits human labeling —
no real-world precision/recall claim is made from it.** Synthetic-fixture precision/recall is
real, computed, and reported below.

This is the mandatory M6 safety gate required before continuing Phase 19 M7–M16 (overnight
authorization, section 8/9). `services/story_memory.py` — its thresholds, its category/
topic_bucket gate, and `story_memory_mode`'s default (`"off"`) — is **not modified** by this
milestone. This milestone only measures.

## 0. Method

Two datasets, kept explicitly separate, never blended:

1. **Synthetic regression fixtures** (`scripts/_phase19_m6_synthetic_fixtures.py`) — designed
   ground truth, run through the real `services.story_memory.match_story()` against a disposable
   Postgres database (`phase19_m6_synthetic`, isolated container, migrated to head via
   `alembic upgrade head`, dropped after this run). Ground truth is legitimate here because these
   cases are constructed, not blank human labels standing in for real judgment.
2. **Real/human-review calibration packet** (`scripts/_phase19_m6_real_data_replay.py` →
   `scripts/_phase19_m6_build_calibration_packet.py` → `scripts/_phase19_m6_render_calibration_
   packet.py` → `docs/phase19_m6_human_review_packet.md`) — every real, non-`UNKNOWN`-category
   `NewsEvent` row in the real `ai_newsroom` database (read-only: title/category/timestamps only,
   never content/url), replayed chronologically through the real `match_story()` against a
   *second*, separate disposable database (`phase19_m6`). The real database was never written to.

Both disposable databases were created fresh for this run, migrated via `alembic upgrade head`
(never the real DB), and dropped afterward. See section 4 for the exact revision-unchanged proof.

## 1. Synthetic regression fixtures — real, computed metrics

Six fixture sets, one per required category (A–F), each run in a freshly-truncated scope so no
set's stories can leak into another's matching (`_reset_story_tables()` — an early run without
this isolation showed `wrong_category` contamination between sets B and F using an unintentionally
similar "GPT-6" title; fixed before these numbers were produced). Raw results:
`scripts/_phase19_m6_synthetic_fixture_results.json`.

| Category | Label | Scored cases | Recall (any match) | Recall (confident match only) | Precision | False-merge rate (negative cases) |
|---|---|---|---|---|---|---|
| A | Same story across categories (Muse-Code class) | 6 | 0.17 (1/6) | 0.00 (0/6) | 1.00 | n/a (no negative cases) |
| B | Same story across sources (single category) | 2 | 1.00 (2/2) | 1.00 (2/2) | 1.00 | n/a |
| C | Genuine story updates | 2 | 1.00 (2/2) | 0.00 (0/2) | 1.00 | n/a |
| D | Supporting confirmations | 2 | 0.50 (1/2) | 0.50 (1/2) | 1.00 | n/a |
| E | Similar companies, different events | 2 | n/a (no positive cases) | n/a | n/a | 0.00 (0/2) |
| F | Different stories, same entity | 1 | n/a (no positive cases) | n/a | n/a | 0.00 (0/1) |
| **Aggregate** | | **15** | **0.50 (6/12)** | **0.25 (3/12)** | **1.00 (6/6)** | **0.00 (0/3)** |

**Reading this**:

- **Zero false merges anywhere** (precision 1.00 aggregate, false-merge rate 0.00 on every
  negative-case category). The category/topic_bucket gate plus the entity/title-overlap scoring
  never confidently merged two genuinely distinct stories in this run, including the "same entity,
  different topic" case (F) that is specifically designed to tempt a naive entity-only matcher.
- **Category A (cross-category same story) has by far the worst recall**: only 1 of 6 expected
  merges was found at all (as `UNCERTAIN_MATCH`, not a confident merge) — the other 5 landed as
  `NEW_STORY`. This is not a new finding — it independently reproduces the exact, already-
  documented Muse-Code failure class from `docs/phase18_10_editorial_intelligence_report.md`
  §7-9 (which found 1-of-7 on the real historical titles this fixture set reuses verbatim), and
  confirms the root cause is structural: `match_story()`'s hard `topic_bucket` gate never even
  scores a candidate in a different bucket, regardless of entity/title similarity.
- **Within a single category/topic_bucket, recall is much better** (B: 2/2, C: 2/2, D: 1/2) —
  the system reliably catches same-bucket duplication, though not always at *confident* strength
  (C's two genuine updates both landed as `UNCERTAIN_MATCH`, correctly found but not confidently
  classified — a downstream consumer that only acts on `STORY_UPDATE`/`SUPPORTING_SOURCE`/
  `SEMANTIC_DUPLICATE` would miss these two).

## 2. Real/human-review calibration packet — composition and coverage (no precision/recall claim)

**Source data**: 9,450 real, non-`UNKNOWN`-category `NewsEvent` rows (title/category/timestamps
only — the real database's full current content as of this run), replayed chronologically through
the real `match_story()` against an isolated disposable database
(`scripts/_phase19_m6_real_data_replay.py` → `scripts/_phase19_m6_real_replay_predictions.json`).

**Machine-prediction outcome distribution** (before any sampling):

| Outcome | Count | % of total |
|---|---|---|
| `new_story` | 8,636 | 91.4% |
| `uncertain_match` | 464 | 4.9% |
| `semantic_duplicate` | 255 | 2.7% |
| `story_update` | 78 | 0.8% |
| `supporting_source` | 17 | 0.2% |

**Packet composition** (`docs/phase19_m6_human_review_packet.md`, 80 stratified items + 20
cross-category candidate groups, well above the ≥50-case target):

- Part 1 — stratified sample by machine outcome, seed `19.6`: 15 each of `semantic_duplicate`,
  `story_update`, `supporting_source`, `uncertain_match` (every non-`new_story` outcome type is
  capped at 15, well under its available pool), plus a 20-item random spot-check of `new_story`
  cases (to help a human catch possible missed merges — the system cannot flag its own false
  negatives).
- Part 2 — 20 cross-category/cross-topic-bucket entity-overlap candidate groups (heuristic-only,
  bounded to a 72-hour window and 2-5 members per group). Spot-checking a sample of these while
  building the packet showed genuine, correct near-duplicate catches within a topic_bucket (e.g.
  two sources' near-identical titles for the same PR/CI event, two "ETF" market-commentary
  pieces), alongside expected heuristic noise from generic recurring entities ("New York",
  "GPT-5.6") spanning genuinely unrelated stories — exactly the kind of noise the packet's own
  framing discloses and asks a human reviewer to filter, never a scored claim on this script's part.

**Coverage**: every real, non-`UNKNOWN`-category `NewsEvent` currently in the database was
replayed (no sampling at the prediction stage — only the review packet itself is a sample of the
9,450 predictions). `UNKNOWN`-category events (6,504 of 15,954 total) were excluded from the
replay entirely, since `match_story()`'s own category-scoped candidate query would put all of them
in one large, editorially meaningless bucket together.

Every `human_decision`/`human_notes` field in `docs/phase19_m6_human_review_packet.md` is
genuinely blank — nothing was filled in automatically. **No real-world precision/recall figure is
computed or claimed from this packet in this report** — there is nothing to compare machine
predictions against until a human actually reviews and labels the items. This section reports
only composition and coverage, per the overnight authorization's explicit instruction (section 8):
"If human labels are blank, do NOT claim final real-world precision/recall from them. Instead
report: packet composition; coverage; machine predictions awaiting human review."

## 3. M6 automatic decision gate

Per the overnight authorization (section 9), classifying into A/B/C:

**Classification: B — STORY MEMORY QUALITY UNRESOLVED**, with the cross-category recall gap
falling under the "hypothetical future enforce behavior" branch of Case C (section 9's own
guidance: a defect affecting only hypothetical future `enforce` behavior should be documented,
not stopped on, with M7/M8 kept shadow-only and M9–M16 continuing independently).

Reasoning:

- `story_memory_mode` defaults `"off"` in code (`core/config.py`) and is **not set at all** in
  the real deployment's `.env` (confirmed by inspection — the variable is simply absent, so the
  code default applies). The real database does not even have the `stories`/
  `news_event_story_links` tables migrated yet (real DB revision `31a8d7c95c87`, which predates
  migration `c2bc6affb100 "add story memory tables"` in the chain). **Story Memory has zero
  effect on current production behavior today**, regardless of this calibration's findings.
- The cross-category recall gap (category A) is not a new discovery — it is an independent
  reproduction of an already-documented, already-quantified limitation
  (`docs/phase18_10_editorial_intelligence_report.md` §7-9). Nothing here changes what was already
  known and disclosed.
- No false merges were found anywhere (precision 1.00, false-merge rate 0.00) — the system's
  known failure mode is under-merging (missing real duplicates), never over-merging (falsely
  linking distinct stories). This is the safer direction for a shadow-only feature: a missed
  duplicate today only means the same story text gets its own scaffold row for review; it never
  causes an incorrect action, since Story Memory does not gate publication, ranking, or delivery
  in this phase.

**Per section 9's Case B rule**: M7/M8 continue, but only in a way that is provably shadow-only
and cannot influence Copywriting, ranking, publication, Telegram routing, or task selection — both
are marked **"CALIBRATION PENDING HUMAN REVIEW"** below and in their own milestone docs. M9–M16
continue independently, unaffected by this finding (none of them depend on Story Memory being
accurate).

**This finding does not authorize any threshold change, gate removal, or `enforce` activation** —
none is proposed or made in this run.

### 3.1 A second, more concrete finding: `story_memory_mode="shadow"` is not yet actually safe for Telegram delivery

While tracing how Story Memory reaches Telegram delivery (relevant to scoping M7), a real,
already-committed defect was confirmed in `worker/content_cycle.py` (Phase 18.10 M3, commit
`634a8b9`, lines ~220-246 as of this branch): the reply-threading computation — including a
fail-closed `continue` that can skip sending a completed `ContentDraft` to Telegram entirely — is
gated directly on `if settings.story_memory_mode != "off":`, not on an independent setting. This
means `story_memory_mode="shadow"` does **not** actually leave "publication behavior completely
unchanged" as its own `core/config.py` comment claims — it can change which message a post replies
to, or suppress a Telegram send altogether, the moment it is enabled. This is exactly the gap
`docs/phase19_m0_audit.md` §7 already disclosed and exactly what `telegram_story_reply_mode`
(already scaffolded in `core/config.py`, currently unconsumed by any code) is designed to fix —
now implemented as the core of Phase 19 M7 (see `docs/phase19_m7_story_timeline_and_reply_routing.md`).

This does **not** change today's production behavior — `story_memory_mode` defaults `"off"` and is
unset in the real `.env`, so the buggy branch is never entered under current default settings. It
does mean `story_memory_mode="shadow"` should not be turned on in production until M7's fix ships
(now true as of this run) and is itself validated — this is exactly the "hypothetical future
[mode] behavior" branch of the overnight authorization's Case C guidance (section 9): documented,
not redesigned overnight, M7 kept shadow-only, M9–M16 continue independently.

## 4. Real DB revision proof (unchanged by this milestone)

```
REAL DB REVISION BEFORE THIS MILESTONE: 31a8d7c95c87
REAL DB REVISION AFTER THIS MILESTONE:  31a8d7c95c87
```

Both disposable databases used in this milestone (`phase19_m6`, `phase19_m6_synthetic`) ran in
isolated, throwaway Docker containers on non-default ports, migrated independently, and were
dropped (container + anonymous volume) after use. The real database was only ever read from
(a single `SELECT id, title, category, collected_at, published_at FROM news_events WHERE
category != 'UNKNOWN'` query), never written to.

## 5. What this milestone does NOT do

- Does not change `_LOW_THRESHOLD`/`_HIGH_THRESHOLD`, the topic_bucket keyword lists, or the
  entity/title-overlap weighting in `services/story_memory.py`.
- Does not change `story_memory_mode`'s default or set it anywhere.
- Does not remove or weaken the category/topic_bucket gate — section 4's own reasoning is that
  the gate's conservatism (zero false merges) is a feature to preserve, not a bug to route around
  overnight.
- Does not claim the cross-category gap is fixed, tuned, or scheduled for a fix in this phase —
  it is documented as a known, pre-existing, still-open limitation.
