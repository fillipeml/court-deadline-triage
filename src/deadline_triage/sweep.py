"""Capture: list by bar number -> normalise -> state -> report.

A failure on one bar number does not stop the others: it goes into `failed_bars` and the caller
decides on the failure alert. Classification, computation and output come after the state.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .config import BarNumber, Config
from .djen import ApiError, DjenClient, normalise
from .state import State


class PublicationSource(Protocol):
    warnings: list[str]

    def list(self, bar: BarNumber, start: date, end: date) -> Iterator[dict[str, Any]]: ...


def window(config: Config) -> tuple[date, date]:
    end = config.today
    return end - timedelta(days=config.window_days), end


def sample(config: Config, count: int, client: PublicationSource | None = None) -> Path:
    """Save the first N publications (raw + normalised) under the output folder, for schema study
    and prompt design. Does not touch the state."""
    config.require_bar_numbers()
    client = client or DjenClient(config)
    start, end = window(config)
    items: list[dict[str, Any]] = []
    for bar in config.bar_numbers:
        for raw in client.list(bar, start, end):
            items.append({"raw": raw, "normalised": normalise(raw, bar)})
            if len(items) >= count:
                break
        if len(items) >= count:
            break
    target = Path(config.output_dir) / "djen-sample.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "window": f"{start.isoformat()} to {end.isoformat()}",
                "bars": [str(b) for b in config.bar_numbers],
                "items": items,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return target


def run(config: Config, client: PublicationSource | None = None) -> dict[str, Any]:
    """Sweep the configured bar numbers and register unseen publications in the state."""
    config.require_bar_numbers()
    start, end = window(config)
    client = client or DjenClient(config)

    state = State(config.db_path)
    try:
        listed = 0
        repeated = 0
        new: list[dict[str, Any]] = []
        by_bar: dict[str, dict[str, int]] = {}
        failed_bars: list[str] = []
        for bar in config.bar_numbers:
            try:
                raws = list(client.list(bar, start, end))
            except ApiError as error:
                print(f"FAILURE on bar {bar}: {error}")
                failed_bars.append(f"{bar}: {error}")
                continue
            listed += len(raws)
            new_for_bar = 0
            for raw in raws:
                pub = normalise(raw, bar)
                if state.register(pub):
                    new.append(pub)
                    new_for_bar += 1
                else:
                    repeated += 1
            by_bar[str(bar)] = {"listed": len(raws), "new": new_for_bar}

        state.record_run(
            success=not failed_bars,
            bars=[str(b) for b in config.bar_numbers],
            listed=listed,
            new=len(new),
            dry_run=config.dry_run,
            error="; ".join(failed_bars)[:500] or None,
        )
    finally:
        state.close()

    return {
        "period": f"{start.isoformat()} to {end.isoformat()}",
        "bars": [str(b) for b in config.bar_numbers],
        "failed_bars": failed_bars,
        "listed": listed,
        "new": len(new),
        "repeated": repeated,  # already known from earlier runs, or repeated across bar numbers
        "by_bar": by_bar,
        "sealed": sum(1 for p in new if p["sealed"]),
        "cancelled": sum(1 for p in new if p.get("active") is False or p.get("cancelled_on")),
        "warnings": list(getattr(client, "warnings", []) or []),
        "dry_run": config.dry_run,
    }
