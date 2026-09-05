"""INSTAGRAM-GROWTH-3, item 2/11: Original Format Lab persistence - moves
services/instagram_original_format_lab.py beyond contract-only. Both `create_experiment()` and
`update_experiment_status()` re-validate through the ACCEPTED
`services/instagram_original_format_lab.py::OriginalFormatExperiment` dataclass before writing -
the terminal-status-requires-result rule is never reimplemented here, only re-run. No automatic
adoption anywhere: `status` only ever changes via an explicit caller-supplied value."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_original_format_memory import InstagramOriginalFormatExperiment
from database.models.instagram_original_format_memory import OriginalFormatStatus as DBOriginalFormatStatus
from services.instagram_original_format_lab import OriginalFormatExperiment, OriginalFormatStatus


async def create_experiment(
    session: AsyncSession, *, idea: str, novelty_hypothesis: str, intentional_difference: str,
    target_objective: str, target_audience: str, format: str, test_conditions: str, success_criteria: str,
    evaluation_window: str, references: list[str] | None = None, confidence: float = 0.2,
) -> InstagramOriginalFormatExperiment:
    # Constructed purely to reuse the accepted dataclass's own validation (raises on a
    # contradiction the DB layer should never accept either) - never persisted itself.
    OriginalFormatExperiment(
        idea=idea, novelty_hypothesis=novelty_hypothesis, intentional_difference=intentional_difference,
        target_objective=target_objective, target_audience=target_audience, format=format,
        test_conditions=test_conditions, success_criteria=success_criteria, evaluation_window=evaluation_window,
        references=references or [], confidence=confidence,
    )
    experiment = InstagramOriginalFormatExperiment(
        idea=idea, novelty_hypothesis=novelty_hypothesis, intentional_difference=intentional_difference,
        target_objective=target_objective, target_audience=target_audience, format=format,
        test_conditions=test_conditions, success_criteria=success_criteria, evaluation_window=evaluation_window,
        references=references or [], confidence=confidence,
    )
    session.add(experiment)
    await session.commit()
    await session.refresh(experiment)
    return experiment


async def get_experiment(session: AsyncSession, experiment_id: UUID) -> InstagramOriginalFormatExperiment | None:
    return await session.get(InstagramOriginalFormatExperiment, experiment_id)


async def list_experiments(session: AsyncSession) -> list[InstagramOriginalFormatExperiment]:
    return list((await session.execute(select(InstagramOriginalFormatExperiment))).scalars().all())


async def update_experiment_status(
    session: AsyncSession, experiment_id: UUID, *, status: OriginalFormatStatus, result: str | None = None,
) -> InstagramOriginalFormatExperiment:
    experiment = await session.get(InstagramOriginalFormatExperiment, experiment_id)
    if experiment is None:
        raise ValueError(f"no InstagramOriginalFormatExperiment with id={experiment_id}")

    # Re-validates the SAME terminal-status-requires-result rule the accepted dataclass enforces -
    # raises before anything is written if the caller tries to close out a terminal status with no
    # recorded result.
    OriginalFormatExperiment(
        idea=experiment.idea, novelty_hypothesis=experiment.novelty_hypothesis,
        intentional_difference=experiment.intentional_difference, target_objective=experiment.target_objective,
        target_audience=experiment.target_audience or "", format=experiment.format,
        test_conditions=experiment.test_conditions or "", success_criteria=experiment.success_criteria or "",
        evaluation_window=experiment.evaluation_window or "", references=list(experiment.references or []),
        status=status, result=result, confidence=experiment.confidence,
    )

    experiment.status = DBOriginalFormatStatus(status.value)
    experiment.result = result
    await session.commit()
    await session.refresh(experiment)
    return experiment
