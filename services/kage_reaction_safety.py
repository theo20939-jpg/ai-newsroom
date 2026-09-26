"""Conservative, evidence-gated safety checks for KAGE reaction-bearing drafts.

These checks enforce explicit take boundaries and wording-sensitive headline
qualifiers. They do not score style or require an editorial reaction. Quality's
semantic review remains responsible for claims outside these narrow patterns.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from services.kage_evidence_first import editorial_take_contract, minimum_story_contract, select_evidence_cards


def _copy_text(draft: Mapping[str, Any]) -> tuple[str, str]:
    title = str(draft.get("title") or "")
    body = "\n".join(str(draft.get(key) or "") for key in ("main_body", "ending"))
    return title.casefold(), body.casefold()


def reaction_safety_issues(
    draft: Mapping[str, Any], research: Mapping[str, Any], intelligence: Mapping[str, Any],
    *, source_headline: str = "",
) -> list[str]:
    """Reject supported-boundary violations without treating opinion as fact.

    Each check is conditional on the selected evidence or take boundary. It does
    not import omitted article details or demand optional facts. The same
    contract generator is used for writer, Quality and this local audit.
    """
    selected, _, _ = select_evidence_cards(research, intelligence, source_headline=source_headline)
    evidence = " ".join(card["fact"] for card in selected).casefold()
    story = minimum_story_contract(research, intelligence, source_headline=source_headline)
    selected_by_id = {card["id"]: card["fact"] for card in selected}
    core = " ".join(selected_by_id[card["id"]] for card in story["core_facts"]).casefold()
    take = editorial_take_contract(research, intelligence, source_headline=source_headline)
    boundary = " ".join(take["reaction_boundary"]).casefold()
    title, body = _copy_text(draft)
    full = f"{title}\n{body}"
    issues: list[str] = []

    # A headline is independently read: a later body qualifier does not fix it.
    if ("дополнительн" in core and "контекст" in core
            and "акцент" in title and re.search(r"gemini|уведомлен", title)
            and not re.search(r"контекст|дополнительн", title)):
        issues.append("HEADLINE_SCOPE: contextual notification qualifier absent from accent headline")
    if (re.search(r"уволен\w*\s+или\s+отстран", core)
            and re.search(r"увол|увольн", title) and not re.search(r"отстран|снят", title)):
        issues.append("HEADLINE_OUTCOME: dismissal-only headline narrows dismissed-or-removed outcome")

    # Only activate these checks where the upstream contract expressly forbids
    # the proposition. A subjective judgment such as 'красиво' is never matched.
    if "replaced hardware" in boundary and not re.search(r"замен\w*.{0,35}(?:пульт|контроллер)", evidence):
        if (re.search(r"замен\w*.{0,35}(?:пульт|контроллер)", full)
                or re.search(r"вместо\s+(?:\w+\s+){0,3}(?:пульта|контроллера)", full)
                or re.search(r"(?:пульт|контроллер).{0,30}(?:больше\s+не\s+нужен|не\s+понадобился)", full)):
            issues.append("REACTION_BOUNDARY_REPLACEMENT: unevidenced replacement controller")
    if "not an embedded episode" in boundary and "ссылк" in evidence:
        if (re.search(r"истори\w*.{0,65}(?:буквально\s+)?(?:в|на)\s+(?:\w+\s+){0,3}панел", full)
                or re.search(r"(?:эпизод|подкаст|истори\w*).{0,45}(?:встроен|внутри\s+карточки|прямо\s+в\s+карточке)", full)):
            issues.append("REACTION_BOUNDARY_EMBEDDING: history presented as content in link panel")
    if "not automatic mind-reading or removal" in boundary and not re.search(r"контент\s+не\s+исчез", evidence):
        if (re.search(r"контент\s+не\s+(?:исчез\w*|удал\w*)", full)
                or re.search(r"(?:песни|треки|музыка).{0,18}(?:никуда\s+не\s+денут\w*|остан\w*|не\s+удал\w*)", full)):
            issues.append("REACTION_BOUNDARY_PERSISTENCE: unsupported content-persistence assurance")

    # Grammar is a separate quality remit; this does not relabel it as misinformation.
    if re.search(r"у\s+устройств\w*\s+средн\w*\s+оценк", full):
        issues.append("LANGUAGE_AMBIGUITY: rating construction is grammatically ambiguous")
    return issues
