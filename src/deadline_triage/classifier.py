"""Deadline-type classification with a language model: the two-call pattern.

Call 1: a free-form legal map of the publication (the model reasons before it structures).
Call 2: JSON validated by Pydantic (structured outputs) from that map.
The system prompt (rules + catalogue table) is identical in both calls and sits in the cache.

The model never computes dates: it returns the catalogue event, the number of days when it is
written in the act, and flags. Code decides and computes.

The publications are Portuguese; the prompt is English with the Portuguese cues quoted, and the
model answers in the structured schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from .catalogue import Catalogue
from .excerpt import excerpt

# Sonnet 5 list price (USD per million tokens): input 2, output 10; cache write 1.25x, cache read 0.1x
PRICE_USD = {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20}
MAX_TOKENS_MAP = 4_000
MAX_TOKENS_JSON = 4_000

SYSTEM = """You support the deadline-control desk of a law firm (civil, real-estate and labour litigation \
in Brazil). You receive publications from the national electronic court gazette (DJEN) addressed to \
the firm's lawyers and identify which procedural deadline, if any, each publication opens.

Rules:
- Read the body of the act. The court's "document type" and "class" fields are free text and unreliable.
- The deadline type must be an event of the table below, chosen by code. If none fits, say so and \
describe the deadline in your own words. Never force a code.
- You do not compute dates. Give the number of days only when it is written in the act (e.g. "no prazo \
de 10 (dez) dias"); do not infer it from the law.
- Flag a hint of a doubled deadline: public treasury ("Fazenda Pública"), public prosecutor ("Ministério \
Público"), public defender ("Defensoria Pública") or co-parties with different counsel (CPC, arts. 180, \
183, 186 and 229).
- Acts without a deadline for the party (mere notice, referral, "conclusão", certificate, a docket entry \
already fulfilled) open no deadline.
- A hearing or session already scheduled: record the scheduled date; it is not a deadline counted from \
the publication.
- Do not invent: if the text does not allow a conclusion, say that no conclusion is possible.

Event table (the firm's catalogue):
{table}"""

MAP_TASK = """Write a short map (up to 250 words) of this publication:
1. What act it is (order, decision, judgment, appellate decision, clerk's act...) and what it determines.
2. Whom the determination addresses (which side/party) and whether it reaches the party represented by \
the addressed lawyers.
3. Whether it opens a deadline: for what, how many days IF written in the act, and business or calendar \
days IF written.
4. Which event of the table corresponds (code and name) or "none", and why.
5. Hints of a doubled deadline, a scheduled hearing/session (date), or the absence of a deadline.
6. LITERAL EXCERPT: copy the sentence of the act that grounds your conclusion.

{publication}"""

JSON_TASK = """Convert the map below into the requested format. Use only what the map states; \
event_code only if the map points at a code of the table.

MAP:
{map}"""


class Classification(BaseModel):
    opens_deadline: bool
    event_code: int | None
    suggested_type: str | None
    days_in_text: int | None
    regime_in_text: Literal["business", "calendar"] | None
    double_deadline_hint: bool
    scheduled_date: str | None
    confidence: Literal["high", "medium", "low"]
    rationale: str
    source_excerpt: str


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0

    def add(self, usage: Any) -> None:
        self.input += int(getattr(usage, "input_tokens", 0) or 0)
        self.output += int(getattr(usage, "output_tokens", 0) or 0)
        self.cache_write += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        self.cache_read += int(getattr(usage, "cache_read_input_tokens", 0) or 0)

    @property
    def cost_usd(self) -> float:
        return sum(getattr(self, k) * v for k, v in PRICE_USD.items()) / 1_000_000


@dataclass
class LlmResult:
    classification: Classification | None
    map: str
    usage: Usage = field(default_factory=Usage)
    truncated: bool = False
    failure: str | None = None  # refusal, truncation or invalid JSON -> priority review


def build_prompt(pub: dict[str, Any]) -> tuple[str, bool]:
    text, truncated = excerpt(pub.get("text") or "")
    recipients = "; ".join(
        f"{r.get('name')} (side {r.get('side')})" for r in pub.get("recipients") or []
    )
    lawyers = "; ".join(
        f"{a.get('name')} bar {a.get('bar_number')}/{a.get('state')}"
        for a in pub.get("lawyers") or []
    )
    header = (
        f"Court: {pub.get('court')} | Unit: {pub.get('unit')} | Class: {pub.get('case_class')}\n"
        f"Document type (free text from the court): {pub.get('document_type')}\n"
        f"Case: {pub.get('case_number_masked') or pub.get('case_number')}\n"
        f"Recipients: {recipients or 'not informed'}\n"
        f"Addressed lawyers: {lawyers or 'not informed'}\n"
        + ("Note: long text shortened; omitted passages are marked.\n" if truncated else "")
    )
    return f"{header}\nBODY:\n{text}", truncated


class Classifier:
    def __init__(self, catalogue: Catalogue, model: str, client: Any | None = None) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client
        self._model = model
        self._system = [
            {
                "type": "text",
                "text": SYSTEM.format(table=catalogue.table_for_llm),
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def classify(self, pub: dict[str, Any]) -> LlmResult:
        publication, truncated = build_prompt(pub)
        usage = Usage()

        r1 = self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS_MAP,
            system=self._system,
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": MAP_TASK.format(publication=publication)}],
        )
        usage.add(r1.usage)
        legal_map = "".join(b.text for b in r1.content if getattr(b, "type", "") == "text").strip()
        if r1.stop_reason in {"refusal", "max_tokens"} or not legal_map:
            return LlmResult(
                None, legal_map, usage, truncated, f"call 1 ended with {r1.stop_reason}"
            )

        r2 = self._client.messages.parse(
            model=self._model,
            max_tokens=MAX_TOKENS_JSON,
            system=self._system,
            messages=[{"role": "user", "content": JSON_TASK.format(map=legal_map)}],
            output_format=Classification,
        )
        usage.add(r2.usage)
        parsed = getattr(r2, "parsed_output", None)
        if r2.stop_reason in {"refusal", "max_tokens"} or parsed is None:
            return LlmResult(
                None, legal_map, usage, truncated, f"call 2 ended with {r2.stop_reason}"
            )
        return LlmResult(parsed, legal_map, usage, truncated)


def result_to_json(r: LlmResult) -> str:
    return json.dumps(
        {
            "map": r.map,
            "classification": r.classification.model_dump() if r.classification else None,
            "truncated": r.truncated,
            "failure": r.failure,
        },
        ensure_ascii=False,
    )
