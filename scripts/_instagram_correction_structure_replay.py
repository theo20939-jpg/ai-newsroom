"""Zero-model OFFLINE REPLAY of the ninth paid viral canary's Director correction (founder task 2026-09-28: structural non-regression of the
ONE correction). No provider / LLM / image call, no database write. Judge v5 is NOT called: the replay uses the two SAVED judge verdicts
of canary 9 (initial and correction round) as historical evidence, through the real role guard.

  1. the FIRST output through the real path (services.instagram_creative_director._validate_viral_carousel) with the saved initial verdict:
     the EditorialCorrectionRequired it raises now carries the rejected version, and its correction note (the text the one correction
     receives) contains the complete previous output plus the structural-preservation contract;
  2. the saved CORRECTED output through the real path in correction mode with the saved final (clean) verdict: reproduces the canary's
     terminal media-first finding (the 2nd slide: generated, story_anchor null);
  3. a LOCAL structurally valid correction fixture (replay-only wording, never production copy): the same semantic repair with the 2nd
     slide's story_anchor restored from its own evidence line (E7) - through the same real path and every deterministic validator.
Usage: python scripts/_instagram_correction_structure_replay.py <out dir>
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
CANARY = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary9_20260928/post"
FIXTURE_ANCHOR = ("The Senate inquiry chair wrote to OpenAI and Anthropic asking for their US-based chief executives to appear on Thursday.")


def load(name: str) -> dict:
    return json.loads((CANARY / name).read_text(encoding="utf-8"))


def evidence_lines() -> list[str]:
    call = load("calls/03_director.json")
    text = "\n".join(t for message in call["request"] for t in message["text"])
    return [line for _n, line in re.findall(r"^E(\d+): (.*)$", text, re.M)]


def director_input(evidence: list[str], *, note: str = "", invariants: dict | None = None):
    from services.instagram_creative_director import CreativeDirectorInput
    from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE

    return CreativeDirectorInput(
        objective="shares", format="carousel", opportunity_summary="Anthropic / Australian Senate AI inquiry", allowed_evidence=evidence,
        locale="ru", external_news_entities_allowed=True, media_first=True, generated_media_available=True, planned_format="TREND",
        planned_archetype="trend_generative", available_media_subjects=("source",), unsuitable_media_subjects=(),
        viral_carousel_note=VIRAL_CAROUSEL_NOTE, contract_retry_note=note, factual_invariants=dict(invariants or {}))


async def real_path(raw: dict, di, saved_verdict: dict) -> dict:
    import services.instagram_creative_director as cd
    import services.instagram_viral_editorial_judge as judge_mod

    calls: list[int] = []

    async def saved(_gateway, _repo, *, slides, caption, allowed_evidence):  # the SAVED verdict of this round - no provider call
        calls.append(len(slides))
        return judge_mod.apply_role_guard(judge_mod.parse_verdict(saved_verdict, len(slides)), slides)

    real = judge_mod.judge_viral_copy
    judge_mod.judge_viral_copy = saved
    cd.set_raw_output_sink(lambda *_a: None)
    try:
        await cd._validate_viral_carousel(None, None, copy.deepcopy(raw), None, director_input=di, archetype="trend_generative")
        return {"result": "PASS", "judge_replayed_from_saved_verdict": bool(calls)}
    except Exception as exc:  # noqa: BLE001 - the replay reports whatever the validation raises
        return {"result": type(exc).__name__, "hard": isinstance(exc, cd.CreativeFactSafetyError), "detail": str(exc)[:2000],
                "findings": list(getattr(exc, "findings", []) or []), "judge_replayed_from_saved_verdict": bool(calls),
                "carries_previous_output": getattr(exc, "previous_output", None) is not None,
                "correction_note": getattr(exc, "correction_note", None)}
    finally:
        judge_mod.judge_viral_copy = real  # never leak the stub
        cd.set_raw_output_sink(None)


def deterministic(raw: dict, evidence: list[str]) -> dict:
    from services.instagram_factual_status import build_status_ledger, status_violations, unsupported_target_violations
    from services.instagram_media_first import MediaFirstContractError, assert_media_first
    from services.instagram_viral_format import classify_quote_use, generated_person_risks, viral_copy_findings

    slides, caption = raw["slides"], raw.get("final_caption") or ""
    try:
        assert_media_first(slides, available_subjects={"source"}, unsuitable_subjects=set(), generated_media_available=True)
        media_first = "PASS"
    except MediaFirstContractError as exc:
        media_first = f"FAIL: {exc}"
    quotes = classify_quote_use([*((f"slide {i} hook", s.get("slide_copy") or "") for i, s in enumerate(slides, 1)),
                                 *((f"slide {i} body", s.get("slide_body") or "") for i, s in enumerate(slides, 1)), ("caption", caption)], evidence)
    ledger = build_status_ledger(evidence)
    required = ("generation_brief", "story_anchor", "visual_direction", "source_evidence", "layout")
    return {
        "media_first_contract": media_first,
        "generated_slide_fields": [{"slide": i, **{k: bool(s.get(k)) for k in required}} for i, s in enumerate(slides, 1)
                                   if s.get("media_source") == "generated"],
        "quote_use": {"terminal": quotes.terminal, "repairable": quotes.repairable},
        "named_person_risks": generated_person_risks(slides, evidence),
        "status_violations": [v.render() for v in status_violations(slides, caption, ledger, evidence)],
        "unsupported_targets": [v.render() for v in unsupported_target_violations(slides, caption, evidence)],
        "hook_lengths": [len(s.get("slide_copy") or "") for s in slides],
        "copy_thesis_findings": viral_copy_findings(slides, evidence, caption=caption, include_quotes=False),
    }


def main() -> None:
    from services.instagram_factual_status import build_status_ledger, factual_invariants

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    evidence = evidence_lines()
    first = load("director_raw_output_initial.json")["structured_output"]
    corrected = load("director_raw_output.json")["structured_output"]
    judge_initial, judge_final = load("director_semantic_judge_initial.json")["verdict"], load("director_semantic_judge_correction.json")["verdict"]
    ledger = build_status_ledger(evidence)
    invariants = factual_invariants(first["slides"], first.get("final_caption") or "", ledger, evidence)

    first_path = asyncio.run(real_path(first, director_input(evidence), judge_initial))
    note = first_path.get("correction_note") or ""
    fixture = copy.deepcopy(corrected)
    assert fixture["slides"][1].get("story_anchor") in (None, ""), "the saved corrected output changed"
    fixture["slides"][1]["story_anchor"] = FIXTURE_ANCHOR
    report = {
        "provider_calls": 0, "image_calls": 0, "judge": "saved canary-9 verdicts only (no new judge call)",
        "first_output": {"real_path": {k: v for k, v in first_path.items() if k != "correction_note"},
                         "correction_note_chars": len(note),
                         "note_has_previous_output": "PREVIOUS VERSION (JSON):" in note and first["slides"][1]["story_anchor"] in note,
                         "note_has_structural_contract": "STRUCTURAL PRESERVATION" in note,
                         "note_carries_every_first_story_anchor": all(s["story_anchor"] in note for s in first["slides"])},
        "old_corrected_output": {"deterministic": deterministic(corrected, evidence),
                                 "real_path_correction_mode": asyncio.run(real_path(corrected, director_input(evidence, note=note, invariants=invariants),
                                                                                    judge_final))},
        "structural_fixture": {"change": {"slide": 2, "story_anchor": FIXTURE_ANCHOR}, "deterministic": deterministic(fixture, evidence),
                               "real_path_correction_mode": asyncio.run(real_path(fixture, director_input(evidence, note=note, invariants=invariants),
                                                                                  judge_final))},
    }
    (out / "correction_structure_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "correction_note_first_output.txt").write_text(note, encoding="utf-8")
    brief = {"first_output": report["first_output"],
             "old_corrected": {"media_first": report["old_corrected_output"]["deterministic"]["media_first_contract"],
                               "result": report["old_corrected_output"]["real_path_correction_mode"]["result"],
                               "findings": report["old_corrected_output"]["real_path_correction_mode"].get("findings")},
             "fixture": {k: v for k, v in report["structural_fixture"]["deterministic"].items() if k != "generated_slide_fields"}
             | {"real_path": report["structural_fixture"]["real_path_correction_mode"]}}
    print(json.dumps(brief, ensure_ascii=False, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
