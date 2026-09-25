"""Deterministic decision: catalogue + model output -> what to do with the publication.

No date leaves this module; what leaves is the instruction for the engine (days and regime) or
the reason for review. Only what is mapped computes; in doubt, review, and priority review when
a deadline may be running.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .catalogue import Catalogue, Event
from .classifier import Classification

CALCULATE = "CALCULATE"
REVIEW = "REVIEW"
PRIORITY_REVIEW = "PRIORITY_REVIEW"
NO_DEADLINE = "NO_DEADLINE"

MODES_WITHOUT_DATE = {"NO_DEADLINE", "NO_FATAL_DEADLINE"}
MODES_HEARING = {"HEARING_DATE", "HEARING_ANCHORED"}


@dataclass
class Decision:
    action: str
    reason: str
    event: Event | None = None
    days: int | None = None
    regime: str | None = None
    warnings: list[str] = field(default_factory=list)


def pre_filter(pub: dict[str, Any]) -> Decision | None:
    """Cases resolved without the model (and without cost)."""
    if pub.get("sealed"):
        return Decision(
            PRIORITY_REVIEW, "sealed case: body not published in the gazette; check the case file"
        )
    if pub.get("active") is False or pub.get("cancelled_on"):
        reason = pub.get("cancellation_reason") or "no reason given"
        return Decision(
            PRIORITY_REVIEW, f"publication cancelled ({reason}); check for a republication"
        )
    kind = str(pub.get("communication_type") or "").lower()
    if "distribui" in kind:
        return Decision(NO_DEADLINE, "case-assignment list: opens no deadline")
    if not (pub.get("text") or "").strip():
        return Decision(PRIORITY_REVIEW, "publication without a body")
    return None


def decide(c: Classification, catalogue: Catalogue, require_validated: bool = False) -> Decision:
    warnings: list[str] = []
    if c.double_deadline_hint:
        warnings.append(
            "hint of a doubled deadline (CPC, arts. 180, 183, 186 or 229): not computed doubled"
        )

    if not c.opens_deadline:
        if c.confidence == "high" and not c.double_deadline_hint:
            return Decision(
                NO_DEADLINE, f"no deadline for the party: {c.rationale}", warnings=warnings
            )
        return Decision(
            REVIEW, f"model reports no deadline with {c.confidence} confidence", warnings=warnings
        )

    event = catalogue.get(c.event_code)
    if c.event_code is not None and event is None:
        return Decision(
            PRIORITY_REVIEW,
            f"model gave code {c.event_code}, absent from the catalogue",
            warnings=warnings,
        )
    if event is None:
        suggestion = c.suggested_type or "not described"
        return Decision(
            PRIORITY_REVIEW,
            f"deadline outside the catalogue; model suggests: {suggestion}",
            warnings=warnings,
        )

    if c.double_deadline_hint:
        return Decision(PRIORITY_REVIEW, "hint of a doubled deadline", event, warnings=warnings)
    if c.confidence == "low":
        return Decision(
            PRIORITY_REVIEW, "classification with low confidence", event, warnings=warnings
        )
    if require_validated and not event.validated:
        return Decision(
            REVIEW,
            f"event '{event.name}' not yet validated by the legal team",
            event,
            warnings=warnings,
        )

    mode = event.mode
    if mode in MODES_WITHOUT_DATE:
        return Decision(
            NO_DEADLINE, f"'{event.name}' has no legal due date", event, warnings=warnings
        )
    if mode in MODES_HEARING:
        when = f" (scheduled: {c.scheduled_date})" if c.scheduled_date else ""
        return Decision(
            REVIEW,
            f"'{event.name}' is a docket date, not a counted deadline{when}",
            event,
            warnings=warnings,
        )
    if mode == "AUTO":
        if c.days_in_text is not None and c.days_in_text != event.days_in_law:
            return Decision(
                PRIORITY_REVIEW,
                f"the act sets {c.days_in_text} days; the law provides {event.days_in_law} for '{event.name}'",
                event,
                warnings=warnings,
            )
        return Decision(
            CALCULATE,
            "legal deadline from the catalogue",
            event,
            event.days_in_law,
            event.regime or "business",
            warnings,
        )
    if mode == "DAYS_IN_TEXT":
        if c.days_in_text is None or c.days_in_text <= 0:
            return Decision(
                REVIEW,
                f"'{event.name}' depends on the deadline set in the act, which is not explicit",
                event,
                warnings=warnings,
            )
        regime = c.regime_in_text or event.regime or "business"
        return Decision(
            CALCULATE, "deadline set in the act", event, c.days_in_text, regime, warnings
        )
    return Decision(
        REVIEW, f"'{event.name}' requires a human check ({mode})", event, warnings=warnings
    )
