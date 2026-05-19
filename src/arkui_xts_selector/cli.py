#!/usr/bin/env python3
"""
Suggest ArkUI XTS tests to run for changed ArkUI/OpenHarmony files.

This is impact analysis, not runtime coverage. It correlates:
1. ArkUI native files and paths
2. ArkUI SDK/API files
3. actual XTS imports and API usage
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


from .api_lineage import ApiLineageMap, build_api_lineage_map
from .api_entity_details import build_affected_api_entity_details
from .constants import COMMON_PROJECT_HINTS
from .api_surface import (
    parse_query_surface_intent,
)
from .build_state import build_guidance, inspect_product_build
from .built_artifacts import inspect_built_artifacts, load_built_artifact_index
from .daily_prebuilt import (
    DEFAULT_DAILY_COMPONENT,
    DEFAULT_DAILY_CACHE_ROOT,
    DEFAULT_FIRMWARE_CACHE_ROOT,
    DEFAULT_FIRMWARE_COMPONENT,
    DEFAULT_SDK_CACHE_ROOT,
    DEFAULT_SDK_COMPONENT,
)
from .execution import (
    RUN_PRIORITY_CHOICES,
    RUN_TOOL_CHOICES,
    SHARD_MODE_CHOICES,
    attach_execution_plan,
    build_run_target_entry,
    execute_planned_targets,
    normalize_requested_test_names,
    preflight_execution,
    read_requested_test_names,
    resolve_devices,
)
from .run_store import (
    build_run_manifest,
    create_run_session,
    default_run_store_root,
    write_run_artifacts,
)
from .runtime_history import (
    RuntimeHistoryIndex,
    annotate_report_runtime_estimates,
    build_runtime_history_index,
    update_runtime_history,
)
from .runtime_state import (
    default_runtime_history_file,
    default_runtime_state_root,
)
from .workspace import (
    default_acts_out_root,
    default_git_repo_root,
    default_sdk_api_root,
    default_xts_root,
    discover_repo_root,
)
from .report_human import (
    print_human,
    print_executive_summary,
    build_next_steps,
    build_coverage_run_commands,
)
from .report_explanation import (
    build_result_explanation,
    build_project_entry_explanation,
)
from .coverage_planner import (
    build_global_coverage_recommendations,
    driver_module_name,
    driver_type,
    build_unresolved_analysis,
    build_function_coverage_rows,
    _build_coverage_gap_report,
)
from .progress import (
    emit_progress,
    build_progress_callback,
    build_execution_progress_callback,
    write_execution_artifact_index,
    prepare_daily_prebuilt_from_config,
    prepare_daily_sdk_from_config,
    _has_local_acts_artifacts,
    _sync_prebuilt_acts_to_local_root,
)
from .query import (
    build_query_signals,
    explain_symbol_query_sources,
    search_code_matches,
)
from .report_json import (
    resolve_json_output_path,
    write_json_report,
    resolve_selected_tests_output_path,
    resolve_selected_tests_report_base_path,
    write_selected_tests_report,
    load_selector_report,
    resolve_selector_report_input,
    run_session_from_report,
)
from .utility_modes import (
    run_list_tags_mode,
    utility_mode_requested,
    run_benchmark_mode,
    run_inspect_mode,
    run_utility_mode,
)
from .signal_inference import (
    infer_signals,
    apply_api_lineage_signals,
    collect_source_only_consumers,
    compute_signal_symbol_df,
    resolve_variants_mode,
)
from .project_index import (
    repo_rel as project_index_repo_rel,
    default_cache_path as project_index_default_cache_path,
    default_cache_meta_path as project_index_default_cache_meta_path,
    parse_test_file_names,
    infer_xdevice_module_name,
    guess_build_target,
    load_or_build_projects,
    load_sdk_index,
    select_candidate_projects,
)
from .scoring import (
    UBIQUITOUS_DF_FRACTION,
    score_project,
    confidence,
    project_has_non_lexical_evidence,
    candidate_bucket,
    filter_project_results_by_relevance,
    classify_project_scope,
)
from .gate_adapter import apply_must_run_gate
from .scoring import (
    sort_project_results,
    matched_file_surfaces,
    should_keep_project_for_surface,
    restrict_explicit_surface_projects,
    diversify_symbol_query_projects,
    coverage_signature,
    deduplicate_by_coverage_signature,
    make_coverage_source,
)
from .source_profile import (
    build_source_profile,
    infer_project_family_profile,
)
from .file_indexing import (
    infer_project_type_hint_profile,
    infer_project_member_hint_profile,
)
from .git_host import (
    resolve_path,
    normalize_git_host_kind,
    load_ini_git_host_config,
    git_changed_files,
    resolve_pr_owner_repo,
    fetch_pr_changed_files,
    resolve_pr_api_credentials,
    fetch_pr_metadata_via_api,
    fetch_pr_changed_files_and_ranges_via_api,
)
from .changed_files import (
    normalize_changed_files,
    parse_changed_ranges,
    merge_changed_range_maps,
    load_changed_file_exclusion_config,
    filter_changed_files_for_xts,
)
from .mapping_config import (
    build_content_modifier_index,
    default_path_rules_file,
    default_composite_mappings_file,
    default_changed_file_exclusions_file,
    load_mapping_config,
)
from .ranking_rules import (
    default_ranking_rules_file,
    load_ranking_rules_config,
    apply_ranking_rules_config,
    RankingRulesConfig as RankingRulesConfigClass,
)
from .tokens import (
    compact_token,
)
from .file_io import (
    read_text,
    load_json_file,
)
from .models import (
    XtsUserError,
    SdkIndex,
    ContentModifierIndex,
    MappingConfig,
    AppConfig,
    TestProjectIndex,
)


RankingRulesConfig = RankingRulesConfigClass
# Re-export project_index functions for backward compatibility
default_cache_path = project_index_default_cache_path
default_cache_meta_path = project_index_default_cache_meta_path
repo_rel = project_index_repo_rel  # Use project_index version


def resolve_pr_changed_files_with_ranges(
    app_config: AppConfig,
    pr_ref: str,
    pr_source: str,
) -> tuple[list[Path], dict[Path, list[tuple[int, int]]]]:
    """Compatibility wrapper preserving cli-level monkeypatch points."""
    owner_repo = resolve_pr_owner_repo(
        pr_ref, app_config.git_repo_root, app_config.git_remote
    )
    api_error: RuntimeError | None = None
    if pr_source in ("auto", "api"):
        api_kind, api_url, token = resolve_pr_api_credentials(app_config, pr_ref)
        if not api_url or not token:
            api_error = RuntimeError(
                "PR API mode requires git host credentials; pass --git-host-token/--git-host-url or --git-host-config with [gitcode]/[codehub] token/url."
            )
        elif owner_repo is None:
            api_error = RuntimeError(
                "could not determine owner/repo for PR API mode from --pr-url or local git remote"
            )
        else:
            try:
                fetch_pr_metadata_via_api(
                    api_kind=api_kind,
                    api_url=api_url,
                    token=token,
                    owner=owner_repo[0],
                    repo=owner_repo[1],
                    pr_ref=pr_ref,
                )
                return fetch_pr_changed_files_and_ranges_via_api(
                    api_kind=api_kind,
                    api_url=api_url,
                    token=token,
                    owner=owner_repo[0],
                    repo=owner_repo[1],
                    pr_ref=pr_ref,
                    repo_root=app_config.git_repo_root,
                )
            except RuntimeError as exc:
                api_error = exc
        if pr_source == "api":
            raise (
                api_error
                if api_error is not None
                else RuntimeError("PR API mode failed")
            )

    try:
        return fetch_pr_changed_files(
            repo_root=app_config.git_repo_root,
            remote=app_config.git_remote,
            base_branch=app_config.git_base_branch,
            pr_ref=pr_ref,
        ), {}
    except RuntimeError as exc:
        if api_error is not None and pr_source == "auto":
            raise RuntimeError(f"api failed: {api_error}; git failed: {exc}") from exc
        raise


def resolve_pr_changed_files(
    app_config: AppConfig, pr_ref: str, pr_source: str
) -> list[Path]:
    """Resolve PR changed files while preserving the historical cli API."""
    changed_files, _changed_ranges = resolve_pr_changed_files_with_ranges(
        app_config, pr_ref, pr_source
    )
    return changed_files


# Re-export for backward compatibility
REPO_ROOT = discover_repo_root()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_CACHE_FILE = Path("/tmp/arkui_xts_selector_cache.json")
COMMAND_PREFIX_ENV = "ARKUI_XTS_SELECTOR_COMMAND_PREFIX"
COMMAND_MODE_ENV = "ARKUI_XTS_SELECTOR_COMMAND_MODE"
DEFAULT_REPORT_FILE = "arkui_xts_selector_report.json"
SELECTED_TESTS_FILE_NAME = "selected_tests.json"
RELEVANCE_MODE_CHOICES = ("all", "balanced", "strict")
PR_SOURCE_CHOICES = ("auto", "api", "git")
GIT_HOST_KIND_CHOICES = ("auto", "gitcode", "codehub")
CODEHUB_SECTION_NAMES = ("codehub", "codehub-y", "cr-y.codehub", "opencodehub")
HUMAN_OPTIONAL_DUPLICATE_DISPLAY_LIMIT = 20
HUMAN_RUN_TARGET_DISPLAY_LIMIT = 10
HUMAN_COMPACT_CHANGED_FILE_THRESHOLD = 8
PROGRESS_AGGREGATE_CHANGED_FILE_THRESHOLD = 6
PROGRESS_AGGREGATE_CHANGED_FILE_STEP = 5
DEFAULT_CHANGED_FILE_EXCLUSION_RULES = {
    "rules": [
        {
            "id": "native_unit_tests_root",
            "category": "non_xts_local_tests",
            "path_prefix": "test/unittest/",
            "description": "Native/unit-test sources are implementation-side checks, not user-facing XTS coverage targets.",
            "how_to_identify": [
                "Path starts with test/unittest/.",
                "File belongs to local unit-test coverage rather than XTS ACTS suites.",
            ],
        },
        {
            "id": "ace_engine_unit_tests_mirror",
            "category": "non_xts_local_tests",
            "path_prefix": "foundation/arkui/ace_engine/test/unittest/",
            "description": "Mirrored ace_engine unit-test directories should not drive XTS selection.",
            "how_to_identify": [
                "Path starts with foundation/arkui/ace_engine/test/unittest/.",
                "Content is repo-local unit testing, not external ArkUI XTS behavior coverage.",
            ],
        },
        {
            "id": "mock_sources_root",
            "category": "non_product_test_support",
            "path_prefix": "test/mock/",
            "description": "Mock infrastructure changes should not directly select product-facing XTS suites.",
            "how_to_identify": [
                "Path starts with test/mock/.",
                "Files provide fake or stub test infrastructure rather than production behavior.",
            ],
        },
        {
            "id": "ace_engine_mock_sources_mirror",
            "category": "non_product_test_support",
            "path_prefix": "foundation/arkui/ace_engine/test/mock/",
            "description": "Mirrored ace_engine mock sources are support code and should be excluded from XTS changed-file analysis.",
            "how_to_identify": [
                "Path starts with foundation/arkui/ace_engine/test/mock/.",
                "Files are mock/stub support code rather than product behavior.",
            ],
        },
        {
            "id": "generated_advanced_ui_assembled_wrappers",
            "category": "generated_wrapper_noise",
            "path_prefix": "foundation/arkui/ace_engine/advanced_ui_component_static/assembled_advanced_ui_component/",
            "description": "Generated assembled advanced-ui ETS wrappers import broad generic ArkUI symbols and can swamp the selector with unrelated XTS suites.",
            "how_to_identify": [
                "Path is under foundation/arkui/ace_engine/advanced_ui_component_static/assembled_advanced_ui_component/.",
                "File is an assembled @ohos.arkui.advanced.* ETS wrapper rather than the authored source under advanced_ui_component/<component>/source/.",
                "The wrapper re-exports or imports broad generic ArkUI component symbols such as Text, Image, Button, Scroll, Stack, and similar shared primitives.",
            ],
        },
    ]
}

IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
IMPORT_BINDING_RE = re.compile(
    r"""import\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""", re.S
)
DEFAULT_IMPORT_RE = re.compile(
    r"""import\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+['"]([^'"]+)['"]"""
)
IDENTIFIER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\s*\(""")
MEMBER_CALL_RE = re.compile(r"""\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
WORD_RE = re.compile(r"""\b[A-Za-z_][A-Za-z0-9_]{2,}\b""")
PARAM_TYPE_RE = re.compile(
    r"""[\(,]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Z][A-Za-z0-9_]*)\b"""
)
VAR_TYPE_RE = re.compile(
    r"""\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Z][A-Za-z0-9_]*)\b"""
)
MEMBER_ACCESS_RE = re.compile(
    r"""\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()"""
)
TYPED_OBJECT_LITERAL_RE = re.compile(
    r"""\b(?:const|let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*([A-Z][A-Za-z0-9_]*)\s*=\s*\{(?P<body>[^{}]*)\}""",
    re.S,
)
OBJECT_LITERAL_FIELD_RE = re.compile(r"""\b([A-Za-z_][A-Za-z0-9_]*)\s*:""")
OHOS_MODULE_RE = re.compile(r"""@ohos\.[A-Za-z0-9._]+""")
CPP_IDENTIFIER_RE = re.compile(r"""\b[A-Z][A-Za-z0-9_]{2,}\b""")
TYPE_MEMBER_CALL_RE = re.compile(
    r"""\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\("""
)
EXPORT_CLASS_RE = re.compile(r"""\bexport\s+class\s+([A-Z][A-Za-z0-9_]*)\b""")
EXPORT_INTERFACE_RE = re.compile(r"""\bexport\s+interface\s+([A-Z][A-Za-z0-9_]*)\b""")
EXPORT_INTERFACE_BLOCK_RE = re.compile(
    r"""\bexport\s+(?:declare\s+)?interface\s+([A-Z][A-Za-z0-9_]*)[^{]*\{(?P<body>.*?)\}""",
    re.S,
)
INTERFACE_PROPERTY_RE = re.compile(
    r"""^\s*(?:readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)\??\s*:\s*[^;{}]+;?\s*$""", re.M
)
INTERFACE_METHOD_RE = re.compile(
    r"""^\s*(?:readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*:\s*[^;]+;?\s*$""",
    re.M,
)
PUBLIC_METHOD_RE = re.compile(
    r"""\bpublic\s+(?:static\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\("""
)
UNIFIED_DIFF_HUNK_RE = re.compile(r"""^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@""", re.M)
GENERATED_ACCESSOR_NAMESPACE_RE = re.compile(
    r"""GeneratedModifier::([A-Za-z_][A-Za-z0-9_]*)Accessor\b"""
)
GET_ACCESSOR_RE = re.compile(r"""\bGet([A-Za-z_][A-Za-z0-9_]*)Accessor\s*\(""")
PEER_INCLUDE_RE = re.compile(r"#include\s+\"[^\"]*/([a-z0-9_]+)_peer\.h\"")
DYNAMIC_MODULE_RE = re.compile(r"""GetDynamicModule\("([A-Za-z0-9_]+)"\)""")
DECLARE_INTERFACE_RE = re.compile(r"""\bdeclare\s+interface\s+([A-Z][A-Za-z0-9_]*)\b""")
DECLARE_TYPE_RE = re.compile(
    r"""\bdeclare\s+(?:type|typedef)\s+([A-Z][A-Za-z0-9_]*)\b"""
)
DECLARE_FUNCTION_RE = re.compile(
    r"""\bdeclare\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("""
)
DECLARE_MODULE_RE = re.compile(r"""declare\s+module\s+['"]([^'"]+)['"]""")
TS_EXPORT_TYPE_RE = re.compile(
    r"""\bexport\s+(?:type|interface|class|const|function)\s+([A-Za-z_][A-Za-z0-9_]*)\b"""
)
CPP_FUNCTION_DEF_RE = re.compile(
    r"""(?:(?:const\s+)?(?:void|bool|int|auto|static|RefPtr|AceType|"""
    r"""std::(?:optional|string|pair|shared_ptr|unique_ptr)|"""
    r"""Color|Dimension|Offset|Size|Rect|PointF|Matrix4|Matrix44|"""
    r"""std::pair|std::tuple|std::function|"""
    r"""std::variant|std::monostate|std::any|"""
    r"""Template\s*<[^>]*>|"""
    r"""typename\s+\w+)\s+)?"""
    r"""(\b[A-Z][A-Za-z0-9_]{2,}\b)\s*\("""
)
CPP_METHOD_DEF_RE = re.compile(
    r"""(\b[A-Z][A-Za-z0-9_]{2,})::([A-Z][A-Za-z0-9_]{2,})\s*\("""
)
TYPED_ATTRIBUTE_MODIFIER_RE = re.compile(
    r"""AttributeModifier<([A-Za-z_][A-Za-z0-9_]*)Attribute>"""
)
EXTENDS_MODIFIER_RE = re.compile(r"""extends\s+([A-Za-z_][A-Za-z0-9_]*)Modifier\b""")
HOOK_CONTENT_MODIFIER_RE = re.compile(r"""\bhook([A-Za-z0-9]+)ContentModifier\b""")
IDL_CONTENT_MODIFIER_RE = re.compile(r"""\b(?:reset)?contentModifier([A-Za-z0-9]+)\b""")
CONTENT_MODIFIER_CUSTOM_RE = re.compile(r"""GetCustomModifier\("contentModifier"\)""")
INCLUDE_PATTERN_COMPONENT_RE = re.compile(r"""pattern/([^/]+)/""")
REASON_SYMBOL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\b""")
CONTENT_MODIFIER_NOISE = {
    "accessor",
    "builder",
    "commonview",
    "configuration",
    "content",
    "helper",
    "implementation",
    "modifier",
    "native",
}


def format_report(
    changed_files: list[Path],
    symbol_queries: list[str],
    code_queries: list[str],
    projects: list[TestProjectIndex],
    sdk_index: SdkIndex,
    content_index: ContentModifierIndex,
    mapping_config: MappingConfig,
    app_config: AppConfig,
    top_projects: int,
    top_files: int,
    device: str | None,
    xts_root: Path,
    sdk_api_root: Path,
    git_repo_root: Path,
    acts_out_root: Path | None,
    variants_mode: str,
    relevance_mode: str = "all",
    keep_per_signature: int = 0,
    cache_used: bool = False,
    debug_trace: bool = False,
    runtime_history_index: RuntimeHistoryIndex | None = None,
    requested_run_tool: str = "auto",
    progress_callback: Callable[[str], None] | None = None,
    api_lineage_map: ApiLineageMap | None = None,
    api_lineage_map_path: Path | None = None,
    changed_symbols: list[str] | None = None,
    changed_ranges_by_file: dict[Path, list[tuple[int, int]]] | None = None,
) -> dict:
    setup_started = time.perf_counter()
    built_artifacts = inspect_built_artifacts(REPO_ROOT, acts_out_root)
    built_artifact_index = load_built_artifact_index(REPO_ROOT, acts_out_root)
    product_build = inspect_product_build(
        REPO_ROOT, app_config.product_name, acts_out_root
    )
    report = {
        "repo_root": str(REPO_ROOT),
        "xts_root": str(xts_root),
        "sdk_api_root": str(sdk_api_root),
        "git_repo_root": str(git_repo_root),
        "acts_out_root": str(acts_out_root or (REPO_ROOT / "out/release/suites/acts")),
        "cache_file": str(app_config.cache_file) if app_config.cache_file else None,
        "ranking_rules_file": str(app_config.ranking_rules_file)
        if app_config.ranking_rules_file
        else None,
        "runtime_state_root": str(app_config.runtime_state_root)
        if app_config.runtime_state_root
        else None,
        "runtime_history_file": str(
            default_runtime_history_file(app_config.runtime_state_root)
        ),
        "hdc_path": str(app_config.hdc_path) if app_config.hdc_path else None,
        "hdc_endpoint": app_config.hdc_endpoint,
        "built_artifacts": built_artifacts,
        "built_artifact_index": built_artifact_index,
        "product_build": product_build,
        "cache_used": cache_used,
        "debug_trace": debug_trace,
        "variants_mode": variants_mode,
        "relevance_mode": relevance_mode,
        "excluded_inputs": [],
        "results": [],
        "symbol_queries": [],
        "code_queries": [],
        "unresolved_files": [],
        "coverage_gap": [],
        "affected_api_entities": [],
        "lineage_hops": [],
        "lineage_gaps": [],
        "source_only_consumers": [],
        "timings_ms": {},
    }
    if api_lineage_map is not None:
        report["api_lineage_map"] = {
            "schema_version": api_lineage_map.schema_version,
            "path": str(api_lineage_map_path) if api_lineage_map_path else None,
            "api_entity_count": len(api_lineage_map.api_to_sources),
            "source_count": len(api_lineage_map.source_to_apis),
            "consumer_file_count": len(api_lineage_map.consumer_file_to_apis),
            "consumer_project_count": len(api_lineage_map.consumer_project_to_apis),
            "source_only_consumer_file_count": sum(
                1
                for kind in api_lineage_map.consumer_file_kinds.values()
                if kind == "source_only"
            ),
            "source_only_consumer_project_count": sum(
                1
                for kind in api_lineage_map.consumer_project_kinds.values()
                if kind == "source_only"
            ),
        }
    coverage_candidates: list[dict[str, object]] = []
    report["timings_ms"]["report_setup"] = round(
        (time.perf_counter() - setup_started) * 1000, 3
    )
    selected_build_targets: list[str] = []
    changed_started = time.perf_counter()
    for changed_file in changed_files:
        if progress_callback:
            progress_callback(f"scoring changed file {repo_rel(changed_file)}")
        rel = repo_rel(changed_file)
        changed_ranges = list(
            (changed_ranges_by_file or {}).get(changed_file.resolve(), [])
        )
        signals = infer_signals(
            changed_file,
            sdk_index,
            content_index,
            mapping_config,
            changed_ranges=changed_ranges,
            api_lineage_map=api_lineage_map,
            repo_root=app_config.repo_root,
        )
        (
            affected_api_entities,
            file_level_affected_api_entities,
            derived_source_symbols,
        ) = apply_api_lineage_signals(
            changed_file,
            signals,
            api_lineage_map,
            app_config.repo_root,
            changed_symbols=changed_symbols,
            changed_ranges=changed_ranges,
        )
        source_only_consumers = collect_source_only_consumers(
            affected_api_entities,
            api_lineage_map,
            top_projects=top_projects,
            top_files=top_files,
        )
        effective_variants_mode = resolve_variants_mode(variants_mode, changed_file)
        source_profile = build_source_profile(
            "changed_file",
            rel,
            signals,
            raw_path=changed_file,
        )
        if affected_api_entities:
            source_profile["affected_api_entities"] = affected_api_entities
        if changed_symbols:
            source_profile["changed_symbols"] = sorted(changed_symbols)
        if changed_ranges:
            source_profile["changed_ranges"] = [
                f"{start}:{end}" for start, end in changed_ranges
            ]
        if derived_source_symbols:
            source_profile["derived_source_symbols"] = derived_source_symbols
        if file_level_affected_api_entities != affected_api_entities:
            source_profile["file_level_affected_api_entities"] = (
                file_level_affected_api_entities
            )
        project_results = []
        all_variant_projects, candidate_projects = select_candidate_projects(
            projects,
            signals,
            effective_variants_mode,
        )
        # Compute IDF for signal symbols (SCORING_PIPELINE.md bottleneck B2).
        # Symbols imported by >30% of candidate projects get 0 import/call
        # score — their evidence must come from type hints, member hints,
        # or typed field access instead.
        _symbol_df, _total_projects = compute_signal_symbol_df(
            candidate_projects, signals
        )
        signals["_symbol_df"] = _symbol_df
        signals["_total_projects"] = _total_projects
        _ubiquitous_symbols = {
            sym
            for sym, count in _symbol_df.items()
            if _total_projects > 0 and count > _total_projects * UBIQUITOUS_DF_FRACTION
        }
        # Propagate to score_file: ubiquitous type hint tokens get 0 points
        # for constructor/import evidence. Only deep evidence scores.
        signals["_ubiquitous_type_tokens"] = {
            compact_token(sym) for sym in _ubiquitous_symbols
        }
        for project in candidate_projects:
            score, project_reasons, file_hits = score_project(project, signals)
            if score <= 0:
                continue
            if not should_keep_project_for_surface(
                project, file_hits, effective_variants_mode
            ):
                continue
            hit_surfaces = sorted(matched_file_surfaces(file_hits))
            _nlx = project_has_non_lexical_evidence(
                project_reasons, file_hits, ubiquitous_symbols=_ubiquitous_symbols
            )
            family_profile = infer_project_family_profile(
                project, project_reasons, file_hits
            )
            type_hint_profile = infer_project_type_hint_profile(file_hits, signals)
            member_hint_profile = infer_project_member_hint_profile(file_hits, signals)
            _evidence_profile = {
                "direct_type_hint_keys": type_hint_profile["direct_type_hint_keys"],
                "direct_member_hint_keys": member_hint_profile[
                    "direct_member_hint_keys"
                ],
            }
            _bucket = candidate_bucket(score, _nlx, evidence_profile=_evidence_profile)
            _bucket, _gate_blockers = apply_must_run_gate(
                _bucket, score, _nlx, _evidence_profile, project_reasons,
            )
            scope_tier, specificity_score, scope_reasons = classify_project_scope(
                project,
                signals,
                project_reasons,
                file_hits,
            )
            project_entry = {
                # Only 'possible related' suites (call-only, no explicit import)
                # are eligible for coverage deduplication. Must-run and
                # high-confidence suites always pass through so that every
                # explicitly-tested suite is preserved regardless of keep_per_signature.
                "_coverage_sig": coverage_signature(
                    file_hits, project_path_key=project.path_key
                )
                if _bucket == "possible related"
                else None,
                "score": score,
                "specificity_score": specificity_score,
                "scope_tier": scope_tier,
                "scope_reasons": scope_reasons if debug_trace else scope_reasons[:3],
                "confidence": confidence(score),
                "bucket": _bucket,
                "bucket_gate_passed": not _gate_blockers,
                "bucket_gate_blockers": _gate_blockers,
                "variant": project.variant,
                "surface": project.surface,
                "supported_surfaces": sorted(project.supported_surfaces),
                "matched_surfaces": hit_surfaces,
                "project": project.relative_root,
                "test_json": project.test_json,
                "bundle_name": project.bundle_name,
                "driver_module_name": driver_module_name(
                    project.test_json, repo_root=app_config.repo_root
                ),
                "xdevice_module_name": infer_xdevice_module_name(
                    project.test_json, repo_root=app_config.repo_root
                ),
                "build_target": guess_build_target(project.relative_root),
                "driver_type": driver_type(
                    project.test_json, repo_root=app_config.repo_root
                ),
                "family_keys": family_profile["family_keys"],
                "direct_family_keys": family_profile["direct_family_keys"],
                "family_quality": family_profile["family_quality"],
                "family_representative_quality": family_profile[
                    "family_representative_quality"
                ],
                "capability_keys": family_profile["capability_keys"],
                "direct_capability_keys": family_profile["direct_capability_keys"],
                "capability_quality": family_profile["capability_quality"],
                "capability_representative_quality": family_profile[
                    "capability_representative_quality"
                ],
                "type_hint_keys": type_hint_profile["type_hint_keys"],
                "direct_type_hint_keys": type_hint_profile["direct_type_hint_keys"],
                "type_hint_focus_counts": type_hint_profile["focus_token_counts"],
                "member_hint_keys": member_hint_profile["member_hint_keys"],
                "direct_member_hint_keys": member_hint_profile[
                    "direct_member_hint_keys"
                ],
                "member_hint_focus_counts": member_hint_profile["focus_token_counts"],
                "focus_token_counts": family_profile["focus_token_counts"],
                "umbrella_penalty": family_profile["umbrella_penalty"],
                "reasons": project_reasons,
                "test_files": [
                    {
                        "score": file_score,
                        "file": test_file.relative_path,
                        "reasons": reasons if debug_trace else reasons[:6],
                    }
                    for file_score, test_file, reasons in file_hits[:top_files]
                ],
            }
            if debug_trace:
                project_entry["debug"] = {
                    "non_lexical_evidence": _nlx,
                    "matched_file_count": len(file_hits),
                    "project_reason_count": len(project_reasons),
                }
            project_entry["explanation"] = build_project_entry_explanation(project_entry)
            project_results.append(project_entry)
        # Abstention for broad infrastructure files: files in common/ or base_
        # paths that produce signals for many families AND match many projects
        # (e.g. base_pattern.cpp). Only keep projects with direct type/member
        # hint evidence to avoid flooding the output. Specific component files
        # (e.g. menu_item_pattern.cpp in pattern/menu/menu_item/) are NOT
        # subject to this filter even if they have many family tokens.
        _is_infrastructure_file = "/common/" in rel or rel.split("/")[-1].startswith(
            "base_"
        )
        _broad_family_count = len(signals.get("family_tokens", set()))
        if (
            _is_infrastructure_file
            and _broad_family_count >= 3
            and len(project_results) > 5
        ):
            project_results = [
                p
                for p in project_results
                if p.get("direct_type_hint_keys") or p.get("direct_member_hint_keys")
            ]
        sort_project_results(project_results)
        project_results = deduplicate_by_coverage_signature(
            project_results, keep_per_signature
        )
        filtered_project_results, relevance_summary = (
            filter_project_results_by_relevance(project_results, relevance_mode)
        )
        shown_project_results = (
            filtered_project_results
            if top_projects <= 0
            else filtered_project_results[:top_projects]
        )
        coverage_source = make_coverage_source("changed_file", rel)
        # Only include projects with meaningful scores in coverage candidates.
        # Projects with very low scores (path token overlap only) add noise
        # to the coverage planner without meaningful signal.
        COVERAGE_MIN_SCORE = 15
        coverage_candidates.extend(
            {
                "source": coverage_source,
                "source_profile": source_profile,
                "project_entry": item,
                "source_rank": index,
            }
            for index, item in enumerate(filtered_project_results, start=1)
            if item.get("score", 0) >= COVERAGE_MIN_SCORE
        )
        function_coverage = build_function_coverage_rows(
            changed_file=changed_file,
            derived_source_symbols=derived_source_symbols,
            affected_api_entities=affected_api_entities,
            api_lineage_map=api_lineage_map,
            repo_root=app_config.repo_root,
            project_results=filtered_project_results,
        )
        api_coverage = _build_coverage_gap_report(
            affected_api_entities,
            filtered_project_results,
            api_lineage_map,
        )
        uncovered_functions = [
            row["symbol"]
            for row in function_coverage
            if row.get("status") not in {"covered", "indirectly_covered"}
        ]
        uncovered_apis = api_coverage["not_covered"] + [
            e["api_entity"] for e in api_coverage["unresolved"]
        ]
        result_item = {
            "changed_file": rel,
            "changed_symbols": sorted(changed_symbols or []),
            "changed_ranges": [f"{start}:{end}" for start, end in changed_ranges],
            "derived_source_symbols": derived_source_symbols,
            "touched_source_functions": derived_source_symbols,
            "affected_api_entities": affected_api_entities,
            "affected_api_entity_details": build_affected_api_entity_details(
                affected_api_entities, sdk_index, api_lineage_map,
            ),
            "file_level_affected_api_entities": file_level_affected_api_entities,
            "api_coverage": api_coverage,
            "direct_covering_suites": api_coverage["direct_covering_suites"],
            "indirectly_covering_suites": api_coverage["indirectly_covering_suites"],
            "uncovered_functions": uncovered_functions,
            "uncovered_apis": uncovered_apis,
            "function_coverage": function_coverage,
            "source_only_consumers": source_only_consumers,
            "signals": {
                "modules": sorted(signals["modules"]),
                "weak_modules": sorted(signals.get("weak_modules", set())),
                "symbols": sorted(signals["symbols"]),
                "weak_symbols": sorted(signals.get("weak_symbols", set())),
                "project_hints": sorted(signals["project_hints"]),
                "method_hints": sorted(signals.get("method_hints", set())),
                "type_hints": sorted(signals.get("type_hints", set())),
                "member_hints": sorted(signals.get("member_hints", set())),
                "family_tokens": sorted(signals["family_tokens"]),
            },
            "coverage_families": source_profile["family_keys"],
            "coverage_capabilities": source_profile["capability_keys"],
            "effective_variants_mode": effective_variants_mode,
            "relevance_summary": {
                **relevance_summary,
                "shown": len(shown_project_results),
            },
            "projects": shown_project_results,
            "run_targets": [
                build_run_target_entry(
                    item,
                    repo_root=REPO_ROOT,
                    acts_out_root=acts_out_root,
                    built_artifact_index=built_artifact_index,
                    device=device,
                    hdc_path=app_config.hdc_path,
                    hdc_endpoint=app_config.hdc_endpoint,
                )
                for item in shown_project_results
            ],
        }
        if debug_trace:
            result_item["debug"] = {
                "candidate_project_count": len(candidate_projects),
                "candidate_projects_before_prefilter": len(all_variant_projects),
                "candidate_projects_after_prefilter": len(candidate_projects),
                "matched_project_count": len(filtered_project_results),
            }
        selected_build_targets.extend(
            guess_build_target(item["project"]) for item in shown_project_results
        )
        unresolved = build_unresolved_analysis(
            signals,
            project_results,
            affected_api_entities=affected_api_entities,
            derived_source_symbols=derived_source_symbols,
        )
        if debug_trace:
            result_item["unresolved_debug"] = unresolved
        if unresolved["reason"]:
            result_item["unresolved_reason"] = unresolved["reason"]
            if unresolved.get("reason_class"):
                result_item["unresolved_reason_class"] = unresolved["reason_class"]
            unresolved_entry = {
                "changed_file": rel,
                "reason": unresolved["reason"],
                "reason_class": unresolved.get("reason_class"),
                "signals": result_item["signals"],
            }
            if debug_trace:
                unresolved_entry["debug"] = unresolved
            report["unresolved_files"].append(unresolved_entry)
        for entity in affected_api_entities:
            report["lineage_hops"].append(f"{rel} -> {entity}")
            if entity not in report["affected_api_entities"]:
                report["affected_api_entities"].append(entity)
        if api_lineage_map is not None and not affected_api_entities:
            report["lineage_gaps"].append(rel)
        report["source_only_consumers"].extend(source_only_consumers)
        report["coverage_gap"].extend(api_coverage["not_covered"])
        result_item["explanation"] = build_result_explanation(result_item)
        report["results"].append(result_item)
    report["affected_api_entity_details"] = build_affected_api_entity_details(
        report["affected_api_entities"], sdk_index, api_lineage_map,
    )
    report["timings_ms"]["changed_file_analysis"] = round(
        (time.perf_counter() - changed_started) * 1000, 3
    )
    symbol_started = time.perf_counter()
    for query in symbol_queries:
        if progress_callback:
            progress_callback(f"scoring symbol query {query}")
        signals = build_query_signals(query, sdk_index, content_index, mapping_config)
        query_surface_intent = parse_query_surface_intent(query)
        effective_variants_mode = resolve_variants_mode(variants_mode)
        if variants_mode == "auto":
            effective_variants_mode = query_surface_intent.requested_surface
        source_profile = build_source_profile("symbol_query", query, signals)
        project_results = []
        all_variant_projects, candidate_projects = select_candidate_projects(
            projects,
            signals,
            effective_variants_mode,
        )
        # IDF for symbol queries (same logic as changed_file section)
        _sq_symbol_df, _sq_total_projects = compute_signal_symbol_df(
            candidate_projects, signals
        )
        signals["_symbol_df"] = _sq_symbol_df
        signals["_total_projects"] = _sq_total_projects
        _sq_ubiquitous_symbols = {
            sym
            for sym, count in _sq_symbol_df.items()
            if _sq_total_projects > 0
            and count > _sq_total_projects * UBIQUITOUS_DF_FRACTION
        }
        for project in candidate_projects:
            score, project_reasons, file_hits = score_project(project, signals)
            if score <= 0:
                continue
            if not should_keep_project_for_surface(
                project, file_hits, effective_variants_mode
            ):
                continue
            hit_surfaces = sorted(matched_file_surfaces(file_hits))
            _nlx = project_has_non_lexical_evidence(
                project_reasons, file_hits, ubiquitous_symbols=_sq_ubiquitous_symbols
            )
            family_profile = infer_project_family_profile(
                project, project_reasons, file_hits
            )
            type_hint_profile = infer_project_type_hint_profile(file_hits, signals)
            member_hint_profile = infer_project_member_hint_profile(file_hits, signals)
            _evidence_profile = {
                "direct_type_hint_keys": type_hint_profile["direct_type_hint_keys"],
                "direct_member_hint_keys": member_hint_profile[
                    "direct_member_hint_keys"
                ],
            }
            _bucket = candidate_bucket(score, _nlx, evidence_profile=_evidence_profile)
            _bucket, _gate_blockers = apply_must_run_gate(
                _bucket, score, _nlx, _evidence_profile, project_reasons,
            )
            scope_tier, specificity_score, scope_reasons = classify_project_scope(
                project,
                signals,
                project_reasons,
                file_hits,
            )
            project_entry = {
                "_coverage_sig": coverage_signature(
                    file_hits, project_path_key=project.path_key
                )
                if _bucket == "possible related"
                else None,
                "score": score,
                "specificity_score": specificity_score,
                "scope_tier": scope_tier,
                "scope_reasons": scope_reasons if debug_trace else scope_reasons[:3],
                "confidence": confidence(score),
                "bucket": _bucket,
                "bucket_gate_passed": not _gate_blockers,
                "bucket_gate_blockers": _gate_blockers,
                "variant": project.variant,
                "surface": project.surface,
                "supported_surfaces": sorted(project.supported_surfaces),
                "matched_surfaces": hit_surfaces,
                "project": project.relative_root,
                "test_json": project.test_json,
                "bundle_name": project.bundle_name,
                "driver_module_name": driver_module_name(
                    project.test_json, repo_root=app_config.repo_root
                ),
                "xdevice_module_name": infer_xdevice_module_name(
                    project.test_json, repo_root=app_config.repo_root
                ),
                "build_target": guess_build_target(project.relative_root),
                "driver_type": driver_type(
                    project.test_json, repo_root=app_config.repo_root
                ),
                "test_haps": parse_test_file_names(
                    project.test_json, repo_root=app_config.repo_root
                ),
                "family_keys": family_profile["family_keys"],
                "direct_family_keys": family_profile["direct_family_keys"],
                "family_quality": family_profile["family_quality"],
                "family_representative_quality": family_profile[
                    "family_representative_quality"
                ],
                "capability_keys": family_profile["capability_keys"],
                "direct_capability_keys": family_profile["direct_capability_keys"],
                "capability_quality": family_profile["capability_quality"],
                "capability_representative_quality": family_profile[
                    "capability_representative_quality"
                ],
                "type_hint_keys": type_hint_profile["type_hint_keys"],
                "direct_type_hint_keys": type_hint_profile["direct_type_hint_keys"],
                "type_hint_focus_counts": type_hint_profile["focus_token_counts"],
                "member_hint_keys": member_hint_profile["member_hint_keys"],
                "direct_member_hint_keys": member_hint_profile[
                    "direct_member_hint_keys"
                ],
                "member_hint_focus_counts": member_hint_profile["focus_token_counts"],
                "focus_token_counts": family_profile["focus_token_counts"],
                "umbrella_penalty": family_profile["umbrella_penalty"],
                "test_files": [
                    {
                        "score": file_score,
                        "file": test_file.relative_path,
                        "reasons": reasons if debug_trace else reasons[:6],
                    }
                    for file_score, test_file, reasons in file_hits[:top_files]
                ],
            }
            if debug_trace:
                project_entry["reasons"] = project_reasons
                project_entry["debug"] = {
                    "non_lexical_evidence": _nlx,
                    "matched_file_count": len(file_hits),
                    "project_reason_count": len(project_reasons),
                }
            project_entry["explanation"] = build_project_entry_explanation(project_entry)
            project_results.append(project_entry)
        sort_project_results(project_results)
        project_results = deduplicate_by_coverage_signature(
            project_results, keep_per_signature
        )
        filtered_project_results, relevance_summary = (
            filter_project_results_by_relevance(project_results, relevance_mode)
        )
        display_project_results = restrict_explicit_surface_projects(
            filtered_project_results,
            query_surface_intent.requested_surface,
            explicit_surface_query=bool(query_surface_intent.reasons),
        )
        shown_project_results = (
            display_project_results
            if top_projects <= 0
            else display_project_results[:top_projects]
        )
        if effective_variants_mode == "both":
            shown_project_results = diversify_symbol_query_projects(
                display_project_results, top_projects
            )
        coverage_source = make_coverage_source("symbol_query", query)
        coverage_candidates.extend(
            {
                "source": coverage_source,
                "source_profile": source_profile,
                "project_entry": item,
                "source_rank": index,
            }
            for index, item in enumerate(display_project_results, start=1)
        )
        symbol_item = {
            "query": query,
            "signals": {
                "modules": sorted(signals["modules"]),
                "weak_modules": sorted(signals.get("weak_modules", set())),
                "symbols": sorted(signals["symbols"]),
                "weak_symbols": sorted(signals.get("weak_symbols", set())),
                "project_hints": sorted(signals["project_hints"]),
                "method_hints": sorted(signals.get("method_hints", set())),
                "type_hints": sorted(signals.get("type_hints", set())),
                "member_hints": sorted(signals.get("member_hints", set())),
                "family_tokens": sorted(signals["family_tokens"]),
            },
            "coverage_families": source_profile["family_keys"],
            "coverage_capabilities": source_profile["capability_keys"],
            "code_search_evidence": explain_symbol_query_sources(query, xts_root),
            "effective_variants_mode": effective_variants_mode,
            "relevance_summary": {
                **relevance_summary,
                "total_after": len(display_project_results),
                "filtered_out": len(project_results) - len(display_project_results),
                "shown": len(shown_project_results),
            },
            "projects": shown_project_results,
            "run_targets": [
                build_run_target_entry(
                    item,
                    repo_root=REPO_ROOT,
                    acts_out_root=acts_out_root,
                    built_artifact_index=built_artifact_index,
                    device=device,
                    hdc_path=app_config.hdc_path,
                    hdc_endpoint=app_config.hdc_endpoint,
                )
                for item in shown_project_results
            ],
        }
        if debug_trace:
            symbol_item["debug"] = {
                "candidate_project_count": len(candidate_projects),
                "candidate_projects_before_prefilter": len(all_variant_projects),
                "candidate_projects_after_prefilter": len(candidate_projects),
                "matched_project_count": len(display_project_results),
            }
        symbol_item["explanation"] = build_result_explanation(symbol_item)
        report["symbol_queries"].append(symbol_item)
        selected_build_targets.extend(
            guess_build_target(item["project"]) for item in shown_project_results
        )
    report["timings_ms"]["symbol_query_analysis"] = round(
        (time.perf_counter() - symbol_started) * 1000, 3
    )
    code_root = git_repo_root
    code_started = time.perf_counter()
    for query in code_queries:
        if progress_callback:
            progress_callback(f"searching code query {query}")
        report["code_queries"].append(
            {
                "query": query,
                "matches": search_code_matches(query, code_root),
            }
        )
    report["timings_ms"]["code_query_analysis"] = round(
        (time.perf_counter() - code_started) * 1000, 3
    )
    report["coverage_recommendations"] = build_global_coverage_recommendations(
        coverage_candidates,
        repo_root=REPO_ROOT,
        acts_out_root=acts_out_root,
        built_artifact_index=built_artifact_index,
        device=device,
    )
    if runtime_history_index is not None:
        annotate_report_runtime_estimates(
            report, runtime_history_index, requested_tool=requested_run_tool
        )
    if progress_callback:
        progress_callback("assembling build guidance")
    guidance_started = time.perf_counter()
    guidance = build_guidance(
        REPO_ROOT,
        report["built_artifacts"],
        report["product_build"],
        app_config,
        selected_build_targets,
    )
    report["timings_ms"]["build_guidance"] = round(
        (time.perf_counter() - guidance_started) * 1000, 3
    )
    if guidance:
        report["build_guidance"] = guidance
    report["timings_ms"]["report_total"] = round(sum(report["timings_ms"].values()), 3)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    progress_group = parser.add_mutually_exclusive_group()
    json_group = parser.add_mutually_exclusive_group()
    parser.add_argument("--config", help="JSON config file.")
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="Changed file path. Can be repeated.",
    )
    parser.add_argument(
        "--changed-symbol",
        action="append",
        default=[],
        help="Optional changed symbol/function name used to narrow affected APIs for changed-file analysis. Can be repeated.",
    )
    parser.add_argument(
        "--changed-range",
        action="append",
        default=[],
        help="Optional changed line range used to derive touched source symbols, in 'start:end' or 'path:start:end' form. Can be repeated.",
    )
    parser.add_argument(
        "--changed-lines",
        action="append",
        default=[],
        help=(
            "Changed hunk specified as PATH:START-END (1-based, inclusive). "
            "Requires --use-graph-resolver. "
            "Resolves changed line range to overlapping source symbols via an "
            "externally-supplied symbol index, then queries the graph for tests. "
            "Example: foundation/arkui/ace_engine/frameworks/core/components_ng/"
            "pattern/button/button_model_ng.cpp:10-50. Can be repeated."
        ),
    )
    parser.add_argument(
        "--symbol-query",
        action="append",
        default=[],
        help="Find XTS tests by component/symbol name, e.g. ButtonModifier.",
    )
    parser.add_argument(
        "--code-query",
        action="append",
        default=[],
        help="Find code files by keyword, e.g. ButtonModifier.",
    )
    parser.add_argument(
        "--changed-files-from", help="Text file with one changed file path per line."
    )
    parser.add_argument(
        "--git-diff", help="Optional git diff ref, for example HEAD~1..HEAD."
    )
    parser.add_argument("--git-root", help="Git root to use with --git-diff.")
    parser.add_argument(
        "--pr-url",
        help="GitCode/CodeHub PR or MR URL, for example https://gitcode.com/.../pull/82225 or https://codehub.example.com/.../merge_requests/12",
    )
    parser.add_argument("--pr-number", help="Git host PR/MR number.")
    parser.add_argument(
        "--pr-source",
        choices=PR_SOURCE_CHOICES,
        default="auto",
        help="How to resolve PR/MR changed files: auto prefers the detected host API when token/config is available, api forces API mode, git forces git-fetch mode.",
    )
    parser.add_argument("--git-remote", help="Git remote for PR fetching.")
    parser.add_argument(
        "--git-base-branch", help="Base branch for PR diff. Default: master."
    )
    parser.add_argument(
        "--git-host-kind",
        choices=GIT_HOST_KIND_CHOICES,
        default="auto",
        help="PR API host kind. auto detects from the PR URL and falls back to GitCode-compatible behavior.",
    )
    parser.add_argument(
        "--git-host-url",
        help="Git host base URL for API mode, for example https://gitcode.com or https://codehub.example.com",
    )
    parser.add_argument("--git-host-token", help="Git host access token for API mode.")
    parser.add_argument(
        "--gitcode-api-url",
        help="Deprecated alias for --git-host-url, kept for backward compatibility.",
    )
    parser.add_argument(
        "--gitcode-token",
        help="Deprecated alias for --git-host-token, kept for backward compatibility.",
    )
    parser.add_argument(
        "--git-host-config",
        help="Path to INI config with [gitcode] or [codehub] token/url entries.",
    )
    parser.add_argument(
        "--repo-root",
        help="Explicit OHOS workspace root. By default the CLI auto-discovers the workspace, including sibling ohos_master trees.",
    )
    parser.add_argument("--xts-root", help="Absolute or relative path to XTS root.")
    parser.add_argument(
        "--sdk-api-root", help="Absolute or relative path to SDK api root."
    )
    parser.add_argument(
        "--acts-out-root",
        help="Built ACTS output root, for xdevice command generation.",
    )
    parser.add_argument(
        "--path-rules-file",
        help="Optional JSON file with path and alias mapping rules.",
    )
    parser.add_argument(
        "--composite-mappings-file",
        help="Optional JSON file with multi-component mapping rules.",
    )
    parser.add_argument(
        "--ranking-rules-file",
        help="Optional JSON file with family-group, generic-token, umbrella, and planner ranking rules.",
    )
    parser.add_argument(
        "--changed-file-exclusions-file",
        help="Optional JSON file with changed-file path prefixes to exclude from XTS analysis.",
    )
    parser.add_argument(
        "--device",
        help="Optional device serial/connect key visible from the selected HDC server.",
    )
    parser.add_argument(
        "--devices",
        action="append",
        default=[],
        help="Comma-separated device serial list for command generation and execution.",
    )
    parser.add_argument(
        "--devices-from",
        help="File with one device serial per line (comments with # are ignored).",
    )
    parser.add_argument(
        "--server-host",
        help="Optional remote Linux execution host for wrapper-driven `ohos xts ...` flows.",
    )
    parser.add_argument(
        "--server-user",
        help="Optional remote Linux user for --server-host. Default: current user on the caller side.",
    )
    parser.add_argument(
        "--product-name", help="Product name for build guidance. Default: rk3568."
    )
    parser.add_argument(
        "--system-size", help="System size for build guidance. Default: standard."
    )
    parser.add_argument(
        "--xts-suitetype",
        help="Optional xts_suitetype for build guidance, for example hap_static or hap_dynamic.",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Immediately execute selected run targets after report generation.",
    )
    parser.add_argument(
        "--from-report",
        help="Reuse a previously saved selector JSON report instead of recomputing selection.",
    )
    parser.add_argument(
        "--last-report",
        action="store_true",
        help="Reuse the latest saved selector JSON report from the run store.",
    )
    parser.add_argument(
        "--run-label",
        help="Optional label for storing this planned/executed selector run, for example baseline or v1.",
    )
    parser.add_argument(
        "--run-store-root",
        help="Directory used to persist labeled selector runs. Default: <selector_repo>/.runs",
    )
    parser.add_argument(
        "--runtime-state-root",
        help="Shared runtime state directory for device locks and runtime history. Default: /tmp/arkui_xts_selector_state",
    )
    parser.add_argument(
        "--daily-build-tag",
        help="Daily build tag for prebuilt suites, for example 20260403_120242.",
    )
    parser.add_argument(
        "--daily-component",
        help=(
            "Daily build component name for prebuilt ACTS packages, for example "
            f"{DEFAULT_DAILY_COMPONENT}. Plain board aliases such as dayu200 are "
            "still accepted and will first try <board>_Dyn_Sta_XTS."
        ),
    )
    parser.add_argument(
        "--daily-branch", help="Daily build branch filter. Default: master."
    )
    parser.add_argument(
        "--daily-date",
        help="Daily build date in YYYYMMDD or YYYY-MM-DD. Defaults to the date derived from --daily-build-tag.",
    )
    parser.add_argument(
        "--daily-cache-root",
        help=f"Cache directory for downloaded/extracted daily full packages. Default: {DEFAULT_DAILY_CACHE_ROOT}",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick mode: skip daily download and use only local ACTS artifacts. Use when you have a built tree or want fast analysis with reduced accuracy.",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run benchmark cases from canonical corpus and exit with code 1 if any fail.",
    )
    parser.add_argument(
        "--benchmark-fixtures-dir",
        help="Directory containing canonical corpus benchmark fixtures. Default: tests/fixtures/canonical_corpus",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Enable inspect mode for querying the persisted dependency/lineage map.",
    )
    parser.add_argument(
        "--inspect-api-entity",
        help="Inspect mode: show all source files, consumers, and projects that reference this API entity.",
    )
    parser.add_argument(
        "--inspect-source-file",
        help="Inspect mode: show all API entities and consumers reachable from this source file.",
    )
    parser.add_argument(
        "--inspect-consumer-project",
        help="Inspect mode: show all API entities and source files reachable from this consumer project.",
    )
    parser.add_argument(
        "--download-daily-tests",
        action="store_true",
        help="Download and extract the daily XTS package described by --daily-* options, then exit.",
    )
    parser.add_argument(
        "--download-daily-sdk",
        action="store_true",
        help="Download and extract the daily SDK package described by --sdk-* options, then exit.",
    )
    parser.add_argument(
        "--download-daily-firmware",
        action="store_true",
        help="Download and extract the daily firmware image package described by --firmware-* options, then exit.",
    )
    parser.add_argument(
        "--flash-daily-firmware",
        action="store_true",
        help="Download/extract the daily firmware image package described by --firmware-* options and flash it to the connected device, then exit.",
    )
    parser.add_argument(
        "--sdk-build-tag", help="Daily SDK build tag, for example 20260404_120537."
    )
    parser.add_argument(
        "--sdk-component",
        help=f"Daily SDK component name. Default: {DEFAULT_SDK_COMPONENT}.",
    )
    parser.add_argument(
        "--sdk-branch", help="Daily SDK branch filter. Default: master."
    )
    parser.add_argument(
        "--sdk-date",
        help="Daily SDK build date in YYYYMMDD or YYYY-MM-DD. Defaults to the date derived from --sdk-build-tag.",
    )
    parser.add_argument(
        "--sdk-cache-root",
        help=f"Cache directory for downloaded/extracted daily SDK packages. Default: {DEFAULT_SDK_CACHE_ROOT}",
    )
    parser.add_argument(
        "--firmware-build-tag",
        help="Daily firmware build tag, for example 20260404_120244.",
    )
    parser.add_argument(
        "--firmware-component",
        help=f"Daily firmware component name. Default: {DEFAULT_FIRMWARE_COMPONENT}.",
    )
    parser.add_argument(
        "--firmware-branch", help="Daily firmware branch filter. Default: master."
    )
    parser.add_argument(
        "--firmware-date",
        help="Daily firmware build date in YYYYMMDD or YYYY-MM-DD. Defaults to the date derived from --firmware-build-tag.",
    )
    parser.add_argument(
        "--firmware-cache-root",
        help=f"Cache directory for downloaded/extracted daily firmware packages. Default: {DEFAULT_FIRMWARE_CACHE_ROOT}",
    )
    parser.add_argument(
        "--flash-firmware-path",
        help="Path to an unpacked local firmware image bundle root, or a parent directory containing one, to flash directly.",
    )
    parser.add_argument(
        "--list-daily-tags",
        metavar="TYPE",
        help="List recent daily build tags and exit. TYPE: tests (default), sdk, firmware.",
    )
    parser.add_argument(
        "--list-tags-count",
        type=int,
        default=10,
        metavar="N",
        help="Number of tags to show with --list-daily-tags. Default: 10.",
    )
    parser.add_argument(
        "--list-tags-after",
        metavar="DATE",
        help="Only list tags on or after this date (YYYYMMDD or YYYY-MM-DD).",
    )
    parser.add_argument(
        "--list-tags-before",
        metavar="DATE",
        help="Only list tags on or before this date (YYYYMMDD or YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--list-tags-lookback",
        type=int,
        default=30,
        metavar="DAYS",
        help="How many days back to search when listing tags. Default: 30.",
    )
    parser.add_argument(
        "--flash-py-path",
        help="Path to the Rockchip flash.py helper used for board flashing.",
    )
    parser.add_argument(
        "--hdc-path",
        help="Path to hdc used for generated commands, execution preflight, and flashing.",
    )
    parser.add_argument(
        "--hdc-endpoint",
        help="Remote HDC server endpoint HOST:PORT used for generated commands, preflight, and execution.",
    )
    parser.add_argument(
        "--run-tool",
        choices=RUN_TOOL_CHOICES,
        default="auto",
        help="Execution tool to use for --run-now. Default: auto.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        default=False,
        help="Skip automatic HAP installation before aa_test execution. Use when HAPs are already installed on the device.",
    )
    parser.add_argument(
        "--run-priority",
        choices=RUN_PRIORITY_CHOICES,
        default="recommended",
        help="Execution priority for --run-now. required = strongest unique coverage, recommended = required plus additional unique coverage, all = include duplicate fallback coverage.",
    )
    parser.add_argument(
        "--shard-mode",
        choices=SHARD_MODE_CHOICES,
        default="mirror",
        help="Execution distribution mode. mirror = all selected targets on every device; split = shard unique targets across devices.",
    )
    parser.add_argument(
        "--parallel-jobs",
        type=int,
        default=1,
        help="Maximum number of device queues to execute in parallel for --run-now. Same-device commands stay sequential.",
    )
    parser.add_argument(
        "--device-lock-timeout",
        type=float,
        default=30.0,
        help="Wait up to N seconds for an exclusive device lock before blocking that device queue. Default: 30.",
    )
    parser.add_argument(
        "--run-top-targets",
        type=int,
        default=0,
        help="Execute at most N unique run targets. 0 = all.",
    )
    parser.add_argument(
        "--run-test-name",
        action="append",
        default=[],
        help="Run only the named suite. Can be repeated. Matches names and aliases from selected_tests.json.",
    )
    parser.add_argument(
        "--run-test-names-file",
        help="Text file with one or comma-separated suite names per line for manual run selection.",
    )
    parser.add_argument(
        "--run-timeout",
        type=float,
        default=0.0,
        help="Per-command timeout in seconds for --run-now. 0 = disabled.",
    )
    parser.add_argument(
        "--relevance-mode",
        choices=RELEVANCE_MODE_CHOICES,
        default="all",
        help="Filter ranked projects by relevance. all = current behavior, balanced = must-run + high-confidence, strict = must-run only.",
    )
    parser.add_argument(
        "--variants",
        choices=["auto", "static", "dynamic", "both"],
        default="auto",
        help="Filter returned candidates by variant. Default: auto.",
    )
    parser.add_argument(
        "--top-projects",
        type=int,
        default=12,
        help="Number of ranked suites to display per source. 0 = show all. Default: 12.",
    )
    parser.add_argument("--top-files", type=int, default=5)
    parser.add_argument(
        "--keep-per-signature",
        type=int,
        default=0,
        help=(
            "Deduplicate output by coverage signature. "
            "Keep at most N projects that provide identical evidence for the query. "
            "0 = disabled (default). 2 = recommended: keeps 2 representatives per "
            "coverage pattern as a guard against flaky tests."
        ),
    )
    parser.add_argument("--cache-file", default=str(DEFAULT_CACHE_FILE))
    parser.add_argument(
        "--debug-trace",
        action="store_true",
        help="Include timing metadata and extra ranking diagnostics in the report.",
    )
    parser.add_argument(
        "--show-source-evidence",
        action="store_true",
        help="Show per-source Changed File evidence blocks even in combined multi-source PR/MR reports.",
    )
    progress_group.add_argument(
        "--progress",
        action="store_true",
        help="Explicitly enable phase-progress messages (default behavior).",
    )
    progress_group.add_argument(
        "--no-progress", action="store_true", help="Disable phase-progress messages."
    )
    parser.add_argument("--no-cache", action="store_true")
    json_group.add_argument(
        "--json",
        action="store_true",
        help="Write machine-readable JSON to stdout instead of the default report file.",
    )
    json_group.add_argument(
        "--json-out", help="Write machine-readable JSON to the specified file path."
    )

    # Add subcommands for specialized indexing operations
    subparsers = parser.add_subparsers(
        dest="command", help="Specialized indexing commands"
    )

    trace_parser = subparsers.add_parser(
        "trace", help="Trace a source symbol to consumer tests"
    )
    trace_parser.add_argument(
        "target", help="File path and symbol, e.g. path/to/file.cpp:SetRole"
    )
    trace_parser.add_argument("--repo-root", help="OHOS workspace root")
    trace_parser.add_argument("--sdk-root", help="SDK root directory")

    explain_parser = subparsers.add_parser(
        "explain", help="List API entities that a test project covers"
    )
    explain_parser.add_argument(
        "test_project", help="Path to the test project directory"
    )

    batch_parser = subparsers.add_parser(
        "validate-batch",
        help="In-process batch validation: load indices once, resolve multiple PRs",
    )
    batch_parser.add_argument(
        "--pr-list-file", required=True, help="File with PR URLs (one per line)"
    )
    batch_parser.add_argument(
        "--sample-size", type=int, default=None, help="Limit to first N PRs"
    )
    batch_parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Per-PR timeout in seconds (default: 300)",
    )
    batch_parser.add_argument(
        "--output", default="local/batch_results.json", help="Output JSON path"
    )
    batch_parser.add_argument(
        "--cache-dir",
        default="local/pr_cache",
        help="Cache directory for per-PR results",
    )
    batch_parser.add_argument("--repo-root", default=None, help="OHOS workspace root")
    batch_parser.add_argument("--xts-root", default=None, help="XTS tests root")
    batch_parser.add_argument("--sdk-api-root", default=None, help="SDK API root")
    batch_parser.add_argument(
        "--git-host-config", default=None, help="Git host config file (INI with token)"
    )
    batch_parser.add_argument(
        "--workers",
        type=int,
        default=80,
        help="Max parallel workers (default: 80, clamped to cpu_count)",
    )
    batch_parser.add_argument(
        "--pr-api-cache-dir",
        default="local/pr_api_cache",
        help="Cache directory for raw PR API responses",
    )
    batch_parser.add_argument(
        "--pr-cache-mode",
        choices=["read-write", "read-only", "refresh"],
        default="read-write",
        help="PR API cache mode (default: read-write)",
    )
    batch_parser.add_argument(
        "--allow-expired-overrides",
        action="store_true",
        help="Allow expired manual overrides (default: CI fails on expired)",
    )

    parser.add_argument(
        "--use-graph-resolver",
        action="store_true",
        help="Add graph-based selection results in JSON under 'graph_selection' key. Experimental, default off.",
    )

    # Audit subcommand (Phase 11, T11.15)
    audit_parser = subparsers.add_parser("audit", help="Audit log operations")
    audit_sub = audit_parser.add_subparsers(dest="audit_command")

    fn_rate_parser = audit_sub.add_parser(
        "fn-rate", help="Compute false-negative rate from audit log"
    )
    fn_rate_parser.add_argument(
        "--days", type=int, default=30, help="Analyze last N days (default: 30)"
    )
    fn_rate_parser.add_argument(
        "--audit-dir", default=None, help="Audit log directory (default: .runs/audit/)"
    )

    record_parser = audit_sub.add_parser(
        "record", help="Record a PR run result to audit log"
    )
    record_parser.add_argument("--pr-number", type=int, required=True, help="PR number")
    record_parser.add_argument(
        "--selected", nargs="*", default=[], help="Selected test targets"
    )
    record_parser.add_argument(
        "--ran", nargs="*", default=[], help="Actually executed test targets"
    )
    record_parser.add_argument(
        "--failed", nargs="*", default=[], help="Failed test targets"
    )
    record_parser.add_argument(
        "--selector-report", default=None, help="Path to selector report JSON"
    )
    record_parser.add_argument("--audit-dir", default=None, help="Audit log directory")

    # Oracle extract subcommand (Wave 4, W1.5)
    oracle_parser = subparsers.add_parser(
        "oracle-extract", help="Extract ground-truth API changes from PR diff"
    )
    oracle_parser.add_argument("--pr-number", type=int, required=True, help="PR number")
    oracle_parser.add_argument("--repo-root", required=True, help="OHOS workspace root")
    oracle_parser.add_argument(
        "--cache-dir", default="local/pr_api_cache", help="PR API cache directory"
    )
    oracle_parser.add_argument(
        "--git-host-config", default=None, help="Git host config file"
    )
    oracle_parser.add_argument(
        "--output", default=None, help="Output JSON path (default: stdout)"
    )

    # Coverage eval subcommand (Wave 4, W2.6)
    cov_parser = subparsers.add_parser(
        "coverage-eval", help="Evaluate selector coverage against golden fixtures"
    )
    cov_parser.add_argument(
        "--batch-results", required=True, help="Path to batch_results.json"
    )
    cov_parser.add_argument(
        "--golden", required=True, help="Path to golden fixtures JSON"
    )
    cov_parser.add_argument(
        "--baseline",
        default=None,
        help="Path to baseline metrics JSON (for regression gate)",
    )
    cov_parser.add_argument("--output", default=None, help="Output JSON path")
    cov_parser.add_argument(
        "--report-md", default=None, help="Output markdown report path"
    )

    return parser.parse_args()


def load_app_config(args: argparse.Namespace) -> AppConfig:
    selector_repo_root = PROJECT_ROOT
    cfg = (
        load_json_file(
            resolve_path(args.config, selector_repo_root, selector_repo_root)
        )
        if args.config
        else {}
    )
    repo_root = discover_repo_root(
        explicit_root=args.repo_root or cfg.get("repo_root"),
        selector_repo_root=selector_repo_root,
    )
    git_host_kind = normalize_git_host_kind(
        args.git_host_kind or cfg.get("git_host_kind")
    )
    git_host_config_value = args.git_host_config or cfg.get("git_host_config")
    git_host_config_path = (
        resolve_path(git_host_config_value, repo_root, repo_root)
        if git_host_config_value
        else None
    )
    ini_url, ini_token = load_ini_git_host_config(
        git_host_config_value,
        repo_root,
        git_host_kind if git_host_kind != "auto" else "gitcode",
    )
    xts_root = resolve_path(
        args.xts_root or cfg.get("xts_root"), default_xts_root(repo_root), repo_root
    )
    sdk_api_root = resolve_path(
        args.sdk_api_root or cfg.get("sdk_api_root"),
        default_sdk_api_root(repo_root),
        repo_root,
    )
    git_repo_root = resolve_path(
        args.git_root or cfg.get("git_repo_root"),
        default_git_repo_root(repo_root),
        repo_root,
    )
    git_remote = args.git_remote or cfg.get("git_remote") or "gitcode"
    git_base_branch = args.git_base_branch or cfg.get("git_base_branch") or "master"
    config_devices_raw = cfg.get("devices", [])
    if isinstance(config_devices_raw, list):
        config_devices = [str(item) for item in config_devices_raw]
    elif isinstance(config_devices_raw, str):
        config_devices = [config_devices_raw]
    else:
        config_devices = []
    devices_from_value = args.devices_from or cfg.get("devices_from")
    devices_from_path = (
        resolve_path(devices_from_value, repo_root, repo_root)
        if devices_from_value
        else None
    )
    devices = resolve_devices(
        cli_devices=args.devices,
        cli_device=args.device,
        devices_from_path=devices_from_path,
        config_devices=config_devices,
        config_device=cfg.get("device"),
    )
    device = devices[0] if devices else None
    server_host = str(args.server_host or cfg.get("server_host") or "").strip() or None
    server_user = str(args.server_user or cfg.get("server_user") or "").strip() or None
    product_name = args.product_name or cfg.get("product_name") or "rk3568"
    system_size = args.system_size or cfg.get("system_size") or "standard"
    xts_suitetype = args.xts_suitetype or cfg.get("xts_suitetype")
    acts_out_root = resolve_path(
        args.acts_out_root or cfg.get("acts_out_root"),
        default_acts_out_root(repo_root),
        repo_root,
    )
    path_rules_file = (
        resolve_path(
            args.path_rules_file or cfg.get("path_rules_file"),
            default_path_rules_file() or repo_root,
            repo_root,
        )
        if (
            args.path_rules_file
            or cfg.get("path_rules_file")
            or default_path_rules_file()
        )
        else None
    )
    composite_mappings_file = (
        resolve_path(
            args.composite_mappings_file or cfg.get("composite_mappings_file"),
            default_composite_mappings_file() or repo_root,
            repo_root,
        )
        if (
            args.composite_mappings_file
            or cfg.get("composite_mappings_file")
            or default_composite_mappings_file()
        )
        else None
    )
    ranking_rules_file = (
        resolve_path(
            args.ranking_rules_file or cfg.get("ranking_rules_file"),
            default_ranking_rules_file() or repo_root,
            repo_root,
        )
        if (
            args.ranking_rules_file
            or cfg.get("ranking_rules_file")
            or default_ranking_rules_file()
        )
        else None
    )
    changed_file_exclusions_file = (
        resolve_path(
            args.changed_file_exclusions_file
            or cfg.get("changed_file_exclusions_file"),
            default_changed_file_exclusions_file() or repo_root,
            repo_root,
        )
        if (
            args.changed_file_exclusions_file
            or cfg.get("changed_file_exclusions_file")
            or default_changed_file_exclusions_file()
        )
        else None
    )
    run_store_root = resolve_path(
        args.run_store_root or cfg.get("run_store_root"),
        default_run_store_root(selector_repo_root),
        selector_repo_root,
    )
    runtime_state_root = resolve_path(
        args.runtime_state_root or cfg.get("runtime_state_root"),
        default_runtime_state_root(selector_repo_root),
        selector_repo_root,
    )
    daily_cache_root = resolve_path(
        args.daily_cache_root or cfg.get("daily_cache_root"),
        DEFAULT_DAILY_CACHE_ROOT,
        selector_repo_root,
    )
    sdk_cache_root = resolve_path(
        args.sdk_cache_root or cfg.get("sdk_cache_root") or str(DEFAULT_SDK_CACHE_ROOT),
        DEFAULT_SDK_CACHE_ROOT,
        selector_repo_root,
    )
    firmware_cache_root = resolve_path(
        args.firmware_cache_root
        or cfg.get("firmware_cache_root")
        or str(DEFAULT_FIRMWARE_CACHE_ROOT),
        DEFAULT_FIRMWARE_CACHE_ROOT,
        selector_repo_root,
    )
    flash_py_path = (
        resolve_path(
            args.flash_py_path or cfg.get("flash_py_path"),
            selector_repo_root,
            selector_repo_root,
        )
        if (args.flash_py_path or cfg.get("flash_py_path"))
        else None
    )
    flash_firmware_path = (
        resolve_path(
            args.flash_firmware_path or cfg.get("flash_firmware_path"),
            selector_repo_root,
            selector_repo_root,
        )
        if (args.flash_firmware_path or cfg.get("flash_firmware_path"))
        else None
    )
    hdc_path = (
        resolve_path(
            args.hdc_path or cfg.get("hdc_path"),
            selector_repo_root,
            selector_repo_root,
        )
        if (args.hdc_path or cfg.get("hdc_path"))
        else None
    )
    hdc_endpoint = args.hdc_endpoint or cfg.get("hdc_endpoint")
    git_host_api_url = (
        args.git_host_url
        or cfg.get("git_host_api_url")
        or args.gitcode_api_url
        or cfg.get("gitcode_api_url")
        or ini_url
    )
    git_host_token = (
        args.git_host_token
        or cfg.get("git_host_token")
        or args.gitcode_token
        or cfg.get("gitcode_token")
        or ini_token
    )
    gitcode_api_url = args.gitcode_api_url or cfg.get("gitcode_api_url") or ini_url
    gitcode_token = args.gitcode_token or cfg.get("gitcode_token") or ini_token
    cache_value = None if args.no_cache else (args.cache_file or cfg.get("cache_file"))
    if args.no_cache:
        cache_file = None
    elif cache_value and cache_value != str(DEFAULT_CACHE_FILE):
        cache_file = resolve_path(cache_value, DEFAULT_CACHE_FILE, repo_root)
    else:
        cache_file = default_cache_path(xts_root)
    return AppConfig(
        repo_root=repo_root,
        xts_root=xts_root,
        sdk_api_root=sdk_api_root,
        cache_file=cache_file,
        git_repo_root=git_repo_root,
        git_remote=git_remote,
        git_base_branch=git_base_branch,
        git_host_kind=git_host_kind,
        git_host_api_url=git_host_api_url,
        git_host_token=git_host_token,
        git_host_config_path=git_host_config_path,
        server_host=server_host,
        server_user=server_user,
        device=device,
        devices=devices,
        gitcode_api_url=gitcode_api_url,
        gitcode_token=gitcode_token,
        acts_out_root=acts_out_root,
        path_rules_file=path_rules_file,
        composite_mappings_file=composite_mappings_file,
        ranking_rules_file=ranking_rules_file,
        changed_file_exclusions_file=changed_file_exclusions_file,
        product_name=product_name,
        system_size=system_size,
        xts_suitetype=xts_suitetype,
        selector_repo_root=selector_repo_root,
        run_label=args.run_label or cfg.get("run_label"),
        run_store_root=run_store_root,
        runtime_state_root=runtime_state_root,
        shard_mode=args.shard_mode or cfg.get("shard_mode") or "mirror",
        device_lock_timeout=float(
            args.device_lock_timeout
            if args.device_lock_timeout is not None
            else (cfg.get("device_lock_timeout") or 30.0)
        ),
        daily_build_tag=args.daily_build_tag or cfg.get("daily_build_tag"),
        daily_component=args.daily_component
        or cfg.get("daily_component")
        or DEFAULT_DAILY_COMPONENT,
        daily_branch=args.daily_branch or cfg.get("daily_branch") or "master",
        daily_date=args.daily_date or cfg.get("daily_date"),
        daily_cache_root=daily_cache_root,
        quick_mode=bool(args.quick),
        sdk_build_tag=args.sdk_build_tag or cfg.get("sdk_build_tag"),
        sdk_component=args.sdk_component
        or cfg.get("sdk_component")
        or DEFAULT_SDK_COMPONENT,
        sdk_branch=args.sdk_branch or cfg.get("sdk_branch") or "master",
        sdk_date=args.sdk_date or cfg.get("sdk_date"),
        sdk_cache_root=sdk_cache_root,
        firmware_build_tag=args.firmware_build_tag or cfg.get("firmware_build_tag"),
        firmware_component=args.firmware_component
        or cfg.get("firmware_component")
        or DEFAULT_FIRMWARE_COMPONENT,
        firmware_branch=args.firmware_branch or cfg.get("firmware_branch") or "master",
        firmware_date=args.firmware_date or cfg.get("firmware_date"),
        firmware_cache_root=firmware_cache_root,
        flash_firmware_path=flash_firmware_path,
        flash_py_path=flash_py_path,
        hdc_path=hdc_path,
        hdc_endpoint=hdc_endpoint,
    )


def _cmd_oracle_extract(args: argparse.Namespace) -> int:
    from .validation.ast_oracle import extract_method_changes
    from .validation.api_mapper import map_method_changes, group_by_confidence
    from .pr_cache import PrApiCache

    cache_dir = Path(args.cache_dir)
    cache = PrApiCache(cache_dir, mode="read-only")

    pr_number = args.pr_number
    repo_root = Path(args.repo_root)

    # Auto-discover cache entry: scan cache dir for PR_<pr_number>.json
    entry = None
    pr_url_pattern = ""
    for pr_json in cache_dir.rglob(f"PR_{pr_number}.json"):
        try:
            raw = json.loads(pr_json.read_text(encoding="utf-8"))
            from .pr_cache import PrCacheEntry

            entry = PrCacheEntry.from_dict(raw)
            pr_url_pattern = raw.get("pr_url", str(pr_json))
            break
        except Exception:
            continue

    if entry is None:
        print(f"PR #{pr_number} not found in cache", file=sys.stderr)
        return 1

    if entry is None:
        print(f"PR #{pr_number} not found in cache", file=sys.stderr)
        return 1

    if not entry.base_sha or not entry.head_sha:
        print(
            f"PR #{pr_number} has no SHA data — run refresh_pr_metadata first",
            file=sys.stderr,
        )
        return 1

    changes = extract_method_changes(
        repo_root=repo_root,
        base_sha=entry.base_sha,
        head_sha=entry.head_sha,
        changed_files=entry.changed_files,
    )

    from dataclasses import asdict

    mappings = map_method_changes([asdict(c) for c in changes])
    grouped = group_by_confidence(mappings)

    result = {
        "pr_number": pr_number,
        "total_changes": len(changes),
        "high_confidence": grouped["high"],
        "medium_confidence": grouped["medium"],
        "unmapped": grouped["unmapped"],
    }

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Wrote oracle output to {args.output}")
    else:
        print(output)

    return 0


def _cmd_coverage_eval(args: argparse.Namespace) -> int:
    from .coverage_eval import (
        CoverageEvaluator,
        load_golden_fixtures,
        load_baseline_metrics,
    )

    batch_results = json.loads(Path(args.batch_results).read_text(encoding="utf-8"))
    golden = load_golden_fixtures(Path(args.golden))

    baseline = None
    if args.baseline:
        baseline = load_baseline_metrics(Path(args.baseline))

    evaluator = CoverageEvaluator(
        batch_results=batch_results,
        golden_fixtures=golden,
        baseline_metrics=baseline,
    )

    report = evaluator.evaluate()

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Wrote coverage eval to {output_path}")

    if args.report_md:
        report_path = Path(args.report_md)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.format_report_md(), encoding="utf-8")
        print(f"Wrote report to {report_path}")

    return evaluator.check_regression_gate()


def validate_inputs(args: argparse.Namespace, app_config: AppConfig) -> list[str]:
    """Return early syntax-level input errors only."""
    del app_config
    errors: list[str] = []
    pr_url = str(getattr(args, "pr_url", None) or "").strip()
    if not pr_url:
        return errors
    parsed = urlparse(pr_url)
    if not parsed.scheme or not parsed.netloc:
        errors.append(
            f"invalid PR URL format: {pr_url!r} - expected https://gitcode.com/.../pull/NNN"
        )
    elif "/pull/" not in parsed.path and "/pulls/" not in parsed.path:
        errors.append(f"PR URL does not look like a pull request URL: {pr_url!r}")
    return errors


def main() -> int:
    global REPO_ROOT
    runtime_started = time.perf_counter()
    args = parse_args()

    # Handle subcommands
    if args.command == "trace":
        from .indexing.trace import cmd_trace

        return cmd_trace(args)
    if args.command == "explain":
        from .indexing.explain import cmd_explain

        return cmd_explain(args)
    if args.command == "validate-batch":
        from .batch_validate import cmd_validate_batch

        return cmd_validate_batch(args)

    if args.command == "audit":
        if args.audit_command == "fn-rate":
            from .audit.analyzer import compute_fn_rate, format_fn_rate_report
            from pathlib import Path as _Path

            report = compute_fn_rate(
                audit_dir=_Path(args.audit_dir) if args.audit_dir else None,
                days=args.days,
            )
            print(format_fn_rate_report(report))
            return 0
        if args.audit_command == "record":
            from .audit.recorder import record_run
            import json as _json
            from pathlib import Path as _Path

            selector_report = None
            if args.selector_report:
                selector_report = _json.loads(_Path(args.selector_report).read_text())
            record_run(
                pr_number=args.pr_number,
                selected=args.selected,
                ran=args.ran,
                failed=args.failed,
                selector_report=selector_report,
                audit_dir=_Path(args.audit_dir) if args.audit_dir else None,
            )
            print(f"Recorded audit entry for PR #{args.pr_number}")
            return 0
        print(
            "Usage: arkui-xts-selector audit <fn-rate|record> [options]",
            file=sys.stderr,
        )
        return 1

    if args.command == "oracle-extract":
        return _cmd_oracle_extract(args)

    if args.command == "coverage-eval":
        return _cmd_coverage_eval(args)

    progress_enabled = not args.no_progress
    json_to_stdout = bool(args.json)
    json_output_path: Path | None = None
    if args.run_top_targets < 0:
        print("--run-top-targets must be >= 0", file=sys.stderr)
        return 2
    if args.run_timeout < 0:
        print("--run-timeout must be >= 0", file=sys.stderr)
        return 2
    app_config = load_app_config(args)
    apply_ranking_rules_config(load_ranking_rules_config(app_config.ranking_rules_file))
    REPO_ROOT = app_config.repo_root
    if args.list_daily_tags is not None:
        return run_list_tags_mode(args, app_config)
    if utility_mode_requested(args):
        return run_utility_mode(
            args=args,
            app_config=app_config,
            progress_enabled=progress_enabled,
            json_to_stdout=json_to_stdout,
            json_output_path=json_output_path,
        )
    if args.benchmark:
        return run_benchmark_mode(args, app_config)
    if args.inspect:
        return run_inspect_mode(args, app_config)
    validation_errors = validate_inputs(args, app_config)
    if validation_errors:
        for err in validation_errors:
            print(f"error: {err}", file=sys.stderr)
        return 2
    if app_config.quick_mode:
        # Quick mode: skip daily download, use only local artifacts
        emit_progress(
            progress_enabled, "quick mode enabled (using local ACTS artifacts only)"
        )
        if not _has_local_acts_artifacts(app_config.acts_out_root):
            print(
                "warning: --quick mode active but no local ACTS artifacts found. "
                f"Expected under: {app_config.acts_out_root or '<unset>'}",
                file=sys.stderr,
                flush=True,
            )
            print(
                "Options: (1) Build tests: ohos build --product-name rk3568 --build-target ohos_test\n"
                "         (2) Download daily: ohos download tests\n"
                "         (3) Run without --quick to auto-download daily prebuilt\n"
                "Proceeding with API/SDK analysis only (reduced accuracy).",
                file=sys.stderr,
                flush=True,
            )
    elif app_config.daily_build_tag or app_config.daily_date:
        emit_progress(
            progress_enabled,
            f"preparing daily prebuilt {app_config.daily_build_tag or app_config.daily_date}",
        )
        try:
            prepare_daily_prebuilt_from_config(app_config)
        except (OSError, ValueError, FileNotFoundError, urllib.error.URLError) as exc:
            print(f"daily prebuilt preparation failed: {exc}", file=sys.stderr)
            return 2
    elif not _has_local_acts_artifacts(app_config.acts_out_root):
        warning_root = str(app_config.acts_out_root or "")
        preferred_local_acts_root = app_config.acts_out_root
        app_config.daily_date = time.strftime("%Y%m%d")
        print(
            "warning: local ACTS artifacts were not found under "
            f"{warning_root or '<unset>'}; auto-downloading daily tests for {app_config.daily_date}.",
            file=sys.stderr,
            flush=True,
        )
        emit_progress(
            progress_enabled, f"preparing daily prebuilt {app_config.daily_date}"
        )
        try:
            prepared = prepare_daily_prebuilt_from_config(app_config)
        except (OSError, ValueError, FileNotFoundError, urllib.error.URLError) as exc:
            if args.run_now:
                print(f"daily prebuilt preparation failed: {exc}", file=sys.stderr)
                return 2
            else:
                print(
                    f"warning: daily prebuilt preparation failed: {exc}; "
                    "continuing with selection-only analysis and current inventory gaps.",
                    file=sys.stderr,
                    flush=True,
                )
                prepared = None
        if prepared is not None and preferred_local_acts_root is not None:
            try:
                synced_root = _sync_prebuilt_acts_to_local_root(
                    prepared,
                    preferred_local_acts_root,
                    progress_enabled=progress_enabled,
                )
            except OSError as exc:
                if args.run_now:
                    print(f"daily prebuilt sync failed: {exc}", file=sys.stderr)
                    return 2
                else:
                    print(
                        f"warning: daily prebuilt sync failed: {exc}", file=sys.stderr
                    )
                    synced_root = None
            if synced_root is not None:
                app_config.acts_out_root = synced_root
                app_config.daily_prebuilt_note = (
                    f"{app_config.daily_prebuilt_note} Synced to local ACTS root {synced_root}."
                ).strip()

    # Auto-download SDK if sdk_api_root is empty or has no SDK API files
    sdk_component_root = app_config.sdk_api_root / "arkui" / "component"
    if not sdk_component_root.is_dir() or not any(sdk_component_root.glob("*.d.ets")):
        if app_config.sdk_date is None and app_config.sdk_build_tag is None:
            app_config.sdk_date = time.strftime("%Y%m%d")
        if app_config.sdk_date or app_config.sdk_build_tag:
            emit_progress(
                progress_enabled,
                f"auto-downloading daily SDK {app_config.sdk_build_tag or app_config.sdk_date}",
            )
            try:
                prepared_sdk = prepare_daily_sdk_from_config(app_config)
                if prepared_sdk.primary_root is not None:
                    app_config.sdk_api_root = prepared_sdk.primary_root
            except (
                OSError,
                ValueError,
                FileNotFoundError,
                urllib.error.URLError,
            ) as exc:
                print(f"warning: SDK auto-download failed: {exc}", file=sys.stderr)

    source_report_path = resolve_selector_report_input(
        args.from_report,
        bool(args.last_report),
        app_config.run_store_root or default_run_store_root(PROJECT_ROOT),
    )
    source_report = (
        load_selector_report(source_report_path)
        if source_report_path is not None
        else None
    )
    run_session = (
        create_run_session(
            app_config.run_label,
            run_store_root=app_config.run_store_root,
            selector_repo_root=app_config.selector_repo_root,
        )
        if app_config.run_label
        else (
            run_session_from_report(source_report, source_report_path)
            if source_report is not None and source_report_path is not None
            else None
        )
    )
    if not json_to_stdout:
        if args.json_out:
            json_output_path = resolve_json_output_path(args.json_out)
        elif run_session is not None:
            json_output_path = run_session.selector_report_path
        elif source_report_path is not None:
            json_output_path = source_report_path
        else:
            json_output_path = resolve_json_output_path(None)
    xdevice_reports_root = (
        (run_session.run_dir / "xdevice_reports") if run_session is not None else None
    )
    changed_inputs = list(args.changed_file)
    changed_symbols = [
        item.strip() for item in args.changed_symbol if item and item.strip()
    ]
    symbol_queries = [
        item.strip() for item in args.symbol_query if item and item.strip()
    ]
    code_queries = [item.strip() for item in args.code_query if item and item.strip()]
    requested_test_names_path = (
        resolve_path(
            args.run_test_names_file, app_config.repo_root, app_config.repo_root
        )
        if args.run_test_names_file
        else None
    )
    requested_test_names = normalize_requested_test_names(
        [
            *list(args.run_test_name),
            *read_requested_test_names(requested_test_names_path),
        ]
    )
    execution_progress_callback = build_execution_progress_callback(progress_enabled)

    if args.changed_files_from:
        changed_inputs.extend(
            read_text(
                resolve_path(
                    args.changed_files_from, app_config.repo_root, app_config.repo_root
                )
            ).splitlines()
        )

    if source_report is not None:
        report = source_report
        report["human_mode"] = "run_only"
        report["timings_ms"] = {}
        report["json_output_mode"] = "stdout" if json_to_stdout else "file"
        report["requested_devices"] = list(app_config.devices)
        report["execution_server_host"] = app_config.server_host or ""
        report["execution_server_user"] = app_config.server_user or ""
        report["execution_xdevice_reports_root"] = (
            str(xdevice_reports_root) if xdevice_reports_root is not None else ""
        )
        report["execution_summary"] = {}
        selected_tests_report_base_path = resolve_selected_tests_report_base_path(
            run_session, json_output_path
        )
        if json_output_path is not None:
            report["json_output_path"] = str(json_output_path)
            selected_tests_json_path = resolve_selected_tests_output_path(
                selected_tests_report_base_path
            )
            if selected_tests_json_path is not None:
                report["selected_tests_json_path"] = str(selected_tests_json_path)
        if run_session is not None:
            report["selector_run"] = {
                "label": run_session.label,
                "label_key": run_session.label_key,
                "timestamp": run_session.timestamp,
                "status": str(report.get("selector_run", {}).get("status", "planned")),
                "run_dir": str(run_session.run_dir),
                "run_store_root": str(
                    (
                        app_config.run_store_root
                        or default_run_store_root(PROJECT_ROOT)
                    ).resolve()
                ),
                "selector_report_path": str(run_session.selector_report_path),
                "manifest_path": str(run_session.manifest_path),
            }

        if app_config.daily_prebuilt is not None:
            report["daily_prebuilt"] = {
                **app_config.daily_prebuilt.to_dict(),
                "note": app_config.daily_prebuilt_note,
            }

        emit_progress(progress_enabled, "planning target execution from saved report")
        attach_execution_plan(
            report,
            repo_root=app_config.repo_root,
            acts_out_root=app_config.acts_out_root,
            devices=app_config.devices,
            run_tool=args.run_tool,
            run_top_targets=args.run_top_targets,
            shard_mode=app_config.shard_mode,
            xdevice_reports_root=xdevice_reports_root,
            run_priority=args.run_priority,
            parallel_jobs=args.parallel_jobs,
            runtime_state_root=app_config.runtime_state_root,
            device_lock_timeout=app_config.device_lock_timeout,
            hdc_path=app_config.hdc_path,
            hdc_endpoint=app_config.hdc_endpoint,
            requested_test_names=requested_test_names,
            skip_install=args.skip_install,
        )
        report["next_steps"] = build_next_steps(report, app_config, args)
        execution_summary = None
        execution_preflight = None
        preflight_failed = False
        execution_interrupted = False
        if args.run_now:
            emit_progress(progress_enabled, "preflighting execution")
            execution_preflight = preflight_execution(
                report,
                repo_root=app_config.repo_root,
                devices=app_config.devices,
                hdc_path=app_config.hdc_path,
                hdc_endpoint=app_config.hdc_endpoint,
            )
            report["execution_preflight"] = execution_preflight
            if execution_preflight.get("status") != "passed":
                preflight_failed = True
            else:
                emit_progress(progress_enabled, "running selected targets")
                try:
                    execution_summary = execute_planned_targets(
                        report,
                        repo_root=app_config.repo_root,
                        acts_out_root=app_config.acts_out_root,
                        devices=app_config.devices,
                        run_tool=args.run_tool,
                        run_top_targets=args.run_top_targets,
                        run_timeout=args.run_timeout,
                        shard_mode=app_config.shard_mode,
                        xdevice_reports_root=xdevice_reports_root,
                        run_priority=args.run_priority,
                        parallel_jobs=args.parallel_jobs,
                        runtime_state_root=app_config.runtime_state_root,
                        device_lock_timeout=app_config.device_lock_timeout,
                        requested_test_names=requested_test_names,
                        hdc_path=app_config.hdc_path,
                        hdc_endpoint=app_config.hdc_endpoint,
                        progress_callback=execution_progress_callback,
                        skip_install=args.skip_install,
                    )
                except KeyboardInterrupt:
                    execution_interrupted = True
                    report["execution_interrupted"] = True
                    execution_summary = dict(report.get("execution_summary") or {})
        else:
            report["execution_preflight"] = {}
        if run_session is not None:
            status = "planned"
            if preflight_failed:
                status = "failed_preflight"
            elif execution_interrupted:
                status = "interrupted"
            elif execution_summary is not None:
                status = (
                    "completed_with_failures"
                    if execution_summary.get("has_failures")
                    else "completed"
                )
            report["selector_run"]["status"] = status
        if execution_summary is not None:
            report["runtime_history_update"] = update_runtime_history(
                default_runtime_history_file(app_config.runtime_state_root),
                report,
                run_label=str(
                    report.get("selector_run", {}).get("label")
                    or app_config.run_label
                    or ""
                ),
            )
        else:
            report["runtime_history_update"] = {
                "history_file": str(
                    default_runtime_history_file(app_config.runtime_state_root)
                ),
                "updated_targets": 0,
                "updated_samples": 0,
                "significant_updates": 0,
            }

        artifact_output_dir = (
            run_session.run_dir
            if run_session is not None
            else (json_output_path.parent if json_output_path is not None else None)
        )
        artifact_index_path = write_execution_artifact_index(
            report, artifact_output_dir
        )
        if artifact_index_path is not None:
            report["execution_artifact_index_path"] = str(artifact_index_path)

        emit_progress(progress_enabled, "writing JSON report")
        written_json_path = write_json_report(
            report, json_to_stdout=json_to_stdout, json_output_path=json_output_path
        )
        selected_tests_report_base_path = resolve_selected_tests_report_base_path(
            run_session, written_json_path
        )
        if selected_tests_report_base_path is not None:
            selected_tests_path = write_selected_tests_report(
                report, selected_tests_report_base_path
            )
            if selected_tests_path is not None:
                report["selected_tests_json_path"] = str(selected_tests_path)
                if written_json_path is not None:
                    write_json_report(
                        report, json_to_stdout=False, json_output_path=written_json_path
                    )
        if run_session is not None:
            manifest = build_run_manifest(
                report,
                selector_repo_root=app_config.selector_repo_root or PROJECT_ROOT,
                run_store_root=app_config.run_store_root
                or default_run_store_root(PROJECT_ROOT),
                session=run_session,
                status=report["selector_run"]["status"],
                shard_mode=app_config.shard_mode,
                preflight=execution_preflight,
            )
            write_run_artifacts(run_session, report, manifest)
        if not json_to_stdout:
            emit_progress(progress_enabled, "rendering human report")
            print_executive_summary(report, written_json_path)
            print_human(report, None, written_json_path)
        if execution_interrupted:
            return 130
        if args.run_now and preflight_failed:
            return 2
        if args.run_now and execution_summary and execution_summary.get("has_failures"):
            return 1
        return 0

    changed_files = normalize_changed_files(
        changed_inputs, base_roots=[app_config.repo_root, app_config.git_repo_root]
    )
    if args.git_diff:
        try:
            changed_files.extend(
                git_changed_files(app_config.git_repo_root, args.git_diff)
            )
        except RuntimeError as exc:
            print(f"error: git diff failed: {exc}", file=sys.stderr)
            return 2
    inferred_changed_ranges_by_file: dict[Path, list[tuple[int, int]]] = {}
    if args.pr_url or args.pr_number:
        try:
            pr_ref = args.pr_url or args.pr_number
            pr_changed_files, pr_changed_ranges = resolve_pr_changed_files_with_ranges(
                app_config,
                pr_ref,
                args.pr_source,
            )
            changed_files.extend(pr_changed_files)
            inferred_changed_ranges_by_file = merge_changed_range_maps(
                inferred_changed_ranges_by_file,
                pr_changed_ranges,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "403" in message or "401" in message or "token" in message.lower():
                hint = "The Git host token may be missing or expired. Run: ohos pr setup-token"
            elif "404" in message or "not found" in message.lower():
                hint = f"PR not found. Check the PR URL or number: {getattr(args, 'pr_url', None) or getattr(args, 'pr_number', None)}"
            else:
                hint = "Check the PR URL, configured git host credentials, and network access."
            print(
                f"error: {XtsUserError(f'cannot fetch PR diff: {message}', hint=hint)}",
                file=sys.stderr,
            )
            return 2

    deduped: list[Path] = []
    seen = set()
    for item in changed_files:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    changed_files = deduped

    try:
        changed_ranges_by_file = merge_changed_range_maps(
            inferred_changed_ranges_by_file,
            parse_changed_ranges(
                args.changed_range,
                changed_files=changed_files,
                base_roots=[app_config.repo_root, app_config.git_repo_root],
            ),
        )
    except ValueError as exc:
        print(f"changed range parsing failed: {exc}", file=sys.stderr)
        return 2

    if not changed_files and not symbol_queries and not code_queries:
        print(
            "No changed files, symbol queries, or code queries were provided.",
            file=sys.stderr,
        )
        return 2

    exclusion_started = time.perf_counter()
    exclusion_config = load_changed_file_exclusion_config(
        app_config.changed_file_exclusions_file
    )
    changed_files, excluded_inputs = filter_changed_files_for_xts(
        changed_files,
        app_config.git_repo_root,
        exclusion_config,
    )
    changed_file_filtering_ms = round(
        (time.perf_counter() - exclusion_started) * 1000, 3
    )

    progress_callback = build_progress_callback(progress_enabled, len(changed_files))

    emit_progress(progress_enabled, "loading XTS project index")
    load_started = time.perf_counter()
    projects, cache_used = load_or_build_projects(
        app_config.xts_root, app_config.cache_file
    )
    load_projects_ms = round((time.perf_counter() - load_started) * 1000, 3)
    emit_progress(progress_enabled, "loading SDK index")
    sdk_started = time.perf_counter()
    sdk_index = load_sdk_index(app_config.sdk_api_root)
    load_sdk_index_ms = round((time.perf_counter() - sdk_started) * 1000, 3)
    emit_progress(progress_enabled, "building content modifier index")
    content_started = time.perf_counter()
    content_index = build_content_modifier_index()
    build_content_modifier_index_ms = round(
        (time.perf_counter() - content_started) * 1000, 3
    )
    emit_progress(progress_enabled, "loading mapping config")
    mapping_started = time.perf_counter()
    api_lineage_map = None
    api_lineage_map_path = None
    build_api_lineage_map_ms = 0.0
    lineage_auto_alias = None
    if changed_files:
        emit_progress(progress_enabled, "building api lineage map")
        lineage_started = time.perf_counter()
        api_lineage_map, api_lineage_map_path = build_api_lineage_map(
            repo_root=app_config.repo_root,
            ace_engine_root=app_config.git_repo_root,
            sdk_api_root=app_config.sdk_api_root,
            projects=projects,
            runtime_state_root=app_config.runtime_state_root,
            project_cache_file=app_config.cache_file,
        )
        build_api_lineage_map_ms = round(
            (time.perf_counter() - lineage_started) * 1000, 3
        )
        if api_lineage_map is not None:
            lineage_auto_alias = api_lineage_map.auto_pattern_alias()
    mapping_config = load_mapping_config(
        path_rules_file=app_config.path_rules_file,
        composite_mappings_file=app_config.composite_mappings_file,
        lineage_auto_alias=lineage_auto_alias,
    )
    load_mapping_config_ms = round((time.perf_counter() - mapping_started) * 1000, 3)
    emit_progress(progress_enabled, "loading runtime history")
    runtime_history_started = time.perf_counter()
    runtime_history_index = build_runtime_history_index(
        default_runtime_history_file(app_config.runtime_state_root)
    )
    load_runtime_history_ms = round(
        (time.perf_counter() - runtime_history_started) * 1000, 3
    )
    api_lineage_map = None
    api_lineage_map_path = None
    build_api_lineage_map_ms = 0.0
    if changed_files:
        emit_progress(progress_enabled, "building api lineage map")
        lineage_started = time.perf_counter()
        api_lineage_map, api_lineage_map_path = build_api_lineage_map(
            repo_root=app_config.repo_root,
            ace_engine_root=app_config.git_repo_root,
            sdk_api_root=app_config.sdk_api_root,
            projects=projects,
            runtime_state_root=app_config.runtime_state_root,
            project_cache_file=app_config.cache_file,
        )
        build_api_lineage_map_ms = round(
            (time.perf_counter() - lineage_started) * 1000, 3
        )
    emit_progress(progress_enabled, "building report")
    report_started = time.perf_counter()
    report = format_report(
        changed_files=changed_files,
        changed_symbols=changed_symbols,
        changed_ranges_by_file=changed_ranges_by_file,
        symbol_queries=symbol_queries,
        code_queries=code_queries,
        projects=projects,
        sdk_index=sdk_index,
        content_index=content_index,
        mapping_config=mapping_config,
        app_config=app_config,
        top_projects=args.top_projects,
        top_files=args.top_files,
        device=app_config.device,
        xts_root=app_config.xts_root,
        sdk_api_root=app_config.sdk_api_root,
        git_repo_root=app_config.git_repo_root,
        acts_out_root=app_config.acts_out_root,
        variants_mode=args.variants,
        relevance_mode=args.relevance_mode,
        keep_per_signature=args.keep_per_signature,
        cache_used=cache_used,
        debug_trace=args.debug_trace,
        runtime_history_index=runtime_history_index,
        requested_run_tool=args.run_tool,
        progress_callback=progress_callback,
        api_lineage_map=api_lineage_map,
        api_lineage_map_path=api_lineage_map_path,
    )
    report["acts_out_root"] = str(
        app_config.acts_out_root or (app_config.repo_root / "out/release/suites/acts")
    )
    report["excluded_inputs"] = excluded_inputs
    report["timings_ms"].update(
        {
            "changed_file_filtering": changed_file_filtering_ms,
            "load_projects": load_projects_ms,
            "load_sdk_index": load_sdk_index_ms,
            "build_content_modifier_index": build_content_modifier_index_ms,
            "load_mapping_config": load_mapping_config_ms,
            "load_runtime_history": load_runtime_history_ms,
            "build_api_lineage_map": build_api_lineage_map_ms,
            "main_report_call": round((time.perf_counter() - report_started) * 1000, 3),
        }
    )
    report["timings_ms"]["total_runtime"] = round(
        (time.perf_counter() - runtime_started) * 1000, 3
    )
    # ---- Changed-symbol warning (opt-in, requires --use-graph-resolver) ----
    if changed_symbols and not args.use_graph_resolver:
        print(
            "warning: --changed-symbol requires --use-graph-resolver, ignoring symbol query",
            file=sys.stderr,
        )
    # ---- Graph-based resolver (Phase 7, experimental, under flag) ----
    if args.use_graph_resolver and changed_files:
        try:
            from .indexing.cache import (
                cached_sdk_index,
                cached_ace_index,
                cached_inverted_index,
            )
            from .indexing.sdk_indexer import SdkIndexResult
            from .indexing.ace_indexer import AceIndexResult
            from .indexing.inverted_index import InvertedIndex
            from .indexing.pr_resolver import resolve_pr, apply_fallback

            graph_started = time.perf_counter()

            _sdk_root = app_config.sdk_api_root or (
                app_config.repo_root / "interface/sdk-js/api"
            )
            _ace_root = app_config.repo_root / "foundation/arkui/ace_engine"
            _xts_root = app_config.xts_root

            _sdk = (
                cached_sdk_index(_sdk_root) if _sdk_root.is_dir() else SdkIndexResult()
            )
            _ace = (
                cached_ace_index(_ace_root) if _ace_root.is_dir() else AceIndexResult()
            )
            _inverted = (
                cached_inverted_index(_xts_root, sdk_index=_sdk, sdk_api_root=_sdk_root)
                if _xts_root and _xts_root.is_dir()
                else InvertedIndex()
            )

            from .indexing.target_index import build_target_index, TargetIndexResult

            _target_index = (
                build_target_index(_xts_root)
                if _xts_root and _xts_root.is_dir()
                else TargetIndexResult()
            )

            _broad_rules = PROJECT_ROOT / "config" / "broad_infrastructure_files.json"

            # Convert changed_ranges_by_file (Path keys) to str keys for resolve_pr
            _changed_ranges: dict[str, list[tuple[int, int]]] = {}
            for fpath, ranges in (changed_ranges_by_file or {}).items():
                _changed_ranges[str(fpath)] = ranges

            _result = resolve_pr(
                changed_files=[str(f) for f in changed_files],
                ace_index=_ace,
                sdk_index=_sdk,
                inverted=_inverted,
                broad_rules_path=_broad_rules if _broad_rules.exists() else None,
                changed_ranges=_changed_ranges if _changed_ranges else None,
                xts_root=_xts_root if _xts_root else None,
            )

            # Apply conservative fallback policy (Phase 11)
            _result = apply_fallback(
                _result,
                xts_root=_xts_root if _xts_root else None,
                target_index=_target_index,
            )

            def _entry_to_dict(e):
                d = {
                    "changed_file": e.changed_file,
                    "affected_apis": list(e.affected_apis),
                    "consumer_projects": list(e.consumer_projects),
                    "selection_reasons": [r.to_dict() for r in e.selection_reasons],
                    "false_negative_risk": e.false_negative_risk,
                    "parser_level": e.parser_level,
                }
                if e.broad_infra_match is not None:
                    d["broad_infra_match"] = {
                        "rule_id": e.broad_infra_match.rule_id,
                        "rationale": e.broad_infra_match.rationale,
                        "fan_out_target": e.broad_infra_match.fan_out_target,
                        "risk": e.broad_infra_match.false_negative_risk,
                    }
                if e.impact_candidates:
                    d["impact_candidates"] = list(e.impact_candidates)
                if e.unresolved_reason is not None:
                    d["unresolved_reason"] = e.unresolved_reason
                return d

            graph_selection = {
                "schema_version": "graph-pr-v1",
                "entries": [_entry_to_dict(e) for e in _result.entries],
                "overall_false_negative_risk": _result.overall_false_negative_risk,
                "index_stats": {
                    "sdk_entries": len(_sdk.entries),
                    "ace_entries": len(_ace.entries),
                    "inverted_apis": len(_inverted.by_api),
                },
            }
            if _result.coverage_gap:
                graph_selection["coverage_gap"] = list(_result.coverage_gap)
            # Fallback policy fields (Phase 11)
            graph_selection["fallback_applied"] = _result.fallback_applied
            graph_selection["fallback_reason"] = _result.fallback_reason
            graph_selection["fallback_level"] = _result.fallback_level
            if _result.fallback_extra_targets:
                graph_selection["fallback_extra_targets"] = list(
                    _result.fallback_extra_targets
                )
            # Phase 7: CI policy and unresolved tracking
            graph_selection["ci_policy_recommendation"] = (
                _result.ci_policy_recommendation
            )
            graph_selection["ci_policy_reason"] = _result.ci_policy_reason
            graph_selection["semantic_source"] = _result.semantic_source
            if _result.unresolved_files:
                graph_selection["unresolved_files"] = list(_result.unresolved_files)
            report["graph_selection"] = graph_selection
            report["timings_ms"]["graph_resolver"] = round(
                (time.perf_counter() - graph_started) * 1000, 3
            )
        except Exception as exc:
            report["graph_selection"] = {"error": str(exc)}
    # ---- End graph-based resolver ----

    # ---- Symbol-precision graph query (opt-in, --changed-symbol + --use-graph-resolver) ----
    if args.use_graph_resolver and changed_symbols:
        sym_query_started = time.perf_counter()
        try:
            from .graph.resolver import resolve_changed_symbol_to_tests
            from .graph.schema import Graph

            # Attempt to locate a persisted graph file in the runtime state root or
            # config directory.  In production the graph is typically absent (no build
            # step populates it yet), in which case we report unresolved gracefully.
            _graph_path: Path | None = None
            _graph_search_roots = [
                app_config.runtime_state_root,
                PROJECT_ROOT / "config",
                PROJECT_ROOT,
            ]
            for _search_root in _graph_search_roots:
                if _search_root is None:
                    continue
                _candidate = Path(_search_root) / "api_graph.json"
                if _candidate.is_file():
                    _graph_path = _candidate
                    break

            _sym_graph: Graph | None = None
            _graph_load_error: str = ""
            if _graph_path is not None:
                try:
                    import json as _json

                    _sym_graph = Graph.from_dict(
                        _json.loads(_graph_path.read_text(encoding="utf-8"))
                    )
                except Exception as _ge:
                    _graph_load_error = str(_ge)

            symbol_query_results: list[dict] = []
            for _sym in changed_symbols:
                # Derive source_file_path from changed_files when exactly one is given
                _source_file: str | None = None
                if len(changed_files) == 1:
                    _source_file = str(changed_files[0])

                if _sym_graph is not None:
                    _selections = resolve_changed_symbol_to_tests(
                        _sym_graph, _sym, source_file_path=_source_file
                    )
                    _unresolved = len(_selections) == 0
                    _gap_reason = (
                        f"no source-span evidence found for symbol '{_sym}' in graph"
                        if _unresolved
                        else ""
                    )
                    _has_must_run = any(
                        s.semantic_bucket == "must_run" for s in _selections
                    )
                    _coverage_gap_note = (
                        ""
                        if not _unresolved and _has_must_run
                        else (
                            "coverage_equivalence not satisfied: no must_run produced"
                            if not _unresolved
                            else _gap_reason
                        )
                    )
                    symbol_query_results.append(
                        {
                            "changed_symbol": _sym,
                            "source_file": _source_file,
                            "unresolved": _unresolved,
                            "coverage_gap_reason": _coverage_gap_note,
                            "selection_count": len(_selections),
                            "must_run_count": sum(
                                1
                                for s in _selections
                                if s.semantic_bucket == "must_run"
                            ),
                            "selections": [
                                {
                                    "api_entity_id": s.candidate.api_entity_id.canonical(),
                                    "semantic_bucket": s.semantic_bucket,
                                    "runnability_state": s.runnability_state,
                                    "coverage_equivalence": s.candidate.coverage_equivalence,
                                    "order_score": s.order_score,
                                }
                                for s in _selections
                            ],
                        }
                    )
                else:
                    # No graph available — report unresolved
                    _no_graph_reason = (
                        f"graph not found (searched {[str(r) for r in _graph_search_roots if r]})"
                        if not _graph_load_error
                        else f"graph load error: {_graph_load_error}"
                    )
                    symbol_query_results.append(
                        {
                            "changed_symbol": _sym,
                            "source_file": _source_file,
                            "unresolved": True,
                            "coverage_gap_reason": _no_graph_reason,
                            "selection_count": 0,
                            "must_run_count": 0,
                            "selections": [],
                        }
                    )

            report["symbol_query"] = {
                "schema_version": "symbol-query-v1",
                "changed_symbols": list(changed_symbols),
                "graph_path": str(_graph_path) if _graph_path else None,
                "results": symbol_query_results,
            }
            report["timings_ms"]["symbol_query_graph"] = round(
                (time.perf_counter() - sym_query_started) * 1000, 3
            )
        except Exception as exc:
            report["symbol_query"] = {"error": str(exc)}
    # ---- End symbol-precision graph query ----

    # ---- Hunk-precision graph query (opt-in, --changed-lines + --use-graph-resolver) ----
    _raw_changed_lines = [
        item.strip() for item in args.changed_lines if item and item.strip()
    ]
    if _raw_changed_lines and not args.use_graph_resolver:
        print(
            "warning: --changed-lines requires --use-graph-resolver, ignoring hunk query",
            file=sys.stderr,
        )
    if args.use_graph_resolver and _raw_changed_lines:
        hunk_query_started = time.perf_counter()
        try:
            from .hunk_impact import (
                parse_changed_lines_arg,
                resolve_hunk_to_symbols,
                HunkQueryEntry,
                _compute_overall_bucket,
            )
            from .graph.resolver import resolve_changed_symbol_to_tests
            from .graph.schema import Graph

            # Reuse graph path resolution from symbol_query block above
            _hq_graph_path: "Path | None" = None
            _hq_graph_search_roots = [
                app_config.runtime_state_root,
                PROJECT_ROOT / "config",
                PROJECT_ROOT,
            ]
            for _hq_root in _hq_graph_search_roots:
                if _hq_root is None:
                    continue
                _hq_candidate = Path(_hq_root) / "api_graph.json"
                if _hq_candidate.is_file():
                    _hq_graph_path = _hq_candidate
                    break

            _hq_graph: "Graph | None" = None
            _hq_graph_load_error: str = ""
            if _hq_graph_path is not None:
                try:
                    import json as _json2
                    _hq_graph = Graph.from_dict(
                        _json2.loads(_hq_graph_path.read_text(encoding="utf-8"))
                    )
                except Exception as _hqge:
                    _hq_graph_load_error = str(_hqge)

            # symbol_index: caller may supply via a side-channel file; in v1 we
            # accept an empty index and report unresolved gracefully.
            _symbol_index: dict = {}
            _symbol_index_source = "empty (no symbol index file supplied)"
            _sym_index_path = app_config.runtime_state_root
            if _sym_index_path is not None:
                _sym_idx_file = Path(_sym_index_path) / "symbol_spans.json"
                if _sym_idx_file.is_file():
                    try:
                        import json as _json3
                        _raw_idx = _json3.loads(_sym_idx_file.read_text(encoding="utf-8"))
                        # Expected format: {file_path: [[sym, start, end], ...]}
                        for fp, spans in _raw_idx.items():
                            _symbol_index[fp] = [
                                (str(s[0]), int(s[1]), int(s[2])) for s in spans
                            ]
                        _symbol_index_source = str(_sym_idx_file)
                    except Exception as _sie:
                        _symbol_index_source = f"error loading {_sym_idx_file}: {_sie}"

            hunk_entries: list[dict] = []
            parse_errors: list[str] = []

            for _raw_hunk in _raw_changed_lines:
                try:
                    _hunk_path, _hunk_start, _hunk_end = parse_changed_lines_arg(_raw_hunk)
                except ValueError as _pe:
                    parse_errors.append(str(_pe))
                    continue

                _hunk_result = resolve_hunk_to_symbols(
                    path=_hunk_path,
                    line_start=_hunk_start,
                    line_end=_hunk_end,
                    symbol_index=_symbol_index,
                )

                _sym_selections: dict[str, list] = {}
                if _hq_graph is not None:
                    for _rsym in _hunk_result.resolved_symbols:
                        _sel = resolve_changed_symbol_to_tests(
                            _hq_graph, _rsym, source_file_path=_hunk_path
                        )
                        _sym_selections[_rsym] = _sel
                elif _hunk_result.resolved_symbols:
                    for _rsym in _hunk_result.resolved_symbols:
                        _sym_selections[_rsym] = []

                _hq_entry = HunkQueryEntry(
                    path=_hunk_path,
                    line_start=_hunk_start,
                    line_end=_hunk_end,
                    hunk_impact=_hunk_result,
                    symbol_selections=_sym_selections,
                    overall_bucket=_compute_overall_bucket(_sym_selections),
                )
                hunk_entries.append(_hq_entry.to_dict())

            _hq_no_graph_note = ""
            if _hq_graph is None:
                _hq_no_graph_note = (
                    f"graph not found (searched {[str(r) for r in _hq_graph_search_roots if r]})"
                    if not _hq_graph_load_error
                    else f"graph load error: {_hq_graph_load_error}"
                )

            report["hunk_query"] = {
                "schema_version": "hunk-query-v1",
                "changed_lines_inputs": _raw_changed_lines,
                "graph_path": str(_hq_graph_path) if _hq_graph_path else None,
                "graph_note": _hq_no_graph_note,
                "symbol_index_source": _symbol_index_source,
                "entries": hunk_entries,
                "parse_errors": parse_errors,
            }
            report["timings_ms"]["hunk_query_graph"] = round(
                (time.perf_counter() - hunk_query_started) * 1000, 3
            )
        except Exception as exc:
            report["hunk_query"] = {"error": str(exc)}
    # ---- End hunk-precision graph query ----

    report["json_output_mode"] = "stdout" if json_to_stdout else "file"
    report["requested_devices"] = list(app_config.devices)
    report["execution_server_host"] = app_config.server_host or ""
    report["execution_server_user"] = app_config.server_user or ""
    report["execution_xdevice_reports_root"] = (
        str(xdevice_reports_root) if xdevice_reports_root is not None else ""
    )
    if app_config.daily_prebuilt is not None:
        report["daily_prebuilt"] = {
            **app_config.daily_prebuilt.to_dict(),
            "note": app_config.daily_prebuilt_note,
        }
    selected_tests_report_base_path = resolve_selected_tests_report_base_path(
        run_session, json_output_path
    )
    if json_output_path is not None:
        report["json_output_path"] = str(json_output_path)
        selected_tests_json_path = resolve_selected_tests_output_path(
            selected_tests_report_base_path
        )
        if selected_tests_json_path is not None:
            report["selected_tests_json_path"] = str(selected_tests_json_path)
    if run_session is not None:
        report["selector_run"] = {
            "label": run_session.label,
            "label_key": run_session.label_key,
            "timestamp": run_session.timestamp,
            "status": "planned",
            "run_dir": str(run_session.run_dir),
            "run_store_root": str(
                (
                    app_config.run_store_root or default_run_store_root(PROJECT_ROOT)
                ).resolve()
            ),
            "selector_report_path": str(run_session.selector_report_path),
            "manifest_path": str(run_session.manifest_path),
        }

    emit_progress(progress_enabled, "planning target execution")
    attach_execution_plan(
        report,
        repo_root=app_config.repo_root,
        acts_out_root=app_config.acts_out_root,
        devices=app_config.devices,
        run_tool=args.run_tool,
        run_top_targets=args.run_top_targets,
        shard_mode=app_config.shard_mode,
        xdevice_reports_root=xdevice_reports_root,
        run_priority=args.run_priority,
        parallel_jobs=args.parallel_jobs,
        runtime_state_root=app_config.runtime_state_root,
        device_lock_timeout=app_config.device_lock_timeout,
        hdc_path=app_config.hdc_path,
        hdc_endpoint=app_config.hdc_endpoint,
        requested_test_names=requested_test_names,
        skip_install=args.skip_install,
    )
    report["show_source_evidence"] = bool(args.show_source_evidence or args.debug_trace)
    report["coverage_run_commands"] = build_coverage_run_commands(
        report, app_config, args
    )
    report["next_steps"] = build_next_steps(report, app_config, args)
    execution_summary = None
    execution_preflight = None
    preflight_failed = False
    execution_interrupted = False
    if args.run_now:
        emit_progress(progress_enabled, "preflighting execution")
        execution_preflight = preflight_execution(
            report,
            repo_root=app_config.repo_root,
            devices=app_config.devices,
            hdc_path=app_config.hdc_path,
            hdc_endpoint=app_config.hdc_endpoint,
        )
        report["execution_preflight"] = execution_preflight
        if execution_preflight.get("status") != "passed":
            preflight_failed = True
        else:
            emit_progress(progress_enabled, "running selected targets")
            try:
                execution_summary = execute_planned_targets(
                    report,
                    repo_root=app_config.repo_root,
                    acts_out_root=app_config.acts_out_root,
                    devices=app_config.devices,
                    run_tool=args.run_tool,
                    run_top_targets=args.run_top_targets,
                    run_timeout=args.run_timeout,
                    shard_mode=app_config.shard_mode,
                    xdevice_reports_root=xdevice_reports_root,
                    run_priority=args.run_priority,
                    parallel_jobs=args.parallel_jobs,
                    runtime_state_root=app_config.runtime_state_root,
                    device_lock_timeout=app_config.device_lock_timeout,
                    requested_test_names=requested_test_names,
                    hdc_path=app_config.hdc_path,
                    hdc_endpoint=app_config.hdc_endpoint,
                    progress_callback=execution_progress_callback,
                    skip_install=args.skip_install,
                )
            except KeyboardInterrupt:
                execution_interrupted = True
                report["execution_interrupted"] = True
                execution_summary = dict(report.get("execution_summary") or {})
    else:
        report["execution_preflight"] = {}

    if run_session is not None:
        status = "planned"
        if preflight_failed:
            status = "failed_preflight"
        elif execution_interrupted:
            status = "interrupted"
        elif execution_summary is not None:
            status = (
                "completed_with_failures"
                if execution_summary.get("has_failures")
                else "completed"
            )
        report["selector_run"]["status"] = status
    if execution_summary is not None:
        report["runtime_history_update"] = update_runtime_history(
            default_runtime_history_file(app_config.runtime_state_root),
            report,
            run_label=app_config.run_label,
        )
    else:
        report["runtime_history_update"] = {
            "history_file": str(
                default_runtime_history_file(app_config.runtime_state_root)
            ),
            "updated_targets": 0,
            "updated_samples": 0,
            "significant_updates": 0,
        }

    artifact_output_dir = (
        run_session.run_dir
        if run_session is not None
        else (json_output_path.parent if json_output_path is not None else None)
    )
    artifact_index_path = write_execution_artifact_index(report, artifact_output_dir)
    if artifact_index_path is not None:
        report["execution_artifact_index_path"] = str(artifact_index_path)

    emit_progress(progress_enabled, "writing JSON report")
    written_json_path = write_json_report(
        report, json_to_stdout=json_to_stdout, json_output_path=json_output_path
    )
    selected_tests_report_base_path = resolve_selected_tests_report_base_path(
        run_session, written_json_path
    )
    if selected_tests_report_base_path is not None:
        selected_tests_path = write_selected_tests_report(
            report, selected_tests_report_base_path
        )
        if selected_tests_path is not None:
            report["selected_tests_json_path"] = str(selected_tests_path)
            if written_json_path is not None:
                write_json_report(
                    report, json_to_stdout=False, json_output_path=written_json_path
                )
    if run_session is not None:
        manifest = build_run_manifest(
            report,
            selector_repo_root=app_config.selector_repo_root or PROJECT_ROOT,
            run_store_root=app_config.run_store_root
            or default_run_store_root(PROJECT_ROOT),
            session=run_session,
            status=report["selector_run"]["status"],
            shard_mode=app_config.shard_mode,
            preflight=execution_preflight,
        )
        write_run_artifacts(run_session, report, manifest)

    if not json_to_stdout:
        emit_progress(progress_enabled, "rendering human report")
        print_executive_summary(report, written_json_path)
        print_human(report, cache_used, written_json_path)
    if execution_interrupted:
        return 130
    if args.run_now and preflight_failed:
        return 2
    if args.run_now and execution_summary and execution_summary.get("has_failures"):
        return 1
    return 0


def main_entry() -> None:
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
