"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S7): EvidencePack construction.

`research_facts` (this codebase's existing, already-verified Research-capability output - a plain
list of strings, see `services.presentation_director._find_data_candidate`'s own docstring: "no
Research fact IDs exist in this schema") is the one real, available factual surface. This module's
job is narrow: wrap that list into addressable `EvidenceClaim`s with stable, deterministic ids, so
every later structured-content field can cite exactly which claim it came from
(`EvidenceClaim.claim_id`) instead of the pipeline silently re-reading raw prose later. It invents
no new fact-extraction of its own - each fact string becomes exactly one claim, verbatim.
"""
from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from services.editorial_pipeline.contracts import EvidenceClaim, EvidencePack

logger = logging.getLogger(__name__)


def _claim_id(news_event_id: UUID, index: int, text: str) -> str:
    """Deterministic, stable across re-builds of the same EvidencePack for the same event (never a
    fresh uuid4() per call - a claim_id must remain valid to reference across pipeline stages
    within one run, and reproducible for replay/test purposes)."""
    digest = hashlib.sha256(f"{news_event_id}:{index}:{text}".encode("utf-8")).hexdigest()[:12]
    return f"claim-{digest}"


def build_evidence_pack(
    *, news_event_id: UUID, story_id: UUID | None, source_url: str | None,
    research_facts: list[str] | None,
) -> EvidencePack:
    """Never fabricates a claim: `research_facts` entries that are not real, non-empty strings are
    dropped (matching `_find_data_candidate`'s own existing `isinstance(f, str)` filter), never
    coerced or padded to look complete."""
    facts = tuple(f for f in (research_facts or []) if isinstance(f, str) and f.strip())
    claims = tuple(
        EvidenceClaim(claim_id=_claim_id(news_event_id, i, fact), text=fact.strip(), source_url=source_url, raw_fact_text=fact)
        for i, fact in enumerate(facts)
    )
    pack = EvidencePack(
        news_event_id=news_event_id, story_id=story_id, claims=claims, source_url=source_url, research_facts=facts,
    )
    logger.info(
        "evidence_ready",
        extra={"news_event_id": str(news_event_id), "story_id": str(story_id) if story_id else None, "claim_count": len(claims)},
    )
    return pack
