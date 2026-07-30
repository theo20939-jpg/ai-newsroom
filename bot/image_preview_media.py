"""Phase 16 M6: shared photo-input resolution for the Telegram Editorial Preview (docs/
phase16_m6_telegram_editorial_preview_report.md §11). Used by both `bot/handlers/image_preview.py`
(navigation) and `services/image_preview_notifier.py` (the initial push) so the file_id-caching
policy lives in exactly one place. Aiogram-aware (returns a `BufferedInputFile`), unlike
`bot/image_preview_formatting.py`'s own deliberately pure, aiogram-free discipline.
"""
from aiogram.types import BufferedInputFile

from services.image_persistence import EditorialImageCandidate, read_candidate_bytes

_EXTENSION_BY_FORMAT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}


def resolve_photo_input(candidate: EditorialImageCandidate) -> str | BufferedInputFile | None:
    """A cached Telegram `file_id` (string) when available - zero local byte reads, valid
    regardless of which process/container sends it, as long as it holds this application's own bot
    token. Otherwise freshly-read bytes via the storage abstraction (`services.image_persistence.
    read_candidate_bytes` - never this module, or any caller, reaching into
    `integrations.storage` directly), wrapped for upload. `None` when nothing is resolvable (no
    stored bytes, expired/missing file) - callers always fall back to a text-only send/edit."""
    if candidate.telegram_file_id:
        return candidate.telegram_file_id
    data = read_candidate_bytes(candidate)
    if data is None:
        return None
    extension = _EXTENSION_BY_FORMAT.get((candidate.image_format or "").upper(), "jpg")
    return BufferedInputFile(data, filename=f"preview.{extension}")
