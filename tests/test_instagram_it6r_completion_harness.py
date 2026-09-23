"""Iteration-6r completion harness: a pinned recap source binary that disappeared from storage may be absent ONLY when no slide consumes it,
the preserved note had it available-but-unsuitable and the image prompt cannot read it. Everything else stays exact; zero provider calls."""
import json
from pathlib import Path

import pytest
from PIL import Image

import scripts._instagram_quality_loop_it6r_complete as harness

_UNSUITABLE = "SOURCE_AVAILABLE: yes. SOURCE_SUITABLE_FOR_FINAL_VISUAL: NO - a flat article / text / social card whose content is baked-in text."
_SUITABLE = "SOURCE_AVAILABLE: yes. SOURCE_SUITABLE_FOR_FINAL_VISUAL: yes. REAL image 640x480, tone=mid."
_KEYS = ("story_1", "story_2", "story_3", "story_4", "story_5")


def _note(suitable_5: bool = False) -> str:
    lines = []
    for key in _KEYS:
        body = _SUITABLE if (key == "story_1" or (key == "story_5" and suitable_5)) else _UNSUITABLE
        lines.append(f"subject key '{key}': {body}")
        if body is _SUITABLE:
            lines.append("  immersive_image_field: calm zone top-left")
    return "\n".join(lines + ["GENERATED media is a first-class option for ANY slide."])


def _slide(subject: str, source: str, ref: str | None) -> dict:
    regions = [{"kind": "surface", "content_ref": None}] + ([{"kind": "media", "content_ref": ref}] if ref else [])
    return {"media_subject": subject, "media_source": source, "layout": {"regions": regions}}


def _plan(**override) -> list[dict]:
    slides = {k: _slide(k, "generated", "generated") for k in _KEYS}
    slides["story_1"] = _slide("story_1", "source", "story_1")
    slides.update(override)
    return list(slides.values())


def _fixture(tmp_path: Path, monkeypatch, *, plan: list[dict], note: str, missing: tuple[str, ...] = ("story_5",)) -> Path:
    src = tmp_path / "src"
    store = tmp_path / "store"
    handles, pinned = {}, {}
    for n, key in enumerate(_KEYS, start=1):
        handles[f"E{2 * n - 1}"] = f"[{key}] Title {n}"
        handles[f"E{2 * n}"] = f"[{key}] Fact {n}"
        rel = f"images/{n:02d}/{key}.png"
        pinned[key] = (f"event-{n}", f"cand-{n}", rel)
        if key not in missing:
            (store / rel).parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (640, 480), (40 * n, 90, 120)).save(store / rel)
    for name, payload in {
        "news_recap/raw_creative_director_output.json": {"evidence_handles": handles},
        "news_recap/creative_director_output.json": {"slides": plan},
        "news_recap/render_manifest.json": {"media_note_passed_to_model": note},
        "trend_generative/raw_creative_director_output.json": {"evidence_handles": {"E1": handles["E7"], "E2": handles["E8"]}},
    }.items():
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(harness, "PINNED", pinned)
    monkeypatch.setattr(harness, "STORE_ROOT", store)
    return src


def test_first_launch_behaviour_stops_on_the_missing_binary(tmp_path, monkeypatch):
    src = _fixture(tmp_path, monkeypatch, plan=_plan(), note=_note())
    with pytest.raises(harness.SafeStop, match="story_5: pinned source file .* is missing"):
        harness._pinned_inputs(src, allow_unused_missing=False)


def test_unused_previously_unsuitable_binary_may_be_absent_and_is_never_substituted(tmp_path, monkeypatch):
    src = _fixture(tmp_path, monkeypatch, plan=_plan(), note=_note())
    bundle, trend, missing = harness._pinned_inputs(src)
    assert list(missing) == ["story_5"]
    assert missing["story_5"]["substituted_image"] is None and missing["story_5"]["slides_consuming_image"] == []
    by_key = {s.key: s for s in bundle.stories}
    assert by_key["story_5"].image_bytes is None
    assert all(by_key[k].image_bytes for k in _KEYS if k != "story_5")
    assert by_key["story_5"].evidence == ["[story_5] Title 5", "[story_5] Fact 5"]
    assert trend.key == "story_4" and trend.image_bytes


@pytest.mark.parametrize("override, reason", [
    ({"story_5": _slide("story_5", "generated", "story_5")}, "media region consuming story_5"),
    ({"story_5": _slide("story_5", "source", None)}, "plans story_5's own source media"),
    ({"story_5": {"media_subject": "story_5", "media_source": "generated", "layout": None}}, "no declarative layout"),
    ({"story_2": _slide("story_2", "generated", "story_5")}, "slide 1 has a media region consuming story_5"),
])
def test_a_missing_binary_that_a_slide_consumes_stops(tmp_path, monkeypatch, override, reason):
    src = _fixture(tmp_path, monkeypatch, plan=_plan(**override), note=_note())
    with pytest.raises(harness.SafeStop, match=reason):
        harness._pinned_inputs(src)


def test_a_missing_binary_the_real_run_treated_as_suitable_stops(tmp_path, monkeypatch):
    src = _fixture(tmp_path, monkeypatch, plan=_plan(), note=_note(suitable_5=True))
    with pytest.raises(harness.SafeStop, match="not preserved as available-but-unsuitable"):
        harness._pinned_inputs(src)


def test_a_missing_binary_absent_from_the_preserved_note_stops(tmp_path, monkeypatch):
    note = "\n".join(line for line in _note().split("\n") if "story_5" not in line)
    src = _fixture(tmp_path, monkeypatch, plan=_plan(), note=note)
    with pytest.raises(harness.SafeStop, match="absent from the preserved media note"):
        harness._pinned_inputs(src)


def test_the_trend_story_binary_is_never_excused(tmp_path, monkeypatch):
    src = _fixture(tmp_path, monkeypatch, plan=_plan(), note=_note(), missing=("story_4",))
    with pytest.raises(harness.SafeStop, match="trend story's own source image is missing"):
        harness._pinned_inputs(src)


def test_image_prompt_builder_reads_text_only():
    assert harness.missing_source_block_reason("story_5", _plan(), _note()) is None
    import inspect

    import services.instagram_creative_media as media

    assert set(inspect.signature(media.compile_instagram_generation_prompt).parameters) == harness.PROMPT_INPUTS


def test_restored_note_equals_the_preserved_note_and_only_that_line_changes():
    import services.instagram_automatic_trigger as trigger

    saved = _note()
    rebuilt = saved.replace(f"subject key 'story_5': {_UNSUITABLE}",
                            "story_5: SOURCE_AVAILABLE: no. Plan a GENERATED contextual visual for this story (media_subject 'story_5', media_source 'generated').")
    assert rebuilt != saved
    assert harness.restore_preserved_note_lines(rebuilt, saved, ["story_5"]) == saved
    with pytest.raises(harness.SafeStop, match="exactly one"):
        harness.restore_preserved_note_lines(saved, saved, ["story_5"])
    assert hasattr(trigger, "_carousel_media_note") and hasattr(trigger, "_carousel_media_subjects")


def test_real_note_builder_writes_the_line_the_harness_restores():
    """Pins the coupling: the product note builder's own 'no image' line for a story without bytes starts with '<key>: SOURCE_AVAILABLE: no.'."""
    import services.instagram_automatic_trigger as trigger
    from services.instagram_recap_bundle import InstagramRecapBundle, RecapStory

    stories = tuple(RecapStory(key=f"story_{i}", story_id=str(i), event_id=str(i), title=f"T{i}", evidence=[f"[story_{i}] T{i}"], image_bytes=None,
                               source_ref=None) for i in (1, 2, 3))
    note = trigger._carousel_media_note(source_image=None, recap_bundle=InstagramRecapBundle(stories=stories), media_first=True)
    assert sum(1 for line in note.split("\n") if line.startswith("story_2: SOURCE_AVAILABLE: no.")) == 1


_PRESERVED = Path(__file__).resolve().parent.parent / "artifacts" / "instagram_quality_loop_it6r" / "instagram_quality_loop_it6r" / "news_recap"


@pytest.mark.skipif(not _PRESERVED.exists(), reason="preserved iteration-6r artifacts are local-only (untracked)")
def test_real_preserved_recap_plan_does_not_consume_story_5():
    plan = json.loads((_PRESERVED / "creative_director_output.json").read_text(encoding="utf-8"))["slides"]
    note = json.loads((_PRESERVED / "render_manifest.json").read_text(encoding="utf-8"))["media_note_passed_to_model"]
    assert harness.missing_source_block_reason("story_5", plan, note) is None
    assert harness.missing_source_block_reason("story_3", plan, note) is not None  # story_3's real image IS on a slide
