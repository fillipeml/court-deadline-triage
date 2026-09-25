"""Local state in SQLite. Idempotency: no publication is handled twice and none is lost.

The key of a publication is the `hash` the API itself returns; the same publication found
through two lawyers' bar numbers enters once and accumulates the bar numbers in `queried_bars`.
Triage rows carry the whole audit trail (decision, legal grounds, calendars, model output, cost).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS publications (
    hash                TEXT PRIMARY KEY,
    djen_id             TEXT,
    case_number         TEXT,
    case_number_masked  TEXT,
    court               TEXT,
    communication_type  TEXT,
    document_type       TEXT,
    unit                TEXT,
    case_class          TEXT,
    available_on        TEXT,
    medium              TEXT,
    link                TEXT,
    active              INTEGER,
    status              TEXT,
    cancellation_reason TEXT,
    cancelled_on        TEXT,
    sealed              INTEGER NOT NULL DEFAULT 0,
    text                TEXT,
    recipients_json     TEXT,
    lawyers_json        TEXT,
    queried_bars        TEXT NOT NULL,
    seen_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_publications_available_on ON publications(available_on);

CREATE TABLE IF NOT EXISTS triages (
    hash            TEXT PRIMARY KEY REFERENCES publications(hash),
    action          TEXT NOT NULL,      -- CALCULATE | REVIEW | PRIORITY_REVIEW | NO_DEADLINE
    reason          TEXT,
    event_code      INTEGER,
    event_name      TEXT,
    mode            TEXT,
    days            INTEGER,
    regime          TEXT,
    reference_court TEXT,
    published_on    TEXT,
    start_on        TEXT,
    due_on          TEXT,
    legal_grounds   TEXT,
    confidence      TEXT,
    source_excerpt  TEXT,
    warnings_json   TEXT,
    audit_json      TEXT,               -- grounds, skipped days, calendars used
    llm_json        TEXT,               -- free-form map + structured output (model trail)
    model           TEXT,
    tokens_json     TEXT,
    cost_usd        REAL,
    review_status   TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | adjusted
    triaged_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at    TEXT NOT NULL,
    success   INTEGER NOT NULL,
    bars      TEXT,
    listed    INTEGER,
    new       INTEGER,
    dry_run   INTEGER,
    error     TEXT
);
"""


def publication_key(pub: dict[str, Any]) -> str:
    """The API `hash`; without it, the `id`; without both, a stable synthetic key."""
    if pub.get("hash"):
        return str(pub["hash"])
    if pub.get("id") not in (None, ""):
        return f"ID/{pub['id']}"
    return (
        f"NO-ID/{pub.get('case_number')}/{pub.get('available_on')}"
        f"/{pub.get('document_type')}/{pub.get('unit')}"
    )


class State:
    PUB_COLUMNS = [
        "hash", "djen_id", "case_number", "case_number_masked", "court", "communication_type",
        "document_type", "unit", "case_class", "available_on", "active", "status",
        "cancellation_reason", "cancelled_on", "sealed", "text", "recipients_json", "lawyers_json",
        "queried_bars",
    ]  # fmt: skip

    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.executescript(SCHEMA)

    def register(self, pub: dict[str, Any]) -> bool:
        """Insert the publication if unseen. Returns True when it is new.

        If it already existed, accumulate the bar number through which it was also found (the
        same publication serves two lawyers of the firm) and return False.
        """
        key = publication_key(pub)
        bar = str(pub.get("queried_bar") or "")
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO publications (hash, djen_id, case_number, case_number_masked,"
            " court, communication_type, document_type, unit, case_class, available_on, medium, link,"
            " active, status, cancellation_reason, cancelled_on, sealed, text,"
            " recipients_json, lawyers_json, queried_bars, seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                None if pub.get("id") is None else str(pub["id"]),
                pub.get("case_number"),
                pub.get("case_number_masked"),
                pub.get("court"),
                pub.get("communication_type"),
                pub.get("document_type"),
                pub.get("unit"),
                pub.get("case_class"),
                pub.get("available_on"),
                pub.get("medium"),
                pub.get("link"),
                None if pub.get("active") is None else int(bool(pub["active"])),
                pub.get("status"),
                pub.get("cancellation_reason"),
                pub.get("cancelled_on"),
                int(bool(pub.get("sealed"))),
                pub.get("text"),
                json.dumps(pub.get("recipients") or [], ensure_ascii=False),
                json.dumps(pub.get("lawyers") or [], ensure_ascii=False),
                bar,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        if cursor.rowcount == 1:
            self._conn.commit()
            return True
        if bar:
            current = self._conn.execute(
                "SELECT queried_bars FROM publications WHERE hash = ?", (key,)
            ).fetchone()[0]
            known = [b for b in str(current or "").split(",") if b]
            if bar not in known:
                self._conn.execute(
                    "UPDATE publications SET queried_bars = ? WHERE hash = ?",
                    (",".join([*known, bar]), key),
                )
                self._conn.commit()
        return False

    def pending_triage(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Publications without a triage row, oldest first (their deadline has been running longer)."""
        sql = (
            f"SELECT {', '.join('p.' + c for c in self.PUB_COLUMNS)} FROM publications p "
            "LEFT JOIN triages t ON t.hash = p.hash WHERE t.hash IS NULL "
            "ORDER BY p.available_on, p.hash"
        )
        rows = self._conn.execute(
            sql + (" LIMIT ?" if limit else ""), (limit,) if limit else ()
        ).fetchall()
        pubs = []
        for row in rows:
            pub = dict(zip(self.PUB_COLUMNS, row, strict=True))
            pub["recipients"] = json.loads(pub.pop("recipients_json") or "[]")
            pub["lawyers"] = json.loads(pub.pop("lawyers_json") or "[]")
            pub["active"] = None if pub["active"] is None else bool(pub["active"])
            pub["sealed"] = bool(pub["sealed"])
            pubs.append(pub)
        return pubs

    def record_triage(self, pub_hash: str, data: dict[str, Any]) -> None:
        columns = ["hash", "triaged_at", *data.keys()]
        values = [pub_hash, datetime.now().isoformat(timespec="seconds"), *data.values()]
        self._conn.execute(
            f"INSERT OR REPLACE INTO triages ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
            values,
        )
        self._conn.commit()

    def triages(self, since: str | None = None) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT t.*, p.case_number_masked, p.case_number, p.available_on, p.unit, p.court AS publishing_court, "
            "p.queried_bars FROM triages t JOIN publications p ON p.hash = t.hash "
            + ("WHERE t.triaged_at >= ? " if since else "")
            + "ORDER BY t.due_on IS NULL, t.due_on",
            (since,) if since else (),
        )
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def record_run(
        self,
        success: bool,
        bars: list[str] | None = None,
        listed: int | None = None,
        new: int | None = None,
        dry_run: bool | None = None,
        error: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO runs (ran_at, success, bars, listed, new, dry_run, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                int(success),
                ",".join(bars or []),
                listed,
                new,
                None if dry_run is None else int(dry_run),
                error,
            ),
        )
        self._conn.commit()

    def recent_runs(self, count: int = 5) -> list[dict[str, Any]]:
        columns = ["ran_at", "success", "bars", "listed", "new", "dry_run", "error"]
        rows = self._conn.execute(
            f"SELECT {', '.join(columns)} FROM runs ORDER BY id DESC LIMIT ?", (count,)
        ).fetchall()
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def summary(self) -> dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
        by_court = dict(
            self._conn.execute(
                "SELECT COALESCE(court, '?'), COUNT(*) FROM publications GROUP BY court ORDER BY 2 DESC"
            ).fetchall()
        )
        by_document = dict(
            self._conn.execute(
                "SELECT COALESCE(document_type, '?'), COUNT(*) FROM publications GROUP BY document_type ORDER BY 2 DESC"
            ).fetchall()
        )
        sealed = self._conn.execute(
            "SELECT COUNT(*) FROM publications WHERE sealed = 1"
        ).fetchone()[0]
        return {"total": total, "by_court": by_court, "by_document": by_document, "sealed": sealed}

    def close(self) -> None:
        self._conn.close()
