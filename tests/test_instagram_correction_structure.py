"""DIRECTOR CORRECTION STRUCTURAL NON-REGRESSION (founder task 2026-09-28, after the ninth paid viral canary).

Canary 9: judge v5 found a real duplicate, the ONE correction fixed it and the final judge was clean - but the correction was a fresh
regeneration from the note alone (the model never saw the version it corrected) and the 2nd slide came back generated with story_anchor
null; the media-first contract stopped the post. The correction now receives the rejected version as the object to edit plus a binding
structural-preservation contract; the corrected version is still fully re-validated and any violation stays terminal (no 2nd correction)."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

import scripts._instagram_correction_structure_replay as replay
import services.instagram_creative_director as cd
from services.instagram_media_first import MediaFirstContractError, assert_media_first
from services.instagram_viral_format import EditorialCorrectionRequired

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = replay.evidence_lines()
FIRST = replay.load("director_raw_output_initial.json")["structured_output"]
CORRECTED = replay.load("director_raw_output.json")["structured_output"]
JUDGE_INITIAL = replay.load("director_semantic_judge_initial.json")["verdict"]
JUDGE_FINAL = replay.load("director_semantic_judge_correction.json")["verdict"]
def _first_invariants() -> dict:
    from services.instagram_factual_status import build_status_ledger, factual_invariants

    return factual_invariants(FIRST["slides"], FIRST.get("final_caption") or "", build_status_ledger(EVIDENCE), EVIDENCE)


STRUCTURAL = ("media_source", "story_anchor", "visual_direction", "generation_brief", "source_evidence", "layout", "role", "visual_family")


def _note_for(output: dict, findings: list[str]) -> str:
    return EditorialCorrectionRequired(findings, previous_output=output).correction_note


def _previous_in_note(note: str) -> dict:
    return json.loads(note.split("PREVIOUS VERSION (JSON):\n", 1)[1])


def _media_first(slides: list[dict]) -> None:
    assert_media_first(slides, available_subjects={"source"}, unsuitable_subjects=set(), generated_media_available=True)


@pytest.mark.parametrize("finding", ["slide 3 body is a list of product names",  # 1. a text-only correction
                                     "slide 1 hook is a clipped telegraphic fragment",  # 2. a hook correction
                                     "caption sentence repeats the slides"])  # 3. a caption correction
def test_1_2_3_every_correction_receives_the_complete_previous_version_with_all_structural_fields(finding):
    note = _note_for(FIRST, [finding])
    previous = _previous_in_note(note)
    assert previous == json.loads(json.dumps(FIRST, default=str))  # the whole object, nothing dropped
    for original, sent in zip(FIRST["slides"], previous["slides"]):
        assert all(sent.get(k) == original.get(k) for k in STRUCTURAL)
    assert "STRUCTURAL PRESERVATION" in note and "Never emit null or an empty value for a field the previous version had filled" in note
    assert "never strengthen a claim" in note and "edit it, do not write a new carousel" in note


def test_the_real_viral_path_attaches_the_rejected_version_to_its_correction():
    result = asyncio.run(replay.real_path(FIRST, replay.director_input(EVIDENCE), JUDGE_INITIAL))
    assert result["result"] == "EditorialCorrectionRequired" and result["carries_previous_output"]
    assert all(s["story_anchor"] in result["correction_note"] for s in FIRST["slides"])


def test_4_the_canary9_duplicate_correction_with_a_null_story_anchor_is_rejected_by_the_contract():
    with pytest.raises(MediaFirstContractError, match="slide 2: a generated slide needs a story_anchor"):  # 1-based now
        _media_first(CORRECTED["slides"])


def test_5_a_merge_that_removes_a_slide_is_valid_when_every_remaining_slide_keeps_its_contract():
    fixed = copy.deepcopy(CORRECTED)
    fixed["slides"][1]["story_anchor"] = replay.FIXTURE_ANCHOR
    assert len(fixed["slides"]) == len(FIRST["slides"]) - 1  # the duplicate was merged away - a legitimate count change
    _media_first(fixed["slides"])


@pytest.mark.parametrize("field,message", [("visual_direction", "visual_direction"), ("generation_brief", "generation_brief"),
                                           ("source_evidence", "source_evidence")])
def test_6_7_a_generated_slide_cannot_lose_its_visual_direction_brief_or_evidence(field, message):
    broken = copy.deepcopy(FIRST)
    broken["slides"][2][field] = None
    with pytest.raises(MediaFirstContractError, match=f"slide 3: .*{message}"):
        _media_first(broken["slides"])


def test_8_a_source_photo_slide_keeps_its_source_metadata_in_the_previous_version_and_cannot_drop_its_subject():
    with_source = copy.deepcopy(FIRST)
    slide = with_source["slides"][2]
    slide["media_source"] = "source"
    for region in slide["layout"]["regions"]:
        if region.get("kind") == "media":
            region["content_ref"] = "source"
    _media_first(with_source["slides"])
    sent = _previous_in_note(_note_for(with_source, ["x"]))["slides"][2]
    assert sent["media_source"] == "source" and any(r.get("content_ref") == "source" for r in sent["layout"]["regions"])
    for region in slide["layout"]["regions"]:
        if region.get("kind") == "media":
            region["content_ref"] = "nonexistent"
    with pytest.raises(MediaFirstContractError, match="slide 3: .*(listed real subject|unlisted subject)"):
        _media_first(with_source["slides"])


def test_9_slides_the_findings_do_not_name_are_sent_verbatim():
    note = _note_for(FIRST, ["semantic review: slides 1 and 2 make the same point in different words (x)"])
    previous = _previous_in_note(note)
    for i in (2, 3, 4):  # slides 3-5 are untouched by the finding - they travel verbatim as the object to keep
        assert previous["slides"][i] == json.loads(json.dumps(FIRST["slides"][i], default=str))


def test_10_12_the_trigger_still_allows_exactly_one_correction_and_no_hidden_second_one():
    source = (ROOT / "services/instagram_automatic_trigger.py").read_text(encoding="utf-8")
    block = source[source.index("except _EditorialRetry as retry:"):source.index("single, carousel, reel = creative_outcome")]
    assert block.count("await regenerator(") == 1
    assert "correction_note" in block  # the note (now carrying the previous version) is what the one correction receives


def test_11_an_invalid_corrected_structure_is_terminal_in_correction_mode():
    note = _note_for(FIRST, ["x"])
    result = asyncio.run(replay.real_path(CORRECTED, replay.director_input(EVIDENCE, note=note, invariants=_first_invariants()), JUDGE_FINAL))
    # in correction mode any remaining finding raises out of the one retry - the trigger's except clause makes it terminal
    assert result["result"] == "EditorialCorrectionRequired"
    assert any("slide 2: a generated slide needs a story_anchor" in f for f in result["findings"])


def test_the_structurally_valid_fixture_passes_the_real_correction_mode_path_with_the_saved_clean_verdict():
    fixed = copy.deepcopy(CORRECTED)
    fixed["slides"][1]["story_anchor"] = replay.FIXTURE_ANCHOR
    note = _note_for(FIRST, ["x"])
    result = asyncio.run(replay.real_path(fixed, replay.director_input(EVIDENCE, note=note, invariants=_first_invariants()), JUDGE_FINAL))
    assert result == {"result": "PASS", "judge_replayed_from_saved_verdict": True}


def test_no_previous_version_keeps_the_note_exactly_as_before():
    note = EditorialCorrectionRequired(["slide 2: x"]).correction_note
    assert "STRUCTURAL PRESERVATION" not in note and "PREVIOUS VERSION" not in note and note.endswith("1. slide 2: x")


def test_the_correction_note_is_what_the_trigger_sends(monkeypatch):
    """The trigger's one correction receives exactly exc.correction_note - now including the previous version."""
    from tests.test_instagram_director_correction import _Recorder, _run

    first = EditorialCorrectionRequired(["slide 1 hook is a clipped fragment"], previous_output=FIRST)
    recorder = _Recorder(first, EditorialCorrectionRequired(["still clipped"], previous_output=FIRST))
    outcome = asyncio.run(_run(monkeypatch, recorder))
    assert len(recorder.inputs) == 2 and outcome.reason == "creative_director_failed:EditorialCorrectionRequired"
    assert recorder.inputs[1].contract_retry_note == first.correction_note and "PREVIOUS VERSION (JSON):" in first.correction_note
    assert cd  # the Director module the correction flows back through is unchanged apart from attaching previous_output
