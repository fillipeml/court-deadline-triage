from datetime import date, datetime

from deadline_triage.config import BarNumber, Config
from deadline_triage.court_calendar import Calendars
from deadline_triage.health import check_calendars, expected_last_business_day, report
from deadline_triage.state import State


def test_expected_last_business_day():
    assert expected_last_business_day(datetime(2026, 9, 24, 10)) == date(
        2026, 9, 24
    )  # Thu, after 9h
    assert expected_last_business_day(datetime(2026, 9, 24, 7)) == date(2026, 9, 23)  # before 9h
    assert expected_last_business_day(datetime(2026, 9, 27, 12)) == date(
        2026, 9, 25
    )  # Sunday -> Friday


def test_check_calendars_points_at_the_court_without_a_file():
    lines: list[str] = []
    problems = check_calendars(["TJGO", "TRT18", "TJMG"], date(2026, 9, 24), lines)
    assert any("TJMG" in p for p in problems)
    assert not any("TJGO" in p for p in problems)


def test_from_november_next_year_is_required():
    problems = check_calendars(["TJGO"], date(2026, 11, 3), [])
    assert any("2027" in p and "TJGO" in p for p in problems)


def test_healthy_report_with_a_run_and_calendars(tmp_path):
    db = tmp_path / "state.sqlite"
    state = State(db)
    state.register({"hash": "h1", "court": "TJGO", "queried_bar": "12345/ZZ", "text": "x"})
    state.record_run(success=True, listed=1, new=1)
    state.close()
    config = Config(
        bar_numbers=[BarNumber.parse("12345/ZZ")],
        dry_run=False,
        email_recipients="a@b.c",
        db_path=db,
    )
    text, code = report(config, now=datetime.now(), calendars=Calendars())
    assert code == 0, text
    assert "covered TJGO" in text


def test_missing_database_and_dry_run_are_flagged(tmp_path):
    config = Config(
        bar_numbers=[BarNumber.parse("12345/ZZ")], dry_run=True, db_path=tmp_path / "none.sqlite"
    )
    text, code = report(config)
    assert code == 1 and "DRY_RUN=true" in text and "does not exist" in text
