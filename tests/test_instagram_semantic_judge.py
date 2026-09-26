"""The viral-carousel SEMANTIC EDITORIAL JUDGE (founder task 2026-09-26): one bounded classification call, fail closed, feeding the one
existing editorial correction. Zero provider calls: the judge's gateway is a stub."""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.instagram_creative_director as cd
from integrations.prompts.file_repository import FilePromptRepository
from services.instagram_viral_editorial_judge import (
    JUDGE_MAX_OUTPUT_TOKENS,
    JUDGE_PROMPT_NAME,
    JUDGE_PROMPT_VERSION,
    MAX_EVIDENCE_CHARS,
    SemanticJudgeUnavailableError,
    build_judge_input,
    parse_verdict,
    worst_case_cost_usd,
)

ROOT = Path(__file__).resolve().parent.parent
OFFLINE = ROOT / "artifacts/instagram_feed_product/semantic_judge_20260926/offline"


def _replay():
    spec = importlib.util.spec_from_file_location("semantic_judge_replay", ROOT / "scripts/_instagram_semantic_judge_replay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._patch_call_generate()
    return mod


def _run(coro):
    return asyncio.run(coro)


# --- the contract --------------------------------------------------------------------------------------------------------------------------

def test_a_well_formed_verdict_becomes_correctable_findings():
    verdict = parse_verdict({"same_thesis_pairs": [{"slides": [2, 1], "reason": "Both say a modder did it."}],
                             "caption_repeats_slides": {"present": False, "reason": ""},
                             "caption_aphorism": {"present": True, "sentence": "Иногда так бывает.", "reason": "A generic moral."},
                             "unsupported_interpretation": []}, 4)
    findings = verdict.findings()
    assert findings[0].startswith("semantic review: slides 1 and 2 make the same point in different words (Both say a modder did it)")
    assert "merge them into one slide" in findings[0]
    assert "generalised moral" in findings[1] and "Иногда так бывает." in findings[1]


def test_only_adjacent_pairs_are_findings():
    verdict = parse_verdict({"same_thesis_pairs": [{"slides": [1, 5], "reason": "hook echo"}],
                             "caption_repeats_slides": {"present": False, "reason": ""},
                             "caption_aphorism": {"present": False, "sentence": "", "reason": ""}, "unsupported_interpretation": []}, 5)
    assert verdict.findings() == [] and verdict.raw["same_thesis_pairs"]


@pytest.mark.parametrize("output", [None, {"same_thesis_pairs": []}, {"unexpected": True},
                                    {"same_thesis_pairs": [{"slides": [1, 9], "reason": "x"}], "caption_repeats_slides": {"present": False, "reason": ""},
                                     "caption_aphorism": {"present": False, "sentence": "", "reason": ""}, "unsupported_interpretation": []},
                                    {"same_thesis_pairs": [], "caption_repeats_slides": {"present": "yes", "reason": ""},
                                     "caption_aphorism": {"present": False, "sentence": "", "reason": ""}, "unsupported_interpretation": []}])
def test_a_malformed_verdict_fails_closed(output):
    with pytest.raises(SemanticJudgeUnavailableError):
        parse_verdict(output, 4)


def test_the_judge_input_is_bounded_and_windows_each_evidence_line_on_the_copy():
    long_line = "Обзор смартфона и другие заголовки страницы. " * 12 + "Моддер добавил в игру поддержку сглаживания и HDR."
    slides = [{"slide_copy": f"Заголовок {i}", "slide_body": "Моддер добавил сглаживание и HDR.", "source_evidence": "E1"} for i in range(9)]
    text = build_judge_input(slides, "Подпись.", [long_line, "SOURCE MEDIA: 800x450 source image available", *["факт"] * 20])
    assert text.count("headline:") == 7  # never more than the viral maximum
    evidence_lines = [line for line in text.splitlines() if line[:1] == "E" and line[1:2].isdigit()]
    assert "SOURCE MEDIA" not in text and len(evidence_lines) == 10  # at most 10 evidence lines, placeholders dropped
    e1 = next(line for line in text.splitlines() if line.startswith("E1: "))
    assert len(e1) <= len("E1: ") + MAX_EVIDENCE_CHARS and "поддержку сглаживания и HDR" in e1  # the supporting sentence, not the head


def test_the_worst_case_cost_is_explicit_and_small():
    bound = worst_case_cost_usd(FilePromptRepository(ROOT / "prompts"), input_per_million=1.0, output_per_million=6.0)
    assert bound["output_tokens_cap"] == JUDGE_MAX_OUTPUT_TOKENS == 1500
    assert bound["worst_case_usd"] < 0.016  # vs a Director call's worst case of ~$0.076 (10,737 output tokens + input)


def test_the_published_prompt_is_the_one_the_judge_uses_and_earlier_versions_stay_untouched():
    repo = FilePromptRepository(ROOT / "prompts")
    assert JUDGE_PROMPT_VERSION == "4"
    for version in ("1", "2", "3", "4"):
        assert repo.resolve(JUDGE_PROMPT_NAME, version).output_schema["required"] == [
            "same_thesis_pairs", "caption_repeats_slides", "caption_aphorism", "unsupported_interpretation"]
    rules = " ".join(repo.resolve(JUDGE_PROMPT_NAME, JUDGE_PROMPT_VERSION).rules).lower()
    for term in ("gta", "rockstar", "моддер", "modder", "dlss", "патч"):
        assert term not in rules


# --- the validation order ------------------------------------------------------------------------------------------------------------------

def test_semantic_findings_join_the_deterministic_ones_in_one_correction_with_one_judge_call():
    mod = _replay()
    raw, director_input = mod.gta_final()
    stub = mod.StubGateway(mod._verdict(pairs=[(1, 2)], aphorism="Иногда патч для старой игры приходит совсем не от тех, кто её выпустил."))
    result = _run(mod._validate(raw, director_input, stub))
    assert result["result"] == "EditorialCorrectionRequired" and stub.calls == 1
    assert any(f.startswith("semantic review: slides 1 and 2") for f in result["findings"])
    assert any("generalised moral" in f for f in result["findings"])


@pytest.mark.parametrize("name", ["deepseek", "hamster"])
def test_the_accepted_golden_carousels_pass_with_an_empty_verdict(name):
    mod = _replay()
    output, director_input = mod.goldens()[name]
    stub = mod.StubGateway(mod._verdict())
    assert _run(mod._validate(output, director_input, stub)) == {"result": "PASS"} and stub.calls == 1


@pytest.mark.parametrize("mode", ["raise", "length", "malformed"])
def test_a_technical_judge_failure_is_terminal_never_a_guessed_pass(mode):
    mod = _replay()
    raw, director_input = mod.gta_final()
    stub = mod.StubGateway(mod._verdict(), fail=mode)
    assert _run(mod._validate(raw, director_input, stub))["result"].startswith("SemanticJudgeUnavailableError") and stub.calls == 1
    assert issubclass(SemanticJudgeUnavailableError, cd.CreativeDirectorUnavailableError)  # the trigger's terminal path
    assert not issubclass(SemanticJudgeUnavailableError, cd.DirectorStructuredOutputError)  # never the technical-recovery path


def test_a_hard_failure_raises_before_the_judge_is_called():
    mod = _replay()
    raw, director_input = mod.gta_final()
    quoted = copy.deepcopy(raw)
    quoted["slides"][1]["slide_body"] = "Моддер сказал: «это было проще, чем казалось»."
    stub = mod.StubGateway(mod._verdict())
    assert _run(mod._validate(quoted, director_input, stub))["result"].startswith("CreativeFactSafetyError") and stub.calls == 0


def test_a_non_viral_carousel_never_calls_the_judge(monkeypatch):
    mod = _replay()
    output, director_input = mod.goldens()["deepseek"]
    calls = []

    async def director(*_a, **_kw):
        return copy.deepcopy(output), SimpleNamespace()

    async def judge(*_a, **_kw):
        calls.append(1)
        raise AssertionError("the judge must not run for a non-viral carousel")

    monkeypatch.setattr(cd, "_call_creative_director", director)
    monkeypatch.setattr("services.instagram_viral_editorial_judge.judge_viral_copy", judge)
    monkeypatch.setattr(cd, "_validate_carousel_output", lambda *_a, **_kw: "validated")
    from dataclasses import replace

    plain = replace(director_input, viral_carousel_note="")
    assert _run(cd.generate_carousel_creative(None, None, director_input=plain)) == "validated" and calls == []


# --- the recorded judge-only calibration (real model verdicts, prompt v4) ------------------------------------------------------------------

def test_the_recorded_calibration_meets_every_offline_acceptance_item():
    report = json.loads((OFFLINE / "live_judge_calibration.json").read_text(encoding="utf-8"))
    assert report["all_pass"] and all(report["checks"].values())
    assert report["results"]["golden_deepseek"]["findings"] == [] and report["results"]["golden_hamster"]["findings"] == []
