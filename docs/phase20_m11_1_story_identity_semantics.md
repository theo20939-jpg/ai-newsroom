# Phase 20 CP4.4 — Story Identity Semantics (explicit definitions)

Companion to `docs/phase20_m11_1_story_identity_investigation.md` (the M11.1 root-cause/design
doc). That doc explains *why* the dispatch changed; this one defines *what the resulting relations
actually mean*, per Checkpoint 4's explicit request to make this precise before considering any
further change.

## The three relations

**1. Membership** — "this `NewsEvent` is part of this `Story`'s real event history."
Represented by a `NewsEventStoryLink` row whose `match_type ∈ {NEW_STORY, STORY_UPDATE,
SUPPORTING_SOURCE, SEMANTIC_DUPLICATE}`. Only these four outcomes bump `Story.event_count` - the
denormalized "how developed is this story" counter. `Story.entities`/`keywords`/`topic_bucket`
are computed once, at `NEW_STORY` time, from the *root* event only - a member added later via
`STORY_UPDATE`/etc. does not update the Story's own signature (a pre-existing, unchanged
convention from Phase 18.10, not touched this phase).

**2. Provisional membership** — "this `NewsEvent` is attached to this `Story`, but the match was
not confident enough to count as confirmed continuation." Represented by a `NewsEventStoryLink`
row with `match_type = UNCERTAIN_MATCH` **and** `entity_overlap >= _RELATED_STORY_ENTITY_FLOOR`
(the "stays attached" branch of the M11.1 dispatch). `Story.event_count` is *not* bumped. The
event's own title still becomes visible to the Delta Engine's prior-titles pool for that story
(`compute_story_delta()` queries every link row for a `story_id` regardless of `match_type` - a
pre-existing, disclosed behavior, not changed this phase) and to future candidate retrieval (the
Story itself, not this specific link, is what future events are scored against) - so a provisional
member can still contribute to how the story is perceived later, without being counted as
"confirmed."

**3. Related-to (non-membership)** — "this `NewsEvent` is NOT part of this `Story`, but shares a
real entity signal with it worth a diagnostic note." Represented, *transiently only*, by
`MatchResult(RELATED_STORY, matched_story_id=<Y>, ...)` at match time, logged via
`triage_orchestrator`'s own `phase18_10_story_memory_match` log line
(`services/triage_orchestrator.py`). **After M11.1, this relation is never persisted to the
database.** The event instead becomes the root of its own new `Story` (membership relation #1,
type NEW_STORY-equivalent); the fact that it was found "related to Y" exists only in that one log
line and is not queryable afterward. The link row's own `match_type` field is repurposed to record
`"related_story"` / `"uncertain_match"` as a *historical annotation of how this event's own root
Story was established* (i.e., "this Story exists because its founding event was only related-to,
not new outright"), not as a pointer to Y.

**4. Provisional root (new this phase)** — "this `NewsEvent` becomes the anchor of a brand-new
`Story`, but the founding evidence for that identity was itself uncertain or only loosely
related." This is the M11.1 fix's own new case: `RELATED_STORY` and weak-entity-overlap
`UNCERTAIN_MATCH` now create a `Story` exactly like `NEW_STORY` does (membership relation #1,
`event_count=1`, `first_event_id = this event`), distinguishable from a genuine `NEW_STORY` root
only via the link's own `match_type` field (`"related_story"` / `"uncertain_match"` instead of
`"new_story"`). No separate "confidence of the root itself" flag exists on `Story` - a reader has
to join back through `NewsEventStoryLink` on `first_event_id` to recover whether a given Story's
own root was confidently new or only provisionally so.

## The confirmed schema limitation

**`NewsEventStoryLink` cannot represent both "this event belongs to Story X" and "this event is
related to Story Y" at the same time.** `news_event_id` is the table's primary key - at most one
row per event, ever, by hard database constraint (a deliberate Phase 18.10 design choice - see
`database/models/story_link.py`'s own docstring on why story-linkage was never put directly on
`NewsEvent`). Before M11.1, this meant a `RELATED_STORY` event's *only* representable fact was "is
related to Y" (at the cost of never getting its own membership anywhere). After M11.1, it is the
reverse: the event gets real membership in its own new Story, but the "related to Y" fact is lost
the moment the triage cycle's transaction commits and the log line scrolls past.

**This limitation is disclosed, not solved, here.** A `related_story_id` (nullable) column on
`Story`, or a second, non-PK-constrained table (`story_relations(story_id, related_story_id,
entity_overlap, created_at)`), would let both facts coexist - but per Checkpoint 4's own
instruction, no migration is proposed this round. There is no evidence yet that anything would
consume that information if it existed (no capability, worker, or report currently reads
`RELATED_STORY` data at all beyond the `TriageCycleReport.story_related` counter added in M8) -
adding the schema ahead of a concrete consumer would be exactly the kind of premature migration
this phase's own guardrails warn against. If a future milestone needs genuine "these two Stories
are the same real-world entity family, cross-reference them for a reader" functionality, this is
the schema gap to revisit first.

## Fragmentation, named precisely

"Fragmentation" (the M11.1 cost measured in Checkpoint 3/4's replay) is precisely: the count of
Stories whose root event reached relation #4 (provisional root) rather than a genuine `NEW_STORY`.
Every provisional-root Story is a full, ordinary `Story` row in every other respect - it competes
in candidate retrieval exactly like any confidently-new Story, and can receive real future
membership growth via relation #1 exactly like any other Story (this is *why* no explicit
merge/convergence machinery was needed - see the M11.1 investigation doc's own §5, point 4). The
cost is real (an extra row, an extra competing candidate in retrieval) but structurally bounded -
a fragmented Story behaves identically to a real one from that point forward, it just may never
receive the growth a "true" root would have, and may itself be an unnecessary duplicate of a
"real" root Story it should have been (relation #4's own weak evidence, by definition, cannot
guarantee otherwise).
