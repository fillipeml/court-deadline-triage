"""Health check of the pilot: "silence is never success" applied to the routine itself.

Answers: did the sweep run when it should? Did it succeed? Is the configuration still sound? Is
there a calendar for every court that published? `deadline-triage --health`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from .config import Config
from .court_calendar import NATIONAL, Calendars
from .state import State

EXPECTED_HOUR_WITH_SLACK = 9  # the task runs at 08:00; we start asking at 09:00


def expected_last_business_day(now: datetime) -> date:
    """Date on which the last scheduled sweep should have happened."""
    d = now.date()
    if d.weekday() < 5 and now.hour >= EXPECTED_HOUR_WITH_SLACK:
        return d
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def check_calendars(
    courts: list[str], today: date, lines: list[str], calendars: Calendars | None = None
) -> list[str]:
    """A court with publications and no calendar does not compute. From 1 November the check also
    asks for next year: the art. 220 suspension pushes December deadlines into January."""
    calendars = calendars or Calendars()
    years = [today.year] + ([today.year + 1] if today.month >= 11 else [])
    problems: list[str] = []
    for year in years:
        available = set(calendars.available_courts(year))
        valid = [c for c in courts if c and c != "?"]
        covered = [c for c in valid if c.upper() in available]
        missing = [c for c in valid if c.upper() not in available]
        lines.append(f"Calendars {year}: covered {', '.join(covered) or 'none'}")
        if calendars.file(NATIONAL, year) is None:
            problems.append(f"calendar {NATIONAL}/{year} missing: no {year} deadline computes")
        if missing:
            problems.append(
                f"no {year} calendar for {', '.join(missing)}: publications of these courts go to review without a due date"
            )
    return problems


def report(
    config: Config, now: datetime | None = None, calendars: Calendars | None = None
) -> tuple[str, int]:
    """Returns (report text, exit code): 0 = healthy, 1 = attention."""
    now = now or datetime.now()
    problems: list[str] = []
    lines: list[str] = ["HEALTH OF THE PILOT: court deadline triage", ""]

    # 1. configuration
    if config.bar_numbers:
        lines.append(f"[ok] Monitored bar numbers: {', '.join(str(b) for b in config.bar_numbers)}")
    else:
        problems.append("BAR_NUMBERS empty: nothing will be swept")
    if config.dry_run:
        problems.append("DRY_RUN=true: the pilot is NOT sending real e-mails")
    else:
        lines.append("[ok] DRY_RUN=false (real delivery active)")
    if config.recipients or config.demo_mode:
        lines.append(f"[ok] Recipients: {', '.join(config.recipients) or 'demo outbox'}")
    else:
        problems.append("EMAIL_RECIPIENTS empty")

    # 2. runs
    if not Path(config.db_path).exists():
        problems.append("state database does not exist: no sweep has run on this machine")
    else:
        state = State(config.db_path)
        try:
            runs = state.recent_runs(5)
            summary = state.summary()
        finally:
            state.close()

        if not runs:
            problems.append("no run recorded in the history")
        else:
            last = runs[0]
            last_date = str(last["ran_at"])[:10]
            expected = expected_last_business_day(now).isoformat()
            if last_date < expected:
                problems.append(
                    f"last run was on {last_date}, but one was expected on {expected}: check the scheduled task and the machine"
                )
            else:
                lines.append(f"[ok] Last run: {last['ran_at']}")
            failures = [r for r in runs if not r["success"]]
            if failures and not runs[0]["success"]:
                problems.append(f"LAST run FAILED: {runs[0]['error']}")
            elif failures:
                lines.append(
                    f"[minor] {len(failures)} failure(s) in the last {len(runs)} runs (the most recent succeeded)"
                )
            lines.append("")
            lines.append("Recent runs:")
            for r in runs:
                status = "OK   " if r["success"] else "FAIL "
                lines.append(f"  {r['ran_at']}  {status} listed={r['listed']} new={r['new']}")
            lines.append(f"Known publications: {summary['total']} (sealed: {summary['sealed']})")

        # 3. calendar coverage for the courts that actually published
        lines.append("")
        problems.extend(check_calendars(list(summary["by_court"]), now.date(), lines, calendars))

    lines.append("")
    if problems:
        lines.append("VERDICT: ATTENTION")
        lines.extend(f"  ! {p}" for p in problems)
        return "\n".join(lines), 1
    lines.append("VERDICT: HEALTHY")
    return "\n".join(lines), 0
