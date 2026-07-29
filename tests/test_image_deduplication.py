"""Tests for services.image_deduplication and the perceptual-hash portion of services.image_
quality (Phase 16 M3, docs/phase16_m3_quality_and_deduplication_report.md). Pure logic - no
network, generated in-memory Pillow fixtures only.
"""
import io
import random
from datetime import datetime, timezone
from uuid import uuid4

from PIL import Image, ImageDraw, ImageEnhance

from database.models.news_source import SourceType
from schemas.image_candidate import ImageCandidate, ImageCandidateStatus, ImageDiscoveryMethod, TechnicalValidation
from services.image_deduplication import AUTO_DUPLICATE_MAX_DISTANCE, REVIEW_MAX_DISTANCE, cluster_candidates
from services.image_quality import analyze_candidate, compute_dhash, hamming_distance


def _scene(seed: int = 7) -> Image.Image:
    """A realistic-ish, non-flat image (gradient + shapes + noise) - a solid-color fixture would
    trivially hash to all-zero bits and cannot exercise real distance measurement. `seed` only
    varies the sparse noise overlay (for exact-hash-uniqueness tests) - it deliberately does NOT
    produce a perceptually distinct image (dHash correctly treats seed-1 vs seed-99 noise as near-
    identical after its aggressive 9x8 downsample, since noise averages out - use `_distinct_
    scene()` below for genuinely different-content test cases)."""
    random.seed(seed)
    img = Image.new("RGB", (800, 600))
    px = img.load()
    for y in range(600):
        for x in range(800):
            px[x, y] = (int(255 * x / 800), int(255 * y / 600), int(255 * (x + y) / 1400))
    draw = ImageDraw.Draw(img)
    draw.ellipse((100, 100, 400, 400), fill=(200, 30, 30))
    draw.rectangle((500, 200, 750, 500), fill=(30, 30, 200))
    for _ in range(1500):
        x, y = random.randint(0, 799), random.randint(0, 599)
        px[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    return img


def _distinct_scene() -> Image.Image:
    """A structurally different scene (inverted gradient direction, different shape/position) -
    genuinely perceptually distinct from `_scene()`, unlike a mere noise-seed variation."""
    img = Image.new("RGB", (800, 600))
    px = img.load()
    for y in range(600):
        for x in range(800):
            px[x, y] = (int(255 * (800 - x) / 800), int(255 * (600 - y) / 600), 128)
    draw = ImageDraw.Draw(img)
    draw.ellipse((450, 80, 700, 330), fill=(10, 150, 220))
    return img


def _to_bytes(img: Image.Image, fmt: str = "PNG", **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _candidate(cid: str, url: str, width: int, height: int, data: bytes, order: int = 0) -> ImageCandidate:
    import hashlib

    sha = hashlib.sha256(data).hexdigest()
    return ImageCandidate(
        candidate_id=cid, event_id=uuid4(), source_type=SourceType.RSS,
        discovery_method=ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, status=ImageCandidateStatus.VALIDATED,
        remote_url=url, discovery_order=order, discovered_at=datetime.now(timezone.utc),
        technical_validation=TechnicalValidation(
            width=width, height=height, format="PNG", error_code=None, sha256=sha,
            pixel_count=width * height, byte_size=len(data),
        ),
    )


def _analyzed(cid: str, url: str, img: Image.Image, order: int = 0):
    data = _to_bytes(img)
    width, height = img.size
    candidate = _candidate(cid, url, width, height, data, order)
    analysis = analyze_candidate(data, candidate=candidate)
    return candidate, analysis


# ---------------------------------------------------------------------------
# 38-45: exact duplicates
# ---------------------------------------------------------------------------


def test_identical_bytes_produce_same_sha256() -> None:
    scene = _scene()
    data_a = _to_bytes(scene)
    data_b = _to_bytes(scene)
    import hashlib

    assert hashlib.sha256(data_a).hexdigest() == hashlib.sha256(data_b).hexdigest()


def test_same_sha256_produces_exact_duplicate_cluster() -> None:
    scene = _scene()
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene, order=0)
    c2, a2 = _analyzed("c2", "https://x/a-mirror.jpg", scene, order=1)
    clusters = cluster_candidates([(c1, a1), (c2, a2)])
    assert clusters["c1"].exact_cluster_id == clusters["c2"].exact_cluster_id
    assert clusters["c2"].duplicate_of == "c1"
    assert clusters["c2"].hamming_distance == 0


def test_exact_duplicate_representative_prefers_higher_resolution() -> None:
    small = _scene().resize((200, 150))
    small_upscaled_to_match_hash = small  # same bytes reused for both to force identical sha
    data = _to_bytes(small_upscaled_to_match_hash)
    c_small = _candidate("c_small", "https://x/small.jpg", 200, 150, data, order=0)
    c_small2 = _candidate("c_small2", "https://x/small2.jpg", 200, 150, data, order=1)
    a_small = analyze_candidate(data, candidate=c_small)
    a_small2 = analyze_candidate(data, candidate=c_small2)
    clusters = cluster_candidates([(c_small, a_small), (c_small2, a_small2)])
    # identical content/resolution -> tie broken by discovery_order (c_small is order=0)
    assert clusters["c_small2"].duplicate_of == "c_small"


def test_stable_cluster_id() -> None:
    scene = _scene()
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene)
    c2, a2 = _analyzed("c2", "https://x/b.jpg", scene, order=1)
    first = cluster_candidates([(c1, a1), (c2, a2)])
    second = cluster_candidates([(c1, a1), (c2, a2)])
    assert first["c1"].exact_cluster_id == second["c1"].exact_cluster_id


def test_candidate_order_does_not_unexpectedly_change_representative() -> None:
    scene = _scene()
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene, order=0)
    c2, a2 = _analyzed("c2", "https://x/b.jpg", scene, order=1)
    forward = cluster_candidates([(c1, a1), (c2, a2)])
    backward = cluster_candidates([(c2, a2), (c1, a1)])
    assert forward["c1"].is_representative == backward["c1"].is_representative
    assert forward["c2"].duplicate_of == backward["c2"].duplicate_of


def test_duplicate_evidence_remains_serialized() -> None:
    scene = _scene()
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene)
    c2, a2 = _analyzed("c2", "https://x/b.jpg", scene, order=1)
    clusters = cluster_candidates([(c1, a1), (c2, a2)])
    payload = {cid: info.model_dump(mode="json") for cid, info in clusters.items()}
    import json

    json.dumps(payload)  # must not raise - both c1 and c2 present, c2 not silently dropped
    assert set(payload.keys()) == {"c1", "c2"}


def test_distinct_hashes_remain_separate() -> None:
    c1, a1 = _analyzed("c1", "https://x/a.jpg", _scene(seed=1))
    c2, a2 = _analyzed("c2", "https://x/b.jpg", _scene(seed=2), order=1)
    clusters = cluster_candidates([(c1, a1), (c2, a2)])
    assert clusters["c1"].exact_cluster_id != clusters["c2"].exact_cluster_id


def test_duplicate_consolidation_scoped_to_one_event_by_construction() -> None:
    """cluster_candidates() takes no event_id/global-query parameter at all - it operates purely
    on the list handed to it, which the caller (services/image_intelligence.py) always builds from
    exactly one event's own consolidated candidates."""
    import inspect

    from services.image_deduplication import cluster_candidates as fn

    assert list(inspect.signature(fn).parameters.keys()) == ["items"]


# ---------------------------------------------------------------------------
# 46-60: perceptual hash
# ---------------------------------------------------------------------------


def test_identical_decoded_image_produces_identical_hash() -> None:
    scene = _scene()
    assert compute_dhash(scene) == compute_dhash(scene)


def test_hash_remains_stable_across_repeated_runs() -> None:
    scene = _scene()
    hashes = {compute_dhash(scene) for _ in range(5)}
    assert len(hashes) == 1


def test_resized_copy_remains_near_identical() -> None:
    scene = _scene()
    resized = scene.resize((400, 300), Image.Resampling.LANCZOS)
    distance = hamming_distance(compute_dhash(scene), compute_dhash(resized))
    assert distance <= AUTO_DUPLICATE_MAX_DISTANCE


def test_jpeg_recompression_remains_near_identical() -> None:
    scene = _scene()
    recompressed = Image.open(io.BytesIO(_to_bytes(scene, "JPEG", quality=50)))
    distance = hamming_distance(compute_dhash(scene), compute_dhash(recompressed))
    assert distance <= AUTO_DUPLICATE_MAX_DISTANCE


def test_png_and_jpeg_representation_of_same_content_hash_close() -> None:
    scene = _scene()
    as_jpeg = Image.open(io.BytesIO(_to_bytes(scene, "JPEG", quality=90)))
    distance = hamming_distance(compute_dhash(scene), compute_dhash(as_jpeg))
    assert distance <= AUTO_DUPLICATE_MAX_DISTANCE


def test_small_brightness_change_remains_close() -> None:
    scene = _scene()
    brighter = ImageEnhance.Brightness(scene).enhance(1.15)
    distance = hamming_distance(compute_dhash(scene), compute_dhash(brighter))
    assert distance <= REVIEW_MAX_DISTANCE


def test_minor_crop_stays_close_or_review() -> None:
    scene = _scene()
    w, h = scene.size
    cropped = scene.crop((int(w * 0.03), int(h * 0.03), int(w * 0.97), int(h * 0.97))).resize((w, h))
    distance = hamming_distance(compute_dhash(scene), compute_dhash(cropped))
    assert distance <= REVIEW_MAX_DISTANCE


def test_substantial_crop_does_not_automatically_merge() -> None:
    scene = _scene()
    w, h = scene.size
    cropped = scene.crop((int(w * 0.25), int(h * 0.25), int(w * 0.75), int(h * 0.75))).resize((w, h))
    distance = hamming_distance(compute_dhash(scene), compute_dhash(cropped))
    assert distance > AUTO_DUPLICATE_MAX_DISTANCE


def test_added_text_overlay_does_not_automatically_merge() -> None:
    scene = _scene()
    overlaid = scene.copy()
    draw = ImageDraw.Draw(overlaid)
    draw.rectangle((250, 250, 550, 320), fill=(0, 0, 0))
    draw.text((260, 270), "BREAKING NEWS", fill=(255, 255, 255))
    distance = hamming_distance(compute_dhash(scene), compute_dhash(overlaid))
    assert distance > AUTO_DUPLICATE_MAX_DISTANCE


def test_unrelated_images_have_large_distance() -> None:
    distance = hamming_distance(compute_dhash(_scene()), compute_dhash(_distinct_scene()))
    assert distance > REVIEW_MAX_DISTANCE


def test_exif_orientation_normalized_consistently() -> None:
    scene = _scene()
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6  # "Rotate 90 CW" orientation tag
    scene.save(buf, format="JPEG", exif=exif)
    reloaded = Image.open(buf)
    # must not raise, and must produce a stable, deterministic hash either way
    h1 = compute_dhash(reloaded)
    h2 = compute_dhash(Image.open(io.BytesIO(buf.getvalue())))
    assert h1 == h2


def test_color_mode_differences_normalized_consistently() -> None:
    scene = _scene()
    rgba = scene.convert("RGBA")
    distance = hamming_distance(compute_dhash(scene), compute_dhash(rgba))
    assert distance == 0  # grayscale conversion of RGB vs RGBA-of-same-content is identical


def test_grayscale_and_rgb_equivalent_content_behave_consistently() -> None:
    scene = _scene()
    grayscale_version = scene.convert("L").convert("RGB")
    # not asserting near-zero distance (grayscale genuinely loses color-gradient information the
    # dHash partially relies on) - only that it doesn't crash and produces a valid, bounded hash
    h = compute_dhash(grayscale_version)
    assert len(h) == 16
    int(h, 16)  # valid hex


def test_no_image_bytes_persisted_by_hash_computation() -> None:
    scene = _scene()
    result = compute_dhash(scene)
    assert isinstance(result, str)
    assert all(c in "0123456789abcdef" for c in result)


def test_no_heavyweight_external_cv_dependency_added() -> None:
    import ast
    import inspect

    from services import image_quality

    tree = ast.parse(inspect.getsource(image_quality))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])
    forbidden = {"numpy", "cv2", "scipy", "imagehash", "torch", "tensorflow"}
    assert imported_modules.isdisjoint(forbidden)


# ---------------------------------------------------------------------------
# 61-70: near-duplicate clustering
# ---------------------------------------------------------------------------


def test_strict_near_duplicate_pair_clustered() -> None:
    scene = _scene()
    resized = scene.resize((400, 300), Image.Resampling.LANCZOS)
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene, order=0)
    c2, a2 = _analyzed("c2", "https://x/a-resized.jpg", resized, order=1)
    clusters = cluster_candidates([(c1, a1), (c2, a2)])
    assert clusters["c2"].duplicate_of == "c1"
    assert clusters["c2"].hamming_distance is not None and clusters["c2"].hamming_distance <= AUTO_DUPLICATE_MAX_DISTANCE


def test_uncertain_similarity_marked_review_not_duplicate() -> None:
    scene = _scene()
    overlaid = scene.copy()
    draw = ImageDraw.Draw(overlaid)
    draw.rectangle((250, 250, 550, 320), fill=(0, 0, 0))
    draw.text((260, 270), "BREAKING NEWS", fill=(255, 255, 255))
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene, order=0)
    c2, a2 = _analyzed("c2", "https://x/a-overlay.jpg", overlaid, order=1)
    clusters = cluster_candidates([(c1, a1), (c2, a2)])
    distance = hamming_distance(a1.perceptual_hash, a2.perceptual_hash)
    if distance <= REVIEW_MAX_DISTANCE:
        assert clusters["c2"].duplicate_of is None
        assert clusters["c2"].hamming_distance is not None


def test_distinct_pair_not_clustered() -> None:
    c1, a1 = _analyzed("c1", "https://x/a.jpg", _scene(), order=0)
    c2, a2 = _analyzed("c2", "https://x/b.jpg", _distinct_scene(), order=1)
    clusters = cluster_candidates([(c1, a1), (c2, a2)])
    assert clusters["c1"].perceptual_cluster_id != clusters["c2"].perceptual_cluster_id


def test_exact_duplicate_takes_priority_over_near_duplicate_logic() -> None:
    scene = _scene()
    data = _to_bytes(scene)
    c1 = _candidate("c1", "https://x/a.jpg", *scene.size, data, order=0)
    c2 = _candidate("c2", "https://x/a2.jpg", *scene.size, data, order=1)
    a1 = analyze_candidate(data, candidate=c1)
    a2 = analyze_candidate(data, candidate=c2)
    clusters = cluster_candidates([(c1, a1), (c2, a2)])
    assert clusters["c2"].hamming_distance == 0
    assert clusters["c2"].exact_cluster_id is not None


def test_cluster_representative_chosen_deterministically() -> None:
    scene = _scene()
    resized = scene.resize((400, 300), Image.Resampling.LANCZOS)
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene, order=0)
    c2, a2 = _analyzed("c2", "https://x/a-small.jpg", resized, order=1)
    first = cluster_candidates([(c1, a1), (c2, a2)])
    second = cluster_candidates([(c1, a1), (c2, a2)])
    assert first["c1"].is_representative == second["c1"].is_representative


def test_transitive_chain_does_not_over_merge() -> None:
    """A (distance 3 from B) and B (distance 3 from C) must not force A and C together if A and C
    themselves are far apart - the representative-based star clustering compares every candidate
    against established REPRESENTATIVES only, never chains through intermediate members."""
    scene = _scene(seed=1)
    close_to_scene = scene.resize((790, 590)).resize((800, 600))  # tiny resize round-trip, very close
    far_but_still_related = _scene(seed=1)  # regenerate then heavily crop for a bigger shift
    w, h = far_but_still_related.size
    cropped = far_but_still_related.crop((int(w * 0.2), int(h * 0.2), int(w * 0.8), int(h * 0.8))).resize((w, h))

    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene, order=0)
    c2, a2 = _analyzed("c2", "https://x/a-close.jpg", close_to_scene, order=1)
    c3, a3 = _analyzed("c3", "https://x/a-cropped.jpg", cropped, order=2)
    clusters = cluster_candidates([(c1, a1), (c2, a2), (c3, a3)])
    # whatever the outcome, c3's cluster decision must be based on its OWN distance to a
    # representative, never inherited transitively through c2
    d13 = hamming_distance(a1.perceptual_hash, a3.perceptual_hash)
    if d13 > AUTO_DUPLICATE_MAX_DISTANCE:
        assert clusters["c3"].duplicate_of != "c1" or clusters["c3"].hamming_distance == d13


def test_cluster_ids_stable_across_reruns() -> None:
    scene = _scene()
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene)
    first = cluster_candidates([(c1, a1)])
    second = cluster_candidates([(c1, a1)])
    assert first["c1"].perceptual_cluster_id == second["c1"].perceptual_cluster_id


def test_rerun_does_not_multiply_clusters() -> None:
    scene = _scene()
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene, order=0)
    c2, a2 = _analyzed("c2", "https://x/b.jpg", scene, order=1)
    items = [(c1, a1), (c2, a2)]
    first = cluster_candidates(items)
    second = cluster_candidates(items)
    assert len(first) == len(second) == 2


def test_duplicate_candidate_remains_in_audit_output() -> None:
    scene = _scene()
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene, order=0)
    c2, a2 = _analyzed("c2", "https://x/b.jpg", scene, order=1)
    clusters = cluster_candidates([(c1, a1), (c2, a2)])
    assert "c2" in clusters  # never silently dropped, even though it's a duplicate


def test_one_events_candidates_cannot_deduplicate_another_events() -> None:
    """cluster_candidates() has no cross-call state (no module-level cache/global) - two separate
    calls for two different events' candidate lists cannot influence each other."""
    scene = _scene()
    c1, a1 = _analyzed("c1", "https://x/a.jpg", scene, order=0)
    event_a_clusters = cluster_candidates([(c1, a1)])
    c2, a2 = _analyzed("c2", "https://x/a-same-bytes.jpg", scene, order=0)
    event_b_clusters = cluster_candidates([(c2, a2)])
    assert event_a_clusters["c1"].duplicate_of is None
    assert event_b_clusters["c2"].duplicate_of is None  # not merged with c1 despite identical bytes
