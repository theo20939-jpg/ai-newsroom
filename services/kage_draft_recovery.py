"""Accepted deterministic KAGE draft correction used before independent Quality."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from services.kage_editorial_contract import unsupported_absence_clauses


_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def remove_unsupported_absence_sentence(research: Mapping[str, Any], copy: Mapping[str, Any]) -> dict[str, Any] | None:
    """Delete exactly one isolated unsupported absence sentence, never add a claim.

    A returned draft still requires the normal Quality and publication gates.
    """
    if unsupported_absence_clauses(research, str(copy.get("title") or "")):
        return None
    repaired = dict(copy)
    removed = 0
    for field in ("main_body", "ending"):
        value = copy.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        kept_paragraphs = []
        for paragraph in re.split(r"\n\s*\n", value):
            keep = []
            for sentence in [item.strip() for item in _SENTENCE.split(paragraph) if item.strip()]:
                if unsupported_absence_clauses(research, sentence):
                    removed += 1
                else:
                    keep.append(sentence)
            if keep:
                kept_paragraphs.append(" ".join(keep))
        if field == "main_body" and not kept_paragraphs:
            return None
        repaired[field] = "\n\n".join(kept_paragraphs) if kept_paragraphs else None
    return repaired if removed == 1 else None
