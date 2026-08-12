import json

r = json.load(open("artifacts/phase20_m11_replay_results.json", encoding="utf-8"))
examples = r["would_suppress_examples"]
non_suppress = r["non_suppress_control_examples"]
material_update = r["material_update_control_examples"]

_AGGREGATOR_MARKERS = ("Google News", "Yandex News", "Bing News")


def is_aggregator(source: str) -> bool:
    return any(m in (source or "") for m in _AGGREGATOR_MARKERS)


def fmt_suppress(e, idx):
    linked = e.get("linked_events") or []
    prev_titles = "; ".join(f"{le['title']} ({le['source']})" for le in linked) or "(none captured)"
    sources = sorted({le["source"] for le in linked}) or [e.get("root_source", "?")]
    claims = ", ".join(e.get("delta_new_material_claims") or []) or "(none)"
    keywords = ", ".join(e.get("delta_new_keywords") or []) or "(none)"
    return (
        f"### Case {idx}\n\n"
        f"**NEW EVENT**\n"
        f"- event_id: `{e['event_id']}`\n"
        f"- title: {e['title']}\n"
        f"- source: {e['source']}\n"
        f"- category: {e['category']}\n"
        f"- published_at: {e.get('published_at', 'unknown')}\n"
        f"- short evidence summary: {e.get('delta_reason', '(no reason recorded)')}"
        f" (new keywords: {keywords}; new material claims: {claims})\n\n"
        f"**MATCHED STORY**\n"
        f"- story_id: `{e['story_id']}`\n"
        f"- root title: {e.get('root_title', '?')}\n"
        f"- previous linked event titles: {prev_titles}\n"
        f"- source list: {', '.join(sources)}\n"
        f"- most recent known facts: (see linked-event titles above - no separate fact ledger persisted)\n\n"
        f"**DECISION**\n"
        f"- match_type: {e['match_type']}\n"
        f"- match_score: {e['match_score']:.3f}\n"
        f"- confidence band: {e['confidence_band']}\n"
        f"- delta classification: {e['delta_classification']}\n"
        f"- would_suppress: True\n"
        f"- reason: {e.get('suppression_reason', '?')}\n\n"
        f"**HUMAN VERDICT**:\n"
        f"[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN\n"
    )


def fmt_control(e, idx, *, would_suppress_value):
    return (
        f"### Control {idx}\n\n"
        f"**NEW EVENT**\n"
        f"- event_id: `{e['event_id']}`\n"
        f"- title: {e['title']}\n"
        f"- source: {e['source']}\n"
        f"- category: {e['category']}\n"
        f"- published_at: {e.get('published_at', 'unknown')}\n"
        f"- short evidence summary: {e.get('delta_reason', '(no reason recorded)')}\n\n"
        f"**MATCHED STORY**\n"
        f"- story_id: `{e['story_id']}`\n"
        f"- root title: {e.get('root_title', '?')}\n\n"
        f"**DECISION**\n"
        f"- match_type: {e['match_type']}\n"
        f"- match_score: {e['match_score']:.3f}\n"
        f"- confidence band: {e['confidence_band']}\n"
        f"- delta classification: {e['delta_classification']}\n"
        f"- would_suppress: {would_suppress_value}\n\n"
        f"**HUMAN VERDICT**:\n"
        f"[ ] CORRECT_SUPPRESS  [ ] SHOULD_UPDATE  [ ] FALSE_MATCH  [ ] UNCERTAIN\n"
    )


# --- stratify ---------------------------------------------------------------------------------
seen_ids: set[str] = set()


def take(pool, n, key=None, reverse=False):
    items = sorted(pool, key=key, reverse=reverse) if key else list(pool)
    out = []
    for e in items:
        if e["event_id"] in seen_ids:
            continue
        out.append(e)
        seen_ids.add(e["event_id"])
        if len(out) >= n:
            break
    return out


# Rarest categories claim first, so a scarce match_type isn't accidentally swallowed by a
# generic top/bottom score scan before its own dedicated section gets a chance at it.
supporting_src = take([e for e in examples if e["match_type"] == "supporting_source"], 10)
confirmation_only_remaining = take([e for e in examples if e["delta_classification"] == "confirmation_only"], 10)
distinctive_diff = take([e for e in examples if e.get("delta_new_keywords")], 8)
semantic_dup = take([e for e in examples if e["match_type"] == "semantic_duplicate"], 10)
highest_confidence = take(examples, 8, key=lambda e: e["match_score"], reverse=True)
threshold_edge = take(examples, 8, key=lambda e: e["match_score"])
cross_source = take([e for e in examples if e["source"] != e["root_source"]], 8)
cross_category = take([e for e in examples if e["category"] != e["root_category"]], 8)
same_source = take([e for e in examples if e["source"] == e["root_source"]], 8)
aggregator_repeats = take([e for e in examples if is_aggregator(e["source"]) and is_aggregator(e["root_source"])], 8)

_notes = {
    "SUPPORTING_SOURCE cases": (
        f"Only 1 of 173 `would_suppress=True` cases is `SUPPORTING_SOURCE` (172 are "
        "`SEMANTIC_DUPLICATE`) - included here if found." if not supporting_src else None
    ),
    "Remaining CONFIRMATION_ONLY cases": (
        "0 found - every one of the 173 `would_suppress=True` cases is now `delta_classification="
        "no_new_facts`. This fully confirms the Checkpoint 4 delta-engine fix: no case reaches "
        "suppression eligibility via the CONFIRMATION_ONLY path anymore in this replay."
        if not confirmation_only_remaining else None
    ),
    "Cases with some distinctive keyword difference (extra scrutiny)": (
        "0 found - structurally guaranteed: `NO_NEW_FACTS` (the only delta classification present "
        "in the would_suppress set - see above) requires zero new keywords by definition. No "
        "residual 'quiet mismatch' cases (like the Checkpoint 4 romance-walkthrough finding) "
        "remain in this replay's suppression-eligible set."
        if not distinctive_diff else None
    ),
}

sections = [
    ("SUPPORTING_SOURCE cases", supporting_src),
    ("Remaining CONFIRMATION_ONLY cases", confirmation_only_remaining),
    ("Cases with some distinctive keyword difference (extra scrutiny)", distinctive_diff),
    ("SEMANTIC_DUPLICATE cases", semantic_dup),
    ("Highest-confidence suppressions", highest_confidence),
    ("Threshold-edge suppressions (closest to 0.65)", threshold_edge),
    ("Cross-source cases", cross_source),
    ("Cross-category cases", cross_category),
    ("Same-source repeated pages", same_source),
    ("Repeated aggregator coverage (Google News-style, both sides)", aggregator_repeats),
]

lines = []
lines.append("# Phase 20 M12 - Suppression Human-Review Packet (Checkpoint 5)\n")
total_cases = sum(len(v) for _, v in sections) + min(8, len(non_suppress)) + min(8, len(material_update))
lines.append(
    f"Stratified sample of {total_cases} cases drawn from the Checkpoint 4 same-dataset replay "
    "(2026-08-04 to 2026-08-07, 3,774 real events, disposable Postgres) - not all 173 "
    "`would_suppress=True` cases, per instruction. **Suppression is NOT enabled anywhere.** Every "
    "HUMAN VERDICT checkbox below is blank and must stay that way until a person reviews it - "
    "this script never auto-fills them. No suppression precision/recall number should be computed "
    "until every verdict below has been filled in.\n"
)

idx = 1
for title, items in sections:
    lines.append(f"## {title} ({len(items)} cases)\n")
    if not items:
        lines.append(f"_{_notes.get(title) or 'None found.'}_\n")
    for e in items:
        lines.append(fmt_suppress(e, idx))
        idx += 1

lines.append(f"## Non-suppress controls ({min(8, len(non_suppress))} cases)\n")
lines.append(
    "Obvious non-suppress cases (would_suppress=False) - sanity check that the policy correctly "
    "stays silent here.\n"
)
for e in non_suppress[:8]:
    lines.append(fmt_control(e, idx, would_suppress_value=False))
    idx += 1

lines.append(f"## MATERIAL_UPDATE controls ({min(8, len(material_update))} cases)\n")
lines.append(
    "Cases classified MATERIAL_UPDATE - these must NEVER be suppressed (the suppression policy "
    "already guarantees this structurally). Included so a reviewer can confirm these genuinely "
    "look like real updates worth publishing, not just verify the boolean.\n"
)
for e in material_update[:8]:
    lines.append(fmt_control(e, idx, would_suppress_value=False))
    idx += 1

lines.append("## Reviewer instructions\n")
lines.append(
    "For each case: read the NEW EVENT and MATCHED STORY facts and the DECISION already computed, "
    "then check exactly one HUMAN VERDICT box - CORRECT_SUPPRESS (genuinely the same story, "
    "nothing new), SHOULD_UPDATE (same story but with real new information), FALSE_MATCH (a "
    "real, distinct story that scored highly), or UNCERTAIN (genuinely unclear from the titles "
    "alone). For the two control sections, the question is simply whether the policy's own "
    "non-suppression / material-update judgment looks correct.\n"
)

with open("docs/phase20_m12_suppression_review_packet.md", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print("total cases:", total_cases)
for title, items in sections:
    print(f"  {title}: {len(items)}")
