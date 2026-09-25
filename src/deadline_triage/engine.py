"""Deterministic deadline engine: made available -> published -> first day -> due date.

The model never does this arithmetic. Rules:
  1st jump   publication = first day with court business after the day the act was made
             available (CPC, art. 224, §2; Law 11,419/2006, art. 4, §3).
  2nd jump   first day of the count = first business day after publication (CPC, art. 224, §3),
             which cannot be a reduced-hours day (art. 224, §1).
  counting   excludes the first day, includes the last (art. 224); business days (CPC, art. 219)
             or calendar days; the art. 220 suspension does not run.
  due date on a closed / reduced / suspended day -> next full business day (art. 224, §1).
It never estimates: a missing calendar anywhere in the period raises `MissingCoverageError`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from .court_calendar import Calendars, CourtCalendar, DayStatus

REGIMES = {"business", "calendar"}
HORIZON_DAYS = 400  # stop against an endless loop on a malformed calendar

GROUND_PUBLICATION = (
    "Published on the first business day after the act was made available "
    "(CPC, art. 224, §2; Law 11,419/2006, art. 4, §3)"
)
GROUND_START = "Counting starts on the first business day after publication (CPC, art. 224, §3)"
GROUND_BUSINESS = "Counted in business days (CPC, art. 219), excluding the first day and including the last (CPC, art. 224)"
GROUND_CALENDAR = (
    "Counted in calendar days, excluding the first day and including the last (CPC, art. 224)"
)
GROUND_EXTENSION = "Due date moved to the next business day (CPC, art. 224, §1)"
GROUND_REDUCED = (
    "A reduced-hours day can be neither the first nor the last day of the count (CPC, art. 224, §1)"
)


@dataclass
class Result:
    court: str
    available_on: date
    published_on: date
    start_on: date
    due_on: date
    days: int
    regime: str
    grounds: list[str]
    skipped_days: list[str] = field(default_factory=list)  # holidays / suspensions in the period
    uncertain: list[str] = field(default_factory=list)  # to confirm: they may push the date
    calendars: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.days} {self.regime} days | available {self.available_on:%d/%m/%Y} -> "
            f"published {self.published_on:%d/%m/%Y} -> first day {self.start_on:%d/%m/%Y} -> "
            f"DUE {self.due_on:%d/%m/%Y}"
        )


class _Walk:
    """Walks the calendar day by day while collecting the audit trail."""

    def __init__(self, cal: CourtCalendar) -> None:
        self.cal = cal
        self.skipped: list[str] = []
        self.uncertain: list[str] = []
        self.local: list[str] = []
        self._seen: set[date] = set()

    def look(self, d: date) -> DayStatus:
        s = self.cal.status(d)
        if d not in self._seen:
            self._seen.add(d)
            self.skipped += [r for r in s.reasons if r not in self.skipped]
            self.uncertain += [u for u in s.uncertain if u not in self.uncertain]
            self.local += [x for x in s.not_applied_local if x not in self.local]
        return s

    def next(self, after: date, criterion: Callable[[DayStatus], bool]) -> date:
        d = after
        for _ in range(HORIZON_DAYS):
            d += timedelta(days=1)
            if criterion(self.look(d)):
                return d
        raise RuntimeError(
            f"no valid day within {HORIZON_DAYS} days after {after}: malformed calendar?"
        )


def _full_business_day(s: DayStatus) -> bool:
    return s.counts and not s.reduced


def compute(
    available_on: date,
    days: int,
    regime: str,
    court: str,
    calendars: Calendars,
    unit: str | None = None,
) -> Result:
    if days <= 0:
        raise ValueError("the number of days must be positive")
    if regime not in REGIMES:
        raise ValueError(f"invalid regime {regime!r}: use {sorted(REGIMES)}")

    cal = CourtCalendar(calendars, court, unit)
    walk = _Walk(cal)
    grounds = [
        GROUND_PUBLICATION,
        GROUND_START,
        GROUND_BUSINESS if regime == "business" else GROUND_CALENDAR,
    ]

    published = walk.next(available_on, lambda s: s.open)
    start = walk.next(published, lambda s: s.counts)
    if walk.look(start).reduced:
        start = walk.next(start, _full_business_day)
        grounds.append(GROUND_REDUCED)

    counted, d = 1, start
    while counted < days:
        d += timedelta(days=1)
        s = walk.look(d)
        # in calendar days, holidays and weekends count; only a suspension stops the count
        if s.counts if regime == "business" else not s.suspended:
            counted += 1
        if (d - start).days > HORIZON_DAYS:
            raise RuntimeError("count exceeded the safety horizon: malformed calendar?")

    due = d
    s = walk.look(due)
    if not _full_business_day(s):
        due = walk.next(due, _full_business_day)
        grounds.append(GROUND_REDUCED if s.reduced and s.counts else GROUND_EXTENSION)

    warnings: list[str] = []
    if walk.uncertain:
        warnings.append(
            "day(s) with an unconfirmed effect in the period; the due date treats them as business days "
            "(the earlier date is the safe one). Check: " + "; ".join(walk.uncertain)
        )
    for file in cal.files_used.values():
        if not file.reviewed:
            warnings.append(f"calendar {file.identification} not yet reviewed by a human")
        if file.court != "NATIONAL" and file.local_coverage != "complete":
            warnings.append(
                f"calendar {file.court}/{file.year}: municipal holidays not loaded; check the district's holidays"
            )
    if walk.local:
        warnings.append(
            "holiday(s) of other districts in the period, not applied to this unit: "
            + "; ".join(walk.local)
        )

    return Result(
        court=cal.court,
        available_on=available_on,
        published_on=published,
        start_on=start,
        due_on=due,
        days=days,
        regime=regime,
        grounds=grounds,
        skipped_days=walk.skipped,
        uncertain=walk.uncertain,
        calendars=sorted(f.identification for f in cal.files_used.values()),
        warnings=warnings,
    )
