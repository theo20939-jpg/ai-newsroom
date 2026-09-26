"""Isolated publication-factual contract and deterministic publication decision.

The gate is not enabled in the live workflow. A later authorized validation can
execute its request; Quality 9.2 results are deliberately absent from the
publication decision. Malformed gate output fails closed.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from integrations.prompts.protocol import RenderedPrompt
from services.kage_evidence_first import (
    editorial_take_contract,
    minimum_story_contract,
    select_evidence_cards,
)
from services.kage_reaction_safety import reaction_safety_issues

INPUT_KEYS = frozenset({
    "SELECTED_PREMISE", "CORE_FACTS", "OPTIONAL_FACTS", "MATERIAL_QUALIFIERS",
    "EDITORIAL_PRESENCE_TARGET", "REACTION_TYPE", "REACTION_BASIS",
    "REACTION_BOUNDARY", "GENERATED_HEADLINE", "GENERATED_BODY",
})
ISSUE_TYPES = frozenset({"UNSUPPORTED", "AMBIGUOUS_MATERIAL"})
VIOLATED_DIMENSIONS = frozenset({
    "MECHANISM", "SCOPE", "ACTOR", "CHRONOLOGY", "CAUSALITY", "CERTAINTY",
    "COMPARISON_BASE", "QUANTITY", "OUTCOME", "AVAILABILITY",
    "TECHNICAL_BEHAVIOR", "PRODUCT_BEHAVIOR", "REMEDIATION",
    "PREREQUISITE", "REPLACEMENT", "PERSISTENCE", "OTHER",
})
DIAGNOSTICS = frozenset({"TARGET_MET", "UNDERDELIVERED", "OVERDONE", "NOT_REQUIRED"})


def build_gate_input(
    *, draft: Mapping[str, Any], research: Mapping[str, Any],
    intelligence: Mapping[str, Any], source_headline: str = "",
) -> dict[str, Any]:
    """Use the already selected cards; never send source article or prior drafts."""
    story = minimum_story_contract(research, intelligence, source_headline=source_headline)
    take = editorial_take_contract(research, intelligence, source_headline=source_headline)
    cards, _, _ = select_evidence_cards(research, intelligence, source_headline=source_headline)
    by_id = {card["id"]: card["fact"] for card in cards}
    headline, main_body = draft.get("title"), draft.get("main_body")
    ending = draft.get("ending")
    if not isinstance(headline, str) or not headline.strip():
        raise ValueError("generated headline missing")
    if not isinstance(main_body, str) or not main_body.strip():
        raise ValueError("generated body missing")
    if ending is not None and not isinstance(ending, str):
        raise ValueError("ending must be text or null")
    body = main_body if not ending or not ending.strip() else f"{main_body}\n\n{ending}"
    result = {
        "SELECTED_PREMISE": story["selected_premise"],
        "CORE_FACTS": [{**item, "fact": by_id[item["id"]]} for item in story["core_facts"]],
        "OPTIONAL_FACTS": [{**item, "fact": by_id[item["id"]]} for item in story["optional_facts"]],
        "MATERIAL_QUALIFIERS": story["material_qualifiers"],
        "EDITORIAL_PRESENCE_TARGET": take["editorial_presence_target"],
        "REACTION_TYPE": take["reaction_type"],
        "REACTION_BASIS": take["reaction_basis"],
        "REACTION_BOUNDARY": take["reaction_boundary"],
        "GENERATED_HEADLINE": headline,
        "GENERATED_BODY": body,
    }
    if set(result) != INPUT_KEYS:
        raise RuntimeError("gate input shape drift")
    return result


def build_gate_request(
    gate_input: Mapping[str, Any], prompt: RenderedPrompt, *, model: str,
    provider: str | None = None, max_tokens: int = 1200,
    reasoning_effort: str | None = None,
) -> GenerateRequest:
    """Construct only; no provider call or budget mutation occurs here."""
    if set(gate_input) != INPUT_KEYS or prompt.name != "publication_factual_gate" or prompt.version != "1":
        raise ValueError("invalid factual-gate contract")
    system = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system)]),
            Message(role="user", content=[ContentPart(
                type="text", text="FACTUAL GATE INPUT:\n" + json.dumps(gate_input, ensure_ascii=False),
            )]),
        ],
        preferred_model=model,
        preferred_provider=provider,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        response_mode="json_schema",
        response_schema=prompt.output_schema,
    )


def validate_gate_output(output: Mapping[str, Any], gate_input: Mapping[str, Any]) -> None:
    """Validate structural coherence, not semantic entailment (the model's job)."""
    required = {"FACTUAL_SAFETY", "HEADLINE_SAFETY", "BODY_SAFETY",
                "UNSUPPORTED_CLAIMS", "EDITORIAL_OPINION_SPANS", "EDITORIAL_PRESENCE_DIAGNOSTIC"}
    if set(output) != required or any(output[k] not in ("PASS", "FAIL") for k in
                                     ("FACTUAL_SAFETY", "HEADLINE_SAFETY", "BODY_SAFETY")):
        raise ValueError("invalid factual-gate verdict shape")
    if output["EDITORIAL_PRESENCE_DIAGNOSTIC"] not in DIAGNOSTICS:
        raise ValueError("invalid editorial diagnostic")
    claims = output["UNSUPPORTED_CLAIMS"]
    if not isinstance(claims, list):
        raise ValueError("UNSUPPORTED_CLAIMS must be a list")
    all_text = gate_input["GENERATED_HEADLINE"] + "\n" + gate_input["GENERATED_BODY"]
    known_ids = {card["id"] for key in ("CORE_FACTS", "OPTIONAL_FACTS") for card in gate_input[key]}
    bad_headline = bad_body = False
    for claim in claims:
        if not isinstance(claim, Mapping) or set(claim) != {
            "span", "location", "issue_type", "violated_dimension", "supporting_fact_ids", "reason",
        }:
            raise ValueError("invalid claim shape")
        span, location = claim["span"], claim["location"]
        ids = claim["supporting_fact_ids"]
        if not isinstance(span, str) or not span.strip() or span not in all_text:
            raise ValueError("claim span not found in generated text")
        if location not in ("HEADLINE", "BODY") or span not in gate_input["GENERATED_" + location]:
            raise ValueError("claim location does not match span")
        if claim["issue_type"] not in ISSUE_TYPES or claim["violated_dimension"] not in VIOLATED_DIMENSIONS:
            raise ValueError("invalid claim classification")
        if not isinstance(claim["reason"], str) or not claim["reason"].strip():
            raise ValueError("claim reason missing")
        if not isinstance(ids, list) or any(type(fact_id) is not int or fact_id not in known_ids for fact_id in ids):
            raise ValueError("invalid supporting fact ID")
        bad_headline |= location == "HEADLINE"
        bad_body |= location == "BODY"
    opinions = output["EDITORIAL_OPINION_SPANS"]
    if not isinstance(opinions, list) or any(
        not isinstance(span, str) or not span.strip() or span not in all_text
        for span in opinions
    ):
        raise ValueError("invalid editorial opinion span")
    headline_fail = output["HEADLINE_SAFETY"] == "FAIL"
    body_fail = output["BODY_SAFETY"] == "FAIL"
    if headline_fail != bad_headline or body_fail != bad_body:
        raise ValueError("headline/body verdict inconsistent with claim list")
    if (output["FACTUAL_SAFETY"] == "FAIL") != (headline_fail or body_fail):
        raise ValueError("overall verdict inconsistent with claim list")


def publication_decision(
    gate_output: Mapping[str, Any] | None, gate_input: Mapping[str, Any],
    *, local_guard_issues: Sequence[str], quality_9_2_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Only factual safety and the existing local guard can block.

    Quality 9.2 is accepted as an argument solely to make its non-authoritative
    status explicit to callers; it is never read in this decision.
    """
    del quality_9_2_result
    if gate_output is None:
        return {"PUBLICATION_BLOCK": True, "reasons": ["FACTUAL_GATE_MISSING"]}
    try:
        validate_gate_output(gate_output, gate_input)
    except (ValueError, KeyError, TypeError) as exc:
        return {"PUBLICATION_BLOCK": True, "reasons": ["FACTUAL_GATE_INVALID: " + str(exc)]}
    reasons = []
    if any(gate_output[key] == "FAIL" for key in
           ("FACTUAL_SAFETY", "HEADLINE_SAFETY", "BODY_SAFETY")):
        reasons.append("FACTUAL_SAFETY_FAIL")
    if local_guard_issues:
        reasons.extend("LOCAL_GUARD: " + issue for issue in local_guard_issues)
    return {"PUBLICATION_BLOCK": bool(reasons), "reasons": reasons}


def decide_for_draft(
    *, gate_output: Mapping[str, Any] | None, draft: Mapping[str, Any],
    research: Mapping[str, Any], intelligence: Mapping[str, Any], source_headline: str = "",
    quality_9_2_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind the gate to the unchanged local guard; callers cannot omit it."""
    gate_input = build_gate_input(
        draft=draft, research=research, intelligence=intelligence,
        source_headline=source_headline,
    )
    guard_issues = reaction_safety_issues(
        draft, research, intelligence, source_headline=source_headline,
    )
    return publication_decision(
        gate_output, gate_input, local_guard_issues=guard_issues,
        quality_9_2_result=quality_9_2_result,
    )
