"""Zero-cost OFFLINE REPLAY of the first paid viral canary (artifacts/instagram_feed_product/viral_nominated_canary_20260926) through the
target-status safety + copy / judge calibration (founder task 2026-09-27). No provider call, no image, no publication.

Inputs are exactly the saved artifacts: the Director request (its E1..En evidence lines incl. the CHRONOLOGY line), the FIRST Director
output (call 03), the CORRECTED output (call 05), the correction note it was sent, and the two saved semantic-judge verdicts (v4).
  A. component view per version - the target-status ledger and gate, chronology markers, copied wording (the rule before vs after the
     calibration), deterministic same-thesis findings (before vs after the role guard), the saved judge pairs (before vs after the role
     guard), abstract-question findings;
  B. factual non-regression: the corrected version against the first version's invariants;
  C. the REAL validation path, services.instagram_creative_director._validate_viral_carousel, for both versions - with only the judge call
     replaced by the saved verdict of that round (so the order hard -> deterministic -> judge -> correction is the production order).
Usage: python scripts/_instagram_viral_status_replay.py <out dir>
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
CANARY = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary_20260926/post"


def _output(call_file: str) -> dict:
    response = json.loads((CANARY / "calls" / call_file).read_text(encoding="utf-8"))["response"]
    response = json.loads(response) if isinstance(response, str) else response
    return response.get("structured_output", response)


def _request_text(call_file: str) -> str:
    call = json.loads((CANARY / "calls" / call_file).read_text(encoding="utf-8"))
    return "\n".join(t for message in call["request"] for t in message["text"])


def director_input(*, correction_note: str = "", invariants: dict | None = None):
    from services.instagram_creative_director import CreativeDirectorInput
    from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE

    evidence = [line for _n, line in re.findall(r"^E(\d+): (.*)$", _request_text("03_director.json"), re.M)]
    return CreativeDirectorInput(
        objective="shares", format="carousel", opportunity_summary="OpenAI agents / US government websites", allowed_evidence=evidence,
        locale="ru", external_news_entities_allowed=True, media_first=True, generated_media_available=True, planned_format="TREND",
        planned_archetype="trend_generative", available_media_subjects=("source",), unsuitable_media_subjects=(),
        viral_carousel_note=VIRAL_CAROUSEL_NOTE, contract_retry_note=correction_note, factual_invariants=dict(invariants or {}))


def old_lifted_wording(text: str, evidence: list[str], run: int = 6) -> str | None:
    """The rule exactly as it ran in the canary (before the 2026-09-27 calibration) - for the before/after comparison only."""
    word = re.compile(r"[A-Za-zА-Яа-яЁё0-9\-]+")
    words = [w.lower() for w in word.findall(text or "")]
    for item in evidence:
        source = [w.lower() for w in word.findall(item or "")]
        grams = {tuple(source[i:i + run]) for i in range(len(source) - run + 1)}
        for i in range(len(words) - run + 1):
            gram = tuple(words[i:i + run])
            if gram in grams and sum(1 for w in gram if re.fullmatch(r"[а-яё\-]{8,}", w)) >= 3:
                return " ".join(gram)
    return None


def components(raw: dict, evidence: list[str], saved_judge: dict, saved_deterministic: list[str]) -> dict:
    from services.instagram_factual_status import (
        abstract_question_findings,
        build_status_ledger,
        factual_invariants,
        ledger_lines,
        slide_thesis_role,
        status_violations,
    )
    from services.instagram_viral_editorial_judge import apply_role_guard, parse_verdict
    from services.instagram_viral_format import lifted_wording, viral_copy_findings

    slides, caption = raw["slides"], raw.get("final_caption") or ""
    ledger = build_status_ledger(evidence)
    lifted = []
    for i, slide in enumerate(slides, 1):
        for sentence in re.split(r"(?<=[.!?…])\s+", slide.get("slide_body") or ""):
            before, after = old_lifted_wording(sentence, evidence), lifted_wording(sentence, evidence)
            if before or after:
                lifted.append({"slide": i, "sentence": sentence, "before": before, "after": after})
    now = viral_copy_findings(slides, evidence, caption=caption, include_quotes=False)
    thesis_markers = ("make the same point", "repeats the first slide", "restates the first slide", "only specifies the first slide")
    verdict = apply_role_guard(parse_verdict(saved_judge, len(slides)), slides)
    return {
        "ledger": ledger_lines(ledger),
        "status_violations": [v.render() for v in status_violations(slides, caption, ledger, evidence)],
        "invariants": {k: v for k, v in factual_invariants(slides, caption, ledger, evidence).items() if k != "ledger"},
        "roles": [slide_thesis_role(s, i) for i, s in enumerate(slides, 1)],
        "copied_wording": lifted,
        "deterministic_same_thesis_before": [f for f in saved_deterministic if any(m in f for m in thesis_markers)],
        "deterministic_same_thesis_after": [f for f in now if any(m in f for m in thesis_markers)],
        "judge_pairs_before": [[p["slides"], p["reason"]] for p in saved_judge.get("same_thesis_pairs", [])],
        "judge_pairs_after": [[[a, b], r] for a, b, r in verdict.same_thesis_pairs],
        "judge_pairs_dropped_by_role_guard": verdict.dropped_pairs,
        "judge_unsupported_interpretation": [list(u) for u in verdict.unsupported_interpretation],
        "judge_caption_aphorism": verdict.caption_aphorism,
        "abstract_questions": abstract_question_findings(slides, caption, evidence),
        "all_deterministic_findings_after": now,
    }


async def real_path(raw: dict, di, saved_judge: dict) -> dict:
    import services.instagram_creative_director as cd
    import services.instagram_viral_editorial_judge as judge_mod

    diagnostics: list = []
    cd.set_raw_output_sink(lambda event, payload: diagnostics.append(event))

    async def saved(_gateway, _repo, *, slides, caption, allowed_evidence):  # the saved verdict of this round, through the real guard
        return judge_mod.apply_role_guard(judge_mod.parse_verdict(saved_judge, len(slides)), slides)

    real_judge = judge_mod.judge_viral_copy
    judge_mod.judge_viral_copy = saved
    try:
        await cd._validate_viral_carousel(None, None, copy.deepcopy(raw), None, director_input=di, archetype="trend_generative")
        result = {"result": "PASS"}
    except Exception as exc:  # noqa: BLE001 - the replay reports whatever the validation raises
        result = {"result": type(exc).__name__, "hard": isinstance(exc, cd.CreativeFactSafetyError), "detail": str(exc)[:2400],
                  "invariants_attached": bool(getattr(exc, "factual_invariants", None))}
    finally:
        judge_mod.judge_viral_copy = real_judge  # never leak the stub
        cd.set_raw_output_sink(None)
    result["diagnostics_emitted"] = diagnostics
    return result


def main() -> None:
    from services.instagram_factual_status import build_status_ledger, factual_invariants, non_regression_findings

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    first, corrected = _output("03_director.json"), _output("05_director.json")
    note = _request_text("05_director.json").split("PREVIOUS ATTEMPT REJECTED: ", 1)[-1]
    evidence = list(director_input().allowed_evidence)
    judge_initial = json.loads((CANARY / "director_semantic_judge_initial.json").read_text(encoding="utf-8"))
    judge_correction = json.loads((CANARY / "director_semantic_judge_correction.json").read_text(encoding="utf-8"))
    ledger = build_status_ledger(evidence)
    baseline = factual_invariants(first["slides"], first.get("final_caption") or "", ledger, evidence)
    report = {
        "provider_calls": 0, "image_calls": 0, "evidence_lines": len(evidence),
        "first_version": components(first, evidence, judge_initial["verdict"], judge_initial.get("deterministic_findings", [])),
        "corrected_version": components(corrected, evidence, judge_correction["verdict"], judge_correction.get("deterministic_findings", [])),
        "non_regression_corrected_vs_first": non_regression_findings(baseline, corrected["slides"], corrected.get("final_caption") or "",
                                                                      ledger, evidence),
        "real_path_first": asyncio.run(real_path(first, director_input(), judge_initial["verdict"])),
        "real_path_corrected": asyncio.run(real_path(corrected, director_input(correction_note=note, invariants=baseline),
                                                     judge_correction["verdict"])),
    }
    (out / "status_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("non_regression_corrected_vs_first",)}
                     | {"first_status": report["first_version"]["status_violations"],
                        "corrected_status": report["corrected_version"]["status_violations"],
                        "real_path_first": report["real_path_first"]["result"], "real_path_corrected": report["real_path_corrected"]["result"]},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
