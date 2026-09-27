"""Zero-model OFFLINE REPLAY of the sixth paid viral canary's FIRST Director output through the context-aware named-person image-safety
gate, then the next existing validators (founder task 2026-09-27). No provider / LLM / image call, no database write, no publication.

Input: artifacts/instagram_feed_product/viral_nominated_canary6_20260927/post - the saved Director request (its E1..En evidence lines) and
the saved first Director output. Steps:
  1. image safety: named_people (A) and generated_person_risks (B) per slide, before (the saved canary error) vs now;
  2. the REAL validation path services.instagram_creative_director._validate_viral_carousel, with the semantic-judge call replaced by a
     sentinel - the judge was never run in canary 6, so there is no saved verdict to replay: if the path reaches the judge, the judge is
     reported NOT RUN OFFLINE and everything before it (hard gates, target status, deterministic copy / thesis) has passed;
  3. component view: target-status ledger + violations, unsupported targets, factual invariants, deterministic copy / thesis findings.
Usage: python scripts/_instagram_named_person_replay.py <out dir>
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
CANARY = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary6_20260927/post"


class JudgeReached(Exception):
    """The validation reached the semantic judge - there is no saved verdict for canary 6, so it is not run offline."""


def evidence_lines() -> list[str]:
    call = json.loads((CANARY / "calls/03_director.json").read_text(encoding="utf-8"))
    text = "\n".join(t for message in call["request"] for t in message["text"])
    return [line for _n, line in re.findall(r"^E(\d+): (.*)$", text, re.M)]


def director_input(evidence: list[str]):
    from services.instagram_creative_director import CreativeDirectorInput
    from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE

    return CreativeDirectorInput(
        objective="shares", format="carousel", opportunity_summary="OpenAI agents / US government websites", allowed_evidence=evidence,
        locale="ru", external_news_entities_allowed=True, media_first=True, generated_media_available=True, planned_format="TREND",
        planned_archetype="trend_generative", available_media_subjects=("source",), unsuitable_media_subjects=(),
        viral_carousel_note=VIRAL_CAROUSEL_NOTE, contract_retry_note="", factual_invariants={})


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
        return {"result": type(exc).__name__, "hard": isinstance(exc, cd.CreativeFactSafetyError), "detail": str(exc)[:3000],
                "factual_repair": list(getattr(exc, "factual_repair", []) or []), "judge": "NOT REACHED"}
    finally:
        judge_mod.judge_viral_copy = real_judge  # never leak the stub
        cd.set_raw_output_sink(None)


def correctable_findings(raw: dict, di) -> list[str]:
    import services.instagram_creative_director as cd
    from services.instagram_viral_format import EditorialCorrectionRequired

    try:
        cd._validate_carousel_output(copy.deepcopy(raw), None, director_input=di, archetype="trend_generative")
        return []
    except EditorialCorrectionRequired as exc:
        return list(exc.findings)


def main() -> None:
    from services.instagram_factual_status import (
        build_status_ledger,
        factual_invariants,
        ledger_lines,
        status_violations,
        unsupported_target_violations,
    )
    from services.instagram_viral_format import depiction_findings, generated_person_risks, named_identities, viral_copy_findings

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    raw = json.loads((CANARY / "director_raw_output_initial.json").read_text(encoding="utf-8"))["structured_output"]
    evidence = evidence_lines()
    identities = named_identities(evidence)
    slides, caption = raw["slides"], raw.get("final_caption") or ""
    ledger = build_status_ledger(evidence)
    per_slide = [{"slide": i, "media_source": s.get("media_source"),
                  "findings": depiction_findings(" ".join(str(s.get(k) or "") for k in ("generation_brief", "visual_direction")), identities)
                  if s.get("media_source") == "generated" else "n/a (not generated)"} for i, s in enumerate(slides, 1)]
    report = {
        "provider_calls": 0, "image_calls": 0, "evidence_lines": len(evidence),
        "A_named_people_in_evidence": {k: sorted(v) for k, v in identities.items()},
        "image_safety_before": json.loads((CANARY / "director_validation_error.json").read_text(encoding="utf-8")),
        "image_safety_now": {"risks": generated_person_risks(slides, evidence), "per_slide": per_slide},
        "target_status": {"ledger": ledger_lines(ledger),
                          "status_violations": [v.render() for v in status_violations(slides, caption, ledger, evidence)],
                          "unsupported_targets": [v.render() for v in unsupported_target_violations(slides, caption, evidence)],
                          "invariants": {k: v for k, v in factual_invariants(slides, caption, ledger, evidence).items() if k != "ledger"}},
        "deterministic_copy_and_thesis": viral_copy_findings(slides, evidence, caption=caption, include_quotes=False),
        "real_path": asyncio.run(real_path(raw, director_input(evidence))),
        # what the real path would carry INTO the judge round (combined with the judge's findings there)
        "deterministic_correctable_carried_to_judge": correctable_findings(raw, director_input(evidence)),
        "slides": [[s.get("role"), s.get("slide_copy"), s.get("slide_body"), s.get("source_evidence")] for s in slides], "caption": caption,
    }
    (out / "named_person_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("A_named_people_in_evidence", "image_safety_now", "target_status", "deterministic_copy_and_thesis", "deterministic_correctable_carried_to_judge",
                                             "real_path")}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
