"""Zero-model OFFLINE REPLAY of the seventh paid viral canary's FIRST Director output through the quote-use classification (founder task
2026-09-27), then one LOCAL correction fixture through the real correction-mode validation. No provider / LLM / image call, no database
write, no publication.

Input: artifacts/instagram_feed_product/viral_nominated_canary7_20260927/post - the saved Director request (E1..En) and the first output.
  1. the first output through classify_quote_use and the REAL path (services.instagram_creative_director._validate_viral_carousel), with
     the semantic judge replaced by a sentinel: canary 7 never ran the judge, so there is no verdict to replay - reaching it means every
     gate before it (quote, named-person, factual status, deterministic copy / thesis) ran; the deterministic findings carried into the
     judge round are reported, and the correction note the ONE correction would receive is built from them (judge part NOT RUN OFFLINE);
  2. a LOCAL correction fixture (replay-only wording, never production copy): the caption's closing sentence without the quotation marks,
     through the real path in CORRECTION mode (the correction note + the first version's factual invariants) - the complete chain again.
Usage: python scripts/_instagram_quote_use_replay.py <out dir>
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
CANARY = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary7_20260927/post"
QUOTED_SENTENCE = "Поэтому здесь важно не перепрыгивать от «неожиданного взаимодействия» сразу к «взлому»."
FIXTURE_SENTENCE = "Поэтому здесь важно не перепрыгивать от неожиданного взаимодействия сразу к взлому."


class JudgeReached(Exception):
    pass


def evidence_lines() -> list[str]:
    call = json.loads((CANARY / "calls/02_director.json").read_text(encoding="utf-8"))
    text = "\n".join(t for message in call["request"] for t in message["text"])
    return [line for _n, line in re.findall(r"^E(\d+): (.*)$", text, re.M)]


def director_input(evidence: list[str], *, note: str = "", invariants: dict | None = None):
    from services.instagram_creative_director import CreativeDirectorInput
    from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE

    return CreativeDirectorInput(
        objective="shares", format="carousel", opportunity_summary="OpenAI agents / US government websites", allowed_evidence=evidence,
        locale="ru", external_news_entities_allowed=True, media_first=True, generated_media_available=True, planned_format="TREND",
        planned_archetype="trend_generative", available_media_subjects=("source",), unsuitable_media_subjects=(),
        viral_carousel_note=VIRAL_CAROUSEL_NOTE, contract_retry_note=note, factual_invariants=dict(invariants or {}))


async def real_path(raw: dict, di) -> dict:
    import services.instagram_creative_director as cd
    import services.instagram_viral_editorial_judge as judge_mod

    async def sentinel(*_a, **_k):
        raise JudgeReached()

    real_judge = judge_mod.judge_viral_copy
    judge_mod.judge_viral_copy = sentinel
    cd.set_raw_output_sink(lambda *_a: None)
    try:
        await cd._validate_viral_carousel(None, None, copy.deepcopy(raw), None, director_input=di, archetype="trend_generative")
        return {"result": "PASS", "judge": "NOT CALLED"}
    except JudgeReached:
        return {"result": "REACHED_SEMANTIC_JUDGE", "judge": "NOT RUN OFFLINE (no saved verdict; a judge run is a provider call)"}
    except Exception as exc:  # noqa: BLE001 - the replay reports whatever the validation raises
        return {"result": type(exc).__name__, "hard": isinstance(exc, cd.CreativeFactSafetyError), "detail": str(exc)[:3000], "judge": "NOT REACHED"}
    finally:
        judge_mod.judge_viral_copy = real_judge  # never leak the stub
        cd.set_raw_output_sink(None)


def carried(raw: dict, di) -> list[str]:
    """The deterministic correctable findings the real path carries into the judge round (combined with the judge's findings there)."""
    import services.instagram_creative_director as cd
    from services.instagram_viral_format import EditorialCorrectionRequired

    try:
        cd._validate_carousel_output(copy.deepcopy(raw), None, director_input=di, archetype="trend_generative")
        return []
    except EditorialCorrectionRequired as exc:
        return list(exc.findings)


def stage(raw: dict, evidence: list[str], di) -> dict:
    from services.instagram_factual_status import build_status_ledger, factual_invariants, status_violations, unsupported_target_violations
    from services.instagram_viral_format import classify_quote_use, generated_person_risks

    slides, caption = raw["slides"], raw.get("final_caption") or ""
    fields = [*((f"slide {i} hook", s.get("slide_copy") or "") for i, s in enumerate(slides, 1)),
              *((f"slide {i} body", s.get("slide_body") or "") for i, s in enumerate(slides, 1)), ("caption", caption)]
    quotes = classify_quote_use(fields, evidence)
    ledger = build_status_ledger(evidence)
    return {
        "quote_gate": {"terminal": quotes.terminal, "repairable": quotes.repairable,
                       "result": "TERMINAL" if quotes.terminal else "REPAIRABLE" if quotes.repairable else "PASS"},
        "named_person_risks": generated_person_risks(slides, evidence),
        "status_violations": [v.render() for v in status_violations(slides, caption, ledger, evidence)],
        "unsupported_targets": [v.render() for v in unsupported_target_violations(slides, caption, evidence)],
        "invariants": {k: v for k, v in factual_invariants(slides, caption, ledger, evidence).items() if k != "ledger"},
        "hook_lengths": [len(s.get("slide_copy") or "") for s in slides],
        "deterministic_carried_to_judge": carried(raw, di),
        "real_path": asyncio.run(real_path(raw, di)),
    }


def main() -> None:
    from services.instagram_factual_status import build_status_ledger, factual_invariants, ledger_lines
    from services.instagram_viral_format import EditorialCorrectionRequired

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    first = json.loads((CANARY / "director_raw_output_initial.json").read_text(encoding="utf-8"))["structured_output"]
    evidence = evidence_lines()
    first_stage = stage(first, evidence, director_input(evidence))
    ledger = build_status_ledger(evidence)
    invariants = factual_invariants(first["slides"], first.get("final_caption") or "", ledger, evidence)
    # the note the ONE correction receives when the judge adds nothing (the judge's own findings would be appended - NOT RUN OFFLINE)
    note = EditorialCorrectionRequired(first_stage["deterministic_carried_to_judge"], factual_contract=ledger_lines(ledger),
                                       factual_invariants=invariants).correction_note
    assert QUOTED_SENTENCE in first["final_caption"], "the saved caption changed"
    fixture = copy.deepcopy(first)
    fixture["final_caption"] = first["final_caption"].replace(QUOTED_SENTENCE, FIXTURE_SENTENCE)
    report = {
        "provider_calls": 0, "image_calls": 0, "evidence_lines": len(evidence),
        "first_output": first_stage,
        "correction_note_deterministic_part": note,
        "fixture": {"caption": fixture["final_caption"], "change": [QUOTED_SENTENCE, FIXTURE_SENTENCE],
                    **stage(fixture, evidence, director_input(evidence, note=note, invariants=invariants))},
    }
    (out / "quote_use_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    brief = {k: {kk: vv for kk, vv in v.items() if kk != "invariants"} for k, v in report.items() if k in ("first_output", "fixture")}
    print(json.dumps(brief, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
