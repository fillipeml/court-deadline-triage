"""Golden cases: the engine against dates computed by hand over the real calendars."""

import json
from datetime import date
from pathlib import Path

import pytest

from deadline_triage.court_calendar import Calendars, MissingCoverageError
from deadline_triage.engine import compute

CASES = json.loads((Path(__file__).parent / "golden" / "cases.json").read_text(encoding="utf-8"))[
    "cases"
]


@pytest.fixture(scope="module")
def calendars():
    return Calendars()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_case(case, calendars):
    expected = case["expected"]
    args = (
        date.fromisoformat(case["available_on"]),
        case["days"],
        case["regime"],
        case["court"],
        calendars,
    )
    if "missing_coverage" in expected:
        with pytest.raises(MissingCoverageError) as error:
            compute(*args)
        assert f"{error.value.court}/{error.value.year}" == expected["missing_coverage"]
        return
    r = compute(*args)
    assert r.published_on.isoformat() == expected["published_on"], case["reasoning"]
    assert r.start_on.isoformat() == expected["start_on"], case["reasoning"]
    assert r.due_on.isoformat() == expected["due_on"], case["reasoning"]
    uncertain_dates = sorted({u[6:10] + "-" + u[3:5] + "-" + u[0:2] for u in r.uncertain})
    assert uncertain_dates == sorted(expected.get("uncertain", []))
