"""Shared fixtures. Synthetic case numbers are built with valid check digits at test time, so no
real-looking CNJ number sits in the repository."""

from __future__ import annotations

import pytest

from deadline_triage.court import expected_check_digits


def cnj(sequence: str, branch: str, court: str, unit: str = "0001", year: str = "2099") -> str:
    """Masked CNJ number with valid check digits, e.g. cnj("0000001", "8", "09")."""
    dd = expected_check_digits(sequence, year, branch, court, unit)
    return f"{sequence}-{dd:02d}.{year}.{branch}.{court}.{unit}"


def digits(masked: str) -> str:
    return "".join(ch for ch in masked if ch.isdigit())


@pytest.fixture(scope="session")
def tjgo_number() -> str:
    return cnj("0000001", "8", "09")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "DEMO_MODE", "DRY_RUN", "REFERENCE_DATE", "BAR_NUMBERS", "DJEN_BASE_URL", "WINDOW_DAYS",
        "ANTHROPIC_API_KEY", "CLASSIFIER_MODEL", "LLM_DISABLED", "TRIAGE_LIMIT", "REQUIRE_VALIDATED_CATALOGUE",
        "GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "EMAIL_SENDER", "EMAIL_RECIPIENTS",
        "URGENT_BUSINESS_DAYS", "DB_PATH", "OUTPUT_DIR",
    ):  # fmt: skip
        monkeypatch.delenv(name, raising=False)
