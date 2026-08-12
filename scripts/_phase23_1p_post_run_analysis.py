"""Phase 23.1P post-run analysis - read-only. Reconstructs Story Memory V2 diagnostics (delta/
confidence/would_suppress) by RE-RUNNING the same deterministic functions against the real,
already-persisted NewsEventStoryLink/Story state (V1's match_type/match_score ARE persisted; V2's
outputs were logged only, not persisted, and the plain-text log formatter does not render `extra`
fields - re-deriving them here is bit-for-bit identical to what was logged, since these are pure
functions of already-persisted state). No writes, no Telegram calls, no paid API calls.
"""
import asyncio
import json
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import select

from database.models.ai_execution import AIExecution
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.session import async_session_factory
from services.article_cleaning import clean_extracted_text
from services.image_persistence import get_editorial_image_candidates
from services.news_telegram_presentation import is_v8_family_output, render_v81_news_card_html
from services.story_confidence import compute_confidence_band
from services.story_delta_engine import compute_story_delta, gate_delta_by_identity
from services.story_duplicate_guard import should_block_duplicate_delivery
from services.story_memory import (
    NEW_STORY, RELATED_STORY, SEMANTIC_DUPLICATE, STORY_UPDATE, SUPPORTING_SOURCE, UNCERTAIN_MATCH,
)
from services.story_suppression import compute_would_suppress
from services.story_telegram_delivery import get_root_delivery
from worker.content_cycle import (
    _classify_event_for_router_treatment, _extract_intelligence_result, _extract_scoring_result,
)

CANARY_START = datetime.fromisoformat("2026-08-11T18:17:23.461213+00:00")
CANARY_END = datetime.fromisoformat("2026-08-11T19:54:04.939595+00:00")

_CONFIDENT_OUTCOMES = {STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE, UNCERTAIN_MATCH}


def _workflow_steps(task: EditorialTask) -> dict:
    return {s.get("step_name"): s.get("result") for s in (task.workflow or {}).get("step_results", [])}


async def main() -> None:
    async with async_session_factory() as session:
        links = (
            await session.execute(
                select(NewsEventStoryLink).where(
                    NewsEventStoryLink.created_at >= CANARY_START, NewsEventStoryLink.created_at <= CANARY_END,
                )
            )
        ).scalars().all()

        story_memory_records = []
        for link in links:
            event = await session.get(NewsEvent, link.news_event_id)
            source = await session.get(NewsSource, event.source_id) if event else None
            story = await session.get(Story, link.story_id)

            record = {
                "event_id": str(link.news_event_id),
                "title": event.title if event else None,
                "source": source.name if source else None,
                "story_id": str(link.story_id),
                "story_root_title": story.title if story else None,
                "match_type": link.match_type,
                "match_score": link.match_score,
                "created_at": str(link.created_at),
            }
            if link.match_type in _CONFIDENT_OUTCOMES:
                try:
                    delta = await compute_story_delta(
                        session, new_title=event.title, story_id=link.story_id, exclude_event_id=link.news_event_id,
                    )
                    delta = gate_delta_by_identity(delta, has_distinctive_shared_entity=True)  # already gated at match time for these 4 outcomes
                    confidence_band = compute_confidence_band(link.match_score)
                    would_suppress = compute_would_suppress(
                        match_type=link.match_type, confidence_band=confidence_band, delta_classification=delta.classification,
                    )
                    record.update({
                        "confidence_band": confidence_band, "delta_classification": delta.classification,
                        "delta_reason": delta.reason, "new_material_claims": delta.new_material_claims,
                        "would_suppress_v2": would_suppress,
                        "would_block_v1_only": should_block_duplicate_delivery(link.match_type, True),
                    })
                except Exception as exc:
                    record["v2_error"] = repr(exc)

                # Was this event actually delivered, and if so, was a prior root delivery already blocking it?
                root_delivery = await get_root_delivery(session, link.story_id)
                record["prior_root_delivery_existed_at_check_time"] = root_delivery is not None
            story_memory_records.append(record)

        # ---- delivered posts in the window (CONTENT_GENERATION tasks created in window) ----
        cg_tasks = (
            await session.execute(
                select(EditorialTask).where(
                    EditorialTask.workflow["workflow_name"].as_string() == "CONTENT_GENERATION",
                    EditorialTask.created_at >= CANARY_START, EditorialTask.created_at <= CANARY_END,
                )
            )
        ).scalars().all()

        delivered_records = []
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
            link = await session.get(NewsEventStoryLink, task.event_id)

            v8_family = bool(copywriting_output) and is_v8_family_output(copywriting_output)
            rendered_html = (
                render_v81_news_card_html(copywriting_output, treatment=treatment_decision.treatment)
                if copywriting_output and v8_family else None
            )
            main_body = copywriting_output.get("main_body") if copywriting_output else None
            ending = copywriting_output.get("ending") if copywriting_output else None
            quote_field = copywriting_output.get("quote") if copywriting_output else None

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
                await session.execute(select(AIExecution).where(AIExecution.event_id == task.event_id))
            ).scalars().all()
            total_cost = sum(float(e.cost or 0) for e in event_cost)

            # quote-source-text availability, recomputed the same way capabilities/executor.py does
            from database.models.news_event_article_acquisition import NewsEventArticleAcquisition
            acquisition = await session.get(NewsEventArticleAcquisition, task.event_id)
            quote_source_available = False
            quote_source_char_count = 0
            if acquisition is not None and acquisition.effective_completeness_status in ("FULL_TEXT", "PARTIAL_TEXT") and acquisition.raw_extracted_text:
                quote_source_available = True
                cleaning = clean_extracted_text(acquisition.raw_extracted_text, title=event.title if event else "")
                quote_source_char_count = len(cleaning.cleaned_text)

            delivered_records.append({
                "event_id": str(task.event_id),
                "cg_task_id": str(task.id),
                "cg_task_created_at": str(task.created_at),
                "source_name": source.name if source else None,
                "source_url": event.url if event else None,
                "original_title": event.title if event else None,
                "category": event.category.value if event and event.category else None,
                "treatment": treatment_decision.treatment,
                "treatment_reason": treatment_decision.reason,
                "story_id": str(link.story_id) if link else None,
                "story_match_type": link.match_type if link else None,
                "headline": copywriting_output.get("title") if copywriting_output else None,
                "main_body": main_body,
                "ending": ending,
                "story_led": copywriting_output.get("story_led") if copywriting_output else None,
                "viral_potential": copywriting_output.get("viral_potential") if copywriting_output else None,
                "meme_potential": copywriting_output.get("meme_potential") if copywriting_output else None,
                "quote": quote_field,
                "quote_source_available": quote_source_available,
                "quote_source_char_count": quote_source_char_count,
                "fact_safety": fact_safety,
                "image_candidate_count": image_candidate_count,
                "image_domain": image_domain,
                "image_url": image_url,
                "rendered_html": rendered_html,
                "content_draft_id": str(draft.id) if draft else None,
                "incremental_cost_usd": total_cost,
                "intelligence_significance": _extract_intelligence_result(task.workflow)[0],
                "intelligence_recommendation": _extract_intelligence_result(task.workflow)[1],
                "score": _extract_scoring_result(task.workflow),
            })

        # ---- NEWS_ANALYSIS candidates in window (for skip-sample / broader picture) ----
        na_tasks = (
            await session.execute(
                select(EditorialTask).where(
                    EditorialTask.workflow["workflow_name"].as_string() == "NEWS_ANALYSIS",
                    EditorialTask.status == TaskStatus.COMPLETED,
                    EditorialTask.updated_at >= CANARY_START, EditorialTask.updated_at <= CANARY_END,
                )
            )
        ).scalars().all()

        failed_tasks = (
            await session.execute(
                select(EditorialTask).where(
                    EditorialTask.updated_at >= CANARY_START, EditorialTask.updated_at <= CANARY_END,
                    EditorialTask.status == TaskStatus.FAILED,
                )
            )
        ).scalars().all()

        ai_executions_window = (
            await session.execute(
                select(AIExecution).where(
                    AIExecution.created_at >= CANARY_START, AIExecution.created_at <= CANARY_END,
                )
            )
        ).scalars().all()
        cost_by_capability: dict[str, float] = {}
        retry_count = 0
        for e in ai_executions_window:
            cost_by_capability[e.capability] = cost_by_capability.get(e.capability, 0) + float(e.cost or 0)
            if (e.retry_number or 0) > 0:
                retry_count += 1

    with open("scripts/_phase23_1p_post_run_analysis.json", "w", encoding="utf-8") as f:
        json.dump({
            "canary_start": str(CANARY_START), "canary_end": str(CANARY_END),
            "story_memory_links_count": len(links),
            "story_memory_records": story_memory_records,
            "delivered_records": delivered_records,
            "na_candidates_count": len(na_tasks),
            "failed_tasks_count": len(failed_tasks),
            "failed_task_ids": [str(t.id) for t in failed_tasks],
            "ai_executions_count": len(ai_executions_window),
            "cost_by_capability": cost_by_capability,
            "retry_count": retry_count,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(
        f"wrote scripts/_phase23_1p_post_run_analysis.json: {len(links)} story links, "
        f"{len(cg_tasks)} delivered, {len(na_tasks)} NA candidates, {len(failed_tasks)} failed"
    )


if __name__ == "__main__":
    asyncio.run(main())
