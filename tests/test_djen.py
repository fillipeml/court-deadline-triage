import json
from datetime import date

import pytest

from deadline_triage.config import BarNumber, Config
from deadline_triage.djen import PAGE_SIZE, ApiError, DjenClient, clean_text, is_sealed, normalise
from tests.conftest import cnj, digits

BAR = BarNumber("12345", "ZZ")
WINDOW = (date(2026, 9, 15), date(2026, 9, 18))
NUMBER = cnj("0000002", "8", "09")


class Response:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text or json.dumps(body or {})

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params)
        return self.responses.pop(0)


def _item(i, **extra):
    return {
        "id": i, "hash": f"h{i}", "texto": "Prazo de 15 (quinze) dias &uacute;teis",
        "numero_processo": digits(NUMBER), "siglaTribunal": "TJGO", "data_disponibilizacao": "2026-09-16", **extra,
    }  # fmt: skip


def _page(items, count):
    return {"status": "success", "message": "ok", "count": count, "items": items}


def test_clean_text_undoes_html_entities():
    assert (
        clean_text("Poder Judici&aacute;rio &ndash; prazo &gt; 5") == "Poder Judiciário – prazo > 5"
    )


def test_clean_text_keeps_paragraphs_and_normalises_spaces():
    assert clean_text("a   b\r\n\n\n\n   c\t d") == "a b\n\nc d"
    assert clean_text(None) == ""


def test_sealed_only_when_there_is_no_body():
    assert is_sealed(
        "PROCESSO EM SEGREDO DE JUSTIÇA. OS ARQUIVOS DA INTIMAÇÃO NÃO FORAM PUBLICADOS."
    )
    assert not is_sealed(
        "Processo em segredo de justiça. Intime-se o réu para contestar em 15 dias."
    )


def test_normalise_maps_lawyers_recipients_and_queried_bar():
    raw = _item(
        1,
        destinatarioadvogados=[
            {"advogado": {"nome": "Ana Exemplo", "numero_oab": "12345", "uf_oab": "ZZ"}}
        ],
        destinatarios=[{"nome": "Acme Ltda", "polo": "P"}],
        ativo=True,
    )
    pub = normalise(raw, BAR)
    assert pub["hash"] == "h1"
    assert pub["text"] == "Prazo de 15 (quinze) dias úteis"
    assert pub["lawyers"] == [{"name": "Ana Exemplo", "bar_number": "12345", "state": "ZZ"}]
    assert pub["recipients"] == [{"name": "Acme Ltda", "side": "P"}]
    assert pub["queried_bar"] == "12345/ZZ"
    assert pub["sealed"] is False and pub["court"] == "TJGO"


def test_pagination_follows_until_a_short_page():
    session = Session([
        Response(200, _page([_item(i) for i in range(PAGE_SIZE)], 150)),
        Response(200, _page([_item(i) for i in range(100, 150)], 150)),
    ])  # fmt: skip
    items = list(DjenClient(Config(), session).list(BAR, *WINDOW))
    assert len(items) == 150
    assert [c["pagina"] for c in session.calls] == [1, 2]
    assert session.calls[0]["numeroOab"] == "12345" and session.calls[0]["ufOab"] == "ZZ"
    assert session.calls[0]["dataDisponibilizacaoInicio"] == "2026-09-15"
    assert session.calls[0]["itensPorPagina"] == PAGE_SIZE


def test_empty_page_ends_without_error():
    session = Session([Response(200, _page([], 0))])
    assert list(DjenClient(Config(), session).list(BAR, *WINDOW)) == []


def test_count_cap_produces_a_warning():
    session = Session([Response(200, _page([_item(1)], 10_000))])
    client = DjenClient(Config(), session)
    list(client.list(BAR, *WINDOW))
    assert client.warnings and "cap" in client.warnings[0]


def test_4xx_does_not_retry():
    session = Session([Response(400, text="Bad Request")])
    with pytest.raises(ApiError, match="HTTP 400"):
        list(DjenClient(Config(), session).list(BAR, *WINDOW))
    assert len(session.calls) == 1


def test_5xx_retries_and_recovers(monkeypatch):
    monkeypatch.setattr("deadline_triage.djen.time.sleep", lambda _s: None)
    session = Session([Response(500, text="SHORTCIRCUIT"), Response(200, _page([_item(1)], 1))])
    items = list(DjenClient(Config(), session).list(BAR, *WINDOW))
    assert len(items) == 1 and len(session.calls) == 2


def test_error_status_in_the_body_becomes_api_error():
    session = Session(
        [Response(200, {"status": "error", "message": "invalid parameter", "items": []})]
    )
    with pytest.raises(ApiError, match="invalid parameter"):
        list(DjenClient(Config(), session).list(BAR, *WINDOW))
