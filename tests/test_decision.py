import pytest

from deadline_triage.catalogue import Catalogue
from deadline_triage.classifier import Classification
from deadline_triage.decision import (
    CALCULATE,
    NO_DEADLINE,
    PRIORITY_REVIEW,
    REVIEW,
    decide,
    pre_filter,
)


@pytest.fixture(scope="module")
def catalogue():
    return Catalogue()


def _c(**kw) -> Classification:
    base = dict(
        opens_deadline=True, event_code=None, suggested_type=None, days_in_text=None, regime_in_text=None,
        double_deadline_hint=False, scheduled_date=None, confidence="high", rationale="r", source_excerpt="s",
    )  # fmt: skip
    return Classification(**{**base, **kw})


@pytest.mark.parametrize(
    "pub,action",
    [
        ({"sealed": True, "text": "x"}, PRIORITY_REVIEW),
        ({"active": False, "text": "x"}, PRIORITY_REVIEW),
        ({"cancelled_on": "2026-09-19", "text": "x"}, PRIORITY_REVIEW),
        ({"communication_type": "Lista de distribuição", "text": "x"}, NO_DEADLINE),
        ({"text": "  "}, PRIORITY_REVIEW),
        ({"text": "Intime-se.", "communication_type": "Intimação", "active": True}, None),
    ],
)
def test_pre_filter(pub, action):
    d = pre_filter(pub)
    assert (d.action if d else None) == action


def test_auto_computes_with_the_legal_days(catalogue):
    ev = catalogue.by_name("Contestação")
    d = decide(_c(event_code=ev.code), catalogue)
    assert (d.action, d.days, d.regime) == (CALCULATE, 15, "business")


def test_labour_auto_8_business_days(catalogue):
    ev = catalogue.by_name("Recurso Ordinário Trabalhista")
    d = decide(_c(event_code=ev.code), catalogue)
    assert (d.action, d.days, d.regime) == (CALCULATE, 8, "business")


def test_auto_with_divergent_days_in_the_act_goes_to_priority(catalogue):
    ev = catalogue.by_name("Contestação")
    assert decide(_c(event_code=ev.code, days_in_text=10), catalogue).action == PRIORITY_REVIEW
    assert decide(_c(event_code=ev.code, days_in_text=15), catalogue).action == CALCULATE


def test_days_in_text_uses_the_act_or_reviews(catalogue):
    ev = catalogue.by_name("Manifestação Diversa")
    d = decide(_c(event_code=ev.code, days_in_text=5), catalogue)
    assert (d.action, d.days, d.regime) == (CALCULATE, 5, "business")
    assert (
        decide(_c(event_code=ev.code, days_in_text=5, regime_in_text="calendar"), catalogue).regime
        == "calendar"
    )
    assert decide(_c(event_code=ev.code), catalogue).action == REVIEW


def test_outside_the_catalogue_and_invented_code(catalogue):
    assert decide(_c(suggested_type="deadline X"), catalogue).action == PRIORITY_REVIEW
    assert decide(_c(event_code=999_999), catalogue).action == PRIORITY_REVIEW


def test_double_hint_and_low_confidence_never_compute(catalogue):
    ev = catalogue.by_name("Apelação")
    d = decide(_c(event_code=ev.code, double_deadline_hint=True), catalogue)
    assert d.action == PRIORITY_REVIEW and any("doubled" in w for w in d.warnings)
    assert decide(_c(event_code=ev.code, confidence="low"), catalogue).action == PRIORITY_REVIEW


def test_no_deadline_only_with_high_confidence(catalogue):
    assert decide(_c(opens_deadline=False), catalogue).action == NO_DEADLINE
    assert decide(_c(opens_deadline=False, confidence="medium"), catalogue).action == REVIEW
    assert decide(_c(opens_deadline=False, double_deadline_hint=True), catalogue).action == REVIEW


def test_small_claims_and_hearings_go_to_review(catalogue):
    assert (
        decide(_c(event_code=catalogue.by_name("Recurso Inominado").code), catalogue).action
        == REVIEW
    )
    hearing = catalogue.by_name("Audiência de Conciliação")
    d = decide(_c(event_code=hearing.code, scheduled_date="2026-10-20"), catalogue)
    assert d.action == REVIEW and "2026-10-20" in d.reason


def test_no_fatal_deadline_events_close_without_a_date(catalogue):
    d = decide(_c(event_code=catalogue.by_name("Pedido de Reconsideração").code), catalogue)
    assert d.action == NO_DEADLINE


def test_require_validated_blocks_pending_events(catalogue):
    ev = catalogue.by_name("Apelação")
    assert decide(_c(event_code=ev.code), catalogue, require_validated=True).action == REVIEW
