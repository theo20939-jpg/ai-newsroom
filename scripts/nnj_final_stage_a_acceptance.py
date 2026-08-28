"""Phase V2.12A/B - the final, real, isolated Stage-A acceptance harness for ONE fresh NEWS story.

Produces a complete, self-contained, human-reviewable package (final branded image, exact
Telegram HTML, exact source-only keyboard, exact destination, a SHA256 manifest) using the real
committed production functions this project already has - never reimplementing research/
intelligence/copywriting, image ranking, recomposition, branding, rendering, keyboard
construction, or destination routing. Structurally cannot send anything to Telegram: no
`aiogram.Bot` import anywhere in this file, no import of any of the
`services.telegram_routing.send_*`/`services.telegram_notifier.send_*` functions - `audit_no_
telegram_send_calls()` below proves this by parsing this module's own source, and is itself unit-
tested (tests/test_final_stage_a_acceptance.py).

Real DB/Redis/provider infrastructure is required to actually RUN `main()` (`run_stage_a()`
selects a real event, calls the real `run_content_generation_for_event()` - which needs a real
Postgres session and, unless a fake registry is injected, the real Redis-backed `LLMGateway` -
and, if recomposition triggers, exactly one real Gemini Flash call). This module is safe to
IMPORT anywhere (zero top-level I/O, zero provider/DB/Telegram calls at import time) - only
`main()`, invoked exclusively under `if __name__ == "__main__":`, touches real infrastructure.

Mirrors this project's own established "settings mutated in-process only, reverted after" canary
discipline (scripts/nnj_v2_10_visual_acceptance_canary.py) for every settings override below -
never a `.env` write, never a change that outlives this one process.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.image_preview import build_source_only_keyboard
from core.config import settings
from database.models.editorial_task import TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from schemas.editorial_route import EditorialDestination
from scripts.run_content_generation import ContentGenerationOutcome, run_content_generation_for_event
from services.editorial_recomposition import RecompositionResult, maybe_recompose
from services.image_persistence import EditorialImageCandidate, get_editorial_image_candidates, read_candidate_bytes
from services.news_telegram_presentation import (
    _NINJA_PULSE_TEXT,
    _NINJA_PULSE_URL,
    is_v8_family_output,
    render_v81_news_card_html,
)
from services.nnj_master_news_overlay import MasterNewsBrandingDecision, apply_master_news_branding
from services.quote_lookup import get_quote_for_draft, resolve_display_text
from services.telegram_routing import RouteTarget, resolve_route
from worker.content_cycle import (
    _NEWS_SOURCE_BUTTON_LABEL,
    _classify_event_for_router_treatment,
    _select_eligible_events,
    assess_recomposition_source_risk,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_THIS_FILE = Path(__file__).resolve()

# Phase V2.12A/B: the checkpoint this harness was authored and validated against - recorded in the
# manifest so a reviewer can confirm which committed contract produced any given package.
CHECKPOINT_SHA = "bb74509902383fb8754b3da1081a66d625bfbcc3"

EXPECTED_CHAT_ID = -1004297182444
EXPECTED_TOPIC_ID = 2

_PREFERRED_CATEGORIES: tuple[EventCategory, ...] = (
    EventCategory.AI, EventCategory.GADGETS, EventCategory.HARDWARE, EventCategory.SOFTWARE, EventCategory.TECH,
)

# Real event_ids already spent as visual/text CALIBRATION fixtures across the V2.x sessions this
# project ran - never a valid fresh acceptance candidate even if still technically DB-eligible.
EXCLUDED_CALIBRATION_EVENT_IDS: frozenset[UUID] = frozenset({
    UUID("c59323de-9d79-4d8e-a1f5-7fb4307e0739"),  # V2.10 Stage-A canary - robot vacuum ban (9to5google.com)
})

MAX_GEMINI_RECOMPOSITION_CALLS = 1

# Section 13's own explicit audit list - any of these appearing as a Name/Attribute this module
# calls (not merely mentions in a string/comment) is a hard contract violation.
_FORBIDDEN_TELEGRAM_CALL_NAMES = frozenset({
    "send_message", "send_photo", "send_media_group", "send_to_editorial_destination",
    "send_photo_to_editorial_destination", "send_media_group_to_editorial_destination",
    "send_editorial_card", "edit_message_reply_markup", "edit_message_text", "delete_message",
})


class StageAContractError(RuntimeError):
    """Raised whenever a required Stage-A contract cannot be proven - this harness fails closed,
    never degrades to a placeholder/fabricated value."""


@dataclass(frozen=True)
class StoryCandidate:
    event_id: UUID
    title: str
    source_domain: str | None
    published_at: datetime | None
    url: str | None
    category: str


def audit_no_telegram_send_calls(source_path: Path = _THIS_FILE) -> list[str]:
    """Parses `source_path` (this module, by default) and returns every forbidden call name
    (Section 13's own list) that appears as an actual function/method CALL - not merely imported
    or mentioned in a string/comment/docstring. An empty list is the required, proven state."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name in _FORBIDDEN_TELEGRAM_CALL_NAMES:
            found.append(name)
    return found


def _filter_candidate_event_ids(ranked_event_ids: list[UUID]) -> list[UUID]:
    """Pure, DB-free filtering step: removes known calibration event_ids from an already-ranked
    list. Separated from `select_candidate_event()` below purely so this rule is unit-testable
    without a database."""
    return [eid for eid in ranked_event_ids if eid not in EXCLUDED_CALIBRATION_EVENT_IDS]


async def select_candidate_event(session: AsyncSession) -> StoryCandidate | None:
    """Reuses the real, unmodified production eligibility/ranking query
    (`worker.content_cycle._select_eligible_events()`) - never a second, hand-written eligibility
    scan. Applies only two additional, narrow preferences on top of that already-ranked list:
    known-calibration exclusion (`_filter_candidate_event_ids()`) and a soft category preference
    (AI/GADGETS/HARDWARE/SOFTWARE/TECH first, any other still-eligible category as a fallback
    rather than returning nothing). Returns `None` - a valid, expected outcome, never a fabricated
    fallback story - when no eligible, non-excluded candidate exists at all."""
    ranked_ids = await _select_eligible_events(session)
    candidate_ids = _filter_candidate_event_ids(ranked_ids)
    if not candidate_ids:
        return None

    candidates: list[StoryCandidate] = []
    for event_id in candidate_ids:
        event = await session.get(NewsEvent, event_id)
        if event is None:
            continue
        source_domain = await session.scalar(select(NewsSource.name).where(NewsSource.id == event.source_id))
        candidates.append(StoryCandidate(
            event_id=event.id, title=event.title, source_domain=source_domain,
            published_at=event.published_at, url=event.url, category=event.category.value,
        ))

    for preferred in _PREFERRED_CATEGORIES:
        for candidate in candidates:
            if candidate.category == preferred.value:
                return candidate
    return candidates[0] if candidates else None


@contextlib.contextmanager
def process_local_overrides():
    """Mirrors this project's own established canary discipline: mutate `settings` in this
    process only, always revert in a `finally`, never write `.env`. Activates exactly the real
    NEWS production path this phase requires (V8.6 copy, the enforce-mode branding branch, and the
    real source-faithful recomposition attempt) without touching the persisted config."""
    original = {
        "copywriting_prompt_version": settings.copywriting_prompt_version,
        "presentation_director_mode": settings.presentation_director_mode,
        "pulse_brand_enabled": settings.pulse_brand_enabled,
        "editorial_recomposition_mode": settings.editorial_recomposition_mode,
    }
    settings.copywriting_prompt_version = "8.6"
    settings.presentation_director_mode = "enforce"
    settings.pulse_brand_enabled = True
    settings.editorial_recomposition_mode = "live"
    try:
        yield dict(original)
    finally:
        settings.copywriting_prompt_version = original["copywriting_prompt_version"]
        settings.presentation_director_mode = original["presentation_director_mode"]
        settings.pulse_brand_enabled = original["pulse_brand_enabled"]
        settings.editorial_recomposition_mode = original["editorial_recomposition_mode"]


async def generate_content(event_id: UUID) -> ContentGenerationOutcome:
    """Thin wrapper - the real production entry point
    (`scripts.run_content_generation.run_content_generation_for_event()`) does every real
    Research -> Intelligence -> Copywriting -> Quality step itself; nothing is duplicated here."""
    return await run_content_generation_for_event(event_id, priority=TaskPriority.B)


def render_final_html(outcome: ContentGenerationOutcome) -> tuple[str, str]:
    """Fails closed (StageAContractError) rather than accepting non-V8.6 output - Section 7's own
    "must be real V8.6 output" requirement, checked structurally via the real production shape-
    detector (`is_v8_family_output()`), never a version-string comparison that could be fooled by
    a differently-shaped payload. Returns (html, plain_text) - the plain rendering is HTML with
    tags stripped, for the human-review block only, never a second independent render path."""
    if outcome.copywriting_output is None:
        raise StageAContractError("content generation produced no copywriting_output - cannot render V8.6 copy")
    if not is_v8_family_output(outcome.copywriting_output):
        raise StageAContractError(
            "copywriting_output is not V8-family shaped - settings.copywriting_prompt_version='8.6' "
            "did not take effect, or the prompt repository returned an unexpected schema"
        )
    from services.editorial_treatment import STANDARD

    html = render_v81_news_card_html(
        outcome.copywriting_output, treatment=STANDARD, include_ninja_pulse_footer=True,
    )
    plain_text = ast_strip_html_tags(html)
    return html, plain_text


def ast_strip_html_tags(html: str) -> str:
    """A tiny, dependency-free tag stripper for the human-review plain-text block only - never
    used for the persisted `final_post.html` (which stays the exact real renderer output)."""
    import re

    return re.sub(r"<[^>]+>", "", html).strip()


async def resolve_source_image(
    session: AsyncSession, content_draft_id: UUID,
) -> tuple[EditorialImageCandidate, bytes]:
    """Reuses the real production candidate retrieval (`get_editorial_image_candidates()`, already
    eligible-only and rank-ordered - no second ranking pass) and the real storage read
    (`read_candidate_bytes()`). Fails closed when no usable candidate exists - never a synthetic
    placeholder image."""
    candidates = await get_editorial_image_candidates(session, content_draft_id=content_draft_id)
    for candidate in candidates:
        if candidate.is_expired:
            continue
        source_bytes = read_candidate_bytes(candidate)
        if source_bytes is not None:
            return candidate, source_bytes
    raise StageAContractError("no usable (non-expired, readable) real image candidate found for this draft")


async def apply_visual_path(
    candidate: EditorialImageCandidate, source_bytes: bytes,
) -> tuple[bytes, RecompositionResult | None, str]:
    """The real production visual-path decision (`worker/content_cycle.py`'s own logic, reused
    exactly, not duplicated): `assess_recomposition_source_risk()` gates eligibility, then at most
    ONE real call to `maybe_recompose()` (`MAX_GEMINI_RECOMPOSITION_CALLS = 1`, enforced simply by
    calling it exactly once - `maybe_recompose()` itself never retries or calls a second model).
    Returns (chosen_bytes, recomposition_result_or_None, visual_path)."""
    risk = assess_recomposition_source_risk(candidate)
    if risk is not None:
        logger.info("stage_a_recomposition_skipped_source_risk", extra={"reason": risk})
        return source_bytes, None, "ORIGINAL_SOURCE"

    result = await maybe_recompose(source_image_bytes=source_bytes)
    if result.used_recomposed_image:
        return result.image_bytes, result, "RECOMPOSE"
    return source_bytes, result, "ORIGINAL_SOURCE"


def apply_branding(image_bytes: bytes, *, disable_lower_signature: bool) -> tuple[bytes, MasterNewsBrandingDecision]:
    """Thin wrapper - the real, frozen MASTER_BALANCED contract
    (`services.nnj_master_news_overlay.apply_master_news_branding()`), never reimplemented."""
    return apply_master_news_branding(image_bytes, disable_lower_signature=disable_lower_signature)


def build_keyboard(source_url: str | None) -> InlineKeyboardMarkup | None:
    """The real production NEWS keyboard builder, with the real production label - reused, not
    reimplemented. Structurally asserts the approved contract (exactly one button, no CTA) before
    returning, failing closed if a future, unrelated change to `build_source_only_keyboard()`
    ever silently added a second button."""
    keyboard = build_source_only_keyboard(source_url, label=_NEWS_SOURCE_BUTTON_LABEL)
    if keyboard is None:
        return None
    rows = keyboard.inline_keyboard
    if len(rows) != 1 or len(rows[0]) != 1:
        raise StageAContractError(f"expected exactly one button, got rows={rows!r}")
    button = rows[0][0]
    if button.text != _NEWS_SOURCE_BUTTON_LABEL:
        raise StageAContractError(f"expected button text {_NEWS_SOURCE_BUTTON_LABEL!r}, got {button.text!r}")
    return keyboard


def resolve_destination() -> RouteTarget:
    """The real production routing resolver (`services.telegram_routing.resolve_route()`), never
    hardcoded. Fails closed (Section 12's own explicit rule) if the resolved destination does not
    match the approved chat_id/topic_id - a real, disclosed mismatch must stop this harness, never
    be silently accepted."""
    route = resolve_route(EditorialDestination.NEWS)
    if route is None:
        raise StageAContractError("NEWS destination did not resolve - newsroom_telegram_chat_id is unset")
    if route.chat_id != EXPECTED_CHAT_ID or route.topic_id != EXPECTED_TOPIC_ID:
        raise StageAContractError(
            f"resolved destination {route!r} does not match the approved "
            f"chat_id={EXPECTED_CHAT_ID}, topic_id={EXPECTED_TOPIC_ID}"
        )
    return route


def validate_final_package_contract(
    *, html: str, plain_text: str, keyboard: InlineKeyboardMarkup | None,
    source_url: str | None, destination: RouteTarget,
) -> None:
    """Phase V2.12G: the narrow, Stage-A-specific hard-contract gate this harness was missing
    entirely - `services.content_quality_gates.evaluate_content_quality_gates()` (called for real
    inside `run_content_generation_for_event()`) validates content-DRAFT text quality and is
    deliberately non-blocking by this project's own established policy (services/
    content_draft_service.py's own "assess and record, don't silently reject" comment) - never
    touched here. This is a completely separate concern: the FINAL, fully-composed NEWS package
    (text/HTML/keyboard/destination) either matches the approved contract or it does not, and a
    violation here must never be reported as acceptance success. Reuses the real, single-source
    constants (`_NINJA_PULSE_TEXT`/`_NINJA_PULSE_URL` from services.news_telegram_presentation,
    `_NEWS_SOURCE_BUTTON_LABEL` from worker.content_cycle, `EXPECTED_CHAT_ID`/`EXPECTED_TOPIC_ID`
    from this module) rather than re-declaring the forbidden strings a second time.

    Phase V2.12I: V2.12G's CTA-forbidding gate is itself superseded - the approved contract
    restores Phase 23.1Q's requirement that the NINJA PULSE footer (text + link) appear exactly
    once in the final HTML. `plain_text` is `ast_strip_html_tags(html)`'s output, which strips the
    `<a href="...">` tag along with every other tag - the URL itself is never visible there (real
    Telegram anchor-text rendering), so only the CTA TEXT, not the URL, is checked in plain_text."""
    if html.count(_NINJA_PULSE_TEXT) != 1:
        raise StageAContractError(
            f"expected the NINJA PULSE CTA text exactly once in final HTML, found {html.count(_NINJA_PULSE_TEXT)}"
        )
    if f'<a href="{_NINJA_PULSE_URL}">{_NINJA_PULSE_TEXT}</a>' not in html:
        raise StageAContractError(f"expected the NINJA PULSE CTA anchor linking to {_NINJA_PULSE_URL} in final HTML")
    if plain_text.count(_NINJA_PULSE_TEXT) != 1:
        raise StageAContractError(
            f"expected the NINJA PULSE CTA text exactly once in final plain text, "
            f"found {plain_text.count(_NINJA_PULSE_TEXT)}"
        )

    if keyboard is None:
        raise StageAContractError("NEWS package has no keyboard - a source-only button is required")
    rows = keyboard.inline_keyboard
    if len(rows) != 1 or len(rows[0]) != 1:
        raise StageAContractError(f"keyboard is not exactly one row/one button, got rows={rows!r}")
    button = rows[0][0]
    if button.text != _NEWS_SOURCE_BUTTON_LABEL:
        raise StageAContractError(f"button text {button.text!r} != approved {_NEWS_SOURCE_BUTTON_LABEL!r}")
    if button.url != source_url:
        raise StageAContractError(f"button url {button.url!r} != event source url {source_url!r}")

    if destination.chat_id != EXPECTED_CHAT_ID or destination.topic_id != EXPECTED_TOPIC_ID:
        raise StageAContractError(
            f"destination {destination!r} does not match approved "
            f"chat_id={EXPECTED_CHAT_ID}, topic_id={EXPECTED_TOPIC_ID}"
        )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest(
    *, story: StoryCandidate, outcome: ContentGenerationOutcome, candidate: EditorialImageCandidate,
    recomposition: RecompositionResult | None, visual_path: str, branding: MasterNewsBrandingDecision,
    destination: RouteTarget, keyboard: InlineKeyboardMarkup | None, source_bytes: bytes,
    raw_recomposition_bytes: bytes | None, final_image_bytes: bytes, html: str, plain_text: str,
    settings_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Pure function - every value is already computed by the caller; no I/O, no DB, no provider
    call, fully unit-testable with synthetic inputs."""
    keyboard_json = (
        {"inline_keyboard": [
            [{"text": b.text, "url": b.url} for b in row] for row in keyboard.inline_keyboard
        ]}
        if keyboard is not None else None
    )
    return {
        "checkpoint_sha": CHECKPOINT_SHA,
        "package_created_at": datetime.now(timezone.utc).isoformat(),
        "event_id": str(story.event_id),
        "task_id": str(outcome.task_id),
        "draft_id": str(outcome.content_draft.id) if outcome.content_draft is not None else None,
        "story": {
            "title": story.title, "source_domain": story.source_domain,
            "published_at": story.published_at.isoformat() if story.published_at else None,
            "url": story.url, "category": story.category,
        },
        "source_image": {
            "candidate_source_url": candidate.source_url, "article_url": candidate.article_url,
            "mime": candidate.observed_mime, "width": candidate.width, "height": candidate.height,
            "sha256": _sha256(source_bytes),
        },
        "copywriting_prompt_version": settings_snapshot["copywriting_prompt_version"],
        "visual_path": visual_path,
        "recomposition": (
            {
                "attempted": True, "provider": recomposition.provider, "model": recomposition.model,
                "used_recomposed_image": recomposition.used_recomposed_image,
                "fallback_reason": recomposition.fallback_reason,
                "source_sha256": recomposition.source_sha256, "result_sha256": recomposition.result_sha256,
            }
            if recomposition is not None else {"attempted": False, "reason": "source_risk_gate"}
        ),
        "raw_recomposition_sha256": _sha256(raw_recomposition_bytes) if raw_recomposition_bytes else None,
        "branding": {
            "degradation_mode": branding.degradation_mode,
            "upper_mark_placement": branding.upper_mark.placement.value,
            "upper_mark_rejected_candidate_count": len(branding.upper_mark.attempts),
            "lower_signature_placement": branding.lower_signature.placement.value,
            "lower_signature_rejected_candidate_count": len(branding.lower_signature.attempts),
            "lower_signature_disabled_reason": branding.lower_signature.disabled_reason,
        },
        "destination": {"chat_id": destination.chat_id, "topic_id": destination.topic_id},
        "keyboard": keyboard_json,
        "final_html_sha256": _sha256(html.encode("utf-8")),
        "final_text_sha256": _sha256(plain_text.encode("utf-8")),
        "final_image_sha256": _sha256(final_image_bytes),
        "telegram_sends_this_run": 0,
        "gemini_recomposition_calls_this_run": 1 if recomposition is not None else 0,
    }


def persist_package(
    output_dir: Path, *, final_image_bytes: bytes, source_image_bytes: bytes,
    raw_recomposition_bytes: bytes | None, html: str, plain_text: str,
    keyboard: InlineKeyboardMarkup | None, destination: RouteTarget, manifest: dict[str, Any],
) -> dict[str, str]:
    """Writes every required artifact (Section 14) and returns a {filename: sha256} map - pure
    filesystem I/O, no network, no DB, fully unit-testable against a tmp_path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}

    def _write(name: str, data: bytes) -> None:
        (output_dir / name).write_bytes(data)
        hashes[name] = _sha256(data)

    _write("final_image.jpg", final_image_bytes)
    _write("source_image.jpg", source_image_bytes)
    if raw_recomposition_bytes is not None:
        _write("raw_recomposition.jpg", raw_recomposition_bytes)
    _write("final_post.html", html.encode("utf-8"))
    _write("final_post.txt", plain_text.encode("utf-8"))

    keyboard_json = (
        {"inline_keyboard": [
            [{"text": b.text, "url": b.url} for b in row] for row in keyboard.inline_keyboard
        ]}
        if keyboard is not None else None
    )
    _write("keyboard.json", json.dumps(keyboard_json, indent=2, ensure_ascii=False).encode("utf-8"))
    _write(
        "destination.json",
        json.dumps({"chat_id": destination.chat_id, "topic_id": destination.topic_id}, indent=2).encode("utf-8"),
    )
    telemetry = {
        "checkpoint_sha": CHECKPOINT_SHA, "telegram_sends": 0,
        "gemini_recomposition_calls": manifest["gemini_recomposition_calls_this_run"],
    }
    _write("telemetry.json", json.dumps(telemetry, indent=2, ensure_ascii=False).encode("utf-8"))
    _write("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
    return hashes


async def run_stage_a() -> Path:
    """The real orchestrator - only ever called from `main()`, never at import time. Requires
    real Postgres (`database.session.async_session_factory`), and - inside
    `run_content_generation_for_event()` - the real Redis-backed production `LLMGateway`
    (`integrations.llm_gateway.boot.assemble_ai_integration_layer()`) plus, if recomposition
    triggers, exactly one real Gemini Flash call. Zero Telegram calls anywhere in this function -
    see `audit_no_telegram_send_calls()`."""
    with process_local_overrides() as settings_snapshot:
        async with async_session_factory() as session:
            story = await select_candidate_event(session)
            if story is None:
                raise StageAContractError("no suitable fresh, non-excluded, eligible NEWS story found in the DB")
            logger.info(
                "stage_a_story_selected",
                extra={
                    "event_id": str(story.event_id), "title": story.title, "source_domain": story.source_domain,
                    "published_at": story.published_at.isoformat() if story.published_at else None,
                    "url": story.url, "category": story.category,
                },
            )

        outcome = await generate_content(story.event_id)
        if outcome.content_draft is None:
            raise StageAContractError(f"content generation did not produce a ContentDraft (status={outcome.workflow_status})")

        html, plain_text = render_final_html(outcome)

        async with async_session_factory() as session:
            candidate, source_bytes = await resolve_source_image(session, outcome.content_draft.id)
            treatment_decision = await _classify_event_for_router_treatment(session, story.event_id)
            quote = await get_quote_for_draft(session, outcome.content_draft.id)
        quote_text, quote_speaker = resolve_display_text(quote) if quote is not None else (None, None)
        if quote_text is not None:
            html, plain_text = render_final_html_with_quote(outcome, treatment_decision, quote_text, quote_speaker)

        chosen_bytes, recomposition, visual_path = await apply_visual_path(candidate, source_bytes)
        raw_recomposition_bytes = (
            recomposition.image_bytes if recomposition is not None and recomposition.used_recomposed_image else None
        )
        disable_lower_signature = assess_recomposition_source_risk(candidate) is not None
        final_image_bytes, branding = apply_branding(chosen_bytes, disable_lower_signature=disable_lower_signature)

        keyboard = build_keyboard(story.url)
        destination = resolve_destination()

        # Phase V2.12G: fail closed BEFORE anything is persisted or reported as success - a
        # violation here raises StageAContractError, which propagates out of run_stage_a()/main()
        # unhandled, giving a non-zero process exit. No partial/forensic persistence on failure -
        # the simplest safe implementation, per this phase's own explicit preference.
        validate_final_package_contract(
            html=html, plain_text=plain_text, keyboard=keyboard, source_url=story.url, destination=destination,
        )

        manifest = build_manifest(
            story=story, outcome=outcome, candidate=candidate, recomposition=recomposition,
            visual_path=visual_path, branding=branding, destination=destination, keyboard=keyboard,
            source_bytes=source_bytes, raw_recomposition_bytes=raw_recomposition_bytes,
            final_image_bytes=final_image_bytes, html=html, plain_text=plain_text,
            settings_snapshot=settings_snapshot,
        )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = _REPO_ROOT / "artifacts" / "final_stage_a" / f"{timestamp}_{story.event_id}"
        persist_package(
            output_dir, final_image_bytes=final_image_bytes, source_image_bytes=source_bytes,
            raw_recomposition_bytes=raw_recomposition_bytes, html=html, plain_text=plain_text,
            keyboard=keyboard, destination=destination, manifest=manifest,
        )

        _print_human_review_block(story, plain_text, output_dir, visual_path, branding, keyboard, destination, manifest)
        return output_dir


def render_final_html_with_quote(
    outcome: ContentGenerationOutcome, treatment_decision, quote_text: str, quote_speaker: str | None,
) -> tuple[str, str]:
    """Same real renderer as `render_final_html()`, re-invoked once a real quote is available -
    never a second render path, only the additional real arguments the production renderer already
    accepts."""
    if outcome.copywriting_output is None:
        raise StageAContractError("copywriting_output became None between the first and quote-aware render")
    html = render_v81_news_card_html(
        outcome.copywriting_output, treatment=treatment_decision.treatment,
        quote_text=quote_text, quote_speaker=quote_speaker, include_ninja_pulse_footer=True,
    )
    return html, ast_strip_html_tags(html)


def _print_human_review_block(
    story: StoryCandidate, plain_text: str, output_dir: Path, visual_path: str,
    branding: MasterNewsBrandingDecision, keyboard: InlineKeyboardMarkup | None,
    destination: RouteTarget, manifest: dict[str, Any],
) -> None:
    buttons = (
        ", ".join(f"{b.text} -> {b.url}" for row in keyboard.inline_keyboard for b in row)
        if keyboard is not None else "(none)"
    )
    print("=" * 70)
    print("STORY:", story.title, "|", story.source_domain, "|", story.published_at, "|", story.url)
    print("-" * 70)
    print("TEXT:\n" + plain_text)
    print("-" * 70)
    print("IMAGE:", output_dir / "final_image.jpg")
    print("VISUAL PATH:", visual_path)
    print("BRANDING degradation_mode:", branding.degradation_mode)
    print("BUTTONS:", buttons)
    print("DESTINATION: chat_id=%s topic_id=%s" % (destination.chat_id, destination.topic_id))
    print("HASHES: html=%s image=%s" % (manifest["final_html_sha256"], manifest["final_image_sha256"]))
    print("TELEGRAM SEND COUNT: 0")
    print("=" * 70)


def main() -> None:
    import asyncio

    asyncio.run(run_stage_a())


if __name__ == "__main__":
    main()
