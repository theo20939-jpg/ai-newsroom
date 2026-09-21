"""KAGE brand voice: ONE shared source of truth (docs/brand/kage_voice_v1.md), loaded - never copied - by every platform prompt that speaks as KAGE."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

KAGE_VOICE_RELATIVE_PATH = "docs/brand/kage_voice_v1.md"
_ROOT = Path(__file__).resolve().parent.parent


class KageVoiceUnavailableError(RuntimeError):
    """The shared voice document is missing or empty: audience-facing generation must fail closed rather than invent a voice."""


@dataclass(frozen=True)
class KageVoice:
    text: str
    sha256: str
    path: str

    def render_context(self) -> str:
        return f"KAGE VOICE (shared brand voice, source of truth {self.path}, sha256 {self.sha256[:12]}):\n{self.text}"


@lru_cache(maxsize=1)
def load_kage_voice() -> KageVoice:
    path = _ROOT / KAGE_VOICE_RELATIVE_PATH
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise KageVoiceUnavailableError(f"{KAGE_VOICE_RELATIVE_PATH} is not readable: {exc}") from exc
    text = raw.decode("utf-8").strip()
    if not text:
        raise KageVoiceUnavailableError(f"{KAGE_VOICE_RELATIVE_PATH} is empty")
    return KageVoice(text=text, sha256=hashlib.sha256(raw).hexdigest(), path=KAGE_VOICE_RELATIVE_PATH)
