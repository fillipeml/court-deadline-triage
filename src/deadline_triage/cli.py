"""Command line of the deadline triage.

    deadline-triage                       # sweep the window for the configured bar numbers, then triage
    deadline-triage --window-days 7
    deadline-triage --bar 12345/SP        # only these bar numbers, ignoring BAR_NUMBERS
    deadline-triage --sample 30           # save raw + normalised publications for study (no state)
    deadline-triage --triage-only --limit 50   # classify pending publications without sweeping
    deadline-triage --health              # health of the pilot, no API call
    deadline-triage --compute 2026-09-21 15 business TJGO [--unit "Goiania - 1a Vara Civel"]

Read-only: reading a publication in the gazette does not acknowledge service.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from .alerts import send_digest, send_failure, summary
from .config import BarNumber, Config
from .djen import ApiError
from .factory import build_classifier, build_client, build_mailer


def _compute(available_on: str, days: str, regime: str, court: str, unit: str | None) -> int:
    """Stand-alone computation by the engine, for a human to check a date."""
    from .court_calendar import Calendars, InvalidCalendarError, MissingCoverageError
    from .engine import compute

    try:
        r = compute(
            date.fromisoformat(available_on),
            int(days),
            regime.lower(),
            court,
            Calendars(),
            unit=unit,
        )
    except MissingCoverageError as error:
        print(f"NOT COMPUTED: {error}")
        return 3
    except (ValueError, InvalidCalendarError) as error:
        print(f"Invalid input or calendar: {error}", file=sys.stderr)
        return 1
    print(f"Court: {r.court}" + (f" | unit: {unit}" if unit else ""))
    print(r.summary())
    print("\nLegal grounds:")
    print("\n".join(f"  - {g}" for g in r.grounds))
    if r.skipped_days:
        print("\nNon-business days considered:")
        print("\n".join(f"  - {d}" for d in r.skipped_days))
    print(f"\nCalendars: {', '.join(r.calendars)}")
    if r.warnings:
        print("\nWARNINGS:")
        print("\n".join(f"  ! {w}" for w in r.warnings))
    return 0


def _triage(config: Config) -> int:
    """Classify pending publications (pre-filter, model, decision, engine) and report."""
    from .catalogue import Catalogue
    from .court_calendar import Calendars
    from .report import render_digest, render_table, write_csv
    from .state import State
    from .triage import triage_pending

    catalogue = Catalogue()
    classifier = build_classifier(config, catalogue)
    if classifier is None:
        reason = "LLM_DISABLED=true" if config.llm_disabled else "ANTHROPIC_API_KEY empty"
        print(f"Model off ({reason}): only the pre-filter is recorded; the rest stays pending.")
    model = getattr(classifier, "model", None) or (config.classifier_model if classifier else None)

    state = State(config.db_path)
    try:
        r = triage_pending(
            state, classifier, catalogue, Calendars(), model,
            limit=config.triage_limit, require_validated=config.require_validated_catalogue,
        )  # fmt: skip
    finally:
        state.close()
    print("Triage:")
    print(f"  pending read: {r['pending']} | triaged: {r['triaged']} | by action: {r['by_action']}")
    if r["awaiting_llm"]:
        print(f"  awaiting the model: {r['awaiting_llm']}")
    if r["with_llm"]:
        print(
            f"  classified by the model: {r['with_llm']} | cost USD {r['cost_usd']:.4f} "
            f"| mean per publication USD {r['mean_cost_usd']:.5f}"
        )
    for failure in r["failures"]:
        print(f"  FAILURE (stays pending): {failure}", file=sys.stderr)

    if r["rows"]:
        today = config.today
        print()
        print(render_table(r["rows"], today, config.urgent_business_days))
        path = write_csv(r["rows"], config.output_dir / f"triage-{today.isoformat()}.csv")
        print(f"\nCSV: {path}")
        subject, body = render_digest(r["rows"], today, config.urgent_business_days)
        delivered = send_digest(config, build_mailer(config), subject, body)
        print(f"Digest e-mail: {'delivered' if delivered else 'not delivered (DRY_RUN or error)'}")
    return 2 if r["failures"] and not r["triaged"] else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Court deadline triage from the national electronic gazette (DJEN)"
    )
    parser.add_argument(
        "--window-days", type=int, default=None, help="days to look back in the sweep"
    )
    parser.add_argument(
        "--bar",
        action="append",
        metavar="NUMBER/STATE",
        help="bar number to sweep (repeatable); ignores BAR_NUMBERS",
    )
    parser.add_argument(
        "--sample",
        type=int,
        metavar="N",
        help="save the first N publications for schema study (no state)",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="check the health of the pilot without calling the API",
    )
    parser.add_argument(
        "--compute", nargs=4, metavar=("AVAILABLE_ON", "DAYS", "REGIME", "COURT"),
        help="compute one due date with the engine (e.g. 2026-09-21 15 business TJGO)",
    )  # fmt: skip
    parser.add_argument(
        "--triage-only",
        action="store_true",
        help="do not sweep; only classify pending publications",
    )
    parser.add_argument(
        "--limit", type=int, help="maximum publications sent to the model in this run"
    )
    parser.add_argument(
        "--unit", help="unit/district of the publication, for local holidays (with --compute)"
    )
    args = parser.parse_args()

    if args.compute:
        return _compute(*args.compute, unit=args.unit)

    if args.health:
        from .health import report

        text, code = report(Config.from_env())
        print(text)
        return code

    config = Config.from_env()
    if args.window_days is not None:
        config.window_days = args.window_days
    if args.bar:
        try:
            config.bar_numbers = [BarNumber.parse(b) for b in args.bar]
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
    try:
        config.require_bar_numbers()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    mode = "DEMO (fixtures)" if config.demo_mode else config.djen_base_url
    print(
        f"Source: {mode} | bars: {', '.join(str(b) for b in config.bar_numbers)} | "
        f"window: {config.window_days} day(s) to {config.today} | DRY_RUN: {config.dry_run}"
    )

    if args.limit is not None:
        config.triage_limit = args.limit
    if args.triage_only:
        return _triage(config)

    from .sweep import run, sample

    client = build_client(config)
    try:
        if args.sample:
            target = sample(config, args.sample, client)
            print(f"Sample saved to {target} (outside version control).")
            return 0
        report = run(config, client)
    except ApiError as error:
        print(f"SWEEP FAILURE: {error}", file=sys.stderr)
        print(
            "Action: check today's publications by hand (contingency) and investigate the cause.",
            file=sys.stderr,
        )
        try:
            from .state import State

            state = State(config.db_path)
            state.record_run(
                success=False,
                bars=[str(b) for b in config.bar_numbers],
                dry_run=config.dry_run,
                error=str(error)[:500],
            )
            state.close()
        except Exception as exc:  # noqa: BLE001 - recording must never mask the original failure
            print(f"WARNING: could not record the failure in the history: {exc}", file=sys.stderr)
        delivered = send_failure(config, build_mailer(config), str(error))
        print(
            f"Failure alert e-mail: {'delivered' if delivered else 'not delivered (DRY_RUN or error)'}",
            file=sys.stderr,
        )
        return 2

    print("Sweep report:")
    print(summary(report))

    if report["failed_bars"]:
        errors = "; ".join(report["failed_bars"])
        print(f"FAILURE on bar number(s): {errors}", file=sys.stderr)
        delivered = send_failure(
            config, build_mailer(config), f"bar number(s) failed in the sweep: {errors}"
        )
        print(
            f"Failure alert e-mail: {'delivered' if delivered else 'not delivered (DRY_RUN or error)'}",
            file=sys.stderr,
        )
        return 2
    return _triage(config)


if __name__ == "__main__":
    sys.exit(main())
