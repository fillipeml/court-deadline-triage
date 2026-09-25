"""Unified case number (CNJ) -> court, and the reference court whose calendar governs a deadline.

Format (CNJ Resolution 65/2008): NNNNNNN-DD.YYYY.J.TR.OOOO
  J  = branch of the judiciary; TR = court or region; OOOO = originating unit.
  DD = 98 - (NNNNNNN YYYY J TR OOOO 00 mod 97).

The reference court is the `siglaTribunal` of the publication: that is where the act will be
performed, so its calendar rules the deadline. The court derived from the case number is a
cross-check. In a superior court (STF, STJ, TST, TSE, STM) it is normal for the number to point
at the court of origin of the appeal; anywhere else a divergence goes to review. Without an
acronym in the publication, the CNJ number decides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STATES = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SE", "SP", "TO",
]  # fmt: skip

SUPERIOR_COURTS = {"STF", "STJ", "TST", "TSE", "STM"}

_NON_DIGITS = re.compile(r"\D")


@dataclass(frozen=True)
class CnjNumber:
    sequence: str
    check_digits: str
    year: str
    branch: str
    court: str
    unit: str

    @property
    def masked(self) -> str:
        return f"{self.sequence}-{self.check_digits}.{self.year}.{self.branch}.{self.court}.{self.unit}"

    @property
    def check_digits_valid(self) -> bool:
        return int(self.check_digits) == expected_check_digits(
            self.sequence, self.year, self.branch, self.court, self.unit
        )

    @property
    def acronym(self) -> str | None:
        return acronym_for(self.branch, self.court)


def expected_check_digits(sequence: str, year: str, branch: str, court: str, unit: str) -> int:
    """Mod-97 check digits of a CNJ number (also used by tests to build synthetic numbers)."""
    return 98 - int(f"{sequence}{year}{branch}{court}{unit}00") % 97


def parse_cnj(text: str | None) -> CnjNumber | None:
    """Accepts the number with or without the mask. None unless it has exactly 20 digits."""
    digits = _NON_DIGITS.sub("", text or "")
    if len(digits) != 20:
        return None
    return CnjNumber(
        digits[0:7], digits[7:9], digits[9:13], digits[13], digits[14:16], digits[16:20]
    )


def acronym_for(branch: str, tr: str) -> str | None:
    try:
        n = int(tr)
    except ValueError:
        return None
    state = STATES[n - 1] if 1 <= n <= len(STATES) else None
    if branch == "1":
        return "STF"
    if branch == "2":
        return "CNJ"
    if branch == "3":
        return "STJ"
    if branch == "4":
        return f"TRF{n}" if 1 <= n <= 6 else None
    if branch == "5":
        return "TST" if n == 0 else (f"TRT{n}" if 1 <= n <= 24 else None)
    if branch == "6":
        return "TSE" if n == 0 else (f"TRE-{state}" if state else None)
    if branch == "7":
        return "STM" if n == 0 else None
    if branch == "8":
        return ("TJDFT" if state == "DF" else f"TJ{state}") if state else None
    if branch == "9":
        return {13: "TJMMG", 21: "TJMRS", 26: "TJMSP"}.get(n)
    return None


def _normalise(acronym: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (acronym or "").upper())


@dataclass(frozen=True)
class CourtReference:
    acronym: str | None
    cnj_acronym: str | None
    divergent: bool
    warnings: tuple[str, ...]


def reference_court(case_number: str | None, published_by: str | None) -> CourtReference:
    cnj = parse_cnj(case_number)
    warnings: list[str] = []
    cnj_acronym = cnj.acronym if cnj else None
    if cnj is None:
        warnings.append("case number outside the CNJ standard (20 digits)")
    elif not cnj.check_digits_valid:
        warnings.append(f"invalid check digits in CNJ number {cnj.masked}")

    acronym = (published_by or "").strip().upper() or None
    if acronym is None:
        return CourtReference(
            cnj_acronym, cnj_acronym, False, (*warnings, "court derived from the CNJ number")
        )
    if cnj_acronym is None or _normalise(acronym) == _normalise(cnj_acronym):
        return CourtReference(acronym, cnj_acronym, False, tuple(warnings))
    if _normalise(acronym) in SUPERIOR_COURTS:
        warnings.append(f"case originated in {cnj_acronym}, published by {acronym}")
        return CourtReference(acronym, cnj_acronym, False, tuple(warnings))
    warnings.append(f"publishing court ({acronym}) diverges from the CNJ number ({cnj_acronym})")
    return CourtReference(acronym, cnj_acronym, True, tuple(warnings))
