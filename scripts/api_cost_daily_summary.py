"""API cost optimization (Step 8 - cost observability). Read-only daily summary over the
`ai_executions` table (now populated going forward by capabilities/executor.py's own
cost-recording, wired in this same task - see docs/api_cost_optimization_report.md §8).

Reports, for a given UTC calendar day (default: today):
- total spend
- spend by workflow
- spend by capability
- spend by model
- cost per analyzed event (distinct NEWS_ANALYSIS event_id)
- cost per generated draft (distinct CONTENT_GENERATION task_id)
- cost per Telegram-delivered story (joined against real ContentDraft rows)

Never stores or prints a prompt or a secret - only the already-durable numeric/categorical
AIExecution columns.

Launch with:
    python -m scripts.api_cost_daily_summary [YYYY-MM-DD]
"""
import asyncio
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from database.models.ai_execution import AIExecution
from database.models.content_draft import ContentDraft
from database.session import async_session_factory


async def main() -> None:
    target_date = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(timezone.utc).date()
    start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    async with async_session_factory() as session:
        total_row = await session.execute(
            select(func.coalesce(func.sum(AIExecution.cost), 0), func.count())
            .where(AIExecution.created_at >= start, AIExecution.created_at < end)
        )
        total_cost, total_calls = total_row.one()

        by_workflow = (
            await session.execute(
                select(AIExecution.workflow_name, func.sum(AIExecution.cost), func.count())
                .where(AIExecution.created_at >= start, AIExecution.created_at < end)
                .group_by(AIExecution.workflow_name)
            )
        ).all()
        by_capability = (
            await session.execute(
                select(AIExecution.capability, func.sum(AIExecution.cost), func.count())
                .where(AIExecution.created_at >= start, AIExecution.created_at < end)
                .group_by(AIExecution.capability)
            )
        ).all()
        by_model = (
            await session.execute(
                select(AIExecution.model, func.sum(AIExecution.cost), func.count())
                .where(AIExecution.created_at >= start, AIExecution.created_at < end)
                .group_by(AIExecution.model)
            )
        ).all()

        analyzed_events = (
            await session.execute(
                select(func.count(func.distinct(AIExecution.event_id)))
                .where(
                    AIExecution.created_at >= start, AIExecution.created_at < end,
                    AIExecution.workflow_name == "NEWS_ANALYSIS",
                )
            )
        ).scalar_one()
        na_cost = (
            await session.execute(
                select(func.coalesce(func.sum(AIExecution.cost), 0))
                .where(
                    AIExecution.created_at >= start, AIExecution.created_at < end,
                    AIExecution.workflow_name == "NEWS_ANALYSIS",
                )
            )
        ).scalar_one()

        drafted_tasks = (
            await session.execute(
                select(func.count(func.distinct(AIExecution.task_id)))
                .where(
                    AIExecution.created_at >= start, AIExecution.created_at < end,
                    AIExecution.workflow_name == "CONTENT_GENERATION",
                )
            )
        ).scalar_one()
        cg_cost = (
            await session.execute(
                select(func.coalesce(func.sum(AIExecution.cost), 0))
                .where(
                    AIExecution.created_at >= start, AIExecution.created_at < end,
                    AIExecution.workflow_name == "CONTENT_GENERATION",
                )
            )
        ).scalar_one()

        delivered = (
            await session.execute(
                select(func.count()).select_from(ContentDraft).where(
                    ContentDraft.created_at >= start, ContentDraft.created_at < end
                )
            )
        ).scalar_one()

    cost_per_analyzed_event = (Decimal(str(na_cost)) / analyzed_events) if analyzed_events else None
    cost_per_draft = (Decimal(str(cg_cost)) / drafted_tasks) if drafted_tasks else None
    cost_per_delivered = ((Decimal(str(total_cost))) / delivered) if delivered else None

    print(f"=== API cost summary for {target_date.isoformat()} (UTC) ===")
    print(f"Total spend: ${total_cost} across {total_calls} recorded calls")
    print("\nBy workflow:")
    for workflow_name, cost, count in by_workflow:
        print(f"  {workflow_name}: ${cost} ({count} calls)")
    print("\nBy capability:")
    for capability, cost, count in by_capability:
        print(f"  {capability}: ${cost} ({count} calls)")
    print("\nBy model:")
    for model, cost, count in by_model:
        print(f"  {model}: ${cost} ({count} calls)")
    print(f"\nAnalyzed events (NEWS_ANALYSIS, distinct event_id): {analyzed_events}, cost ${na_cost}")
    print(f"Cost per analyzed event: {cost_per_analyzed_event if cost_per_analyzed_event is not None else 'n/a (0 events)'}")
    print(f"\nGenerated drafts (CONTENT_GENERATION, distinct task_id): {drafted_tasks}, cost ${cg_cost}")
    print(f"Cost per generated draft: {cost_per_draft if cost_per_draft is not None else 'n/a (0 drafts)'}")
    print(f"\nTelegram-delivered ContentDraft rows: {delivered}")
    print(f"Cost per delivered story (total spend / delivered rows): {cost_per_delivered if cost_per_delivered is not None else 'n/a (0 delivered)'}")


if __name__ == "__main__":
    asyncio.run(main())
