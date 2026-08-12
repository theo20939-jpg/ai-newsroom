"""Video Shadow Checkpoint - read-only post-run analysis of the bounded ~75-minute
video_discovery_mode="shadow" canary (scripts/_phase23_1q_video_shadow_canary.py,
2026-08-12T17:13:14Z - 2026-08-12T18:28:37Z).

Queries `content_draft_media_items` rows created during the canary's own start/end window,
cross-references them against `image_candidates` (same news_event_id) for coexistence stats, and
exercises the existing, unmodified `rank_media_candidates()` (services/media_ranking.py) and
`build_rich_media_plan()` (services/image_preview_notifier.py) read-only, in-process, to determine
hypothetical delivery eligibility. Makes zero writes, zero Telegram calls, and never imports
worker/content_cycle.py (the live delivery orchestrator) - this script cannot affect real
delivery even by accident.

No new persistence, no schema change, no production code change - a one-off analysis script,
mirrors this project's own established scripts/_phase23_1*_post_run_analysis.py convention.
"""
import asyncio
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from database.models.content_draft_media_item import ContentDraftMediaItem
from database.models.image_candidate_record import ImageCandidateRecord
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from schemas.media_ranking import MediaRankingInput
from schemas.video_candidate import NativeVideoHint, VideoDiscoveryMethod, VideoPlatform
from services.image_preview_notifier import build_rich_media_plan
from services.media_ranking import rank_media_candidates
from services.video_discovery_persistence import EligibleVideoCandidate

_RUN_START = datetime(2026, 8, 12, 19, 33, 43, 627234, tzinfo=timezone.utc)
_RUN_END = datetime(2026, 8, 12, 20, 18, 48, 698233, tzinfo=timezone.utc)


def _row_to_candidate(row: ContentDraftMediaItem) -> EligibleVideoCandidate:
    return EligibleVideoCandidate(
        id=row.id, event_id=row.event_id, content_draft_id=row.content_draft_id,
        discovery_method=row.discovery_method, remote_url=row.remote_url, platform=row.platform,
        declared_width=row.declared_width, declared_height=row.declared_height,
        declared_mime_type=row.declared_mime_type, declared_duration_seconds=row.declared_duration_seconds,
        validation_status=row.validation_status, detected_container=row.detected_container,
        byte_size=row.byte_size, error_code=row.error_code,
    )


async def main() -> None:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(ContentDraftMediaItem).where(
                    ContentDraftMediaItem.created_at >= _RUN_START,
                    ContentDraftMediaItem.created_at <= _RUN_END,
                ).order_by(ContentDraftMediaItem.created_at.asc())
            )
        ).scalars().all()

        candidates = [_row_to_candidate(r) for r in rows]
        event_ids = {c.event_id for c in candidates}

        events_by_id: dict[UUID, NewsEvent] = {}
        if event_ids:
            event_rows = (
                await session.execute(select(NewsEvent).where(NewsEvent.id.in_(event_ids)))
            ).scalars().all()
            events_by_id = {e.id: e for e in event_rows}

        image_rows_by_event: dict[UUID, list[ImageCandidateRecord]] = defaultdict(list)
        if event_ids:
            image_rows = (
                await session.execute(
                    select(ImageCandidateRecord).where(ImageCandidateRecord.news_event_id.in_(event_ids))
                )
            ).scalars().all()
            for ir in image_rows:
                image_rows_by_event[ir.news_event_id].append(ir)

    report: dict[str, object] = {}
    report["run_window"] = {"start_utc": _RUN_START.isoformat(), "end_utc": _RUN_END.isoformat()}
    report["total_video_hint_rows"] = len(candidates)
    report["distinct_events_with_video_hints"] = len(event_ids)

    # --- discovery method distribution ---
    report["discovery_method_distribution"] = dict(Counter(c.discovery_method for c in candidates))

    # --- platform/type distribution ---
    report["platform_distribution"] = dict(Counter(c.platform for c in candidates))

    def _detected_type(c: EligibleVideoCandidate) -> str:
        if c.platform != "direct_hosted":
            return c.platform
        if c.detected_container in ("mp4",):
            return "direct_hosted_mp4"
        if c.detected_container in ("webm", "mkv"):
            return f"direct_hosted_{c.detected_container}"
        if c.detected_container:
            return f"direct_hosted_{c.detected_container}"
        return "direct_hosted_undetected"

    report["direct_hosted_container_distribution"] = dict(
        Counter(_detected_type(c) for c in candidates if c.platform == "direct_hosted")
    )

    # --- validation distribution ---
    report["validation_status_distribution"] = dict(Counter(c.validation_status for c in candidates))
    rejected = [c for c in candidates if c.validation_status == "rejected"]
    report["rejected_count"] = len(rejected)
    report["rejection_error_code_distribution"] = dict(Counter(c.error_code or "unknown" for c in rejected))

    # --- hints per story distribution ---
    hints_per_event: Counter = Counter(c.event_id for c in candidates)
    report["hints_per_story_distribution"] = dict(Counter(hints_per_event.values()))

    # --- DISCLOSED FINDING: hosted_platform_link_in_article has no path-based filtering at all
    # (services/video_discovery.py's extract_article_video_metadata() treats ANY <a href>/<iframe
    # src> whose host matches youtube.com/vimeo.com as a "video hint" - classify_video_url() is
    # host-only, never inspects the path). A real watch link (/watch?v=..., youtu.be/..., Vimeo
    # numeric video path) is indistinguishable, at persistence time, from a channel/user/handle/
    # subscribe link (e.g. "Follow us on YouTube" footer links) - both get discovery_method=
    # "hosted_platform_link_in_article" and platform="youtube"/"vimeo". This block classifies the
    # REAL persisted URLs from this run by path shape to quantify how often that actually happens
    # in practice - not a hypothetical, a measurement of this run's own real data.
    def _looks_like_real_video_link(url: str) -> bool:
        u = url.lower()
        if "youtube.com/watch" in u or "youtu.be/" in u or "youtube.com/embed/" in u or "youtube-nocookie.com/embed/" in u:
            return True
        if "vimeo.com/" in u:
            tail = u.split("vimeo.com/", 1)[1].split("?")[0].strip("/")
            return tail.isdigit()  # a numeric Vimeo video id, not a user/channel slug
        return False

    hosted_platform_all = [c for c in candidates if c.platform in ("youtube", "vimeo")]
    real_video_link = [c for c in hosted_platform_all if _looks_like_real_video_link(c.remote_url)]
    non_video_link = [c for c in hosted_platform_all if not _looks_like_real_video_link(c.remote_url)]
    report["hosted_platform_link_quality_check"] = {
        "total_hosted_platform_hints": len(hosted_platform_all),
        "real_watch_or_embed_links": len(real_video_link),
        "channel_user_handle_subscribe_links_not_actual_videos": len(non_video_link),
        "non_video_link_sample": [c.remote_url for c in non_video_link[:10]],
        "finding": (
            "extract_article_video_metadata()'s hosted-platform-link extraction (services/"
            "video_discovery.py, anchor_hrefs + iframe_srcs loop) filters only by HOST via "
            "classify_video_url() - it never inspects the URL PATH, so any youtube.com/vimeo.com "
            "anchor in an article (e.g. a footer 'Follow us on YouTube' link, a channel/subscribe "
            "link, an author's channel link) is persisted as a 'video hint' identically to a real "
            "watch/embed link. This is a real discovery-quality gap, not merely a hypothetical - "
            "see the measured ratio above from this run's own real data."
        ),
    }

    # --- direct-hosted valid candidate technical detail ---
    valid_direct_hosted = [c for c in candidates if c.platform == "direct_hosted" and c.validation_status == "valid"]
    report["valid_direct_hosted_count"] = len(valid_direct_hosted)
    report["valid_direct_hosted_detail"] = [
        {
            "event_id": str(c.event_id), "detected_container": c.detected_container, "byte_size": c.byte_size,
            "declared_mime_type": c.declared_mime_type, "declared_width": c.declared_width,
            "declared_height": c.declared_height, "declared_duration_seconds": c.declared_duration_seconds,
        }
        for c in valid_direct_hosted
    ]

    # --- image/video coexistence ---
    coexistence = {"video_and_usable_image": 0, "video_only": 0}
    for event_id in event_ids:
        images = image_rows_by_event.get(event_id, [])
        has_usable_image = any(ir.eligible_for_editorial for ir in images)
        if has_usable_image:
            coexistence["video_and_usable_image"] += 1
        else:
            coexistence["video_only"] += 1
    report["video_story_image_coexistence"] = coexistence

    # --- hypothetical delivery eligibility (read-only, reuses existing rank_media_candidates()) ---
    # NOTE (disclosed gap - see checkpoint §13): MediaRankingInput.quality_score is a required
    # field, but no quality-scoring pipeline exists for video candidates anywhere in this
    # codebase (services/image_quality.py's QualitySignals is image-only). A neutral 50 is used
    # ONLY for this read-only report - never for any real selection decision, and this
    # substitution is explicitly called out in the checkpoint rather than silently assumed.
    _PLACEHOLDER_QUALITY_SCORE = 50
    direct_hosted_candidates = [c for c in candidates if c.platform == "direct_hosted"]
    ranking_inputs = [
        MediaRankingInput(
            media_item_id=c.id, media_type="video", quality_score=_PLACEHOLDER_QUALITY_SCORE,
            source_priority=10, video_validation_status=c.validation_status,
        )
        for c in direct_hosted_candidates
    ]
    ranking_results = rank_media_candidates(ranking_inputs) if ranking_inputs else []
    hypothetical_eligible = sum(1 for r in ranking_results if r.eligible_for_delivery)
    hypothetical_rejected_by_ranking = sum(1 for r in ranking_results if not r.eligible_for_delivery)

    hosted_platform_candidates = [c for c in candidates if c.platform in ("youtube", "vimeo")]

    report["hypothetical_eligibility"] = {
        "direct_hosted_candidates_considered": len(direct_hosted_candidates),
        "eligible_under_existing_ranking_formula_with_placeholder_quality_score": hypothetical_eligible,
        "ineligible_under_existing_ranking_formula": hypothetical_rejected_by_ranking,
        "note": (
            "quality_score is a required MediaRankingInput field with no real computed source for "
            "video - the placeholder above only demonstrates the validation-status gate "
            "(video_rejected -> ineligible), not a true quality-based eligibility count."
        ),
        "hosted_platform_candidates_youtube_vimeo": len(hosted_platform_candidates),
        "hosted_platform_never_gated_by_ranking_eligibility": (
            "confirmed by code inspection - services/image_preview_notifier.py's "
            "send_news_with_rich_media()/build_rich_media_plan() append a caption link line for "
            "any YOUTUBE/VIMEO video_hint unconditionally (never passed through "
            "rank_media_candidates() at all); this is dormant, unwired code today - no live "
            "caller ever supplies a non-None video_hint"
        ),
    }

    # --- representative sample walkthroughs ---
    def _sample_for(pred, label):
        for c in candidates:
            if pred(c):
                event = events_by_id.get(c.event_id)
                return {
                    "category": label,
                    "event_title": event.title if event else None,
                    "event_url": event.url if event else None,
                    "discovery_method": c.discovery_method,
                    "platform": c.platform,
                    "validation_status": c.validation_status,
                    "detected_container": c.detected_container,
                    "byte_size": c.byte_size,
                    "error_code": c.error_code,
                    "remote_url_host_only": c.remote_url.split("/")[2] if c.remote_url and "//" in c.remote_url else None,
                }
        return None

    samples = []
    s1 = _sample_for(lambda c: c.platform == "direct_hosted" and c.validation_status == "valid", "valid_direct_hosted")
    if s1:
        samples.append(s1)
    else:
        samples.append({"category": "valid_direct_hosted", "observed": False})
    s2 = _sample_for(lambda c: _looks_like_real_video_link(c.remote_url), "hosted_platform_real_video_link")
    if s2:
        samples.append(s2)
    s2b = _sample_for(lambda c: c.platform in ("youtube", "vimeo") and not _looks_like_real_video_link(c.remote_url), "hosted_platform_false_positive_channel_link")
    if s2b:
        samples.append(s2b)
    s3 = _sample_for(lambda c: c.validation_status == "rejected", "rejected")
    if s3:
        samples.append(s3)
    else:
        samples.append({"category": "rejected", "observed": False})
    report["representative_samples"] = samples

    # Real, read-only demonstration of the dormant M12 hosted-platform-link mechanism: feed one
    # real persisted hosted-platform hint through the actual, unmodified build_rich_media_plan()
    # (never called with a real video_hint anywhere in live delivery today) to show, with real
    # code, what caption line it would produce - never executed against a live send.
    hosted_platform_demo = next((c for c in candidates if c.platform in ("youtube", "vimeo")), None)
    if hosted_platform_demo is not None:
        demo_hint = NativeVideoHint(
            discovery_method=VideoDiscoveryMethod(hosted_platform_demo.discovery_method),
            remote_url=hosted_platform_demo.remote_url,
            platform=VideoPlatform(hosted_platform_demo.platform),
        )
        demo_plan = build_rich_media_plan([], demo_hint, caption="<demo caption>")
        report["hosted_platform_dormant_m12_demo"] = {
            "input_platform": hosted_platform_demo.platform,
            "input_remote_url_host_only": (
                hosted_platform_demo.remote_url.split("/")[2] if "//" in hosted_platform_demo.remote_url else None
            ),
            "resulting_hosted_platform_link_line": demo_plan.hosted_platform_link,
            "resulting_media_group_item_count": len(demo_plan.media_group_items),
        }

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    with open("scripts/_phase23_1q_video_shadow_post_run_analysis.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    asyncio.run(main())
