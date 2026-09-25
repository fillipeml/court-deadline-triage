from deadline_triage.state import State, publication_key
from tests.conftest import cnj, digits

PUB = {
    "hash": "abc123", "id": 1, "case_number": digits(cnj("0000003", "8", "09")), "court": "TJGO",
    "document_type": "Despacho", "available_on": "2026-09-16", "text": "Intime-se.",
    "recipients": [{"name": "A", "side": "P"}], "lawyers": [], "queried_bar": "12345/ZZ",
    "sealed": False, "active": True,
}  # fmt: skip


def test_idempotent_by_hash(tmp_path):
    state = State(tmp_path / "state.sqlite")
    assert state.register(PUB) is True
    assert state.register(PUB) is False
    assert state.summary()["total"] == 1
    state.close()


def test_same_publication_through_another_bar_accumulates(tmp_path):
    state = State(tmp_path / "state.sqlite")
    state.register(PUB)
    assert state.register({**PUB, "queried_bar": "67890/ZZ"}) is False
    bars = state._conn.execute(
        "SELECT queried_bars FROM publications WHERE hash = 'abc123'"
    ).fetchone()[0]
    assert bars == "12345/ZZ,67890/ZZ"
    assert state.summary()["total"] == 1
    state.close()


def test_key_falls_back_to_id_then_to_a_stable_synthetic_key():
    assert publication_key({**PUB, "hash": None}) == "ID/1"
    synthetic = publication_key({**PUB, "hash": None, "id": None})
    assert synthetic.startswith("NO-ID/") and synthetic == publication_key(
        {**PUB, "hash": None, "id": None}
    )


def test_summary_groups_by_court_and_document(tmp_path):
    state = State(tmp_path / "state.sqlite")
    state.register(PUB)
    state.register(
        {**PUB, "hash": "other", "court": "TRT18", "document_type": "Sentença", "sealed": True}
    )
    summary = state.summary()
    assert summary["by_court"] == {"TJGO": 1, "TRT18": 1}
    assert summary["by_document"]["Sentença"] == 1
    assert summary["sealed"] == 1
    state.close()


def test_pending_and_triage_round_trip(tmp_path):
    state = State(tmp_path / "state.sqlite")
    state.register(PUB)
    pending = state.pending_triage()
    assert [p["hash"] for p in pending] == ["abc123"] and pending[0]["recipients"] == [
        {"name": "A", "side": "P"}
    ]
    state.record_triage("abc123", {"action": "NO_DEADLINE", "reason": "test", "cost_usd": 0.0})
    assert state.pending_triage() == []
    rows = state.triages()
    assert (
        rows[0]["action"] == "NO_DEADLINE"
        and rows[0]["review_status"] == "pending"
        and rows[0]["queried_bars"] == "12345/ZZ"
    )
    state.close()


def test_recent_runs(tmp_path):
    state = State(tmp_path / "state.sqlite")
    state.record_run(success=True, bars=["12345/ZZ"], listed=3, new=2, dry_run=True)
    state.record_run(success=False, error="HTTP 500")
    recent = state.recent_runs(5)
    assert recent[0]["success"] == 0 and recent[0]["error"] == "HTTP 500"
    assert recent[1]["bars"] == "12345/ZZ" and recent[1]["new"] == 2
    state.close()
