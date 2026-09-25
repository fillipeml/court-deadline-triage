"""Output of a triage run: a console table, a CSV file and the text of the daily digest.

The five fields a lawyer needs are visible first (due date, action, deadline type, case, court);
the rest of the audit trail stays in the SQLite row.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any

COLUMNS = [
    "due_on",
    "action",
    "event_name",
    "case",
    "reference_court",
    "days",
    "regime",
    "published_on",
    "start_on",
    "reason",
]


def weekdays_until(today: date, due: date) -> int:
    """Weekdays (Mon-Fri) strictly after today up to and including the due date. An approximation
    for the URGENT flag: the exact business-day count, with holidays, is in the row itself."""
    if due <= today:
        return 0
    n, d = 0, today
    while d < due:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def is_urgent(due_on: str | None, today: date, urgent_business_days: int) -> bool:
    if not due_on:
        return False
    return weekdays_until(today, date.fromisoformat(due_on)) <= urgent_business_days


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"PRIORITY_REVIEW": 0, "CALCULATE": 1, "REVIEW": 2, "NO_DEADLINE": 3}
    return sorted(
        rows,
        key=lambda r: (
            r.get("due_on") is None,
            r.get("due_on") or "",
            order.get(r.get("action"), 9),
        ),
    )


def render_table(rows: list[dict[str, Any]], today: date, urgent_business_days: int) -> str:
    if not rows:
        return "(no triage rows)"
    lines = [f"{'DUE':<11} {'ACTION':<16} {'DEADLINE TYPE':<34} {'CASE':<26} {'COURT':<6} REASON"]
    for r in sort_rows(rows):
        due = r.get("due_on") or "-"
        flag = "!" if is_urgent(r.get("due_on"), today, urgent_business_days) else " "
        lines.append(
            f"{due:<11}{flag}{r.get('action', ''):<16} {(r.get('event_name') or '-')[:34]:<34} "
            f"{(r.get('case') or '-')[:26]:<26} {(r.get('reference_court') or '-')[:6]:<6} {(r.get('reason') or '')[:70]}"
        )
    return "\n".join(lines)


def write_csv(rows: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[*COLUMNS, "legal_grounds", "warnings_json", "hash"],
            extrasaction="ignore",
        )
        writer.writeheader()
        for r in sort_rows(rows):
            writer.writerow(r)
    return path


def render_digest(
    rows: list[dict[str, Any]], today: date, urgent_business_days: int
) -> tuple[str, str]:
    """(subject, body) of the daily digest for the team."""
    computed = [r for r in rows if r.get("due_on")]
    priority = [r for r in rows if r.get("action") == "PRIORITY_REVIEW"]
    urgent = [r for r in computed if is_urgent(r["due_on"], today, urgent_business_days)]
    flag = "[URGENT] " if urgent else ""
    subject = (
        f"{flag}Deadline triage {today:%d/%m/%Y}: "
        f"{len(computed)} dates computed, {len(priority)} priority reviews"
    )
    lines = [
        f"Triage of the court gazette publications, {today:%d/%m/%Y}.",
        "",
        f"Rows: {len(rows)} | dates computed: {len(computed)} | priority review: {len(priority)} | urgent: {len(urgent)}",
        "",
        "Every date below is a proposal for a lawyer to confirm; nothing is final without that confirmation.",
        "",
        render_table(rows, today, urgent_business_days),
        "",
        "Legend: ! = due within the urgent window · CALCULATE = date computed · PRIORITY_REVIEW = a deadline",
        "may be running and needs a human now · REVIEW = check when convenient · NO_DEADLINE = nothing to do.",
    ]
    return subject, "\n".join(lines)
