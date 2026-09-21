"""Phase B.5R: reference fidelity reconstruction. Proves (no provider call) that the reference is analysed from real
pixels, that Visual DNA v2 keeps the board's distinct visual families instead of averaging them, and that the safe
renderer can express those families - including dark solid surfaces WITHOUT any overlay."""
from __future__ import annotations

import base64
import hashlib
import io
import itertools
import json
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from core.config import settings  # noqa: F401  (settings import proves the app config still loads)
from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramSlideLayout, LayoutRegion
from scripts import _instagram_phase_b5r_families as fam
from scripts import _instagram_phase_b5r_render as render
from services.instagram_declarative_layout import (
    PALETTES,
    DeclaredRenderRejected,
    render_declared_slide,
)
from services.instagram_layout_signature import geometry_distance, structure_profile
from services.instagram_layout_validation import validate_layout
from services.instagram_reference_analysis import (
    ReferenceAnalysisUnavailableError,
    analyze_reference_samples,
    build_sample_analysis_request,
    prepare_reference_image,
)
from services.instagram_reference_segmentation import build_row_montages, crop_sample, reference_samples
from services.instagram_visual_dna import REFERENCE_BOARD_PATH, VisualDnaOriginalityError, load_visual_dna
from services.instagram_visual_dna_v2 import (
    InstagramVisualDNAV2,
    assert_v2_mechanics_only,
    family_mix,
    load_visual_dna_v2,
    render_visual_dna_v2_context,
    surface_mix,
)

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_IMAGES = fam.assets()


class _CapturingGateway:
    def __init__(self, output: dict) -> None:
        self.output = output
        self.requests: list[GenerateRequest] = []

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        return GenerateResponse(text=None, structured_output=self.output, finish_reason="stop", model_used="fake", usage=CapabilityUsage())


def _v2_dna() -> InstagramVisualDNAV2:
    dna = load_visual_dna_v2()
    assert dna is not None, "docs/references/instagram/visual_dna/v2.json must be stored"
    return dna


# ------------------------------------------------------------------ reference pixels / analysis path


def test_segmentation_finds_all_board_samples_inside_the_real_image() -> None:
    board = Image.open(REFERENCE_BOARD_PATH).convert("RGB")
    samples = reference_samples()
    assert len(samples) == 20 and {s.row for s in samples} == {1, 2, 3, 4}
    for s in samples:
        x0, y0, x1, y1 = s.box
        assert 0 <= x0 < x1 <= board.width and 0 <= y0 < y1 <= board.height
        crop = crop_sample(board, s, scale=1.0)
        extrema = crop.convert("L").getextrema()
        assert extrema[1] - extrema[0] > 60, f"{s.sample_id} crop is blank"
    for a, b in itertools.combinations(samples, 2):
        ix = min(a.box[2], b.box[2]) - max(a.box[0], b.box[0])
        iy = min(a.box[3], b.box[3]) - max(a.box[1], b.box[1])
        assert not (ix > 0 and iy > 0), f"{a.sample_id} overlaps {b.sample_id}"


@pytest.mark.asyncio
async def test_sample_analysis_sends_the_real_board_and_labelled_crops_as_image_bytes() -> None:
    _jpeg, _uri, digest = prepare_reference_image(REFERENCE_BOARD_PATH)
    assert digest == hashlib.sha256(REFERENCE_BOARD_PATH.read_bytes()).hexdigest()
    gateway = _CapturingGateway({})  # an empty output is rejected AFTER the request is built
    raw: list = []
    with pytest.raises(ReferenceAnalysisUnavailableError):
        await analyze_reference_samples(
            gateway, FilePromptRepository(_PROMPTS), reference_path=REFERENCE_BOARD_PATH,  # type: ignore[arg-type]
            repo_relative_path="docs/references/instagram/instagram_visual_reference_board_v1.png", raw_sink=raw,
        )
    request = gateway.requests[0]
    assert "image" in request.modalities
    parts = [p for m in request.messages for p in m.content if p.type == "artifact_ref"]
    assert len(parts) == 1 + len(build_row_montages(REFERENCE_BOARD_PATH))  # the full board + one montage per row
    for part in parts:
        image = Image.open(io.BytesIO(base64.b64decode(part.artifact_ref.split(",", 1)[1])))
        assert image.width > 300 and image.height > 100
    text = " ".join(p.text or "" for m in request.messages for p in m.content if p.type == "text")
    assert "docs/references" not in text and "S01" in text and "S20" in text
    assert raw == [{}]  # the raw model output is persisted even when validation rejects it


def test_prompt_v3_forces_sample_by_sample_and_forbids_averaging_and_style_questions() -> None:
    prompt = FilePromptRepository(_PROMPTS).resolve("instagram_reference_analysis", "3")
    blob = (prompt.system + " ".join(prompt.rules)).lower()
    assert "every labelled sample" in blob and "without averaging" in blob and "contradictory" in blob
    assert "describe the visual style" not in blob
    assert set(prompt.output_schema["properties"]) >= {"samples", "families", "contradictions_kept_distinct", "must_not_copy"}
    assert "docs/references" not in blob


def test_v3_request_builder_lists_every_sample_id() -> None:
    prompt = FilePromptRepository(_PROMPTS).resolve("instagram_reference_analysis", "3")
    ids = [s.sample_id for s in reference_samples()]
    request = build_sample_analysis_request(prompt, board_data_uri="data:image/jpeg;base64,AA==", montage_data_uris=["data:image/jpeg;base64,AA=="], sample_ids=ids)
    text = " ".join(p.text or "" for m in request.messages for p in m.content if p.type == "text")
    assert all(i in text for i in ids)


# ------------------------------------------------------------------ Visual DNA v2


def test_v2_keeps_multiple_families_and_membership_references_analysed_samples() -> None:
    dna = _v2_dna()
    assert len(dna.samples) == 20 and len(dna.families) >= 5
    known = {s.sample_id for s in dna.samples}
    assert known == {s.sample_id for s in reference_samples()}
    for family in dna.families:
        assert set(family.member_samples) <= known
    covered = {m for f in dna.families for m in f.member_samples}
    assert covered == known, "every reference sample belongs to at least one family"
    assert max(f["count"] for f in family_mix(dna).values()) < len(known) * 0.5  # no family swallows the board


def test_v2_records_the_real_surface_distribution_dark_is_the_majority_light_is_not_the_default() -> None:
    mix = surface_mix(_v2_dna())
    dark = mix["dark_solid"] + mix["dark_image_field"]
    assert dark > mix["light"] + mix["mixed"]
    families = _v2_dna().families
    assert any(f.dark_surface_allowed for f in families) and any(not f.dark_surface_allowed for f in families)
    assert all(f.image_overlay_allowed is False for f in families)


def test_v2_does_not_average_contradictory_examples_and_global_invariants_exclude_layout_choices() -> None:
    dna = _v2_dna()
    assert len(dna.contradictions_kept_distinct) >= 3
    blob = " ".join(dna.global_invariants).lower()
    for banned in ("white background", "dark background", "whitespace", "left-aligned", "split ratio"):
        assert banned not in blob
    ranges = {(f.density_min, f.density_max) for f in dna.families}
    assert len(ranges) >= 2, "families do not share one averaged density"
    order = ("low", "medium", "high")
    covered = {d for f in dna.families for d in order if order.index(f.density_min) <= order.index(d) <= order.index(f.density_max)}
    assert covered == set(order)


def test_v2_guidance_is_mechanics_only_and_must_not_copy_is_mandatory() -> None:
    dna = _v2_dna()
    assert_v2_mechanics_only(dna)
    assert dna.must_not_copy and dna.originality_constraints
    leaky = dna.model_copy(update={"global_invariants": [*dna.global_invariants, "use the exact headline about the mac studio launch"]})
    with pytest.raises(VisualDnaOriginalityError):
        assert_v2_mechanics_only(leaky)
    coords = dna.model_copy(update={"global_invariants": [*dna.global_invariants, "place the headline at x=120 and colour #ff0000"]})
    with pytest.raises(VisualDnaOriginalityError):
        assert_v2_mechanics_only(coords)
    with pytest.raises(ValueError):
        InstagramVisualDNAV2.model_validate({**json.loads(dna.model_dump_json()), "must_not_copy": []})
    bad_member = json.loads(dna.model_dump_json())
    bad_member["families"][0]["member_samples"] = ["S99"]
    with pytest.raises(ValueError):
        InstagramVisualDNAV2.model_validate(bad_member)


def test_v2_context_for_the_creative_director_carries_families_not_a_path() -> None:
    dna = _v2_dna()
    text = render_visual_dna_v2_context(dna)
    assert all(f.family_id in text for f in dna.families)
    assert "RENDERER CONSTRAINTS" in text and "MUST NOT COPY" in text and "docs/references" not in text
    assert "NO overlays" in text


def test_v1_is_retained_and_still_the_default_loader_target() -> None:
    v1 = load_visual_dna()
    assert v1 is not None and v1.version == "1"


# ------------------------------------------------------------------ renderer expressivity


def _rendered() -> dict[str, list[dict]]:
    return render.render_all()


def test_every_family_has_two_accepted_compositions_with_zero_overlay() -> None:
    families = {f.family_id for f in _v2_dna().families}
    results = _rendered()
    assert set(results) == families
    for family_id, rows in results.items():
        assert len(rows) == 2
        for row in rows:
            assert row["result"] is not None, (family_id, row["comp"]["name"], row["validated"].rejection_codes)
            assert row["result"].text_clipped is False
            assert row["result"].source_image_treatment != "overlay"
            assert row["result"].notes["source_media_pixels_unaltered"] in (True, None)


def test_dark_solid_surface_renders_without_overlay_scrim_dimming_or_blur() -> None:
    row = _rendered()["dark_type_number_statement"][0]
    image = row["result"].image.convert("L")
    assert image.getpixel((900, 700)) < 20 and image.getpixel((40, 1300)) < 20  # a real dark designed surface
    assert row["comp"]["layout"]["background"] == "ink"
    media_row = _rendered()["hero_object_stage"][0]  # dark surface + independent media
    assert media_row["result"].notes["source_media_pixels_unaltered"] is True
    assert media_row["result"].notes["media_regions"][0]["treatment"] == "cover_cropped"


def test_media_heavy_composition_lets_media_own_the_frame() -> None:
    row = _rendered()["immersive_image_field"][0]
    regions = [r for r in row["comp"]["layout"]["regions"] if r["kind"] == "media"]
    assert sum(r["w"] * r["h"] for r in regions) >= 0.85
    assert row["result"].notes["source_media_pixels_unaltered"] is True
    assert structure_profile(row["comp"]["layout"])["text_on_media"] == "yes"


def test_collage_uses_multiple_media_at_different_scales_with_tilt_and_devices() -> None:
    layout = _rendered()["culture_collage"][1]["comp"]["layout"]
    medias = [r for r in layout["regions"] if r["kind"] == "media"]
    assert len(medias) >= 3 and len({round(r["w"] * r["h"], 2) for r in medias}) == len(medias)
    assert any(r["tilt_deg"] for r in medias) and any(r["graphic_type"] == "badge" for r in layout["regions"] if r["kind"] == "graphic")
    assert _rendered()["culture_collage"][1]["result"].notes["media_regions_tilted"] >= 2


def test_number_hero_and_interface_devices_are_expressible() -> None:
    a1 = _rendered()["dark_type_number_statement"][0]
    numeral = next(r for r in a1["comp"]["layout"]["regions"] if r["content_ref"] == "number")
    assert numeral["scale_token"] == "NUMERAL" and numeral["w"] * numeral["h"] >= 0.2
    e1 = _rendered()["interface_cards"][0]
    assert any(r["graphic_type"] == "poll_cards" for r in e1["comp"]["layout"]["regions"] if r["kind"] == "graphic")


def test_density_range_low_medium_and_high_is_supported() -> None:
    densities = {row["comp"]["layout"]["density"] for rows in _rendered().values() for row in rows}
    assert densities == {"LOW", "MEDIUM", "HIGH"}


def test_same_family_two_plans_look_related_but_have_materially_different_geometry() -> None:
    for family_id, comps in fam.FAMILY_COMPOSITIONS.items():
        a, b = comps[0]["layout"], comps[1]["layout"]
        assert geometry_distance(a, b) >= 0.5, family_id  # not the same layout nudged
        assert a["visual_weight"] == b["visual_weight"], family_id  # but the same family character


def test_different_families_have_materially_different_visual_structure() -> None:
    flat = [(f, c["name"], c["layout"]) for f, cs in fam.FAMILY_COMPOSITIONS.items() for c in cs]
    for (f1, n1, l1), (f2, n2, l2) in itertools.combinations(flat, 2):
        if f1 == f2:
            continue
        p1, p2 = structure_profile(l1), structure_profile(l2)
        assert sum(p1[k] != p2[k] for k in p1) >= 2, (n1, n2)
    images = {}
    results = _rendered()
    for family_id, rows in results.items():
        images[family_id] = rows[0]["result"].image
    for a, b in itertools.combinations(images, 2):
        diff = ImageChops.difference(images[a].convert("L"), images[b].convert("L"))
        assert sum(diff.histogram()[24:]) > 0.05 * diff.width * diff.height, (a, b)


def test_identical_plan_is_deterministic() -> None:
    comp = fam.FAMILY_COMPOSITIONS["culture_collage"][1]
    one, two = render.render_composition(comp, _IMAGES)[1], render.render_composition(comp, _IMAGES)[1]
    assert one is not None and two is not None and one.image.tobytes() == two.image.tobytes()


def test_no_overlay_primitives_in_the_renderer_source() -> None:
    import ast

    forbidden = {"apply_bottom_readability_gradient", "apply_top_readability_gradient", "build_dimmed_source_field", "GaussianBlur", "ImageFilter"}
    for module in ("services/instagram_declarative_layout.py", "services/instagram_layout_validation.py"):
        tree = ast.parse(Path(module).read_text(encoding="utf-8"))
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden:
                seen.add(node.id)
            if isinstance(node, ast.Attribute) and node.attr in ("alpha_composite", "filter"):
                seen.add(node.attr)
        assert not seen, (module, seen)


def test_text_on_media_needs_quiet_pixels_otherwise_the_plan_is_rejected_not_overlaid() -> None:
    noisy = Image.new("RGB", (1080, 1350), (120, 120, 120))
    for x in range(0, 1080, 40):
        noisy.paste((240, 240, 240), (x, 0, x + 20, 1350))  # bright and dark stripes: not quiet
    layout = InstagramSlideLayout.model_validate(fam._layout([
        fam._m(0.0, 0.0, 1.0, 1.0, "noisy"), fam._t(0.07, 0.62, 0.62, 0.26, ref="copy", token="HEADLINE_L", on_media=True),
    ], background="ink"))
    validated = validate_layout(layout, slide_copy="Заголовок", resolvable_subjects={"noisy"})
    assert validated.accepted and validated.layout is not None
    with pytest.raises(DeclaredRenderRejected):
        render_declared_slide(spec=render.SPEC, layout=validated.layout, slide_copy="Заголовок", index=0, total=1, subject_assets={"noisy": (noisy, "n")})
    from services.instagram_carousel_layouts import _try_declared

    outcome = _try_declared(spec=render.SPEC, layout_plan=layout.model_dump(), slide_copy="Заголовок", index=0, total=1,
                            subject_assets={"noisy": (noisy, "n")}, visual_direction=None)
    assert outcome == (None, ["text_on_media_unreadable"])  # the caller falls back to the deterministic renderer


def test_text_over_media_without_the_declaration_is_still_rejected() -> None:
    layout = InstagramSlideLayout.model_validate(fam._layout([
        fam._m(0.0, 0.0, 1.0, 1.0, "portrait"), fam._t(0.07, 0.62, 0.62, 0.26, ref="copy", token="HEADLINE_L"),
    ], background="ink"))
    validated = validate_layout(layout, slide_copy="Заголовок", resolvable_subjects={"portrait"})
    assert not validated.accepted and "text_over_media" in validated.rejection_codes


def test_brand_assets_and_colours_stay_renderer_owned() -> None:
    fields = set(LayoutRegion.model_fields) | set(InstagramSlideLayout.model_fields)
    assert not any(t in f for f in fields for t in ("font", "color", "colour", "hex", "css", "svg", "code"))
    with pytest.raises(ValueError):
        LayoutRegion.model_validate({**fam._t(0.1, 0.1, 0.5, 0.2), "tone": "#ff0000"})
    with pytest.raises(ValueError):
        InstagramSlideLayout.model_validate({**fam._layout([fam._t(0.1, 0.1, 0.5, 0.2)]), "palette": "custom"})
    assert set(PALETTES) == {"brand", "culture", "neo"} and PALETTES["brand"][0] == PALETTES["brand"][1]
    import services.instagram_declarative_layout as renderer

    assert "ig_brand_mark" in Path(renderer.__file__).read_text(encoding="utf-8")  # the canonical mark, never redrawn
