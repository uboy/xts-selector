"""
CLI for xts_compare.

Usage:
  # Two-run comparison
  python3 -m arkui_xts_selector.xts_compare \\
      --base <zip_or_dir> --target <zip_or_dir> \\
      [--json] [--output report.json] \\
      [--module-filter "ActsButton*"] \\
      [--show-stable] [--show-persistent]

  # Timeline mode (N runs)
  python3 -m arkui_xts_selector.xts_compare \\
      --timeline <zip1> <zip2> <zip3> ... \\
      [--labels "base,fix1,fix2"] \\
      [--json] [--output timeline.json]

Exit codes:
  0  No regressions found (or timeline mode completed successfully).
  1  Regressions were found.
  2  Error (bad arguments, file not found, parse failure, etc.).
"""

from __future__ import annotations

import argparse
import sys
import traceback

from .compare import compare_runs, build_timeline
from .format_json import report_to_dict, timeline_to_dict, write_json
from .format_terminal import format_report, format_timeline
from .models import FailureType
from .parse import load_run
from .selector_integration import correlate_with_selector, load_selector_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m arkui_xts_selector.xts_compare",
        description=(
            "Compare XTS test results between two runs (or build a timeline "
            "across N runs).  Accepts ZIP archives or directories produced by "
            "xdevice."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--base",
        metavar="PATH",
        help="Base run archive (ZIP) or result directory.",
    )
    mode.add_argument(
        "--timeline",
        nargs="+",
        metavar="PATH",
        help="Two or more run archives for timeline mode.",
    )

    parser.add_argument(
        "--target",
        metavar="PATH",
        help="Target run archive (ZIP) or result directory (required with --base).",
    )
    parser.add_argument(
        "--selector-report",
        metavar="FILE",
        default=None,
        dest="selector_report",
        help="Optional selector JSON report to correlate predicted suites with actual regressions.",
    )
    parser.add_argument(
        "--labels",
        metavar="LABELS",
        help=(
            "Comma-separated list of custom run labels.  "
            "In compare mode: two labels.  In timeline mode: one per run."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit JSON output instead of terminal text.",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write output to FILE instead of stdout.",
    )
    parser.add_argument(
        "--module-filter",
        metavar="GLOB",
        default=None,
        dest="module_filter",
        help=(
            "Restrict terminal output to modules matching this glob pattern "
            "(e.g. 'ActsButton*').  JSON output is always unfiltered."
        ),
    )
    parser.add_argument(
        "--suite-filter",
        metavar="GLOB",
        default=None,
        dest="suite_filter",
        help="Restrict terminal output to suites matching this glob pattern.",
    )
    parser.add_argument(
        "--case-filter",
        metavar="GLOB",
        default=None,
        dest="case_filter",
        help="Restrict terminal output to test cases matching this glob pattern.",
    )
    parser.add_argument(
        "--failure-type",
        metavar="TYPES",
        default=None,
        dest="failure_type",
        help=(
            "Comma-separated failure types for terminal filtering. "
            "Supported: crash, timeout, assertion, cast, resource, unknown."
        ),
    )
    parser.add_argument(
        "--sort",
        metavar="KEY",
        default="module",
        choices=("module", "severity", "time-delta"),
        dest="sort_key",
        help="Terminal sort key: module, severity, or time-delta.",
    )
    parser.add_argument(
        "--min-time-delta",
        metavar="MS",
        default=1000.0,
        type=float,
        dest="min_time_delta",
        help="Minimum absolute timing delta in milliseconds for performance changes.",
    )
    parser.add_argument(
        "--min-time-ratio",
        metavar="RATIO",
        default=3.0,
        type=float,
        dest="min_time_ratio",
        help="Minimum relative timing ratio for performance changes.",
    )
    parser.add_argument(
        "--show-stable",
        action="store_true",
        default=False,
        dest="show_stable",
        help="Include STABLE_PASS tests in terminal output (very verbose).",
    )
    parser.add_argument(
        "--show-persistent",
        action="store_true",
        default=False,
        dest="show_persistent",
        help="Include PERSISTENT_FAIL details section in terminal output.",
    )
    return parser


def _parse_failure_types(raw: str | None) -> set[FailureType] | None:
    """Parse a comma-separated list of failure types."""
    if not raw:
        return None

    mapping = {
        "crash": FailureType.CRASH,
        "timeout": FailureType.TIMEOUT,
        "assert": FailureType.ASSERTION,
        "assertion": FailureType.ASSERTION,
        "cast": FailureType.CAST_ERROR,
        "cast_error": FailureType.CAST_ERROR,
        "resource": FailureType.RESOURCE,
        "unknown": FailureType.UNKNOWN_FAIL,
    }
    result: set[FailureType] = set()
    invalid: list[str] = []
    for chunk in raw.split(","):
        token = chunk.strip().lower()
        if not token:
            continue
        ftype = mapping.get(token)
        if ftype is None:
            invalid.append(chunk.strip())
        else:
            result.add(ftype)
    if invalid:
        raise ValueError(
            "unknown failure type(s): " + ", ".join(invalid)
        )
    return result or None


def _parse_labels(raw: str | None, count: int) -> list[str]:
    """Split a comma-separated labels string; pad/truncate to match count."""
    if not raw:
        return [""] * count
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) < count:
        parts.extend([""] * (count - len(parts)))
    return parts[:count]


def _emit(text: str, output_path: str | None) -> None:
    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


def _run_compare(args: argparse.Namespace) -> int:
    if not args.target:
        print(
            "error: --target is required when using --base",
            file=sys.stderr,
        )
        return 2

    labels = _parse_labels(args.labels, 2)
    base_label = labels[0] or None
    target_label = labels[1] or None
    try:
        failure_types = _parse_failure_types(args.failure_type)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        base_meta, base_results = load_run(args.base, label=base_label or "")
        target_meta, target_results = load_run(args.target, label=target_label or "")
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"error loading run: {exc}", file=sys.stderr)
        return 2

    # If the user supplied labels, override the auto-detected ones.
    if base_label:
        base_meta.label = base_label
    if target_label:
        target_meta.label = target_label

    report = compare_runs(
        base_meta,
        base_results,
        target_meta,
        target_results,
        min_time_delta_ms=args.min_time_delta,
        min_time_ratio=args.min_time_ratio,
    )
    if args.selector_report:
        try:
            selector_report = load_selector_report(args.selector_report)
        except (FileNotFoundError, ValueError, OSError) as exc:
            print(f"error loading selector report: {exc}", file=sys.stderr)
            return 2
        report.selector_correlations = correlate_with_selector(report, selector_report)

    if args.json:
        data = report_to_dict(report)
        if args.output:
            write_json(data, args.output)
            print(f"JSON report written to: {args.output}", file=sys.stderr)
        else:
            text = write_json(data)
            sys.stdout.write(text)
            sys.stdout.write("\n")
    else:
        text = format_report(
            report,
            show_stable=args.show_stable,
            show_persistent=args.show_persistent,
            module_filter=args.module_filter,
            suite_filter=args.suite_filter,
            case_filter=args.case_filter,
            failure_types=failure_types,
            sort_key=args.sort_key,
        )
        _emit(text, args.output)

    # Exit code: 1 if any regressions, else 0.
    return 1 if report.summary.regression > 0 else 0


def _run_timeline(args: argparse.Namespace) -> int:
    paths = args.timeline
    labels = _parse_labels(args.labels, len(paths))

    runs = []
    for path, label in zip(paths, labels):
        try:
            meta, results = load_run(path, label=label or "")
        except (FileNotFoundError, ValueError, OSError) as exc:
            print(f"error loading run '{path}': {exc}", file=sys.stderr)
            return 2
        if label:
            meta.label = label
        runs.append((meta, results))

    timeline = build_timeline(runs)

    if args.json:
        data = timeline_to_dict(timeline)
        if args.output:
            write_json(data, args.output)
            print(f"JSON timeline written to: {args.output}", file=sys.stderr)
        else:
            text = write_json(data)
            sys.stdout.write(text)
            sys.stdout.write("\n")
    else:
        text = format_timeline(timeline)
        _emit(text, args.output)

    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to compare or timeline mode."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.base is not None:
            return _run_compare(args)
        else:
            return _run_timeline(args)
    except KeyboardInterrupt:
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"unexpected error: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2
