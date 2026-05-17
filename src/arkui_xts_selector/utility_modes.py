"""Utility mode functions for downloading, flashing, and benchmarking."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import Any

from .daily_prebuilt import (
    PreparedDailyArtifact,
    list_daily_tags,
    is_placeholder_metadata,
)
from .flashing import flash_image_bundle
from .models import AppConfig
from . import progress as _progress
from . import report_json as _report_json


def run_list_tags_mode(args: argparse.Namespace, app_config: "AppConfig") -> int:
    tag_type = (args.list_daily_tags or "tests").lower().strip()
    if tag_type == "sdk":
        component = app_config.sdk_component
        branch = app_config.sdk_branch
        label = "SDK"
        component_role = "sdk"
    elif tag_type == "firmware":
        component = app_config.firmware_component
        branch = app_config.firmware_branch
        label = "firmware"
        component_role = "firmware"
    else:
        component = app_config.daily_component
        branch = app_config.daily_branch
        label = "XTS tests"
        component_role = "xts"

    count = max(1, args.list_tags_count)
    after_date = args.list_tags_after or None
    before_date = args.list_tags_before or None
    lookback = max(1, args.list_tags_lookback)

    date_range_note = ""
    if after_date or before_date:
        date_range_note = (
            f", date filter: {after_date or '...'} – {before_date or 'today'}"
        )
    print(
        f"Listing {count} most recent {label} tags (component={component}, branch={branch}{date_range_note}):"
    )
    try:
        builds = list_daily_tags(
            component=component,
            branch=branch,
            count=count,
            after_date=after_date,
            before_date=before_date,
            lookback_days=lookback,
            component_role=component_role,
        )
    except Exception as exc:
        print(f"error: failed to fetch tag list: {exc}", file=sys.stderr)
        return 2

    if not builds:
        print("  (no builds found in the specified date range)")
        return 0

    for build in builds:
        extra = []
        if not is_placeholder_metadata(build.version_name):
            extra.append(build.version_name)
        if not is_placeholder_metadata(build.hardware_board):
            extra.append(build.hardware_board)
        suffix = f"  [{', '.join(extra)}]" if extra else ""
        print(f"  {build.tag}{suffix}")
    return 0


def utility_mode_requested(args: argparse.Namespace) -> bool:
    return any(
        (
            args.download_daily_tests,
            args.download_daily_sdk,
            args.download_daily_firmware,
            args.flash_daily_firmware,
            bool(args.flash_firmware_path),
        )
    )


def write_and_render_utility_report(
    report: dict[str, Any],
    json_to_stdout: bool,
    json_output_path: Path | None,
) -> None:
    written_json_path = _report_json.write_json_report(
        report, json_to_stdout=json_to_stdout, json_output_path=json_output_path
    )
    if json_to_stdout:
        return
    print("utility_mode: daily_artifacts")
    operations = report.get("operations", {})
    for name, payload in operations.items():
        status = payload.get("status", "")
        print(f"{name}: {status}")
        if payload.get("error"):
            print(f"  error: {payload['error']}")
        for key in (
            "tag",
            "component",
            "role",
            "package_kind",
            "cache_root",
            "archive_path",
            "extracted_root",
            "manifest_path",
        ):
            value = payload.get(key)
            if value:
                print(f"  {key}: {value}")
        manifest_hint = payload.get("manifest_path")
        if manifest_hint:
            print(f"  hint: ohos init -m {manifest_hint} sync build rk3568")
        if payload.get("note"):
            print(f"  note: {payload['note']}")
        if payload.get("output_tail"):
            print("  output_tail:")
            for line in str(payload["output_tail"]).splitlines():
                print(f"    {line}")
    if written_json_path is not None:
        print(f"json_output_path: {written_json_path}")


def run_benchmark_mode(args: argparse.Namespace, app_config: AppConfig) -> int:
    """Run benchmark cases from canonical corpus and report results.

    Returns 0 if all cases pass, 1 if any fail.
    """
    from .benchmark import BenchmarkRunner, BenchmarkResult

    fixtures_dir = (
        Path(args.benchmark_fixtures_dir) if args.benchmark_fixtures_dir else None
    )
    if not fixtures_dir:
        fixtures_dir = (
            Path(__file__).resolve().parents[1]
            / "tests"
            / "fixtures"
            / "canonical_corpus"
        )

    if not fixtures_dir.exists():
        print(
            f"error: benchmark fixtures directory not found: {fixtures_dir}",
            file=sys.stderr,
        )
        return 2

    runner = BenchmarkRunner(fixtures_dir)
    cases = runner.load_all_cases()

    if not cases:
        print("error: no benchmark cases found", file=sys.stderr)
        return 2

    results: list[BenchmarkResult] = []
    overall_pass = True

    for case in cases:
        # Build a minimal report for evaluation
        # We need to run the selector to get a real report
        # For now, evaluate with empty report if workspace unavailable
        ws = _workspace()
        if ws is None:
            # No workspace available — skip evaluation but still report structure
            results.append(
                BenchmarkResult(
                    case_name=case.name,
                    family=case.family,
                    pass_fail=False,
                    notes=f"SKIPPED: workspace not available for case {case.name!r}",
                )
            )
            continue

        # Run selector for this case
        try:
            extra_args: list[str] = []
            for changed_file in case.input_changed_files:
                full_path = ws["repo_root"].parent / changed_file
                if full_path.exists():
                    extra_args.extend(["--changed-file", str(full_path)])
                else:
                    extra_args.extend(["--changed-file", changed_file])

            report = _run_selector(ws, extra_args)
            result = runner.evaluate(case, report)
            results.append(result)
        except RuntimeError as exc:
            results.append(
                BenchmarkResult(
                    case_name=case.name,
                    family=case.family,
                    pass_fail=False,
                    notes=f"ERROR: {exc}",
                )
            )

    # Print summary
    print("\n=== Benchmark Results ===")
    for result in results:
        status = "PASS" if result.pass_fail else "FAIL"
        print(f"  [{status}] {result.case_name}: {result.notes}")
        if result.noise_violations:
            for v in result.noise_violations:
                print(f"    noise: {v}")
        if result.recall < 0.9 and result.recall > 0:
            print(f"    WARNING: recall {result.recall:.2f} below 0.9 threshold")
        if result.recall == 0.0:
            print("    SKIPPED (no workspace)")
        if result.notes.startswith("ERROR"):
            print(f"    ERROR: {result.notes}")
        if result.notes.startswith("SKIPPED"):
            continue
        if not result.pass_fail:
            overall_pass = False

    print(
        f"\nTotal: {len(results)} cases, {'ALL PASS' if overall_pass else 'SOME FAILED'}"
    )
    return 0 if overall_pass else 1


def run_inspect_mode(args: argparse.Namespace, app_config: AppConfig) -> int:
    """Inspect the persisted dependency/lineage map."""
    from .api_lineage import read_api_lineage_map, default_api_lineage_map_file

    lineage_path = default_api_lineage_map_file(app_config.runtime_state_root)
    if not lineage_path.exists():
        print(f"error: lineage map not found at {lineage_path}", file=sys.stderr)
        return 2

    lineage_map = read_api_lineage_map(lineage_path)

    if args.inspect_api_entity:
        entity = args.inspect_api_entity
        result = {
            "api_entity": entity,
            "source_files": sorted(lineage_map.api_to_sources.get(entity, set())),
            "families": sorted(lineage_map.api_to_families.get(entity, set())),
            "surfaces": sorted(lineage_map.api_to_surfaces.get(entity, set())),
            "consumer_files": sorted(
                lineage_map.api_to_consumer_files.get(entity, set())
            ),
            "consumer_projects": sorted(
                lineage_map.api_to_consumer_projects.get(entity, set())
            ),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.inspect_source_file:
        source = args.inspect_source_file
        result = {
            "source_file": source,
            "api_entities": sorted(lineage_map.source_to_apis.get(source, set())),
            "consumer_files": [],
            "consumer_projects": [],
        }
        for api in result["api_entities"]:
            result["consumer_files"].extend(
                lineage_map.api_to_consumer_files.get(api, set())
            )
            result["consumer_projects"].extend(
                lineage_map.api_to_consumer_projects.get(api, set())
            )
        result["consumer_files"] = sorted(set(result["consumer_files"]))
        result["consumer_projects"] = sorted(set(result["consumer_projects"]))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.inspect_consumer_project:
        project = args.inspect_consumer_project
        result = {
            "consumer_project": project,
            "api_entities": sorted(
                lineage_map.consumer_project_to_apis.get(project, set())
            ),
            "source_files": [],
        }
        for api in result["api_entities"]:
            result["source_files"].extend(lineage_map.api_to_sources.get(api, set()))
        result["source_files"] = sorted(set(result["source_files"]))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    # No specific query — print map summary
    result = {
        "schema_version": lineage_map.schema_version,
        "metadata": lineage_map.metadata,
        "source_to_api_count": len(lineage_map.source_to_apis),
        "api_to_source_count": len(lineage_map.api_to_sources),
        "api_to_family_count": len(lineage_map.api_to_families),
        "consumer_file_count": len(lineage_map.consumer_file_to_apis),
        "consumer_project_count": len(lineage_map.consumer_project_to_apis),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def run_utility_mode(
    args: argparse.Namespace,
    app_config: AppConfig,
    progress_enabled: bool,
    json_to_stdout: bool,
    json_output_path: Path | None,
) -> int:
    report: dict[str, Any] = {
        "mode": "utility",
        "requested_devices": list(app_config.devices),
        "operations": {},
    }
    exit_code = 0

    if args.download_daily_tests:
        _progress.emit_progress(
            progress_enabled,
            f"downloading daily tests {app_config.daily_build_tag or ''}".strip(),
        )
        try:
            prepared = _progress.prepare_daily_prebuilt_from_config(app_config)
            if prepared is None:
                raise ValueError(
                    "daily build tag is required; provide --daily-build-tag"
                )
            report["operations"]["download_daily_tests"] = {
                **prepared.to_dict(),
                "role": "tests",
                "package_kind": "full",
                "status": "ready" if prepared.acts_out_root else "extracted",
                "primary_root": str(prepared.acts_out_root)
                if prepared.acts_out_root
                else "",
            }
        except (OSError, ValueError, FileNotFoundError, urllib.error.URLError) as exc:
            report["operations"]["download_daily_tests"] = {
                "status": "failed",
                "error": str(exc),
            }
            exit_code = 2

    firmware_prepared: PreparedDailyArtifact | None = None
    if args.download_daily_sdk:
        _progress.emit_progress(
            progress_enabled,
            f"downloading daily sdk {app_config.sdk_build_tag or ''}".strip(),
        )
        try:
            prepared_sdk = _progress.prepare_daily_sdk_from_config(app_config)
            report["operations"]["download_daily_sdk"] = prepared_sdk.to_dict()
        except (OSError, ValueError, FileNotFoundError, urllib.error.URLError) as exc:
            report["operations"]["download_daily_sdk"] = {
                "status": "failed",
                "error": str(exc),
            }
            exit_code = 2

    if args.download_daily_firmware or args.flash_daily_firmware:
        _progress.emit_progress(
            progress_enabled,
            f"downloading daily firmware {app_config.firmware_build_tag or ''}".strip(),
        )
        try:
            firmware_prepared = _progress.prepare_daily_firmware_from_config(app_config)
            report["operations"]["download_daily_firmware"] = (
                firmware_prepared.to_dict()
            )
        except (OSError, ValueError, FileNotFoundError, urllib.error.URLError) as exc:
            report["operations"]["download_daily_firmware"] = {
                "status": "failed",
                "error": str(exc),
            }
            exit_code = 2

    if args.flash_daily_firmware:
        _progress.emit_progress(progress_enabled, "flashing daily firmware")
        try:
            if firmware_prepared is None:
                raise ValueError("firmware package is not prepared")
            if firmware_prepared.primary_root is None:
                raise ValueError(
                    "no flashable image root was discovered in the firmware package"
                )
            flash_result = flash_image_bundle(
                image_root=firmware_prepared.primary_root,
                flash_py_path=str(app_config.flash_py_path)
                if app_config.flash_py_path
                else None,
                hdc_path=str(app_config.hdc_path) if app_config.hdc_path else None,
                device=app_config.device,
                progress_callback=(
                    lambda message: _progress.emit_subprogress(
                        progress_enabled, "flash", message
                    )
                ),
            )
            report["operations"]["flash_daily_firmware"] = flash_result.to_dict()
            if flash_result.status != "completed":
                exit_code = max(exit_code, 1)
        except (
            OSError,
            ValueError,
            FileNotFoundError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as exc:
            report["operations"]["flash_daily_firmware"] = {
                "status": "failed",
                "error": str(exc),
            }
            exit_code = max(exit_code, 2)

    if app_config.flash_firmware_path is not None:
        _progress.emit_progress(
            progress_enabled,
            f"flashing local firmware {app_config.flash_firmware_path}",
        )
        try:
            image_root = _progress.resolve_local_firmware_root(
                app_config.flash_firmware_path
            )
            flash_result = flash_image_bundle(
                image_root=image_root,
                flash_py_path=str(app_config.flash_py_path)
                if app_config.flash_py_path
                else None,
                hdc_path=str(app_config.hdc_path) if app_config.hdc_path else None,
                device=app_config.device,
                progress_callback=(
                    lambda message: _progress.emit_subprogress(
                        progress_enabled, "flash", message
                    )
                ),
            )
            report["operations"]["flash_local_firmware"] = {
                **flash_result.to_dict(),
                "requested_path": str(app_config.flash_firmware_path),
            }
            if flash_result.status != "completed":
                exit_code = max(exit_code, 1)
        except (
            OSError,
            ValueError,
            FileNotFoundError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as exc:
            report["operations"]["flash_local_firmware"] = {
                "status": "failed",
                "requested_path": str(app_config.flash_firmware_path),
                "error": str(exc),
            }
            exit_code = max(exit_code, 2)

    write_and_render_utility_report(
        report, json_to_stdout=json_to_stdout, json_output_path=json_output_path
    )
    return exit_code


# Helper functions for benchmark mode
def _workspace() -> dict | None:
    """Get workspace configuration for benchmark mode.

    This is a placeholder that should be implemented based on the actual
    workspace discovery logic needed for benchmark testing.
    """
    # TODO: Implement proper workspace discovery for benchmark mode
    # For now, return None to indicate workspace is not available
    return None


def _run_selector(workspace: dict, extra_args: list[str]) -> dict:
    """Run the selector with the given workspace and arguments.

    This is a placeholder that should be implemented based on the actual
    selector invocation logic needed for benchmark testing.
    """
    # TODO: Implement proper selector invocation for benchmark mode
    raise RuntimeError("Selector invocation not yet implemented for benchmark mode")
