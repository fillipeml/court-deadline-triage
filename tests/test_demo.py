"""The demo path end to end: fixtures -> sweep -> triage -> report, twice, offline."""

from datetime import date

import pytest

from deadline_triage import cli
from deadline_triage.catalogue import Catalogue
from deadline_triage.config import DEMO_REFERENCE_DATE, Config, parse_bar_numbers
from deadline_triage.court import parse_cnj
from deadline_triage.court_calendar import Calendars
from deadline_triage.demo import (
    FixtureClassifier,
    FixtureDjenClient,
    complete_case_number,
    load_fixtures,
)
from deadline_triage.excerpt import LIMIT
from deadline_triage.state import State
from deadline_triage.sweep import run
from deadline_triage.triage import triage_pending

EXPECTED = {
    "fixture-0001-answer": ("CALCULATE", "2026-10-14"),
    "fixture-0002-labour-appeal": ("CALCULATE", "2026-10-01"),
    "fixture-0003-five-days-in-text": ("CALCULATE", "2026-09-28"),
    "fixture-0004-court-without-calendar": ("PRIORITY_REVIEW", None),
    "fixture-0005-assignment-list": ("NO_DEADLINE", None),
    "fixture-0006-sealed": ("PRIORITY_REVIEW", None),
    "fixture-0007-cancelled": ("PRIORITY_REVIEW", None),
    "fixture-0008-mere-notice": ("NO_DEADLINE", None),
    "fixture-0009-public-treasury": ("PRIORITY_REVIEW", None),
    "fixture-0010-hearing-scheduled": ("REVIEW", None),
    "fixture-0011-long-appellate-decision": ("CALCULATE", "2026-10-01"),
    "fixture-0012-court-diverges-from-number": ("PRIORITY_REVIEW", "2026-10-14"),
}


def _config(tmp_path) -> Config:
    return Config(
        bar_numbers=parse_bar_numbers("12345/ZZ,67890/ZZ"), demo_mode=True, dry_run=True, window_days=3,
        reference_date=DEMO_REFERENCE_DATE, db_path=tmp_path / "state.sqlite", output_dir=tmp_path / "out",
    )  # fmt: skip


def test_fixture_case_numbers_are_completed_with_valid_check_digits():
    masked, digits = complete_case_number("0000101-XX.2099.8.09.0001")
    assert "-XX." not in masked and len(digits) == 20 and parse_cnj(masked).check_digits_valid
    for item in load_fixtures():
        number = item["raw"]["numero_processo"]
        assert len(number) == 20
    long_text = next(
        i for i in load_fixtures() if i["raw"]["hash"] == "fixture-0011-long-appellate-decision"
    )["raw"]["texto"]
    assert len(long_text) > LIMIT


def test_fixture_client_filters_by_bar_and_window():
    client = FixtureDjenClient()
    ana = list(client.list(parse_bar_numbers("12345/ZZ")[0], date(2026, 9, 18), date(2026, 9, 21)))
    bruno = list(
        client.list(parse_bar_numbers("67890/ZZ")[0], date(2026, 9, 18), date(2026, 9, 21))
    )
    assert len(ana) == 8 and len(bruno) == 5
    assert not list(
        client.list(parse_bar_numbers("12345/ZZ")[0], date(2026, 1, 1), date(2026, 1, 31))
    )


def test_fixture_classifier_replays_or_fails_explicitly():
    classifier = FixtureClassifier()
    ok = classifier.classify({"hash": "fixture-0001-answer", "text": "x"})
    assert ok.classification.event_code == 1 and ok.usage.cost_usd == 0
    missing = classifier.classify({"hash": "unknown", "text": "x"})
    assert missing.classification is None and "no fixture classification" in missing.failure


def test_demo_end_to_end_and_idempotent(tmp_path):
    config = _config(tmp_path)
    report = run(config, FixtureDjenClient())
    assert (report["listed"], report["new"], report["repeated"]) == (13, 12, 1)
    assert report["sealed"] == 1 and report["cancelled"] == 1

    state = State(config.db_path)
    try:
        r = triage_pending(state, FixtureClassifier(), Catalogue(), Calendars(), "fixture")
        assert r["by_action"] == {
            "CALCULATE": 4,
            "PRIORITY_REVIEW": 5,
            "NO_DEADLINE": 2,
            "REVIEW": 1,
        }
        assert r["awaiting_llm"] == 0 and r["failures"] == [] and r["cost_usd"] == 0
        rows = {t["hash"]: t for t in state.triages()}
        for h, (action, due) in EXPECTED.items():
            assert (rows[h]["action"], rows[h]["due_on"]) == (action, due), h
        assert "TJMG/2026" in rows["fixture-0004-court-without-calendar"]["reason"]
        assert "2026-10-20" in rows["fixture-0010-hearing-scheduled"]["reason"]
        assert "doubled" in rows["fixture-0009-public-treasury"]["reason"]
        assert "diverges" in rows["fixture-0012-court-diverges-from-number"]["reason"]
        assert '"truncated": true' in rows["fixture-0011-long-appellate-decision"]["llm_json"]
        assert rows["fixture-0001-answer"]["queried_bars"] == "12345/ZZ,67890/ZZ"
    finally:
        state.close()

    again = run(config, FixtureDjenClient())
    assert again["new"] == 0 and again["repeated"] == 13
    state = State(config.db_path)
    try:
        assert (
            triage_pending(state, FixtureClassifier(), Catalogue(), Calendars(), "fixture")[
                "pending"
            ]
            == 0
        )
    finally:
        state.close()


@pytest.mark.parametrize("dry_run", ["true", "false"])
def test_cli_demo_run_writes_csv_and_outbox(tmp_path, monkeypatch, capsys, dry_run):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DRY_RUN", dry_run)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr("sys.argv", ["deadline-triage"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "Source: DEMO (fixtures)" in out and "by action:" in out and "2026-10-14" in out
    assert (tmp_path / "out" / "triage-2026-09-21.csv").exists()
    outbox = (
        list((tmp_path / "out" / "outbox").glob("*.txt"))
        if (tmp_path / "out" / "outbox").exists()
        else []
    )
    assert (len(outbox) == 1) == (dry_run == "false")


def test_cli_compute_and_health(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "sys.argv", ["deadline-triage", "--compute", "2026-09-21", "15", "business", "TJGO"]
    )
    assert cli.main() == 0
    assert "DUE 14/10/2026" in capsys.readouterr().out
    monkeypatch.setattr(
        "sys.argv", ["deadline-triage", "--compute", "2026-09-21", "15", "business", "STJ"]
    )
    assert cli.main() == 3
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "none.sqlite"))
    monkeypatch.setattr("sys.argv", ["deadline-triage", "--health"])
    assert cli.main() == 1  # no run yet, dry run on
    assert "VERDICT: ATTENTION" in capsys.readouterr().out
