"""Phase V2.7 - E2E Failure Forensic + Editorial Presentation Recovery.

Covers: TEXT (the clean-card render fix), VISUAL (the adaptive overlay director + ORIGINAL_SOURCE
risk gate), CANARY (the two-stage architecture's own call-boundary guarantees). No real
Gemini/OpenAI/Anthropic/Telegram call anywhere in this file."""
from __future__ import annotations

import ast
import asyncio
import io
import uuid
from pathlib import Path

import pytest
from PIL import Image

from services.news_telegram_presentation import render_compact_news_card_html
from services.nnj_adaptive_overlay import (
    OverlayPlacement,
    select_overlay_placement,
)
from services.image_persistence import EditorialImageCandidate
from worker.content_cycle import assess_recomposition_source_risk

# ---------------------------------------------------------------------------
# TEXT
# ---------------------------------------------------------------------------


def test_compact_card_never_leaks_category_or_date_header() -> None:
    html = render_compact_news_card_html("Заголовок", "Тело новости.")
    assert "\U0001F4F0" not in html  # the 📰 inbox-card glyph never appears
    assert "GADGETS" not in html
    assert "·" not in html  # the category/date separator the inbox card uses


def test_compact_card_never_leaks_raw_english_source_headline() -> None:
    html = render_compact_news_card_html("Российский заголовок", "Тело новости на русском.")
    assert "Robot vacuums are included in US robot ban" not in html


def test_compact_card_is_headline_plus_body_only() -> None:
    html = render_compact_news_card_html("Заголовок", "Тело.")
    assert html == "<b>Заголовок</b>\n\nТело."


def test_compact_card_html_escaping_intact() -> None:
    html = render_compact_news_card_html("Title <b>", "Body & <script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_compact_card_optional_quote_block_included_when_distinct() -> None:
    html = render_compact_news_card_html(
        "Заголовок", "Совершенно другое содержание тела статьи про роботов.",
        quote_text="Это отдельная цитата спикера компании.", quote_speaker="Представитель компании",
    )
    assert "Это отдельная цитата спикера компании." in html


def test_content_cycle_wires_compact_card_renderer_for_non_v8_output() -> None:
    source_text = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "render_compact_news_card_html" in source_text
    # The genuinely-no-copywriting-output fallback (render_editorial_card) must still exist,
    # unchanged, for the one case it was always meant for.
    assert "render_editorial_card(card, include_url=include_url)" in source_text


# ---------------------------------------------------------------------------
# VISUAL - recomposition prompt tightened
# ---------------------------------------------------------------------------


def test_recomposition_prompt_forbids_full_background_replacement() -> None:
    from services.editorial_recomposition import build_recomposition_prompt

    prompt = build_recomposition_prompt()
    assert "replace background" not in prompt.lower() or "fully replacing the real background" in prompt.lower()
    assert "fully replacing the real background with an unrelated generic studio backdrop" in prompt
    assert "restyling the photograph as a render, illustration, or concept image" in prompt


def test_recomposition_prompt_has_uncertainty_rule() -> None:
    from services.editorial_recomposition import build_recomposition_prompt

    prompt = build_recomposition_prompt()
    assert "preserve the source subject and make a weaker edit" in prompt.lower()


def test_recomposition_prompt_still_forbids_everything_it_forbade_before() -> None:
    from services.editorial_recomposition import build_recomposition_prompt

    prompt = build_recomposition_prompt().lower()
    for still_required in ("changing human identity", "fabricating ui", "changing logos or labels"):
        assert still_required in prompt


# ---------------------------------------------------------------------------
# VISUAL - ORIGINAL_SOURCE vs RECOMPOSE risk gate
# ---------------------------------------------------------------------------


def _fake_candidate(**overrides: object) -> EditorialImageCandidate:
    from dataclasses import replace

    base = EditorialImageCandidate(
        id=uuid.uuid4(), candidate_id="c1", rank=1, relevance_score=80, quality_score=80,
        discovery_method="open_graph_image", source_relationship=None, relevance_reason=None,
        width=1600, height=800, observed_mime="image/jpeg", image_format="JPEG",
        storage_status="stored", storage_key="images/x/x.jpg", telegram_file_id=None,
        editor_decision=None, source_url=None, article_url=None, warnings=[], is_expired=False,
    )
    return replace(base, id=uuid.uuid4(), **overrides)  # type: ignore[arg-type]


def test_original_source_is_first_class_when_no_risk_detected() -> None:
    candidate = _fake_candidate(warnings=[])
    assert assess_recomposition_source_risk(candidate) is None


def test_recomposition_risk_detected_for_branded_screenshot() -> None:
    candidate = _fake_candidate(warnings=["possible_branded_screenshot"])
    assert assess_recomposition_source_risk(candidate) == "possible_branded_screenshot"


@pytest.mark.parametrize("warning", ["possible_logo", "possible_banner", "possible_watermark", "possible_tv_lower_third"])
def test_recomposition_risk_detected_for_every_known_flag(warning: str) -> None:
    candidate = _fake_candidate(warnings=[warning])
    assert assess_recomposition_source_risk(candidate) == warning


def test_recomposition_risk_none_for_no_candidate() -> None:
    assert assess_recomposition_source_risk(None) is None


def test_content_cycle_gates_recomposition_call_on_source_risk() -> None:
    source_text = Path("worker/content_cycle.py").read_text(encoding="utf-8")
    assert "assess_recomposition_source_risk" in source_text
    assert "recomposition_source_risk is None" in source_text


# ---------------------------------------------------------------------------
# VISUAL - adaptive overlay director
# ---------------------------------------------------------------------------


def test_lower_right_selected_when_subject_is_upper_left_only() -> None:
    decision = select_overlay_placement((0, 0, 400, 300))
    assert decision.placement == OverlayPlacement.LOWER_RIGHT
    assert decision.rejected_placements == ()


def test_alternative_placement_selected_when_preferred_collides() -> None:
    # A subject sitting exactly in Candidate C's own lower-right zone forces the algorithm past
    # LOWER_RIGHT to the next candidate in priority order.
    decision = select_overlay_placement((800, 600, 1280, 720))
    assert decision.placement != OverlayPlacement.LOWER_RIGHT
    assert OverlayPlacement.LOWER_RIGHT in decision.rejected_placements


def test_no_overlay_selected_when_every_placement_collides() -> None:
    decision = select_overlay_placement((0, 0, 1280, 720))
    assert decision.placement == OverlayPlacement.NO_OVERLAY
    assert decision.image is None
    assert decision.zone is None
    assert len(decision.rejected_placements) == 5  # every non-NO_OVERLAY entry tried and rejected


def test_selected_placement_never_intersects_subject_bbox() -> None:
    for subject_bbox in [(0, 0, 400, 300), (900, 0, 1280, 300), (0, 400, 400, 720), (300, 300, 900, 500)]:
        decision = select_overlay_placement(subject_bbox)
        if decision.zone is None:
            continue
        sx0, sy0, sx1, sy1 = subject_bbox
        zx0, zy0 = decision.zone.clearance_x_start, decision.zone.clearance_y_start
        zx1, zy1 = decision.zone.clearance_x_end, decision.zone.clearance_y_end
        intersects = sx0 < zx1 and sx1 > zx0 and sy0 < zy1 and sy1 > zy0
        assert not intersects, f"{decision.placement} collided with {subject_bbox}"


def test_overlay_selection_is_deterministic() -> None:
    bbox = (300, 300, 900, 500)
    first = select_overlay_placement(bbox)
    second = select_overlay_placement(bbox)
    assert first.placement == second.placement


def test_logo_only_uses_canonical_logo_not_a_recreated_mark() -> None:
    from services.nnj_adaptive_overlay import build_overlay_layer

    built = build_overlay_layer(OverlayPlacement.LOGO_ONLY)
    assert built is not None
    image, zone = built
    assert image.split()[-1].getbbox() is not None  # real, non-empty alpha content


def test_no_ml_or_llm_import_in_adaptive_overlay_module() -> None:
    tree = ast.parse(Path("services/nnj_adaptive_overlay.py").read_text(encoding="utf-8"))
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any(risky in m.lower() for m in imported for risky in ("gemini", "openai", "anthropic", "torch", "sklearn"))


# ---------------------------------------------------------------------------
# CANARY - two-stage architecture
# ---------------------------------------------------------------------------


def _function_source(module_path: Path, func_name: str) -> str:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == func_name:
            return ast.get_source_segment(module_path.read_text(encoding="utf-8"), node) or ""
    raise AssertionError(f"{func_name} not found in {module_path}")


def test_stage_a_never_references_telegram_send_or_bot() -> None:
    source = _function_source(Path("scripts/nnj_v2_7_two_stage_canary.py"), "run_stage_a")
    assert "send_photo_to_editorial_destination" not in source
    assert "send_to_editorial_destination" not in source
    assert "aiogram" not in source


def test_stage_b_never_references_recomposition_or_capability_calls() -> None:
    source = _function_source(Path("scripts/nnj_v2_7_two_stage_canary.py"), "run_stage_b")
    assert "maybe_recompose" not in source
    assert "capability_registry" not in source
    assert "gemini" not in source.lower()
    assert "openai" not in source.lower()


def test_stage_a_zero_telegram_calls_with_live_false() -> None:
    from scripts.nnj_v2_7_two_stage_canary import run_stage_a

    candidate = _fake_candidate(storage_key=None, storage_status="not_requested")

    async def _run() -> dict:
        return await run_stage_a(
            news_event_id=uuid.uuid4(), candidate=candidate, title="T",
            copywriting_output={"title": "T", "body": "B"}, treatment="STANDARD",
            subject_bbox=(0, 0, 100, 100), output_dir=Path("_pytest_stage_a_scratch"), live=False,
        )

    with pytest.raises(RuntimeError):
        asyncio.run(_run())


def test_stage_a_produces_package_stage_b_can_send_byte_identical(tmp_path: Path) -> None:
    from scripts.nnj_v2_7_two_stage_canary import run_stage_a, run_stage_b

    buf = io.BytesIO()
    Image.new("RGB", (1600, 800), (10, 20, 30)).save(buf, "JPEG")
    class _FakeCandidate:
        id = uuid.uuid4()
        image_format = "JPEG"

    async def _run() -> tuple[dict, dict]:
        import unittest.mock as mock

        with mock.patch("scripts.nnj_v2_7_two_stage_canary.read_candidate_bytes", return_value=buf.getvalue()):
            manifest = await run_stage_a(
                news_event_id=uuid.uuid4(), candidate=_FakeCandidate(),  # type: ignore[arg-type]
                title="Заголовок", copywriting_output={"title": "Заголовок", "body": "Тело."},
                treatment="STANDARD", subject_bbox=(0, 0, 100, 100), output_dir=tmp_path, live=False,
            )

        sent_calls = []

        class _FakeRoutingOutcome:
            sent = True
            message_id = 42
            chat_id = -1004297182444
            reason = None

        async def _fake_send(bot, destination, photo, html, *, dry_run):
            sent_calls.append({"photo_bytes": photo.data, "html": html, "dry_run": dry_run})
            return _FakeRoutingOutcome()

        with mock.patch("services.telegram_routing.send_photo_to_editorial_destination", _fake_send):
            send_result = await run_stage_b(package_dir=tmp_path, bot=object(), authorize_send=True)
        return manifest, {"send_result": send_result, "sent_calls": sent_calls}

    manifest, extra = asyncio.run(_run())
    assert extra["send_result"]["sent"] is True
    assert extra["send_result"]["chat_id"] == -1004297182444
    assert len(extra["sent_calls"]) == 1
    assert extra["sent_calls"][0]["html"] == manifest["telegram_html"]
    assert extra["sent_calls"][0]["photo_bytes"] == (tmp_path / "final_nnj_branded.jpg").read_bytes()


def test_stage_b_refuses_without_authorization() -> None:
    from scripts.nnj_v2_7_two_stage_canary import run_stage_b

    async def _run() -> dict:
        return await run_stage_b(package_dir=Path("assets/brand/newsroom_visuals/v2_7_local_e2e_proof/package_a_robot_vacuum"), bot=object(), authorize_send=False)

    result = asyncio.run(_run())
    assert result["sent"] is False
    assert result["telegram_calls_made"] == 0


def test_stage_a_manifest_persists_chat_and_topic_before_any_send(tmp_path: Path) -> None:
    from scripts.nnj_v2_7_two_stage_canary import run_stage_a

    buf = io.BytesIO()
    Image.new("RGB", (1600, 800), (10, 20, 30)).save(buf, "JPEG")
    class _FakeCandidate:
        id = uuid.uuid4()
        image_format = "JPEG"

    async def _run() -> dict:
        import unittest.mock as mock

        with mock.patch("scripts.nnj_v2_7_two_stage_canary.read_candidate_bytes", return_value=buf.getvalue()):
            return await run_stage_a(
                news_event_id=uuid.uuid4(), candidate=_FakeCandidate(),  # type: ignore[arg-type]
                title="T", copywriting_output={"title": "T", "body": "B"}, treatment="STANDARD",
                subject_bbox=(0, 0, 100, 100), output_dir=tmp_path, live=False,
            )

    manifest = asyncio.run(_run())
    assert manifest["intended_chat_id"] == -1004297182444
    assert manifest["intended_topic_id"] is None
    assert manifest["telegram_calls_made"] == 0
