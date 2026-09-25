"""Catalogue rules, the built catalogue and its consistency with the source."""

import json

import pytest

from deadline_triage.catalogue import CATALOGUE_PATH, Catalogue
from deadline_triage.catalogue_build import SOURCE_PATH, build_events
from deadline_triage.catalogue_rules import classify, days_in_law, regime_of


@pytest.fixture(scope="module")
def catalogue():
    return Catalogue()


@pytest.mark.parametrize(
    "name,kind,deadline,basis,mode,anchor",
    [
        ("Contestação", "judicial", "15 dias úteis", "CPC, art. 335", "AUTO", "publication"),
        (
            "Recurso Ordinário Trabalhista",
            "judicial",
            "8 dias úteis",
            "CLT, art. 895",
            "AUTO",
            "publication",
        ),
        (
            "Manifestação Diversa",
            "judicial",
            "Prazo fixado no despacho",
            "Prazo fixado no despacho judicial",
            "DAYS_IN_TEXT",
            "publication",
        ),
        (
            "Juntada de Guia de Custas",
            "judicial",
            "Prazo fixado no despacho",
            "Regimento de custas do tribunal",
            "DAYS_IN_TEXT",
            "publication",
        ),
        (
            "Alegações Finais",
            "judicial",
            "15 dias úteis (quando por memorial escrito)",
            "CPC, art. 364",
            "CONDITIONAL",
            "publication",
        ),
        (
            "Recurso Inominado",
            "judicial",
            "10 dias",
            "Lei 9.099/1995, art. 42",
            "REVIEW",
            "publication",
        ),
        (
            "Mandado de Segurança",
            "judicial",
            "120 dias corridos (decadencial)",
            "Lei 12.016/2009",
            "REVIEW",
            "challenged_act",
        ),
        (
            "Habilitação de Crédito",
            "judicial",
            "15 dias",
            "contados da publicação do edital",
            "REVIEW",
            "edict",
        ),
        (
            "Embargos à Execução Fiscal",
            "judicial",
            "30 dias úteis",
            "LEF, art. 16; contados do depósito",
            "REVIEW",
            "other_act",
        ),
        (
            "Recurso Administrativo",
            "judicial",
            "10 dias",
            "Lei 9.784/1999; validar o regulamento",
            "REVIEW",
            "publication",
        ),
        (
            "Audiência de Conciliação",
            "hearing",
            "Data de pauta",
            "ato de pauta",
            "HEARING_DATE",
            "docket",
        ),
        (
            "Assembleia Geral de Credores",
            "judicial",
            "Data de pauta",
            "Lei 11.101/2005, art. 36",
            "HEARING_DATE",
            "docket",
        ),
        (
            "Contestação Trabalhista",
            "judicial",
            "Apresentada em audiência",
            "CLT, art. 847",
            "HEARING_ANCHORED",
            "hearing",
        ),
        (
            "Exceção de Pré-Executividade",
            "judicial",
            "Sem prazo fatal legal fixo",
            "a qualquer tempo",
            "NO_FATAL_DEADLINE",
            "n/a",
        ),
        (
            "Acompanhamento",
            "judicial",
            "Rotina interna",
            "sem prazo legal",
            "NO_DEADLINE",
            "internal",
        ),
        ("Coisa estranha", "judicial", "depende", "sem base", "REVIEW", "undefined"),
    ],
)
def test_classify(name, kind, deadline, basis, mode, anchor):
    assert classify(name, kind, deadline, basis)[:2] == (mode, anchor)


def test_regime_and_days():
    assert regime_of("15 dias úteis") == "business" and regime_of("120 dias corridos") == "calendar"
    assert regime_of("10 dias") is None and regime_of("10 dias", "calendar") == "calendar"
    assert (
        days_in_law("15 dias úteis para pagamento") == 15 and days_in_law("Até 5 dias após") is None
    )


def test_built_catalogue_reads_modes_and_days(catalogue):
    answer = catalogue.by_name("Contestação")
    assert (answer.mode, answer.days_in_law, answer.regime) == ("AUTO", 15, "business")
    assert catalogue.by_name("Recurso Ordinário Trabalhista").days_in_law == 8
    assert catalogue.by_name("Manifestação Diversa").mode == "DAYS_IN_TEXT"
    assert (
        catalogue.by_name("Recurso Voluntário").regime == "calendar"
    )  # explicit override in the source
    assert catalogue.by_name("Audiência de Conciliação").mode == "HEARING_DATE"
    assert not catalogue.by_name("Apelação").validated  # nothing validated yet


def test_table_for_llm_has_codes_and_glosses(catalogue):
    table = catalogue.table_for_llm
    assert table.startswith("code | event | legal deadline | legal basis")
    assert "Contestação (Answer to the complaint)" in table
    assert catalogue.get(None) is None and catalogue.get(999_999) is None


def test_build_preserves_existing_validation_and_rejects_duplicates():
    source = [
        {
            "code": 1,
            "name": "Contestação",
            "name_en": "Answer",
            "kind": "judicial",
            "legal_deadline": "15 dias úteis",
            "legal_basis": "CPC, art. 335",
        },
    ]
    previous = {
        1: {
            "validation": {
                "status": "validated",
                "by": "legal team",
                "on": "2026-10-01",
                "final_mode": None,
                "note": None,
            }
        }
    }
    built = build_events(source, previous)
    assert built[0]["validation"]["status"] == "validated" and built[0]["mode"] == "AUTO"
    with pytest.raises(ValueError, match="duplicate"):
        build_events(source + source)


def test_committed_catalogue_matches_its_source():
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))["events"]
    committed = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    previous = {int(e["code"]): e for e in committed["events"]}
    assert build_events(source, previous) == committed["events"]
    assert committed["total"] == len(source)
