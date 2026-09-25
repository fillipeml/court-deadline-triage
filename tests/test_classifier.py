"""Excerpt, prompt assembly and the two-call classifier against a fake client."""

from types import SimpleNamespace

import pytest

from deadline_triage.catalogue import Catalogue
from deadline_triage.classifier import Classification, Classifier, Usage, build_prompt
from deadline_triage.excerpt import CUT_MARK, LIMIT, excerpt


@pytest.fixture(scope="module")
def catalogue():
    return Catalogue()


def _c(**kw) -> Classification:
    base = dict(
        opens_deadline=True, event_code=None, suggested_type=None, days_in_text=None, regime_in_text=None,
        double_deadline_hint=False, scheduled_date=None, confidence="high", rationale="r", source_excerpt="s",
    )  # fmt: skip
    return Classification(**{**base, **kw})


def test_short_text_passes_whole():
    assert excerpt("short") == ("short", False)


def test_long_text_keeps_head_tail_and_deadline_passages():
    middle = (
        ("lorem ipsum " * 3000)
        + " INTIME-SE a parte para se manifestar no prazo de 10 dias. "
        + ("dolor " * 3000)
    )
    text = "HEADER " + middle + " FINAL OPERATIVE PART"
    out, truncated = excerpt(text)
    assert truncated and len(out) <= LIMIT + 3 * len(CUT_MARK)
    assert out.startswith("HEADER") and out.endswith("FINAL OPERATIVE PART")
    assert "prazo de 10 dias" in out


def test_build_prompt_marks_truncation_and_lists_parties():
    text, truncated = build_prompt(
        {
            "text": "prazo " * 5000,
            "court": "TJGO",
            "recipients": [{"name": "Acme", "side": "P"}],
            "lawyers": [{"name": "Ana", "bar_number": "12345", "state": "ZZ"}],
        }
    )
    assert truncated and "long text shortened" in text
    assert "Acme (side P)" in text and "Ana bar 12345/ZZ" in text


class FakeClient:
    def __init__(self, legal_map="map of the act", parsed=None, stop1="end_turn", stop2="end_turn"):
        self.calls = []
        usage = SimpleNamespace(
            input_tokens=1000,
            output_tokens=200,
            cache_creation_input_tokens=5000,
            cache_read_input_tokens=0,
        )
        self.messages = SimpleNamespace(
            create=lambda **kw: self._record(
                "create",
                kw,
                SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=legal_map)],
                    stop_reason=stop1,
                    usage=usage,
                ),
            ),
            parse=lambda **kw: self._record(
                "parse", kw, SimpleNamespace(parsed_output=parsed, stop_reason=stop2, usage=usage)
            ),
        )

    def _record(self, name, kw, response):
        self.calls.append((name, kw))
        return response


def test_two_calls_share_a_cached_system_prompt(catalogue):
    client = FakeClient(parsed=_c(event_code=1))
    r = Classifier(catalogue, "claude-sonnet-5", client).classify(
        {"text": "Intime-se.", "court": "TJGO"}
    )
    (n1, k1), (n2, k2) = client.calls
    assert (n1, n2) == ("create", "parse")
    assert k1["system"] == k2["system"] and k1["system"][0]["cache_control"] == {
        "type": "ephemeral"
    }
    assert "Contestação" in k1["system"][0]["text"]
    assert k2["output_format"] is Classification
    assert "map of the act" in k2["messages"][0]["content"]
    assert r.classification.event_code == 1 and r.failure is None
    assert r.usage.input == 2000 and r.usage.cache_write == 10_000


def test_refusal_on_call_1_skips_call_2(catalogue):
    client = FakeClient(stop1="refusal")
    r = Classifier(catalogue, "m", client).classify({"text": "x"})
    assert r.classification is None and "refusal" in r.failure and len(client.calls) == 1


def test_invalid_json_becomes_a_failure(catalogue):
    r = Classifier(catalogue, "m", FakeClient(parsed=None)).classify({"text": "x"})
    assert r.classification is None and "call 2" in r.failure


def test_sonnet_5_cost():
    usage = Usage(input=1_000_000, output=100_000, cache_write=0, cache_read=1_000_000)
    assert usage.cost_usd == pytest.approx(2.0 + 1.0 + 0.2)
