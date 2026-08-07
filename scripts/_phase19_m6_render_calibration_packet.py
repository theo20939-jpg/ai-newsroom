"""Phase 19 M6 - renders docs/phase19_m6_human_review_packet.md from
scripts/_phase19_m6_human_review_selection.json. Pure formatting, no DB access, no network.
Every `human_decision`/`human_notes` field is emitted genuinely blank - mirrors scripts/
_phase18_5_render_human_review_packet.py's own explicit "never pre-filled or guessed" discipline.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_SELECTION_PATH = Path(__file__).with_name("_phase19_m6_human_review_selection.json")
_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "phase19_m6_human_review_packet.md"

_OUTCOME_ORDER = ["semantic_duplicate", "story_update", "supporting_source", "uncertain_match", "new_story"]
_OUTCOME_TITLE = {
    "semantic_duplicate": "SEMANTIC_DUPLICATE (system says: near-identical rehash)",
    "story_update": "STORY_UPDATE (system says: confident match, new substance)",
    "supporting_source": "SUPPORTING_SOURCE (system says: confident match, corroborating)",
    "uncertain_match": "UNCERTAIN_MATCH (system says: borderline, not confident either way)",
    "new_story": "NEW_STORY spot-check (system says: unrelated to anything seen before)",
}
_DECISION_OPTIONS = "`correct_match` / `incorrect_match` / `missed_match` / `unsure`"


def _render_outcome_item(index: int, item: dict) -> str:
    matched = (
        f"matched story: \"{item['matched_story_title']}\" (`{item['matched_story_id']}`)"
        if item.get("matched_story_id")
        else "no matched story (this is a NEW_STORY spot-check item - check whether it should "
        "actually have matched something the system has already seen)"
    )
    return f"""### {index}. {item['title']}

- **real_event_id**: `{item['real_event_id']}`
- **category**: {item['category']}
- **topic_bucket**: {item['topic_bucket']}
- **collected_at**: {item['collected_at']}
- **system outcome**: `{item['outcome']}` (confidence {item['confidence']:.2f})
- **system reasoning**: {item['similarity_reason']}
- **{matched}**

**human_decision** ({_DECISION_OPTIONS}): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---
"""


def _render_cross_category_group(index: int, group: dict) -> str:
    events_lines = []
    for e in group["events"]:
        events_lines.append(
            f"  - \"{e['title']}\" — category={e['category']}, topic_bucket={e['topic_bucket']}, "
            f"collected_at={e['collected_at']}, system outcome=`{e['outcome']}` (`{e['real_event_id']}`)"
        )
    events_block = "\n".join(events_lines)
    return f"""### Group {index}: shared entity "{group['shared_entity']}" across topic_buckets {group['topic_buckets']}

{events_block}

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---
"""


def main() -> None:
    data = json.loads(_SELECTION_PATH.read_text(encoding="utf-8"))
    stratified = data["stratified_by_outcome"]
    cross_category = data["cross_category_entity_overlap_candidates"]

    sections = ["## Part 1 — stratified sample by system outcome\n"]
    counter = 1
    total_stratified = 0
    for outcome in _OUTCOME_ORDER:
        rows = stratified.get(outcome, [])
        total_stratified += len(rows)
        sections.append(f"### {_OUTCOME_TITLE[outcome]} — {len(rows)} items\n")
        if not rows:
            sections.append("_No real events landed in this outcome in the replayed sample._\n\n---\n")
            continue
        for item in rows:
            sections.append(_render_outcome_item(counter, item))
            counter += 1

    sections.append(
        "\n## Part 2 — cross-category / cross-topic-bucket entity-overlap candidates "
        f"({len(cross_category)} groups)\n\n"
        "Heuristic-only surfacing (never a scored claim - see docs/phase19_m6_story_memory_"
        "calibration_report.md's own explicit separation of this from the synthetic fixtures' "
        "real precision/recall numbers): real event pairs sharing a distinctive, multi-word "
        "entity within a 72-hour window that landed in *different* topic_buckets - exactly the "
        "shape of the known Muse-Code failure class "
        "(docs/phase18_10_editorial_intelligence_report.md sec7-9), applied to real, current "
        "production data. A human reviewer's job here is to say whether each group is genuinely "
        "one real-world story the topic_bucket gate incorrectly split apart, or a coincidental "
        "entity collision across unrelated stories.\n\n"
    )
    if not cross_category:
        sections.append("_No candidate groups found in the replayed sample._\n")
    else:
        for i, group in enumerate(cross_category, start=1):
            sections.append(_render_cross_category_group(i, group))

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"""# Phase 19 M6 — Real/Human-Review Calibration Packet

Status: **ready for human review — every `human_decision`/`human_notes` field below is
intentionally blank.** Nothing in this document was filled in automatically. Machine predictions
only; no ground truth exists for these items until a human fills them in.

**{total_stratified} stratified real-event items** (Part 1) + **{len(cross_category)} cross-category
candidate groups** (Part 2), drawn from a real, read-only replay of
**{data['generated_from_predictions_count']} real `NewsEvent` rows**
(`scripts/_phase19_m6_real_data_replay.py`, generated {generated_at}) through the real
`services.story_memory.match_story()` against a disposable database - the real ai_newsroom
database was never written to. Selection was a deterministic random sample (seed `19.6`,
reproducible via `scripts/_phase19_m6_build_calibration_packet.py`).

This packet does **not** by itself establish real-world precision/recall - see
`docs/phase19_m6_story_memory_calibration_report.md` for why (blank human labels cannot yet be
compared against anything) and for the separately-computed synthetic-fixture metrics
(`scripts/_phase19_m6_synthetic_fixtures.py`), which use designed, not blank, ground truth.

## How to use this packet

**Part 1** — for each item, record:

- **human_decision** — one of {_DECISION_OPTIONS}
- **human_notes** — free text: why, what evidence would change your mind

**Part 2** — for each group, record whether it is genuinely one real-world story split across
topic_buckets (`same_story`), genuinely unrelated (`different_stories`), or `unsure`.

---

"""
    _OUTPUT_PATH.write_text(header + "\n".join(sections), encoding="utf-8")
    print(f"Wrote {total_stratified} stratified items + {len(cross_category)} candidate groups to {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
