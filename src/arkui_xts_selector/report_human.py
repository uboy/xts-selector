"""Human-readable report printing functions.

This module contains all functions for printing human-readable reports,
including the main print_human function and all its helper functions.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterable

# Lazy imports: rich is loaded only when a rendering function is called
# to avoid ImportError when the optional dependency is missing.
_rich_available = False
_rich_box = None
_RichConsole = None
_RichPadding = None
_RichTable = None


def _ensure_rich():
    global _rich_available, _rich_box, _RichConsole, _RichPadding, _RichTable
    if _rich_available:
        return
    try:
        from rich import box as _rich_box
        from rich.console import Console as _RichConsole
        from rich.padding import Padding as _RichPadding
        from rich.table import Table as _RichTable
        _rich_available = True
    except ImportError:
        _rich_available = False

from .daily_prebuilt import (
    daily_component_candidates,
    derive_date_from_tag,
    is_placeholder_metadata,
    list_daily_tags,
)
from .execution import collect_unique_run_targets
from .models import AppConfig
from .runtime_state import default_runtime_state_root
from .run_store import (
    COMPLETED_RUN_STATUSES,
    default_run_store_root,
    list_run_manifests,
    normalize_run_label,
)
from .scoring import split_scope_groups
from .tokens import compact_token

# Module-level constants (from cli.py)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMAND_PREFIX_ENV = "ARKUI_XTS_SELECTOR_COMMAND_PREFIX"
COMMAND_MODE_ENV = "ARKUI_XTS_SELECTOR_COMMAND_MODE"

# Import constants from ranking_rules for mutable global access

# Import constants from constants module
from .constants import (
    HUMAN_COMPACT_CHANGED_FILE_THRESHOLD,
    HUMAN_RUN_TARGET_DISPLAY_LIMIT,
    HUMAN_OPTIONAL_DUPLICATE_DISPLAY_LIMIT,
)


def _human_value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    parts = [part.strip() for part in text.splitlines() if part.strip()]
    if not parts:
        return "-"
    return " / ".join(parts)


def _human_join(values: Iterable[object]) -> str:
    rendered: list[str] = []
    for value in values:
        text = _human_value(value)
        if text == "-":
            continue
        rendered.append(text)
    return ", ".join(rendered) if rendered else "-"


def _human_preview(values: Iterable[object], limit: int = 8) -> str:
    items: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            items.append(text)
    if not items:
        return "-"
    if len(items) <= limit:
        return ", ".join(items)
    return f"{', '.join(items[:limit])}, ... (+{len(items) - limit})"


def _human_console() -> "_RichConsole":
    _ensure_rich()
    stream = sys.stdout
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    width = shutil.get_terminal_size((120, 40)).columns if is_tty else 120
    if _rich_available:
        return _RichConsole(
            file=stream,
            force_terminal=False,
            no_color=True,
            highlight=False,
            soft_wrap=False,
            width=width,
        )
    return None


def _add_table_column(table: "_RichTable", header: str) -> None:
    title = _human_value(header)
    compact = compact_token(title)
    kwargs: dict[str, object] = {"overflow": "fold", "vertical": "top"}
    if compact in {"#", "sel", "score", "rc"}:
        kwargs.update({"justify": "right", "no_wrap": True, "width": 3})
    elif compact in {
        "variant",
        "bucket",
        "confidence",
        "status",
        "tool",
        "device",
        "step",
        "priority",
    }:
        kwargs.update({"no_wrap": True, "max_width": 12})
    elif compact in {"key", "item", "type", "scope", "newcoverage", "totalcoverage"}:
        kwargs.update({"max_width": 16})
    elif compact in {"bundle", "available", "source"}:
        kwargs.update({"max_width": 20})
    elif compact in {"covers"}:
        kwargs.update({"max_width": 28})
    elif compact in {"target", "project", "testjson", "file", "match"}:
        kwargs.update({"max_width": 36})
    elif compact in {"command", "why", "details", "reasons"}:
        kwargs.update({"max_width": 56})
    table.add_column(title, **kwargs)


def _print_human_table(
    headers: list[str],
    rows: list[list[object]] | list[tuple[object, ...]],
    indent: int = 0,
) -> None:
    _ensure_rich()
    if not _rich_available:
        if not rows:
            return
        col_widths = [
            max(len(h), max((len(str(c)) for c in col), default=0))
            for h, col in zip(headers, zip(*rows))
        ]
        padding = " " * indent
        sep_fmt = padding + "  ".join(f"{{:<{w}}}" for w in col_widths)
        print(sep_fmt.format(*headers))
        print(padding + "  ".join("-" * w for w in col_widths))
        for row in rows:
            vals = [str(c) if c is not None else "-" for c in row]
            print(sep_fmt.format(*vals))
        return
    console = _human_console()
    table = _RichTable(
        box=_rich_box.ROUNDED,
        show_header=True,
        show_lines=False,
        expand=True,
        padding=(0, 1),
        pad_edge=True,
    )
    for header in headers:
        _add_table_column(table, _human_value(header))
    for row in rows:
        normalized_row = [_human_value(cell) for cell in row]
        table.add_row(*normalized_row)
    renderable = _RichPadding(table, (0, 0, 0, indent)) if indent else table
    console.print(renderable)


def _single_line_comment_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _print_actionable_command_list(title: str, items: list[dict[str, object]]) -> None:
    entries: list[tuple[str, str]] = []
    seen_commands: set[str] = set()
    for item in items:
        command = str(item.get("command") or "").strip()
        if not command or command == "-" or command in seen_commands:
            continue
        seen_commands.add(command)
        title_text = _single_line_comment_text(
            item.get("label") or item.get("step") or item.get("title")
        )
        status_text = _single_line_comment_text(item.get("status"))
        why_text = _single_line_comment_text(item.get("why"))
        details_text = _single_line_comment_text(item.get("details"))
        summary = title_text or "Command"
        if status_text and status_text != "-":
            summary = f"{summary} [{status_text}]"
        tail_parts = [part for part in (why_text, details_text) if part]
        if tail_parts:
            summary = f"{summary}. {' '.join(tail_parts)}"
        entries.append((summary, command))
    if not entries:
        return
    print(title)
    for index, (summary, command) in enumerate(entries, start=1):
        print(f"{index}. {summary}")
        print(command)
        print()


def _print_key_value_section(title: str, rows: list[tuple[object, object]]) -> None:
    filtered_rows = [(key, value) for key, value in rows if _human_value(value) != "-"]
    if not filtered_rows:
        return
    print(title)
    _print_human_table(["Key", "Value"], filtered_rows)
    print()


def _print_explanation_section(explanation: dict | None, indent: int = 2) -> None:
    """Print a human-readable WHY section from an explanation dict.

    Shows summary, evidence chain, limitations, and next actions.
    Skipped silently when explanation is None or empty.
    """
    if not explanation:
        return
    summary = str(explanation.get("summary") or "").strip()
    evidence_chain: list[str] = [
        str(s).strip()
        for s in (explanation.get("evidence_chain") or [])
        if str(s).strip()
    ]
    limitations: list[str] = [
        str(s).strip()
        for s in (explanation.get("limitations") or [])
        if str(s).strip()
    ]
    next_actions: list[str] = [
        str(s).strip()
        for s in (explanation.get("next_actions") or [])
        if str(s).strip()
    ]

    rows: list[tuple[object, object]] = []
    if summary:
        rows.append(("Why", summary))
    if evidence_chain:
        for i, step in enumerate(evidence_chain, start=1):
            rows.append((f"Step {i}", step))
    if limitations:
        for lim in limitations:
            rows.append(("Limitation", lim))
    if next_actions:
        for action in next_actions:
            rows.append(("Next Action", action))

    if not rows:
        return
    print(f"{' ' * indent}Evidence")
    _print_human_table(["Key", "Value"], rows)
    print()


def _format_case_summary(summary: dict | None) -> str:
    if not summary:
        return "-"
    parts = [
        f"total={summary.get('total_tests', 0)}",
        f"passed={summary.get('pass_count', 0)}",
        f"failed={summary.get('fail_count', 0)}",
        f"blocked={summary.get('blocked_count', 0)}",
        f"unknown={summary.get('unknown_count', 0)}",
    ]
    unavailable = int(summary.get("unavailable_count", 0) or 0)
    if unavailable:
        parts.append(f"unavailable={unavailable}")
    return ", ".join(parts)


def _tail_hint(result: dict) -> str:
    if result.get("stderr_tail"):
        return result["stderr_tail"].splitlines()[-1]
    if result.get("stdout_tail") and result.get("status") != "passed":
        return result["stdout_tail"].splitlines()[-1]
    return "-"


def _format_duration_seconds(value: object) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "-"
    if seconds <= 0:
        return "-"
    rounded = int(round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"~{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"~{minutes}m {secs:02d}s"
    return f"~{secs}s"


class _ProgressTracker:
    """Phase progress tracker with optional ETA estimation."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._phase_started = 0.0

    def start(self, phase_name: str, estimated_seconds: float | None = None) -> None:
        self._phase_started = time.perf_counter()
        if not self._enabled:
            return
        suffix = ""
        if estimated_seconds and estimated_seconds > 0:
            suffix = f" (est. {_format_duration_seconds(estimated_seconds)})"
        print(f"phase: {phase_name}{suffix}", file=sys.stderr, flush=True)

    def update(self, message: str, progress_percent: float | None = None) -> None:
        if not self._enabled:
            return
        elapsed = time.perf_counter() - self._phase_started
        pct_part = f" [{progress_percent:.0f}%]" if progress_percent is not None else ""
        eta_part = ""
        if progress_percent is not None and progress_percent > 0 and elapsed > 1.0:
            total_estimate = elapsed / (progress_percent / 100.0)
            remaining = max(0.0, total_estimate - elapsed)
            if remaining > 0:
                eta_part = f" ETA: {_format_duration_seconds(remaining)}"
        print(f"phase: {message}{pct_part}{eta_part}", file=sys.stderr, flush=True)

    def complete(self, phase_name: str) -> None:
        if not self._enabled:
            return
        elapsed = time.perf_counter() - self._phase_started
        print(
            f"phase: {phase_name} done ({_format_duration_seconds(elapsed)})",
            file=sys.stderr,
            flush=True,
        )


def _format_estimate_label(entry: dict[str, object]) -> str:
    base = _format_duration_seconds(entry.get("estimated_duration_s"))
    if base == "-":
        return "-"
    source = str(entry.get("estimate_source") or "")
    source_label = {
        "exact_target_tool": "observed",
        "exact_target_any_tool": "observed",
        "capability_tool": "capability",
        "family_tool": "family",
        "tool_default": "default",
    }.get(source, source or "estimated")
    return f"{base} ({source_label})"


def _shell_join(parts: Iterable[object]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts if str(part))


def _suite_label(entry: dict[str, object]) -> str:
    suite = _human_value(entry.get("build_target"))
    if suite != "-":
        return suite
    suite = _human_value(entry.get("xdevice_module_name"))
    if suite != "-":
        return suite
    project = str(entry.get("project") or "").strip()
    if project:
        return project.rstrip("/").rsplit("/", 1)[-1]
    return _human_value(entry.get("test_json"))


def _run_tool_purpose(tool: str) -> str:
    if tool == "aa_test":
        return "Direct device run via hdc and OpenHarmonyTestRunner."
    if tool == "xdevice":
        return "XDevice run with reports and logs written to -rp."
    if tool == "runtest":
        return "Standard ACTS runtest.sh workflow."
    return "-"


def _selector_command_prefix_tokens() -> list[str]:
    raw = str(os.environ.get(COMMAND_PREFIX_ENV) or "").strip()
    if raw:
        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = raw.split()
        if tokens:
            return tokens
    return ["arkui-xts-selector"]


def _uses_wrapper_commands() -> bool:
    mode = compact_token(os.environ.get(COMMAND_MODE_ENV, ""))
    if mode == "wrapper":
        return True
    tokens = [compact_token(token) for token in _selector_command_prefix_tokens()]
    return len(tokens) >= 2 and tokens[:2] == ["ohos", "xts"]


def _wrapper_or_direct_command_tokens(
    wrapper_subcommand: str | None = None,
) -> list[object]:
    tokens: list[object] = list(_selector_command_prefix_tokens())
    if _uses_wrapper_commands() and wrapper_subcommand:
        tokens.append(wrapper_subcommand)
    return tokens


def _wrapper_download_command_tokens(download_subcommand: str) -> list[object]:
    if not _uses_wrapper_commands():
        return list(_selector_command_prefix_tokens())
    tokens: list[object] = list(_selector_command_prefix_tokens())
    compact_tokens = [compact_token(token) for token in tokens]
    if compact_tokens:
        if compact_tokens[-1] == "xts":
            tokens[-1] = "download"
        elif compact_tokens[-1] != "download":
            tokens.append("download")
    else:
        tokens = ["ohos", "download"]
    tokens.append(download_subcommand)
    return tokens


def _wrapper_device_flash_command_tokens() -> list[object]:
    if not _uses_wrapper_commands():
        return list(_selector_command_prefix_tokens())
    tokens: list[object] = list(_selector_command_prefix_tokens())
    compact_tokens = [compact_token(token) for token in tokens]
    if compact_tokens:
        if compact_tokens[-1] == "xts":
            tokens[-1] = "device"
        elif compact_tokens[-1] != "device":
            tokens.append("device")
    else:
        tokens = ["ohos", "device"]
    tokens.append("flash")
    return tokens


def _showing_summary_text(
    relevance_summary: dict[str, object], shown_count: int
) -> str:
    shown = int(relevance_summary.get("shown", shown_count))
    total_after = int(relevance_summary.get("total_after", shown_count))
    total_before = int(relevance_summary.get("total_before", total_after))
    filtered_out = int(
        relevance_summary.get("filtered_out", max(total_before - total_after, 0))
    )
    if shown >= total_after:
        text = f"all {shown} matching tests"
    else:
        text = f"top {shown} of {total_after} matching tests"
    if filtered_out > 0:
        text = f"{text}; {filtered_out} were filtered out by relevance"
    if total_before > total_after:
        text = f"{text}; {total_before} were seen before filtering"
    if shown < total_after:
        return f"{text}. Increase --top-projects to see more."
    return text


def _daily_selector_arg(
    flag: str, build_tag: str | None, build_date: str | None
) -> list[str]:
    normalized_tag = str(build_tag or "").strip()
    normalized_date = str(build_date or "").strip() or derive_date_from_tag(
        normalized_tag
    )
    if normalized_tag:
        result = [flag, normalized_tag]
        if normalized_date:
            result.extend([flag.replace("build-tag", "date"), normalized_date])
        return result
    return [flag.replace("build-tag", "date"), normalized_date or "<YYYYMMDD>"]


@lru_cache(maxsize=32)
def _latest_daily_selector_metadata(
    component: str, branch: str, component_role: str
) -> tuple[str, str]:
    normalized_component = str(component or "").strip()
    normalized_branch = str(branch or "").strip() or "master"
    candidates = daily_component_candidates(
        normalized_component, component_role=component_role
    )
    newest_tag = ""
    newest_date = ""
    for candidate in candidates:
        try:
            builds = list_daily_tags(
                component=candidate, branch=normalized_branch, count=1
            )
        except Exception:
            continue
        if not builds:
            continue
        tag = str(builds[0].tag or "").strip()
        if tag and tag > newest_tag:
            newest_tag = tag
            newest_date = derive_date_from_tag(tag)
    return newest_tag, newest_date


def _daily_selector_hint_args(
    flag: str,
    *,
    build_tag: str | None,
    build_date: str | None,
    component: str,
    branch: str,
    component_role: str,
) -> list[str]:
    normalized_tag = (
        "" if is_placeholder_metadata(build_tag) else str(build_tag or "").strip()
    )
    normalized_date = (
        "" if is_placeholder_metadata(build_date) else str(build_date or "").strip()
    )
    if not normalized_tag and not normalized_date:
        normalized_tag, normalized_date = _latest_daily_selector_metadata(
            component, branch, component_role
        )
    return _daily_selector_arg(flag, normalized_tag or None, normalized_date or None)


def _cache_state_text(cache_used: bool, cache_file: object | None) -> str:
    state = "hit" if cache_used else "miss"
    if cache_file:
        return f"{state} ({cache_file})"
    return state


def _preparation_summary(report: dict) -> str:
    built = report.get("built_artifacts", {})
    daily_prebuilt = report.get("daily_prebuilt", {})
    has_acts = bool(built.get("testcases_dir_exists")) and bool(
        built.get("module_info_exists")
    )
    if has_acts or daily_prebuilt.get("acts_out_root"):
        return "ready"
    return "missing"


def _base_selector_run_command(
    report: dict, app_config: AppConfig, args: argparse.Namespace
) -> list[object]:
    if _uses_wrapper_commands():
        run_command: list[object] = _wrapper_or_direct_command_tokens("run")
    else:
        run_command = [
            *_wrapper_or_direct_command_tokens(),
            "--repo-root",
            app_config.repo_root,
        ]
    selector_report_path = str(
        report.get("selector_run", {}).get("selector_report_path", "")
    ).strip()
    if selector_report_path:
        run_command.extend(["--from-report", selector_report_path])
    else:
        for changed_file in getattr(args, "changed_file", []):
            run_command.extend(["--changed-file", changed_file])
        for changed_symbol in getattr(args, "changed_symbol", []):
            run_command.extend(["--changed-symbol", changed_symbol])
        for changed_range in getattr(args, "changed_range", []):
            run_command.extend(["--changed-range", changed_range])
        for symbol_query in getattr(args, "symbol_query", []):
            run_command.extend(["--symbol-query", symbol_query])
        for code_query in getattr(args, "code_query", []):
            run_command.extend(["--code-query", code_query])
        if getattr(args, "changed_files_from", None):
            run_command.extend(
                ["--changed-files-from", getattr(args, "changed_files_from")]
            )
        if getattr(args, "git_diff", None):
            run_command.extend(["--git-diff", getattr(args, "git_diff")])
        if getattr(args, "pr_url", None):
            run_command.extend(["--pr-url", getattr(args, "pr_url")])
        if getattr(args, "pr_number", None):
            run_command.extend(["--pr-number", getattr(args, "pr_number")])
        if getattr(args, "pr_source", "auto") != "auto":
            run_command.extend(["--pr-source", getattr(args, "pr_source")])
        if getattr(args, "git_host_kind", "auto") != "auto":
            run_command.extend(["--git-host-kind", getattr(args, "git_host_kind")])
        if getattr(args, "git_host_config", None):
            run_command.extend(["--git-host-config", getattr(args, "git_host_config")])
        if getattr(args, "git_host_url", None):
            run_command.extend(["--git-host-url", getattr(args, "git_host_url")])
        if getattr(args, "gitcode_api_url", None):
            run_command.extend(["--gitcode-api-url", getattr(args, "gitcode_api_url")])
        run_command.extend(
            [
                "--variants",
                getattr(args, "variants", "auto"),
                "--relevance-mode",
                getattr(args, "relevance_mode", "all"),
            ]
        )
        if getattr(args, "top_projects", 0) > 0:
            run_command.extend(["--top-projects", getattr(args, "top_projects")])
        if getattr(args, "keep_per_signature", 0):
            run_command.extend(
                ["--keep-per-signature", getattr(args, "keep_per_signature")]
            )
    if (
        app_config.runtime_state_root
        and app_config.runtime_state_root != default_runtime_state_root()
    ):
        run_command.extend(["--runtime-state-root", app_config.runtime_state_root])
    if app_config.server_host:
        run_command.extend(["--server-host", app_config.server_host])
    if app_config.server_user:
        run_command.extend(["--server-user", app_config.server_user])
    if app_config.hdc_path and not _uses_wrapper_commands():
        run_command.extend(["--hdc-path", app_config.hdc_path])
    if app_config.hdc_endpoint:
        run_command.extend(["--hdc-endpoint", app_config.hdc_endpoint])
    if float(app_config.device_lock_timeout or 0.0) != 30.0:
        run_command.extend(["--device-lock-timeout", app_config.device_lock_timeout])
    if app_config.devices:
        run_command.extend(["--devices", ",".join(app_config.devices)])
    for test_name in getattr(args, "run_test_name", []) or []:
        run_command.extend(["--run-test-name", test_name])
    run_test_names_file = getattr(args, "run_test_names_file", None)
    if run_test_names_file:
        run_command.extend(["--run-test-names-file", run_test_names_file])
    if getattr(args, "show_source_evidence", False):
        run_command.append("--show-source-evidence")
    return run_command


def _repeat_this_run_command_tokens(
    report: dict, app_config: AppConfig, args: argparse.Namespace
) -> list[object]:
    """Shell tokens to replay the current run: same report, devices, HDC, and run flags."""
    command = list(_base_selector_run_command(report, app_config, args))
    if not _uses_wrapper_commands():
        command.append("--run-now")
    command.extend(["--run-tool", str(getattr(args, "run_tool", "auto") or "auto")])
    command.extend(
        [
            "--run-priority",
            str(getattr(args, "run_priority", "recommended") or "recommended"),
        ]
    )
    rtp = int(getattr(args, "run_top_targets", 0) or 0)
    if rtp > 0:
        command.extend(["--run-top-targets", str(rtp)])
    pj = int(getattr(args, "parallel_jobs", 1) or 1)
    if pj > 1:
        command.extend(["--parallel-jobs", str(pj)])
    shard = str(getattr(app_config, "shard_mode", None) or "mirror")
    if shard and shard != "mirror":
        command.extend(["--shard-mode", shard])
    rto = float(getattr(args, "run_timeout", 0.0) or 0.0)
    if rto > 0:
        command.extend(["--run-timeout", str(rto)])
    dlt = float(getattr(app_config, "device_lock_timeout", 30.0) or 30.0)
    if dlt != 30.0:
        command.extend(["--device-lock-timeout", str(dlt)])
    run_label = (
        str(getattr(args, "run_label", None) or "").strip()
        or str(getattr(app_config, "run_label", None) or "").strip()
    )
    if run_label:
        command.extend(["--run-label", run_label])
    return command


def _run_priority_target_count(coverage: dict[str, object], priority: str) -> int:
    required_count = len(coverage.get("required_target_keys", []))
    recommended_count = len(coverage.get("recommended_target_keys", []))
    optional_count = len(coverage.get("optional_target_keys", []))
    if priority == "required":
        return required_count
    if priority == "recommended":
        return recommended_count
    return recommended_count + optional_count


def _build_compare_command(
    base_label: str, target_label: str, run_store_root: Path | None
) -> str:
    if _uses_wrapper_commands():
        return _shell_join(
            [*_wrapper_or_direct_command_tokens("compare"), base_label, target_label]
        )
    resolved_run_store = (
        run_store_root or default_run_store_root(PROJECT_ROOT)
    ).resolve()
    return _shell_join(
        [
            "python3",
            "-m",
            "arkui_xts_selector.xts_compare",
            "--base-label",
            base_label,
            "--target-label",
            target_label,
            "--label-root",
            str(resolved_run_store),
        ]
    )


def _find_compare_base_label(
    run_store_root: Path | None, current_label: str | None
) -> str | None:
    current = str(current_label or "").strip()
    if not current:
        return None
    current_key = normalize_run_label(current)
    root = (run_store_root or default_run_store_root(PROJECT_ROOT)).resolve()
    candidates: dict[str, dict[str, str]] = {}
    for manifest in list_run_manifests(root):
        label = str(manifest.get("label") or "").strip()
        label_key = str(manifest.get("label_key") or normalize_run_label(label))
        if not label or label_key == current_key:
            continue
        if str(manifest.get("status") or "") not in COMPLETED_RUN_STATUSES:
            continue
        comparable_paths = [
            str(Path(path).expanduser().resolve())
            for path in manifest.get("comparable_result_paths", [])
            if str(path).strip() and Path(path).expanduser().exists()
        ]
        if not comparable_paths:
            continue
        candidate = {
            "label": label,
            "label_key": label_key,
            "timestamp": str(manifest.get("timestamp", "")),
        }
        previous = candidates.get(label_key)
        if previous is None or candidate["timestamp"] > previous["timestamp"]:
            candidates[label_key] = candidate
    if not candidates:
        return None
    if "baseline" in candidates:
        return candidates["baseline"]["label"]
    if len(candidates) == 1:
        return next(iter(candidates.values()))["label"]
    return None


def build_coverage_run_commands(
    report: dict, app_config: AppConfig, args: argparse.Namespace
) -> list[dict[str, str]]:
    coverage = report.get("coverage_recommendations", {})
    commands: list[dict[str, str]] = []
    for priority, label, why in (
        ("required", "Run required batch", "Only strongest unique coverage."),
        (
            "recommended",
            "Run recommended batch",
            "Strong plus additional unique coverage.",
        ),
        ("all", "Run full batch", "Includes duplicate fallback coverage."),
    ):
        target_count = _run_priority_target_count(coverage, priority)
        command = _base_selector_run_command(report, app_config, args)
        if not _uses_wrapper_commands():
            command.append("--run-now")
        if getattr(args, "run_tool", "auto") != "auto":
            command.extend(["--run-tool", getattr(args, "run_tool", "auto")])
        command.extend(["--run-priority", priority])
        if target_count > 0:
            command.extend(["--run-top-targets", target_count])
        if getattr(args, "parallel_jobs", 1) > 1:
            command.extend(["--parallel-jobs", getattr(args, "parallel_jobs", 1)])
        if getattr(app_config, "shard_mode", "mirror") != "mirror":
            command.extend(
                ["--shard-mode", getattr(app_config, "shard_mode", "mirror")]
            )
        if getattr(args, "run_timeout", 0.0) > 0:
            command.extend(["--run-timeout", getattr(args, "run_timeout", 0.0)])
        if priority == "required":
            estimated_duration_s = coverage.get("estimated_required_duration_s", 0.0)
        elif priority == "recommended":
            estimated_duration_s = coverage.get("estimated_recommended_duration_s", 0.0)
        else:
            estimated_duration_s = coverage.get("estimated_all_duration_s", 0.0)
        commands.append(
            {
                "label": label,
                "priority": priority,
                "count": str(target_count),
                "why": why,
                "estimated_duration": _format_duration_seconds(estimated_duration_s),
                "command": _shell_join(command),
            }
        )
    return commands


def build_next_steps(
    report: dict, app_config: AppConfig, args: argparse.Namespace
) -> list[dict[str, str]]:
    sdk_root_value = str(report.get("sdk_api_root") or "").strip()
    sdk_root_exists = bool(sdk_root_value) and Path(sdk_root_value).exists()
    run_only_flow = bool(
        getattr(args, "from_report", None) or getattr(args, "last_report", False)
    )
    built_artifacts = report.get("built_artifacts", {})
    has_acts_artifacts = bool(built_artifacts.get("testcases_dir_exists")) and bool(
        built_artifacts.get("module_info_exists")
    )
    daily_prebuilt_ready = bool(getattr(app_config, "daily_prebuilt_ready", False))
    coverage = report.get("coverage_recommendations", {})
    selector_run = (
        report.get("selector_run", {})
        if isinstance(report.get("selector_run"), dict)
        else {}
    )
    current_run_label = str(
        selector_run.get("label") or app_config.run_label or ""
    ).strip()
    required_target_count = len(coverage.get("required_target_keys", []))
    recommended_target_count = len(coverage.get("recommended_target_keys", []))
    selected_targets = int(
        report.get("execution_overview", {}).get("selected_target_count", 0)
    )
    run_blocked = recommended_target_count <= 0 or (
        not has_acts_artifacts and not daily_prebuilt_ready
    )
    run_block_reason = (
        "No runnable targets were selected."
        if recommended_target_count <= 0
        else "ACTS artifacts are missing; download tests or prepare build artifacts first."
    )

    repeat_tokens = _repeat_this_run_command_tokens(report, app_config, args)
    report["repeat_run_command"] = _shell_join(repeat_tokens)

    steps: list[dict[str, str]] = []
    steps.append(
        {
            "step": "Repeat this run",
            "status": "ready",
            "why": "Re-execute with the same report path, devices, HDC settings, and run flags as this invocation.",
            "command": report["repeat_run_command"],
        }
    )
    if not run_only_flow:
        steps.append(
            {
                "step": "Switch SDK For Selection"
                if sdk_root_exists
                else "Download SDK For Selection",
                "status": "optional",
                "why": (
                    "Optional: use this only to rescore the selector against another SDK build. It is not required to run selected tests."
                    if sdk_root_exists
                    else "Optional: adding an SDK can improve selector matching for ArkUI API symbols, but it is not required to execute selected tests."
                ),
                "command": _shell_join(
                    [
                        *(
                            _wrapper_download_command_tokens("sdk")
                            if _uses_wrapper_commands()
                            else _wrapper_or_direct_command_tokens(None)
                        ),
                        *([] if _uses_wrapper_commands() else ["--download-daily-sdk"]),
                        "--sdk-component",
                        app_config.sdk_component,
                        "--sdk-branch",
                        app_config.sdk_branch,
                        *_daily_selector_hint_args(
                            "--sdk-build-tag",
                            build_tag=app_config.sdk_build_tag,
                            build_date=app_config.sdk_date,
                            component=app_config.sdk_component,
                            branch=app_config.sdk_branch,
                            component_role="generic",
                        ),
                    ]
                ),
            }
        )
    steps.append(
        {
            "step": "Download tests",
            "status": "recommended"
            if not has_acts_artifacts and not daily_prebuilt_ready
            else "optional",
            "why": (
                "ACTS artifacts are missing."
                if not has_acts_artifacts and not daily_prebuilt_ready
                else "Use this to switch to another prebuilt test package."
            ),
            "command": _shell_join(
                [
                    *(
                        _wrapper_download_command_tokens("tests")
                        if _uses_wrapper_commands()
                        else _wrapper_or_direct_command_tokens(None)
                    ),
                    *([] if _uses_wrapper_commands() else ["--download-daily-tests"]),
                    "--daily-component",
                    app_config.daily_component,
                    "--daily-branch",
                    app_config.daily_branch,
                    *_daily_selector_hint_args(
                        "--daily-build-tag",
                        build_tag=app_config.daily_build_tag,
                        build_date=app_config.daily_date,
                        component=app_config.daily_component,
                        branch=app_config.daily_branch,
                        component_role="xts",
                    ),
                ]
            ),
        }
    )
    steps.append(
        {
            "step": "Download firmware",
            "status": "optional",
            "why": "Use this when you need a matching daily firmware image package.",
            "command": _shell_join(
                [
                    *(
                        _wrapper_download_command_tokens("firmware")
                        if _uses_wrapper_commands()
                        else _wrapper_or_direct_command_tokens(None)
                    ),
                    *(
                        []
                        if _uses_wrapper_commands()
                        else ["--download-daily-firmware"]
                    ),
                    "--firmware-component",
                    app_config.firmware_component,
                    "--firmware-branch",
                    app_config.firmware_branch,
                    *_daily_selector_hint_args(
                        "--firmware-build-tag",
                        build_tag=app_config.firmware_build_tag,
                        build_date=app_config.firmware_date,
                        component=app_config.firmware_component,
                        branch=app_config.firmware_branch,
                        component_role="generic",
                    ),
                ]
            ),
        }
    )
    steps.append(
        {
            "step": "Flash daily firmware",
            "status": "optional",
            "why": "Download and flash a daily firmware package to the connected device.",
            "command": _shell_join(
                [
                    *(
                        _wrapper_device_flash_command_tokens()
                        if _uses_wrapper_commands()
                        else _wrapper_or_direct_command_tokens(None)
                    ),
                    *([] if _uses_wrapper_commands() else ["--flash-daily-firmware"]),
                    "--firmware-component",
                    app_config.firmware_component,
                    "--firmware-branch",
                    app_config.firmware_branch,
                    *_daily_selector_hint_args(
                        "--firmware-build-tag",
                        build_tag=app_config.firmware_build_tag,
                        build_date=app_config.firmware_date,
                        component=app_config.firmware_component,
                        branch=app_config.firmware_branch,
                        component_role="generic",
                    ),
                    *(["--device", app_config.device] if app_config.device else []),
                ]
            ),
        }
    )
    steps.append(
        {
            "step": "Flash local firmware",
            "status": "ready" if app_config.flash_firmware_path else "optional",
            "why": (
                "A local firmware path is already configured."
                if app_config.flash_firmware_path
                else "Flash your own unpacked image bundle from a local path for validating custom changes."
            ),
            "command": _shell_join(
                [
                    *_wrapper_or_direct_command_tokens(),
                    "--flash-firmware-path",
                    app_config.flash_firmware_path or "<image_bundle_root>",
                    *(["--device", app_config.device] if app_config.device else []),
                ]
            ),
        }
    )

    for priority, label, count, why in (
        (
            "required",
            "Run required tests",
            required_target_count,
            f"{required_target_count} strongest unique target(s) are ready to run.",
        ),
        (
            "recommended",
            "Run recommended tests",
            recommended_target_count,
            f"{recommended_target_count} unique target(s) are ready to run.",
        ),
        (
            "all",
            "Run all coverage",
            _run_priority_target_count(coverage, "all"),
            f"{_run_priority_target_count(coverage, 'all')} total target(s), including duplicates, are ready to run.",
        ),
    ):
        command = _base_selector_run_command(report, app_config, args)
        if not _uses_wrapper_commands():
            command.append("--run-now")
        if getattr(args, "run_tool", "auto") != "auto":
            command.extend(["--run-tool", getattr(args, "run_tool", "auto")])
        command.extend(["--run-priority", priority])
        if count > 0:
            command.extend(["--run-top-targets", count])
        if getattr(args, "parallel_jobs", 1) > 1:
            command.extend(["--parallel-jobs", getattr(args, "parallel_jobs", 1)])
        if getattr(app_config, "shard_mode", "mirror") != "mirror":
            command.extend(
                ["--shard-mode", getattr(app_config, "shard_mode", "mirror")]
            )
        if getattr(args, "run_timeout", 0.0) > 0:
            command.extend(["--run-timeout", getattr(args, "run_timeout", 0.0)])
        steps.append(
            {
                "step": label,
                "status": "blocked" if run_blocked or count <= 0 else "ready",
                "why": run_block_reason
                if run_blocked
                else (
                    why if count > 0 else "No targets available in this priority tier."
                ),
                "command": _shell_join(command),
            }
        )
    compare_base_label = _find_compare_base_label(
        app_config.run_store_root, current_run_label
    )
    recommended_run_command = ""
    if compare_base_label:
        recommended_run_command = ""
        for step in steps:
            if step.get("step") == "Run recommended tests":
                recommended_run_command = str(step.get("command") or "")
                break
        if recommended_run_command and not run_blocked and recommended_target_count > 0:
            steps.append(
                {
                    "step": "Run recommended tests + compare",
                    "status": "recommended",
                    "why": f"Runs the recommended batch and then compares the result against the saved base run '{compare_base_label}'.",
                    "command": f"{recommended_run_command} && {_build_compare_command(compare_base_label, current_run_label, app_config.run_store_root)}",
                }
            )
        steps.append(
            {
                "step": "Compare with base run",
                "status": "follow-up",
                "why": f"Use this after the run finishes to compare the new results against the saved base run '{compare_base_label}'.",
                "command": _build_compare_command(
                    compare_base_label, current_run_label, app_config.run_store_root
                ),
            }
        )
    return steps


def print_executive_summary(report: dict, json_report_path: Path | None = None) -> None:
    """Print a compact summary before the detailed report."""
    coverage = report.get("coverage_recommendations", {})
    results = list(report.get("results", []))
    changed_file_count = sum(
        1
        for result in results
        if str(
            (result.get("source_profile") or result.get("source") or {}).get("type", "")
        )
        == "changed_file"
    )

    seen_families: set[str] = set()
    affected_families: list[str] = []
    for result in results:
        source_profile = result.get("source_profile") or result.get("source") or {}
        for family_key in list(source_profile.get("family_keys", []))[:3]:
            token = str(family_key).split("/")[-1]
            if not token or token in seen_families:
                continue
            seen_families.add(token)
            affected_families.append(token.replace("_", " ").title())
            if len(affected_families) >= 8:
                break

    required_targets = list(coverage.get("required", []))
    recommended_targets = list(coverage.get("recommended_additional", []))
    optional_targets = list(coverage.get("optional_duplicates", []))
    est_required = _format_duration_seconds(
        coverage.get("estimated_required_duration_s")
    )
    est_recommended = _format_duration_seconds(
        coverage.get("estimated_recommended_duration_s")
    )
    est_all = _format_duration_seconds(coverage.get("estimated_all_duration_s"))
    coverage_commands = list(report.get("coverage_run_commands", []))
    selected_tests_path = str(report.get("selected_tests_json_path", "")).strip()
    repeat_run_command = str(report.get("repeat_run_command", "")).strip()

    separator = "═" * 63
    thin_separator = "─" * 63

    print()
    print(separator)
    print(" EXECUTIVE SUMMARY")
    print(separator)
    print()

    info_lines: list[str] = []
    if changed_file_count:
        suffix = "s" if changed_file_count != 1 else ""
        info_lines.append(f"Changed: {changed_file_count} file{suffix} analyzed")
    if affected_families:
        families = ", ".join(affected_families[:5])
        if len(affected_families) > 5:
            families += f", +{len(affected_families) - 5} more"
        info_lines.append(f"APIs Affected: {families}")
    for line in info_lines:
        print(line)
    if info_lines:
        print()

    total_suites = (
        len(required_targets) + len(recommended_targets) + len(optional_targets)
    )
    if total_suites > 0:
        total_duration = (
            est_all
            if est_all != "-"
            else (est_recommended if est_recommended != "-" else "-")
        )
        duration_note = f", {total_duration} estimated" if total_duration != "-" else ""
        suite_suffix = "s" if total_suites != 1 else ""
        print(f"TESTS TO RUN ({total_suites} suite{suite_suffix}{duration_note})")
        print(thin_separator)
        print(f" {'Priority':<10}  {'Suites':>6}  {'Est. Time':>10}")
        print(f" {'─' * 10}  {'─' * 6}  {'─' * 10}")
        if required_targets:
            print(f" {'MUST RUN':<10}  {len(required_targets):>6}  {est_required:>10}")
        if recommended_targets:
            high_duration = (
                est_recommended
                if est_recommended != "-" and not required_targets
                else "-"
            )
            print(f" {'HIGH':<10}  {len(recommended_targets):>6}  {high_duration:>10}")
        if optional_targets:
            print(f" {'OPTIONAL':<10}  {len(optional_targets):>6}  {'':>10}")
        print()

    if coverage_commands:
        print("RUN COMMANDS:")
        for command_entry in coverage_commands[:3]:
            label = str(command_entry.get("label", "")).strip()
            command = str(command_entry.get("command", "")).strip()
            count = str(command_entry.get("count", "")).strip()
            if not label or not command:
                continue
            count_note = f" ({count} suites)" if count and count != "0" else ""
            print(f"  {label + count_note:<40}  {command}")
    elif repeat_run_command:
        print("RUN COMMANDS:")
        print(f"  Repeat this run:                          {repeat_run_command}")

    if selected_tests_path:
        print(f"  Full JSON:                                cat {selected_tests_path}")
    elif json_report_path is not None:
        print(f"  Full JSON:                                cat {json_report_path}")

    print()
    print(separator)
    print()


def print_human(
    report: dict, cache_used: bool | None = None, json_report_path: Path | None = None
) -> None:
    selected_tests_json_path = str(report.get("selected_tests_json_path", "")).strip()
    unique_run_targets = collect_unique_run_targets(report)
    selected_target_count = len(
        report.get("execution_overview", {}).get("selected_target_keys", [])
    )
    compact_changed_file_sections = (
        len(report.get("results", [])) >= HUMAN_COMPACT_CHANGED_FILE_THRESHOLD
    )

    def _selected_run_target_groups() -> list[dict]:
        selected_keys = {
            str(item).strip()
            for item in report.get("execution_overview", {}).get(
                "selected_target_keys", []
            )
            if str(item).strip()
        }
        if not selected_keys:
            return list(unique_run_targets)
        filtered = [
            group
            for group in unique_run_targets
            if str(group.get("key") or "").strip() in selected_keys
        ]
        return filtered or list(unique_run_targets)

    def _run_target_has_inventory(group: dict[str, object]) -> bool:
        candidates = list(group.get("targets", []))
        representative = group.get("representative", {})
        if representative:
            candidates.append(representative)
        for target in candidates:
            if str(target.get("artifact_status") or "").strip() != "missing":
                return True
        return False

    def _print_run_only_human() -> None:
        selected_groups = _selected_run_target_groups()
        summary_rows: list[tuple[object, object]] = [
            ("Workspace", report.get("repo_root")),
            ("ACTS Out", report.get("acts_out_root")),
            ("Selected", len(selected_groups)),
        ]
        selector_run = report.get("selector_run") or {}
        if selector_run:
            summary_rows.extend(
                [
                    ("Run Label", selector_run.get("label", "-")),
                    ("Run Dir", selector_run.get("run_dir", "-")),
                ]
            )
        if json_report_path is not None:
            summary_rows.append(("Report JSON", json_report_path))
        if selected_tests_json_path:
            summary_rows.append(("Selected Tests JSON", selected_tests_json_path))
        if report.get("execution_artifact_index_path"):
            summary_rows.append(
                ("Execution Artifact Index", report["execution_artifact_index_path"])
            )
        if report.get("execution_xdevice_reports_root"):
            summary_rows.append(
                ("XDevice Reports Root", report["execution_xdevice_reports_root"])
            )
        requested_names = list(
            report.get("execution_overview", {}).get("requested_test_names", [])
        )
        if requested_names:
            summary_rows.append(("Requested Names", _human_join(requested_names)))
        if report.get("requested_devices"):
            summary_rows.append(("Devices", _human_join(report["requested_devices"])))
        if report.get("execution_server_host"):
            summary_rows.append(("Execution Host", report["execution_server_host"]))
        if report.get("execution_server_user"):
            summary_rows.append(("Execution User", report["execution_server_user"]))
        if report.get("daily_prebuilt", {}).get("note"):
            summary_rows.append(("Daily Note", report["daily_prebuilt"]["note"]))
        _print_key_value_section("Run Summary", summary_rows)

        if selected_groups:
            print("Selected Tests")
            test_rows: list[list[object]] = []
            display_limit = (
                HUMAN_RUN_TARGET_DISPLAY_LIMIT
                if len(selected_groups) > HUMAN_RUN_TARGET_DISPLAY_LIMIT
                else None
            )
            display_groups = (
                selected_groups[:display_limit] if display_limit else selected_groups
            )
            for index, group in enumerate(display_groups, start=1):
                target = group.get("representative", {})
                first_plan = (target.get("execution_plan") or [{}])[0]
                first_result = (target.get("execution_results") or [{}])[0]
                test_rows.append(
                    [
                        index,
                        _suite_label(target),
                        target.get("artifact_status", "-"),
                        first_result.get("selected_tool")
                        or first_plan.get("selected_tool")
                        or "-",
                        first_result.get("device_label")
                        or first_plan.get("device_label")
                        or "-",
                        first_result.get("status")
                        or first_plan.get("status")
                        or (
                            "selected"
                            if target.get("selected_for_execution")
                            else "pending"
                        ),
                    ]
                )
            _print_human_table(
                ["#", "Suite", "Artifacts", "Tool", "Device", "Status"],
                test_rows,
                indent=2,
            )
            print()
            if display_limit and len(selected_groups) > display_limit:
                note_rows: list[tuple[object, object]] = [
                    ("Visible", f"{display_limit} of {len(selected_groups)}"),
                    (
                        "Note",
                        "Full selected suite list remains in selected_tests.json.",
                    ),
                ]
                if selected_tests_json_path:
                    note_rows.append(("JSON", selected_tests_json_path))
                _print_key_value_section("Selected Tests Note", note_rows)

        execution_rows: list[tuple[object, object]] = []
        if report.get("execution_overview"):
            overview = report["execution_overview"]
            execution_rows.append(
                (
                    "execution_overview",
                    (
                        f"tool={overview.get('run_tool', '-')}, "
                        f"run_priority={overview.get('run_priority', 'recommended')}, "
                        f"parallel_jobs={overview.get('parallel_jobs', 1)}, "
                        f"selected_targets={overview.get('selected_target_count', 0)}, "
                        f"executed={_human_value(overview.get('executed'))}"
                    ),
                )
            )
        if report.get("execution_preflight"):
            preflight = report["execution_preflight"]
            execution_rows.append(
                (
                    "execution_preflight",
                    (
                        f"status={preflight.get('status', '-')}, "
                        f"plans={preflight.get('plan_count', 0)}, "
                        f"tools={_human_join(preflight.get('selected_tools', []))}, "
                        f"connected_devices={_human_join(preflight.get('connected_devices', []))}"
                    ),
                )
            )
            if preflight.get("errors"):
                execution_rows.append(
                    (
                        "preflight_errors",
                        _human_preview(preflight.get("errors", [])[:5], limit=5),
                    )
                )
            if preflight.get("warnings"):
                execution_rows.append(
                    (
                        "preflight_warnings",
                        _human_preview(preflight.get("warnings", [])[:5], limit=5),
                    )
                )
        if report.get("execution_summary"):
            summary = report["execution_summary"]
            execution_rows.append(
                (
                    "execution_summary",
                    (
                        f"planned={summary.get('planned_run_count', 0)}, "
                        f"passed={summary.get('passed', 0)}, "
                        f"failed={summary.get('failed', 0)}, "
                        f"blocked={summary.get('blocked', 0)}, "
                        f"timeout={summary.get('timeout', 0)}, "
                        f"unavailable={summary.get('unavailable', 0)}, "
                        f"skipped={summary.get('skipped', 0)}, "
                        f"interrupted={_human_value(summary.get('interrupted'))}"
                    ),
                )
            )
        if report.get("runtime_history_update"):
            history_update = report["runtime_history_update"]
            execution_rows.append(
                (
                    "runtime_history",
                    (
                        f"file={history_update.get('history_file', '-')}, "
                        f"updated_targets={history_update.get('updated_targets', 0)}, "
                        f"updated_samples={history_update.get('updated_samples', 0)}, "
                        f"significant_updates={history_update.get('significant_updates', 0)}"
                    ),
                )
            )
        if execution_rows:
            _print_key_value_section("Execution", execution_rows)

        result_rows: list[list[object]] = []
        plan_rows: list[list[object]] = []
        for index, group in enumerate(selected_groups, start=1):
            target = group.get("representative", {})
            for plan in target.get("execution_plan", []):
                plan_rows.append(
                    [
                        index,
                        _suite_label(target),
                        plan.get("device_label", "-"),
                        plan.get("status", "-"),
                        plan.get("selected_tool") or "-",
                        plan.get("reason") or "-",
                    ]
                )
            for result in target.get("execution_results", []):
                result_rows.append(
                    [
                        index,
                        _suite_label(target),
                        result.get("device_label", "-"),
                        result.get("status", "-"),
                        result.get("selected_tool") or "-",
                        _format_duration_seconds(result.get("duration_s")),
                        "-"
                        if result.get("returncode") is None
                        else result.get("returncode"),
                        _format_case_summary(result.get("case_summary")),
                        result.get("result_path") or "-",
                    ]
                )
        if result_rows:
            print("Execution Results")
            _print_human_table(
                [
                    "#",
                    "Suite",
                    "Device",
                    "Status",
                    "Tool",
                    "Duration",
                    "RC",
                    "Case Summary",
                    "Result Path",
                ],
                result_rows,
                indent=2,
            )
            print()
        if plan_rows and (not result_rows or report.get("execution_interrupted")):
            print(
                "Execution Plan"
                if not report.get("execution_interrupted")
                else "Remaining Execution Plan"
            )
            _print_human_table(
                ["#", "Suite", "Device", "Status", "Tool", "Reason"],
                plan_rows,
                indent=2,
            )
            print()

        next_steps = list(report.get("next_steps") or [])
        if next_steps:
            status_rank = {
                "recommended": 0,
                "ready": 1,
                "follow-up": 2,
                "optional": 3,
                "blocked": 4,
            }

            def _next_step_sort_key(item: dict[str, object]) -> tuple[object, ...]:
                step = str(item.get("step", ""))
                prefix = 0 if step == "Repeat this run" else 1
                return (prefix, status_rank.get(str(item.get("status", "")), 99), step)

            ordered_next_steps = sorted(next_steps, key=_next_step_sort_key)
            _print_actionable_command_list("Next Steps", ordered_next_steps)

    if str(report.get("human_mode", "")).strip() == "run_only":
        _print_run_only_human()
        return

    def print_coverage_recommendations(recommendations: dict[str, object]) -> None:
        ordered_targets = list(recommendations.get("ordered_targets", []))
        required_targets = list(recommendations.get("required", []))
        recommended_targets = list(recommendations.get("recommended", []))
        recommended_additional_targets = list(
            recommendations.get("recommended_additional", [])
        )
        optional_targets = list(recommendations.get("optional_duplicates", []))
        source_count = int(recommendations.get("source_count", 0) or 0)
        candidate_count = int(recommendations.get("candidate_count", 0) or 0)
        if (
            not ordered_targets
            and not recommended_targets
            and not optional_targets
            and source_count <= 0
            and candidate_count <= 0
        ):
            return

        def _coverage_label_items(
            target: dict[str, object], primary_only: bool
        ) -> list[str]:
            capabilities = list(
                target.get(
                    "new_capabilities" if primary_only else "covered_capabilities", []
                )
            )
            if capabilities:
                return [str(item) for item in capabilities if str(item).strip()]
            families = list(
                target.get("new_families" if primary_only else "covered_families", [])
            )
            if families:
                return [str(item) for item in families if str(item).strip()]
            sources = target.get(
                "new_sources" if primary_only else "covered_sources", []
            )
            return [
                f"{item.get('type')}={item.get('value')}"
                for item in sources
                if str(item.get("value") or "").strip()
            ]

        coverage_rows: list[tuple[object, object]] = [
            ("Changed Areas", source_count),
            ("Candidate Suites", candidate_count),
            ("Required", len(required_targets)),
            ("Recommended", len(recommended_additional_targets)),
            ("Optional Duplicates", len(optional_targets)),
            (
                "Est. Required",
                _format_duration_seconds(
                    recommendations.get("estimated_required_duration_s")
                ),
            ),
            (
                "Est. Recommended",
                _format_duration_seconds(
                    recommendations.get("estimated_recommended_duration_s")
                ),
            ),
            (
                "Est. Full",
                _format_duration_seconds(
                    recommendations.get("estimated_all_duration_s")
                ),
            ),
        ]
        uncovered_sources = recommendations.get("uncovered_sources", [])
        unavailable_targets = list(recommendations.get("unavailable_targets", []))
        if uncovered_sources:
            coverage_rows.append(
                (
                    "Uncovered",
                    _human_preview(
                        [
                            f"{item.get('type')}={item.get('value')}"
                            for item in uncovered_sources
                        ],
                        limit=6,
                    ),
                )
            )
        if unavailable_targets:
            coverage_rows.append(("Unavailable In Artifacts", len(unavailable_targets)))
        _print_key_value_section("Coverage Recommendations", coverage_rows)
        batch_run_commands = list(report.get("coverage_run_commands", []))
        if batch_run_commands:
            _print_actionable_command_list(
                "Batch Run Commands",
                [
                    {
                        "label": item.get("label", "-"),
                        "why": item.get("why", "-"),
                        "details": f"Targets: {item.get('count', '-')}. Est.: {item.get('estimated_duration', '-')}.",
                        "command": item.get("command", "-"),
                    }
                    for item in batch_run_commands
                ],
            )

        def _print_coverage_group(
            title: str,
            targets: list[dict[str, object]],
            *,
            display_limit: int | None = None,
            overflow_note: str | None = None,
        ) -> None:
            if not targets:
                return
            print(title)
            rows: list[list[object]] = []
            display_targets = (
                targets[:display_limit]
                if display_limit and display_limit > 0
                else targets
            )
            for index, target in enumerate(display_targets, start=1):
                rows.append(
                    [
                        index,
                        _suite_label(target),
                        target.get("new_coverage_count", 0),
                        target.get("total_coverage_count", 0),
                        target.get("scope_tier", "-"),
                        target.get("variant") or target.get("surface") or "-",
                        target.get("bucket", "-"),
                        _format_estimate_label(target),
                        _human_preview(
                            _coverage_label_items(target, primary_only=True), limit=4
                        ),
                        target.get("coverage_reason", "-"),
                    ]
                )
            _print_human_table(
                [
                    "#",
                    "Suite",
                    "New Coverage",
                    "Total Coverage",
                    "Scope",
                    "Surface",
                    "Priority",
                    "Est.",
                    "Covers",
                    "Why First",
                ],
                rows,
                indent=2,
            )
            if display_limit and len(targets) > display_limit:
                note = overflow_note or (
                    f"showing first {display_limit} of {len(targets)} entries; full list remains in JSON output"
                )
                _print_key_value_section(
                    f"{title} Note",
                    [
                        ("Visible", f"{display_limit} of {len(targets)}"),
                        ("Note", note),
                    ],
                )
            print()

        _print_coverage_group("Required Run Order", required_targets)
        _print_coverage_group(
            "Recommended Additional Coverage", recommended_additional_targets
        )
        _print_coverage_group(
            "Optional Duplicate Coverage",
            optional_targets,
            display_limit=HUMAN_OPTIONAL_DUPLICATE_DISPLAY_LIMIT,
            overflow_note="showing only the top duplicate fallbacks; the full duplicate tail remains in JSON output",
        )
        if unavailable_targets:
            print("Unavailable In Current Artifacts")
            rows = [
                [
                    index,
                    item.get("build_target")
                    or item.get("xdevice_module_name")
                    or item.get("project")
                    or "-",
                    item.get("artifact_reason") or "-",
                ]
                for index, item in enumerate(unavailable_targets, start=1)
            ]
            _print_human_table(["#", "Suite", "Why Skipped"], rows, indent=2)
            print()

    def print_run_targets(
        targets: list[dict], relevance_summary: dict[str, object] | None = None
    ) -> None:
        if not targets:
            return
        primary_targets, broader_targets = split_scope_groups(targets)

        def _print_target_group(group_title: str, grouped_targets: list[dict]) -> None:
            if not grouped_targets:
                return
            print(group_title)
            target_rows: list[list[object]] = []
            plan_rows: list[list[object]] = []
            result_rows: list[list[object]] = []
            display_limit = (
                HUMAN_RUN_TARGET_DISPLAY_LIMIT
                if len(grouped_targets) > HUMAN_RUN_TARGET_DISPLAY_LIMIT
                else None
            )
            display_targets = (
                grouped_targets[:display_limit] if display_limit else grouped_targets
            )
            for index, target in enumerate(display_targets, start=1):
                target_rows.append(
                    [
                        index,
                        _suite_label(target),
                        target.get("artifact_status", "-"),
                        target.get("scope_tier", "-"),
                        target.get("variant", "-"),
                        target.get("bucket", "-"),
                        _format_estimate_label(target),
                        _human_preview(
                            (
                                [target.get("artifact_reason")]
                                if target.get("artifact_status") == "missing"
                                else []
                            )
                            + list(target.get("scope_reasons", [])),
                            limit=2,
                        ),
                        target.get("project") or target.get("test_json") or "-",
                    ]
                )
                for plan in target.get("execution_plan", []):
                    plan_rows.append(
                        [
                            index,
                            plan.get("device_label", "-"),
                            plan.get("status", "-"),
                            plan.get("selected_tool") or "-",
                            _human_join(plan.get("available_tools", [])),
                            plan.get("reason") or "-",
                            plan.get("result_path") or "-",
                        ]
                    )
                for result in target.get("execution_results", []):
                    result_rows.append(
                        [
                            index,
                            result.get("device_label", "-"),
                            result.get("status", "-"),
                            result.get("selected_tool") or "-",
                            _format_duration_seconds(result.get("duration_s")),
                            "-"
                            if result.get("returncode") is None
                            else result.get("returncode"),
                            _format_case_summary(result.get("case_summary")),
                            _tail_hint(result),
                            result.get("result_path") or "-",
                        ]
                    )
            _print_human_table(
                [
                    "#",
                    "Suite",
                    "Artifacts",
                    "Scope",
                    "Surface",
                    "Priority",
                    "Est.",
                    "Why First",
                    "Project",
                ],
                target_rows,
                indent=2,
            )
            print()
            if display_limit and len(grouped_targets) > display_limit:
                note_rows: list[tuple[object, object]] = [
                    ("Visible", f"{display_limit} of {len(grouped_targets)}"),
                    ("Note", "Full suite list remains in selected_tests.json."),
                ]
                if selected_tests_json_path:
                    note_rows.append(("JSON", selected_tests_json_path))
                _print_key_value_section(f"{group_title} Note", note_rows)
            missing_targets = [
                target
                for target in grouped_targets
                if str(target.get("artifact_status") or "") == "missing"
            ]
            if missing_targets:
                _print_actionable_command_list(
                    "Unavailable Suites",
                    [
                        {
                            "label": _suite_label(target),
                            "why": target.get("artifact_reason")
                            or "suite is absent from the active ACTS artifacts",
                            "command": "",
                        }
                        for target in missing_targets
                    ],
                )
            show_plan = bool(result_rows) or any(
                row[2] != "pending" for row in plan_rows
            )
            if plan_rows and show_plan:
                print("Execution Plan")
                _print_human_table(
                    [
                        "#",
                        "Device",
                        "Status",
                        "Tool",
                        "Available",
                        "Reason",
                        "Result Path",
                    ],
                    plan_rows,
                    indent=2,
                )
                print()
            if result_rows:
                print("Execution Results")
                _print_human_table(
                    [
                        "#",
                        "Device",
                        "Status",
                        "Tool",
                        "Duration",
                        "RC",
                        "Case Summary",
                        "Hint",
                        "Result Path",
                    ],
                    result_rows,
                    indent=2,
                )
                print()

        if primary_targets:
            _print_target_group("Primary Tests", primary_targets)
        if broader_targets:
            _print_target_group("Broader Coverage", broader_targets)
        if not primary_targets and not broader_targets:
            return

    def print_projects(projects: list[dict]) -> None:
        if not projects:
            return

        def _print_project_group(
            group_title: str, grouped_projects: list[dict]
        ) -> None:
            if not grouped_projects:
                return
            file_rows: list[list[object]] = []
            for index, project in enumerate(grouped_projects, start=1):
                for test_file in project.get("test_files", []):
                    file_rows.append(
                        [
                            index,
                            project.get("project", "-"),
                            test_file.get("score", "-"),
                            test_file.get("file", "-"),
                            _human_preview(test_file.get("reasons", []), limit=5),
                        ]
                    )
            if file_rows:
                print(group_title)
                _print_human_table(
                    ["#", "Project", "File Score", "File", "Why It Matched"],
                    file_rows,
                    indent=2,
                )
                print()

        primary_projects, broader_projects = split_scope_groups(projects)
        if primary_projects:
            _print_project_group("Primary Evidence", primary_projects)
        if broader_projects:
            _print_project_group("Broader Coverage Evidence", broader_projects)

    if cache_used is None:
        cache_used = bool(report.get("cache_used"))

    summary_rows: list[tuple[object, object]] = [
        ("Workspace", report.get("repo_root")),
        ("XTS", report.get("xts_root")),
        ("SDK API (selection)", report.get("sdk_api_root")),
        ("ACE Engine", report.get("git_repo_root")),
        ("ACTS Out", report.get("acts_out_root")),
        ("Mode", report.get("variants_mode", "auto")),
        ("Index Cache", _cache_state_text(cache_used, report.get("cache_file"))),
    ]
    if report.get("ranking_rules_file"):
        summary_rows.append(("Ranking Rules", report.get("ranking_rules_file")))
    if report.get("runtime_state_root"):
        summary_rows.append(("Runtime State", report.get("runtime_state_root")))
    if report.get("runtime_history_file"):
        summary_rows.append(("Runtime History", report.get("runtime_history_file")))
    if report.get("selector_run"):
        selector_run = report["selector_run"]
        summary_rows.extend(
            [
                (
                    "selector_run",
                    f"label={selector_run.get('label', '-')}, status={selector_run.get('status', '-')}, run_dir={selector_run.get('run_dir', '-')}",
                ),
                ("selector_run_manifest", selector_run.get("manifest_path", "-")),
            ]
        )
    if report.get("requested_devices"):
        summary_rows.append(("Devices", _human_join(report["requested_devices"])))
    if report.get("daily_prebuilt"):
        daily_prebuilt = report["daily_prebuilt"]
        summary_rows.append(
            (
                "Daily Prebuilt",
                f"status={daily_prebuilt.get('status', '-')}, tag={daily_prebuilt.get('tag', '-')}, component={daily_prebuilt.get('component', '-')}, acts_out_root={daily_prebuilt.get('acts_out_root', '-') or '-'}",
            )
        )
        if daily_prebuilt.get("note"):
            summary_rows.append(("Daily Note", daily_prebuilt["note"]))
    if json_report_path is not None:
        summary_rows.append(("JSON", json_report_path))
    _print_key_value_section("Report Summary", summary_rows)

    product_build = report["product_build"]
    built = report["built_artifacts"]
    artifact_index = report.get("built_artifact_index", {})
    build_rows: list[list[object]] = [
        [
            "selector_analysis",
            "ready",
            "Test search already completed. Product build is not required for selection itself.",
        ],
        [
            "execution_artifacts",
            _preparation_summary(report),
            (
                "Needed only for running tests. You can either download prebuilt test artifacts or build them locally."
            ),
        ],
        [
            "product_build",
            product_build.get("status", "-"),
            (
                f"out_dir={_human_value(product_build.get('out_dir_exists'))}, "
                f"build_log={_human_value(product_build.get('build_log_exists'))}, "
                f"error_log={_human_value(product_build.get('error_log_exists'))}, "
                f"error_log_size={product_build.get('error_log_size', 0)}, "
                f"reason={product_build.get('reason', '-')}"
            ),
        ],
        [
            "built_artifacts",
            built.get("status", "-"),
            (
                f"testcases_dir={_human_value(built.get('testcases_dir_exists'))}, "
                f"module_info={_human_value(built.get('module_info_exists'))}, "
                f"testcase_json_count={built.get('testcase_json_count', 0)}, "
                f"module_info_entry_count={built.get('module_info_entry_count', 0)}"
            ),
        ],
    ]
    if artifact_index:
        build_rows.append(
            [
                "built_artifact_index",
                artifact_index.get("status", "-"),
                (
                    f"testcase_modules={artifact_index.get('testcase_modules_count', 0)}, "
                    f"hap_runtime_modules={artifact_index.get('hap_runtime_modules_count', 0)}"
                ),
            ]
        )
    if report.get("build_guidance"):
        guidance = report["build_guidance"]
        build_rows.append(
            [
                "local_build_option",
                "available" if guidance.get("required") else "not-needed",
                guidance.get("reason", "-"),
            ]
        )
    print("Preparation")
    _print_human_table(["Item", "Status", "Details"], build_rows)
    print()
    if report.get("build_guidance"):
        guidance = report["build_guidance"]
        command_rows: list[list[object]] = []
        if guidance.get("code_build_required"):
            command_rows.append(
                ["product", guidance.get("full_code_build_command", "-")]
            )
        if guidance.get("acts_build_required"):
            command_rows.append(["acts", guidance.get("full_acts_build_command", "-")])
        for command in guidance.get("target_build_commands", [])[:5]:
            command_rows.append(["target", command])
        if command_rows:
            _print_actionable_command_list(
                "Local Build Commands",
                [
                    {
                        "label": f"Local build [{scope}]",
                        "why": "Prepare missing local build artifacts.",
                        "command": command,
                    }
                    for scope, command in command_rows
                ],
            )

    next_steps = report.get("next_steps", [])
    if next_steps:
        status_rank = {
            "recommended": 0,
            "ready": 1,
            "follow-up": 2,
            "optional": 3,
            "blocked": 4,
        }

        def _next_step_sort_key_main(item: dict[str, object]) -> tuple[object, ...]:
            step = str(item.get("step", ""))
            prefix = 0 if step == "Repeat this run" else 1
            return (prefix, status_rank.get(str(item.get("status", "")), 99), step)

        ordered_next_steps = sorted(next_steps, key=_next_step_sort_key_main)
        _print_actionable_command_list("Next Steps", ordered_next_steps)

    if unique_run_targets:
        runnable_inventory_count = sum(
            1 for group in unique_run_targets if _run_target_has_inventory(group)
        )
        unavailable_inventory_count = max(
            len(unique_run_targets) - runnable_inventory_count, 0
        )
        runnable_rows: list[tuple[object, object]] = [
            ("Selected Inventory Entries", len(unique_run_targets)),
            ("Selected By Analysis", selected_target_count),
            ("Runnable In Current Inventory", runnable_inventory_count),
            (
                "Meaning",
                '"Runnable Tests" is shorthand only: selection comes from source/API analysis, and actual execution still depends on the current ACTS/build artifacts.',
            ),
            (
                "Manual Selection",
                "Use --run-test-name <name> or --run-test-names-file <file> with the run command.",
            ),
        ]
        if unavailable_inventory_count > 0:
            runnable_rows.append(
                ("Unavailable In Current Inventory", unavailable_inventory_count)
            )
        if selected_tests_json_path:
            runnable_rows.append(("JSON", selected_tests_json_path))
        requested_names = list(
            report.get("execution_overview", {}).get("requested_test_names", [])
        )
        if requested_names:
            runnable_rows.append(("Requested Names", _human_join(requested_names)))
        _print_key_value_section("Selected Test Inventory", runnable_rows)

    coverage_recommendations = report.get("coverage_recommendations", {})
    if coverage_recommendations:
        print_coverage_recommendations(coverage_recommendations)

    execution_rows: list[tuple[object, object]] = []
    if report.get("execution_overview"):
        overview = report["execution_overview"]
        execution_rows.append(
            (
                "execution_overview",
                (
                    f"tool={overview.get('run_tool', '-')}, "
                    f"run_priority={overview.get('run_priority', 'recommended')}, "
                    f"parallel_jobs={overview.get('parallel_jobs', 1)}, "
                    f"device_lock_timeout={overview.get('device_lock_timeout_s', '-')}, "
                    f"shard_mode={overview.get('shard_mode', 'mirror')}, "
                    f"unique_targets={overview.get('unique_target_count', 0)}, "
                    f"required_targets={overview.get('required_target_count', 0)}, "
                    f"recommended_targets={overview.get('recommended_target_count', 0)}, "
                    f"optional_targets={overview.get('optional_target_count', 0)}, "
                    f"selected_targets={overview.get('selected_target_count', 0)}, "
                    f"executed={_human_value(overview.get('executed'))}"
                ),
            )
        )
    if report.get("execution_preflight"):
        preflight = report["execution_preflight"]
        execution_rows.append(
            (
                "execution_preflight",
                (
                    f"status={preflight.get('status', '-')}, "
                    f"plans={preflight.get('plan_count', 0)}, "
                    f"tools={_human_join(preflight.get('selected_tools', []))}, "
                    f"connected_devices={_human_join(preflight.get('connected_devices', []))}"
                ),
            )
        )
        if preflight.get("errors"):
            execution_rows.append(
                (
                    "preflight_errors",
                    _human_preview(preflight.get("errors", [])[:5], limit=5),
                )
            )
        if preflight.get("warnings"):
            execution_rows.append(
                (
                    "preflight_warnings",
                    _human_preview(preflight.get("warnings", [])[:5], limit=5),
                )
            )
    if report.get("execution_summary"):
        summary = report["execution_summary"]
        execution_rows.append(
            (
                "execution_summary",
                (
                    f"planned={summary.get('planned_run_count', 0)}, "
                    f"passed={summary.get('passed', 0)}, "
                    f"failed={summary.get('failed', 0)}, "
                    f"blocked={summary.get('blocked', 0)}, "
                    f"timeout={summary.get('timeout', 0)}, "
                    f"unavailable={summary.get('unavailable', 0)}, "
                    f"skipped={summary.get('skipped', 0)}"
                ),
            )
        )
    if report.get("runtime_history_update"):
        history_update = report["runtime_history_update"]
        execution_rows.append(
            (
                "runtime_history",
                (
                    f"file={history_update.get('history_file', '-')}, "
                    f"updated_targets={history_update.get('updated_targets', 0)}, "
                    f"updated_samples={history_update.get('updated_samples', 0)}, "
                    f"significant_updates={history_update.get('significant_updates', 0)}"
                ),
            )
        )
    _print_key_value_section("Execution", execution_rows)

    timings = report.get("timings_ms", {})
    if timings and report.get("debug_trace"):
        print("Timings (ms)")
        _print_human_table(
            ["Metric", "Value"],
            [[key, value] for key, value in timings.items()],
            indent=2,
        )
        print()

    excluded_inputs = report.get("excluded_inputs", [])
    if excluded_inputs:
        print("Excluded Inputs")
        _print_human_table(
            ["Changed File", "Rule", "Matched Prefix"],
            [
                [
                    item.get("changed_file", "-"),
                    item.get("rule_id", item.get("reason", "-")),
                    item.get("matched_prefix", "-"),
                ]
                for item in excluded_inputs
            ],
            indent=2,
        )
        print()

    show_source_evidence = bool(report.get("show_source_evidence", False))
    if report["results"] and not show_source_evidence:
        _print_key_value_section(
            "Source Evidence",
            [
                (
                    "Visibility",
                    "hidden by default; use --show-source-evidence to inspect matching source files",
                )
            ],
        )
    if compact_changed_file_sections and report["results"]:
        print("Changed Files Summary")
        changed_summary_rows: list[list[object]] = []
        for index, item in enumerate(report["results"], start=1):
            primary_projects, broader_projects = split_scope_groups(
                item.get("projects", [])
            )
            affected_apis = list(item.get("affected_api_entities", [])) or list(
                item.get("file_level_affected_api_entities", [])
            )
            changed_summary_rows.append(
                [
                    index,
                    item.get("changed_file", "-"),
                    _human_preview(affected_apis, limit=3),
                    len(item.get("projects", [])),
                    len(item.get("run_targets", [])),
                    len(primary_projects),
                    len(broader_projects),
                    "see JSON",
                ]
            )
        _print_human_table(
            [
                "#",
                "Changed File",
                "APIs",
                "Tests",
                "Run Targets",
                "Primary",
                "Broader",
                "Detail",
            ],
            changed_summary_rows,
            indent=2,
        )
        print()
        compact_note_rows: list[tuple[object, object]] = [
            (
                "Mode",
                f"compact (auto-enabled for {len(report['results'])} changed files)",
            ),
            (
                "Why",
                "Per-file suite tables are omitted to keep multi-file PR output readable; full per-file detail remains in the JSON report.",
            ),
        ]
        if json_report_path is not None:
            compact_note_rows.append(("JSON", json_report_path))
        _print_key_value_section("Changed Files Note", compact_note_rows)
    for item in report["results"]:
        if compact_changed_file_sections:
            continue
        signals = item["signals"]
        relevance_summary = item.get("relevance_summary", {})
        primary_projects, broader_projects = split_scope_groups(
            item.get("projects", [])
        )
        changed_rows: list[tuple[object, object]] = [
            (
                "Surface",
                item.get(
                    "effective_variants_mode", report.get("variants_mode", "auto")
                ),
            ),
            ("Families", _human_preview(item.get("coverage_families", []))),
            ("Capabilities", _human_preview(item.get("coverage_capabilities", []))),
            (
                "Relevance",
                relevance_summary.get("mode", report.get("relevance_mode", "all")),
            ),
            (
                "Showing",
                _showing_summary_text(relevance_summary, len(item.get("projects", []))),
            ),
            ("Tests", len(item.get("projects", []))),
            ("Run Targets", len(item.get("run_targets", []))),
            ("Primary", len(primary_projects)),
            ("Broader", len(broader_projects)),
        ]
        source_only_consumers = list(item.get("source_only_consumers", []))
        if source_only_consumers:
            changed_rows.append(("Source-only Apps", len(source_only_consumers)))
            changed_rows.append(
                (
                    "Source-only Preview",
                    _human_preview(
                        [entry.get("project", "-") for entry in source_only_consumers],
                        limit=4,
                    ),
                )
            )
        if item.get("changed_symbols"):
            changed_rows.append(
                (
                    "Changed Symbols",
                    _human_preview(item.get("changed_symbols", []), limit=4),
                )
            )
        if item.get("changed_ranges"):
            changed_rows.append(
                (
                    "Changed Ranges",
                    _human_preview(item.get("changed_ranges", []), limit=4),
                )
            )
        if item.get("derived_source_symbols"):
            changed_rows.append(
                (
                    "Derived Symbols",
                    _human_preview(item.get("derived_source_symbols", []), limit=4),
                )
            )
        if item.get("affected_api_entities"):
            changed_rows.append(
                (
                    "Affected APIs",
                    _human_preview(item.get("affected_api_entities", []), limit=4),
                )
            )
        file_level_apis = list(item.get("file_level_affected_api_entities", []))
        if file_level_apis and file_level_apis != item.get("affected_api_entities", []):
            changed_rows.append(
                ("File-level APIs", _human_preview(file_level_apis, limit=4))
            )
        function_coverage = list(item.get("function_coverage", []))
        if function_coverage:
            status_counts: dict[str, int] = {}
            not_covered_symbols: list[str] = []
            unresolved_symbols: list[str] = []
            for entry in function_coverage:
                status = str(entry.get("status") or "unresolved")
                status_counts[status] = status_counts.get(status, 0) + 1
                symbol = str(entry.get("symbol") or "")
                if status == "not_covered" and symbol:
                    not_covered_symbols.append(symbol)
                if status == "unresolved" and symbol:
                    unresolved_symbols.append(symbol)
            changed_rows.append(
                (
                    "Function Coverage",
                    ", ".join(
                        f"{key}={value}" for key, value in sorted(status_counts.items())
                    ),
                )
            )
            if not_covered_symbols:
                changed_rows.append(
                    ("Not Covered", _human_preview(not_covered_symbols, limit=4))
                )
            if unresolved_symbols:
                changed_rows.append(
                    (
                        "Unresolved Functions",
                        _human_preview(unresolved_symbols, limit=4),
                    )
                )
        if report.get("debug_trace"):
            changed_rows.extend(
                [
                    ("Modules", _human_preview(signals.get("modules", []))),
                    ("Weak Modules", _human_preview(signals.get("weak_modules", []))),
                    ("Symbols", _human_preview(signals.get("symbols", []))),
                    ("Weak Symbols", _human_preview(signals.get("weak_symbols", []))),
                    ("Project Hints", _human_preview(signals.get("project_hints", []))),
                    ("Method Hints", _human_preview(signals.get("method_hints", []))),
                    ("Type Hints", _human_preview(signals.get("type_hints", []))),
                    ("Member Hints", _human_preview(signals.get("member_hints", []))),
                    ("Families", _human_preview(signals.get("family_tokens", []))),
                ]
            )
        if item.get("unresolved_reason"):
            changed_rows.append(("Unresolved", item["unresolved_reason"]))
        if item.get("debug"):
            debug = item["debug"]
            before = debug.get(
                "candidate_projects_before_prefilter",
                debug.get("candidate_project_count", 0),
            )
            after = debug.get(
                "candidate_projects_after_prefilter",
                debug.get("candidate_project_count", 0),
            )
            changed_rows.append(
                (
                    "debug",
                    f"candidate_projects={debug.get('candidate_project_count', 0)}, prefilter={before}->{after}, matched_projects={debug.get('matched_project_count', 0)}",
                )
            )
        if report.get("debug_trace") and item.get("unresolved_debug"):
            debug = item["unresolved_debug"]
            changed_rows.append(
                (
                    "unresolved_debug",
                    f"top_score={debug.get('top_score', '-')}, broad_common_hits={debug.get('broad_common_hits', '-')}",
                )
            )
        _print_key_value_section(f"Changed File: {item['changed_file']}", changed_rows)
        _print_explanation_section(item.get("explanation"))
        if not item["projects"]:
            print("No candidate XTS projects found")
            print()
            continue
        print_run_targets(item["run_targets"], relevance_summary)
        if show_source_evidence:
            print_projects(item["projects"])

    if report["unresolved_files"]:
        print("Unresolved Files")
        has_reason_class = any(
            item.get("reason_class") for item in report["unresolved_files"]
        )
        headers = (
            ["Changed File", "Reason", "Class"]
            if has_reason_class
            else ["Changed File", "Reason"]
        )
        rows = []
        for item in report["unresolved_files"]:
            base = [item.get("changed_file", "-"), item.get("reason", "-")]
            if has_reason_class:
                base.append(item.get("reason_class", "-"))
            rows.append(base)
        _print_human_table(
            headers,
            rows,
            indent=2,
        )
        print()

    for item in report["symbol_queries"]:
        relevance_summary = item.get("relevance_summary", {})
        primary_projects, broader_projects = split_scope_groups(
            item.get("projects", [])
        )
        signal_rows: list[tuple[object, object]] = [
            (
                "Surface",
                item.get(
                    "effective_variants_mode", report.get("variants_mode", "auto")
                ),
            ),
            ("Families", _human_preview(item.get("coverage_families", []))),
            ("Capabilities", _human_preview(item.get("coverage_capabilities", []))),
            (
                "Relevance",
                relevance_summary.get("mode", report.get("relevance_mode", "all")),
            ),
            (
                "Showing",
                _showing_summary_text(relevance_summary, len(item.get("projects", []))),
            ),
            ("Tests", len(item.get("projects", []))),
            ("Run Targets", len(item.get("run_targets", []))),
            ("Primary", len(primary_projects)),
            ("Broader", len(broader_projects)),
        ]
        if report.get("debug_trace"):
            signal_rows.extend(
                [
                    ("Symbols", _human_preview(item["signals"].get("symbols", []))),
                    (
                        "Weak Symbols",
                        _human_preview(item["signals"].get("weak_symbols", [])),
                    ),
                    (
                        "Project Hints",
                        _human_preview(item["signals"].get("project_hints", [])),
                    ),
                    (
                        "Method Hints",
                        _human_preview(item["signals"].get("method_hints", [])),
                    ),
                    (
                        "Type Hints",
                        _human_preview(item["signals"].get("type_hints", [])),
                    ),
                    (
                        "Member Hints",
                        _human_preview(item["signals"].get("member_hints", [])),
                    ),
                ]
            )
        if item.get("debug"):
            debug = item["debug"]
            before = debug.get(
                "candidate_projects_before_prefilter",
                debug.get("candidate_project_count", 0),
            )
            after = debug.get(
                "candidate_projects_after_prefilter",
                debug.get("candidate_project_count", 0),
            )
            signal_rows.append(
                (
                    "debug",
                    f"candidate_projects={debug.get('candidate_project_count', 0)}, prefilter={before}->{after}, matched_projects={debug.get('matched_project_count', 0)}",
                )
            )
        _print_key_value_section(f"Symbol Query: {item['query']}", signal_rows)
        _print_explanation_section(item.get("explanation"))
        evidence = item.get("code_search_evidence", {})
        evidence_rows = [
            ["exact", match] for match in evidence.get("exact_hits", [])[:5]
        ]
        evidence_rows.extend(
            ["related", match] for match in evidence.get("related_hits", [])[:5]
        )
        if evidence_rows and report.get("debug_trace"):
            print("Code Search Evidence")
            _print_human_table(["Type", "Match"], evidence_rows, indent=2)
            print()
        if not item["projects"]:
            print("No candidate XTS projects found")
            print()
            continue
        print_run_targets(item.get("run_targets", []), relevance_summary)
        if show_source_evidence:
            print_projects(item["projects"])

    for item in report["code_queries"]:
        _print_key_value_section(
            f"Code Query: {item['query']}", [("matches", len(item.get("matches", [])))]
        )
        if not item["matches"]:
            print("No code matches found")
            print()
            continue
        match_rows = [
            [
                index,
                match.get("score", "-"),
                match.get("file", "-"),
                _human_preview(match.get("reasons", []), limit=5),
            ]
            for index, match in enumerate(item["matches"], start=1)
        ]
        print("Code Matches")
        _print_human_table(["#", "Score", "File", "Reasons"], match_rows, indent=2)
        print()
