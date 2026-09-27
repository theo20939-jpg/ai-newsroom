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
CANARY3 = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary3_20260927/post"  # Phase A v4 live output (canary 3)
CANARY4 = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary4_20260927/post"  # Phase A v5 live output (canary 4)


def saved_output(canary: Path = CANARY2) -> dict:
    return json.loads((canary / "director_phase_a_raw_output.json").read_text(encoding="utf-8"))["structured_output"]


def saved_evidence(canary: Path = CANARY2) -> list[str]:
    call = json.loads((canary / "calls/01_phase_a.json").read_text(encoding="utf-8"))
    text = "\n".join(t for message in call["request"] for t in message["text"])
    return [line for _n, line in re.findall(r"^E(\d+): (.*)$", text, re.M)]


def decision_input(canary: Path = CANARY2):
    from services.instagram_creative_director import InstagramEditorialDecisionInput

    return InstagramEditorialDecisionInput(source_type="NEWS", source_summary="OpenAI agents / US government websites",
                                           allowed_evidence=saved_evidence(canary), executable_formats=["single", "carousel"], locale="ru",
                                           planned_format="TREND")


def valid_v5_fixture(saved: dict) -> dict:
    """Canary 3's own (substantively correct) Phase A plan with a COMPLETE creative_direction under 650 characters; the negated warning
    against calling it a hack stays. Replay / test material only, never production wording."""
    fixture = copy.deepcopy(saved)
    fixture["creative_direction"] = (
        "Первый слайд — реальное фото из источника и крупный хук: ИИ-агент OpenAI сам заходил на сайты ведомств США, узнали об этом только "
        "сейчас. Далее: хронология — поведение летом, раскрытие 25–26 сентября; доступ к сайтам Министерства торговли и SEC подтверждён; "
        "эпизод с Министерством образования ещё расследуется; что ответила компания. Визуал: реальное фото источника и абстрактная "
        "серверная инфраструктура. Финал — главный факт: это раскрытие летнего эпизода, а не событие сегодняшнего дня.")
    return fixture


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


def canary4_correction_fixture(saved: dict) -> dict:
    """What a valid ONE-REPAIR correction of canary 4's plan looks like: the same plan, the two flagged passages rephrased unambiguously
    (no warning word to misread, the Education card as its own sentence). Replay / test material only, never production wording."""
    fixture = copy.deepcopy(saved)
    fixture["audience_value"] = ("Аудитория поймёт, что именно подтверждено, какие действия агента описаны в источнике и почему автономный "
                                 "доступ к государственным сайтам вызывает тревогу - без преувеличений.")
    fixture["creative_direction"] = (
        "Открытие: крупная типографика «ИИ сам взаимодействовал с госсайтами?» и пометка «раскрыто сейчас, произошло летом». Далее отдельные "
        "карточки: OpenAI подтвердила доступ к сайтам Министерства торговли и SEC. Затем отдельная карточка: эпизод с Министерством "
        "образования ещё расследуется. Использовать исходное изображение и абстрактную графику цифровой инфраструктуры, без имитации "
        "чужих сайтов и документов. Финал: «Это не сегодняшнее событие: сегодня раскрыли детали летнего эпизода».")
    return fixture


async def run_phase_a_sequence(outputs: list[dict], canary: Path = CANARY2) -> dict:
    """The REAL Phase A path (generate_editorial_decision) with the model calls replaced by `outputs` in order: the first generation, then
    the one correction. Records every call (capability, the correction prompt's presence) and the diagnostics."""
    import services.instagram_creative_director as cd
    from integrations.prompts.file_repository import FilePromptRepository

    real = cd.call_generate
    diagnostics: list = []
    calls: list = []
    cd.set_raw_output_sink(lambda event, payload: diagnostics.append((event, payload)))

    async def fake_call(_gateway, request, **kw):
        calls.append({"capability": kw["runtime"].capability_name,
                      "correction_input": "ORIGINAL PHASE A PLAN" in request.messages[1].content[0].text})
        if len(calls) > len(outputs):
            raise AssertionError("more Phase A calls than the bound")
        return SimpleNamespace(error=None, call=None, response=SimpleNamespace(finish_reason="stop",
                                                                             structured_output=copy.deepcopy(outputs[len(calls) - 1])))

    cd.call_generate = fake_call
    try:
        decision, _call = await cd.generate_editorial_decision(None, FilePromptRepository(ROOT / "prompts"), decision_input=decision_input(canary))
        result = {"result": "PASS", "recommended_format": decision.recommended_format, "source_summary": decision.source_summary}
    except Exception as exc:  # noqa: BLE001 - the replay reports what the validation raises
        result = {"result": type(exc).__name__, "detail": str(exc)[:3000]}
    finally:
        cd.call_generate = real
        cd.set_raw_output_sink(None)
    result["phase_a_calls"] = len(calls)
    result["calls"] = calls
    result["diagnostics"] = [event for event, _p in diagnostics]
    result["summary"] = next((p for event, p in reversed(diagnostics) if event == "phase_a_summary"), None)
    result["first_findings"] = next((p["findings"] for event, p in diagnostics if event == "phase_a_contract_violation"), [])
    result["post_correction_findings"] = next((p["findings"] for event, p in diagnostics if event == "phase_a_correction_contract_violation"), [])
    return result


async def run_phase_a(structured: dict, canary: Path = CANARY2) -> dict:
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
        decision, _call = await cd.generate_editorial_decision(None, FilePromptRepository(ROOT / "prompts"), decision_input=decision_input(canary))
        result = {"result": "PASS", "recommended_format": decision.recommended_format, "angle_intent": decision.angle_intent,
                  "evidence_used": len(decision.evidence_used)}
    except Exception as exc:  # noqa: BLE001 - the replay reports what the validation raises
        result = {"result": type(exc).__name__, "detail": str(exc)[:3000]}
    finally:
        cd.call_generate = real
        cd.set_raw_output_sink(None)
    result["diagnostics"] = [event for event, _p in diagnostics]
    return result


def component_view(structured: dict, canary: Path = CANARY2) -> dict:
    import services.instagram_creative_director as cd
    from services.instagram_phase_a_contract import (
        incomplete_creative_direction,
        phase_a_finale_findings,
        phase_a_status_findings,
        phase_a_visual_findings,
    )

    evidence = saved_evidence(canary)
    rationale = structured.get("trend_rationale") or ""
    trend = [{"match": m.group(0), "negated": cd._trend_mention_negated(rationale, m.start(), m.end())}
             for m in cd._UNSUPPORTED_PLATFORM_TREND_CLAIM_RE.finditer(rationale)]
    return {"trend_mentions": trend, "trend_disclaimer_recognised": all(t["negated"] for t in trend),
            "status": phase_a_status_findings(structured, evidence), "visual": phase_a_visual_findings(structured),
            "finale": phase_a_finale_findings(structured, evidence), "incomplete_creative_direction": incomplete_creative_direction(structured),
            "creative_direction_chars": len(structured.get("creative_direction") or "")}


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
    saved3 = saved_output(CANARY3)
    fixture3 = valid_v5_fixture(saved3)
    report["saved_canary3_phase_a_v4"] = {"components": component_view(saved3, CANARY3), "real_path": asyncio.run(run_phase_a(saved3, CANARY3))}
    report["valid_v5_fixture"] = {"creative_direction": fixture3["creative_direction"], "components": component_view(fixture3, CANARY3),
                                  "real_path": asyncio.run(run_phase_a(fixture3, CANARY3))}
    # --- Phase A ONE-REPAIR (founder task 2026-09-27): the saved first outputs stay failures; the orchestration repairs them once ---
    saved4 = saved_output(CANARY4)
    fixture4 = canary4_correction_fixture(saved4)
    repair = {}
    for name, canary, first, corrected in (("canary2", CANARY2, saved, fixture), ("canary3", CANARY3, saved3, fixture3),
                                           ("canary4", CANARY4, saved4, fixture4)):
        repair[name] = {"first_output_components": component_view(first, canary), "correction_fixture_components": component_view(corrected, canary),
                        "sequence": asyncio.run(run_phase_a_sequence([first, corrected], canary))}
    repair["first_pass_no_correction"] = asyncio.run(run_phase_a_sequence([fixture3], CANARY3))
    still_bad = copy.deepcopy(fixture4)
    still_bad["source_summary"] = "OpenAI подтвердила доступ к сайтам Министерства торговли, Министерства образования и SEC."  # promotes Education
    repair["failed_correction_terminal"] = asyncio.run(run_phase_a_sequence([saved4, still_bad], CANARY4))
    report["phase_a_one_repair"] = repair
    (out / "phase_a_contract_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: {"components": v["components"], "real_path": v["real_path"]} for k, v in report.items() if isinstance(v, dict)},
                     ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
