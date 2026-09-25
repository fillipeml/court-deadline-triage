"""Triage: publication -> pre-filter -> model -> decision -> engine -> state.

Each publication is independent: an API failure on one does not bring the batch down, and the
publication stays pending for the next run (idempotency through the state).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from .catalogue import Catalogue
from .classifier import LlmResult, result_to_json
from .court import reference_court
from .court_calendar import Calendars, InvalidCalendarError, MissingCoverageError
from .decision import CALCULATE, PRIORITY_REVIEW, Decision, decide, pre_filter
from .engine import compute
from .state import State


def _legal_grounds(decision: Decision, grounds: list[str]) -> str | None:
    if decision.event is None:
        return None
    base = decision.event.grounds
    if decision.event.mode == "DAYS_IN_TEXT" and decision.days:
        base = (
            f"{decision.event.name} ({decision.event.name_en}): {decision.days} days set in the act"
            f" | {decision.event.legal_basis}"
        )
    return base + (" | " + " | ".join(grounds) if grounds else "")


def triage_publication(
    pub: dict[str, Any],
    classifier: Any | None,
    catalogue: Catalogue,
    calendars: Calendars,
    require_validated: bool = False,
) -> dict[str, Any] | None:
    """Returns the columns of the `triages` table for the publication, without writing. None means
    the model is needed and it is off: the publication stays pending for the next run."""
    ref = reference_court(pub.get("case_number"), pub.get("court"))
    warnings = list(ref.warnings)
    llm: LlmResult | None = None

    decision = pre_filter(pub)
    if decision is None:
        if classifier is None:
            return None
        llm = classifier.classify(pub)
        if llm.classification is None:
            decision = Decision(PRIORITY_REVIEW, f"no valid model answer: {llm.failure}")
        else:
            decision = decide(llm.classification, catalogue, require_validated)
    warnings += decision.warnings

    data: dict[str, Any] = {
        "action": decision.action,
        "reason": decision.reason,
        "event_code": decision.event.code if decision.event else None,
        "event_name": decision.event.name if decision.event else None,
        "mode": decision.event.mode if decision.event else None,
        "days": decision.days,
        "regime": decision.regime,
        "reference_court": ref.acronym,
        "confidence": llm.classification.confidence if llm and llm.classification else None,
        "source_excerpt": llm.classification.source_excerpt if llm and llm.classification else None,
        "llm_json": result_to_json(llm) if llm else None,
        "tokens_json": json.dumps(vars(llm.usage)) if llm else None,
        "cost_usd": round(llm.usage.cost_usd, 6) if llm else 0.0,
        "legal_grounds": _legal_grounds(decision, []),
    }

    if decision.action == CALCULATE:
        if ref.acronym is None:
            data.update(action=PRIORITY_REVIEW, reason="court not identified: no calendar")
        else:
            try:
                r = compute(
                    date.fromisoformat(pub["available_on"]),
                    decision.days,
                    decision.regime,
                    ref.acronym,
                    calendars,
                    unit=pub.get("unit"),
                )
            except MissingCoverageError as error:
                data.update(
                    action=PRIORITY_REVIEW,
                    reason=f"deadline identified, date not computed: {error}",
                )
            except (InvalidCalendarError, ValueError) as error:
                data.update(action=PRIORITY_REVIEW, reason=f"error in the computation: {error}")
            else:
                warnings += r.warnings
                data.update(
                    published_on=r.published_on.isoformat(),
                    start_on=r.start_on.isoformat(),
                    due_on=r.due_on.isoformat(),
                    legal_grounds=_legal_grounds(decision, r.grounds),
                    audit_json=json.dumps(
                        {
                            "grounds": r.grounds,
                            "skipped_days": r.skipped_days,
                            "uncertain": r.uncertain,
                            "calendars": r.calendars,
                        },
                        ensure_ascii=False,
                    ),
                )
                if ref.divergent:
                    data["action"] = PRIORITY_REVIEW
                    data["reason"] = (
                        "date computed, but the publishing court diverges from the CNJ number"
                    )
    data["warnings_json"] = json.dumps(warnings, ensure_ascii=False)
    return data


def triage_pending(
    state: State,
    classifier: Any | None,
    catalogue: Catalogue,
    calendars: Calendars,
    model: str | None,
    limit: int | None = None,
    require_validated: bool = False,
) -> dict[str, Any]:
    # without the model the limit does not apply: the pre-filter is free and the rest stays pending
    pending = state.pending_triage(limit if classifier is not None else None)
    counts: dict[str, int] = {}
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    awaiting_llm = 0
    cost = 0.0
    llm_calls = 0
    for pub in pending:
        try:
            data = triage_publication(pub, classifier, catalogue, calendars, require_validated)
        except Exception as error:  # noqa: BLE001 - one publication never brings the batch down; it stays pending
            failures.append(
                f"{pub.get('case_number_masked') or pub['hash']}: {type(error).__name__}: {error}"
            )
            continue
        if data is None:
            awaiting_llm += 1
            continue
        data["model"] = model if data.get("llm_json") else None
        state.record_triage(pub["hash"], data)
        counts[data["action"]] = counts.get(data["action"], 0) + 1
        cost += data.get("cost_usd") or 0.0
        llm_calls += 1 if data.get("llm_json") else 0
        rows.append(
            {
                "hash": pub["hash"],
                "case": pub.get("case_number_masked") or pub.get("case_number"),
                **data,
            }
        )
    return {
        "pending": len(pending),
        "triaged": sum(counts.values()),
        "by_action": counts,
        "failures": failures,
        "awaiting_llm": awaiting_llm,
        "with_llm": llm_calls,
        "cost_usd": round(cost, 4),
        "mean_cost_usd": round(cost / llm_calls, 5) if llm_calls else 0.0,
        "rows": rows,
    }
