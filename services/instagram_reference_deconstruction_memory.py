"""INSTAGRAM-GROWTH-3, item 2/12: Reference Deconstruction persistence. `create_reference_
deconstruction()` re-validates through the ACCEPTED
services/instagram_reference_deconstruction.py::ReferenceDeconstruction dataclass before writing -
`must_not_copy` non-empty is never re-implemented here, only re-run. `ai_assisted=True` marks a row
produced by services/instagram_creative_director.py's AI-assisted analysis (item 12) - the human/
AI distinction is preserved on the row itself, never silently dropped."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_reference_deconstruction_memory import InstagramReferenceDeconstruction
from services.instagram_reference_deconstruction import ReferenceDeconstruction


async def create_reference_deconstruction(
    session: AsyncSession, *, reference_description: str, must_not_copy: list[str],
    hook_mechanics: str = "", pacing: str = "", scene_structure: str = "", narrative_progression: str = "",
    typography_behavior: str = "", visual_rhythm: str = "", editing_rhythm: str = "", cta_mechanics: str = "",
    interaction_pattern: str = "", what_appears_effective: list[str] | None = None,
    why_hypothesis_only: str | None = None, originality_constraints: list[str] | None = None,
    ai_assisted: bool = False,
) -> InstagramReferenceDeconstruction:
    # Reuses the accepted dataclass's own validation (raises ValueError if must_not_copy is empty)
    # - constructed purely to validate, never persisted itself.
    kwargs = dict(
        reference_description=reference_description, hook_mechanics=hook_mechanics, pacing=pacing,
        scene_structure=scene_structure, narrative_progression=narrative_progression,
        typography_behavior=typography_behavior, visual_rhythm=visual_rhythm, editing_rhythm=editing_rhythm,
        cta_mechanics=cta_mechanics, interaction_pattern=interaction_pattern,
        what_appears_effective=what_appears_effective or [], must_not_copy=must_not_copy,
        originality_constraints=originality_constraints or [],
    )
    if why_hypothesis_only is not None:
        kwargs["why_hypothesis_only"] = why_hypothesis_only
    ReferenceDeconstruction(**kwargs)  # type: ignore[arg-type]

    record = InstagramReferenceDeconstruction(
        reference_description=reference_description, hook_mechanics=hook_mechanics, pacing=pacing,
        scene_structure=scene_structure, narrative_progression=narrative_progression,
        typography_behavior=typography_behavior, visual_rhythm=visual_rhythm, editing_rhythm=editing_rhythm,
        cta_mechanics=cta_mechanics, interaction_pattern=interaction_pattern,
        what_appears_effective=what_appears_effective or [], why_hypothesis_only=why_hypothesis_only,
        must_not_copy=must_not_copy, originality_constraints=originality_constraints or [], ai_assisted=ai_assisted,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_reference_deconstruction(session: AsyncSession, record_id: UUID) -> InstagramReferenceDeconstruction | None:
    return await session.get(InstagramReferenceDeconstruction, record_id)


async def list_reference_deconstructions(session: AsyncSession) -> list[InstagramReferenceDeconstruction]:
    return list((await session.execute(select(InstagramReferenceDeconstruction))).scalars().all())
