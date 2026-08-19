"""NINJA PULSE RECAP Phase R1.3 - offline Story Integrity Gate diagnostic report.

Fully offline/synthetic - no DB, no network, no LLM. Uses the exact R1.2-observed production
title patterns (the same fixtures as tests/test_recap_story_integrity.py) to show:

    Story -> confirmed events -> integrity metrics/reasons -> PASS/FAIL
    -> only if PASS: Announcement Clusters -> Readiness

Run: python scripts/_recap_r1_3_offline_diagnostic.py
Output: tmp/recap_r1_3_offline_diagnostic.txt (untracked)
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.models.news_event import EventCategory, NewsEvent  # noqa: E402
from services.recap_event import (  # noqa: E402
    cluster_announcements,
    count_unique_sources,
    evaluate_recap_readiness,
    evaluate_recap_story_integrity,
)

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _event(*, title: str, minutes_ago: float) -> NewsEvent:
    return NewsEvent(
        id=uuid.uuid4(), source_id=uuid.uuid4(), title=title, category=EventCategory.TECH,
        url=f"https://example.com/{uuid.uuid4()}",
        published_at=_NOW - timedelta(minutes=minutes_ago), collected_at=_NOW - timedelta(minutes=minutes_ago),
        hash=f"h-{uuid.uuid4()}",
    )


def _story(*titles: str, spacing_minutes: float = 10.0) -> tuple[NewsEvent, list[NewsEvent]]:
    n = len(titles)
    events = [_event(title=t, minutes_ago=(n - i - 1) * spacing_minutes) for i, t in enumerate(titles)]
    return events[0], events


CASES: list[tuple[str, str, tuple[str, ...]]] = [
    ("A", "FAIL - generic 'What...' opener (real R1.2 example)", (
        "What are you doing this weekend?",
        "What happens when a hybrid battery dies in a used car you just bought?",
        "What the world's oldest telecommunications company is doing to survive",
        "What software do you use daily to get work done?",
    )),
    ("B", "FAIL - generic 'Accurate...' opener (real R1.2 example)", (
        "Accurate polyp segmentation using a lightweight vision transformer",
        "Accurate color conversions between RGB and CMYK for print workflows",
        "Accurate building height information from lidar without ground survey",
    )),
    ("C", "FAIL - generic 'How AI...' opener (real R1.2 example)", (
        "How AI is driving up consumer prices",
        "How AI is reshaping the path from junior to senior developer",
        "How AI text watermarking works",
    )),
    ("D", "FAIL - arXiv 'Large language models...' opener (real R1.2 example)", (
        "Large language model guardrails for safety critical deployments",
        "Large language models for automated medical consultation triage",
        "Large language models generate executable programs from specifications",
    )),
    ("E", "PASS - OpenAI / Hugging Face breach coverage", (
        "Hugging Face confirms data breach affecting OpenAI models",
        "OpenAI tightens safeguards after Hugging Face security breach",
        "Security researchers detail Hugging Face breach impact on OpenAI",
    )),
    ("F", "PASS - Taiwan $314 AI dividend policy", (
        "Taiwan approves $314 AI dividend for every citizen",
        "Government confirms $314 per person AI dividend program in Taiwan",
        "$314 AI dividend payment explained for Taiwan residents",
    )),
    ("G", "PASS - RISC-V original + response article", (
        "RISC-V International announces new vector extension for edge AI",
        "Why RISC-V's new vector extension matters for edge AI chips",
    )),
    ("H", "PASS - Qwen 3.8 27B launch + overthinking follow-ups", (
        "Qwen 3.8 27B launches with major reasoning upgrade",
        "Why Qwen 3.8 27B seems to overthink simple questions",
        "Developers report Qwen 3.8 27B overthinking basic prompts",
    )),
    ("I", "PASS - identical syndicated articles", (
        "Schools embrace AI and VR tools to modernize classrooms",
        "Schools embrace AI and VR tools to modernize classrooms",
        "Schools embrace AI and VR tools to modernize classrooms",
    )),
]


def render_case(case_id: str, description: str, titles: tuple[str, ...]) -> list[str]:
    anchor, events = _story(*titles)
    lines = [f"Case {case_id}: {description}", f"  Events ({len(events)}), anchor=first_event_id:"]
    for e in events:
        assert e.published_at is not None  # every fixture event above sets published_at explicitly
        marker = " (ANCHOR)" if e.id == anchor.id else ""
        lines.append(f"    [{e.published_at.strftime('%H:%M')}] {e.title!r}{marker}")

    integrity = evaluate_recap_story_integrity(anchor, events)
    verdict = "PASS" if integrity.eligible else "FAIL"
    lines.append(f"  Story Integrity Gate: {verdict}")
    lines.append(f"    reasons: {integrity.reasons}")
    lines.append(f"    metrics: {integrity.metrics}")

    if integrity.eligible:
        clusters = cluster_announcements(events)
        unique_sources = count_unique_sources(events)
        last_event_at = events[-1].published_at
        assert last_event_at is not None
        readiness = evaluate_recap_readiness(
            event_count=len(events), announcement_count=len(clusters), unique_source_count=unique_sources,
            last_event_at=last_event_at, now=_NOW, research_complete=True, unresolved_conflict_count=0,
            story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
        )
        lines.append(f"  Announcement Clusters ({len(clusters)}):")
        for c in clusters:
            lines.append(f"    cluster#{c.cluster_id}: {len(c.event_ids)} event(s), anchor={c.headline!r}")
        lines.append(f"  Readiness: state={readiness.state} ready={readiness.ready}")
    else:
        lines.append("  (integrity FAILED - announcement clustering/readiness intentionally not shown here,")
        lines.append("   per spec item 14's 'only if PASS' presentation rule - never a recap candidate")
        lines.append("   regardless of what clustering/readiness would otherwise compute.)")

    lines.append("")
    return lines


def main() -> None:
    lines = ["NINJA PULSE RECAP Phase R1.3 - offline Story Integrity Gate diagnostic", f"Generated (synthetic clock): {_NOW.isoformat()}", ""]
    for case_id, description, titles in CASES:
        lines += render_case(case_id, description, titles)

    output_path = Path(__file__).resolve().parent.parent / "tmp" / "recap_r1_3_offline_diagnostic.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
