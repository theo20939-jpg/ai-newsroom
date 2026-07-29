"""Phase 16 M4 - weight-variant calibration (docs/phase16_m4_relevance_ranking_report.md §21).
Offline, no network. Builds a bounded set of labeled synthetic scenarios where the "obviously
correct" top candidate is determinable from structural evidence alone (native attachment, textual
overlap, source relationship - never visual content), then scores each scenario under four
candidate weight variants (component budgets only - the underlying signals/formula are unchanged)
and reports top-1 agreement, to justify the weights actually shipped in services/image_relevance.py.

Launch with:
    python -m scripts.phase16_m4_weight_calibration
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from database.models.news_source import SourceType
from schemas.image_candidate import (
    AspectRatioBand,
    DeduplicationInfo,
    ImageCandidate,
    ImageCandidateStatus,
    ImageDiscoveryMethod,
    QualitySignals,
    QualityStatus,
    QualityValidation,
    ResolutionBand,
    TechnicalValidation,
    TelegramReference,
)
from services import image_relevance as relevance


def _candidate(discovery, *, label, remote_url=None, source_url=None, alt_text=None, quality_score=80, order=0, telegram=None):
    technical = TechnicalValidation(
        width=1200, height=630, format="JPEG", error_code=None, sha256=f"h-{label}",
        pixel_count=756000, byte_size=100_000,
    )
    quality = QualityValidation(
        status=QualityStatus.ACCEPTED, quality_score=quality_score,
        signals=QualitySignals(resolution_band=ResolutionBand.GOOD, aspect_ratio_band=AspectRatioBand.EDITORIAL_LANDSCAPE),
        deduplication=DeduplicationInfo(is_representative=True),
    )
    return ImageCandidate(
        candidate_id=label, event_id=uuid4(), source_type=SourceType.RSS, discovery_method=discovery,
        status=ImageCandidateStatus.VALIDATED, remote_url=remote_url, source_url=source_url,
        telegram=telegram, alt_text=alt_text, discovery_order=order, discovered_at=datetime.now(timezone.utc),
        technical_validation=technical, quality_validation=quality,
    )


@dataclass(frozen=True)
class Scenario:
    name: str
    event_title: str
    event_content: str
    event_url: str | None
    source_name: str | None
    candidates: list[ImageCandidate]
    expected_top: str


SCENARIOS = [
    Scenario(
        "native_only_trivial", "OpenAI announces GPT-5", "OpenAI today announced GPT-5.", None, "TechSite",
        [_candidate(ImageDiscoveryMethod.TELEGRAM_PHOTO, label="native", telegram=TelegramReference(message_id=1, media_kind="photo"))],
        "native",
    ),
    Scenario(
        "native_vs_unrelated_no_text", "OpenAI announces GPT-5", "OpenAI today announced GPT-5.",
        "https://techsite.com/a", "TechSite",
        [
            _candidate(ImageDiscoveryMethod.TELEGRAM_PHOTO, label="native", telegram=TelegramReference(message_id=1, media_kind="photo")),
            _candidate(ImageDiscoveryMethod.IMAGE_SRC_LINK, label="unrelated", remote_url="https://other.example/x.jpg", source_url="https://other.example/y", quality_score=95),
        ],
        "native",
    ),
    Scenario(
        "og_strong_overlap_vs_native_no_text", "OpenAI announces GPT-5", "OpenAI today announced GPT-5.",
        "https://techsite.com/article/gpt-5", "TechSite",
        [
            _candidate(ImageDiscoveryMethod.TELEGRAM_PHOTO, label="native", telegram=TelegramReference(message_id=1, media_kind="photo")),
            _candidate(ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, label="og", remote_url="https://techsite.com/gpt-5-launch.jpg", source_url="https://techsite.com/article/gpt-5", alt_text="OpenAI GPT-5 launch photo"),
        ],
        "og",
    ),
    Scenario(
        "og_vs_high_quality_unrelated_cdn", "OpenAI announces GPT-5", "OpenAI today announced GPT-5.",
        "https://techsite.com/article/gpt-5", "TechSite",
        [
            _candidate(ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, label="og", remote_url="https://techsite.com/gpt-5-launch.jpg", source_url="https://techsite.com/article/gpt-5", alt_text="GPT-5 launch photo", quality_score=70),
            _candidate(ImageDiscoveryMethod.IMAGE_SRC_LINK, label="unrelated", remote_url="https://stockphotos.example/beach.jpg", source_url="https://stockphotos.example/gallery", alt_text="beach vacation photo", quality_score=99),
        ],
        "og",
    ),
    Scenario(
        "rss_media_content_vs_generic_thumbnail", "New AI chip announced", "A company announced a new AI chip today.",
        None, "ChipNews",
        [
            _candidate(ImageDiscoveryMethod.RSS_MEDIA_CONTENT, label="entry", remote_url="https://chipnews.com/chip-launch.jpg", alt_text="AI chip launch photo"),
            _candidate(ImageDiscoveryMethod.RSS_MEDIA_THUMBNAIL, label="thumb", remote_url="https://chipnews.com/thumb.jpg", alt_text="thumbnail"),
        ],
        "entry",
    ),
    Scenario(
        "twitter_vs_jsonld_similar_strength", "New AI chip announced", "A company announced a new AI chip today.",
        "https://chipnews.com/article", "ChipNews",
        [
            _candidate(ImageDiscoveryMethod.JSONLD_ARTICLE_IMAGE, label="jsonld", remote_url="https://chipnews.com/chip.jpg", source_url="https://chipnews.com/article", alt_text="AI chip photo"),
            _candidate(ImageDiscoveryMethod.TWITTER_IMAGE, label="twitter", remote_url="https://chipnews.com/social.jpg", source_url="https://chipnews.com/article", alt_text="social preview"),
        ],
        "jsonld",
    ),
    Scenario(
        "logo_flagged_still_below_clean_hero", "Company X launches product", "Company X launched a new product today.",
        "https://companyx.com/news", "Company X",
        [
            _candidate(ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, label="hero", remote_url="https://companyx.com/product-hero.jpg", source_url="https://companyx.com/news", alt_text="Company X product launch photo"),
            _candidate(ImageDiscoveryMethod.OPEN_GRAPH_SECURE_IMAGE, label="logo", remote_url="https://companyx.com/logo.png", source_url="https://companyx.com/news", alt_text="Company X logo"),
        ],
        "hero",
    ),
    Scenario(
        "weak_provenance_rich_text_vs_native_sparse", "Startup Y raises funding round", "Startup Y announced a funding round today.",
        "https://startupnews.com/y", "StartupNews",
        [
            _candidate(ImageDiscoveryMethod.IMAGE_SRC_LINK, label="richtext", remote_url="https://startupnews.com/startup-y-funding-round.jpg", source_url="https://startupnews.com/y", alt_text="Startup Y funding round announcement photo"),
            _candidate(ImageDiscoveryMethod.TELEGRAM_PHOTO, label="native", telegram=TelegramReference(message_id=1, media_kind="photo"), quality_score=50),
        ],
        "richtext",
    ),
    Scenario(
        "enclosure_vs_inline_image", "Weekly roundup published", "This week's roundup covers several stories.",
        None, "RoundupBlog",
        [
            _candidate(ImageDiscoveryMethod.RSS_ENCLOSURE, label="enclosure", remote_url="https://roundupblog.com/cover.jpg", alt_text="weekly roundup cover"),
            _candidate(ImageDiscoveryMethod.RSS_INLINE_IMAGE, label="inline", remote_url="https://roundupblog.com/inline1.jpg", alt_text=None),
        ],
        "enclosure",
    ),
    Scenario(
        "conflicting_relationship_loses_to_same_article", "Security flaw disclosed", "Researchers disclosed a security flaw today.",
        "https://secnews.com/article", "SecNews",
        [
            _candidate(ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, label="correct", remote_url="https://secnews.com/flaw.jpg", source_url="https://secnews.com/article", alt_text="security flaw disclosure diagram"),
            _candidate(ImageDiscoveryMethod.IMAGE_SRC_LINK, label="conflicting", remote_url="https://elsewhere.example/x.jpg", source_url="https://elsewhere.example/other-page", alt_text="security flaw disclosure diagram", quality_score=99),
        ],
        "correct",
    ),
    # Adversarial: quality must not dominate a conflicting-relationship, textless candidate over a
    # correctly-attached native image (discriminates the quality-heavy control variant).
    Scenario(
        "quality_must_not_dominate_conflicting_relationship", "OpenAI announces GPT-5", "OpenAI today announced GPT-5.",
        "https://techsite.com/article/gpt-5", "TechSite",
        [
            _candidate(ImageDiscoveryMethod.TELEGRAM_PHOTO, label="native", telegram=TelegramReference(message_id=1, media_kind="photo"), quality_score=55),
            _candidate(ImageDiscoveryMethod.IMAGE_SRC_LINK, label="conflicting_high_quality", remote_url="https://other.example/x.jpg", source_url="https://other.example/unrelated-page", quality_score=100),
        ],
        "native",
    ),
    # Adversarial: a genuinely richer (more unique matched terms), but relationship-conflicting
    # candidate should still not beat a correctly-attached, real-but-modest-overlap OG image
    # (discriminates the text-overlap-heavy variant).
    Scenario(
        "conflicting_rich_text_vs_correct_modest_text", "OpenAI announces GPT-5 model update", "OpenAI today announced GPT-5, a major new model update for developers worldwide.",
        "https://techsite.com/article/gpt-5", "TechSite",
        [
            _candidate(ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, label="correct", remote_url="https://techsite.com/gpt-5.jpg", source_url="https://techsite.com/article/gpt-5", alt_text="GPT-5"),
            _candidate(ImageDiscoveryMethod.IMAGE_SRC_LINK, label="conflicting_rich_text", remote_url="https://other.example/gpt-5-model-update-developers.jpg", source_url="https://other.example/unrelated-page", alt_text="OpenAI GPT-5 major new model update developers worldwide"),
        ],
        "correct",
    ),
]

VARIANTS = {
    "A_provenance_heavy": {"PROVENANCE_MAX": 45, "RELATIONSHIP_MAX": 25, "TEXTUAL_OVERLAP_MAX": 10, "QUALITY_MAX": 12, "METADATA_CONFIDENCE_MAX": 8},
    "B_balanced_shipped": {"PROVENANCE_MAX": 30, "RELATIONSHIP_MAX": 20, "TEXTUAL_OVERLAP_MAX": 25, "QUALITY_MAX": 15, "METADATA_CONFIDENCE_MAX": 10},
    "C_text_overlap_heavy": {"PROVENANCE_MAX": 15, "RELATIONSHIP_MAX": 15, "TEXTUAL_OVERLAP_MAX": 45, "QUALITY_MAX": 15, "METADATA_CONFIDENCE_MAX": 10},
    "D_quality_heavy_control": {"PROVENANCE_MAX": 15, "RELATIONSHIP_MAX": 15, "TEXTUAL_OVERLAP_MAX": 15, "QUALITY_MAX": 45, "METADATA_CONFIDENCE_MAX": 10},
}


def _run_variant(budgets: dict[str, int]) -> dict:
    originals = {name: getattr(relevance, name) for name in budgets}
    for name, value in budgets.items():
        setattr(relevance, name, value)
    try:
        results = []
        agree = 0
        for scenario in SCENARIOS:
            ranked = relevance.rank_candidates(
                scenario.candidates, event_title=scenario.event_title, event_content=scenario.event_content,
                event_url=scenario.event_url, source_name=scenario.source_name, top_candidates=5,
            )
            top = next((c for c in ranked if c.relevance_validation and c.relevance_validation.rank == 1), None)
            top1_id = top.candidate_id if top else None
            correct = top1_id == scenario.expected_top
            agree += int(correct)
            results.append({"scenario": scenario.name, "top1": top1_id, "expected": scenario.expected_top, "agree": correct})
        return {"top1_agreement": f"{agree}/{len(SCENARIOS)}", "details": results}
    finally:
        for name, value in originals.items():
            setattr(relevance, name, value)


def main() -> None:
    report = {name: _run_variant(budgets) for name, budgets in VARIANTS.items()}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
