"""Builds `catalogue/events.json` from the curated `catalogue/events.source.json`.

The source lists the events a litigation team handles (name, English gloss, kind, legal
deadline and legal basis). This script derives the calculation mode, anchor, regime and legal
days with `catalogue_rules`, and preserves any existing human validation block, so regenerating
the catalogue never erases what the lawyers already decided.

    build-catalogue            # source -> events.json (+ a summary by mode)
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import date
from pathlib import Path

from .catalogue_rules import MODES, classify, days_in_law, regime_of
from .config import ROOT

SOURCE_PATH = ROOT / "catalogue" / "events.source.json"
TARGET_PATH = ROOT / "catalogue" / "events.json"

EMPTY_VALIDATION = {"status": "pending", "by": None, "on": None, "final_mode": None, "note": None}


def build_events(source: list[dict], previous: dict[int, dict] | None = None) -> list[dict]:
    previous = previous or {}
    events: list[dict] = []
    seen: set[int] = set()
    for item in source:
        code = int(item["code"])
        if code in seen:
            raise ValueError(f"duplicate event code {code}")
        seen.add(code)
        deadline, basis = item.get("legal_deadline") or "", item.get("legal_basis") or ""
        mode, anchor, reason = classify(item["name"], item["kind"], deadline, basis)
        events.append(
            {
                "code": code,
                "name": item["name"],
                "name_en": item.get("name_en") or item["name"],
                "kind": item["kind"],
                "legal_deadline": deadline,
                "legal_basis": basis,
                "mode": mode,
                "anchor": anchor,
                "regime": regime_of(deadline, item.get("regime"))
                if mode in ("AUTO", "DAYS_IN_TEXT")
                else None,
                "days_in_law": days_in_law(deadline) if mode == "AUTO" else None,
                "reason": reason,
                "validation": (previous.get(code) or {}).get("validation")
                or dict(EMPTY_VALIDATION),
            }
        )
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive calculation modes for the event catalogue")
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--target", type=Path, default=TARGET_PATH)
    args = parser.parse_args()
    if not args.source.exists():
        print(f"source not found: {args.source}", file=sys.stderr)
        return 1
    source = json.loads(args.source.read_text(encoding="utf-8"))
    previous: dict[int, dict] = {}
    if args.target.exists():
        previous = {
            int(e["code"]): e
            for e in json.loads(args.target.read_text(encoding="utf-8")).get("events", [])
        }
    events = build_events(source["events"], previous)
    body = {
        "generated_on": date.today().isoformat(),
        "source": args.source.name,
        "modes": MODES,
        "total": len(events),
        "events": events,
    }
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(events)} events -> {args.target}")
    for mode, n in collections.Counter(e["mode"] for e in events).most_common():
        print(f"  {mode:18} {n:4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
