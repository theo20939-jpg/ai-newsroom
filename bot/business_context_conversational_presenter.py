"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1 UX CORRECTION: translates a `BusinessContextProposal`'s
internal `proposed_change_set` (entity_type/slug/structured_context - the exact same operations
`bot/business_context_formatting.py::render_proposal_preview()` renders as a numbered technical
dump) into natural, conversational Russian - the ONLY Founder-facing surface this phase changes.

Deliberately a pure, deterministic function of the already-parsed `proposed_change_set` - NOT a
second LLM call, NOT a new parser, NOT a new agent. The real extraction already happened; this
module only decides how to SAY what was already decided. Reusing `render_proposal_preview()`
itself remains the debug/details view (bot/handlers/business_context.py wires a "⚙️ Детали"
button to it) - internal field/entity names are never hidden from someone who explicitly asks,
only from the default conversational surface.

Never invents wording the underlying data doesn't support: a fact's own `note` (the LLM's
already-natural phrasing of the message's own approximate timing, per prompts/
business_context_parser/v4.yaml) is used verbatim, never re-interpreted into an invented precise
date - if there is no note, this module says the fact is "запланировано"/"подтверждено"/etc.
without fabricating a schedule."""
from __future__ import annotations

from typing import Any

from database.models.business_context_proposal import BusinessContextProposal


def _feature_sentence(feature_name: str, state: str, note: str | None) -> str:
    note_text = note.strip() if isinstance(note, str) and note.strip() else None
    if state == "confirmed":
        return f"«{feature_name}» — {note_text}" if note_text else f"«{feature_name}» — уже действует."
    if state == "planned":
        return f"«{feature_name}» — {note_text}" if note_text else f"«{feature_name}» — запланировано."
    if state == "undecided":
        return f"«{feature_name}» — пока не решили." + (f" {note_text}" if note_text else "")
    return f"«{feature_name}»." + (f" {note_text}" if note_text else "")


def _describe_structured_context(ctx: dict[str, Any]) -> tuple[list[str], bool]:
    """Returns (sentences, has_approximate_note) - `has_approximate_note` drives the trailing
    "срок(и) пока считаю ориентировочным(и)" line, since `note` is where the schema puts a
    message's own approximate wording (see v4.yaml's own field description)."""
    notes: dict[str, str] = ctx.get("feature_notes") or {}
    undecided_names: dict[str, str] = ctx.get("undecided_display_names") or {}
    sentences: list[str] = []
    has_note = False

    for name in ctx.get("current_features_add") or []:
        note = notes.get(name)
        sentences.append(_feature_sentence(name, "confirmed", note))
        has_note = has_note or bool(note)
    for name in ctx.get("planned_features_add") or []:
        note = notes.get(name)
        sentences.append(_feature_sentence(name, "planned", note))
        has_note = has_note or bool(note)
    for key in ctx.get("undecided_facts_add") or []:
        display_name = undecided_names.get(key, key)
        note = notes.get(key)
        sentences.append(_feature_sentence(display_name, "undecided", note))

    return sentences, has_note


def render_conversational_proposal_preview(proposal: BusinessContextProposal) -> str:
    """The default Founder-facing preview for a plain-text/Director-originated proposal - see
    `bot/handlers/business_context.py` for where this replaces `render_proposal_preview()` (slash
    commands keep the technical view, unchanged)."""
    change_set: list[dict[str, Any]] = proposal.proposed_change_set or []
    product_names: dict[str, str] = {
        op["slug"]: op["name"] for op in change_set if op.get("entity_type") == "product"
    }

    product_facts: dict[str, list[str]] = {}
    extra_lines: list[str] = []
    has_approximate_note = False

    for op in change_set:
        entity_type = op.get("entity_type")
        if entity_type == "product_context_version":
            product_slug = op.get("product_slug", "")
            name = product_names.get(product_slug, product_slug)
            sentences, approx = _describe_structured_context(op.get("structured_context") or {})
            if sentences:
                product_facts.setdefault(name, []).extend(sentences)
            has_approximate_note = has_approximate_note or approx
        elif entity_type == "campaign":
            name = product_names.get(op.get("product_slug", ""), op.get("product_slug", ""))
            extra_lines.append(f"Отдельно завожу маркетинговую кампанию «{op.get('name')}» для {name}.")
        elif entity_type == "campaign_milestone":
            name = product_names.get(op.get("product_slug", ""), op.get("product_slug", ""))
            extra_lines.append(f"Отмечаю launch-ориентир по {name}: «{op.get('title')}».")
        elif entity_type == "strategic_directive":
            extra_lines.append(f"Записываю как указание: {op.get('instruction')}")
        elif entity_type == "claim_policy":
            name = product_names.get(op.get("product_slug", ""), op.get("product_slug", ""))
            extra_lines.append(f"Фиксирую заявление по {name}: «{op.get('claim_text')}».")

    lines = ["Понял."]
    if len(product_facts) == 1:
        (facts,) = product_facts.values()
        lines.append("")
        lines.extend(facts)
    else:
        for name, facts in product_facts.items():
            lines.append("")
            lines.append(f"Для {name}:")
            lines.extend(facts)

    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)

    if has_approximate_note:
        lines.append("")
        lines.append("Срок" + ("и" if len(product_facts) > 1 else "") + " пока считаю ориентировочны" + ("ми" if len(product_facts) > 1 else "м") + ".")

    lines.append("")
    lines.append("Всё верно?")
    return "\n".join(lines)


def render_conversational_confirmation(proposal: BusinessContextProposal) -> str:
    """After confirm_proposal() actually writes canonical Product Truth - one short line, never a
    dump of what was stored (that remains available via the "⚙️ Детали" debug view)."""
    change_set: list[dict[str, Any]] = proposal.proposed_change_set or []
    has_campaign = any(op.get("entity_type") in ("campaign", "campaign_milestone") for op in change_set)
    lines = ["Готово, зафиксировал."]
    if not has_campaign and any(op.get("entity_type") == "product_context_version" for op in change_set):
        lines.append("Маркетинговые кампании по этому не заводил — ты о них не говорил.")
    return "\n".join(lines)
