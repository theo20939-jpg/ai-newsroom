"""MemeImageGenerationResult (Phase 18 M5): the outcome of one meme image-generation attempt
(docs/phase18_m5_meme_image_generation_report.md).

Never carries raw image bytes (mirrors `database.models.image_candidate_record.
ImageCandidateRecord`'s own "storage_key is an internal reference only" discipline) - only a
reference into `integrations.storage.image_storage.ImageStorage`, plus provider/cost/error
metadata. Directly inspectable and JSON-serializable, mirroring `services.telegram_notifier.
NotificationOutcome`'s/`services.image_preview_notifier.CombinedCardOutcome`'s own established
"always returned, always inspectable" convention for a non-Capability-Framework orchestration
function's result type.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

MEME_IMAGE_SCHEMA_VERSION = "v1"


class MemeImageStatus(str, Enum):
    OFF = "off"  # meme_image_generation_mode == "off" - zero-cost, zero-call no-op
    GENERATED = "generated"
    FAILED = "failed"


class MemeImageGenerationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_IMAGE_SCHEMA_VERSION
    status: MemeImageStatus
    mode: str
    storage_key: str | None = None
    mime_type: str | None = None
    provider: str | None = None
    model_used: str | None = None
    width: int | None = None
    height: int | None = None
    byte_size: int | None = None
    sha256: str | None = None
    # Decimal is not JSON-native - stored as a string, mirroring how AIExecution.cost (a Numeric
    # column) is always serialized as a string in every JSON boundary this codebase already has.
    cost_usd: str | None = None
    error_code: str | None = None
    attempt_count: int = Field(default=0, ge=0)
