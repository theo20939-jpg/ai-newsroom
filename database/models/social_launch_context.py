"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §3/§4/§5/§6/§8: SocialLaunchContext - the ONE canonical,
platform-agnostic model for pre-launch/transition/cold-start planning state. Deliberately NOT two
competing Telegram/Instagram models (spec §3's own explicit instruction) - `platform` is a field,
not a table split, exactly like every other cross-platform table in this codebase (DirectorRun,
telegram_content_calendar_items' own sibling instagram table being the one accepted exception,
kept separate there only because their own column shapes already diverge; this table's shape is
identical across platforms so it stays one table).

Append-only versioning, mirroring database/models/visual_designer_brief.py's own established
shape: `get_current_context(platform)` always returns the highest `version` row for that platform;
confirming a new /launch proposal never UPDATEs the existing row in place, it INSERTs a new one
with `version = previous + 1` (or 1 if none exists yet) - full history stays queryable forever,
satisfying spec §43's own "history/versioning preserved" test requirement and spec §40's "do not
discard pre-launch strategic memory" instruction. No separate ACTIVE/SUPERSEDED status column is
needed the way VisualDesignerBriefVersion has one (that model supports freeze/rollback to an
arbitrary prior version; this phase's own spec never asks for that here) - "current" is simply
"the latest version for this platform" by construction.

`learning_start_at` (spec §6/§9) is the single authoritative first-party-learning boundary this
whole phase exists to protect: `services/social_learning_boundary.py::
is_eligible_for_first_party_learning()` is the ONE function anything (performance collection,
TelegramPerformanceAggregator, Channel Memory, Growth Director evidence) may ever call to decide
whether a given post's `published_at` counts as real first-party learning evidence - never a
second, ad hoc "was this before or after launch" check anywhere else."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class SocialLaunchPlatform(str, enum.Enum):
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"


class LaunchState(str, enum.Enum):
    PRE_LAUNCH = "pre_launch"
    TRANSITION = "transition"
    LIVE = "live"
    PAUSED = "paused"


class LaunchDateStatus(str, enum.Enum):
    UNSCHEDULED = "unscheduled"
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"


class LearningBaselinePolicy(str, enum.Enum):
    """spec §6: which real-world event sets `learning_start_at` - never hardcoded per platform
    (spec §6's own "do not hardcode platform defaults if current architecture prefers explicit
    configuration" instruction), always an explicit field on the context row itself."""

    FROM_EXPLICIT_DATE = "from_explicit_date"
    FROM_FIRST_POST_AFTER_LAUNCH = "from_first_post_after_launch"
    FROM_FIRST_PUBLICATION = "from_first_publication"


class HistoricalContentPolicy(str, enum.Enum):
    """spec §8: how pre-existing content on a platform (e.g. the current NINJA VPN Telegram
    channel's own history) may be used."""

    IGNORE = "ignore"
    LEGACY_CONTEXT_ONLY = "legacy_context_only"
    INCLUDE_IN_LEARNING = "include_in_learning"


class SocialLaunchContext(Base):
    __tablename__ = "social_launch_contexts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[SocialLaunchPlatform] = mapped_column(
        Enum(SocialLaunchPlatform, name="social_launch_platform", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    target_identity: Mapped[str] = mapped_column(String(200), nullable=False)
    current_identity: Mapped[str | None] = mapped_column(String(200), nullable=True)

    launch_state: Mapped[LaunchState] = mapped_column(
        Enum(LaunchState, name="social_launch_state", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=LaunchState.PRE_LAUNCH,
    )

    planned_launch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    launch_date_status: Mapped[LaunchDateStatus] = mapped_column(
        Enum(LaunchDateStatus, name="social_launch_date_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=LaunchDateStatus.UNSCHEDULED,
    )

    # spec §6/§9: NULL until the real boundary event (per baseline_policy) has actually happened -
    # a NULL here is exactly what makes is_eligible_for_first_party_learning() return False for
    # every post, never a fabricated "learning has started" default.
    learning_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    baseline_policy: Mapped[LearningBaselinePolicy] = mapped_column(
        Enum(LearningBaselinePolicy, name="social_launch_baseline_policy", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    historical_content_policy: Mapped[HistoricalContentPolicy] = mapped_column(
        Enum(HistoricalContentPolicy, name="social_launch_historical_content_policy", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    # spec §36/§37: nullable, no FK-enforced requirement to exist yet - a real TelegramSurface/
    # Instagram account may attach to this context LATER without resetting accumulated strategy.
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("launch_campaigns.id"), nullable=True)
    surface_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("telegram_surfaces.id"), nullable=True)

    raw_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_structure: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
