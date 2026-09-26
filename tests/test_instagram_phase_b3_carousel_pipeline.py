"""Phase B.3: the first real carousel system test - `scripts/_instagram_phase_b3_carousel_
diagnostic.py` exercised end to end (creative -> package -> compositor -> QA -> gate -> packaged
asset set), never mocked. Reuses the existing carousel domain model/renderer/validator (schemas.
instagram_creative.InstagramCarouselCreative, services.instagram_platform_renderer.
render_instagram_carousel) - no new abstraction, per the phase's own instruction."""
from __future__ import annotations

import ast
import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "_instagram_phase_b3_carousel_diagnostic.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("phase_b3_carousel_diagnostic", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synthetic_raw_png(tmp_path: Path) -> Path:
    # A real, decodable, non-blank source image standing in for the paid B.2 asset - this test
    # suite must never depend on B.2's actual bytes or on any network/provider access.
    image = Image.new("RGB", (1024, 1536), (40, 60, 90))
    for y in range(0, 1536, 40):
        for x in range(0, 1024, 40):
            image.putpixel((x, y), (220, 40, 30))
    path = tmp_path / "synthetic_raw.png"
    image.save(path, format="PNG")
    return path


def test_carousel_creative_validates_and_has_the_required_production_narrative_shape() -> None:
    mod = _load_module()
    carousel = mod._carousel_creative()
    assert len(carousel.slides) == 5
    roles = [s.role for s in carousel.slides]
    assert roles[0] == "hook"
    assert roles[-1] == "takeaway"
    assert len(set(roles)) == len(roles)  # every slide has a distinct narrative function
    assert all(s.slide_purpose for s in carousel.slides)


def test_slide_order_matches_the_required_five_role_narrative() -> None:
    mod = _load_module()
    carousel = mod._carousel_creative()
    assert [s.role for s in carousel.slides] == ["hook", "context", "comparison", "impact", "takeaway"]
    assert carousel.slides[0].slide_copy == mod._APPROVED_COVER_HEADLINE


def test_no_fabricated_facts_every_slide_traces_to_the_real_evidence_or_is_pure_framing() -> None:
    mod = _load_module()
    carousel = mod._carousel_creative()
    grounded = {s.source_evidence for s in carousel.slides if s.source_evidence is not None}
    assert grounded.issubset(set(mod._EVIDENCE))


def test_full_run_produces_exactly_five_1080x1350_png_slides(tmp_path: Path) -> None:
    mod = _load_module()
    raw_path = _synthetic_raw_png(tmp_path)
    out_dir = tmp_path / "carousel"
    import sys

    old_argv = sys.argv
    sys.argv = ["prog", str(raw_path), str(out_dir)]
    try:
        mod.main()
    finally:
        sys.argv = old_argv

    slide_files = sorted(out_dir.glob("slide_*.png"))
    assert [p.name for p in slide_files] == [f"slide_{i:02d}.png" for i in range(1, 6)]
    for path in slide_files:
        with Image.open(path) as img:
            assert img.size == (1080, 1350)
            assert img.mode in ("RGB", "RGBA")


def test_output_is_deterministic_across_two_runs(tmp_path: Path) -> None:
    mod = _load_module()
    raw_path = _synthetic_raw_png(tmp_path)
    import sys

    old_argv = sys.argv
    try:
        out_a = tmp_path / "run_a"
        sys.argv = ["prog", str(raw_path), str(out_a)]
        mod.main()
        out_b = tmp_path / "run_b"
        sys.argv = ["prog", str(raw_path), str(out_b)]
        mod.main()
    finally:
        sys.argv = old_argv

    for i in range(1, 6):
        name = f"slide_{i:02d}.png"
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes()


def test_manifest_json_is_created_and_traceable(tmp_path: Path) -> None:
    mod = _load_module()
    raw_path = _synthetic_raw_png(tmp_path)
    out_dir = tmp_path / "carousel"
    import sys

    old_argv = sys.argv
    sys.argv = ["prog", str(raw_path), str(out_dir)]
    try:
        mod.main()
    finally:
        sys.argv = old_argv

    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["total_slides"] == 5
    assert manifest["story_id"] == mod._STORY_ID
    assert manifest["provider_image_calls"] == 0
    assert manifest["incremental_image_cost_usd"] == "0"
    assert [s["index"] for s in manifest["slides"]] == [0, 1, 2, 3, 4]
    assert [s["file"] for s in manifest["slides"]] == [f"slide_{i:02d}.png" for i in range(1, 6)]


def test_contact_sheet_is_created_and_review_only_sized(tmp_path: Path) -> None:
    mod = _load_module()
    raw_path = _synthetic_raw_png(tmp_path)
    out_dir = tmp_path / "carousel"
    import sys

    old_argv = sys.argv
    sys.argv = ["prog", str(raw_path), str(out_dir)]
    try:
        mod.main()
    finally:
        sys.argv = old_argv

    sheet_path = out_dir / "contact_sheet.png"
    assert sheet_path.exists()
    with Image.open(sheet_path) as sheet:
        # 5 thumbnails, never a single Instagram-safe 1080x1350 slide - proves this is a distinct,
        # review-only composite rather than an accidental copy of one slide.
        assert sheet.size != (1080, 1350)
        assert sheet.width > sheet.height  # a horizontal contact strip, not another portrait slide


def test_russian_headline_text_is_not_clipped_on_the_approved_cover(tmp_path: Path) -> None:
    mod = _load_module()
    raw_path = _synthetic_raw_png(tmp_path)
    out_dir = tmp_path / "carousel"
    import sys

    old_argv = sys.argv
    sys.argv = ["prog", str(raw_path), str(out_dir)]
    try:
        mod.main()
    finally:
        sys.argv = old_argv

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    # this test is about RENDERING (no clipped Russian headline). The diagnostic fixture is a REACTION-angle carousel, so since the founder
    # review of 2026-09-26 the gate also reads it as viral copy - and correctly finds that slides 3 and 4 make one point from one evidence
    # sentence. That editorial finding is expected here; no rendering issue may block.
    render_blocking = [i for i in manifest["art_validation"]["blocking_issues"] if not i.startswith("viral_copy_quality:")]
    assert render_blocking == []
    assert manifest["art_validation"]["blocking_issues"] == [
        "viral_copy_quality: slides 3 and 4 make the same point (both rest on the same evidence item and the second adds no new concrete "
        "detail) - merge them or give the second a new fact"]
    assert all(not slide["text_clipped"] for slide in manifest["slides"])


def test_no_provider_image_call_is_possible_by_construction() -> None:
    """Structural guarantee, not just an observed count: this module cannot import the paid
    image-generation boundary at all."""
    with open(_SCRIPT_PATH, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    forbidden = {
        "services.budgeted_image_execution",
        "integrations.llm_gateway.providers.openai_image_adapter",
        "services.instagram_creative_media",
    }
    assert imported_modules.isdisjoint(forbidden), imported_modules & forbidden


def test_no_publication_or_telegram_path_touched() -> None:
    """Publication stays disabled and Telegram is untouched by construction: this diagnostic
    imports no bot/Telegram/delivery module at all - review artifacts are local files only."""
    with open(_SCRIPT_PATH, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    forbidden_prefixes = ("bot.", "services.telegram_", "services.brand_renderer", "services.instagram_telegram_")
    touched = {m for m in imported_modules if m.startswith(forbidden_prefixes) or m in {"bot"}}
    assert not touched, touched


def test_single_image_instagram_creative_still_renders_no_regression() -> None:
    """The carousel work must not regress the pre-existing single-format render path."""
    from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
    from services.instagram_content_package import build_instagram_content_package
    from services.instagram_creative_director import CreativeGenerationOutcome
    from services.instagram_format_director import ContentFormat, FormatDecision
    from services.instagram_platform_renderer import render_instagram_feed_image
    from services.instagram_shadow_pipeline import ShadowPlanResult
    from schemas.instagram_creative import InstagramSingleCreative

    opp = ContentOpportunity(id="opp-b3-regress", source_type=OpportunitySourceType.NEWS, story_id="s-b3-regress", product_mention_allowed=True)
    sp = ShadowPlanResult(
        campaign_name=None, campaign_phase=None, opportunity_description="regress check", primary_objective="reach",
        audience_description="", recommended_format="single", hook_family=None, creative_concept_summary="concept",
        alternative_format=None, alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.5,
    )
    single = InstagramSingleCreative(
        creative_angle="a", visual_concept="v", on_image_copy="No regression here", caption_direction="draft caption",
    )
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=sp,
        creative_outcome=CreativeGenerationOutcome(single=single),
    )
    result = render_instagram_feed_image(pkg)
    with Image.open(io.BytesIO(result.image_bytes)) as img:
        assert img.size == (1080, 1350)
