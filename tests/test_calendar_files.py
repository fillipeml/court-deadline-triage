"""Integrity of the versioned calendars: every file loads and declares its source."""

import json

import pytest

from deadline_triage.court_calendar import CALENDARS_DIR, Calendars

FILES = sorted(CALENDARS_DIR.glob("*/*.json"))


@pytest.mark.parametrize("path", FILES, ids=[f"{p.parent.name}/{p.stem}" for p in FILES])
def test_file_loads_and_has_a_source(path):
    file = Calendars().file(path.stem, int(path.parent.name))
    assert file is not None and file.days
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["source"]["url"].startswith("https://")
    assert raw["review"]["status"] in {"pending", "reviewed"}


def test_national_2026_and_2027_exist():
    c = Calendars()
    assert c.file("NATIONAL", 2026) and c.file("NATIONAL", 2027)
    assert c.available_courts(2026) == ["TJGO", "TRT18"]
    assert c.available_courts(2030) == []
