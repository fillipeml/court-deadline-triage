# CLAUDE.md

Working rules for AI-assisted changes in this repository. They mirror the README; the README wins on conflict.

## Non-negotiable rules

1. **The model never computes a date.** `classifier.py` returns a catalogue code, the number of days only when written in the act, flags and a literal excerpt. `decision.py` decides; `engine.py` counts. No date arithmetic may move into a prompt.
2. **Never estimate.** A court or year without a calendar file raises `MissingCoverageError` and the row goes to review with the reason. Do not add fallbacks that guess a calendar.
3. **Unknown means a human.** Sealed, cancelled, outside the catalogue, low confidence, doubled-deadline hint, days in the act that contradict the law: each is a review with a stated reason, never a computed date.
4. **Calendars transcribe the official act.** A new calendar file cites the court's act (`source.url`), declares `local_coverage`, starts with `review.status: pending`, and marks an optional holiday whose effect is unstated with `confirmed: false`. The art. 220 suspension stays in code.
5. **A rule change needs a golden case.** Any change to `engine.py` or `court_calendar.py` comes with a hand-computed case in `tests/golden/cases.json` or a synthetic-calendar test.
6. **Reading the gazette is not acknowledging service.** Do not import the read-only constraint of the electronic judicial domicile project here; the objects of this pipeline are the served acts themselves.

## Conventions

- Python 3.12, `uv`, `ruff`, `pytest`. Batch CLI, not a web app.
- `DEMO_MODE` and `DRY_RUN` are read only in `config.py` and `factory.py`; business modules never check them.
- API field names (Portuguese) are mapped once, in `djen.py`. Everything else is English; catalogue event names stay Portuguese with an English gloss. Terms are in `docs/GLOSSARY.md`.
- `catalogue/events.json` is generated: change `catalogue/events.source.json` or `catalogue_rules.py` and run `build-catalogue`. Never edit the generated file by hand; CI checks it is current.
- Tests run offline. Any new external call gets a fake in the tests and a fixture adapter in `demo.py`.
- Fixtures contain only invented parties and lawyers; case numbers use year 2099 with `XX` check digits completed at load time; the bar state `ZZ` does not exist.
- Never commit `.env`, `data/`, `output/`, `.demo/`.
- Commits: English, Conventional Commits, one logical change each, no AI attribution trailers.
