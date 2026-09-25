"""Alerts to the team. DRY_RUN prints; otherwise the configured mailer delivers.

"Silence is never success": a failed sweep must produce an alert, and the alert code must never
raise, because the original failure is the headline.
"""

from __future__ import annotations

from typing import Any

from .config import Config
from .mail import Mailer

DEMO_RECIPIENT = "review-desk@example.invalid"


def summary(report: dict[str, Any]) -> str:
    """Readable summary of the sweep, for the console/log."""
    lines = [
        f"Period: {report['period']} | bars: {', '.join(report['bars'])}",
        f"Listed: {report['listed']} | new: {report['new']} | repeated/already known: {report['repeated']}",
    ]
    for bar, n in report.get("by_bar", {}).items():
        lines.append(f"  {bar}: listed={n['listed']} new={n['new']}")
    if report.get("sealed"):
        lines.append(f"Without a body (sealed case): {report['sealed']}")
    if report.get("cancelled"):
        lines.append(f"Cancelled: {report['cancelled']}")
    for warning in report.get("warnings", []):
        lines.append(f"WARNING: {warning}")
    return "\n".join(lines)


def _recipients(config: Config) -> list[str]:
    return config.recipients or ([DEMO_RECIPIENT] if config.demo_mode else [])


def send_failure(config: Config, mailer: Mailer, error: str) -> bool:
    """Failure alert of the sweep. Best effort: never raises."""
    subject = "[FAILURE] Court deadline triage did NOT run: check today's publications by hand"
    body = (
        "The automated sweep of the court gazette (DJEN) FAILED.\n\n"
        f"Error: {error}\n\n"
        "Immediate action: check today's publications manually (https://comunica.pje.jus.br) "
        "and call the person responsible for the automation.\n\n"
        "Automated message from court-deadline-triage."
    )
    try:
        if config.dry_run:
            print(f"[DRY_RUN] {subject}")
            print(body)
            return False
        if not config.demo_mode:
            config.require_email()
        mailer.send(subject, body, _recipients(config))
        return True
    except Exception as exc:  # noqa: BLE001 - the safety net must not bring the process down
        print(f"WARNING: the failure alert could not be sent either: {exc}")
        return False


def send_digest(config: Config, mailer: Mailer, subject: str, body: str) -> bool:
    """Daily triage digest. Same best-effort contract as the failure alert."""
    try:
        if config.dry_run:
            print(f"[DRY_RUN] {subject}")
            return False
        if not config.demo_mode:
            config.require_email()
        mailer.send(subject, body, _recipients(config))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: the digest could not be sent: {exc}")
        return False
