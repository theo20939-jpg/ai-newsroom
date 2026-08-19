"""NINJA PULSE RECAP Phase R1.5B.1 - offline publisher-suffix sanitization diagnostic.

Fully offline/synthetic - no DB, no network, no LLM. Shows, for the real Taiwan production titles
(verbatim, from the R1.5B.1 checkpoint message) and a handful of negative-control fixtures: raw
(unsanitized) vs sanitized entities, entity jaccard, `_has_conflicting_distinctive_facts()`, and
`_announcement_similarity()` BEFORE and AFTER `_sanitized_announcement_signature()` - using the
real, current functions (no reimplementation) - plus the resulting `cluster_announcements()` count.

Run: python scripts/_recap_r1_5b1_publisher_sanitization_diagnostic.py
Output: tmp/recap_r1_5b1_publisher_sanitization_diagnostic.txt (untracked)
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.models.news_event import EventCategory, NewsEvent  # noqa: E402
from services.recap_event import (  # noqa: E402
    _announcement_similarity,
    _has_conflicting_distinctive_facts,
    _jaccard,
    _publisher_suffix_entities,
    _sanitized_announcement_signature,
    cluster_announcements,
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


CASES: list[tuple[str, str, tuple[str, ...], float]] = [
    ("Taiwan (real production titles, verbatim)", "PRODUCTION-VERBATIM", (
        "Тайвань выплатит каждому гражданину страны около $314 «дивидендов от ИИ» - Ведомости",
        "Тайвань выплатит каждому гражданину $314 дивидендов от ИИ - Хабр",
        "Тайвань выплатит каждому гражданину «дивиденды от ИИ» в $314 - Эксперт",
        "Тайвань выплатит всем своим гражданам «дивиденды» от мирового бума ИИ - CNews.ru",
    ), 75.0),
    ("Numeric-conflict negative control", "SYNTHETIC negative control", (
        "Taiwan approves $314 AI dividend for every citizen - Reuters",
        "Taiwan approves $500 AI dividend for every citizen - Bloomberg",
    ), 10.0),
    ("Distinct-content negative control", "SYNTHETIC negative control", (
        "Taiwan approves $314 AI dividend for every citizen - Reuters",
        "Taiwan opens new semiconductor factory near Hsinchu - Bloomberg",
    ), 10.0),
]


def render_case(label: str, provenance: str, titles: tuple[str, ...], gap_minutes: float) -> list[str]:
    n = len(titles)
    events = [_event(title=t, minutes_ago=(n - i - 1) * gap_minutes) for i, t in enumerate(titles)]
    raw_sigs = [extract_story_signature(t, EventCategory.TECH) for t in titles]
    sanitized_sigs = [_sanitized_announcement_signature(sig, t) for sig, t in zip(raw_sigs, titles)]

    lines = [f"Case: {label}  [{provenance}]", f"  members: {n}"]
    for i, t in enumerate(titles):
        lines.append(f"  [{i}] {t!r}")
        lines.append(f"       raw_entities={raw_sigs[i].entities}  publisher_suffix_entities={sorted(_publisher_suffix_entities(t))}  sanitized_entities={sanitized_sigs[i].entities}")

    for i in range(n):
        for j in range(i + 1, n):
            raw_jaccard = _jaccard(set(raw_sigs[i].entities), set(raw_sigs[j].entities))
            san_jaccard = _jaccard(set(sanitized_sigs[i].entities), set(sanitized_sigs[j].entities))
            raw_conflict = _has_conflicting_distinctive_facts(raw_sigs[i], titles[i], raw_sigs[j], titles[j])
            san_conflict = _has_conflicting_distinctive_facts(sanitized_sigs[i], titles[i], sanitized_sigs[j], titles[j])
            raw_fuzzy = _announcement_similarity(raw_sigs[i], titles[i], raw_sigs[j], titles[j])
            san_fuzzy = _announcement_similarity(sanitized_sigs[i], titles[i], sanitized_sigs[j], titles[j])
            lines.append(
                f"  pair [{i},{j}]: entity_jaccard {raw_jaccard:.3f} -> {san_jaccard:.3f}   "
                f"conflict {raw_conflict} -> {san_conflict}   fuzzy {raw_fuzzy:.3f} -> {san_fuzzy:.3f}"
            )

    clusters = cluster_announcements(events)
    lines.append(f"  cluster_announcements(): {n} -> {len(clusters)}")
    sizes = sorted(len(c.event_ids) for c in clusters)
    lines.append(f"  cluster sizes: {sizes}")
    lines.append("")
    return lines


def main() -> None:
    lines = ["NINJA PULSE RECAP Phase R1.5B.1 - offline publisher-suffix sanitization diagnostic", f"Generated (synthetic clock): {_NOW.isoformat()}", ""]
    for label, provenance, titles, gap in CASES:
        lines += render_case(label, provenance, titles, gap)

    output_path = Path(__file__).resolve().parent.parent / "tmp" / "recap_r1_5b1_publisher_sanitization_diagnostic.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
