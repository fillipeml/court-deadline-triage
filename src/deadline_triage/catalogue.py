"""Event catalogue (`catalogue/events.json`): the reference for the model and for the engine.

The model only chooses among catalogue events; each event's `mode` decides whether its due
date may be computed without a human (see catalogue_rules.MODES). A human validation block per
event is the final gate: with REQUIRE_VALIDATED_CATALOGUE, only validated events compute.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .config import ROOT

CATALOGUE_PATH = ROOT / "catalogue" / "events.json"
KINDS_FOR_LLM = {"judicial", "hearing"}


@dataclass(frozen=True)
class Event:
    code: int
    name: str  # as the legal term is known (Portuguese)
    name_en: str
    kind: str  # judicial | hearing
    legal_deadline: str
    legal_basis: str
    mode: str
    anchor: str
    regime: str | None
    days_in_law: int | None
    validated: bool

    @property
    def grounds(self) -> str:
        return f"{self.name} ({self.name_en}): {self.legal_deadline} | {self.legal_basis}"


class Catalogue:
    def __init__(self, path: Path = CATALOGUE_PATH) -> None:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.events: dict[int, Event] = {}
        for e in raw["events"]:
            validation = e.get("validation") or {}
            mode = validation.get("final_mode") or e["mode"]
            self.events[int(e["code"])] = Event(
                code=int(e["code"]),
                name=e["name"],
                name_en=e.get("name_en") or e["name"],
                kind=e["kind"],
                legal_deadline=e.get("legal_deadline") or "",
                legal_basis=e.get("legal_basis") or "",
                mode=mode,
                anchor=e.get("anchor") or "",
                regime=e.get("regime"),
                days_in_law=e.get("days_in_law"),
                validated=validation.get("status") in {"validated", "adjusted"},
            )

    def get(self, code: int | None) -> Event | None:
        return self.events.get(code) if code is not None else None

    def by_name(self, name: str) -> Event:
        return next(e for e in self.events.values() if e.name == name)

    @cached_property
    def table_for_llm(self) -> str:
        """Stable table (ordered by code) that goes into the cached system prompt."""
        lines = ["code | event | legal deadline | legal basis"]
        for e in sorted(self.events.values(), key=lambda x: x.code):
            if e.kind in KINDS_FOR_LLM:
                lines.append(
                    f"{e.code} | {e.name} ({e.name_en}) | {e.legal_deadline} | {e.legal_basis}"
                )
        return "\n".join(lines)
