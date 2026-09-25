# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-25

### Added

- Gazette client for the public DJEN API, queried by bar number with pagination, retries and the
  10,000-count cap warning; wire fields mapped once into an English record.
- SQLite state with idempotency by the API hash, bar numbers accumulated per publication, triage
  rows with the full audit trail, and a run history.
- Deterministic deadline engine: publication and first-day jumps, business or calendar days, the
  art. 220 suspension, reduced-hours and district holidays, warnings for unreviewed calendars and
  unconfirmed days; calendars for 2026 (national, TJGO, TRT18) and 2027 (national).
- Event catalogue of 86 procedural events with calculation modes derived by rule from the legal
  text, human validation blocks and a build command checked in CI.
- Two-call classifier (free-form map, then structured output) with the catalogue in a cached
  system prompt, a pre-filter that resolves sealed, cancelled and assignment-list publications
  without the model, and a deterministic decision layer.
- Report (console table, CSV, daily digest), failure alerts, health check, Microsoft Graph and
  outbox mailers, fixture gazette and fixture classifier for the offline demo.
- 161 offline tests including fifteen hand-computed golden cases; CI with lint, tests, catalogue
  freshness, the demo run twice and secret scanning.
