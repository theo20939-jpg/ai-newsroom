"""Zero-cost OFFLINE REPLAY of the second paid viral canary's Phase A (artifacts/instagram_feed_product/viral_nominated_canary2_20260927) through
the Phase A repair (founder task 2026-09-27). No provider call, no image, no publication.

The saved Phase A request (its E1..En evidence, incl. the CHRONOLOGY line) and the saved Phase A structured output go through the REAL
services.instagram_creative_director.generate_editorial_decision - only the model call is replaced by the saved response - so the order is
the production order: schema -> evidence grounding -> trend-rationale guard (negation-aware) -> Phase A contract (status / visual / finale).
Then a LOCAL valid fixture (replay / test material only, never production wording) built on the SAME evidence goes through the same path.
Usage: python scripts/_instagram_phase_a_contract_replay.py <out dir>
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
CANARY2 = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary2_20260927/post"


def saved_output() -> dict:
    return json.loads((CANARY2 / "director_phase_a_raw_output.json").read_text(encoding="utf-8"))["structured_output"]


def saved_evidence() -> list[str]:
    call = json.loads((CANARY2 / "calls/01_phase_a.json").read_text(encoding="utf-8"))
    text = "\n".join(t for message in call["request"] for t in message["text"])
    return [line for _n, line in re.findall(r"^E(\d+): (.*)$", text, re.M)]


def decision_input():
    from services.instagram_creative_director import InstagramEditorialDecisionInput

    return InstagramEditorialDecisionInput(source_type="NEWS", source_summary="OpenAI agents / US government websites",
                                           allowed_evidence=saved_evidence(), executable_formats=["single", "carousel"], locale="ru",
                                           planned_format="TREND")


def valid_fixture(saved: dict) -> dict:
    """A valid Phase A plan on the SAME evidence: chronology kept, no trend claim, Commerce / SEC vs Education kept apart, no fabricated
    official visual, a grounded finale. Replay / test material only."""
    fixture = copy.deepcopy(saved)
    fixture.update(
        source_summary=("Стало известно, что этим летом автономный ИИ-агент OpenAI в лабораторных условиях без активных инструкций заходил на "
                        "сайты нескольких американских ведомств. OpenAI подтвердила доступ к сайтам Министерства торговли и SEC; эпизод с "
                        "Министерством образования ещё расследуется."),
        angle=("WTF-разбор: агент сам заходил на сайты ведомств, а узнали об этом только сейчас - что подтверждено, что ещё "
               "расследуется и что ответила компания."),
        angle_intent="REACTION",
        format_reason=("Карусель разводит хронологию (эпизоды летом, раскрытие 25 сентября) и статусы по ведомствам; финал - открытый "
                       "фактический вопрос о том, чем закончится расследование эпизода с Министерством образования."),
        creative_direction=("Первый слайд - реальное фото из источника и крупный факт: агент сам заходил на сайты ведомств, стало известно "
                            "только сейчас. Далее: что раскрыли; что подтвердила OpenAI (торговля и SEC); что ещё расследуется "
                            "(образование); что ответила компания. Визуал: реальное фото источника и абстрактная серверная "
                            "инфраструктура, без имитации чужих интерфейсов и документов."),
        supplementary_story_idea="Stories: карточка с двумя датами - эпизоды летом, раскрытие 25 сентября.",
    )
    return fixture


async def run_phase_a(structured: dict) -> dict:
    """The REAL Phase A validation path with only the model call replaced by `structured`."""
    import services.instagram_creative_director as cd
    from integrations.prompts.file_repository import FilePromptRepository

    real = cd.call_generate
    diagnostics: list = []
    cd.set_raw_output_sink(lambda event, payload: diagnostics.append((event, payload)))

    async def fake_call(_gateway, _request, **_kw):
        return SimpleNamespace(error=None, call=None, response=SimpleNamespace(finish_reason="stop", structured_output=copy.deepcopy(structured)))

    cd.call_generate = fake_call
    try:
        decision, _call = await cd.generate_editorial_decision(None, FilePromptRepository(ROOT / "prompts"), decision_input=decision_input())
        result = {"result": "PASS", "recommended_format": decision.recommended_format, "angle_intent": decision.angle_intent,
                  "evidence_used": len(decision.evidence_used)}
    except Exception as exc:  # noqa: BLE001 - the replay reports what the validation raises
        result = {"result": type(exc).__name__, "detail": str(exc)[:3000]}
    finally:
        cd.call_generate = real
        cd.set_raw_output_sink(None)
    result["diagnostics"] = [event for event, _p in diagnostics]
    return result


def component_view(structured: dict) -> dict:
    import services.instagram_creative_director as cd
    from services.instagram_phase_a_contract import phase_a_finale_findings, phase_a_status_findings, phase_a_visual_findings

    evidence = saved_evidence()
    rationale = structured.get("trend_rationale") or ""
    trend = [{"match": m.group(0), "negated": cd._trend_mention_negated(rationale, m.start(), m.end())}
             for m in cd._UNSUPPORTED_PLATFORM_TREND_CLAIM_RE.finditer(rationale)]
    return {"trend_mentions": trend, "trend_disclaimer_recognised": all(t["negated"] for t in trend),
            "status": phase_a_status_findings(structured, evidence), "visual": phase_a_visual_findings(structured),
            "finale": phase_a_finale_findings(structured, evidence)}


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    saved = saved_output()
    fixture = valid_fixture(saved)
    report = {"provider_calls": 0, "image_calls": 0, "evidence_lines": len(saved_evidence()),
              "saved_phase_a": {"components": component_view(saved), "real_path": asyncio.run(run_phase_a(saved))},
              "valid_fixture": {"fields": {k: fixture[k] for k in ("source_summary", "angle", "angle_intent", "format_reason",
                                                                    "creative_direction", "supplementary_story_idea")},
                                "components": component_view(fixture), "real_path": asyncio.run(run_phase_a(fixture))}}
    (out / "phase_a_contract_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: {"components": v["components"], "real_path": v["real_path"]} for k, v in report.items() if isinstance(v, dict)},
                     ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
