"""Bounded, secret-safe persistence for KAGE factual-generation lineage."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.kage_content_lineage_audit import KageContentLineageAudit
from database.models.story_telegram_delivery import StoryTelegramDelivery

MAX_AUDIT_BYTES = 2_097_152
MAX_TEXT_CHARS = 524_288
_SECRET_KEY = re.compile(r"(?:api.?key|authorization|secret|password|credential|token|dsn|connection.?string)", re.I)
_BEARER_VALUE = re.compile(r"Bearer\s+\S+", re.I)
_OPENAI_KEY_VALUE = re.compile(r"sk-[A-Za-z0-9_-]{8,}")


class LineageAuditBoundsError(ValueError):
    """The full forensic payload exceeds the explicit storage bound; never silently truncate."""


def capability_input_metadata(request: Any, *, prompt_name: str, prompt_version: str) -> dict[str, Any]:
    """Capture only the exact user-side factual input, never system prompt or request headers."""
    messages = getattr(request, "messages", None) or []
    if not messages:
        raise ValueError("audited capability request has no messages")
    content = getattr(messages[-1], "content", None) or []
    texts = [getattr(part, "text", None) for part in content]
    exact_input = "\n".join(text for text in texts if isinstance(text, str))
    return {
        "prompt_name": prompt_name,
        "prompt_version": str(prompt_version),
        "user_input": exact_input,
        "user_input_sha256": hashlib.sha256(exact_input.encode("utf-8")).hexdigest(),
    }


def kage_content_generation_input_metadata(
    context: Any, request: Any, *, prompt_name: str, prompt_version: str,
) -> dict[str, Any]:
    workflow = getattr(getattr(context, "business", None), "workflow_state", None)
    if getattr(workflow, "workflow_name", None) != "CONTENT_GENERATION":
        return {}
    return capability_input_metadata(request, prompt_name=prompt_name, prompt_version=prompt_version)


def _safe_value(value: Any, *, path: str = "root") -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item, path=f"{path}.{key}")
            for key, item in value.items()
            if not _SECRET_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, path=f"{path}[]") for item in value]
    if isinstance(value, str):
        if len(value) > MAX_TEXT_CHARS:
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
            raise LineageAuditBoundsError(f"{path} exceeds {MAX_TEXT_CHARS} chars (sha256={digest})")
        # Defense in depth for accidental inline credentials (e.g. a header copied into
        # diagnostic text); structured sensitive-key fields are removed above.
        return _OPENAI_KEY_VALUE.sub("[REDACTED]", _BEARER_VALUE.sub("Bearer [REDACTED]", value))
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if hasattr(value, "value") and isinstance(value.value, (str, int, float)):
        return value.value
    raise TypeError(f"unsupported audit value at {path}: {type(value).__name__}")


def bounded_audit(audit: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = _safe_value(audit)
    encoded = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_AUDIT_BYTES:
        raise LineageAuditBoundsError(f"audit document exceeds {MAX_AUDIT_BYTES} bytes")
    return cleaned


async def create_attempt_audit(
    session: AsyncSession, *, task_id: UUID, event_id: UUID, story_id: UUID | None,
    source_snapshot: Mapping[str, Any],
) -> KageContentLineageAudit:
    row = KageContentLineageAudit(
        task_id=task_id, event_id=event_id, story_id=story_id,
        audit=bounded_audit({
            "schema_version": 1,
            "identity": {"attempt_id": str(task_id), "generation_task_id": str(task_id),
                         "event_id": str(event_id), "story_id": str(story_id) if story_id else None,
                         "draft_id": None, "publication_outcome_id": str(task_id),
                         "telegram_message_id": None, "delivery_receipt_id": None},
            "source": dict(source_snapshot), "stages": {}, "publication_factual_gate": None,
            "publication_outcome": None, "created_at": datetime.now(timezone.utc).isoformat(),
        }),
    )
    session.add(row)
    await session.flush()
    return row


async def update_attempt_audit(
    session: AsyncSession, *, task_id: UUID, section: str, value: Mapping[str, Any],
    required: bool = False,
) -> KageContentLineageAudit | None:
    row = await session.get(KageContentLineageAudit, task_id)
    if row is None:
        if required:
            raise ValueError(f"lineage audit missing for attempt {task_id}")
        return None
    audit = dict(row.audit or {})
    if section == "stage":
        stages = dict(audit.get("stages") or {})
        name = str(value.get("name") or "")
        if not name:
            raise ValueError("stage audit requires a name")
        stages[name] = bounded_audit(dict(value))
        audit["stages"] = stages
    elif section in ("publication_factual_gate", "publication_outcome"):
        audit[section] = bounded_audit(dict(value))
        if section == "publication_outcome":
            identity = dict(audit.get("identity") or {})
            identity["telegram_message_id"] = value.get("message_id")
            if value.get("draft_id"):
                identity["draft_id"] = value.get("draft_id")
                receipt_id = (await session.execute(
                    select(StoryTelegramDelivery.id).where(
                        StoryTelegramDelivery.content_draft_id == UUID(str(value["draft_id"])),
                    ).order_by(StoryTelegramDelivery.created_at.desc()).limit(1)
                )).scalar_one_or_none()
                if receipt_id is not None:
                    identity["delivery_receipt_id"] = str(receipt_id)
            audit["identity"] = identity
    else:
        raise ValueError(f"unsupported audit section: {section}")
    row.audit = bounded_audit(audit)
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


async def archive_publication_outcome_for_retry(
    session: AsyncSession, *, task_id: UUID, outcome: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> None:
    """Preserve one failed transport outcome before an explicitly authorized retry."""
    row = await session.get(KageContentLineageAudit, task_id)
    if row is None:
        raise ValueError(f"lineage audit missing for retry attempt {task_id}")
    audit = dict(row.audit or {})
    history = list(audit.get("publication_outcome_history") or [])
    history.append(bounded_audit(dict(outcome)))
    authorizations = list(audit.get("publication_retry_authorizations") or [])
    authorizations.append(bounded_audit(dict(authorization)))
    audit["publication_outcome_history"] = history
    audit["publication_retry_authorizations"] = authorizations
    audit["publication_outcome"] = None
    row.audit = bounded_audit(audit)
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()


async def link_draft(session: AsyncSession, *, task_id: UUID, draft_id: UUID) -> None:
    row = await session.get(KageContentLineageAudit, task_id)
    if row is None:
        return
    identity = dict(row.audit.get("identity") or {})
    identity["draft_id"] = str(draft_id)
    row.audit = bounded_audit({**row.audit, "identity": identity})
    row.draft_id = draft_id
    await session.flush()


async def update_source_snapshot(
    session: AsyncSession, *, task_id: UUID, additions: Mapping[str, Any],
) -> None:
    row = await session.get(KageContentLineageAudit, task_id)
    if row is None:
        raise ValueError(f"lineage audit missing for attempt {task_id}")
    audit = dict(row.audit or {})
    audit["source"] = bounded_audit({**dict(audit.get("source") or {}), **dict(additions)})
    row.audit = bounded_audit(audit)
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()


async def reconstruct_lineage(session: AsyncSession, task_id: UUID) -> dict[str, Any] | None:
    """Reload a complete forensic package using only durable DB rows."""
    from database.models.editorial_task import EditorialTask

    audit_row = await session.get(KageContentLineageAudit, task_id)
    task = await session.get(EditorialTask, task_id)
    if audit_row is None or task is None:
        return None
    workflow = dict(task.workflow or {})
    audit = dict(audit_row.audit)
    steps = {
        item.get("step_name"): item
        for item in workflow.get("step_results", [])
        if isinstance(item, dict) and item.get("step_name") in {"research", "intelligence", "copywriting", "quality"}
    }
    outcome = workflow.get("publication_outcome")
    return bounded_audit({**audit, "workflow_stage_results": steps,
                          "publication_outcome": audit.get("publication_outcome") or outcome})
