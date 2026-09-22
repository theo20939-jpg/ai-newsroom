"""Phase B.5.1: real Creative Director -> Visual DNA v2 -> accepted renderer. Zero-cost contract tests (no provider call)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from PIL import Image
from pydantic import ValidationError

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import (
    CAROUSEL_ROLE_VOCABULARY,
    TERMINAL_ROLES,
    VISUAL_FAMILIES,
    InstagramCarouselCreative,
    InstagramCarouselSlideCreative,
)
from scripts import _instagram_phase_b5r3_families as fam3
from scripts._instagram_phase_b51_acceptance import (
    FixtureSubstitutionError,
    assert_no_fixture_substitution,
    routed_worst_case_call_cost,
)
from services import instagram_creative_director as cd
from services.instagram_asset_profile import profile_asset, render_profile_lines
from services.instagram_b4_observability import build_b4_observability
from services.instagram_content_package import _carousel_media_plan
from services.instagram_creative_director import (
    CAROUSEL_PROMPT_VERSION,
    CreativeContractError,
    CreativeDirectorInput,
    generate_carousel_creative,
)
from services.instagram_creative_plan_service import _fingerprint_from_draft, build_carousel_fatigue_note
from services.instagram_layout_signature import infer_family
from services.instagram_meta_language_guard import MetaLanguageLeakError, assert_no_meta_language, find_meta_language
from tests.test_instagram_phase_b5_visual_dna_declarative import _EVIDENCE, _carousel_output_with_layouts

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_LEAK = "не подпись и не кадры референса"


class _Gateway:
    def __init__(self, output: dict) -> None:
        self.output = output
        self.requests: list = []

    async def generate(self, request):
        self.requests.append(request)
        return GenerateResponse(text=None, structured_output=self.output, finish_reason="stop", model_used="fake", usage=CapabilityUsage())


def _input(**kw) -> CreativeDirectorInput:
    base = dict(objective="saves", format="carousel", opportunity_summary="s", allowed_evidence=[_EVIDENCE], locale="ru")
    base.update(kw)
    return CreativeDirectorInput(**base)


def _output(**overrides) -> dict:
    out = _carousel_output_with_layouts()
    out.update(overrides)
    return out


# ------------------------------------------------------------------------------------------ Visual DNA v2 is the active planning DNA


def test_active_visual_dna_is_v2_and_v1_is_not_on_the_planning_path(monkeypatch) -> None:
    import services.instagram_automatic_trigger as trigger
    import services.instagram_visual_dna as v1_module

    monkeypatch.setattr(v1_module, "load_visual_dna", lambda *a, **k: (_ for _ in ()).throw(AssertionError("v1 loaded by the planner")))
    context = trigger._visual_dna_context()
    assert trigger._visual_dna_version() == "2"
    assert "VISUAL DNA v2" in context and "MUST NOT COPY" in context and "GLOBAL INVARIANTS" in context
    for family in VISUAL_FAMILIES:  # the model sees exactly the ids it is allowed to output
        assert family in context, family
    assert "docs/references" not in context


def test_visual_dna_v1_is_preserved_on_disk_for_history() -> None:
    v1 = Path("docs/references/instagram/visual_dna/v1.json")
    v2 = Path("docs/references/instagram/visual_dna/v2.json")
    assert v1.is_file() and v2.is_file()
    assert json.loads(v1.read_text(encoding="utf-8"))["version"] == "1" and json.loads(v2.read_text(encoding="utf-8"))["version"] == "2"


# ------------------------------------------------------------------------------------------ prompt v9


def _prompt():
    return FilePromptRepository(_PROMPTS).resolve("instagram_creative_director_carousel", "9")


def test_v9_replaces_the_stale_v8_visual_rules_and_v8_is_untouched() -> None:
    assert CAROUSEL_PROMPT_VERSION == "10.6"
    rules = " ".join(_prompt().rules)
    for stale in ("Do not plan black or dark surfaces", "light editorial paper or soft grey", "nothing is ever placed over an image"):
        assert stale not in rules
    assert "solid dark surfaces" in rules and "NO overlay, scrim, dimming" in rules
    assert "do NOT fall back to light_utility_editorial" in rules
    v8 = Path("prompts/instagram_creative_director_carousel/v8.yaml").read_text(encoding="utf-8")
    assert "Do not plan black or dark surfaces" in v8  # history preserved, not mutated in place
    assert yaml.safe_load(v8)["version"] == "8"


def test_v9_schema_is_bounded_family_role_and_layout_vocabulary() -> None:
    schema = _prompt().output_schema
    slide = schema["properties"]["slides"]["items"]["properties"]
    assert tuple(slide["visual_family"]["enum"]) == VISUAL_FAMILIES
    assert tuple(slide["role"]["enum"]) == CAROUSEL_ROLE_VOCABULARY
    assert set(TERMINAL_ROLES) <= set(CAROUSEL_ROLE_VOCABULARY) and "caption" not in CAROUSEL_ROLE_VOCABULARY
    layout = slide["layout"]["properties"]
    assert {"ink", "graphite", "paper", "soft"} == set(layout["background"]["enum"])
    assert set(layout["arrangement"]["enum"]) == {"standard", "collage", "stage"} and set(layout["logo_position"]["enum"]) == {"BOTTOM_RIGHT", "BOTTOM_LEFT"}
    region = layout["regions"]["items"]["properties"]
    assert "object_contain" in region["crop_mode"]["enum"] and "media_ground" in region["surface"]["enum"] and "on_media" in region and "tilt_deg" in region
    assert not any(k for k in slide if any(t in k for t in ("overlay", "scrim", "dim", "tint")))  # overlay stays impossible
    assert set(schema["properties"]["content_archetype"]["enum"]) == {"ai_hack", "news_insight", "news_recap", "trend_generative"}

    def strict(node) -> None:  # OpenAI strict shape: every property required, no extras
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert set(node["required"]) == set(node["properties"]) and node["additionalProperties"] is False
            for value in node.values():
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)

    strict(schema)


@pytest.mark.asyncio
async def test_v9_request_carries_dna_v2_the_media_profile_and_the_meta_language_rule() -> None:
    import services.instagram_automatic_trigger as trigger

    gateway = _Gateway(_output())
    await generate_carousel_creative(gateway, FilePromptRepository(_PROMPTS), director_input=_input(  # type: ignore[arg-type]
        visual_dna_context=trigger._visual_dna_context(), visual_dna_version="2", media_note="no real image is available for this post"))
    system, user = gateway.requests[0].messages[0].content[0].text, gateway.requests[0].messages[1].content[0].text
    assert "VISUAL DNA v2" in user and "FAMILY immersive_image_field" in user and "RENDERER CONSTRAINTS" in user
    assert "не подпись и не кадры референса" in system  # named as a forbidden example
    assert "docs/references" not in system and "docs/references" not in user  # the raw board / a path is never sent per post


# ------------------------------------------------------------------------------------------ family field / dark surfaces / overlay


def test_visual_family_is_a_bounded_value_never_a_free_name() -> None:
    base = dict(role="hook", slide_copy="Заголовок", visual_direction="v")
    assert InstagramCarouselSlideCreative(**base, visual_family="hero_object_stage").visual_family == "hero_object_stage"
    for family in VISUAL_FAMILIES:
        InstagramCarouselSlideCreative(**base, visual_family=family)
    with pytest.raises(ValidationError):
        InstagramCarouselSlideCreative(**base, visual_family="my_new_family")
    assert InstagramCarouselSlideCreative(**base).visual_family is None  # legacy payloads parse


def test_dark_solid_surface_is_allowed_and_overlay_still_cannot_be_planned() -> None:
    out = _output()
    out["slides"][0]["layout"]["background"] = "ink"
    out["slides"][0]["overlay_mode"] = "dark"  # a legacy/hostile field is discarded at the schema boundary
    creative = InstagramCarouselCreative.model_validate(out)
    assert creative.slides[0].layout.background == "ink" and not hasattr(creative.slides[0], "overlay_mode")


# ------------------------------------------------------------------------------------------ role contract


def _with_roles(roles: list[str]) -> dict:
    out = _output()
    template = out["slides"]
    out["slides"] = [{**template[min(i, len(template) - 1)], "role": role, "slide_copy": f"Мысль номер {i + 1} для проверки", "slide_purpose": role}
                     for i, role in enumerate(roles)]
    return out


@pytest.mark.parametrize("terminal", ["result", "takeaway", "cta", "closing"])
def test_every_conclusion_role_is_a_valid_terminal_role(terminal: str) -> None:
    creative = InstagramCarouselCreative.model_validate(_with_roles(["hook", "step", terminal]))
    assert creative.slides[-1].role == terminal


@pytest.mark.parametrize("terminal", ["caption", "step", "context", "story", "evidence", "hook"])
def test_a_non_conclusion_terminal_role_is_rejected(terminal: str) -> None:
    roles = ["hook", "step", terminal] if terminal != "hook" else ["hook", "context", "hook"]
    with pytest.raises(ValidationError, match="conclusion role"):
        InstagramCarouselCreative.model_validate(_with_roles(roles))


def test_schema_and_art_validator_share_one_terminal_role_contract() -> None:
    from services import instagram_art_validator

    source = Path(instagram_art_validator.__file__).read_text(encoding="utf-8")
    assert "TERMINAL_ROLES" in source and '{"takeaway", "cta"}' not in source


@pytest.mark.asyncio
async def test_a_contract_failure_is_a_typed_error_not_an_anonymous_unexpected_error() -> None:
    bad = _with_roles(["hook", "step", "caption"])
    with pytest.raises(CreativeContractError, match="conclusion role"):
        await generate_carousel_creative(_Gateway(bad), FilePromptRepository(_PROMPTS), director_input=_input())  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------ meta-language guard


def test_the_exact_b5_leak_is_rejected_and_ordinary_ai_vocabulary_is_not() -> None:
    hits = find_meta_language({"slide_3": f"Берём только приём — {_LEAK}."})
    assert {h.pattern for h in hits} >= {"design_reference", "negated_caption_or_frames"}
    with pytest.raises(MetaLanguageLeakError):
        assert_no_meta_language({"final_caption": _LEAK})
    for legit in ("Промпт для разбора длинного текста", "Раскладка клавиатуры изменилась", "Шаг 1. Вставьте текст и получите чек-лист",
                  "Модель выбирает по стоимости выполненной задачи"):
        assert find_meta_language({"slide": legit}) == [], legit
    for leaked in ("This slide role is a hook", "Не копируй референс", "quiet zone under the headline", "визуальная ДНК бренда", "архетип поста"):
        assert find_meta_language({"slide": leaked}), leaked


def test_a_term_the_story_itself_uses_is_not_a_leak() -> None:
    assert find_meta_language({"slide": "Референс-дизайн нового чипа"}, allowed_context=["Компания показала референс-дизайн нового чипа."]) == []
    assert find_meta_language({"slide": "Референс-дизайн нового чипа"})


@pytest.mark.asyncio
async def test_generate_carousel_creative_rejects_a_leaking_draft() -> None:
    out = _output()
    out["slides"][2]["slide_copy"] = f"Смотри в профиле — {_LEAK}"
    with pytest.raises(MetaLanguageLeakError):
        await generate_carousel_creative(_Gateway(out), FilePromptRepository(_PROMPTS), director_input=_input())  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------ archetype consistency is exposed


DECISION = json.dumps({
    "source_summary": "s", "why_now": "w", "audience_value": "a", "recommended_format": "carousel", "format_reason": "f", "creative_direction": "c",
    "opportunity_type": "NEWS", "angle_intent": "EXPLAINER", "origin": "NEWS", "purpose": "ENGAGEMENT", "topic": "t", "angle": "a",
    "evidence_used": [], "trend_rationale": None, "trend_signal_type": None, "trend_signal_provenance": None, "product_connection": None,
    "supplementary_story_idea": None,
})


@pytest.mark.asyncio
async def test_archetype_mismatch_is_reported_not_silently_corrected() -> None:
    wrong = _output(content_archetype="trend_generative")
    outcome = await generate_carousel_creative(_Gateway(wrong), FilePromptRepository(_PROMPTS), director_input=_input(editorial_decision=DECISION))  # type: ignore[arg-type]
    assert outcome.archetype_correction_required is True and outcome.model_emitted_archetype == "trend_generative"
    assert outcome.carousel.content_archetype == "news_insight"  # the derived value still wins (existing compatibility behaviour), and it is exposed
    right = await generate_carousel_creative(_Gateway(_output(content_archetype="news_insight")), FilePromptRepository(_PROMPTS),  # type: ignore[arg-type]
                                             director_input=_input(editorial_decision=DECISION))
    assert right.archetype_correction_required is False


# ------------------------------------------------------------------------------------------ family persisted / observed / fatigue unit


def _creative_with_families() -> InstagramCarouselCreative:
    out = _with_roles(["hook", "step", "takeaway"])
    for slide, family in zip(out["slides"], ("immersive_image_field", "interface_cards", "dark_type_number_statement")):
        slide["visual_family"], slide["visual_family_reason"] = family, "content fit"
    return InstagramCarouselCreative.model_validate(out)


def test_chosen_family_is_persisted_in_the_package_plan_and_the_draft_payload() -> None:
    creative = _creative_with_families()
    _caption, _cta, _x, plan = _carousel_media_plan(creative)
    assert [s["visual_family"] for s in plan["slides"]] == ["immersive_image_field", "interface_cards", "dark_type_number_statement"]
    payload = json.loads(creative.model_dump_json())
    assert [s["visual_family"] for s in payload["slides"]] == ["immersive_image_field", "interface_cards", "dark_type_number_statement"]


def test_fatigue_history_unit_is_the_post_and_family_is_one_more_trait() -> None:
    payload = json.loads(_creative_with_families().model_dump_json())
    draft = SimpleNamespace(id="d1", generated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc), payload=payload)
    fp = _fingerprint_from_draft(draft)  # type: ignore[arg-type]
    assert fp is not None
    assert {t for t in fp.layout_traits if t.startswith("visual_family:")} == {
        "visual_family:immersive_image_field", "visual_family:interface_cards", "visual_family:dark_type_number_statement"}
    # ten posts that each use a family on THREE slides count as ten hits, not thirty (post-level unit)
    many = [fp] * 10
    note = build_carousel_fatigue_note(many)  # type: ignore[arg-type]
    assert "appeared in 10 of the last 14d posts" in note and "appeared in 30" not in note


def test_executed_family_is_inferred_from_the_declared_layout_and_reported() -> None:
    assert all(infer_family(p["layout"]) == "hero_object_stage" for p in fam3.hero_plans() if p["label"] in "ACDEF")
    assert all(infer_family(p["layout"]) == "internet_culture_collage" for p in fam3.collage_plans() if p["label"] in "ABD")
    poll = next(p for p in fam3.collage_plans() if p["label"] == "C")
    assert infer_family(poll["layout"]) in ("internet_culture_collage", "interface_cards")
    typographic = {"background": "ink", "regions": [{"kind": "text", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.4, "on_media": None, "content_ref": "number"}]}
    assert infer_family(typographic) == "dark_type_number_statement"
    assert infer_family({**typographic, "background": "paper"}) == "light_utility_editorial"


def test_observability_reports_chosen_and_executed_family_and_archetype_correction() -> None:
    creative = _creative_with_families()
    renders = [SimpleNamespace(evidence=SimpleNamespace(notes={"layout_plan_applied": True, "overlay_operations_executed": 0})) for _ in creative.slides]
    art = SimpleNamespace(passed=True, blocking_issues=[])
    obs = build_b4_observability(carousel=creative, prompt_version="9", renders=renders, art=art, slide_identities={},
                                 model_emitted_archetype="trend_generative", archetype_correction_required=True)
    assert obs["archetype_correction_required"] is True and obs["model_emitted_archetype"] == "trend_generative"
    assert [s["visual_family_chosen"] for s in obs["slides"]] == ["immersive_image_field", "interface_cards", "dark_type_number_statement"]
    assert all("visual_family_executed" in s and "visual_family_matches" in s for s in obs["slides"])


# ------------------------------------------------------------------------------------------ asset <-> family compatibility


def test_asset_profile_only_offers_families_the_pixels_support() -> None:
    kiosk = Image.open("assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case3_bright_promotional_scene.jpg")
    profile = profile_asset(kiosk, subject_key="source")
    lines = render_profile_lines(profile, pool_size=1, allowed_functions="hero, detail, evidence_photo")
    assert not profile.immersive_ready and "immersive_image_field: NOT available" in lines  # busy bright image: no calm text zone, never forced
    assert "internet_culture_collage" in lines
    logo = Image.open("assets/brand/nnj_logo.png")  # a real RGBA object: stageable
    assert profile_asset(logo, subject_key="logo").hero_ready
    calm_dark = Image.new("RGB", (1200, 900), (14, 14, 18))
    dark = profile_asset(calm_dark, subject_key="source")
    assert dark.immersive_ready and dark.tone == "dark" and "calm text zone" in render_profile_lines(dark, pool_size=1, allowed_functions="hero")


def test_media_note_lists_no_image_families_for_a_post_without_media_and_per_story_profiles_for_a_recap() -> None:
    import io

    import services.instagram_automatic_trigger as trigger

    none_note = trigger._carousel_media_note(source_image=None, recap_bundle=None)
    assert "no real image" in none_note and "dark_type_number_statement" in none_note
    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), (14, 14, 18)).save(buf, format="PNG")
    bundle = SimpleNamespace(stories=[SimpleNamespace(key="story_1", image_bytes=buf.getvalue()), SimpleNamespace(key="story_2", image_bytes=None)])
    note = trigger._carousel_media_note(source_image=None, recap_bundle=bundle)  # type: ignore[arg-type]
    assert "story_1" in note and "calm text zone" in note and "story_2: NO image" in note


# ------------------------------------------------------------------------------------------ acceptance runner integrity


def test_the_acceptance_runner_cannot_substitute_a_fixture_for_a_real_output() -> None:
    assert_no_fixture_substitution("real", Path("artifacts/instagram_phase_b51"))
    assert_no_fixture_substitution("fixture", Path("artifacts/instagram_phase_b51_FIXTURE_NOT_MODEL"))
    with pytest.raises(FixtureSubstitutionError):
        assert_no_fixture_substitution("fixture", Path("artifacts/instagram_phase_b51"))
    with pytest.raises(FixtureSubstitutionError):
        assert_no_fixture_substitution("real", Path("artifacts/instagram_phase_b51_FIXTURE_NOT_MODEL"))
    with pytest.raises(FixtureSubstitutionError):
        assert_no_fixture_substitution("simulate", Path("x"))


def test_budget_worst_case_uses_only_models_the_router_can_actually_pick() -> None:
    worst = routed_worst_case_call_cost()
    assert 0 < worst < copy.copy(__import__("decimal").Decimal("0.30"))  # luna/terra ceiling, not the excluded most expensive model


# ------------------------------------------------------------------------------------------ B.5.1.1: bounded Creative Director output


async def _capture_cd_request():
    gateway = _Gateway(_output())
    repo = FilePromptRepository(_PROMPTS)
    director_input = _input()
    await cd._call_creative_director(gateway, repo, prompt_name=cd.CAROUSEL_PROMPT_NAME, director_input=director_input, prompt_version=cd._CAROUSEL_PROMPT_VERSION)
    return gateway.requests[0], repo, director_input


@pytest.mark.asyncio
async def test_creative_director_request_is_bounded_and_otherwise_unchanged() -> None:
    request, repo, director_input = await _capture_cd_request()
    assert cd._CREATIVE_DIRECTOR_MAX_TOKENS == 16_000
    assert request.max_tokens == 16_000
    prompt = repo.resolve(cd.CAROUSEL_PROMPT_NAME, "10.6")
    assert cd._CAROUSEL_PROMPT_VERSION == "10.6"
    assert request.response_mode == "json_schema" and request.response_schema == prompt.output_schema
    assert request.messages[0].content[0].text == prompt.system + "\n\nRULES:\n" + "\n".join(f"- {r}" for r in prompt.rules)
    assert request.messages[1].content[0].text == cd._build_user_text(director_input, evidence_handles=True)
    # nothing else that steers routing/decoding was introduced
    assert request.temperature is None and request.preferred_model is None
    assert [m.role for m in request.messages] == ["system", "user"]


@pytest.mark.asyncio
async def test_bounded_request_leaves_visual_contract_untouched() -> None:
    request, repo, _ = await _capture_cd_request()
    schema = json.dumps(request.response_schema)
    assert '"visual_family"' in schema and "overlay" not in schema.lower() and "scrim" not in schema.lower()
    import services.instagram_automatic_trigger as trigger

    assert trigger._visual_dna_version() == "2"


def test_gateway_worst_case_with_bound_fits_the_diagnostic_cap_for_the_routed_candidate() -> None:
    from decimal import Decimal

    from scripts._instagram_phase_b51_acceptance import DIAG_HARD_CAP_USD, gateway_worst_case_by_model

    by_model = gateway_worst_case_by_model()
    cheapest = min(by_model.values())
    assert cheapest * 4 <= DIAG_HARD_CAP_USD
    assert all(v <= DIAG_HARD_CAP_USD for v in by_model.values())  # no single eligible candidate is denied outright
    assert all(v < Decimal("1") for v in by_model.values())


def test_the_editorial_decision_request_is_not_on_the_acceptance_path() -> None:
    from pathlib import Path as _P

    source = (_P(__file__).resolve().parent.parent / "scripts" / "_instagram_phase_b51_acceptance.py").read_text(encoding="utf-8")
    assert "trigger.generate_editorial_decision = fixed_decision" in source
