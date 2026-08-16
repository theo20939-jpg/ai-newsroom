"""TELEGRAPH Checkpoint 2: pure Telegram-presentation tests - bot.telegraph_shortlist_formatting
and bot.keyboards.telegraph_shortlist. No database, no aiogram Bot/dispatcher, no network - every
input is a hand-built TelegraphTopicProposal dataclass instance (never persisted).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from database.models.telegraph_shortlist import TelegraphProposalStatus, TelegraphTopicProposal
from bot.keyboards.telegraph_shortlist import (
    build_shortlist_keyboard,
    encode_callback_data,
    parse_callback_data,
)
from bot.telegraph_shortlist_formatting import (
    SAFE_LIMIT,
    TelegraphShortlistTextTooLongError,
    render_no_topics_text,
    render_shortlist_message_text,
)


def _proposal(
    *, rank: int = 1, title: str = "OpenAI meniaet pravila igry", score: int = 87,
    status: TelegraphProposalStatus = TelegraphProposalStatus.PENDING,
    significance: float | None = 8.3, source_diversity: int = 4, event_count: int = 3,
    evidence_tier: str = "strong",
) -> TelegraphTopicProposal:
    return TelegraphTopicProposal(
        id=uuid4(), batch_id=uuid4(), story_id=uuid4(), rank=rank, topic_score=score,
        topic_title=title, rationale_snapshot="significance=8.3/10 (+33), news_score=87 (+22)",
        signals_snapshot={
            "normalized_significance": significance, "news_score": score,
            "evidence_tier": evidence_tier, "source_diversity_proxy": source_diversity,
            "event_count": event_count, "max_engagement_potential_score": 70.0,
        },
        status=status, decided_at=None, consumed_at=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------------------------
# Formatting (required tests 21-24)
# ---------------------------------------------------------------------------------------------


def test_21_renders_one_topic() -> None:
    text = render_shortlist_message_text([_proposal(rank=1)])
    assert "1." in text
    assert "TELEGRAPH" in text


def test_22_renders_five_topics() -> None:
    proposals = [_proposal(rank=i, title=f"Topic {i}") for i in range(1, 6)]
    text = render_shortlist_message_text(proposals)
    for i in range(1, 6):
        assert f"{i}. Topic {i}" in text


def test_23_handles_zero_topics_safely() -> None:
    text = render_shortlist_message_text([])
    assert text == render_no_topics_text()
    assert "TELEGRAPH" in text


def test_24_operator_facing_text_is_russian() -> None:
    text = render_shortlist_message_text([_proposal()])
    assert "Потенциал" in text
    assert "Источники" in text
    assert "Значимость" in text
    assert "темы для статьи" in text


def test_does_not_dump_raw_diagnostics() -> None:
    """The human-readable rationale must never be the raw Checkpoint 1 diagnostic string."""
    proposal = _proposal()
    text = render_shortlist_message_text([proposal])
    assert proposal.rationale_snapshot not in text
    assert "(+33)" not in text  # a component-score annotation is a diagnostic, not operator copy


def test_text_within_safe_limit_for_a_normal_batch() -> None:
    proposals = [_proposal(rank=i, title=f"Topic {i}") for i in range(1, 6)]
    text = render_shortlist_message_text(proposals)
    assert len(text) <= SAFE_LIMIT


def test_raises_rather_than_truncates_when_too_long() -> None:
    huge_title = "Тема " * 2000
    proposals = [_proposal(rank=1, title=huge_title)]
    try:
        render_shortlist_message_text(proposals)
        raised = False
    except TelegraphShortlistTextTooLongError:
        raised = True
    assert raised


def test_decided_proposals_render_visible_final_state() -> None:
    """Required test 28: a decided proposal's status line reflects its real outcome."""
    approved = _proposal(rank=1, status=TelegraphProposalStatus.APPROVED)
    rejected = _proposal(rank=2, status=TelegraphProposalStatus.REJECTED)
    pending = _proposal(rank=3, status=TelegraphProposalStatus.PENDING)
    text = render_shortlist_message_text([approved, rejected, pending])
    assert "✅ Одобрено" in text
    assert "❌ Отклонено" in text
    assert "⏳ Решение не принято" in text


# ---------------------------------------------------------------------------------------------
# Callback data / keyboard (required tests 25-27)
# ---------------------------------------------------------------------------------------------


def test_25_callback_data_within_telegram_limits() -> None:
    proposal_id = uuid4()
    data = encode_callback_data("approve", proposal_id)
    assert len(data.encode("utf-8")) <= 64


def test_26_proposal_ids_mapped_correctly_through_encode_decode() -> None:
    proposal_id = uuid4()
    data = encode_callback_data("reject", proposal_id)
    parsed = parse_callback_data(data)
    assert parsed == ("reject", proposal_id)


def test_27_approval_rejection_buttons_rendered_independently_per_topic() -> None:
    proposals = [_proposal(rank=i, title=f"Topic {i}") for i in range(1, 4)]
    keyboard = build_shortlist_keyboard(proposals)
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 3
    for row, proposal in zip(keyboard.inline_keyboard, proposals):
        assert len(row) == 2
        approve_action, approve_id = parse_callback_data(row[0].callback_data)  # type: ignore[arg-type]
        reject_action, reject_id = parse_callback_data(row[1].callback_data)  # type: ignore[arg-type]
        assert approve_action == "approve"
        assert reject_action == "reject"
        assert approve_id == reject_id == proposal.id


def test_keyboard_omits_buttons_for_decided_proposals() -> None:
    pending = _proposal(rank=1, status=TelegraphProposalStatus.PENDING)
    approved = _proposal(rank=2, status=TelegraphProposalStatus.APPROVED)
    keyboard = build_shortlist_keyboard([pending, approved])
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1  # only the pending row


def test_keyboard_is_none_once_every_proposal_is_decided() -> None:
    proposals = [
        _proposal(rank=1, status=TelegraphProposalStatus.APPROVED),
        _proposal(rank=2, status=TelegraphProposalStatus.REJECTED),
    ]
    assert build_shortlist_keyboard(proposals) is None


def test_button_text_never_exposes_the_internal_uuid() -> None:
    proposal = _proposal(rank=1)
    keyboard = build_shortlist_keyboard([proposal])
    assert keyboard is not None
    for row in keyboard.inline_keyboard:
        for button in row:
            assert str(proposal.id) not in (button.text or "")


def test_parse_rejects_malformed_and_wrong_prefix_payloads() -> None:
    assert parse_callback_data("not-a-payload") is None
    assert parse_callback_data("memeprev:approve:" + str(uuid4())) is None
    assert parse_callback_data("tgshort:approve:not-a-uuid") is None
    assert parse_callback_data("tgshort:delete:" + str(uuid4())) is None  # unknown action
