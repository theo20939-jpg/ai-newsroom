"""Phase B.5.1: audience-facing copy must never carry implementation / instruction language.

B.5 exposed a real leak: a Creative Director slide read "не подпись и не кадры референса" - an instruction about the design
reference, presented as audience copy. This guard is a validation boundary, not a rewriter: a leak REJECTS the draft.

Only phrases that are unambiguously about our own tooling or design brief are matched; ordinary vocabulary an AI-news story can
use ("prompt", "промпт", "layout of a keyboard") is NOT matched. A phrase is also NOT a leak when the story's own evidence uses it
(a factual article about, say, "reference designs"), so the caller passes the allowed evidence as `allowed_context`."""
from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple((name, re.compile(rx, re.IGNORECASE | re.UNICODE)) for name, rx in (
    ("design_reference", r"референс\w*|\breference\s+(?:board|image|slide|frame|frames|design)\b"),
    ("visual_dna", r"визуальн\w*\s+днк|visual\s*dna"),
    ("visual_family", r"визуальн\w*\s+семейств\w*|visual[\s_]+family|\b(?:immersive_image_field|hero_object_stage|internet_culture_collage|"
                       r"dark_type_number_statement|interface_cards|light_utility_editorial)\b"),
    ("renderer_or_layout", r"\brenderer\b|рендерер\w*|\blayout\s+plan\b|лейаут\w*|фикстур\w*|\bfixtures?\b"),
    ("negated_caption_or_frames", r"не\s+подпись|не\s+кадры|не\s+сам\s+кадр\w*\s+рефер"),
    ("archetype", r"\barchetype\b|архетип\w*"),
    ("slide_role", r"slide[\s_]+role|роль\s+слайда"),
    ("do_not_copy", r"do\s+not\s+copy|don'?t\s+copy|не\s+копиру\w+\s+(?:рефер|шаблон|макет)"),
    ("image_treatment_instruction", r"\bscrim\b|\boverlay\b|readability\s+(?:layer|field)|quiet[\s-]+zone|тихая\s+зона"),
    ("placeholder", r"\bplaceholder\b|плейсхолдер\w*|lorem\s+ipsum"),
    ("editorial_instruction", r"инструкци\w+\s+(?:для\s+)?(?:модели|дизайнера|редактора)|editorial\s+instruction"),
))


@dataclass(frozen=True)
class MetaLanguageHit:
    field: str
    pattern: str
    snippet: str


class MetaLanguageLeakError(ValueError):
    """Audience-facing copy contains implementation / instruction language."""

    def __init__(self, hits: list[MetaLanguageHit]) -> None:
        self.hits = hits
        super().__init__("meta-language in audience-facing copy: " + "; ".join(f"{h.field}:{h.pattern}:{h.snippet!r}" for h in hits[:4]))


def find_meta_language(fields: dict[str, str], *, allowed_context: list[str] | None = None) -> list[MetaLanguageHit]:
    """`fields` maps a field name to its text. A match is ignored when the same matched text already appears in the
    supplied factual context (the story itself uses that term)."""
    context = " ".join(allowed_context or []).casefold()
    hits: list[MetaLanguageHit] = []
    for name, text in fields.items():
        for label, pattern in _PATTERNS:
            for match in pattern.finditer(text or ""):
                snippet = match.group(0)
                if snippet.casefold() in context:
                    continue
                hits.append(MetaLanguageHit(name, label, snippet))
    return hits


def assert_no_meta_language(fields: dict[str, str], *, allowed_context: list[str] | None = None) -> None:
    hits = find_meta_language(fields, allowed_context=allowed_context)
    if hits:
        raise MetaLanguageLeakError(hits)
