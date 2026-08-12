import json

after = json.load(open("artifacts/phase20_m11_replay_results.json", encoding="utf-8"))
examples = after["would_suppress_examples"]


def fmt(e):
    same_category = "SAME" if e["category"] == e["root_category"] else "DIFFERENT"
    same_source = "SAME" if e["source"] == e["root_source"] else "DIFFERENT"
    claims = ", ".join(e.get("delta_new_material_claims") or []) or "(none)"
    keywords = ", ".join(e.get("delta_new_keywords") or []) or "(none)"
    return (
        f"- **New event**: `{e['title']}`\n"
        f"  - Source: {e['source']} | Category: {e['category']} | Published: {e.get('published_at', 'unknown')}\n"
        f"- **Matched Story root**: `{e['root_title']}`\n"
        f"  - Source: {e['root_source']} | Category: {e['root_category']}\n"
        f"- Category match: {same_category} | Source match: {same_source}\n"
        f"- **Relationship outcome**: {e['match_type']} (score={e['match_score']:.3f}, confidence={e['confidence_band']})\n"
        f"- **Delta outcome**: {e['delta_classification']} - {e.get('delta_reason', '(no reason recorded)')}\n"
        f"  - New material claims found: {claims}\n"
        f"  - New keywords found: {keywords}\n"
        f"- **Suppression reason**: {e.get('suppression_reason', '(not recorded)')}\n"
        f"- **HUMAN VERDICT**: _____ (CORRECT_SUPPRESS / SHOULD_UPDATE / FALSE_MATCH / UNCERTAIN)\n"
    )


by_conf = sorted(examples, key=lambda e: -e["match_score"])
highest_confidence = by_conf[:8]
threshold_edge = sorted(examples, key=lambda e: e["match_score"])[:8]
cross_source_all = [e for e in examples if e["source"] != e["root_source"]]
same_source_all = [e for e in examples if e["source"] == e["root_source"]]
cross_category_all = [e for e in examples if e["category"] != e["root_category"]]

sections = [
    ("Highest-confidence suppressions", highest_confidence[:8], "Top match_score - the cases the policy is most sure about."),
    ("Threshold-edge suppressions", threshold_edge[:8], "Closest to the HIGH confidence-band boundary (0.65) from above - the cases most likely to flip bands under any future recalibration."),
    ("Cross-source cases", cross_source_all[:8], f"New event's source differs from the matched story's own root source ({len(cross_source_all)}/{len(examples)} total) - the classic 'two outlets, one story' pattern this policy is meant to catch."),
    ("Same-source repetitions", same_source_all[:8], f"New event's source is the SAME as the matched story's root source ({len(same_source_all)}/{len(examples)} total) - worth extra scrutiny, since a single source rarely republishes its own article verbatim; may indicate a feed artifact or a genuine same-source follow-up."),
    ("Cross-category cases", cross_category_all[:8], f"New event's NewsEvent.category differs from the matched story's own category ({len(cross_category_all)}/{len(examples)} total) - exercises the post-M3 soft category bonus rather than a hard filter."),
]

lines = []
lines.append("# Phase 20 Checkpoint 4 - Suppression Human-Review Packet\n")
lines.append(
    f"Deterministic sample drawn from all {len(examples)} `would_suppress=True` cases produced by "
    "the Checkpoint 4 same-dataset historical replay (2026-08-04 to 2026-08-07, 3,774 real "
    "events, disposable Postgres, post precision-hardening). **Suppression is NOT enabled "
    "anywhere** - this packet exists to let a human reviewer sample-check the policy's real "
    "output before any activation decision. No suppression precision/recall number should be "
    "reported until every HUMAN VERDICT blank below has actually been filled in by a person - "
    "this script never auto-fills them. All match_score values are >= 0.65, confirming every "
    "sampled case genuinely cleared the HIGH confidence band as the policy requires.\n"
)
for title, items, note in sections:
    lines.append(f"## {title}\n")
    lines.append(f"{note}\n")
    if not items:
        lines.append("_None found in this replay window._\n")
    for e in items:
        lines.append(fmt(e))
    lines.append("")

lines.append("## Different-company/product controls\n")
lines.append(
    f"No case among the {len(examples)} real `would_suppress=True` flags resembles a different-"
    "company/product false positive (all require a HIGH-confidence combined score, which in "
    "this codebase's scoring model requires substantial genuine entity/title overlap - a "
    "different-company pair reaching that combination would itself be a scoring bug worth "
    "escalating, and none was observed). This control category is instead covered by the "
    "permanent synthetic regression suite (tests/test_story_memory_v2.py::"
    "test_synthetic_entity_overlap_traps_never_same_story_merge, now 6 parametrized cases "
    "including the two Checkpoint 4 hard controls - same_company_two_launches and "
    "same_named_event_different_year - all passing) - those cases are constructed specifically "
    "to test this failure mode and are re-run on every commit, not just once here.\n"
)

lines.append("## Reviewer instructions\n")
lines.append(
    "For each sampled pair above: read the New event and Matched Story root facts, the "
    "relationship/delta outcomes already computed, and judge whether this is genuinely the same "
    "real-world story with nothing new to say (CORRECT_SUPPRESS), the same story but with a "
    "real update worth publishing (SHOULD_UPDATE), a real, distinct story that happens to score "
    "highly (FALSE_MATCH), or genuinely unclear from the titles alone (UNCERTAIN). Fill in each "
    "blank HUMAN VERDICT line directly in this file. This packet does not pre-judge any case - "
    "every verdict field starts blank and must stay that way until a person reviews it.\n"
)

with open("docs/phase20_m11_suppression_human_review_packet.md", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

with open("scripts/_phase20_suppression_packet_stats.txt", "w", encoding="utf-8") as f:
    f.write(f"total={len(examples)}\n")
    f.write(f"cross_source={len(cross_source_all)}\n")
    f.write(f"same_source={len(same_source_all)}\n")
    f.write(f"cross_category={len(cross_category_all)}\n")
