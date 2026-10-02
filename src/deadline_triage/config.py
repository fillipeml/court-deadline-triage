"""Configuration from the environment, with an optional `.env` file. No secret lives in code.

`DEMO_MODE` and `DRY_RUN` are read from the environment here and nowhere else; business modules never check
them. In demo mode the defaults point at the fixture bar numbers, a local SQLite file under
`.demo/` and a fixed reference date, so the demo is deterministic and needs no credential.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Public DJEN API (Brazil's national electronic court gazette). Validated in production in
# September 2026: no credential, no registration, plain HTTP 200.
DEFAULT_DJEN_BASE_URL = "https://comunicaapi.pje.jus.br"

DEFAULT_MODEL = "claude-sonnet-5"

# Demo defaults: the fixture publications were made available in the week of 2026-09-21 and the
# committed calendars cover 2026, so the demo computes the same dates on any day it is run.
DEMO_REFERENCE_DATE = date(2026, 9, 21)
DEMO_BAR_NUMBERS = "12345/ZZ,67890/ZZ"


def load_dotenv(path: Path) -> None:
    """Load a `.env` file without a dependency.

    Variables already set in the environment win over the file. Inside the file, a repeated key
    with a filled value wins over an empty occurrence (common when a new block is pasted below
    the template); otherwise an empty placeholder at the top would silently cancel the real value.
    """
    if not path.exists():
        return
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if value or key not in values:
            values[key] = value
    for key, value in values.items():
        os.environ.setdefault(key, value)


def _path(value: str, default: str) -> Path:
    """Relative paths are anchored at the repository root: a scheduler does not guarantee the
    working directory, and a relative path would silently create a new, empty database
    somewhere else."""
    path = Path(value.strip()) if value.strip() else Path(default)
    return path if path.is_absolute() else ROOT / path


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class BarNumber:
    """A lawyer's bar registration (OAB): the query key of the DJEN API (`numeroOab` + `ufOab`)."""

    number: str
    state: str

    @classmethod
    def parse(cls, text: str) -> BarNumber:
        raw = text.strip()
        number, sep, state = raw.partition("/")
        number = "".join(ch for ch in number if ch.isdigit())
        state = state.strip().upper()
        if not sep or not number or len(state) != 2 or not state.isalpha():
            raise ValueError(f"invalid bar number {text!r}: use NUMBER/STATE (e.g. 12345/SP)")
        return cls(number, state)

    def __str__(self) -> str:
        return f"{self.number}/{self.state}"


def parse_bar_numbers(value: str) -> list[BarNumber]:
    bars: list[BarNumber] = []
    for part in value.split(","):
        if part.strip():
            bar = BarNumber.parse(part)
            if bar not in bars:
                bars.append(bar)
    return bars


@dataclass
class Config:
    bar_numbers: list[BarNumber] = field(default_factory=list)
    djen_base_url: str = DEFAULT_DJEN_BASE_URL
    window_days: int = 3
    dry_run: bool = True
    demo_mode: bool = False
    reference_date: date | None = None  # None -> today
    db_path: Path = field(default_factory=lambda: ROOT / "data" / "state.sqlite")
    output_dir: Path = field(default_factory=lambda: ROOT / "output")
    anthropic_api_key: str = ""
    classifier_model: str = DEFAULT_MODEL
    llm_disabled: bool = False
    email_sender: str = ""
    email_recipients: str = ""
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    urgent_business_days: int = 3
    triage_limit: int | None = None  # max publications classified per run (cost control)
    require_validated_catalogue: bool = False  # go-live: only events validated by lawyers compute

    @property
    def llm_available(self) -> bool:
        return self.demo_mode or (bool(self.anthropic_api_key) and not self.llm_disabled)

    @property
    def recipients(self) -> list[str]:
        return [e.strip() for e in self.email_recipients.split(",") if e.strip()]

    @property
    def today(self) -> date:
        return self.reference_date or date.today()

    @classmethod
    def from_env(cls) -> Config:
        load_dotenv(ROOT / ".env")
        env = os.environ.get
        demo = _bool(env("DEMO_MODE"), default=False)
        reference = env("REFERENCE_DATE", "").strip()
        bars = env("BAR_NUMBERS", "").strip() or (DEMO_BAR_NUMBERS if demo else "")
        limit = env("TRIAGE_LIMIT", "").strip()
        return cls(
            bar_numbers=parse_bar_numbers(bars),
            djen_base_url=(env("DJEN_BASE_URL", "").strip() or DEFAULT_DJEN_BASE_URL).rstrip("/"),
            window_days=int(env("WINDOW_DAYS", "").strip() or "3"),
            dry_run=_bool(env("DRY_RUN"), default=True),
            demo_mode=demo,
            reference_date=date.fromisoformat(reference)
            if reference
            else (DEMO_REFERENCE_DATE if demo else None),
            db_path=_path(
                env("DB_PATH", ""), ".demo/state.sqlite" if demo else "data/state.sqlite"
            ),
            output_dir=_path(env("OUTPUT_DIR", ""), ".demo/output" if demo else "output"),
            anthropic_api_key=env("ANTHROPIC_API_KEY", "").strip(),
            classifier_model=env("CLASSIFIER_MODEL", "").strip() or DEFAULT_MODEL,
            llm_disabled=_bool(env("LLM_DISABLED"), default=False),
            email_sender=env("EMAIL_SENDER", "").strip(),
            email_recipients=env("EMAIL_RECIPIENTS", "").strip(),
            graph_tenant_id=env("GRAPH_TENANT_ID", "").strip(),
            graph_client_id=env("GRAPH_CLIENT_ID", "").strip(),
            graph_client_secret=env("GRAPH_CLIENT_SECRET", "").strip(),
            urgent_business_days=int(env("URGENT_BUSINESS_DAYS", "").strip() or "3"),
            triage_limit=int(limit) if limit else None,
            require_validated_catalogue=_bool(env("REQUIRE_VALIDATED_CATALOGUE"), default=False),
        )

    def require_bar_numbers(self) -> None:
        if not self.bar_numbers:
            raise ValueError(
                "No bar number configured: set BAR_NUMBERS in .env (e.g. BAR_NUMBERS=12345/SP,67890/SP). "
                "The DJEN is always queried by bar number: querying by court hits the 10,000 cap."
            )

    def require_email(self) -> None:
        """Validate what a REAL e-mail delivery needs (outside DRY_RUN and demo mode)."""
        missing = [
            name
            for name, value in [
                ("GRAPH_TENANT_ID", self.graph_tenant_id),
                ("GRAPH_CLIENT_ID", self.graph_client_id),
                ("GRAPH_CLIENT_SECRET", self.graph_client_secret),
                ("EMAIL_SENDER", self.email_sender),
                ("EMAIL_RECIPIENTS", self.email_recipients),
            ]
            if not value
        ]
        if missing:
            raise ValueError(f"Real delivery requires in .env: {', '.join(missing)}")
