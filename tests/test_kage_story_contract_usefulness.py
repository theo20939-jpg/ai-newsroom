"""Generic story contract keeps premise-critical context; deterministic usefulness guard blocks a
factually safe headline restatement. Real production lineages (messages 2864/2865) are fixtures;
no provider call, no Telegram send."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.kage_content_lineage_audit import KageContentLineageAudit
from database.models.story_telegram_delivery import StoryTelegramDelivery
from schemas.content_draft import ContentDraftRead
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import kage_evidence_first as ef
from services import workflow_service
from services.content_quality_gates import evaluate_content_quality_gates
from services.kage_content_lineage_audit import create_attempt_audit
from services.kage_editorial_usefulness import evaluate_editorial_usefulness
from services.kage_publication_factual_gate import build_gate_input
from services.kage_publication_worker_gate import WorkerGateResult
from services.telegram_notifier import NotificationOutcome
from tests.test_content_worker_cycle import _make_event, factory, test_source  # noqa: F401
from worker.content_cycle import run_content_cycle

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


M2865 = _load("kage_lineage_msg2865.json")
M2864 = _load("kage_lineage_msg2864.json")
BLOCKED = _load("kage_lineage_blocked_gates.json")
OLD_TITLE = "Обучение последних моделей OpenAI — на паузе"
OLD_BODY = "OpenAI приостановила его."
GOOD_BODY = ("Решение приняли после того, как её агенты неожиданным образом обращались "
             "к сайтам американских госорганов.")


def _contract(fixture: dict) -> dict:
    return ef.minimum_story_contract(fixture["research"], fixture["intelligence"],
                                     source_headline=fixture["source_headline"])


def _guard(fixture: dict, title: str, body: str) -> dict:
    return evaluate_editorial_usefulness(title=title, body=body, research=fixture["research"],
                                         intelligence=fixture["intelligence"],
                                         source_headline=fixture["source_headline"])


def _ids(items) -> list[int]:
    return [item["id"] for item in items]


# --- reproduce the old result exactly, then the new contract ----------------------------------

@pytest.mark.parametrize("fixture", [M2865, M2864, BLOCKED], ids=["msg2865", "msg2864", "blocked"])
def test_old_generic_algorithm_reproduces_the_saved_production_contract_exactly(fixture, monkeypatch):
    monkeypatch.setattr(ef, "premise_context_card_ids", lambda *a, **k: [])
    monkeypatch.setattr(ef, "_GENERIC_COMPLETENESS_RULE", ef._SHORTEST_COMPLETE_RULE)
    assert _contract(fixture) == fixture["saved_minimum_story_contract"]


def test_message_2865_old_contract_made_the_premise_context_optional():
    saved = M2865["saved_minimum_story_contract"]
    assert _ids(saved["core_facts"]) == [1] and _ids(saved["optional_facts"]) == [2]
    assert saved["rule"].endswith("Stop at the shortest complete post.")


def test_message_2865_new_contract_makes_both_premise_facts_core():
    contract = _contract(M2865)
    assert contract["selected_premise"]["kind"] == "supported_fact_with_premise_context"
    assert _ids(contract["core_facts"]) == [1, 2] and contract["optional_facts"] == []
    assert contract["core_facts"][1]["why_core"] == "Supported reason/context the selected premise depends on"
    assert "shortest complete post" not in contract["rule"]
    assert "supported reason/context" in contract["rule"] and "Short is still preferred" in contract["rule"]


def test_message_2865_fact_2_is_the_government_sites_cause():
    fact2 = M2865["research"]["facts"][1]
    assert "агенты OpenAI" in fact2 and "правительства США" in fact2


# --- usefulness guard on message 2865 ---------------------------------------------------------

def test_old_delivered_copy_is_blocked():
    assert M2865["copywriting"]["main_body"] == OLD_BODY and M2865["copywriting"]["title"] == OLD_TITLE
    result = _guard(M2865, OLD_TITLE, OLD_BODY)
    assert result["applicable"] and not result["passed"]
    assert result["reason"] == "body_adds_no_supported_fact_beyond_headline"
    assert result["headline_fact_ids"] == [1] and result["new_body_fact_ids"] == []


def test_semantic_paraphrase_of_the_headline_is_still_a_restatement():
    result = _guard(M2865, "OpenAI приостановила обучение моделей", "OpenAI поставила его на паузу.")
    assert not result["passed"]


@pytest.mark.parametrize("title,body", [
    ("OpenAI приостановила обучение последних моделей", GOOD_BODY),
    (OLD_TITLE, "По данным NBC News, причиной стали агенты OpenAI, которые неожиданно искали что-то "
                "на сайтах правительства США."),
])
def test_supported_body_carrying_the_cause_passes(title, body):
    result = _guard(M2865, title, body)
    assert result["passed"] and result["new_body_fact_ids"] == [2]


def test_dense_headline_with_restating_body_is_blocked():
    result = _guard(M2865, "OpenAI остановила обучение после того, как агенты неожиданно искали на сайтах "
                           "правительства США", "OpenAI приостановила обучение моделей.")
    assert result["headline_fact_ids"] == [1, 2] and not result["passed"]


# --- regressions ---------------------------------------------------------------------------------

def test_message_2864_contract_keeps_one_core_fact_and_accepted_copy_passes():
    contract = _contract(M2864)
    saved = M2864["saved_minimum_story_contract"]
    assert contract["selected_premise"] == saved["selected_premise"]
    assert contract["core_facts"] == saved["core_facts"] and contract["optional_facts"] == saved["optional_facts"]
    copy = M2864["copywriting"]
    result = _guard(M2864, copy["title"], copy["main_body"])
    assert result["passed"] and not result["applicable"]


def test_gap_and_selection_meta_cards_never_become_core():
    facts = M2864["research"]["facts"]
    assert "История выбрана" in facts[1] and "не указаны" in facts[2]
    assert ef.premise_context_card_ids(
        ef.evidence_cards(M2864["research"]), M2864["intelligence"], 1) == []


def test_blocked_story_contract_is_unchanged():
    contract = _contract(BLOCKED)
    saved = BLOCKED["saved_minimum_story_contract"]
    assert contract["core_facts"] == saved["core_facts"] and contract["optional_facts"] == saved["optional_facts"]


def test_true_one_fact_story_is_never_blocked_for_lacking_context():
    research = {"facts": ["Apple выпустила iOS 27.1 с исправлением ошибки Bluetooth."]}
    intelligence = {"angle": "Apple выпустила iOS 27.1 с исправлением Bluetooth", "recommendation": "PUBLISH"}
    result = evaluate_editorial_usefulness(title="Apple выпустила iOS 27.1", body="Обновление исправляет Bluetooth.",
                                           research=research, intelligence=intelligence)
    assert result["passed"] and not result["applicable"] and result["reason"] == "fewer_than_two_core_facts"
    assert evaluate_editorial_usefulness(title="Apple выпустила iOS 27.1", body="Вышла iOS 27.1.",
                                         research=research, intelligence=intelligence)["passed"]


def test_second_fact_the_premise_does_not_depend_on_stays_optional():
    research = {"facts": [
        "Valve выпустила обновление Steam Deck с переназначением кнопок.",
        "Компания основана в 1996 году в Бельвью.",
    ]}
    intelligence = {"angle": "Valve добавила переназначение кнопок в Steam Deck — это удобно игрокам.",
                    "recommendation": "PUBLISH: полезное обновление Steam Deck."}
    contract = ef.minimum_story_contract(research, intelligence)
    assert _ids(contract["core_facts"]) == [1] and _ids(contract["optional_facts"]) == [2]
    assert evaluate_editorial_usefulness(title="Steam Deck получил переназначение кнопок",
                                         body="Valve выпустила обновление.", research=research,
                                         intelligence=intelligence)["passed"]


def test_premise_context_is_capped_at_two_extra_cards():
    research = {"facts": [
        "OpenAI приостановила обучение моделей.",
        "Причиной стали агенты, неожиданно искавшие на сайтах правительства США.",
        "Агенты обращались к сайтам правительства США без запросов пользователей.",
        "Агенты сохраняли найденные на сайтах правительства США данные неожиданно для инженеров.",
    ]}
    intelligence = {"angle": "Агенты неожиданно искали и сохраняли данные на сайтах правительства США без запросов "
                             "пользователей, инженеров это удивило.", "recommendation": "PUBLISH"}
    assert len(ef.premise_context_card_ids(ef.evidence_cards(research), intelligence, 1)) <= 2


def test_hard_coded_branch_contract_is_unchanged_by_the_generic_rule():
    research = {"facts": [
        "Google Maps связала избранные достопримечательности пяти городов США с подкастом Hidden Histories.",
        "На странице места появляется панель с эпизодом о нём.",
    ]}
    contract = ef.minimum_story_contract(research, {"angle": "Hidden Histories в Google Maps", "recommendation": "PUBLISH"})
    assert contract["selected_premise"]["kind"] == "one_supported_fact"
    assert contract["rule"] == ef._SHORTEST_COMPLETE_RULE
    assert [c["minimum_meaning"] for c in contract["core_facts"]][0].startswith("selected landmarks")


def test_factual_gate_input_shape_unchanged_and_only_the_card_split_moves():
    gate_input = build_gate_input(draft={"title": OLD_TITLE, "main_body": OLD_BODY, "ending": None},
                                  research=M2865["research"], intelligence=M2865["intelligence"],
                                  source_headline=M2865["source_headline"])
    assert _ids(gate_input["CORE_FACTS"]) == [1, 2] and gate_input["OPTIONAL_FACTS"] == []
    # Both cards are evidence either way; the gate's known-fact set is identical to before.
    assert {c["id"] for c in gate_input["CORE_FACTS"] + gate_input["OPTIONAL_FACTS"]} == {1, 2}


def test_why_it_matters_is_not_applicable_to_a_schema_without_the_field():
    kwargs = dict(title=OLD_TITLE, body="Причиной стали агенты на сайтах правительства США.", source_title="x")
    assert "why_it_matters_present" not in evaluate_content_quality_gates(**kwargs, why_it_matters_expected=False).failed_gates
    assert "why_it_matters_present" in evaluate_content_quality_gates(**kwargs).failed_gates  # legacy default unchanged


# --- the real worker: blocked before either send branch, durable terminal reason -------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("body, expect_send", [(OLD_BODY, False), (GOOD_BODY, True)])
async def test_worker_blocks_restatement_before_send_and_records_terminal_reason(
    body, expect_send, factory, test_source, monkeypatch,
):
    for key, value in (("copywriting_prompt_version", "11.10"), ("editorial_delivery_mode", "legacy"),
                       ("unified_editorial_pipeline_enabled", False), ("image_editorial_preview_enabled", False),
                       ("content_generation_dry_run", False), ("telegram_story_reply_mode", "off"),
                       ("fact_safety_mode", "enforce"), ("instagram_automatic_generation_enabled", False)):
        monkeypatch.setattr(settings, key, value)
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        event.title = M2865["source_headline"]
        task = await workflow_service.create_task(
            session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION,
                                         priority=TaskPriority.B))
        await create_attempt_audit(session, task_id=task.id, event_id=event.id, story_id=None, source_snapshot={})
        draft_id = uuid4()
        session.add(ContentDraft(id=draft_id, task_id=task.id, type=ContentType.POST, title=OLD_TITLE,
                                 body=body, status="draft", version=1))
        await session.commit()
    now = datetime.now(timezone.utc)
    draft = ContentDraftRead(id=draft_id, task_id=task.id, type=ContentType.POST, title=OLD_TITLE, body=body,
                             hashtags=None, version=1, status="draft", created_at=now, updated_at=now)
    outcome = SimpleNamespace(
        task_id=task.id, content_draft=draft,
        copywriting_output={"title": OLD_TITLE, "main_body": body, "ending": None},
        research_output=M2865["research"], intelligence_output=M2865["intelligence"],
        quality_output={"passed": True}, fact_safety_status=None,
    )
    gate_pass = WorkerGateResult(
        False, False, False, False, {"event_id": str(event.id), "final_publication_block": False},
        {"gate_version": "1", "execution_id": "fixture-gate-pass", "structured_result": {
            "FACTUAL_SAFETY": "PASS", "HEADLINE_SAFETY": "PASS", "BODY_SAFETY": "PASS", "UNSUPPORTED_CLAIMS": []}},
    )
    notify = AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<b>ok</b>", sent=True, message_id=77))
    with (
        patch("worker.content_cycle.evaluate_origin_before_generation",
              new=AsyncMock(return_value=SimpleNamespace(applies=False, allowed=True))),
        patch("worker.content_cycle.check_update_would_fail_closed",
              new=AsyncMock(return_value=SimpleNamespace(would_fail_closed=False))),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.evaluate_worker_publication_gate", new=AsyncMock(return_value=gate_pass)),
        patch("worker.content_cycle.send_editorial_card", new=notify),
    ):
        result = await run_content_cycle(AsyncMock(), AsyncMock(), session_factory=factory,
                                         event_ids_override=[event.id], precomputed_outcomes={event.id: outcome})
    try:
        assert notify.await_count == int(expect_send)
        assert result.factual_gate_pass == 1  # factual safety verdict untouched
        assert result.editorial_usefulness_block == int(not expect_send)
        async with factory() as session:
            lineage = (await session.get(KageContentLineageAudit, task.id)).audit
            persisted_task = await session.get(EditorialTask, task.id)
            persisted_draft = await session.get(ContentDraft, draft_id)
            receipts = await session.scalar(select(func.count()).select_from(StoryTelegramDelivery)
                                            .where(StoryTelegramDelivery.content_draft_id == draft_id))
        assert lineage["publication_factual_gate"]["execution_id"] == "fixture-gate-pass"
        assert lineage["stages"]["editorial_usefulness"]["passed"] is expect_send
        status = persisted_task.workflow["publication_outcome"]["status"]
        if expect_send:
            assert status == "DELIVERED" and persisted_draft.status == "draft"
        else:
            assert status == "BLOCKED_EDITORIAL_USEFULNESS" and status != "BLOCKED_FACTUAL_GATE"
            assert persisted_task.workflow["publication_outcome"]["reason"] == "body_adds_no_supported_fact_beyond_headline"
            assert persisted_draft.status == "draft_blocked_editorial_usefulness" and receipts == 0
    finally:
        async with factory() as session:
            await session.execute(delete(KageContentLineageAudit).where(KageContentLineageAudit.task_id == task.id))
            await session.commit()
