"""Phase 19 M5: the sole lookup for a persisted, verified ContentDraftQuote before Telegram
delivery (docs/phase19_m0_audit.md) - shared by both worker/content_cycle.py send-path branches,
never two divergent lookups.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft_quote import ContentDraftQuote


async def get_quote_for_draft(session: AsyncSession, content_draft_id: UUID) -> ContentDraftQuote | None:
    """A read-only lookup - content_draft_quotes.content_draft_id is the table's own PK
    (Phase 18.10 M5), so at most one row can ever exist per draft."""
    return await session.get(ContentDraftQuote, content_draft_id)


def resolve_display_text(quote: ContentDraftQuote) -> tuple[str, str | None]:
    """Prefers the target-language translation for on-channel display, falling back to the
    verbatim original when no translation exists - matches prompts/copywriting/v4.yaml's/v5.yaml's
    own rule that `speaker` is always target-language while `text` is always verbatim-original."""
    text = quote.translated_text or quote.quote_text
    return text, quote.speaker
