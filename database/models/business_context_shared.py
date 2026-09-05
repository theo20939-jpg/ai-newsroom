"""Shared enum(s) reused across more than one NINJA Business Context model - kept in one place so
the semantics can never drift between `ProductEvent`/`CampaignMilestone`. Each model still maps
its own column to its own named Postgres enum type (`mapped_column(Enum(Visibility, name="..."))`)
- this module only prevents the Python-level definition itself from being duplicated."""
import enum


class Visibility(str, enum.Enum):
    """Distinguishes "true internally" from "approved for public communication" (spec §7/§11) -
    an internal milestone/event must never accidentally become a public social claim merely
    because it is real and known."""

    INTERNAL_ONLY = "internal_only"
    PREPARATION_ALLOWED = "preparation_allowed"
    PUBLIC_ALLOWED = "public_allowed"
