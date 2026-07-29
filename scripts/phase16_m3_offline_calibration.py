"""Phase 16 M3 - offline calibration dataset (docs/phase16_m3_quality_and_deduplication_report.md
§23). Read-only, no network. Generates every required fixture category programmatically (Pillow
only - no committed real/copyrighted images) and runs the full M3 pipeline (services.image_
quality.analyze_candidate + services.image_deduplication.cluster_candidates) against them,
reporting the resulting status/score/signals for manual review.

Launch with:
    python -m scripts.phase16_m3_offline_calibration
"""
import io
import json
from datetime import datetime, timezone
from uuid import uuid4

from PIL import Image, ImageDraw

from database.models.news_source import SourceType
from schemas.image_candidate import ImageCandidate, ImageCandidateStatus, ImageDiscoveryMethod, TechnicalValidation
from services.image_deduplication import cluster_candidates
from services.image_quality import analyze_candidate


def _gradient_scene(w: int, h: int, offset: int = 0) -> Image.Image:
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x + offset) % 256, (y + offset) % 256, (x + y + offset) % 256)
    draw = ImageDraw.Draw(img)
    draw.ellipse((w * 0.1, h * 0.1, w * 0.5, h * 0.5), fill=(200, 30, 30))
    return img


def _solid(w: int, h: int, color=(240, 240, 240), mode="RGB") -> Image.Image:
    return Image.new(mode, (w, h), color=color if mode == "RGB" else color + (255,))


def _to_bytes(img: Image.Image, fmt="PNG", **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


def _candidate(url: str, width: int, height: int, data: bytes, discovery=ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, alt=None, order=0) -> ImageCandidate:
    import hashlib

    return ImageCandidate(
        candidate_id=f"cand-{uuid4().hex[:8]}", event_id=uuid4(), source_type=SourceType.RSS,
        discovery_method=discovery, status=ImageCandidateStatus.VALIDATED, remote_url=url,
        alt_text=alt, discovery_order=order, discovered_at=datetime.now(timezone.utc),
        technical_validation=TechnicalValidation(
            width=width, height=height, format="PNG", error_code=None,
            sha256=hashlib.sha256(data).hexdigest(), pixel_count=width * height, byte_size=len(data),
        ),
    )


CATEGORIES: dict[str, tuple[str, Image.Image]] = {}


def _register(name: str, url: str, img: Image.Image) -> None:
    CATEGORIES[name] = (url, img)


_register("tracking_pixel", "https://ads.example.com/track/pixel.gif", _solid(1, 1))
_register("favicon", "https://example.com/favicon.ico", _solid(32, 32, color=(50, 90, 200)))
_register("app_icon", "https://example.com/assets/app-icon-192.png", _solid(192, 192, (30, 30, 30), mode="RGBA"))
_register("publisher_logo", "https://example.com/assets/site-logo.png", _solid(300, 100, (10, 10, 10)))
_register("author_avatar", "https://example.com/authors/jane-doe-avatar.jpg", _gradient_scene(200, 200, offset=10))
_register("social_placeholder", "https://example.com/img/default-placeholder.png", _solid(600, 315, (230, 230, 230)))
_register("wide_banner", "https://example.com/ads/leaderboard-banner-ad.jpg", _gradient_scene(970, 90, offset=20))
_register("normal_landscape", "https://example.com/article/hero-photo.jpg", _gradient_scene(1200, 630, offset=30))
_register("normal_portrait", "https://example.com/article/portrait-photo.jpg", _gradient_scene(700, 1050, offset=40))
_register("product_screenshot", "https://example.com/product/screenshot-ui.png", _gradient_scene(1440, 900, offset=50))
_register("infographic", "https://example.com/article/data-infographic.png", _gradient_scene(800, 2000, offset=60))
_register("branded_launch_artwork", "https://example.com/launch/product-launch-keyart.jpg", _gradient_scene(1600, 900, offset=70))
_register("unrelated_image", "https://example.com/other/unrelated-photo.jpg", _gradient_scene(1200, 630, offset=200))


def main() -> None:
    results = []
    items_for_dedup: list[tuple[ImageCandidate, object]] = []
    landscape_candidate_id: str | None = None

    order = 0
    for name, (url, img) in CATEGORIES.items():
        data = _to_bytes(img)
        candidate = _candidate(url, *img.size, data, order=order)
        analysis = analyze_candidate(data, candidate=candidate)
        items_for_dedup.append((candidate, analysis))
        if name == "normal_landscape":
            landscape_candidate_id = candidate.candidate_id
        results.append({
            "category": name, "dimensions": img.size, "hard_rejection_reasons": analysis.hard_rejection_reasons,
            "quality_warnings": analysis.quality_warnings, "quality_score": analysis.quality_score,
            "resolution_band": analysis.signals.resolution_band.value, "aspect_ratio_band": analysis.signals.aspect_ratio_band.value,
        })
        order += 1
    assert landscape_candidate_id is not None

    # exact duplicate: reuse normal_landscape's exact bytes
    landscape_url, landscape_img = CATEGORIES["normal_landscape"]
    landscape_bytes = _to_bytes(landscape_img)
    exact_dup_candidate = _candidate("https://example.com/article/hero-photo-mirror.jpg", *landscape_img.size, landscape_bytes, order=order)
    exact_dup_analysis = analyze_candidate(landscape_bytes, candidate=exact_dup_candidate)
    items_for_dedup.append((exact_dup_candidate, exact_dup_analysis))
    order += 1

    # resized duplicate
    resized_img = landscape_img.resize((600, 315), Image.Resampling.LANCZOS)
    resized_bytes = _to_bytes(resized_img)
    resized_candidate = _candidate("https://example.com/article/hero-photo-small.jpg", *resized_img.size, resized_bytes, order=order)
    resized_analysis = analyze_candidate(resized_bytes, candidate=resized_candidate)
    items_for_dedup.append((resized_candidate, resized_analysis))
    order += 1

    # recompressed duplicate (JPEG)
    recompressed_bytes = _to_bytes(landscape_img, "JPEG", quality=40)
    recompressed_candidate = _candidate("https://example.com/article/hero-photo.jpg?q=40", *landscape_img.size, recompressed_bytes, order=order)
    recompressed_analysis = analyze_candidate(recompressed_bytes, candidate=recompressed_candidate)
    items_for_dedup.append((recompressed_candidate, recompressed_analysis))
    order += 1

    # cropped related image
    w, h = landscape_img.size
    cropped_img = landscape_img.crop((int(w * 0.2), int(h * 0.2), int(w * 0.8), int(h * 0.8))).resize((w, h))
    cropped_bytes = _to_bytes(cropped_img)
    cropped_candidate = _candidate("https://example.com/article/hero-photo-cropped.jpg", *cropped_img.size, cropped_bytes, order=order)
    cropped_analysis = analyze_candidate(cropped_bytes, candidate=cropped_candidate)
    items_for_dedup.append((cropped_candidate, cropped_analysis))

    dedup_results = cluster_candidates(items_for_dedup)
    name_by_id = {
        exact_dup_candidate.candidate_id: "exact_duplicate_of_landscape",
        resized_candidate.candidate_id: "resized_duplicate_of_landscape",
        recompressed_candidate.candidate_id: "recompressed_duplicate_of_landscape",
        cropped_candidate.candidate_id: "cropped_related_of_landscape",
    }

    def _cluster_key(info) -> str | None:
        """A single, transitively-resolved cluster identity per candidate: its own perceptual
        cluster id if it founded/belongs to one directly, else its representative's."""
        if info.perceptual_cluster_id:
            return info.perceptual_cluster_id
        if info.duplicate_of and info.duplicate_of in dedup_results:
            return _cluster_key(dedup_results[info.duplicate_of])
        return None

    landscape_cluster_key = _cluster_key(dedup_results[landscape_candidate_id])

    # Which candidate becomes "the representative" among near-identical technical peers is a
    # legitimate, secondary tie-break outcome (this run's synthetic JPEG q=40 re-encode happens to
    # be BYTE-LARGER than the PNG original for this specific gradient pattern, so the documented
    # "-byte_size, larger preferred" tie-break can pick it over the original) - what calibration
    # actually cares about is whether each variant landed in the SAME perceptual cluster.
    dedup_summary = {}
    for cid, info in dedup_results.items():
        label = name_by_id.get(cid, "other")
        if label != "other":
            dedup_summary[label] = {
                "duplicate_of_is_set": info.duplicate_of is not None,
                "hamming_distance": info.hamming_distance,
                "is_representative": info.is_representative,
                "same_perceptual_cluster_as_landscape": _cluster_key(info) == landscape_cluster_key,
            }

    print(json.dumps({"per_category_analysis": results, "deduplication_calibration": dedup_summary}, indent=2, default=str))


if __name__ == "__main__":
    main()
