from datetime import date

import pytest

from deadline_triage.config import (
    DEMO_REFERENCE_DATE,
    ROOT,
    BarNumber,
    Config,
    load_dotenv,
    parse_bar_numbers,
)


def test_parse_bar_number_normalises_spaces_and_state():
    bar = BarNumber.parse(" 12345/zz ")
    assert bar == BarNumber("12345", "ZZ")
    assert str(bar) == "12345/ZZ"


def test_parse_bar_numbers_deduplicates():
    assert parse_bar_numbers("12345/ZZ, 67890/ZZ,12345/ZZ") == [
        BarNumber("12345", "ZZ"),
        BarNumber("67890", "ZZ"),
    ]
    assert parse_bar_numbers("") == []


@pytest.mark.parametrize("text", ["12345", "/ZZ", "12345/Z", "abc/ZZ", "12345/Z0"])
def test_invalid_bar_number(text):
    with pytest.raises(ValueError):
        BarNumber.parse(text)


def test_from_env_reads_bars_and_safe_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("BAR_NUMBERS", "12345/ZZ,67890/ZZ")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "state.sqlite"))
    config = Config.from_env()
    assert config.bar_numbers == [BarNumber("12345", "ZZ"), BarNumber("67890", "ZZ")]
    assert config.dry_run is True  # safe default
    assert config.demo_mode is False and config.reference_date is None
    assert config.djen_base_url == "https://comunicaapi.pje.jus.br"
    assert config.db_path == tmp_path / "state.sqlite"
    assert config.llm_available is False


def test_demo_mode_defaults(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    config = Config.from_env()
    assert [str(b) for b in config.bar_numbers] == ["12345/ZZ", "67890/ZZ"]
    assert config.reference_date == DEMO_REFERENCE_DATE and config.today == date(2026, 9, 21)
    assert config.db_path == ROOT / ".demo" / "state.sqlite"
    assert config.llm_available is True  # the fixture classifier stands in for the model


def test_reference_date_override(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("REFERENCE_DATE", "2026-10-01")
    assert Config.from_env().today == date(2026, 10, 1)


def test_require_bar_numbers_explains_why():
    with pytest.raises(ValueError, match="10,000 cap"):
        Config().require_bar_numbers()


def test_require_email_lists_what_is_missing():
    with pytest.raises(ValueError, match="GRAPH_TENANT_ID"):
        Config(dry_run=False).require_email()


def test_dotenv_filled_repeated_key_wins_over_empty_placeholder(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("BAR_NUMBERS=\nWINDOW_DAYS=5\nBAR_NUMBERS=12345/ZZ\n", encoding="utf-8")
    monkeypatch.setenv("WINDOW_DAYS", "9")  # the process environment wins over the file
    load_dotenv(env)
    import os

    assert os.environ["BAR_NUMBERS"] == "12345/ZZ" and os.environ["WINDOW_DAYS"] == "9"
