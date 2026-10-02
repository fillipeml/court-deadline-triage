# Demo walkthrough (about three minutes)

Everything runs offline. No API key, no network, no mail credential.

```bash
uv sync
cp .env.example .env        # DEMO_MODE=true, DRY_RUN=true
```

## 1. The sweep and the triage

```bash
uv run deadline-triage
```

The fixture gazette holds twelve publications addressed to two fictional lawyers (bar numbers
`12345/ZZ` and `67890/ZZ`; the state "ZZ" does not exist) inside a window ending on the pinned
reference date, 2026-09-21. One publication serves both lawyers, so the sweep lists 13 and stores
12. The triage then runs every publication through the pre-filter, the fixture classifier, the
decision and the engine, and prints the table. What to look for:

| Row | What it shows |
|---|---|
| `Contestação`, TJGO, due 2026-10-14 | golden case A: 15 business days from a Monday, with the 12 October holiday skipped |
| `Recurso Ordinário Trabalhista`, TRT18, due 2026-10-01 | an 8-day labour deadline available on a Friday: published Monday, count starts Tuesday |
| `Manifestação Diversa`, due 2026-09-28 | the number of days came from the act ("5 (cinco) dias"), not from the law; published Monday because it was made available on a Saturday |
| `Recurso de Revista`, TRT18 | a 40,000-character appellate decision: excerpted before classification, the row carries the truncation flag |
| `Contestação`, TRT18, priority review with a date | the case number belongs to the state court: the date is computed by the publishing court's calendar and the row is flagged |
| `Embargos de Declaração`, TJMG, priority review | deadline identified, date not computed: there is no calendar for TJMG. The engine never estimates |
| `Contestação`, TJGO, priority review | the act mentions the public treasury's doubled deadline: flagged, never computed doubled |
| `Audiência de Conciliação`, review | a hearing scheduled for 20/10/2026 is a docket date, not a counted deadline |
| two `PRIORITY_REVIEW` rows without a type | a sealed case (body not published) and a cancelled publication, both resolved by the pre-filter without the model |
| two `NO_DEADLINE` rows | a case-assignment list (pre-filter) and a mere notice of a filing (model, high confidence) |

Run the command again: nothing is new, nothing is triaged twice.

## 2. The digest and the CSV

```bash
rm -rf .demo                            # replay the run with delivery on
DRY_RUN=false uv run deadline-triage
```

Step 1 has already triaged everything, so `--triage-only` on top of it finds nothing left to
do and delivers nothing. The state is reset and the whole run repeated instead.

With `DRY_RUN=false` the digest is delivered. In demo mode delivery means a text file in
`.demo/output/outbox/`, exactly what the team would receive: the counts, the table, the legend and
the sentence that every date is a proposal for a lawyer to confirm. The CSV of the run is in
`.demo/output/triage-2026-09-21.csv`, with the five visible columns first and the legal grounds,
warnings and hash after them. (Delete `.demo/` to replay the first run with delivery on.)

## 3. The health check

```bash
uv run deadline-triage --health
```

Reports the configuration, the recent runs, the known publications and the calendar coverage for
every court that actually published. In the demo the verdict is ATTENTION on purpose: the fixture
from TJMG has no calendar, and that is the kind of gap the check exists to surface.

## 4. A stand-alone computation

```bash
uv run deadline-triage --compute 2026-09-21 15 business TJGO
uv run deadline-triage --compute 2026-02-12 5 business TJGO      # Ash Wednesday as a reduced-hours day
uv run deadline-triage --compute 2026-11-30 15 business TJGO     # crosses the recess: not computed, no 2027 file
uv run deadline-triage --compute 2026-09-21 3 business TJGO --unit "Goiania - 1a Vara Civel"
```

Prints the two jumps, the count, the legal grounds, every non-business day considered, the
calendar files and versions used, and the warnings (calendars pending human review, unconfirmed
optional holidays, district holidays not applied).

## 5. The catalogue

```bash
uv run build-catalogue
```

Rebuilds `catalogue/events.json` from the curated source, deriving the calculation mode of each of
the 86 events by rule, and preserving any validation the legal team has recorded. CI fails when the
committed catalogue is stale.

## Live mode

Set `DEMO_MODE=false`, the lawyers' bar numbers, an Anthropic API key and, for delivery, the
Microsoft Graph application settings. `deadline-triage --sample 30` saves raw and normalised
publications for study without touching the state; `--triage-only --limit 50` runs the
classification on pending publications and prints the measured cost per publication.
