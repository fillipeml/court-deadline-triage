import pytest

from deadline_triage.court import acronym_for, parse_cnj, reference_court
from tests.conftest import cnj, digits


def test_parse_with_and_without_mask(tjgo_number):
    a, b = parse_cnj(tjgo_number), parse_cnj(digits(tjgo_number))
    assert a == b
    assert a.masked == tjgo_number
    assert (a.branch, a.court, a.unit) == ("8", "09", "0001")


def test_check_digits_valid_and_invalid(tjgo_number):
    assert parse_cnj(tjgo_number).check_digits_valid
    wrong = tjgo_number[:8] + f"{(int(tjgo_number[8:10]) + 1) % 100:02d}" + tjgo_number[10:]
    assert not parse_cnj(wrong).check_digits_valid


def test_number_outside_the_standard():
    assert parse_cnj("123") is None and parse_cnj(None) is None


@pytest.mark.parametrize(
    "branch,tr,acronym",
    [
        ("8", "09", "TJGO"),
        ("8", "07", "TJDFT"),
        ("8", "26", "TJSP"),
        ("8", "13", "TJMG"),
        ("5", "18", "TRT18"),
        ("5", "00", "TST"),
        ("4", "01", "TRF1"),
        ("3", "00", "STJ"),
        ("1", "00", "STF"),
        ("6", "09", "TRE-GO"),
        ("9", "26", "TJMSP"),
        ("8", "28", None),
        ("4", "07", None),
    ],  # fmt: skip
)
def test_acronym_for(branch, tr, acronym):
    assert acronym_for(branch, tr) == acronym


def test_reference_matches(tjgo_number):
    ref = reference_court(tjgo_number, "TJGO")
    assert ref.acronym == "TJGO" and not ref.divergent and ref.warnings == ()


def test_superior_court_with_origin_number_does_not_diverge(tjgo_number):
    ref = reference_court(tjgo_number, "STJ")
    assert ref.acronym == "STJ" and not ref.divergent
    assert "originated in TJGO" in ref.warnings[0]


def test_divergence_between_courts_of_the_same_level(tjgo_number):
    ref = reference_court(tjgo_number, "TJMG")
    assert ref.acronym == "TJMG" and ref.divergent


def test_without_acronym_the_number_decides(tjgo_number):
    ref = reference_court(tjgo_number, None)
    assert ref.acronym == "TJGO" and "derived from the CNJ number" in ref.warnings[-1]


def test_invalid_check_digits_become_a_warning():
    wrong = cnj("0000001", "8", "09")
    wrong = wrong[:8] + "00" + wrong[10:]
    ref = reference_court(wrong, "TJGO")
    assert any("check digits" in w for w in ref.warnings)
