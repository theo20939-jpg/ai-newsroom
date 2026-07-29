"""Phase 16 M2 - bounded live network validation (docs/phase16_m2_secure_fetch_and_validation_
report.md §23/§26). Runs ONLY after the security test suite (tests/test_safe_fetch.py) already
passes. Strictly bounded: max 20 article pages, max 5 image downloads per article, max 50 total
image downloads, max 100MB total received image data, one article-fetch chain per event, no
authentication, no provider/search-engine calls, no repeated retries against a domain that just
failed. No page body or image byte is stored after validation - only the derived summary below.

Launch with:
    python -m scripts.phase16_m2_bounded_network_validation
"""
import asyncio
import json
import time
from typing import Any
from urllib.parse import urlsplit

from core.config import settings
from integrations.http.safe_fetch import SafeFetchError, SafeFetchPolicy, safe_fetch
from services.article_metadata import extract_article_image_metadata
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


async def main() -> None:
    total_images_downloaded = 0
    total_image_bytes = 0
    records: list[dict[str, Any]] = []

    for article_url in ARTICLE_URLS[:MAX_ARTICLES]:
        domain = urlsplit(article_url).hostname or "unknown"
        record: dict[str, Any] = {"domain": domain, "article_fetch": None, "metadata_methods": [], "candidate_count": 0, "validated_images": 0, "rejected_images": 0, "error_codes": [], "bytes": 0, "duration_s": 0.0}
        start = time.monotonic()
        try:
            result = await safe_fetch(article_url, policy=HTML_POLICY)
            record["article_fetch"] = f"http_{result.status_code}"
            if result.status_code < 400:
                html = result.body.decode("utf-8", errors="replace")
                hints = extract_article_image_metadata(html, base_url=result.final_url)
                record["metadata_methods"] = sorted({h.discovery_method.value for h in hints})
                record["candidate_count"] = len(hints)

                for hint in hints[:MAX_IMAGES_PER_ARTICLE]:
                    if total_images_downloaded >= MAX_TOTAL_IMAGES or total_image_bytes >= MAX_TOTAL_IMAGE_BYTES:
                        break
                    if not hint.remote_url:
                        continue
                    try:
                        image_result = await safe_fetch(hint.remote_url, policy=IMAGE_POLICY)
                        total_images_downloaded += 1
                        total_image_bytes += image_result.received_byte_count
                        record["bytes"] += image_result.received_byte_count
                        technical = validate_image_bytes(
                            image_result.body, max_pixels=settings.image_intelligence_max_decoded_pixels
                        )
                        if technical.error_code is None:
                            record["validated_images"] += 1
                        else:
                            record["rejected_images"] += 1
                            record["error_codes"].append(technical.error_code)
                    except SafeFetchError as error:
                        record["rejected_images"] += 1
                        record["error_codes"].append(error.code.value)
        except SafeFetchError as error:
            record["article_fetch"] = f"error:{error.code.value}"
        except Exception as error:
            record["article_fetch"] = f"unexpected_error:{type(error).__name__}"

        record["duration_s"] = round(time.monotonic() - start, 2)
        records.append(record)

    summary = {
        "articles_attempted": len(records),
        "articles_reachable": sum(1 for r in records if isinstance(r["article_fetch"], str) and r["article_fetch"].startswith("http_2")),
        "total_candidate_urls_found": sum(r["candidate_count"] for r in records),
        "total_images_downloaded": total_images_downloaded,
        "total_validated_images": sum(r["validated_images"] for r in records),
        "total_rejected_images": sum(r["rejected_images"] for r in records),
        "total_image_bytes_downloaded": total_image_bytes,
        "records": records,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
