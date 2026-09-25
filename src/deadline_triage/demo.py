"""Demo adapters: a fixture gazette and a fixture classifier, so the whole pipeline runs offline.

`fixtures/publications.json` holds invented publications in the raw shape of the DJEN API plus,
for each one that needs the model, the classification the model would return. Case numbers in
the file carry "XX" as check digits; they are completed at load time so they pass the CNJ
check-digit validation without a real-looking number ever sitting in the repository.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from .classifier import Classification, LlmResult, Usage, build_prompt
from .config import ROOT, BarNumber
from .court import expected_check_digits, parse_cnj

FIXTURES_PATH = ROOT / "fixtures" / "publications.json"


def complete_case_number(masked: str) -> tuple[str, str]:
    """ "0000101-XX.2099.8.09.0001" -> (masked with digits, 20 digits)."""
    if "-XX." in masked:
        head, rest = masked.split("-XX.")
        year, branch, court, unit = rest.split(".")
        dd = f"{expected_check_digits(head, year, branch, court, unit):02d}"
        masked = f"{head}-{dd}.{rest}"
    cnj = parse_cnj(masked)
    digits = (
        "".join(ch for ch in masked if ch.isdigit())
        if cnj is None
        else (cnj.sequence + cnj.check_digits + cnj.year + cnj.branch + cnj.court + cnj.unit)
    )
    return masked, digits


def _assemble_text(text: Any) -> str:
    """A fixture text is a string or {"paragraphs": [...], "repeat": n}: long appellate decisions
    are simulated by repeating their reasoning, because real ones run to 60,000 characters."""
    if isinstance(text, dict):
        paragraphs = text.get("paragraphs") or []
        repeat = int(text.get("repeat") or 1)
        body = paragraphs[1:-1] * repeat if len(paragraphs) > 2 else paragraphs * repeat
        return "\n\n".join([paragraphs[0], *body, paragraphs[-1]] if len(paragraphs) > 2 else body)
    return str(text or "")


def load_fixtures(path: Path = FIXTURES_PATH) -> list[dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = []
    for item in raw["publications"]:
        item = copy.deepcopy(item)
        pub = item["raw"]
        masked, digits = complete_case_number(pub["numeroprocessocommascara"])
        pub["numeroprocessocommascara"] = masked
        pub["numero_processo"] = digits
        pub["texto"] = _assemble_text(pub.get("texto"))
        items.append(item)
    return items


class FixtureDjenClient:
    """Yields the fixture publications addressed to the queried bar number inside the window."""

    def __init__(self, path: Path = FIXTURES_PATH) -> None:
        self._items = load_fixtures(path)
        self.warnings: list[str] = []

    def list(self, bar: BarNumber, start: date, end: date) -> Iterator[dict[str, Any]]:
        for item in self._items:
            if str(bar) not in item.get("bars", []):
                continue
            available = date.fromisoformat(item["raw"]["data_disponibilizacao"])
            if start <= available <= end:
                yield copy.deepcopy(item["raw"])


class FixtureClassifier:
    """Replays the canned classification of each fixture publication; no model call, zero cost."""

    model = "fixture"

    def __init__(self, path: Path = FIXTURES_PATH) -> None:
        self._answers = {
            item["raw"]["hash"]: item.get("demo_classification") for item in load_fixtures(path)
        }

    def classify(self, pub: dict[str, Any]) -> LlmResult:
        answer = self._answers.get(pub.get("hash"))
        if not answer:
            return LlmResult(
                None, "", Usage(), False, "no fixture classification for this publication"
            )
        classification = Classification(**answer)
        _, truncated = build_prompt(pub)  # same excerpt path as the real classifier
        return LlmResult(
            classification, f"[fixture] {classification.rationale}", Usage(), truncated
        )
