"""NINJA PULSE RECAP Phase R1.5A.2 - offline Story Integrity diagnostic (pair-specific generic
entity filtering).

Fully offline/synthetic - no DB, no network, no LLM. Shows, for each fixture: member count, anchor
leading entity, then PER anchor->member pair: whether the pair shares the anchor's leading entity,
the pair-specific entity-excluded residual overlap (when applicable), whether the entity was
excluded for THAT pair only, the resulting filtered entities, entity jaccard, title overlap, final
coherence score, required floor, and coherent yes/no - using the real, current
`evaluate_recap_story_integrity()` function (no reimplementation).

Titles marked [PRODUCTION-VERBATIM] were given verbatim in earlier checkpoint messages this
session; titles marked [SYNTHETIC - reconstructed from topic description] were built from a real
production Story's own described topic mix (the real production titles were never available
verbatim) - never claimed as transcribed production text.

Run: python scripts/_recap_r1_5a2_integrity_diagnostic.py
Output: tmp/recap_r1_5a2_integrity_diagnostic.txt (untracked)
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.models.news_event import EventCategory, NewsEvent  # noqa: E402
from services.recap_event import (  # noqa: E402
    _INTEGRITY_ANCHOR_RESIDUAL_FLOOR,
    _integrity_coherence_score,
    _jaccard,
    _leading_entity,
    _residual_overlap_excluding_entity,
    evaluate_recap_story_integrity,
)
from services.story_memory import extract_story_signature  # noqa: E402

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _event(*, title: str, minutes_ago: float) -> NewsEvent:
    return NewsEvent(
        id=uuid.uuid4(), source_id=uuid.uuid4(), title=title, category=EventCategory.TECH,
        url=f"https://example.com/{uuid.uuid4()}",
        published_at=_NOW - timedelta(minutes=minutes_ago), collected_at=_NOW - timedelta(minutes=minutes_ago),
        hash=f"h-{uuid.uuid4()}",
    )


CASES: list[tuple[str, str, bool, tuple[str, ...]]] = [
    # (label, provenance, expected_pass, titles) - anchor is titles[0]
    ("What (weekend)", "PRODUCTION-VERBATIM", False, (
        "What are you doing this weekend?",
        "What happens when a hybrid battery dies in a used car you just bought?",
        "What the world's oldest telecommunications company is doing to survive",
        "What software do you use daily to get work done?",
    )),
    ("Large language models (9-member, no duplicate)", "SYNTHETIC/APPROXIMATE", False, (
        "Large language model guardrails for safety critical deployments",
        "Large language models for automated medical consultation triage",
        "Large language models generate executable programs from specifications",
        "Large language models struggle with multi-step arithmetic reasoning",
        "Large language models show promise in legal document summarization",
        "Large language models and their carbon footprint during training",
        "Large language models for low-resource language translation tasks",
        "Large language models used to detect phishing emails automatically",
        "Large language models evaluated on creative writing benchmarks",
    )),
    ("Large language models (9-member + injected duplicate)", "SYNTHETIC/APPROXIMATE", False, (
        "Large language model guardrails for safety critical deployments",
        "Large language model guardrails for safety-critical deployments",
        "Large language models for automated medical consultation triage",
        "Large language models generate executable programs from specifications",
        "Large language models struggle with multi-step arithmetic reasoning",
        "Large language models show promise in legal document summarization",
        "Large language models and their carbon footprint during training",
        "Large language models for low-resource language translation tasks",
        "Large language models used to detect phishing emails automatically",
        "Large language models evaluated on creative writing benchmarks",
    )),
    ("Accurate", "PRODUCTION-VERBATIM", False, (
        "Accurate polyp segmentation using a lightweight vision transformer",
        "Accurate color conversions between RGB and CMYK for print workflows",
        "Accurate building height information from lidar without ground survey",
    )),
    ("Recent (reconstructed, with near-duplicate)", "SYNTHETIC - reconstructed from topic description", False, (
        "Recent video generators struggle with consistent physical motion",
        "Recent video generators still struggle with consistent physical motion",
        "Recent 3D foundation models enable zero-shot scene reconstruction",
        "Recent progress in robot learning accelerates real-world manipulation tasks",
    )),
    ("Despite (reconstructed, with near-duplicate)", "SYNTHETIC - reconstructed from topic description", False, (
        "Despite recent advances in unified multimodal models text accuracy remains poor",
        "Despite recent advances in unified multimodal models text accuracy is still poor",
        "Despite recent advances battery materials remain difficult to scale",
        "Despite recent advances video editing tools still require manual correction",
        "Despite recent advances medical visual recognition models show demographic bias",
    )),
    ("Autonomous", "SYNTHETIC/APPROXIMATE", False, (
        "Autonomous racecars complete first fully driverless championship lap",
        "Autonomous delivery robots expand to twelve new cities this year",
        "Autonomous farming equipment adoption grows among midwest producers",
    )),
    ("Expert (Russian)", "SYNTHETIC/APPROXIMATE", False, (
        "Эксперт объяснил, почему цены на жильё продолжат расти",
        "Эксперт рассказал о новых правилах регистрации автомобилей",
        "Эксперт оценил перспективы урожая зерна в этом году",
    )),
    ("Bashkiria", "PRODUCTION-VERBATIM (real anchor/ordering unconfirmed)", False, (
        "В Башкирии обозначили направления развития искусственного интеллекта в медицине",
        "В Башкирии определены приоритеты внедрения искусственного интеллекта в медицину",
        "Башкирия внедряет искусственный интеллект в медицину",
        "В Башкирии внедряют искусственный интеллект в медицину",
    )),
    ("Taiwan", "SYNTHETIC/APPROXIMATE", True, (
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
        "$314 AI dividend payment explained for Taiwan residents",
    )),
    ("OpenAI/Hugging Face", "SYNTHETIC/APPROXIMATE", True, (
        "Hugging Face confirms data breach affecting OpenAI models",
        "OpenAI tightens safeguards after Hugging Face security breach",
        "Security researchers detail Hugging Face breach impact on OpenAI",
    )),
    ("Classroom syndicated", "SYNTHETIC/APPROXIMATE", True, (
        "Schools embrace AI and VR tools to modernize classrooms",
        "Schools are embracing AI and VR tools to modernize classrooms",
        "How schools embrace AI and VR tools to modernize classrooms",
    )),
    ("Qwen", "SYNTHETIC/APPROXIMATE", True, (
        "Qwen 3.8 27B launches with major reasoning upgrade",
        "Why Qwen 3.8 27B seems to overthink simple questions",
        "Developers report Qwen 3.8 27B overthinking basic prompts",
    )),
]


def render_case(label: str, provenance: str, expected_pass: bool, titles: tuple[str, ...]) -> list[str]:
    n = len(titles)
    events = [_event(title=t, minutes_ago=(n - i - 1) * 10.0) for i, t in enumerate(titles)]
    sigs = [extract_story_signature(t, EventCategory.TECH) for t in titles]

    lines = [f"Case: {label}  [{provenance}]  (expected {'PASS' if expected_pass else 'FAIL'})", f"  members: {n}"]
    anchor_leading = _leading_entity(sigs[0])
    anchor_entities_full = set(sigs[0].entities)
    lines.append(f"  anchor leading entity: {anchor_leading!r}")

    for i in range(1, n):
        member_leading = _leading_entity(sigs[i])
        shared_leading = anchor_leading is not None and member_leading == anchor_leading
        lines.append(f"  -> [{i}] {titles[i]!r}")
        lines.append(f"       shares anchor leading entity: {shared_leading}")

        pair_anchor_entities = set(anchor_entities_full)
        pair_member_entities = set(sigs[i].entities)
        excluded = None
        if shared_leading and anchor_leading is not None:
            residual = _residual_overlap_excluding_entity(anchor_leading, titles[0], titles[i])
            qualifies = residual >= _INTEGRITY_ANCHOR_RESIDUAL_FLOOR
            lines.append(f"       pair residual overlap (entity-excluded): {residual:.3f}  (floor {_INTEGRITY_ANCHOR_RESIDUAL_FLOOR}, qualifies={qualifies})")
            if not qualifies:
                pair_anchor_entities.discard(anchor_leading)
                pair_member_entities.discard(anchor_leading)
                excluded = anchor_leading
        lines.append(f"       entity excluded for this pair only: {excluded!r}")
        lines.append(f"       filtered anchor entities: {sorted(pair_anchor_entities)}  filtered member entities: {sorted(pair_member_entities)}")

        raw_jaccard = _jaccard(anchor_entities_full, set(sigs[i].entities))
        filtered_jaccard = _jaccard(pair_anchor_entities, pair_member_entities)
        score = _integrity_coherence_score(pair_anchor_entities, titles[0], pair_member_entities, titles[i])
        branch = "entities available" if (pair_anchor_entities and pair_member_entities) else "title-only fallback"
        floor = 0.30 if branch == "entities available" else 0.45
        lines.append(f"       raw entity jaccard: {raw_jaccard:.3f}  filtered entity jaccard: {filtered_jaccard:.3f}")
        lines.append(f"       branch: {branch}  score: {score:.3f}  required floor: {floor}  coherent: {score >= floor}")

    result = evaluate_recap_story_integrity(events[0], events)
    lines.append(f"  pair_entity_exclusions: {result.metrics.get('pair_entity_exclusions')}")
    lines.append(f"  per-member coherence scores: {result.metrics.get('per_event_coherence_scores')}")
    lines.append(f"  final anchor_coherent_ratio: {result.metrics.get('anchor_coherent_ratio')}")
    verdict = "PASS" if result.eligible else "FAIL"
    match = "OK" if result.eligible == expected_pass else "*** MISMATCH ***"
    lines.append(f"  VERDICT: {verdict}  ({match})")
    lines.append("")
    return lines


def main() -> None:
    lines = ["NINJA PULSE RECAP Phase R1.5A.2 - offline Story Integrity diagnostic (pair-specific filtering)", f"Generated (synthetic clock): {_NOW.isoformat()}", ""]
    for label, provenance, expected_pass, titles in CASES:
        lines += render_case(label, provenance, expected_pass, titles)

    output_path = Path(__file__).resolve().parent.parent / "tmp" / "recap_r1_5a2_integrity_diagnostic.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
