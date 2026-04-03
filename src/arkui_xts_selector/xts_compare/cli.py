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
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import ParseError as XmlParseError

from .compare import compare_runs, build_timeline
from .format_html import format_html, format_single_run_html
from .format_json import report_to_dict, single_run_to_dict, timeline_to_dict, write_json
from .format_terminal import format_report, format_single_run, format_timeline
from .models import FailureType, InputOrderInfo
from .parse import discover_archives_with_metadata, find_summary_xml, load_run, sort_run_paths
from .selector_integration import correlate_with_selector, load_selector_report


class XtsCompareArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args: list[str] | None = None, namespace: argparse.Namespace | None = None) -> argparse.Namespace:
        parsed = super().parse_args(args, namespace)
        _validate_args(self, parsed)
        return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = XtsCompareArgumentParser(
        prog="python3 -m arkui_xts_selector.xts_compare",
        description=(
            "Compare XTS test results between two runs (or build a timeline "
            "across N runs).  Accepts ZIP archives or directories produced by "
            "xdevice."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode = parser.add_mutually_exclusive_group(required=False)
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
        "paths",
        nargs="*",
        metavar="PATH",
        help="Positional run archives or a results directory.",
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
        "--html",
        action="store_true",
        default=False,
        help="Emit standalone HTML output instead of terminal text.",
    )
    parser.add_argument(
        "-o",
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
        default=None,
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
        "--show-stable-blocked",
        action="store_true",
        default=False,
        dest="show_stable_blocked",
        help="Include STABLE_BLOCKED tests in terminal output.",
    )
    parser.add_argument(
        "--show-persistent",
        action="store_true",
        default=False,
        dest="show_persistent",
        help="Include PERSISTENT_FAIL details section in terminal output.",
    )
    parser.add_argument(
        "--regressions-only",
        action="store_true",
        default=False,
        dest="regressions_only",
        help="Terminal compare output: summary plus only the REGRESSION section.",
    )
    parser.add_argument(
        "--scan-recursive",
        action="store_true",
        default=False,
        dest="scan_recursive",
        help="Directory-scan mode: search subdirectories recursively for XTS archives.",
    )
    parser.add_argument(
        "--scan-glob",
        metavar="GLOB",
        default=None,
        dest="scan_glob",
        help="Directory-scan mode: only consider archive names/relative paths matching this glob.",
    )
    parser.add_argument(
        "--scan-limit",
        metavar="N",
        type=int,
        default=0,
        dest="scan_limit",
        help="Directory-scan mode: keep only the newest N discovered archives after ordering. 0 = unlimited.",
    )
    parser.add_argument(
        "--strict-archive",
        action="store_true",
        default=False,
        dest="strict_archive",
        help="Reject archives containing skipped special entries instead of reporting them as notices.",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    explicit_mode = args.base is not None or args.timeline is not None
    if args.base is not None and args.paths:
        parser.error("positional paths are not allowed with --base")
    if args.timeline is not None and args.paths:
        parser.error("positional paths are not allowed with --timeline")
    if args.target is not None and args.base is None:
        parser.error("--target requires --base")
    if not explicit_mode and not args.paths:
        parser.error("one of the arguments --base, --timeline, or PATH is required")
    if args.scan_limit < 0:
        parser.error("--scan-limit must be >= 0")


def _infer_output_mode(args: argparse.Namespace) -> None:
    if not args.output or args.json or args.html:
        return
    suffix = Path(args.output).suffix.lower()
    if suffix == ".json":
        args.json = True
    elif suffix in (".html", ".htm"):
        args.html = True


def _resolve_mode(args: argparse.Namespace) -> str:
    if args.base is not None:
        return "compare"
    if args.timeline is not None:
        return "timeline"
    if len(args.paths) == 1:
        candidate = Path(args.paths[0]).expanduser()
        if not candidate.exists():
            return "single-run"
        if candidate.is_file():
            return "single-run"
        if candidate.is_dir() and find_summary_xml(candidate) is not None:
            return "single-run"
        return "directory-scan"
    if len(args.paths) == 2:
        return "compare"
    if len(args.paths) >= 3:
        return "timeline"
    return "invalid"


def _set_input_order(
    args: argparse.Namespace,
    mode: str,
    source: str,
    auto_detected: bool,
    paths: list[str],
    origin: str,
    details: dict[str, str] | None = None,
) -> None:
    args.input_order = InputOrderInfo(
        mode=mode,
        source=source,
        auto_detected=auto_detected,
        origin=origin,
        original_paths=list(paths),
        ordered_paths=list(paths),
        details=dict(details or {}),
    )


def _prepare_compare_args(args: argparse.Namespace) -> None:
    if args.base is not None:
        _set_input_order(
            args,
            mode="compare",
            source="explicit",
            auto_detected=False,
            paths=[args.base, args.target] if args.target else [args.base],
            origin="flags",
            details={path: Path(path).name for path in [args.base, args.target] if path},
        )
        return

    original_paths = list(args.paths[:2])
    ordered_paths, source, details = sort_run_paths(original_paths)
    args.base = ordered_paths[0]
    args.target = ordered_paths[1]
    args.input_order = InputOrderInfo(
        mode="compare",
        source=source,
        auto_detected=True,
        origin="positional",
        original_paths=original_paths,
        ordered_paths=ordered_paths,
        details=details,
    )

    if source == "alphabetical":
        message = (
            "Auto-detected compare order (alphabetical fallback): "
            f"base={Path(args.base).name} -> target={Path(args.target).name}"
        )
    else:
        message = (
            f"Auto-detected compare order ({source}): "
            f"base={Path(args.base).name} [{details[args.base]}] -> "
            f"target={Path(args.target).name} [{details[args.target]}]"
        )
    print(message, file=sys.stderr)


def _prepare_timeline_args(args: argparse.Namespace) -> None:
    if args.timeline is None:
        original_paths = list(args.paths)
        ordered_paths, source, details = sort_run_paths(original_paths)
        args.timeline = ordered_paths
        args.input_order = InputOrderInfo(
            mode="timeline",
            source=source,
            auto_detected=True,
            origin="positional",
            original_paths=original_paths,
            ordered_paths=ordered_paths,
            details=details,
        )
        print(
            f"Auto-detected timeline order ({source}): "
            + " -> ".join(f"{Path(path).name} [{details[path]}]" for path in ordered_paths),
            file=sys.stderr,
        )
        return
    _set_input_order(
        args,
        mode="timeline",
        source="explicit",
        auto_detected=False,
        paths=list(args.timeline),
        origin="flags",
        details={path: Path(path).name for path in args.timeline},
    )


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
    if args.json and args.html:
        print("error: --json and --html cannot be used together", file=sys.stderr)
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
        base_meta, base_results = load_run(args.base, label=base_label or "", strict_archive=args.strict_archive)
        target_meta, target_results = load_run(args.target, label=target_label or "", strict_archive=args.strict_archive)
    except (FileNotFoundError, ValueError, OSError, XmlParseError) as exc:
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
    report.input_order = getattr(args, "input_order", InputOrderInfo(mode="compare", source="explicit"))
    if args.selector_report:
        try:
            selector_report = load_selector_report(args.selector_report)
        except (FileNotFoundError, ValueError, OSError) as exc:
            print(f"error loading selector report: {exc}", file=sys.stderr)
            return 2
        report.selector_correlations = correlate_with_selector(report, selector_report)

    if not args.show_persistent and report.summary.regression == 0 and report.summary.persistent_fail > 0:
        args.show_persistent = True

    if args.html and not args.output:
        args.output = f"xts_compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        print(f"HTML output requires a file. Writing to: {args.output}", file=sys.stderr)

    if args.json:
        data = report_to_dict(report)
        if args.output:
            write_json(data, args.output)
            print(f"JSON report written to: {args.output}", file=sys.stderr)
        else:
            text = write_json(data)
            sys.stdout.write(text)
            sys.stdout.write("\n")
    elif args.html:
        text = format_html(report)
        _emit(text, args.output)
    else:
        sort_key = args.sort_key
        if sort_key is None:
            sort_key = "severity" if report.summary.regression > 0 else "module"
        text = format_report(
            report,
            show_stable=args.show_stable,
            show_stable_blocked=args.show_stable_blocked,
            show_persistent=args.show_persistent,
            module_filter=args.module_filter,
            suite_filter=args.suite_filter,
            case_filter=args.case_filter,
            failure_types=failure_types,
            sort_key=sort_key,
            regressions_only=args.regressions_only,
        )
        _emit(text, args.output)

    # Exit code: 1 if any regressions, else 0.
    return 1 if report.summary.regression > 0 else 0


def _run_timeline(args: argparse.Namespace) -> int:
    if args.html:
        print("error: --html is only supported in compare mode", file=sys.stderr)
        return 2
    paths = args.timeline
    labels = _parse_labels(args.labels, len(paths))

    runs = []
    for path, label in zip(paths, labels):
        try:
            meta, results = load_run(path, label=label or "", strict_archive=args.strict_archive)
        except (FileNotFoundError, ValueError, OSError, XmlParseError) as exc:
            print(f"error loading run '{path}': {exc}", file=sys.stderr)
            return 2
        if label:
            meta.label = label
        runs.append((meta, results))

    timeline = build_timeline(runs)
    timeline.input_order = getattr(args, "input_order", InputOrderInfo(mode="timeline", source="explicit"))

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


def _run_single(path: str, args: argparse.Namespace) -> int:
    label = _parse_labels(args.labels, 1)[0] or None
    try:
        meta, results = load_run(path, label=label or "", strict_archive=args.strict_archive)
    except (FileNotFoundError, ValueError, OSError, XmlParseError) as exc:
        print(f"error loading run: {exc}", file=sys.stderr)
        return 2

    if label:
        meta.label = label

    if args.json:
        data = single_run_to_dict(meta, results)
        if args.output:
            write_json(data, args.output)
            print(f"JSON summary written to: {args.output}", file=sys.stderr)
        else:
            text = write_json(data)
            sys.stdout.write(text)
            sys.stdout.write("\n")
        return 0

    if args.html:
        if not args.output:
            args.output = f"xts_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            print(f"HTML output requires a file. Writing to: {args.output}", file=sys.stderr)
        _emit(format_single_run_html(meta, results), args.output)
        return 0

    _emit(format_single_run(meta), args.output)
    return 0


def _run_directory_scan(args: argparse.Namespace) -> int:
    scan_root = args.paths[0]
    try:
        discovery = discover_archives_with_metadata(
            scan_root,
            recursive=args.scan_recursive,
            pattern=args.scan_glob,
            limit=args.scan_limit,
            strict_archive=args.strict_archive,
        )
        archives = discovery.paths
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as exc:
        print(f"error scanning directory: {exc}", file=sys.stderr)
        return 2

    if not archives:
        print(f"error: no XTS archives found in {scan_root}", file=sys.stderr)
        return 2

    print(
        f"Found {len(archives)} archive(s): {', '.join(Path(path).name for path in archives)}",
        file=sys.stderr,
    )

    if len(archives) == 1:
        print("Entering single-run summary mode...", file=sys.stderr)
        return _run_single(archives[0], args)
    if len(archives) == 2:
        args.base, args.target = archives
        args.input_order = InputOrderInfo(
            mode="compare",
            source=discovery.ordering_source,
            auto_detected=True,
            origin="directory-scan",
            original_paths=archives,
            ordered_paths=archives,
            details=discovery.ordering_details,
        )
        print("Entering compare mode...", file=sys.stderr)
        return _run_compare(args)

    args.timeline = archives
    args.input_order = InputOrderInfo(
        mode="timeline",
        source=discovery.ordering_source,
        auto_detected=True,
        origin="directory-scan",
        original_paths=archives,
        ordered_paths=archives,
        details=discovery.ordering_details,
    )
    print("Entering timeline mode...", file=sys.stderr)
    return _run_timeline(args)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to compare or timeline mode."""
    parser = build_parser()
    args = parser.parse_args(argv)
    _infer_output_mode(args)

    try:
        mode = _resolve_mode(args)
        if mode == "compare":
            _prepare_compare_args(args)
            return _run_compare(args)
        if mode == "timeline":
            _prepare_timeline_args(args)
            return _run_timeline(args)
        if mode == "single-run":
            return _run_single(args.paths[0], args)
        if mode == "directory-scan":
            return _run_directory_scan(args)
        print("error: could not determine execution mode", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"unexpected error: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2
