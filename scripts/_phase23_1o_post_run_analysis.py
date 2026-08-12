"""Phase 23.1O post-run analysis - read-only reconstruction of every meaningful candidate and
every delivered post from the real, already-persisted pipeline data written during the 2-hour
canary (scripts/_phase23_1o_2h_combined_news_canary.py). No writes, no Telegram calls, no paid
API calls - only SELECT queries against the real dev database, scoped to the canary's own
[CANARY_START, CANARY_END] window, plus the real `_classify_event_for_router_treatment()` reused
directly (read-only) to recompute treatment for every candidate, not just delivered ones.
"""
import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select

from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.content_draft import ContentDraft
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.models.story_link import NewsEventStoryLink
from database.models.ai_execution import AIExecution
from database.session import async_session_factory
from services.image_persistence import get_editorial_image_candidates
from services.news_telegram_presentation import is_v8_family_output, render_v81_news_card_html
from worker.content_cycle import _classify_event_for_router_treatment, _extract_scoring_result, _extract_intelligence_result
from core.config import settings

CANARY_START = datetime.fromisoformat("2026-08-11T14:52:55.524863+00:00")
CANARY_END = datetime.fromisoformat("2026-08-11T16:53:03.484971+00:00")


def _workflow_steps(task: EditorialTask) -> dict:
    return {s.get("step_name"): s.get("result") for s in (task.workflow or {}).get("step_results", [])}


async def main() -> None:
    async with async_session_factory() as session:
        # ---- every NEWS_ANALYSIS task completed inside the window ----
        na_tasks = (
            await session.execute(
                select(EditorialTask).where(
                    EditorialTask.workflow["workflow_name"].as_string() == "NEWS_ANALYSIS",
                    EditorialTask.status == TaskStatus.COMPLETED,
                    EditorialTask.updated_at >= CANARY_START,
                    EditorialTask.updated_at <= CANARY_END,
                )
            )
        ).scalars().all()

        candidates = []
        for task in na_tasks:
            event = await session.get(NewsEvent, task.event_id)
            source = await session.get(NewsSource, event.source_id) if event else None
            steps = _workflow_steps(task)
            score = _extract_scoring_result(task.workflow)
            significance, recommendation = _extract_intelligence_result(task.workflow)

            # does a CONTENT_GENERATION task already exist for this event? (real dup-resend guard)
            cg_task = (
                await session.execute(
                    select(EditorialTask).where(
                        EditorialTask.event_id == task.event_id,
                        EditorialTask.workflow["workflow_name"].as_string() == "CONTENT_GENERATION",
                    )
                )
            ).scalar_one_or_none()

            treatment_decision = await _classify_event_for_router_treatment(session, task.event_id)

            story_link = await session.get(NewsEventStoryLink, task.event_id)

            candidates.append({
                "event_id": str(task.event_id),
                "na_task_id": str(task.id),
                "na_task_updated_at": str(task.updated_at),
                "source_name": source.name if source else None,
                "source_type": source.type.value if source and source.type else None,
                "original_title": event.title if event else None,
                "url": event.url if event else None,
                "category": event.category.value if event and event.category else None,
                "collected_at": str(event.collected_at) if event else None,
                "published_at": str(event.published_at) if event else None,
                "score": score,
                "intelligence_significance": significance,
                "intelligence_recommendation": recommendation,
                "min_score_threshold": settings.content_generation_min_score,
                "passes_min_score": bool(score is not None and score >= settings.content_generation_min_score),
                "has_content_generation_task": cg_task is not None,
                "content_generation_task_status": cg_task.status.value if cg_task else None,
                "treatment": treatment_decision.treatment,
                "treatment_reason": treatment_decision.reason,
                "treatment_human_review_required": treatment_decision.human_review_required,
                "story_id": str(story_link.story_id) if story_link else None,
                "story_match_type": story_link.match_type if story_link else None,
                "research_status": "present" if steps.get("research") else "missing",
            })

        # ---- every CONTENT_GENERATION task created inside the window ----
        cg_tasks = (
            await session.execute(
                select(EditorialTask).where(
                    EditorialTask.workflow["workflow_name"].as_string() == "CONTENT_GENERATION",
                    EditorialTask.created_at >= CANARY_START,
                    EditorialTask.created_at <= CANARY_END,
                )
            )
        ).scalars().all()

        delivered_posts = []
        content_gen_records = []
        for task in cg_tasks:
            event = await session.get(NewsEvent, task.event_id)
            source = await session.get(NewsSource, event.source_id) if event else None
            steps = _workflow_steps(task)
            copywriting_output = steps.get("copywriting")
            fact_safety = steps.get("quality")
            draft = (
                await session.execute(select(ContentDraft).where(ContentDraft.task_id == task.id))
            ).scalar_one_or_none()

            treatment_decision = await _classify_event_for_router_treatment(session, task.event_id)
            story_link = await session.get(NewsEventStoryLink, task.event_id)

            v8_family = bool(copywriting_output) and is_v8_family_output(copywriting_output)
            rendered_html = (
                render_v81_news_card_html(copywriting_output, treatment=treatment_decision.treatment)
                if copywriting_output and v8_family else None
            )
            main_body = copywriting_output.get("main_body") if copywriting_output else None
            ending = copywriting_output.get("ending") if copywriting_output else None

            image_domain = None
            image_url = None
            image_candidate_count = 0
            if draft is not None:
                image_candidates = await get_editorial_image_candidates(session, content_draft_id=draft.id)
                image_candidate_count = len(image_candidates)
                if image_candidates and image_candidates[0].source_url:
                    image_domain = urlparse(image_candidates[0].source_url).netloc or None
                    image_url = image_candidates[0].source_url

            event_cost = (
                await session.execute(
                    select(AIExecution).where(AIExecution.event_id == task.event_id)
                )
            ).scalars().all()
            total_cost = sum(float(e.cost or 0) for e in event_cost)

            record = {
                "event_id": str(task.event_id),
                "cg_task_id": str(task.id),
                "cg_task_status": task.status.value,
                "cg_task_created_at": str(task.created_at),
                "source_name": source.name if source else None,
                "source_url": event.url if event else None,
                "original_title": event.title if event else None,
                "category": event.category.value if event and event.category else None,
                "treatment": treatment_decision.treatment,
                "treatment_reason": treatment_decision.reason,
                "story_id": str(story_link.story_id) if story_link else None,
                "story_match_type": story_link.match_type if story_link else None,
                "headline": copywriting_output.get("title") if copywriting_output else None,
                "main_body": main_body,
                "ending": ending,
                "main_body_paragraph_count": (main_body.count(chr(10) + chr(10)) + 1) if main_body else None,
                "story_led": copywriting_output.get("story_led") if copywriting_output else None,
                "viral_potential": copywriting_output.get("viral_potential") if copywriting_output else None,
                "meme_potential": copywriting_output.get("meme_potential") if copywriting_output else None,
                "fact_safety": fact_safety,
                "image_candidate_count": image_candidate_count,
                "image_domain": image_domain,
                "image_url": image_url,
                "rendered_html": rendered_html,
                "content_draft_id": str(draft.id) if draft else None,
                "incremental_cost_usd": total_cost,
                "workflow_failure": (task.workflow or {}).get("failure"),
            }
            content_gen_records.append(record)

        errors_in_window = (
            await session.execute(
                select(EditorialTask).where(
                    EditorialTask.updated_at >= CANARY_START,
                    EditorialTask.updated_at <= CANARY_END,
                    EditorialTask.status == TaskStatus.FAILED,
                )
            )
        ).scalars().all()

        ai_executions_window = (
            await session.execute(
                select(AIExecution).where(
                    AIExecution.created_at >= CANARY_START,
                    AIExecution.created_at <= CANARY_END,
                )
            )
        ).scalars().all()
        cost_by_capability: dict[str, float] = {}
        cost_by_model: dict[str, float] = {}
        retry_count = 0
        for e in ai_executions_window:
            cost_by_capability[e.capability] = cost_by_capability.get(e.capability, 0) + float(e.cost or 0)
            cost_by_model[e.model or "unknown"] = cost_by_model.get(e.model or "unknown", 0) + float(e.cost or 0)
            if (e.retry_number or 0) > 0:
                retry_count += 1

    with open("scripts/_phase23_1o_post_run_analysis.json", "w", encoding="utf-8") as f:
        json.dump({
            "canary_start": str(CANARY_START), "canary_end": str(CANARY_END),
            "news_analysis_candidates_count": len(candidates),
            "content_generation_tasks_count": len(cg_tasks),
            "failed_editorial_tasks_in_window": len(errors_in_window),
            "failed_task_ids": [str(t.id) for t in errors_in_window],
            "ai_executions_in_window": len(ai_executions_window),
            "cost_by_capability": cost_by_capability,
            "cost_by_model": cost_by_model,
            "retry_count": retry_count,
            "candidates": candidates,
            "content_generation_records": content_gen_records,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"wrote scripts/_phase23_1o_post_run_analysis.json : "
          f"{len(candidates)} NEWS_ANALYSIS candidates, {len(cg_tasks)} CONTENT_GENERATION tasks, "
          f"{len(errors_in_window)} failed tasks, {len(ai_executions_window)} ai_executions")


if __name__ == "__main__":
    asyncio.run(main())
