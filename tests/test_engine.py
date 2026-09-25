"""Engine over synthetic calendars: edges the real calendars do not exercise."""

import json
from datetime import date

import pytest

from deadline_triage.court_calendar import Calendars, InvalidCalendarError, MissingCoverageError
from deadline_triage.engine import compute


def _write(root, court, year, days=(), periods=(), reviewed=True, coverage="complete"):
    folder = root / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{court}.json").write_text(
        json.dumps(
            {
                "court": court,
                "year": year,
                "version": "t",
                "source": {"url": "https://example.invalid/act"},
                "review": {"status": "reviewed" if reviewed else "pending"},
                "local_coverage": coverage,
                "days": list(days),
                "periods": list(periods),
            }  # fmt: skip
        ),
        encoding="utf-8",
    )


@pytest.fixture
def cal(tmp_path):
    for year in (2026, 2027):
        _write(tmp_path, "NATIONAL", year)
        _write(tmp_path, "TX", year)
    return tmp_path


def test_crosses_the_art_220_recess(cal):
    # available Thu 17/12/2026 -> published Fri 18/12 -> first day: 20/12-20/01 suspended -> Thu 21/01/2027
    r = compute(date(2026, 12, 17), 5, "business", "TX", Calendars(cal))
    assert r.published_on == date(2026, 12, 18)
    assert r.start_on == date(2027, 1, 21)
    assert r.due_on == date(2027, 1, 27)  # 21,22,25,26,27
    assert any("art. 220" in m for m in r.skipped_days)


def test_calendar_days_do_not_run_during_the_recess(cal):
    # first day 15/12 (1) ... 19/12 (5); 20/12-20/01 suspended; 21/01 (6) ... 25/01 (10)
    r = compute(date(2026, 12, 11), 10, "calendar", "TX", Calendars(cal))
    assert r.start_on == date(2026, 12, 15)
    assert r.due_on == date(2027, 1, 25)


def test_publication_during_a_closed_recess(cal):
    _write(
        cal,
        "TX",
        2026,
        periods=[
            {
                "start": "2026-12-20",
                "end": "2026-12-31",
                "description": "recess",
                "effect": "closed",
            }
        ],
    )
    _write(
        cal,
        "TX",
        2027,
        periods=[
            {
                "start": "2027-01-01",
                "end": "2027-01-06",
                "description": "recess",
                "effect": "closed",
            }
        ],
    )
    r = compute(date(2026, 12, 21), 5, "business", "TX", Calendars(cal))
    assert r.published_on == date(2027, 1, 7)  # first day with court business
    assert r.start_on == date(2027, 1, 21)  # open, but deadlines suspended until 20/01


def test_deadline_suspended_by_an_order(cal):
    _write(
        cal,
        "TX",
        2026,
        days=[{"date": "2026-09-24", "description": "order", "effect": "deadline_suspended"}],
    )
    r = compute(date(2026, 9, 21), 3, "business", "TX", Calendars(cal))
    assert r.due_on == date(2026, 9, 28)  # 23 (1), 24 suspended, 25 (2), 28 (3)


def test_district_holiday_applies_only_to_that_district(cal):
    _write(
        cal,
        "TX",
        2026,
        days=[
            {
                "date": "2026-09-24",
                "description": "patron saint",
                "effect": "closed",
                "scope": "districts",
                "districts": ["Anápolis"],
            }
        ],
    )
    c = Calendars(cal)
    anapolis = compute(date(2026, 9, 21), 3, "business", "TX", c, unit="ANAPOLIS - 2ª Vara Cível")
    goiania = compute(date(2026, 9, 21), 3, "business", "TX", c, unit="Goiânia - 1ª Vara Cível")
    assert anapolis.due_on == date(2026, 9, 28)  # 23, 25, 28
    assert goiania.due_on == date(2026, 9, 25)  # 23, 24, 25
    assert any("other districts" in w for w in goiania.warnings)


def test_review_and_local_coverage_warnings(cal):
    _write(cal, "TX", 2026, reviewed=False, coverage="partial")
    r = compute(date(2026, 9, 21), 3, "business", "TX", Calendars(cal))
    assert any("not yet reviewed" in w for w in r.warnings)
    assert any("municipal holidays" in w for w in r.warnings)


def test_reduced_hours_day_cannot_start_or_end_the_count(cal):
    _write(
        cal,
        "TX",
        2026,
        days=[{"date": "2026-09-22", "description": "half day", "effect": "reduced_hours"}],
    )
    r = compute(date(2026, 9, 21), 1, "business", "TX", Calendars(cal))
    assert r.published_on == date(2026, 9, 22)  # open, so it is the publication day
    assert r.start_on == date(2026, 9, 23) and r.due_on == date(2026, 9, 23)


def test_missing_national_calendar(tmp_path):
    _write(tmp_path, "TX", 2026)
    with pytest.raises(MissingCoverageError, match="NATIONAL/2026"):
        compute(date(2026, 9, 21), 3, "business", "TX", Calendars(tmp_path))


def test_invalid_inputs(cal):
    with pytest.raises(ValueError):
        compute(date(2026, 9, 21), 0, "business", "TX", Calendars(cal))
    with pytest.raises(ValueError):
        compute(date(2026, 9, 21), 5, "weeks", "TX", Calendars(cal))


def test_calendar_with_a_date_outside_its_year_is_rejected(cal):
    _write(cal, "TX", 2026, days=[{"date": "2027-01-02", "description": "x", "effect": "closed"}])
    with pytest.raises(InvalidCalendarError):
        compute(date(2026, 9, 21), 3, "business", "TX", Calendars(cal))


def test_summary_line(cal):
    r = compute(date(2026, 9, 21), 3, "business", "TX", Calendars(cal))
    assert r.summary().startswith("3 business days | available 21/09/2026 -> published 22/09/2026")
