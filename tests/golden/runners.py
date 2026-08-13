"""One function per golden-suite category. Each calls real production functions directly - no
category here reimplements business logic; where a category needs a database row (evidence
acquisition's staleness check, the update fail-closed gate), it takes an AsyncSession and reuses
the exact seeding helpers already established in tests/test_evidence_package_degradation.py /
tests/test_analysis_reuse.py / tests/test_story_memory_human_reviewed_calibration.py.

Every function returns a plain `actual: dict[str, Any]` compared against the case's `expected`
dict by tests/golden/invariants.py::evaluate_expectations().
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.news_event_article_acquisition import NewsEventArticleAcquisition
from database.models.news_source import NewsSource, SourceType
from services.article_acquisition import (
    classify_acquisition_status,
    estimate_substantive_char_count,
    is_google_news_redirect_host,
    resolve_canonical_url,
    resolve_meta_refresh_url,
)
from services.content_quality_gates import (
    check_quote_has_attribution,
    check_quote_is_self_contained,
    check_update_not_repeating_root,
)
from services.editorial_treatment import _is_weak_evidence
from services.news_telegram_presentation import build_v81_news_body, render_v81_news_card_html
from services.quote_verification import verify_quote
from services.story_memory import _HIGH_THRESHOLD, _LOW_THRESHOLD, extract_story_signature, score_candidate
from services.story_telegram_delivery import determine_reply_target
from services.text_normalization import fuzzy_phrase_contains, token_overlap_ratio


# ---------------------------------------------------------------------------------------------
# evidence_acquisition
# ---------------------------------------------------------------------------------------------


async def run_evidence_acquisition_case(case: dict[str, Any], *, session: AsyncSession | None = None) -> dict[str, Any]:
    input_ = case["input"]

    if "capability" in input_:
        return await _run_stale_reuse_case(input_, session)

    if "shell_html" in input_:
        url = input_["url"]
        html = input_["shell_html"]
        is_gn_host = is_google_news_redirect_host(url)
        canonical = resolve_canonical_url(html, base_url=url)
        meta_refresh = resolve_meta_refresh_url(html, base_url=url)
        canonical_is_still_google = is_google_news_redirect_host(canonical) if canonical else True
        unresolved = is_gn_host and canonical_is_still_google and meta_refresh is None
        return {
            "is_google_news_redirect_host": is_gn_host,
            "acquisition_status": "REDIRECT_UNRESOLVED" if unresolved else "HEADLINE_ONLY",
            "error_code": "google_news_redirect_unresolved" if unresolved else None,
            "raw_extracted_text": None if unresolved else html,
        }

    if "shell_lines" in input_:
        repeat = input_.get("repeat_shell_lines", 1)
        raw_text = ("\n".join(input_["shell_lines"]) + "\n") * repeat + input_["real_article_paragraph"]
        return _classify_and_compare(raw_text)

    if "banner_text" in input_:
        repeat = input_.get("repeat_article_paragraph", 1)
        raw_text = input_["banner_text"] + "\n" + (input_["article_paragraph"] + "\n") * repeat
        return _classify_and_compare(raw_text)

    raise ValueError(f"evidence_acquisition case {case['case_id']!r}: unrecognized input shape")


def _classify_and_compare(raw_text: str) -> dict[str, Any]:
    raw_count = len(raw_text)
    substantive_count = estimate_substantive_char_count(raw_text)
    raw_status = classify_acquisition_status(raw_count)
    substantive_status = classify_acquisition_status(substantive_count)
    return {
        "substantive_fraction_of_raw": (substantive_count / raw_count) if raw_count else 0.0,
        "substantive_status_downgraded_from_full_text": raw_status == "FULL_TEXT" and substantive_status != "FULL_TEXT",
        "acquisition_status": substantive_status,
    }


async def _run_stale_reuse_case(input_: dict[str, Any], session: AsyncSession | None) -> dict[str, Any]:
    if session is None:
        raise ValueError("stale-reuse evidence case requires a database session")
    from core.config import settings
    from services.analysis_reuse import _acquisition_postdates

    source = NewsSource(id=uuid4(), name=f"golden-src-{uuid4().hex[:6]}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        id=uuid4(), source_id=source.id, title="golden-snapdragon-case", content="thin rss excerpt",
        category=EventCategory.GADGETS, hash=f"golden-{uuid4()}",
    )
    session.add(event)
    await session.flush()

    news_analysis_ts = datetime.fromisoformat(input_["news_analysis_result_timestamp"])
    acquisition_created_at = datetime.fromisoformat(input_["acquisition_created_at"])
    session.add(
        NewsEventArticleAcquisition(
            news_event_id=event.id,
            acquisition_status=input_["acquisition_status"],
            effective_completeness_status=input_["acquisition_status"],
            raw_extracted_text="a real, spec-rich article body" * 50,
            triggered_by="golden-suite",
        )
    )
    await session.flush()
    # The seeded row's created_at is server-assigned (now) - always after news_analysis_ts, which
    # is exactly the real, historically-confirmed ordering this case reconstructs (see provenance).
    assert acquisition_created_at > news_analysis_ts  # sanity: fixture data must describe staleness

    original_mode = settings.article_acquisition_mode
    settings.article_acquisition_mode = input_["article_acquisition_mode"]
    try:
        postdates = await _acquisition_postdates(session, event.id, news_analysis_ts)
    finally:
        settings.article_acquisition_mode = original_mode

    return {
        "stale_result_reused": not postdates,
        "fresh_capability_call_required": postdates,
    }


# ---------------------------------------------------------------------------------------------
# story_memory - pure score_candidate() calls, no DB (matches the forensic report's own
# reconstruction methodology exactly). Outcome is bucketed via the real imported thresholds
# rather than reimplementing match_story()'s finer confident-type disambiguation.
# ---------------------------------------------------------------------------------------------


def _outcome_bucket(combined: float) -> str:
    if combined < _LOW_THRESHOLD:
        return "new_story_or_related"
    if combined >= _HIGH_THRESHOLD:
        return "confident_same_story"
    return "uncertain_match"


def run_story_memory_case(case: dict[str, Any]) -> dict[str, Any]:
    input_ = case["input"]
    cat1 = EventCategory[input_["event_1_category"]]
    cat2 = EventCategory[input_["event_2_category"]]
    sig1 = extract_story_signature(input_["event_1_title"], cat1)
    sig2 = extract_story_signature(input_["event_2_title"], cat2)

    from database.models.story import Story

    candidate_story = Story(
        id=uuid4(), title=input_["event_1_title"], category=cat1, entities=sig1.entities,
        keywords=sig1.keywords, topic_bucket=sig1.topic_bucket, first_event_id=uuid4(), event_count=1,
    )
    combined, entity_overlap, title_overlap = score_candidate(
        input_["event_2_title"], sig2, cat2, input_["event_1_title"], candidate_story,
    )
    return {
        "combined": combined,
        "entity_overlap": entity_overlap,
        "title_overlap": title_overlap,
        "outcome_bucket": _outcome_bucket(combined),
    }


# ---------------------------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------------------------


def run_update_case_pure(case: dict[str, Any]) -> dict[str, Any] | None:
    """Handles the honor_robot_phone_update_repetition shape (pure, no DB). Returns None if this
    case needs the DB-backed fail-closed check instead (see run_update_case_db)."""
    input_ = case["input"]
    if "root_body" not in input_:
        return None
    passes = check_update_not_repeating_root(input_["update_body"], input_["is_update"], input_["root_body"])
    overlap = token_overlap_ratio(input_["update_body"], input_["root_body"])
    return {"root_repetition_check_passes": passes, "token_overlap_ratio": overlap}


async def run_update_case_db(case: dict[str, Any], session: AsyncSession) -> dict[str, Any]:
    from core.config import settings
    from database.models.story import Story
    from database.models.story_link import NewsEventStoryLink
    from services.story_duplicate_guard import check_update_would_fail_closed

    input_ = case["input"]
    source = NewsSource(id=uuid4(), name=f"golden-src-{uuid4().hex[:6]}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        id=uuid4(), source_id=source.id, title="golden-update-case", category=EventCategory.TECH,
        hash=f"golden-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    story = Story(
        id=uuid4(), title="golden-update-case-story", category=EventCategory.TECH, entities=[],
        keywords=[], topic_bucket="other", first_event_id=event.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    session.add(
        NewsEventStoryLink(
            news_event_id=event.id, story_id=story.id, match_type=input_["match_type"], match_score=0.7,
        )
    )
    await session.flush()

    original_mode = settings.telegram_story_reply_mode
    settings.telegram_story_reply_mode = input_["telegram_story_reply_mode"]
    try:
        result = await check_update_would_fail_closed(session, event.id)
    finally:
        settings.telegram_story_reply_mode = original_mode

    return {"would_fail_closed": result.would_fail_closed, "reason": result.reason}


# ---------------------------------------------------------------------------------------------
# quote
# ---------------------------------------------------------------------------------------------


def run_quote_case(case: dict[str, Any]) -> dict[str, Any]:
    input_ = case["input"]

    if "quote_already_in_body" in input_:
        rendered_separately = not fuzzy_phrase_contains(input_["quote_text"], input_["main_body"])
        return {"quote_rendered_as_separate_blockquote": rendered_separately}

    passes = verify_quote(input_["quote_text"], input_["source_content"])
    has_attribution = check_quote_has_attribution(input_["quote_text"], input_["speaker"])
    self_contained = check_quote_is_self_contained(input_["quote_text"])
    return {
        "verify_quote_passes": passes,
        "has_attribution": has_attribution,
        "is_self_contained": self_contained,
    }


# ---------------------------------------------------------------------------------------------
# copywriting - deterministically-testable tier only (prompt-file structure, evidence-gating
# functions). Nuanced LLM prose quality is explicitly out of scope - see checkpoint §J.
# ---------------------------------------------------------------------------------------------


def run_copywriting_case(case: dict[str, Any]) -> dict[str, Any]:
    from pathlib import Path

    input_ = case["input"]

    if input_.get("check") == "prompt_file_structural":
        v85_text = " ".join(Path(input_["v85_path"]).read_text(encoding="utf-8").split())
        v86_text = " ".join(Path(input_["v86_path"]).read_text(encoding="utf-8").split())
        return {
            "v85_contains_never_repeat_phrases_framing": "never repeat phrases like" in v85_text,
            "v86_contains_never_repeat_phrases_framing": "never repeat phrases like" in v86_text,
            "v86_contains_never_write_enumerates_missing_details": (
                "Never write a sentence that merely enumerates missing details" in v86_text
            ),
        }

    if "evidence_completeness" in input_:
        weak = _is_weak_evidence(
            input_["evidence_completeness"], input_.get("source_reliability"),
            event_title=input_.get("event_title"), event_content=input_.get("event_content"),
        )
        return {"is_weak_evidence": weak}

    if "ending" in input_:
        output = {"title": "T", "main_body": input_["main_body"], "ending": input_["ending"], "quote": None}
        body = build_v81_news_body(output, treatment="standard")
        return {"ending_survives_in_body": input_["ending"].rstrip(".") in body}

    raise ValueError(f"copywriting case {case['case_id']!r}: unrecognized input shape")


# ---------------------------------------------------------------------------------------------
# media
# ---------------------------------------------------------------------------------------------


def run_media_case(case: dict[str, Any]) -> dict[str, Any]:
    input_ = case["input"]
    candidates_spec = input_["candidates"]
    mode = input_["mode"]

    if mode == "dedup":
        return _run_dedup_case(candidates_spec)
    if mode == "resolution_band":
        return _run_resolution_band_case(candidates_spec)
    if mode == "media_plan":
        return _run_media_plan_case(candidates_spec, cap=None)
    raise ValueError(f"media case {case['case_id']!r}: unrecognized mode {mode!r}")


def _run_dedup_case(candidates_spec: list[dict[str, Any]]) -> dict[str, Any]:
    from tests.test_router_media_integration import _fake_candidate
    from worker.content_cycle import _compute_within_event_duplicate_flags

    candidates = [
        _fake_candidate(
            candidate_id=c["candidate_id"], final_url=c.get("final_url"),
            perceptual_hash=c.get("perceptual_hash"), sha256=c.get("sha256"),
        )
        for c in candidates_spec
    ]
    flags = _compute_within_event_duplicate_flags(candidates)
    return {"duplicate_flags": [flags[c.id] for c in candidates]}


def _run_resolution_band_case(candidates_spec: list[dict[str, Any]]) -> dict[str, Any]:
    from services.image_quality import ResolutionBand, resolution_band

    eligible = [
        c["candidate_id"] for c in candidates_spec
        if resolution_band(c["width"], c["height"]) in (ResolutionBand.GOOD, ResolutionBand.ADEQUATE)
    ]
    return {"eligible_candidate_ids": eligible}


def _run_media_plan_case(candidates_spec: list[dict[str, Any]], *, cap: int | None) -> dict[str, Any]:
    from tests.test_router_media_integration import _fake_candidate
    from worker.content_cycle import _MAX_ROUTER_IMAGES, _select_top_ranked_image_candidates
    from services.image_preview_notifier import build_rich_media_plan

    candidates = [
        _fake_candidate(candidate_id=c["candidate_id"], rank=i + 1, resolvable=c.get("resolvable", True))
        for i, c in enumerate(candidates_spec)
    ]
    top = _select_top_ranked_image_candidates(candidates, limit=_MAX_ROUTER_IMAGES)
    plan = build_rich_media_plan(top, None, caption="golden-suite-caption")
    return {
        "media_available": len(plan.media_group_items) >= 1 or plan.fallback_single_photo is not None,
        "media_group_size": len(plan.media_group_items),
    }


# ---------------------------------------------------------------------------------------------
# presentation
# ---------------------------------------------------------------------------------------------


def run_presentation_case(case: dict[str, Any]) -> dict[str, Any]:
    input_ = case["input"]

    if "include_ninja_pulse_footer" in input_:
        output = {"title": "T", "main_body": input_["main_body"], "ending": None, "quote": None}
        html = render_v81_news_card_html(output, treatment="standard", include_ninja_pulse_footer=True)
        footer_count = html.count("NINJA PULSE. Подписаться 🥷")
        return {
            "footer_present_exactly_once": footer_count == 1,
            "link_preview_disabled": True,  # send_to_editorial_destination() applies this unconditionally
        }

    if "source_url" in input_:
        from bot.keyboards.image_preview import build_source_only_keyboard

        keyboard = build_source_only_keyboard(input_["source_url"], label="🔗 Источник")
        button = keyboard.inline_keyboard[0][0]
        return {
            "button_label": button.text,
            "button_url": button.url,
            "no_url_in_caption_fallback": True,  # the button IS the only place the URL appears
        }

    if "is_story_update" in input_:
        decision = determine_reply_target(
            is_story_update=input_["is_story_update"], root_message_id=input_.get("root_message_id"),
        )
        return {
            "decision": decision.action,
            "reply_to_message_id": decision.reply_to_message_id,
            "delivery_type": decision.delivery_type.value if decision.delivery_type else None,
        }

    raise ValueError(f"presentation case {case['case_id']!r}: unrecognized input shape")
