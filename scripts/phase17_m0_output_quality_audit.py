"""Phase 17 M0 - Editorial Output Quality Discovery (docs/
phase17_m0_output_quality_discovery_report.md).

Read-only. Measures the real, already-generated ContentDraft population - length distribution,
deterministic completeness proxies, headline-rewrite proxy, category/source-type breakdowns - from
already-persisted data only. Never calls an LLM/provider, never sends to Telegram, never mutates
NewsEvent/ContentDraft/EditorialTask, never deletes anything.

Two of this file's "completeness" metrics (concrete_details_count, headline_overlap_ratio) are
genuine deterministic proxies computed from real text (regex/set-overlap - no invented numbers).
The remaining, more semantic M0 dimensions (subject_explained, why_it_matters, beginner_friendly,
etc.) are NOT computed here - Phase 17 M0's own scope note is explicit that those require human
(or future LLM-judge) review, not a regex pretending to read for meaning; see the manual-audit
table in the report instead, which covers a 30-draft subsample of the same population sampled here.

Launch with:
    python -m scripts.phase17_m0_output_quality_audit
"""
import asyncio
import json
import re
import statistics
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory

# Fixed, documented length buckets (docs/phase17_m0_output_quality_discovery_report.md §4).
_LENGTH_BUCKETS = [
    ("<50", 0, 49),
    ("50-89", 50, 89),
    ("90-139", 90, 139),
    ("140-219", 140, 219),
    ("220-319", 220, 319),
    ("320+", 320, float("inf")),
]

_WORD_RE = re.compile(r"\S+")
_SENTENCE_SPLIT_RE = re.compile(r"[.!?…]+(?:\s|$)")
_NUMBER_RE = re.compile(r"\d[\d,.\s]*\d|\d")
_CURRENCY_RE = re.compile(r"[$€£₽¥]|\b(?:млн|млрд|тыс|USD|EUR|RUB)\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_PERCENT_RE = re.compile(r"\d+([.,]\d+)?\s*%")
_CAPITALIZED_TOKEN_RE = re.compile(r"(?<!^)(?<![.!?…]\s)\b[A-ZА-ЯЁ][a-zа-яё]{2,}\b")


def _word_count(text: str | None) -> int:
    if not text:
        return 0
    return len(_WORD_RE.findall(text))


def _sentence_count(text: str | None) -> int:
    if not text or not text.strip():
        return 0
    parts = [p for p in _SENTENCE_SPLIT_RE.split(text.strip()) if p.strip()]
    return max(1, len(parts))


def _paragraph_count(text: str | None) -> int:
    if not text or not text.strip():
        return 0
    parts = [p for p in re.split(r"\n\s*\n|\n", text.strip()) if p.strip()]
    return max(1, len(parts))


def _concrete_details_count(text: str | None) -> int:
    """Deterministic proxy: distinct concrete-detail signals actually present in the text -
    numbers, currency/amount markers, years, percentages, capitalized (proper-noun-like)
    tokens beyond the first word of each sentence. A count, not a judgment of quality."""
    if not text:
        return 0
    count = 0
    count += len(_NUMBER_RE.findall(text))
    count += len(_CURRENCY_RE.findall(text))
    count += len(_YEAR_RE.findall(text))
    count += len(_PERCENT_RE.findall(text))
    count += len(set(_CAPITALIZED_TOKEN_RE.findall(text)))
    return count


def _headline_overlap_ratio(draft_title: str | None, draft_body: str | None) -> float | None:
    """Proxy for headline_rewrite_only: fraction of the body's unique word-stems that already
    appear in the title. High overlap + short body is the deterministic flag used below - a real
    editorial read is still required to confirm (see the manual audit)."""
    if not draft_title or not draft_body:
        return None
    title_words = {w.lower().strip(".,!?»«\"'") for w in _WORD_RE.findall(draft_title)}
    body_words = {w.lower().strip(".,!?»«\"'") for w in _WORD_RE.findall(draft_body)}
    title_words = {w for w in title_words if len(w) > 2}
    body_words = {w for w in body_words if len(w) > 2}
    if not body_words:
        return None
    return round(len(body_words & title_words) / len(body_words), 3)


def _unsupported_numeric_flag(draft_body: str | None, source_content: str | None) -> bool:
    """Proxy for unsupported_claim_risk, numeric case only: a number appears in the draft body
    that does not appear anywhere in the source content available at generation time. Cannot
    detect non-numeric fabrication - a real editorial/LLM-judge read is required for that."""
    if not draft_body:
        return False
    body_numbers = {n.replace(" ", "").replace(",", "") for n in _NUMBER_RE.findall(draft_body)}
    body_numbers = {n for n in body_numbers if len(n) >= 2}  # skip single-digit noise (list markers etc.)
    if not body_numbers:
        return False
    source_text = source_content or ""
    source_numbers = {n.replace(" ", "").replace(",", "") for n in _NUMBER_RE.findall(source_text)}
    return not body_numbers.issubset(source_numbers)


def _bucket(word_count: int) -> str:
    for label, low, high in _LENGTH_BUCKETS:
        if low <= word_count <= high:
            return label
    return "320+"


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return round(ordered[index], 1)


def _length_summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(statistics.mean(values), 1),
        "median": statistics.median(values),
        "p25": _percentile(values, 25),
        "p75": _percentile(values, 75),
    }


async def main() -> None:
    async with async_session_factory() as session:
        stmt = (
            select(ContentDraft, EditorialTask, NewsEvent, NewsSource)
            .join(EditorialTask, EditorialTask.id == ContentDraft.task_id)
            .join(NewsEvent, NewsEvent.id == EditorialTask.event_id)
            .join(NewsSource, NewsSource.id == NewsEvent.source_id)
            .order_by(ContentDraft.created_at.asc())
        )
        rows = (await session.execute(stmt)).all()

        # Data-hygiene exclusion (discovered during M0's own manual audit, not assumed up front):
        # a small number of rows are leftover Phase 16 M6/M7 validation fixtures, not real
        # production news items - their source name says so explicitly ("M6 Live Validation
        # Source", "phase14-m6-live-validation-...") or their title is literally tagged
        # "[M6 VALIDATION]". Per this task's own "не создавай синтетические production-события"
        # instruction, they are excluded here rather than silently skewing real numbers.
        excluded_synthetic = 0
        records: list[dict[str, Any]] = []
        for draft, _task, event, source in rows:
            is_synthetic = (
                "validation" in source.name.lower()
                or "backtest" in source.name.lower()
                or "[m6 validation]" in event.title.lower()
                or "[test" in event.title.lower()
            )
            if is_synthetic:
                excluded_synthetic += 1
                continue
            body_word_count = _word_count(draft.body)
            title_word_count = _word_count(draft.title)
            source_content = event.content or ""
            source_word_count = _word_count(source_content)
            record = {
                "draft_id": str(draft.id),
                "event_id": str(event.id),
                "created_at": draft.created_at.isoformat(),
                "source_type": source.type.value,
                "source_name": source.name,
                "category": event.category.value,
                "event_title": event.title,
                "event_has_content": bool(event.content),
                "event_content_chars": len(source_content),
                "event_content_word_count": source_word_count,
                "event_has_summary": bool(event.summary),
                "event_has_url": bool(event.url),
                "draft_title": draft.title,
                "draft_title_word_count": title_word_count,
                "draft_body_word_count": body_word_count,
                "draft_body_char_count": len(draft.body or ""),
                "sentence_count": _sentence_count(draft.body),
                "paragraph_count": _paragraph_count(draft.body),
                "hashtag_count": len(draft.hashtags or []),
                "length_bucket": _bucket(body_word_count),
                "output_source_ratio": (
                    round(body_word_count / source_word_count, 2) if source_word_count > 0 else None
                ),
                "concrete_details_count": _concrete_details_count(draft.body),
                "headline_overlap_ratio": _headline_overlap_ratio(draft.title, draft.body),
                "unsupported_numeric_flag": _unsupported_numeric_flag(draft.body, source_content),
            }
            # Deterministic headline-rewrite proxy: body adds little vocabulary beyond the title
            # AND is short. Both thresholds are declared here, not hidden - see report §6 for the
            # calibration against the 30-draft manual audit's own headline-rewrite verdicts.
            record["headline_rewrite_flag"] = bool(
                record["headline_overlap_ratio"] is not None
                and record["headline_overlap_ratio"] >= 0.6
                and body_word_count <= 45
            )
            records.append(record)

    body_word_counts = [r["draft_body_word_count"] for r in records]
    title_word_counts = [r["draft_title_word_count"] for r in records]
    sentence_counts = [r["sentence_count"] for r in records]
    paragraph_counts = [r["paragraph_count"] for r in records]
    concrete_counts = [r["concrete_details_count"] for r in records]
    ratios = [r["output_source_ratio"] for r in records if r["output_source_ratio"] is not None]

    bucket_histogram: dict[str, int] = defaultdict(int)
    for r in records:
        bucket_histogram[r["length_bucket"]] += 1

    by_source_type: dict[str, list[int]] = defaultdict(list)
    by_category: dict[str, list[int]] = defaultdict(list)
    for r in records:
        by_source_type[r["source_type"]].append(r["draft_body_word_count"])
        by_category[r["category"]].append(r["draft_body_word_count"])

    headline_rewrite_count = sum(1 for r in records if r["headline_rewrite_flag"])
    unsupported_numeric_count = sum(1 for r in records if r["unsupported_numeric_flag"])
    zero_content_count = sum(1 for r in records if not r["event_has_content"])
    zero_summary_count = sum(1 for r in records if not r["event_has_summary"])
    single_paragraph_count = sum(1 for r in records if r["paragraph_count"] == 1)

    report = {
        "sample_size": len(records),
        "excluded_synthetic_validation_fixtures": excluded_synthetic,
        "date_range": {
            "earliest": records[0]["created_at"] if records else None,
            "latest": records[-1]["created_at"] if records else None,
        },
        "source_type_counts": {k: len(v) for k, v in by_source_type.items()},
        "category_counts": {k: len(v) for k, v in by_category.items()},
        "body_word_count": _length_summary(body_word_counts),
        "title_word_count": _length_summary(title_word_counts),
        "sentence_count": _length_summary(sentence_counts),
        "paragraph_count": _length_summary(paragraph_counts),
        "single_paragraph_rate": round(single_paragraph_count / len(records), 3) if records else None,
        "output_source_ratio": _length_summary([int(r * 100) for r in ratios]) if ratios else {"count": 0},
        "length_bucket_histogram": dict(bucket_histogram),
        "body_word_count_by_source_type": {k: _length_summary(v) for k, v in by_source_type.items()},
        "body_word_count_by_category": {k: _length_summary(v) for k, v in by_category.items()},
        "concrete_details_count_summary": _length_summary(concrete_counts),
        "headline_rewrite_flag_rate": round(headline_rewrite_count / len(records), 3) if records else None,
        "headline_rewrite_flag_count": headline_rewrite_count,
        "unsupported_numeric_flag_rate": (
            round(unsupported_numeric_count / len(records), 3) if records else None
        ),
        "unsupported_numeric_flag_count": unsupported_numeric_count,
        "event_zero_content_count": zero_content_count,
        "event_zero_summary_count": zero_summary_count,
        "event_zero_summary_rate": round(zero_summary_count / len(records), 3) if records else None,
    }
    print(json.dumps(report, indent=2, default=str))

    # Full per-draft sample for the report's manual-audit selection and appendix tables - not
    # committed to git (matches the existing, preserved scripts/_phase15_m4_final_cutover_
    # samples.json precedent: a local, untracked reproducibility artifact, not a deliverable).
    with open("scripts/_phase17_m0_output_quality_samples.json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
