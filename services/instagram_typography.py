"""Line-breaking rules for rendered Instagram copy (Russian editorial typography). Deterministic, renderer-owned.

The v10.7 paid validation rendered valid copy with broken lines: "Титановые Watch / 6", "Длинный текст. Два / шага", and a line that
began with "— от $149". wrap_units() groups words that must never be separated; a wrapper breaks only BETWEEN units:
  - a dash never starts a line: it stays with the word before it;
  - a short preposition / conjunction / particle (в, и, с, на, не, от, ...) stays with the word after it;
  - a name and the number or version that follows it stay together (Watch 6, GPT 6, iPhone 17);
  - a number and the word after it stay together (600 млн, 3 пункта, 20 штатов), and so does a spelled-out numeral (два шага).
"""
from __future__ import annotations

import re

_DASHES = ("—", "–", "-")
_SHORT = frozenset("в во и а с со к ко у о об на не по до за от из но же ли бы".split())
_NUMERAL_WORDS = frozenset(
    "два две три четыре пять шесть семь восемь девять десять двух трёх трех четырёх четырех пяти шести семи восьми девяти десяти "
    "двум трём трем оба обе".split()
)
_NUMBER = re.compile(r"^[$€£₽]?\d[\d.,]*[%$€£₽]?$")
_LATIN_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9\-.]*$")


def wrap_units(text: str) -> list[str]:
    """Split on spaces into units that a line break must not split (each unit may contain spaces)."""
    words = text.split()
    units: list[str] = []
    i = 0
    while i < len(words):
        unit = words[i]
        # glue forward: short words, spelled-out numerals, numbers and names followed by a number
        while i + 1 < len(words):
            word, nxt = unit.split(" ")[-1], words[i + 1]
            bare = word.lower().strip("«»\"'(,.:;!?")
            if word.endswith((".", ",", ":", ";", "!", "?", "»", ")")):
                break  # never glue across a clause or sentence boundary
            if (bare in _SHORT or bare in _NUMERAL_WORDS or _NUMBER.match(bare)
                    or (_LATIN_NAME.match(bare) and _NUMBER.match(nxt.strip("«»\"'(),.:;!?")))):
                if nxt in _DASHES:  # "X —": the dash belongs to X anyway
                    break
                unit = f"{unit} {nxt}"
                i += 1
                continue
            break
        units.append(unit)
        i += 1
    # a dash never starts a line: attach it (and nothing else) to the unit before it
    merged: list[str] = []
    for unit in units:
        if merged and (unit in _DASHES or unit.split(" ")[0] in _DASHES):
            merged[-1] = f"{merged[-1]} {unit}"
        else:
            merged.append(unit)
    return merged
