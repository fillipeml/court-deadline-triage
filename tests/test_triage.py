"""Triage end to end: real state, real calendars, fake model."""

import json

import pytest

from deadline_triage.catalogue import Catalogue
from deadline_triage.classifier import Classification, LlmResult, Usage
from deadline_triage.court_calendar import Calendars
from deadline_triage.state import State
from deadline_triage.triage import triage_pending
from tests.conftest import cnj, digits

TJGO_MASKED = cnj("0000011", "8", "09", "0011")


def _pub(h, **kw):
    base = {
        "hash": h, "id": h, "case_number": digits(TJGO_MASKED), "case_number_masked": TJGO_MASKED,
        "court": "TJGO", "communication_type": "Intimação", "unit": "Goiânia - 1ª Vara Cível",
        "available_on": "2026-09-21", "text": "Intime-se o réu para contestar.", "active": True,
        "queried_bar": "12345/ZZ", "recipients": [], "lawyers": [],
    }  # fmt: skip
    return {**base, **kw}


class FakeLlm:
    def __init__(self, answers):
        self.answers = answers  # hash -> Classification | Exception

    def classify(self, pub):
        r = self.answers[pub["hash"]]
        if isinstance(r, Exception):
            raise r
        return LlmResult(r, "map", Usage(input=3000, output=500))


def _c(event_code, **kw):
    base = dict(
        opens_deadline=True, event_code=event_code, suggested_type=None, days_in_text=None, regime_in_text=None,
        double_deadline_hint=False, scheduled_date=None, confidence="high", rationale="answer",
        source_excerpt="Intime-se o réu para contestar.",
    )  # fmt: skip
    return Classification(**{**base, **kw})


@pytest.fixture
def env(tmp_path):
    state = State(tmp_path / "state.sqlite")
    yield state, Catalogue(), Calendars()
    state.close()


def test_answer_at_the_tjgo_gets_a_due_date(env):
    state, catalogue, cal = env
    state.register(_pub("h1"))
    llm = FakeLlm({"h1": _c(catalogue.by_name("Contestação").code)})
    r = triage_pending(state, llm, catalogue, cal, "claude-sonnet-5")
    assert r["by_action"] == {"CALCULATE": 1} and r["cost_usd"] > 0 and len(r["rows"]) == 1
    t = state.triages()[0]
    assert t["due_on"] == "2026-10-14"  # golden case A
    assert t["published_on"] == "2026-09-22" and t["start_on"] == "2026-09-23"
    assert "CPC, art. 335" in t["legal_grounds"] and "art. 224" in t["legal_grounds"]
    assert t["model"] == "claude-sonnet-5" and t["review_status"] == "pending"
    assert json.loads(t["audit_json"])["calendars"]


def test_court_without_a_calendar_becomes_priority_with_the_reason(env):
    state, catalogue, cal = env
    state.register(_pub("h2", court="STJ"))
    triage_pending(
        state, FakeLlm({"h2": _c(catalogue.by_name("Agravo Interno").code)}), catalogue, cal, "m"
    )
    t = state.triages()[0]
    assert t["action"] == "PRIORITY_REVIEW" and "STJ/2026" in t["reason"] and t["due_on"] is None
    assert (
        t["event_name"] == "Agravo Interno"
    )  # the deadline was identified; only the date is missing


def test_pre_filter_does_not_call_the_model(env):
    state, catalogue, cal = env
    state.register(_pub("h3", sealed=True, text="PROCESSO EM SEGREDO DE JUSTIÇA."))
    r = triage_pending(state, FakeLlm({}), catalogue, cal, "m")
    assert r["by_action"] == {"PRIORITY_REVIEW": 1} and r["with_llm"] == 0


def test_without_the_model_the_publication_stays_pending(env):
    state, catalogue, cal = env
    state.register(_pub("h4"))
    state.register(_pub("h5", communication_type="Lista de distribuição"))
    r = triage_pending(state, None, catalogue, cal, None)
    assert r["awaiting_llm"] == 1 and r["by_action"] == {"NO_DEADLINE": 1}
    assert [p["hash"] for p in state.pending_triage()] == ["h4"]


def test_a_model_failure_is_isolated_and_the_publication_stays_pending(env):
    state, catalogue, cal = env
    state.register(_pub("h6"))
    state.register(_pub("h7"))
    llm = FakeLlm(
        {"h6": RuntimeError("HTTP 529 overloaded"), "h7": _c(catalogue.by_name("Contestação").code)}
    )
    r = triage_pending(state, llm, catalogue, cal, "m")
    assert r["triaged"] == 1 and len(r["failures"]) == 1 and "529" in r["failures"][0]
    assert [p["hash"] for p in state.pending_triage()] == ["h6"]


def test_limit_controls_how_many_reach_the_model(env):
    state, catalogue, cal = env
    code = catalogue.by_name("Contestação").code
    for i in range(5):
        state.register(_pub(f"L{i}"))
    r = triage_pending(
        state, FakeLlm({f"L{i}": _c(code) for i in range(5)}), catalogue, cal, "m", limit=2
    )
    assert r["triaged"] == 2 and len(state.pending_triage()) == 3


def test_court_divergence_computes_but_prioritises(env):
    state, catalogue, cal = env
    state.register(_pub("h8", court="TRT18"))  # the number belongs to the TJGO
    triage_pending(
        state, FakeLlm({"h8": _c(catalogue.by_name("Contestação").code)}), catalogue, cal, "m"
    )
    t = state.triages()[0]
    assert t["action"] == "PRIORITY_REVIEW" and t["due_on"] is not None
    assert "diverges" in t["reason"]
