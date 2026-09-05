"""add instagram persistent intelligence memory tables

Revision ID: 12c560efce40
Revises: 495d8c5b408e
Create Date: 2026-09-05 08:00:00.000000

INSTAGRAM-GROWTH-3, item 2/3/9/10/11/12/15: purely additive tables giving Audience Intelligence,
Hook Intelligence, Creative Fatigue, Content Series, Original Format Lab, Reference Deconstruction,
and Creator Radar the persistence they previously lacked (pure dataclasses only). See each
corresponding database/models/instagram_*_memory.py file for the full field-by-field reasoning.

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "12c560efce40"
down_revision: Union[str, None] = "495d8c5b408e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUDIENCE_EVIDENCE_SOURCE = sa.Enum(
    "first_party_performance", "comments", "product_data", "manual_research", "competitor_observation",
    "founder_input", "hypothesis", name="instagram_audience_evidence_source",
)
_INTELLIGENCE_EVIDENCE_STAGE = sa.Enum(
    "observation", "hypothesis", "possible_signal", "repeated_pattern", "stable_working_rule",
    name="instagram_intelligence_evidence_stage",
)
_HOOK_EVIDENCE_STAGE = sa.Enum(
    "anomaly", "possible_signal", "repeated_pattern", "stable_working_rule", name="instagram_hook_evidence_stage",
)
_FATIGUE_STATE = sa.Enum("fresh", "normal", "repeated", "fatigued", "overused", name="instagram_fatigue_state")
_SERIES_STATUS = sa.Enum(
    "series_hypothesis", "series_testing", "series_active", "series_fatigued", "series_retired",
    name="instagram_series_status",
)
_ORIGINAL_FORMAT_STATUS = sa.Enum(
    "draft", "ready_to_test", "testing", "promising", "failed", "retest", "adopted",
    name="instagram_original_format_status",
)
_CREATOR_OBSERVATION_SOURCE = sa.Enum(
    "manual", "public_data_import", name="instagram_creator_observation_source",
)


def upgrade() -> None:
    op.create_table(
        "instagram_audience_insights",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("segment_name", sa.String(length=200), nullable=False),
        sa.Column("funnel_stage", sa.String(length=50), nullable=True),
        sa.Column("need", sa.Text(), nullable=False),
        sa.Column("problem", sa.Text(), nullable=True),
        sa.Column("interest", sa.Text(), nullable=True),
        sa.Column("objection", sa.Text(), nullable=True),
        sa.Column("content_job", sa.Text(), nullable=True),
        sa.Column("format_preference_hypothesis", sa.String(length=200), nullable=True),
        sa.Column("source", _AUDIENCE_EVIDENCE_SOURCE, nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_stage", _INTELLIGENCE_EVIDENCE_STAGE, nullable=False, server_default="observation"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instagram_audience_insights_segment_name", "instagram_audience_insights", ["segment_name"])

    op.create_table(
        "instagram_hook_evidence_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dimension", sa.String(length=50), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("effect_size", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("repeatability", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("recency_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_stage", _HOOK_EVIDENCE_STAGE, nullable=False, server_default="anomaly"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("dimension", "value", name="uq_instagram_hook_evidence_dimension_value"),
    )
    op.create_index("ix_instagram_hook_evidence_records_dimension", "instagram_hook_evidence_records", ["dimension"])
    op.create_index("ix_instagram_hook_evidence_records_value", "instagram_hook_evidence_records", ["value"])

    op.create_table(
        "instagram_fatigue_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dimension", sa.String(length=50), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("repetition_count", sa.Integer(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("fatigue_state", _FATIGUE_STATE, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instagram_fatigue_observations_dimension", "instagram_fatigue_observations", ["dimension"])
    op.create_index("ix_instagram_fatigue_observations_value", "instagram_fatigue_observations", ["value"])
    op.create_index("ix_instagram_fatigue_observations_observed_at", "instagram_fatigue_observations", ["observed_at"])

    op.create_table(
        "instagram_series",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("objective", sa.String(length=50), nullable=False),
        sa.Column("preferred_formats", sa.JSON(), nullable=True),
        sa.Column("topic_scope", sa.Text(), nullable=True),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("cadence", sa.String(length=100), nullable=True),
        sa.Column("status", _SERIES_STATUS, nullable=False, server_default="series_hypothesis"),
        sa.Column("episode_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("performance_summary", sa.Text(), nullable=True),
        sa.Column("fatigue", sa.String(length=50), nullable=False, server_default="fresh"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_instagram_series_name"),
    )
    op.create_index("ix_instagram_series_name", "instagram_series", ["name"])
    op.create_index("ix_instagram_series_status", "instagram_series", ["status"])

    op.create_table(
        "instagram_original_format_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idea", sa.Text(), nullable=False),
        sa.Column("novelty_hypothesis", sa.Text(), nullable=False),
        sa.Column("intentional_difference", sa.Text(), nullable=False),
        sa.Column("target_objective", sa.String(length=50), nullable=False),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("format", sa.String(length=50), nullable=False),
        sa.Column("test_conditions", sa.Text(), nullable=True),
        sa.Column("success_criteria", sa.Text(), nullable=True),
        sa.Column("evaluation_window", sa.String(length=100), nullable=True),
        sa.Column("references", sa.JSON(), nullable=True),
        sa.Column("status", _ORIGINAL_FORMAT_STATUS, nullable=False, server_default="draft"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instagram_original_format_experiments_status", "instagram_original_format_experiments", ["status"])

    op.create_table(
        "instagram_reference_deconstructions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reference_description", sa.Text(), nullable=False),
        sa.Column("hook_mechanics", sa.Text(), nullable=True),
        sa.Column("pacing", sa.Text(), nullable=True),
        sa.Column("scene_structure", sa.Text(), nullable=True),
        sa.Column("narrative_progression", sa.Text(), nullable=True),
        sa.Column("typography_behavior", sa.Text(), nullable=True),
        sa.Column("visual_rhythm", sa.Text(), nullable=True),
        sa.Column("editing_rhythm", sa.Text(), nullable=True),
        sa.Column("cta_mechanics", sa.Text(), nullable=True),
        sa.Column("interaction_pattern", sa.Text(), nullable=True),
        sa.Column("what_appears_effective", sa.JSON(), nullable=True),
        sa.Column("why_hypothesis_only", sa.Text(), nullable=True),
        sa.Column("must_not_copy", sa.JSON(), nullable=False),
        sa.Column("originality_constraints", sa.JSON(), nullable=True),
        sa.Column("ai_assisted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "instagram_creator_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("handle", sa.String(length=200), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False, server_default="instagram"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("observation_source", _CREATOR_OBSERVATION_SOURCE, nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instagram_creator_observations_handle", "instagram_creator_observations", ["handle"])
    op.create_index("ix_instagram_creator_observations_observed_at", "instagram_creator_observations", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_instagram_creator_observations_observed_at", table_name="instagram_creator_observations")
    op.drop_index("ix_instagram_creator_observations_handle", table_name="instagram_creator_observations")
    op.drop_table("instagram_creator_observations")
    _CREATOR_OBSERVATION_SOURCE.drop(op.get_bind(), checkfirst=True)

    op.drop_table("instagram_reference_deconstructions")

    op.drop_index("ix_instagram_original_format_experiments_status", table_name="instagram_original_format_experiments")
    op.drop_table("instagram_original_format_experiments")
    _ORIGINAL_FORMAT_STATUS.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_instagram_series_status", table_name="instagram_series")
    op.drop_index("ix_instagram_series_name", table_name="instagram_series")
    op.drop_table("instagram_series")
    _SERIES_STATUS.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_instagram_fatigue_observations_observed_at", table_name="instagram_fatigue_observations")
    op.drop_index("ix_instagram_fatigue_observations_value", table_name="instagram_fatigue_observations")
    op.drop_index("ix_instagram_fatigue_observations_dimension", table_name="instagram_fatigue_observations")
    op.drop_table("instagram_fatigue_observations")
    _FATIGUE_STATE.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_instagram_hook_evidence_records_value", table_name="instagram_hook_evidence_records")
    op.drop_index("ix_instagram_hook_evidence_records_dimension", table_name="instagram_hook_evidence_records")
    op.drop_table("instagram_hook_evidence_records")
    _HOOK_EVIDENCE_STAGE.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_instagram_audience_insights_segment_name", table_name="instagram_audience_insights")
    op.drop_table("instagram_audience_insights")
    _INTELLIGENCE_EVIDENCE_STAGE.drop(op.get_bind(), checkfirst=True)
    _AUDIENCE_EVIDENCE_SOURCE.drop(op.get_bind(), checkfirst=True)
