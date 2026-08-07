"""Phase 19 M6: synthetic regression fixtures for services.story_memory.match_story(), with
DESIGNED (not blank) ground truth - legitimate here specifically because these cases are
synthetic/constructed, unlike the real/human-review packet (scripts/_phase19_m6_build_
calibration_packet.py), whose human_decision/human_notes fields must stay genuinely blank.

Covers the six required calibration categories (Phase 19 M6 authorization, section 8):
  A. same story across categories (the known Muse-Code failure class)
  B. same story across sources (single category)
  C. genuine story updates (materially new substance each time)
  D. supporting confirmations (same substance, corroborating source)
  E. similar companies but different events (must NOT merge)
  F. different stories sharing the same company/product entity (must NOT merge)

Each case is a chronological list of (title, category) tuples plus a `should_merge_with_first`
flag per subsequent item, run through the real match_story() against a disposable DB (same
two-engine pattern as scripts/_phase19_m6_real_data_replay.py - never touches the real DB).
Computes precision/recall against the designed ground truth, separately per category and in
aggregate. Never tunes services/story_memory.py's thresholds or gate - this script only measures.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from services.story_memory import match_story

_OUTPUT_PATH = Path(__file__).with_name("_phase19_m6_synthetic_fixture_results.json")

# match_story() outcomes that count as "the system found and linked a candidate story" - i.e. a
# predicted positive for merge-detection purposes. UNCERTAIN_MATCH still carries a
# matched_story_id (a real candidate was found, just not confidently), so it counts as a
# predicted positive too - a downstream "route to review" consumer would still see it, unlike
# NEW_STORY which surfaces nothing.
_MERGE_OUTCOMES = {"story_update", "supporting_source", "semantic_duplicate", "uncertain_match"}
# The subset of _MERGE_OUTCOMES that represents a *confident* match (used for a stricter,
# separately-reported recall figure).
_CONFIDENT_MERGE_OUTCOMES = {"story_update", "supporting_source", "semantic_duplicate"}


@dataclass(frozen=True)
class FixtureCase:
    """One item in a chronological sequence. `should_merge_with_first` is None for the first
    item in a sequence (nothing to compare against yet - never scored)."""
    title: str
    category: str
    should_merge_with_first: bool | None


@dataclass(frozen=True)
class FixtureSet:
    category_code: str
    label: str
    cases: list[FixtureCase]


def _seq(category_code: str, label: str, *items: tuple[str, str, bool | None]) -> FixtureSet:
    return FixtureSet(
        category_code=category_code, label=label,
        cases=[FixtureCase(title=t, category=c, should_merge_with_first=m) for t, c, m in items],
    )


FIXTURE_SETS: list[FixtureSet] = [
    # A. Same real story, reported under different categories by different sources - the known,
    # previously-documented Muse-Code failure class (docs/phase18_10_editorial_intelligence_
    # report.md sec7-9). These are the exact 7 real historical titles from
    # scripts/_phase18_10_muse_code_replay.py - reused verbatim since "these 7 titles describe one
    # real story" is itself the designed ground truth (a known fact, not fabricated), even though
    # the titles/timestamps were originally observed in production.
    _seq(
        "A", "same story across categories (Muse-Code class)",
        ("Meta launches Muse Code, an AI agent for large code bases", "STARTUPS", None),
        ("Meta Is Challenging Claude Code and Codex With New Muse Code", "GADGETS", True),
        ("Meta launches Muse Code AI coding agent for macOS and Linux", "GADGETS", True),
        ("Meta releases Muse Code in beta, a terminal coding agent powered by Muse Spark 1.2", "TECH", True),
        ("Meta introduces Muse Code, its take on a coding agent", "GADGETS", True),
        ("Meta has launched Muse Code, an artificial intelligence agent dedicated to programming", "AI", True),
        ("Introducing Muse Code and Muse Spark 1.2", "SOFTWARE", True),
    ),
    # B. Same story, same category, different sources - the "easy" case the topic-bucket gate is
    # specifically designed to still catch (no cross-category split).
    _seq(
        "B", "same story across sources (single category)",
        ("OpenAI unveils GPT-6, its most capable model yet", "AI", None),
        ("OpenAI launches GPT-6 with major reasoning improvements", "AI", True),
        ("OpenAI's new GPT-6 model is now available to developers", "AI", True),
    ),
    # C. Genuine developing story - materially new substance at each step (funding round
    # progressing through stages). Reuses scripts/_phase18_10_additional_replay_sets.py's Set A.
    _seq(
        "C", "genuine story updates",
        ("Anthropic in talks to raise new funding round at higher valuation", "STARTUPS", None),
        ("Anthropic closes funding round, valuation confirmed at $XX billion", "STARTUPS", True),
        ("Anthropic to use new funding round for compute expansion, CEO says", "STARTUPS", True),
    ),
    # D. Supporting confirmations - a second/third source corroborating the same event with a
    # substantially similar (not identical) title, distinct from C's "materially new substance"
    # framing - the expected outcome here is specifically supporting_source/semantic_duplicate,
    # never a fresh story_update.
    _seq(
        "D", "supporting confirmations",
        ("Google announces Gemini 4 Ultra with native video generation", "AI", None),
        ("Google's Gemini 4 Ultra adds native video generation, company confirms", "AI", True),
        ("Report: Gemini 4 Ultra brings native video generation to Google's lineup", "AI", True),
    ),
    # E. Similar surface features (same sector, similar phrasing) but genuinely distinct events -
    # must NOT merge. Reuses scripts/_phase18_10_additional_replay_sets.py's Set B.
    _seq(
        "E", "similar companies, different events",
        ("OpenAI releases new voice model for developers", "AI", None),
        ("Google releases new voice model for Android", "AI", False),
        ("Amazon releases new voice model for Alexa", "AI", False),
    ),
    # F. Different stories sharing the same company/product entity, but genuinely different
    # topics (product launch vs. a later, unrelated regulatory story about the same product) -
    # must NOT merge. Distinct from A: here the topic_bucket split is CORRECT (these really are
    # different stories), whereas in A the topic_bucket split is the bug (it is one story).
    _seq(
        "F", "different stories, same entity",
        ("OpenAI releases GPT-6 with major reasoning improvements", "AI", None),
        ("Regulators open investigation into OpenAI over GPT-6 training data", "AI", False),
    ),
]


async def _reset_story_tables(session_factory) -> None:
    """Each fixture set must be fully isolated from every other - two sets independently
    inventing a similarly-worded title (e.g. both mentioning "GPT-6") must never cross-contaminate
    each other's matching, or a category's precision/recall would silently reflect leftover state
    from an earlier category instead of that category's own designed scenario."""
    async with session_factory() as session:
        await session.execute(
            text("TRUNCATE news_event_story_links, stories, news_events, sources CASCADE")
        )
        await session.commit()


async def _run_fixture_set(session_factory, fixture_set: FixtureSet) -> list[dict]:
    await _reset_story_tables(session_factory)
    async with session_factory() as session:
        source = NewsSource(
            id=uuid4(), name=f"phase19-m6-synthetic-{fixture_set.category_code}",
            type=SourceType.RSS, active=True,
        )
        session.add(source)
        await session.flush()

        first_story_id: object | None = None
        results: list[dict] = []
        for case in fixture_set.cases:
            category = EventCategory[case.category]
            event = NewsEvent(
                id=uuid4(), source_id=source.id, title=case.title, category=category,
                hash=f"m6-synthetic-{uuid4()}",
            )
            session.add(event)
            await session.flush()

            signature, result = await match_story(session, title=case.title, category=category)

            if result.outcome == "new_story":
                story = Story(
                    id=uuid4(), title=case.title, category=category, entities=signature.entities,
                    keywords=signature.keywords, topic_bucket=signature.topic_bucket,
                    first_event_id=event.id, event_count=1,
                )
                session.add(story)
                await session.flush()
                if first_story_id is None:
                    first_story_id = story.id
            await session.commit()

            predicted_merge = result.outcome in _MERGE_OUTCOMES
            predicted_confident_merge = result.outcome in _CONFIDENT_MERGE_OUTCOMES
            matched_first = result.matched_story_id == first_story_id if first_story_id else False

            results.append(
                {
                    "category_code": fixture_set.category_code,
                    "title": case.title,
                    "event_category": case.category,
                    "should_merge_with_first": case.should_merge_with_first,
                    "outcome": result.outcome,
                    "confidence": result.confidence,
                    "predicted_merge": predicted_merge,
                    "predicted_confident_merge": predicted_confident_merge,
                    "matched_first_in_sequence": matched_first,
                    "reason": result.similarity_reason,
                }
            )
        return results


def _compute_metrics(all_results: list[dict]) -> dict:
    scored = [r for r in all_results if r["should_merge_with_first"] is not None]
    tp = sum(1 for r in scored if r["should_merge_with_first"] and r["predicted_merge"])
    tp_confident = sum(1 for r in scored if r["should_merge_with_first"] and r["predicted_confident_merge"])
    fn = sum(1 for r in scored if r["should_merge_with_first"] and not r["predicted_merge"])
    fp = sum(1 for r in scored if not r["should_merge_with_first"] and r["predicted_merge"])
    tn = sum(1 for r in scored if not r["should_merge_with_first"] and not r["predicted_merge"])

    positives = tp + fn
    negatives = fp + tn
    recall = tp / positives if positives else None
    recall_confident = tp_confident / positives if positives else None
    precision = tp / (tp + fp) if (tp + fp) else None
    false_merge_rate = fp / negatives if negatives else None

    return {
        "scored_cases": len(scored),
        "true_positive": tp,
        "true_positive_confident_only": tp_confident,
        "false_negative": fn,
        "false_positive": fp,
        "true_negative": tn,
        "recall_any_predicted_merge": recall,
        "recall_confident_merge_only": recall_confident,
        "precision": precision,
        "false_merge_rate_on_negative_cases": false_merge_rate,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disposable-host", default="localhost")
    parser.add_argument("--disposable-port", type=int, default=55435)
    parser.add_argument("--disposable-user", default="disposable")
    parser.add_argument("--disposable-password", default="disposable_pw")
    parser.add_argument("--disposable-db", default="phase19_m6")
    args = parser.parse_args()

    url = (
        f"postgresql+asyncpg://{args.disposable_user}:{args.disposable_password}"
        f"@{args.disposable_host}:{args.disposable_port}/{args.disposable_db}"
    )
    engine = create_async_engine(url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    all_results: list[dict] = []
    per_category_metrics: dict[str, dict] = {}
    for fixture_set in FIXTURE_SETS:
        set_results = await _run_fixture_set(session_factory, fixture_set)
        all_results.extend(set_results)
        per_category_metrics[fixture_set.category_code] = {
            "label": fixture_set.label,
            **_compute_metrics(set_results),
        }
        print(f"[{fixture_set.category_code}] {fixture_set.label}")
        for r in set_results:
            marker = "" if r["should_merge_with_first"] is None else (
                "MERGE-EXPECTED" if r["should_merge_with_first"] else "NO-MERGE-EXPECTED"
            )
            print(f"    {r['outcome']:20s} conf={r['confidence']:.2f}  [{marker}]  {r['title']}")

    aggregate_metrics = _compute_metrics(all_results)

    await engine.dispose()

    output = {
        "per_category_metrics": per_category_metrics,
        "aggregate_metrics": aggregate_metrics,
        "cases": all_results,
    }
    _OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nWrote {len(all_results)} synthetic fixture results to {_OUTPUT_PATH}")
    print("Aggregate metrics:", json.dumps(aggregate_metrics, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
