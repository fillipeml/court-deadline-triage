from datetime import date
from types import SimpleNamespace

import pytest

from deadline_triage.alerts import send_digest, send_failure, summary
from deadline_triage.config import Config
from deadline_triage.mail import GraphMailer, MailError, OutboxMailer
from deadline_triage.report import (
    is_urgent,
    render_digest,
    render_table,
    sort_rows,
    weekdays_until,
    write_csv,
)

TODAY = date(2026, 9, 21)
ROWS = [
    {
        "hash": "a",
        "action": "CALCULATE",
        "event_name": "Contestação",
        "case": "0000101-00.2099.8.09.0001",
        "reference_court": "TJGO",
        "days": 15,
        "regime": "business",
        "published_on": "2026-09-22",
        "start_on": "2026-09-23",
        "due_on": "2026-10-14",
        "reason": "legal deadline",
        "legal_grounds": "g",
        "warnings_json": "[]",
    },
    {
        "hash": "b",
        "action": "CALCULATE",
        "event_name": "Manifestação Diversa",
        "case": "x",
        "reference_court": "TJGO",
        "days": 5,
        "regime": "business",
        "published_on": "2026-09-21",
        "start_on": "2026-09-22",
        "due_on": "2026-09-23",
        "reason": "set in the act",
        "legal_grounds": "g",
        "warnings_json": "[]",
    },
    {
        "hash": "c",
        "action": "PRIORITY_REVIEW",
        "event_name": None,
        "case": "y",
        "reference_court": "TJGO",
        "days": None,
        "regime": None,
        "published_on": None,
        "start_on": None,
        "due_on": None,
        "reason": "sealed",
        "legal_grounds": None,
        "warnings_json": "[]",
    },
    {
        "hash": "d",
        "action": "NO_DEADLINE",
        "event_name": None,
        "case": "z",
        "reference_court": "TJGO",
        "days": None,
        "regime": None,
        "published_on": None,
        "start_on": None,
        "due_on": None,
        "reason": "notice",
        "legal_grounds": None,
        "warnings_json": "[]",
    },
]


def test_weekdays_and_urgency():
    assert weekdays_until(TODAY, date(2026, 9, 23)) == 2  # Tue, Wed
    assert weekdays_until(TODAY, date(2026, 9, 28)) == 5  # skips the weekend
    assert weekdays_until(TODAY, TODAY) == 0
    assert (
        is_urgent("2026-09-23", TODAY, 3)
        and not is_urgent("2026-10-14", TODAY, 3)
        and not is_urgent(None, TODAY, 3)
    )


def test_sort_puts_dated_rows_first_then_priority_reviews():
    assert [r["hash"] for r in sort_rows(ROWS)] == ["b", "a", "c", "d"]


def test_table_and_digest():
    table = render_table(ROWS, TODAY, 3)
    assert table.splitlines()[1].startswith("2026-09-23 !CALCULATE")  # urgent flag
    subject, body = render_digest(ROWS, TODAY, 3)
    assert subject.startswith(
        "[URGENT] Deadline triage 21/09/2026: 2 dates computed, 1 priority reviews"
    )
    assert "Every date below is a proposal for a lawyer to confirm" in body
    assert render_table([], TODAY, 3) == "(no triage rows)"


def test_csv_has_the_visible_columns_first(tmp_path):
    path = write_csv(ROWS, tmp_path / "out" / "triage.csv")
    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("due_on,action,event_name,case,reference_court") and header.endswith(
        "hash"
    )


def test_outbox_mailer_writes_a_file(tmp_path):
    mailer = OutboxMailer(tmp_path / "outbox")
    mailer.send("Hello: test", "body", ["a@example.invalid"])
    text = mailer.sent[0].read_text(encoding="utf-8")
    assert text.startswith("To: a@example.invalid\nSubject: Hello: test\n\nbody")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.responses.pop(0)


def test_graph_mailer_gets_a_token_then_sends():
    config = Config(
        graph_tenant_id="t",
        graph_client_id="c",
        graph_client_secret="s",
        email_sender="bot@example.invalid",
    )
    session = FakeSession([
        SimpleNamespace(status_code=200, json=lambda: {"access_token": "tok", "expires_in": 3600}, text=""),
        SimpleNamespace(status_code=202, text=""),
    ])  # fmt: skip
    GraphMailer(config, session).send("s", "b", ["a@example.invalid"])
    token_url, send = session.calls[0][0], session.calls[1]
    assert "login.microsoftonline.com/t/" in token_url
    assert (
        send[0].endswith("/users/bot@example.invalid/sendMail")
        and send[1]["headers"]["Authorization"] == "Bearer tok"
    )
    assert send[1]["json"]["message"]["toRecipients"] == [
        {"emailAddress": {"address": "a@example.invalid"}}
    ]


def test_graph_mailer_raises_on_failure():
    config = Config(
        graph_tenant_id="t",
        graph_client_id="c",
        graph_client_secret="s",
        email_sender="x@example.invalid",
    )
    session = FakeSession([SimpleNamespace(status_code=401, text="denied")])
    with pytest.raises(MailError, match="token failed"):
        GraphMailer(config, session).send("s", "b", ["a@example.invalid"])
    with pytest.raises(MailError, match="No recipient"):
        GraphMailer(config, FakeSession([])).send("s", "b", [])


def test_summary_lines():
    text = summary(
        {
            "period": "p",
            "bars": ["12345/ZZ"],
            "listed": 3,
            "new": 2,
            "repeated": 1,
            "by_bar": {"12345/ZZ": {"listed": 3, "new": 2}},
            "sealed": 1,
            "cancelled": 0,
            "warnings": ["w"],
        }
    )
    assert "Listed: 3 | new: 2" in text and "sealed case): 1" in text and "WARNING: w" in text


def test_send_failure_prints_in_dry_run_and_never_raises(tmp_path, capsys):
    assert send_failure(Config(dry_run=True), OutboxMailer(tmp_path), "boom") is False
    assert "[DRY_RUN] [FAILURE]" in capsys.readouterr().out
    # real mode without Graph configuration: reports False instead of raising
    assert send_failure(Config(dry_run=False), OutboxMailer(tmp_path), "boom") is False
    assert "could not be sent" in capsys.readouterr().out


def test_demo_mode_delivers_to_the_outbox_without_graph_settings(tmp_path):
    config = Config(dry_run=False, demo_mode=True)
    mailer = OutboxMailer(tmp_path / "outbox")
    assert send_failure(config, mailer, "boom") is True
    assert send_digest(config, mailer, "subject", "body") is True
    assert len(mailer.sent) == 2 and "review-desk@example.invalid" in mailer.sent[0].read_text(
        encoding="utf-8"
    )
