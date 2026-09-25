"""Excerpt of long publications before the model reads them: appellate decisions reach 64,000
characters.

Keeps the head (header, parties, nature of the act), the tail (the operative part and the
service order usually sit there) and windows around deadline markers in the middle. Short text
passes whole. Nothing is dropped without marking the cut.

The markers are Portuguese because the publications are.
"""

from __future__ import annotations

import re

LIMIT = 12_000
HEAD = 2_500
TAIL = 5_000
WINDOW = 350
CUT_MARK = "\n[... excerpt omitted ...]\n"

MARKERS = re.compile(
    r"prazo|dias?\s+(?:úteis|uteis|corridos)|\(\s*\w+\s*\)\s*dias|intim|manifest|"
    r"cumpra-se|contrarraz|recolh|emend|especific|réplica|replica|audiência|audiencia|"
    r"ante o exposto|isto posto|julgo|acordam|dou provimento|nego provimento",
    re.IGNORECASE,
)


def excerpt(text: str, limit: int = LIMIT) -> tuple[str, bool]:
    """(possibly shortened text, was_shortened)."""
    if len(text) <= limit:
        return text, False
    tail_start = len(text) - TAIL
    budget = limit - HEAD - TAIL
    spans: list[tuple[int, int]] = []
    for m in MARKERS.finditer(text, HEAD, tail_start):
        a, b = max(HEAD, m.start() - WINDOW), min(tail_start, m.end() + WINDOW)
        if spans and a <= spans[-1][1]:
            spans[-1] = (spans[-1][0], b)
        else:
            spans.append((a, b))
    parts, used = [text[:HEAD]], 0
    for a, b in spans:
        if used + (b - a) > budget:
            break
        parts.append(text[a:b])
        used += b - a
    parts.append(text[tail_start:])
    return CUT_MARK.join(parts), True
