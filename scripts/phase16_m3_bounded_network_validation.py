"""Phase 16 M3 - bounded live network validation (docs/phase16_m3_quality_and_deduplication_
report.md §24). Runs only after the offline quality/dedup test suite already passes. Reuses the
M2 safe-fetch boundary and the same strict limits as scripts/phase16_m2_bounded_network_validation.
py (max 20 article pages, max 5 images per article, max 50 total images, max 100MB total), adding
M3 quality analysis + within-event deduplication on top of the same fetched bytes - no additional
network request per image beyond what M2 already made.

Launch with:
    python -m scripts.phase16_m3_bounded_network_validation
"""
import asyncio
import json
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from core.config import settings
from database.models.news_source import SourceType
from integrations.http.safe_fetch import SafeFetchError, SafeFetchPolicy, safe_fetch
from schemas.image_candidate import ImageCandidate, ImageCandidateStatus, ImageDiscoveryMethod
from services.article_metadata import extract_article_image_metadata
from services.image_deduplication import cluster_candidates
from services.image_quality import analyze_candidate
from services.image_validation import validate_image_bytes

MAX_ARTICLES = 20
MAX_IMAGES_PER_ARTICLE = 5
MAX_TOTAL_IMAGES = 50
MAX_TOTAL_IMAGE_BYTES = 100 * 1024 * 1024

ARTICLE_URLS = [
    "https://3dnews.ru/1145923",
    "https://9to5google.com/2026/07/28/honor-robot-phone-gets-official-camera-specs-launches-on-the-same-day-as-pixel-11/",
    "https://9to5mac.com/2026/07/29/the-outsiders-adds-more-detailed-performance-metrics-workout-sharing-more/",
    "https://9to5toys.com/2026/07/28/today-android-app-deals-maneater/",
    "https://abcnews.com/International/scientists-warn-invasive-species-superspreader-event-due-stalling/story?id=135051186",
    "https://abeljansma.nl/2026/07/10/truth-is-not-a-direction.html",
    "https://abhi.now/blog/calm-technologies/",
    "https://academic.oup.com/sleep/article/47/1/zsad253/7280269",
    "https://addisoncrump.info/research/on-accountability/",
    "https://aeon.co/essays/uncovering-a-global-ancient-history-beyond-greece-and-rome",
    "https://alexklos.ca/blog/how-do-we-stop-vibe-coding",
    "https://alexwlchan.net/2026/non-breaking-code/",
    "https://alexyang.dev/vim-ascii-art/",
    "https://ammoniaenergy.org/articles/flexible-renewable-ammonia-demonstrator-now-operational-in-minnesota/",
    "https://anatolyzenkov.com/stolen-buttons",
    "https://ankursethi.com/blog/your-analytics-are-lying-to-you/",
    "https://anthropeum.com/",
    "https://antithesis.com/blog/2026/finding-bugs-in-raft-implementations/",
    "https://arcprize.org/leaderboard",
    "https://areadenial.games/design/preface#00-01",
]

HTML_POLICY = SafeFetchPolicy(
    connect_timeout_seconds=settings.image_intelligence_connect_timeout_seconds,
    read_timeout_seconds=settings.image_intelligence_read_timeout_seconds,
    total_timeout_seconds=settings.image_intelligence_total_timeout_seconds,
    max_redirects=settings.image_intelligence_max_redirects,
    max_bytes=settings.image_intelligence_max_html_bytes,
)
IMAGE_POLICY = SafeFetchPolicy(
    connect_timeout_seconds=settings.image_intelligence_connect_timeout_seconds,
    read_timeout_seconds=settings.image_intelligence_read_timeout_seconds,
    total_timeout_seconds=settings.image_intelligence_total_timeout_seconds,
    max_redirects=settings.image_intelligence_max_redirects,
    max_bytes=settings.image_intelligence_max_image_bytes,
)


def _make_candidate(url: str, order: int, event_id) -> ImageCandidate:
    from datetime import datetime, timezone

    return ImageCandidate(
        candidate_id=f"cand-{uuid4().hex[:8]}", event_id=event_id, source_type=SourceType.RSS,
        discovery_method=ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, status=ImageCandidateStatus.DISCOVERED,
        remote_url=url, discovery_order=order, discovered_at=datetime.now(timezone.utc),
    )


async def main() -> None:
    total_images_downloaded = 0
    total_image_bytes = 0
    records: list[dict[str, Any]] = []

    for article_url in ARTICLE_URLS[:MAX_ARTICLES]:
        domain = urlsplit(article_url).hostname or "unknown"
        record: dict[str, Any] = {
            "domain": domain, "article_fetch": None, "candidate_count": 0,
            "images": [], "duration_s": 0.0,
        }
        start = time.monotonic()
        event_id = uuid4()
        try:
            result = await safe_fetch(article_url, policy=HTML_POLICY)
            record["article_fetch"] = f"http_{result.status_code}"
            if result.status_code < 400:
                html = result.body.decode("utf-8", errors="replace")
                hints = extract_article_image_metadata(html, base_url=result.final_url)
                record["candidate_count"] = len(hints)

                items = []
                for order, hint in enumerate(hints[:MAX_IMAGES_PER_ARTICLE]):
                    if total_images_downloaded >= MAX_TOTAL_IMAGES or total_image_bytes >= MAX_TOTAL_IMAGE_BYTES:
                        break
                    if not hint.remote_url:
                        continue
                    candidate = _make_candidate(hint.remote_url, order, event_id)
                    try:
                        image_result = await safe_fetch(hint.remote_url, policy=IMAGE_POLICY)
                        total_images_downloaded += 1
                        total_image_bytes += image_result.received_byte_count
                        technical = validate_image_bytes(
                            image_result.body, max_pixels=settings.image_intelligence_max_decoded_pixels
                        )
                        candidate = candidate.model_copy(update={
                            "status": ImageCandidateStatus.VALIDATED if technical.error_code is None else ImageCandidateStatus.REJECTED_TECHNICAL,
                            "technical_validation": technical,
                        })
                        if technical.error_code is None:
                            analysis = analyze_candidate(image_result.body, candidate=candidate)
                            items.append((candidate, analysis))
                            record["images"].append({
                                "url_domain": urlsplit(hint.remote_url).hostname,
                                "width": technical.width, "height": technical.height,
                                "aspect_ratio": technical.aspect_ratio, "byte_size": technical.byte_size,
                                "technical_status": candidate.status.value,
                                "hard_rejection_reasons": analysis.hard_rejection_reasons,
                                "quality_warnings": analysis.quality_warnings,
                                "quality_score": analysis.quality_score,
                                "resolution_band": analysis.signals.resolution_band.value,
                                "aspect_ratio_band": analysis.signals.aspect_ratio_band.value,
                            })
                        else:
                            record["images"].append({
                                "url_domain": urlsplit(hint.remote_url).hostname,
                                "technical_status": candidate.status.value, "error_code": technical.error_code,
                            })
                    except SafeFetchError as error:
                        record["images"].append({"url_domain": urlsplit(hint.remote_url).hostname, "fetch_error": error.code.value})

                if items:
                    dedup = cluster_candidates(items)
                    for i, (candidate, analysis) in enumerate(items):
                        info = dedup[candidate.candidate_id]
                        record["images"][i]["exact_cluster_id"] = info.exact_cluster_id
                        record["images"][i]["perceptual_cluster_id"] = info.perceptual_cluster_id
                        record["images"][i]["duplicate_of_index"] = info.duplicate_of
                        record["images"][i]["is_representative"] = info.is_representative
        except SafeFetchError as error:
            record["article_fetch"] = f"error:{error.code.value}"
        except Exception as error:
            record["article_fetch"] = f"unexpected_error:{type(error).__name__}"

        record["duration_s"] = round(time.monotonic() - start, 2)
        records.append(record)

    summary = {
        "articles_attempted": len(records),
        "total_images_downloaded": total_images_downloaded,
        "total_image_bytes_downloaded": total_image_bytes,
        "records": records,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
