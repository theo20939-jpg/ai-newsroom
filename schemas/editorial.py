"""Editorial channel domain model (TELEGRAPH editorial channel split).

`EditorialChannel` is deliberately a general-purpose EDITORIAL concept, not a TELEGRAPH-specific
or Telegram-specific one - it lives in `schemas/` (alongside `schemas/editorial_route.py`'s own
`EditorialDestination`, a genuinely different axis: destination is WHERE something is delivered,
channel is WHICH editorial direction/brand it belongs to) rather than under `database/models/
telegraph_shortlist.py` or a bot-scoped module, so that future consumers outside TELEGRAPH -
Telegram routing, the website, analytics, CRM, recommendations, SEO - can depend on this same
enum without importing anything TELEGRAPH-specific. Deliberately NOT named `AI_CHANNEL`/
`PULSE_CHANNEL`/`TELEGRAPH_CHANNEL` - it names an editorial direction, not a delivery mechanism.
"""
from __future__ import annotations

import enum


class EditorialChannel(str, enum.Enum):
    """The two editorial directions TELEGRAPH content is classified into. Values are the
    lowercase slugs used consistently across persistence (database/models/telegraph_shortlist.py)
    and any future consumer - never re-derived or reformatted per call site."""

    NINJA_AI = "ninja_ai"
    NINJA_PULSE = "ninja_pulse"
