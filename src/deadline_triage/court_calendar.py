"""Versioned court calendars: `calendars/<year>/<COURT>.json`.

Each file transcribes the official act of the court (the bar association's index page is only
an index) and declares its source, version and human review status. `NATIONAL.json` is the
legal floor shared by every court. The suspension of CPC art. 220 (20 Dec to 20 Jan) is a rule
of law and lives in code.

Declared coverage: a court/year without a file raises `MissingCoverageError`; the engine does not
compute and the row goes to review with the reason.

Effects of a special day:
  closed              no court business: not a business day, not even for publication.
  reduced_hours       the court is open, but the day can be neither the first nor the last day
                      of a deadline (CPC, art. 224, §1).
  deadline_suspended  the court is open, but deadlines do not run (e.g. an administrative order).
A day with `confirmed: false` (e.g. an optional holiday without an act suspending deadlines) is
treated as a business day, because the earlier due date is the safe one, and reported as
uncertain for the lawyer to check.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import ROOT

CALENDARS_DIR = ROOT / "calendars"
NATIONAL = "NATIONAL"
EFFECTS = {"closed", "reduced_hours", "deadline_suspended"}
SCOPES = {"whole_court", "districts"}

ART_220 = "Deadlines suspended from 20 Dec to 20 Jan (CPC, art. 220; CLT, art. 775-A)"


class MissingCoverageError(RuntimeError):
    def __init__(self, court: str, year: int) -> None:
        super().__init__(f"no calendar loaded for {court}/{year}: not computed, human review")
        self.court = court
        self.year = year


class InvalidCalendarError(ValueError):
    pass


def _normalise(text: str) -> str:
    no_accents = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(no_accents.upper().split())


@dataclass(frozen=True)
class SpecialDay:
    day: date
    description: str
    effect: str
    scope: str = "whole_court"
    districts: tuple[str, ...] = ()
    confirmed: bool = True
    origin: str = ""  # "TJGO/2026", for the audit trail

    def label(self) -> str:
        return f"{self.day:%d/%m/%Y} {self.description} [{self.origin}]"


@dataclass
class CalendarFile:
    court: str
    year: int
    version: str
    reviewed: bool
    local_coverage: str
    days: list[SpecialDay] = field(default_factory=list)

    @property
    def identification(self) -> str:
        status = "reviewed" if self.reviewed else "review pending"
        return f"{self.court}/{self.year} v{self.version} ({status})"


def _read(path: Path) -> CalendarFile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise InvalidCalendarError(f"{path.name}: invalid JSON ({error})") from error
    court, year = str(raw.get("court", "")).upper(), int(raw.get("year", 0))
    if court != path.stem.upper() or year != int(path.parent.name):
        raise InvalidCalendarError(f"{path}: court/year in the content do not match the path")
    if not (raw.get("source") or {}).get("url") and court != NATIONAL:
        raise InvalidCalendarError(f"{path.name}: the official source (url) is mandatory")
    origin = f"{court}/{year}"
    days: list[SpecialDay] = []

    def validate(item: dict, day: date) -> tuple[str, str, tuple[str, ...]]:
        effect = item.get("effect", "closed")
        scope = item.get("scope", "whole_court")
        if effect not in EFFECTS or scope not in SCOPES:
            raise InvalidCalendarError(f"{path.name} {day}: invalid effect/scope")
        if day.year != year:
            raise InvalidCalendarError(f"{path.name} {day}: date outside the file's year")
        districts = tuple(_normalise(d) for d in item.get("districts") or [])
        if scope == "districts" and not districts:
            raise InvalidCalendarError(
                f"{path.name} {day}: district scope without a list of districts"
            )
        return effect, scope, districts

    for item in raw.get("days") or []:
        day = date.fromisoformat(item["date"])
        effect, scope, districts = validate(item, day)
        days.append(
            SpecialDay(
                day,
                item["description"],
                effect,
                scope,
                districts,
                bool(item.get("confirmed", True)),
                origin,
            )
        )
    for item in raw.get("periods") or []:
        start, end = date.fromisoformat(item["start"]), date.fromisoformat(item["end"])
        if end < start:
            raise InvalidCalendarError(f"{path.name}: period ends before it starts")
        effect, scope, districts = validate(item, end)
        validate(item, start)
        current = start
        while current <= end:
            days.append(
                SpecialDay(
                    current,
                    item["description"],
                    effect,
                    scope,
                    districts,
                    bool(item.get("confirmed", True)),
                    origin,
                )
            )
            current = date.fromordinal(current.toordinal() + 1)

    review = raw.get("review") or {}
    return CalendarFile(
        court, year, str(raw.get("version", "?")), review.get("status") == "reviewed",
        str(raw.get("local_coverage", "partial")), days,
    )  # fmt: skip


class Calendars:
    """Loads the files under `calendars/` on demand and keeps them cached."""

    def __init__(self, root: Path = CALENDARS_DIR) -> None:
        self._root = Path(root)
        self._cache: dict[tuple[str, int], CalendarFile | None] = {}

    def file(self, court: str, year: int) -> CalendarFile | None:
        key = (court.upper(), year)
        if key not in self._cache:
            path = self._root / str(year) / f"{key[0]}.json"
            self._cache[key] = _read(path) if path.exists() else None
        return self._cache[key]

    def require(self, court: str, year: int) -> tuple[CalendarFile, CalendarFile]:
        """(national, court) files of the year, or MissingCoverageError."""
        national = self.file(NATIONAL, year)
        if national is None:
            raise MissingCoverageError(NATIONAL, year)
        own = self.file(court, year)
        if own is None:
            raise MissingCoverageError(court.upper(), year)
        return national, own

    def available_courts(self, year: int) -> list[str]:
        folder = self._root / str(year)
        if not folder.is_dir():
            return []
        return sorted(p.stem for p in folder.glob("*.json") if p.stem != NATIONAL)


def in_art_220_suspension(d: date) -> bool:
    return (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 20)


@dataclass
class DayStatus:
    day: date
    open: bool  # the court has business hours
    counts: bool  # a deadline day (open and not suspended)
    reduced: bool
    suspended: bool  # deadlines do not run (art. 220 or an order); also stops calendar-day counts
    reasons: list[str]
    uncertain: list[str]
    not_applied_local: list[str]


class CourtCalendar:
    """View of one court (and, when given, of its unit/district) across years."""

    def __init__(self, calendars: Calendars, court: str, unit: str | None = None) -> None:
        self._calendars = calendars
        self.court = court.upper()
        self._unit = _normalise(unit) if unit else ""
        self.files_used: dict[tuple[str, int], CalendarFile] = {}

    def _applies(self, day: SpecialDay) -> bool:
        if day.scope == "whole_court":
            return True
        return bool(self._unit) and any(d in self._unit for d in day.districts)

    def status(self, d: date) -> DayStatus:
        national, own = self._calendars.require(self.court, d.year)
        for file in (national, own):
            self.files_used[(file.court, file.year)] = file
        is_open, suspended, reduced = d.weekday() < 5, False, False
        reasons: list[str] = []
        uncertain: list[str] = []
        local: list[str] = []
        for day in (x for file in (national, own) for x in file.days if x.day == d):
            if not self._applies(day):
                local.append(day.label())
                continue
            if not day.confirmed:
                uncertain.append(day.label())
                continue
            reasons.append(day.label())
            if day.effect == "closed":
                is_open = False
            elif day.effect == "reduced_hours":
                reduced = True
            elif day.effect == "deadline_suspended":
                suspended = True
        if in_art_220_suspension(d):
            suspended = True
            reasons.append(f"{d:%d/%m/%Y} {ART_220}")
        return DayStatus(
            d,
            is_open,
            is_open and not suspended,
            reduced and is_open,
            suspended,
            reasons,
            uncertain,
            local,
        )
