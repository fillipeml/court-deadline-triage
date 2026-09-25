# court-deadline-triage

A daily batch job that reads every publication addressed to a firm's lawyers in Brazil's national electronic court gazette (DJEN), has a language model identify which procedural deadline each one opens, computes the due date with a deterministic engine over versioned court calendars, and hands a lawyer a triage table to confirm. Built for a litigation team's deadline-control desk; rebranded and anonymised here. The gazette client and the engine were validated against the live gazette; the classification has run only on fixtures so far.

![CI](https://github.com/fillipeml/court-deadline-triage/actions/workflows/ci.yml/badge.svg) ![Licence: MIT](https://img.shields.io/badge/licence-MIT-informational)

**Status:** pilot, capture and engine validated on real publications · **Runs offline:** yes, `DEMO_MODE=true` needs no key and no network

```
$ DEMO_MODE=true DRY_RUN=false deadline-triage
Source: DEMO (fixtures) | bars: 12345/ZZ, 67890/ZZ | window: 3 day(s) to 2026-09-21 | DRY_RUN: False
Sweep report:
Period: 2026-09-18 to 2026-09-21 | bars: 12345/ZZ, 67890/ZZ
Listed: 13 | new: 12 | repeated/already known: 1
Triage:
  pending read: 12 | triaged: 12 | by action: {'CALCULATE': 4, 'PRIORITY_REVIEW': 5, 'NO_DEADLINE': 2, 'REVIEW': 1}

DUE         ACTION           DEADLINE TYPE                      CASE                       COURT  REASON
2026-09-28  CALCULATE        Manifestação Diversa               0000102-25.2099.8.09.0002  TJGO   deadline set in the act
2026-10-01  CALCULATE        Recurso Ordinário Trabalhista      0000201-89.2099.5.18.0003  TRT18  legal deadline from the catalogue
2026-10-14  PRIORITY_REVIEW  Contestação                        0000109-17.2099.8.09.0002  TRT18  date computed, but the publishing court diverges from the CNJ number
2026-10-14  CALCULATE        Contestação                        0000101-43.2099.8.09.0001  TJGO   legal deadline from the catalogue
-           PRIORITY_REVIEW  Embargos de Declaração             0000301-67.2099.8.13.0024  TJMG   deadline identified, date not computed: no calendar loaded for TJMG/2026
-           PRIORITY_REVIEW  Contestação                        0000107-50.2099.8.09.0001  TJGO   hint of a doubled deadline
-           REVIEW           Audiência de Conciliação           0000108-35.2099.8.09.0001  TJGO   'Audiência de Conciliação' is a docket date, not a counted deadline
-           NO_DEADLINE      -                                  0000103-13.2099.8.09.0001  TJGO   case-assignment list: opens no deadline
```

Every party, lawyer and case number in the demo is invented (the state "ZZ" does not exist; the case numbers are dated 2099).

## The problem

A litigation lawyer in Brazil receives around thirty gazette publications a day, and any of them may start a deadline: fifteen business days to answer a complaint, eight to appeal a labour judgment, five to respond to a motion. Missing one is malpractice. The arithmetic is not trivial either: the act counts as published on the next business day, the count starts the day after that, weekends and the court's own holidays do not count, the whole judiciary suspends deadlines from 20 December to 20 January, and each court publishes its own holiday calendar, so the same act served on the same day by two courts can be due a day apart. The team read every publication by hand and kept the dates in a spreadsheet. They wanted the reading and the arithmetic done for them, and the decision left to a lawyer.

## What it does

- Sweeps the gazette every business day for the firm's lawyers, by bar number, over a rolling window; stores every publication once in SQLite, even when it serves two lawyers.
- Classifies the type of deadline each publication opens with a language model constrained to a catalogue of events, returning the event code, the number of days when the act states it, a doubled-deadline flag and a literal excerpt as evidence.
- Decides deterministically what to do from the catalogue's calculation mode: compute, review, priority review or no deadline. Anything uncertain goes to a human, never to a guess.
- Computes the due date with a deterministic engine: publication jump, first-day jump, business or calendar days, the art. 220 suspension, reduced-hours days, district holidays, all over calendars transcribed from each court's official act and versioned in git.
- Prints and files a triage table, e-mails the team a digest, alerts on its own failure and answers a health check.

## Architecture

```mermaid
flowchart LR
  G[DJEN public API\nby bar number] --> S[sweep\nnormalise once]
  S --> DB[(SQLite\npublications · triages · runs)]
  DB --> P[pre-filter\nsealed · cancelled · lists]
  P --> M[classifier\n2 calls, cached catalogue]
  M --> D[decision\ncatalogue modes]
  D --> E[engine\nversioned court calendars]
  E --> DB
  DB --> R[report\ntable · CSV · digest]
  R --> ML[Mailer\nGraph | Outbox]
  G -. DEMO_MODE .-> F[fixture gazette]
  M -. DEMO_MODE .-> FC[fixture classifier]
```

The gazette client maps the API's Portuguese fields once into an English record; from there on the code is English and the domain terms are in the glossary. Classification is two calls: a free-form legal map of the act, then a Pydantic-validated JSON built only from that map, with the catalogue table in a cached system prompt. The decision layer turns the model's answer plus the event's calculation mode into an instruction for the engine or a reason for review. The engine walks the calendar day by day and keeps the audit trail: every skipped holiday, every uncertain day, every calendar file and version used. The factory is the only module that reads `DEMO_MODE`.

## Design decisions

- **The model never computes a date.** It classifies and quotes; code decides and counts. A wrong date from an LLM looks exactly like a right one, so the arithmetic lives in a deterministic engine with one hand-computed golden case per rule (fifteen so far, including the two courts one day apart). Cost: two more layers than a single prompt would need.
- **Query by bar number, not by court.** The API's `count` caps at 10,000 (one big court hits it in a day), so a sweep by court silently loses publications. A sweep by the lawyers' bar numbers returns tens a day, and the same publication found through two lawyers is stored once, with both bar numbers accumulated on the row.
- **Calendars are transcribed from the official act and versioned.** The bar association page the plan named as the single source turned out to be an index of links, with wrong links for two courts. Each calendar file cites the court's act, declares its coverage (municipal holidays or not), carries a human-review block and treats an optional holiday whose effect is unstated as a business day, because the earlier date is the safe one. A court or year without a file does not compute: the row says so and goes to review.
- **The reference court is the one that published, cross-checked against the case number.** An appeal in a superior court keeps the number of the court of origin, so deriving the court from the number alone would apply the wrong calendar. A divergence between courts of the same level computes the date and still sends the row to priority review.
- **Catalogue modes are derived by rules and gated by humans.** Whether an event can be computed alone depends on three attributes: anchored to the publication, regime known, days fixed by law. Ordered rules over the legal text derive the mode for 86 events; each carries a validation block, and a go-live flag makes the system compute only what the legal team has validated.
- **Unknown means a human.** Sealed cases, cancelled publications, events outside the catalogue, low confidence, a hint of a doubled deadline, days in the act that contradict the law: each is a priority review with a stated reason. Silence is never success either: a failed sweep sends an alert, and the health check reports the last run, the failures and the courts without a calendar.
- **Reading the gazette is not acknowledging service.** This is the opposite rule from the sibling project on the electronic judicial domicile ([court-notice-monitor](https://github.com/fillipeml/court-notice-monitor)), where opening a communication has legal effect. Here the object of the work is the served act itself, and the rule is written down so nobody copies the other project's constraint by mistake.

## How AI was used

- **Generated:** the original Portuguese version was written with an AI coding assistant over one week against the live gazette; this English version was produced by translating and restructuring it with the same assistant, with the `normalise()` boundary, the `Mailer` interface, the fixture adapters and the report module introduced in the process.
- **Rewritten by me:** the legal rules of the engine came from the statutes and were checked against the team's own spreadsheet, including two corrections to the project's written plan (labour deadlines count in business days since 2017; the gazette's two-jump rule, not the portal's rule, applies); the API contract facts came from running against production (`page` ignored, `pagina` honoured; the count cap; HTML entities in the body).
- **Validated:** 161 tests run offline, fifteen of them golden cases computed by hand before the engine existed; the demo path runs twice in CI to prove idempotency.
- **Rejected:** a version that derived the court from the case number alone (wrong for appeals); a single structured call for classification (the free-form map first cut invented codes); treating optional holidays as closed days (it postponed dates the court might not honour).
- **Commits:** made with an AI coding assistant; attribution trailers are omitted and AI usage is documented here.

## Evaluation

The engine is tested against fifteen golden cases computed by hand over the real 2026 calendars of two courts: holidays in the middle, availability on a Friday and on a Saturday, Ash Wednesday as a reduced-hours first day and as a due date, a count crossing the recess without a calendar for the next year, Corpus Christi on both courts, calendar days ending on a Sunday, and a court without a calendar. Synthetic calendars cover the edges the real ones do not: the recess for calendar days, publication during a closed recess, suspension by order, district holidays, review and coverage warnings.

The classifier has not been measured on real publications yet: the original pilot had the capture and the engine running on 82 real publications from ten courts in two days, and the classification code ready, when the port to this repository was made. The measurement plan is fixed: 50 real publications classified through `--triage-only --limit 50`, reviewed by a lawyer, with the agreement rate, the review rate and the cost per publication recorded here. Until then the twelve fixture publications exercise every decision branch, and the table above is what a run looks like.

## Cost & latency

Two model calls per publication needing classification, with the catalogue in a cached system prompt. At Sonnet 5 list prices and a median publication of about 7,000 characters, that is on the order of one cent per publication; long appellate decisions are excerpted to 12,000 characters before the first call. The CLI prints the measured USD per publication after every run so the pilot replaces this estimate with a number. Pre-filtered publications (assignment lists, sealed cases, cancellations) cost nothing. The sweep is one paginated request per bar number per day and finishes in seconds.

## Known failure modes

- **Very long acts are excerpted.** Head, tail and windows around deadline markers are kept and the cut is marked; a deadline stated only in an unmarked middle passage can be missed. The row shows the truncation flag.
- **Municipal holidays** of the labour court are not transcribed (`local_coverage: partial`), so every result from that court carries a warning to check the district. District holidays of the state court apply only when the district name appears in the publishing unit.
- **Next year's calendars** are published between October and January; from December onwards nothing computes until they are added, because the recess pushes deadlines into the new year. The health check starts asking for them in November.
- **Small-claims courts** count deadlines in a way the case law disputes; the whole family is in review until the legal team decides once and records it in the catalogue.
- **Doubled deadlines** (public treasury, public prosecutor, public defender, co-parties with different counsel) are flagged, never computed.
- **The court's own "document type" field is unreliable** (free text such as "57" or a sentence), which is why the model reads the body and that field is only context.

## Data & privacy

The gazette is public by definition, and reading it has no procedural effect. In production the state database holds the publications addressed to the firm's lawyers (case numbers, parties, the text of the act) on the firm's own machine; the model receives the body of the publication and nothing else; e-mails go through the firm's Microsoft 365 tenant. Bar numbers are configuration, never code. This repository runs on fictional data only: invented parties and lawyers, a state code that does not exist, case numbers dated 2099 whose check digits are completed at load time. The system is decision support: a lawyer confirms every date, and the digest says so.

## Tests & CI

`uv run pytest` runs 161 tests, all offline: configuration parsing (including the `.env` rule where a filled value below an empty placeholder must win), the gazette client against a fake session (pagination, cap warning, retry policy), the state's idempotency, the CNJ number parser and court reference, the calendar files, the engine on synthetic calendars and on the golden cases, the catalogue rules and the consistency of the committed catalogue with its source, the two-call classifier against a fake client, every decision branch, the triage end to end with a fake model, the sweep, the health check, the report, the mailers and the whole demo path through the CLI. CI runs lint, the tests, a check that the catalogue is up to date, the demo twice with delivery to the outbox, the health check, a stand-alone computation and a gitleaks scan.

## Stack

`Python 3.12` `uv` `requests` `SQLite` `Anthropic SDK (structured outputs, prompt caching)` `Pydantic` `Microsoft Graph` `pytest` `ruff` `GitHub Actions`

## Running locally

```bash
git clone https://github.com/fillipeml/court-deadline-triage
cd court-deadline-triage
uv sync
cp .env.example .env                   # DEMO_MODE=true by default
uv run deadline-triage                 # sweep the fixture gazette, triage, print the table
uv run deadline-triage                 # nothing new: idempotent
uv run deadline-triage --health
uv run deadline-triage --compute 2026-09-21 15 business TJGO
uv run pytest
```

Set `DRY_RUN=false` (and delete `.demo/` to replay) to see the digest delivered to `.demo/output/outbox/`. Live mode: set `DEMO_MODE=false`, the lawyers' bar numbers in `BAR_NUMBERS`, an `ANTHROPIC_API_KEY`, and the Graph settings for delivery; keep `DRY_RUN=true` until the first digest looks right. `scripts/register_scheduled_task.ps1` registers the daily run on Windows. With Docker: `docker build -t court-deadline-triage . && docker run --rm -v triage-data:/data court-deadline-triage`.

## Demo mode

`DEMO_MODE=true` swaps the gazette client for twelve fixture publications, the model for a classifier that replays canned answers, and Microsoft Graph for a local outbox, and pins the reference date to 2026-09-21 so the dates are the same on any day. Business logic does not change. See [docs/DEMO.md](docs/DEMO.md) for the walkthrough.

## What I'd do next

- Run the 50-publication measurement with a lawyer and publish the agreement rate and the cost per publication.
- Transcribe the calendars of the other eight courts seen in the pilot, and the 2027 files as the courts publish them.
- Close the loop: a review card in the team's mailbox to confirm or adjust each date, recorded back into the `triages` table with author and time.

## Glossary

Brazilian legal terms kept in Portuguese, and the gazette's wire field names, are explained in [docs/GLOSSARY.md](docs/GLOSSARY.md).

## Licence

MIT
