"""Rule-based triage of catalogue events into calculation modes.

Three orthogonal attributes decide whether a row can be computed without a human: the
**anchor** (which act the deadline counts from), the **regime** (business or calendar days)
and the **origin of the number of days** (fixed by law, or set in the judge's order). Only an
event anchored to the publication, with a known regime and days fixed by law, computes alone.

The rules read the Portuguese legal text of each event (`legal_deadline`, `legal_basis`),
because that is how the law is written. Order matters: the first matching rule wins. The output
is a draft; human validation (`validation.status`) is the final gate.
"""

from __future__ import annotations

import re

MODES: dict[str, str] = {
    "AUTO": "model classifies, engine computes, lawyer confirms",
    "DAYS_IN_TEXT": "the number of days comes from the order; the model extracts it; not explicit -> review",
    "CONDITIONAL": "a deadline exists only in a given hypothesis (depends on the text) -> review",
    "REVIEW": "body regulation, divergent case law or a different anchor -> human",
    "HEARING_DATE": "date set by the court (docket), not counted from the publication",
    "HEARING_ANCHORED": "anchored to the hearing, not to the publication",
    "NO_DEADLINE": "internal routine: no due date",
    "NO_FATAL_DEADLINE": "act admissible at any time: no legal due date",
}

_DAYS_IN_TEXT_BASIS = (
    "fixado no despacho",
    "fixado na decisão",
    "regimento de custas",
    "fixado pelo juízo",
)
_REVIEW_BASIS = (
    "validar", "confirmar", "analogia", "regulamento", "regimento", "uso corrente", "por aproximação",
    "fonaje", "jurisprudência",
)  # fmt: skip
_NO_FATAL = ("sem prazo fatal", "qualquer tempo", "antes da prática", "definido no próprio")


def regime_of(deadline_text: str, override: str | None = None) -> str | None:
    """ "business" | "calendar" | None. An explicit override (from the source) wins."""
    if override in {"business", "calendar"}:
        return override
    t = deadline_text.lower()
    if "corrido" in t or "decadencial" in t:
        return "calendar"
    if "úteis" in t or "uteis" in t:
        return "business"
    return None


def days_in_law(deadline_text: str) -> int | None:
    m = re.match(r"^\s*(\d+)\s*dias", deadline_text.lower())
    return int(m.group(1)) if m else None


def classify(name: str, kind: str, deadline_text: str, basis_text: str) -> tuple[str, str, str]:
    """Returns (mode, anchor, reason)."""
    d, b, n = deadline_text.lower(), basis_text.lower(), name.lower()

    # Small-claims courts: the counting regime is disputed (CPC art. 219 vs FONAJE statement 165).
    # The whole family stays in REVIEW until the legal team decides once and records it here.
    if "jec" in n or "inominado" in n or "9.099" in basis_text:
        return (
            "REVIEW",
            "publication",
            "small-claims court: business vs calendar days still open (FONAJE 165)",
        )

    if kind == "hearing":
        return "HEARING_DATE", "docket", "date set by the court"
    if "rotina interna" in d:
        return "NO_DEADLINE", "internal", "no procedural deadline of its own"
    if "pauta" in d:
        return "HEARING_DATE", "docket", "date set by the court"
    if "apresentada em audiência" in d:
        return "HEARING_ANCHORED", "hearing", "anchored to the hearing, not to the publication"
    if any(t in d for t in _NO_FATAL):
        return "NO_FATAL_DEADLINE", "n/a", "no legal due date"

    # the number of days comes from the judicial act, not from the law
    if any(t in b for t in _DAYS_IN_TEXT_BASIS) or "prazo fixado" in d or "usualmente fixado" in d:
        return (
            "DAYS_IN_TEXT",
            "publication",
            "the number of days comes from the order, not from the law",
        )

    # a deadline conditioned on a hypothesis the catalogue cannot resolve
    if "quando" in d:
        return (
            "CONDITIONAL",
            "publication",
            "a deadline exists only in a given hypothesis; depends on the text",
        )

    # the legal basis is not closed federal law
    if any(t in b for t in _REVIEW_BASIS) or "a validar" in d:
        return "REVIEW", "publication", "legal basis depends on a regulation or on case law"

    # anchor other than the publication
    if "decadencial" in d or "ato coator" in b:
        return "REVIEW", "challenged_act", "counted from the awareness of the challenged act"
    if "edital" in b or "relação de credores" in b:
        return "REVIEW", "edict", "counted from the publication of the edict or the creditors list"
    if "citação" in d or "depósito" in b or "penhora" in b or "arrematação" in d:
        return "REVIEW", "other_act", "counted from an act other than the publication"

    if days_in_law(deadline_text) is not None:
        regime = regime_of(deadline_text) or "business"
        return "AUTO", "publication", f"fixed legal deadline, counted in {regime} days"

    return "REVIEW", "undefined", "not matched by any rule: review by hand"
