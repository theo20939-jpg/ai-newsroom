# Phase 20 M11.1 — Story Identity Investigation & Design

**Status: investigation + design, written before any implementation, per explicit instruction.**

## 1. Current dispatch behavior (`services/triage_orchestrator.py::_apply_story_memory()`), exact

All six outcomes go through the same function. `match_story()` returns `(signature, MatchResult)`.
`MatchResult` currently exposes only `outcome`, `matched_story_id`, `confidence`,
`similarity_reason` — **no entity/title overlap component is exposed to the caller**, only
embedded as free text inside `similarity_reason`.

| Outcome | Story row created? | `event_count` bumped? | `story_id` used for the link |
|---|---|---|---|
| `NEW_STORY` | **Yes** — fresh `Story(id=uuid4(), title=event.title, ...)` | n/a (starts at 1) | the new story's own id |
| `STORY_UPDATE` | No | **Yes** | `result.matched_story_id` (an existing story) |
| `SUPPORTING_SOURCE` | No | **Yes** | `result.matched_story_id` |
| `SEMANTIC_DUPLICATE` | No | **Yes** | `result.matched_story_id` |
| `UNCERTAIN_MATCH` | **No** | No | `result.matched_story_id` (whatever scored best in `[0.35, 0.65)`, possibly unrelated) |
| `RELATED_STORY` | **No** | No | `result.matched_story_id` (the "related", explicitly NOT-same, story) |

`NewsEventStoryLink.news_event_id` is the table's **primary key** — at most one link row per
event, ever, by hard DB constraint. `_apply_story_memory()` always does a plain `session.add(...)`
(an INSERT); nothing in this codebase ever re-evaluates or updates an existing link. So today,
whatever `story_id` gets written for an event at triage time is **permanent** — there is no retry,
no re-scoring, no reconciliation mechanism, regardless of how uncertain the original match was.

## 2. Why this breaks Kitesurf and the AI Olympiad root event, precisely

- **`RELATED_STORY`** is, by its own construction in `score_candidate()`/`match_story()`, already
  a *confident* signal that this is a **different** story (`combined < 0.35`, i.e. below even the
  low bar) with just enough real entity signal (`entity_overlap >= 0.2`) to be worth a
  cross-reference note. Despite that, `_apply_story_memory()` attaches the event to the *related*
  story's `story_id` and never creates a story of its own — so the event that is, semantically,
  the start of a *new* story never gets one. This is exactly Kitesurf's root event (`12b1736c`):
  it scored `RELATED_STORY` against an unrelated older story, so no "Kitesurf" story ever existed
  for the second Kitesurf article to find.
- **`UNCERTAIN_MATCH`** is genuinely ambiguous by definition (`combined ∈ [0.35, 0.65)`) — it can
  legitimately be the same story (Moscow pair: `entity_overlap=0.4`, `combined=0.528`, and it
  correctly pointed at its true sibling in the M11 replay) or a coincidental crossing of the low
  threshold against something wholly unrelated (AI Olympiad's root event 4: no real prior sibling
  existed yet, so it landed on *whatever* aged, unrelated story happened to score marginally over
  0.35). In both cases `_apply_story_memory()` does the same thing — attach, don't bump — so there
  is no way today to tell these two situations apart downstream, and no story is ever created for
  the "coincidental" case either.

## 3. The invariant

**A real `NewsEvent` must not permanently lose the ability to become the root/anchor of its own
`Story` merely because its first comparison against older Stories is uncertain or only loosely
related.**

Constraint: do **not** blindly create a new `Story` for every `UNCERTAIN_MATCH` — Moscow proves
that attaching to the existing candidate is sometimes exactly correct, and blind fragmentation
would (a) regress Moscow, and (b) directly worsen M11.2's own candidate-pool dilution problem by
adding hundreds more low-value provisional stories into every future retrieval.

## 4. Design considered and rejected

- **New `related_story_id`/`provisional_parent_id` column on `Story`, tracking explicit
  relationships between stories** — rejected as larger than necessary. It would require a new
  migration (beyond the already-created, unapplied M10 one) and machinery to actually *use* the
  relationship later (a retroactive-merge operation this codebase has never had to build). Given
  the "smallest architecture-compatible solution" instruction, this is deferred, not adopted.
- **Always create a new Story for `UNCERTAIN_MATCH`** — rejected: regresses Moscow, worsens
  dilution.
- **Never create a new Story for `RELATED_STORY` (status quo)** — rejected: this is the direct,
  confirmed cause of the Kitesurf regression; `RELATED_STORY`'s own module docstring already
  states it should be "non-blocking" and never the event's sole identity.

## 5. Chosen design (smallest, reuses existing `Story` + `NewsEventStoryLink` lifecycle, no new
table, no new migration)

1. **`RELATED_STORY` now creates its own fresh `Story` for the event**, exactly like `NEW_STORY`
   does (same code path). The link's `match_type` still records `"related_story"` and
   `match_score` still records the (low) combined score, preserving the informational
   cross-reference for observability — only the *identity* consequence changes. This is a direct,
   semantically-obvious correction: `RELATED_STORY` already means "confidently a different story";
   the only bug was never actually creating that different story.
2. **`UNCERTAIN_MATCH` is split into two sub-cases using `entity_overlap`** — an *already-computed,
   already-existing* value from `score_candidate()` (not a new signal), compared against the
   *already-existing* `_RELATED_STORY_ENTITY_FLOOR = 0.2` constant (not a new threshold — reusing
   the exact same, already-calibrated-in-M5 boundary, not inventing a new number):
   - `entity_overlap >= 0.2` (real, substantial entity signal, like Moscow's 0.4): **unchanged
     behavior** — attach to the existing candidate, no story created, no event_count bump. This is
     the "genuinely could be the same story, worth keeping provisionally attached" case.
   - `entity_overlap < 0.2` (weak/coincidental token overlap, like AI Olympiad event 4's landing):
     **create the event's own fresh Story**, exactly like `NEW_STORY`. The link's `match_type`
     still records `"uncertain_match"` and `match_score` the original combined score — the
     *comparison* that was attempted is still fully observable, only the identity consequence
     changes.
3. **`MatchResult` gains an explicit `entity_overlap: float` field** (`services/story_memory.py`)
   — the only structural code change needed to make step 2 possible. Not a schema/migration change
   (an in-memory dataclass, not a DB table); populated at every existing return site from values
   `match_story()` already computes internally today.
4. **No explicit "merge" or "convergence" machinery is added.** "Later strong evidence can
   converge onto the correct Story" (test case 4) is achieved for free by the *existing* retrieval
   + classification pipeline: a later, more decisive event scores against *all* recent stories
   (fragmented provisional ones included, since they participate in `_fetch_candidate_stories`
   like any other `Story`) and, if it clears `STORY_UPDATE`/`SUPPORTING_SOURCE`/
   `SEMANTIC_DUPLICATE`'s confident band against one of them, attaches there normally — genuinely
   converging the *cluster's future growth* onto one story going forward, without needing to
   retroactively re-parent already-linked events. This does not undo the initial fragmentation
   (the earlier provisional story still exists as a small, separate row) — a full retroactive merge
   is explicitly out of scope as "not the smallest fix."

## 6. Known residual limitation of this design (disclosed, not solved here)

Splitting `UNCERTAIN_MATCH` by a fixed `entity_overlap` cutoff is a heuristic, not a proof — a
genuinely-the-same story with weak entity extraction (e.g., a paraphrase using no shared
capitalized nouns) could still be wrongly forked into its own story. This is a strictly better
failure mode than today's (which *silently* attaches to something unrelated with equal
confidence either way) but is not perfect. M11.3's same-dataset replay will measure whether this
introduces new fragmentation without fixing convergence, and Checkpoint 3 will report that
honestly rather than assume success.
