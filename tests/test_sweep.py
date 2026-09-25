import json
from datetime import date

import pytest

from deadline_triage.config import BarNumber, Config
from deadline_triage.djen import ApiError
from deadline_triage.sweep import run, sample, window
from tests.conftest import cnj, digits

ANA, BRUNO = "12345/ZZ", "67890/ZZ"


def _raw(i, **extra):
    return {
        "id": i, "hash": f"h{i}", "texto": "Intime-se para contestar em 15 dias &uacute;teis",
        "numero_processo": digits(cnj(f"{i:07d}", "8", "09")), "siglaTribunal": "TJGO",
        "data_disponibilizacao": "2026-09-19", "tipoDocumento": "Despacho", "ativo": True, **extra,
    }  # fmt: skip


class FakeClient:
    def __init__(self, by_bar):
        self._by_bar = by_bar
        self.warnings = []

    def list(self, bar, start, end):
        value = self._by_bar.get(str(bar), [])
        if isinstance(value, Exception):
            raise value
        yield from value


def _config(tmp_path) -> Config:
    return Config(
        bar_numbers=[BarNumber.parse(ANA), BarNumber.parse(BRUNO)], dry_run=True,
        db_path=tmp_path / "state.sqlite", output_dir=tmp_path / "out", window_days=3,
        reference_date=date(2026, 9, 21),
    )  # fmt: skip


def test_window_uses_the_reference_date(tmp_path):
    assert window(_config(tmp_path)) == (date(2026, 9, 18), date(2026, 9, 21))


def test_first_sweep_deduplicates_across_bars(tmp_path):
    # h3 serves both lawyers: appears in both queries, enters once
    client = FakeClient({ANA: [_raw(1), _raw(2), _raw(3)], BRUNO: [_raw(3), _raw(4)]})
    report = run(_config(tmp_path), client=client)
    assert report["listed"] == 5
    assert report["new"] == 4
    assert report["repeated"] == 1
    assert report["by_bar"] == {ANA: {"listed": 3, "new": 3}, BRUNO: {"listed": 2, "new": 1}}
    assert report["failed_bars"] == [] and report["dry_run"] is True
    assert report["period"] == "2026-09-18 to 2026-09-21"


def test_second_sweep_repeats_nothing(tmp_path):
    config = _config(tmp_path)
    client = FakeClient({ANA: [_raw(1)], BRUNO: [_raw(2)]})
    run(config, client=client)
    report = run(config, client=client)
    assert report["new"] == 0 and report["repeated"] == 2


def test_failure_on_one_bar_does_not_stop_the_others(tmp_path):
    client = FakeClient({ANA: ApiError("HTTP 500: SHORTCIRCUIT"), BRUNO: [_raw(4)]})
    report = run(_config(tmp_path), client=client)
    assert len(report["failed_bars"]) == 1 and "SHORTCIRCUIT" in report["failed_bars"][0]
    assert report["new"] == 1


def test_without_bars_it_fails_early(tmp_path):
    with pytest.raises(ValueError):
        run(Config(bar_numbers=[], db_path=tmp_path / "e.sqlite"), client=FakeClient({}))


def test_counts_sealed_and_cancelled(tmp_path):
    sealed = _raw(
        9,
        texto="PROCESSO EM SEGREDO DE JUSTI&Ccedil;A. OS ARQUIVOS DA INTIMA&Ccedil;&Atilde;O N&Atilde;O FORAM PUBLICADOS.",
    )
    cancelled = _raw(
        10, ativo=False, data_cancelamento="2026-09-20", motivo_cancelamento="republication"
    )
    report = run(_config(tmp_path), client=FakeClient({ANA: [sealed, cancelled]}))
    assert report["sealed"] == 1
    assert report["cancelled"] == 1


def test_sample_saves_raw_and_normalised_without_touching_the_state(tmp_path):
    config = _config(tmp_path)
    target = sample(config, 2, client=FakeClient({ANA: [_raw(1), _raw(2), _raw(3)]}))
    body = json.loads(target.read_text(encoding="utf-8"))
    assert len(body["items"]) == 2
    assert body["items"][0]["raw"]["hash"] == "h1"
    assert "úteis" in body["items"][0]["normalised"]["text"]
    assert not (tmp_path / "state.sqlite").exists()
