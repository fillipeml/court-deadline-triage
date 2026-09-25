"""Client of the public DJEN / Comunica PJe API: read-only, no credential.

Contract validated in production (September 2026): `GET /api/v1/comunicacao` by `numeroOab` +
`ufOab`, a window on the "made available" date, `itensPorPagina` <= 100, pagination through
`pagina` (1-based; `page` is silently ignored). `count` caps at 10,000, which is why the query
is always by bar number, never by court.

Reading a publication here does NOT acknowledge service and has no procedural effect: the
gazette is already public. This is the difference from the electronic judicial domicile, where
opening a communication is the legal act of acknowledging it.

Wire field names (Portuguese) are mapped once, in `normalise()`; everything downstream is
English. The wire names are listed in docs/GLOSSARY.md.
"""

from __future__ import annotations

import html
import re
import time
from collections.abc import Iterator
from datetime import date
from typing import Any

import requests

from .config import BarNumber, Config

ATTEMPTS = 3
TIMEOUT = 60  # the API takes several seconds on full pages
PAGE_SIZE = 100
COUNT_CAP = 10_000
MAX_PAGES = 500  # 50,000 items in one window: safety stop against a runaway loop

_SEALED = re.compile(r"SEGREDO DE JUSTI[ÇC]A", re.IGNORECASE)
_NOT_PUBLISHED = re.compile(r"N[ÃA]O FORAM PUBLICADOS", re.IGNORECASE)
_SPACES = re.compile(r"[ \t\xa0]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class ApiError(RuntimeError):
    pass


def clean_text(raw: Any) -> str:
    """Undo HTML entities (`&aacute;`, `&ndash;`, `&gt;`) and normalise spaces while keeping
    paragraph breaks. The API returns `texto` escaped; without this the classification degrades."""
    if not raw:
        return ""
    text = html.unescape(str(raw)).replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def is_sealed(text: str) -> bool:
    """Publication without content: "PROCESSO EM SEGREDO DE JUSTIÇA. OS ARQUIVOS ... NÃO FORAM
    PUBLICADOS." Not to be confused with an ordinary order that merely mentions the seal."""
    return bool(_SEALED.search(text) and _NOT_PUBLISHED.search(text))


def normalise(item: dict[str, Any], bar: BarNumber) -> dict[str, Any]:
    """Raw API item -> internal record (stable English names, clean text, queried bar number)."""
    text = clean_text(item.get("texto"))
    lawyers = []
    for link in item.get("destinatarioadvogados") or []:
        lawyer = (link or {}).get("advogado") or {}
        if lawyer:
            lawyers.append(
                {
                    "name": lawyer.get("nome"),
                    "bar_number": lawyer.get("numero_oab"),
                    "state": lawyer.get("uf_oab"),
                }
            )
    recipients = [
        {"name": r.get("nome"), "side": r.get("polo")} for r in item.get("destinatarios") or [] if r
    ]
    return {
        "hash": item.get("hash") or None,
        "id": item.get("id"),
        "case_number": str(item.get("numero_processo") or ""),
        "case_number_masked": item.get("numeroprocessocommascara"),
        "court": item.get("siglaTribunal"),
        "communication_type": item.get("tipoComunicacao"),
        "document_type": item.get("tipoDocumento"),
        "unit": item.get("nomeOrgao"),
        "case_class": item.get("nomeClasse"),
        "available_on": str(
            item.get("data_disponibilizacao") or item.get("datadisponibilizacao") or ""
        )[:10],
        "medium": item.get("meio"),
        "link": item.get("link"),
        "active": item.get("ativo"),
        "status": item.get("status"),
        "cancellation_reason": item.get("motivo_cancelamento"),
        "cancelled_on": item.get("data_cancelamento"),
        "sealed": is_sealed(text),
        "text": text,
        "recipients": recipients,
        "lawyers": lawyers,
        "queried_bar": str(bar),
    }


class DjenClient:
    def __init__(self, config: Config, session: requests.Session | None = None) -> None:
        self._base = config.djen_base_url.rstrip("/")
        self._session = session or requests.Session()
        self.warnings: list[str] = []

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}/api/v1/comunicacao"
        last_failure = ""
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=TIMEOUT,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "court-deadline-triage/0.1",
                    },
                )
            except requests.RequestException as exc:
                last_failure = f"network error: {exc}"
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        raise ApiError(
                            f"API returned 200 with a non-JSON body: {response.text[:300]!r}"
                        ) from None
                last_failure = f"HTTP {response.status_code}: {response.text[:300]}"
                # 4xx (except 429) does not improve with a retry
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < ATTEMPTS:
                time.sleep(2**attempt)
        raise ApiError(
            f"GET /api/v1/comunicacao failed after {ATTEMPTS} attempt(s): {last_failure}"
        )

    def list(self, bar: BarNumber, start: date, end: date) -> Iterator[dict[str, Any]]:
        """RAW publications of one bar number in the window, page by page. Writes nothing."""
        page = 1
        while page <= MAX_PAGES:
            body = self._get(
                {
                    "numeroOab": bar.number,
                    "ufOab": bar.state,
                    "dataDisponibilizacaoInicio": start.isoformat(),
                    "dataDisponibilizacaoFim": end.isoformat(),
                    "itensPorPagina": PAGE_SIZE,
                    "pagina": page,
                }
            )
            status = str(body.get("status", "success")).lower()
            if status not in {"success", "ok"}:
                raise ApiError(f"API answered status={body.get('status')!r}: {body.get('message')}")
            items = body.get("items") or []
            if page == 1:
                count = int(body.get("count") or 0)
                if count >= COUNT_CAP:
                    self.warnings.append(
                        f"bar {bar}: count={count} hit the API cap; publications may be missing "
                        "from the listing, reduce WINDOW_DAYS"
                    )
            yield from items
            if len(items) < PAGE_SIZE:
                return
            page += 1
        raise ApiError(
            f"bar {bar}: more than {MAX_PAGES} pages in the window; safety stop triggered"
        )
