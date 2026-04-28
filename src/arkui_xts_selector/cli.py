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
from bisect import bisect_right
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from configparser import ConfigParser
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Callable
from urllib.parse import urlparse

from rich import box
from rich.console import Console
from rich.padding import Padding
from rich.table import Table

from .api_lineage import ApiLineageMap, build_api_lineage_map
from .api_surface import (
    BOTH,
    DYNAMIC,
    STATIC,
    classify_ace_engine_surface,
    classify_xts_file_surface,
    classify_xts_project_surface,
    parse_query_surface_intent,
    surface_to_variants_mode,
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
    PreparedDailyArtifact,
    PreparedDailyPrebuilt,
    daily_component_candidates,
    discover_image_bundle_roots,
    derive_date_from_tag,
    is_placeholder_metadata,
    list_daily_tags,
    prepare_daily_prebuilt,
    prepare_daily_firmware,
    prepare_daily_sdk,
    resolve_daily_build,
)
from .execution import (
    RUN_PRIORITY_CHOICES,
    RUN_TOOL_CHOICES,
    SHARD_MODE_CHOICES,
    attach_execution_plan,
    build_run_target_entry,
    collect_unique_run_targets,
    execute_planned_targets,
    normalize_requested_test_names,
    preflight_execution,
    read_requested_test_names,
    resolve_devices,
)
from .flashing import flash_image_bundle
from .consumer_semantics import (
    extract_consumer_semantics,
    extract_typed_field_accesses as extract_typed_field_accesses_semantic,
)
from .run_store import (
    COMPLETED_RUN_STATUSES,
    RunSession,
    build_run_manifest,
    create_run_session,
    default_run_store_root,
    list_run_manifests,
    normalize_run_label,
    resolve_latest_run,
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
    resolve_workspace_path,
)


REPO_ROOT = discover_repo_root()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_CACHE_FILE = Path("/tmp/arkui_xts_selector_cache.json")
COMMAND_PREFIX_ENV = "ARKUI_XTS_SELECTOR_COMMAND_PREFIX"
COMMAND_MODE_ENV = "ARKUI_XTS_SELECTOR_COMMAND_MODE"


class XtsUserError(RuntimeError):
    """User-facing error with an optional recovery hint."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint or ""

    def __str__(self) -> str:
        base = super().__str__()
        if not self.hint:
            return base
        return f"{base}\n  Hint: {self.hint}"


@dataclass(frozen=True)
class XtsWorkspaceSnapshot:
    signature: str
    newest_mtime_ns: int


def default_cache_path(xts_root: Path) -> Path:
    """Generate workspace-specific cache path to avoid race conditions."""
    workspace_hash = hashlib.sha256(str(xts_root.resolve()).encode()).hexdigest()[:12]
    return Path(f"/tmp/arkui_xts_selector_cache_{workspace_hash}.json")


def default_cache_meta_path(cache_file: Path) -> Path:
    return cache_file.with_name(cache_file.name + ".meta.json")


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
IMPORT_BINDING_RE = re.compile(r"""import\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""", re.S)
DEFAULT_IMPORT_RE = re.compile(r"""import\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+['"]([^'"]+)['"]""")
IDENTIFIER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\s*\(""")
MEMBER_CALL_RE = re.compile(r"""\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
WORD_RE = re.compile(r"""\b[A-Za-z_][A-Za-z0-9_]{2,}\b""")
PARAM_TYPE_RE = re.compile(r"""[\(,]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Z][A-Za-z0-9_]*)\b""")
VAR_TYPE_RE = re.compile(r"""\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Z][A-Za-z0-9_]*)\b""")
MEMBER_ACCESS_RE = re.compile(r"""\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()""")
TYPED_OBJECT_LITERAL_RE = re.compile(
    r"""\b(?:const|let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*([A-Z][A-Za-z0-9_]*)\s*=\s*\{(?P<body>[^{}]*)\}""",
    re.S,
)
OBJECT_LITERAL_FIELD_RE = re.compile(r"""\b([A-Za-z_][A-Za-z0-9_]*)\s*:""")
OHOS_MODULE_RE = re.compile(r"""@ohos\.[A-Za-z0-9._]+""")
CPP_IDENTIFIER_RE = re.compile(r"""\b[A-Z][A-Za-z0-9_]{2,}\b""")
TYPE_MEMBER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
EXPORT_CLASS_RE = re.compile(r"""\bexport\s+class\s+([A-Z][A-Za-z0-9_]*)\b""")
EXPORT_INTERFACE_RE = re.compile(r"""\bexport\s+interface\s+([A-Z][A-Za-z0-9_]*)\b""")
EXPORT_INTERFACE_BLOCK_RE = re.compile(
    r"""\bexport\s+(?:declare\s+)?interface\s+([A-Z][A-Za-z0-9_]*)[^{]*\{(?P<body>.*?)\}""",
    re.S,
)
INTERFACE_PROPERTY_RE = re.compile(r"""^\s*(?:readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)\??\s*:\s*[^;{}]+;?\s*$""", re.M)
INTERFACE_METHOD_RE = re.compile(r"""^\s*(?:readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*:\s*[^;]+;?\s*$""", re.M)
PUBLIC_METHOD_RE = re.compile(r"""\bpublic\s+(?:static\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
UNIFIED_DIFF_HUNK_RE = re.compile(r"""^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@""", re.M)
GENERATED_ACCESSOR_NAMESPACE_RE = re.compile(r"""GeneratedModifier::([A-Za-z_][A-Za-z0-9_]*)Accessor\b""")
GET_ACCESSOR_RE = re.compile(r"""\bGet([A-Za-z_][A-Za-z0-9_]*)Accessor\s*\(""")
PEER_INCLUDE_RE = re.compile(r"#include\s+\"[^\"]*/([a-z0-9_]+)_peer\.h\"")
DYNAMIC_MODULE_RE = re.compile(r"""GetDynamicModule\("([A-Za-z0-9_]+)"\)""")
DECLARE_INTERFACE_RE = re.compile(r"""\bdeclare\s+interface\s+([A-Z][A-Za-z0-9_]*)\b""")
DECLARE_TYPE_RE = re.compile(r"""\bdeclare\s+(?:type|typedef)\s+([A-Z][A-Za-z0-9_]*)\b""")
DECLARE_FUNCTION_RE = re.compile(r"""\bdeclare\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
DECLARE_MODULE_RE = re.compile(r"""declare\s+module\s+['"]([^'"]+)['"]""")
TS_EXPORT_TYPE_RE = re.compile(r"""\bexport\s+(?:type|interface|class|const|function)\s+([A-Za-z_][A-Za-z0-9_]*)\b""")
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
CPP_METHOD_DEF_RE = re.compile(r"""(\b[A-Z][A-Za-z0-9_]{2,})::([A-Z][A-Za-z0-9_]{2,})\s*\(""")
TYPED_ATTRIBUTE_MODIFIER_RE = re.compile(r"""AttributeModifier<([A-Za-z_][A-Za-z0-9_]*)Attribute>""")
EXTENDS_MODIFIER_RE = re.compile(r"""extends\s+([A-Za-z_][A-Za-z0-9_]*)Modifier\b""")
HOOK_CONTENT_MODIFIER_RE = re.compile(r"""\bhook([A-Za-z0-9]+)ContentModifier\b""")
IDL_CONTENT_MODIFIER_RE = re.compile(r"""\b(?:reset)?contentModifier([A-Za-z0-9]+)\b""")
CONTENT_MODIFIER_CUSTOM_RE = re.compile(r"""GetCustomModifier\("contentModifier"\)""")
INCLUDE_PATTERN_COMPONENT_RE = re.compile(r"""pattern/([^/]+)/""")
REASON_SYMBOL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\b""")


def compact_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def normalize_family_name(value: str) -> str:
    lowered = value.lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "", lowered).strip("_")


def normalize_capability_name(value: str) -> str:
    lowered = value.lower().replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9_.]+", "", lowered).strip("_.")
    return re.sub(r"_+", "_", normalized)


@dataclass
class RankingRulesConfig:
    generic_path_tokens: set[str] = field(default_factory=set)
    generic_scope_tokens: set[str] = field(default_factory=set)
    low_signal_specificity_tokens: set[str] = field(default_factory=set)
    generic_coverage_extra_tokens: set[str] = field(default_factory=set)
    coverage_family_group_overrides: dict[str, str] = field(default_factory=dict)
    coverage_capability_group_overrides: dict[str, str] = field(default_factory=dict)
    scope_gain_multiplier: dict[str, float] = field(default_factory=dict)
    bucket_gain_multiplier: dict[str, float] = field(default_factory=dict)
    umbrella_marker_penalties: dict[str, float] = field(default_factory=dict)
    umbrella_family_count_threshold: int = 4
    umbrella_family_count_penalty: float = 0.05
    umbrella_family_count_penalty_cap: float = 0.25
    umbrella_penalty_cap: float = 0.75
    umbrella_min_factor: float = 0.25
    family_quality_project_tokens: float = 0.45
    family_quality_related_file_path: float = 0.12
    family_quality_direct_file_path: float = 0.28
    family_quality_direct_reason_tokens: float = 0.35
    family_quality_direct_single_family_bonus: float = 0.2
    family_quality_direct_small_family_bonus: float = 0.15
    family_quality_maximum: float = 2.4
    family_gain_direct_base: float = 1.0
    family_gain_related_base: float = 0.45
    family_gain_min_direct_quality: float = 0.55
    family_gain_min_related_quality: float = 0.45
    representative_project_family_hit: float = 0.15
    representative_file_family_hit: float = 0.12
    representative_reason_family_hit: float = 0.16
    representative_direct_file_hit: float = 0.22
    representative_direct_family_bonus: float = 0.3
    representative_single_family_bonus: float = 0.2
    representative_small_family_bonus: float = 0.12
    representative_source_token_overlap_weight: float = 0.12
    representative_source_token_overlap_cap: float = 0.6
    representative_extra_family_penalty: float = 0.06
    representative_extra_family_penalty_cap: float = 0.3
    representative_umbrella_penalty_weight: float = 0.75
    representative_direct_overlap_multiplier: float = 1.0
    representative_related_overlap_multiplier: float = 0.68
    representative_minimum_quality: float = 0.2
    representative_maximum_quality: float = 3.6
    planner_fallback_no_family_gain: float = 0.1
    rank_weight_power: float = 1.0
    rank_weight_floor: int = 1
    family_fanout_limits: dict[str, dict[str, int]] = field(default_factory=dict)
    precision_budget: dict[str, int] = field(default_factory=dict)


def _normalize_token_set(values: Iterable[object]) -> set[str]:
    normalized: set[str] = set()
    for item in values:
        token = compact_token(str(item))
        if token:
            normalized.add(token)
    return normalized


def default_ranking_rules_file() -> Path | None:
    candidate = DEFAULT_CONFIG_DIR / "ranking_rules.json"
    return candidate if candidate.exists() else None


def load_ranking_rules_config(path: Path | None) -> RankingRulesConfig:
    if not path or not path.exists():
        return RankingRulesConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid ranking rules json in {path}: {exc}") from exc
    generic_tokens = data.get("generic_tokens", {})
    umbrella_penalties = data.get("umbrella_penalties", {})
    family_quality = data.get("family_quality", {})
    representative_quality = data.get("representative_quality", {})
    planner = data.get("planner", {})
    raw_family_groups = data.get("coverage_family_groups", {})
    raw_capability_groups = data.get("coverage_capability_groups", {})
    family_groups = {
        compact_token(str(key)): normalize_family_name(str(value))
        for key, value in raw_family_groups.items()
        if compact_token(str(key)) and normalize_family_name(str(value))
    }
    capability_groups = {
        compact_token(str(key)): normalize_capability_name(str(value))
        for key, value in raw_capability_groups.items()
        if compact_token(str(key)) and normalize_capability_name(str(value))
    }
    return RankingRulesConfig(
        generic_path_tokens=_normalize_token_set(generic_tokens.get("path", [])),
        generic_scope_tokens=_normalize_token_set(generic_tokens.get("scope", [])),
        low_signal_specificity_tokens=_normalize_token_set(generic_tokens.get("low_signal_specificity", [])),
        generic_coverage_extra_tokens=_normalize_token_set(generic_tokens.get("coverage_extra", [])),
        coverage_family_group_overrides=family_groups,
        coverage_capability_group_overrides=capability_groups,
        scope_gain_multiplier={str(key): float(value) for key, value in dict(data.get("scope_gain_multiplier", {})).items()},
        bucket_gain_multiplier={str(key): float(value) for key, value in dict(data.get("bucket_gain_multiplier", {})).items()},
        umbrella_marker_penalties={
            compact_token(str(key)): float(value)
            for key, value in dict(umbrella_penalties.get("markers", {})).items()
            if compact_token(str(key))
        },
        umbrella_family_count_threshold=max(0, int(umbrella_penalties.get("family_count_threshold", 4) or 0)),
        umbrella_family_count_penalty=float(umbrella_penalties.get("family_count_penalty", 0.05) or 0.0),
        umbrella_family_count_penalty_cap=float(umbrella_penalties.get("family_count_penalty_cap", 0.25) or 0.0),
        umbrella_penalty_cap=float(umbrella_penalties.get("penalty_cap", 0.75) or 0.0),
        umbrella_min_factor=float(umbrella_penalties.get("minimum_factor", 0.25) or 0.0),
        family_quality_project_tokens=float(family_quality.get("project_tokens", 0.45) or 0.0),
        family_quality_related_file_path=float(family_quality.get("related_file_path", 0.12) or 0.0),
        family_quality_direct_file_path=float(family_quality.get("direct_file_path", 0.28) or 0.0),
        family_quality_direct_reason_tokens=float(family_quality.get("direct_reason_tokens", 0.35) or 0.0),
        family_quality_direct_single_family_bonus=float(family_quality.get("direct_single_family_bonus", 0.2) or 0.0),
        family_quality_direct_small_family_bonus=float(family_quality.get("direct_small_family_bonus", 0.15) or 0.0),
        family_quality_maximum=float(family_quality.get("maximum_quality", 2.4) or 0.0),
        family_gain_direct_base=float(family_quality.get("direct_gain_base", 1.0) or 0.0),
        family_gain_related_base=float(family_quality.get("related_gain_base", 0.45) or 0.0),
        family_gain_min_direct_quality=float(family_quality.get("minimum_direct_quality", 0.55) or 0.0),
        family_gain_min_related_quality=float(family_quality.get("minimum_related_quality", 0.45) or 0.0),
        representative_project_family_hit=float(representative_quality.get("project_family_hit", 0.15) or 0.0),
        representative_file_family_hit=float(representative_quality.get("file_family_hit", 0.12) or 0.0),
        representative_reason_family_hit=float(representative_quality.get("reason_family_hit", 0.16) or 0.0),
        representative_direct_file_hit=float(representative_quality.get("direct_file_hit", 0.22) or 0.0),
        representative_direct_family_bonus=float(representative_quality.get("direct_family_bonus", 0.3) or 0.0),
        representative_single_family_bonus=float(representative_quality.get("single_family_bonus", 0.2) or 0.0),
        representative_small_family_bonus=float(representative_quality.get("small_family_bonus", 0.12) or 0.0),
        representative_source_token_overlap_weight=float(representative_quality.get("source_token_overlap_weight", 0.12) or 0.0),
        representative_source_token_overlap_cap=float(representative_quality.get("source_token_overlap_cap", 0.6) or 0.0),
        representative_extra_family_penalty=float(representative_quality.get("extra_family_penalty", 0.06) or 0.0),
        representative_extra_family_penalty_cap=float(representative_quality.get("extra_family_penalty_cap", 0.3) or 0.0),
        representative_umbrella_penalty_weight=float(representative_quality.get("umbrella_penalty_weight", 0.75) or 0.0),
        representative_direct_overlap_multiplier=float(representative_quality.get("direct_overlap_multiplier", 1.0) or 0.0),
        representative_related_overlap_multiplier=float(representative_quality.get("related_overlap_multiplier", 0.68) or 0.0),
        representative_minimum_quality=float(representative_quality.get("minimum_quality", 0.2) or 0.0),
        representative_maximum_quality=float(representative_quality.get("maximum_quality", 3.6) or 0.0),
        planner_fallback_no_family_gain=float(planner.get("fallback_no_family_gain", 0.1) or 0.0),
        rank_weight_power=float(planner.get("rank_weight_power", 1.0) or 1.0),
        rank_weight_floor=max(1, int(planner.get("rank_weight_floor", 1) or 1)),
        family_fanout_limits={
            str(k): {str(kk): int(vv) for kk, vv in dict(v).items()}
            for k, v in dict(data.get("family_fanout_limits", {})).items()
        },
        precision_budget={
            str(k): int(v) for k, v in dict(data.get("precision_budget", {})).items()
        },
    )


ACTIVE_RANKING_RULES = RankingRulesConfig()
UBIQUITOUS_BASES = {"button", "text", "column", "row", "toggle", "stack", "flex"}
COMMON_PROJECT_HINTS = ("commonattrs", "modifier", "interactiveattributes", "dragcontrol", "focuscontrol")
LOW_SIGNAL_SPECIFICITY_TOKENS: set[str] = set()
GENERIC_SCOPE_TOKENS: set[str] = set()
PRIMARY_SCOPE_TIERS = {"direct", "focused"}
SCOPE_TIER_ORDER = {"direct": 0, "focused": 1, "broad": 2}
BUCKET_ORDER = {"must-run": 0, "high-confidence related": 1, "possible related": 2}
GENERIC_PATH_TOKENS: set[str] = set()
CONTENT_MODIFIER_NOISE = {
    "accessor", "builder", "commonview", "configuration", "content", "helper",
    "implementation", "modifier", "native",
}

SPECIAL_PATH_RULES = {
    "componentutils": {
        "modules": ["@ohos.arkui.componentUtils"],
        "symbols": ["componentUtils", "ComponentUtils"],
    },
    "overlaymanager": {
        "modules": ["@ohos.overlayManager", "@ohos.arkui.UIContext"],
        "symbols": ["overlayManager", "OverlayManager", "UIContext"],
    },
    "promptaction": {
        "modules": ["@ohos.promptAction"],
        "symbols": ["promptAction", "AlertDialog", "ActionSheet", "CustomDialog"],
    },
    "ohosprompt": {
        "modules": ["@ohos.prompt"],
        "symbols": ["prompt", "Prompt"],
    },
    "prefetcher": {
        "modules": ["@ohos.arkui.Prefetcher"],
        "symbols": ["BasicPrefetcher", "IPrefetcher", "IDataSourcePrefetching"],
    },
    "shape": {
        "modules": ["@ohos.arkui.shape"],
        "symbols": ["Shape", "RectShape", "CircleShape", "EllipseShape", "PathShape"],
    },
    "matrix4": {
        "modules": ["@ohos.matrix4"],
        "symbols": ["Matrix4"],
    },
    "displaysync": {
        "symbols": ["DisplaySync", "SwiperDynamicSyncScene", "MarqueeDynamicSyncScene"],
    },
    "scrollable": {
        "symbols": ["Scroll", "List", "Grid", "WaterFlow", "Scroller",
                     "ScrollModifier", "ListModifier", "GridModifier", "WaterFlowModifier"],
        "project_hints": ["scroll", "list", "grid", "waterflow"],
    },
    "textfield": {
        "symbols": ["TextInput", "TextArea", "TextInputModifier", "TextAreaModifier"],
        "project_hints": ["textinput", "textarea"],
    },
    "textdrag": {
        "symbols": ["Text", "TextInput", "RichEditor"],
        "project_hints": ["text", "textinput", "richeditor"],
    },
    "scrollbar": {
        "symbols": ["ScrollBar", "Scroll", "Scroller"],
        "project_hints": ["scroll", "scrollbar"],
    },
    "swiperindicator": {
        "symbols": ["Swiper", "SwiperModifier"],
        "project_hints": ["swiper"],
    },
    "selectcontentoverlay": {
        "symbols": ["Select", "SelectModifier"],
        "project_hints": ["select"],
    },
    "selectoverlay": {
        "symbols": ["Select", "SelectModifier"],
        "project_hints": ["select"],
    },
    "formbutton": {
        "symbols": ["FormComponent", "FormLink"],
        "project_hints": ["form"],
    },
}

PATTERN_ALIAS = {
    # --- Already present ---
    "button":       ["Button", "ButtonModifier", "Toggle", "ToggleModifier", "ToggleButton"],
    "toggle":       ["Toggle", "ToggleModifier", "ToggleButton"],
    "text":         ["Text", "Span", "TextModifier", "SpanModifier", "ContainerSpanModifier"],
    "text_input":   ["TextInput", "TextInputModifier"],
    "text_area":    ["TextArea", "TextAreaModifier"],
    "text_clock":   ["TextClock", "TextClockModifier"],
    "text_picker":  ["TextPicker", "TextPickerModifier"],
    "list":         ["List", "ListItem", "ListItemGroup", "ListModifier", "ListItemModifier", "ListItemGroupModifier"],
    "grid":         ["Grid", "GridModifier", "GridItem", "GridItemModifier"],
    "grid_row":     ["GridRow", "GridRowModifier"],
    "grid_col":     ["GridCol", "GridColModifier"],
    "navigation":   ["Navigation", "Navigator", "NavDestination", "NavRouter",
                     "NavigationModifier", "NavDestinationModifier", "NavigatorModifier"],
    "search":       ["Search", "SearchModifier"],
    "swiper":       ["Swiper", "SwiperModifier"],
    "rich_editor":  ["RichEditor", "RichEditorModifier", "SelectionMenu"],
    "dialog":       ["Dialog", "AlertDialog", "ActionSheet", "CustomDialog", "promptAction"],
    "overlay":      ["OverlayManager", "bindOverlay", "bindPopup", "bindSheet"],
    # --- New entries based on SDK arkui/ Modifier declarations ---
    "slider":               ["Slider", "SliderModifier"],
    "image":                ["Image", "ImageModifier", "ImageSpanModifier"],
    "image_animator":       ["ImageAnimator", "ImageAnimatorModifier"],
    "checkbox":             ["Checkbox", "CheckboxModifier"],
    "checkboxgroup":        ["CheckboxGroup", "CheckboxGroupModifier"],
    "radio":                ["Radio", "RadioModifier"],
    "rating":               ["Rating", "RatingModifier"],
    "progress":             ["Progress", "ProgressModifier"],
    "loading_progress":     ["LoadingProgress", "LoadingProgressModifier"],
    "gauge":                ["Gauge", "GaugeModifier"],
    "data_panel":           ["DataPanel", "DataPanelModifier"],
    "marquee":              ["Marquee", "MarqueeModifier"],
    "qrcode":               ["QRCode", "QRCodeModifier"],
    "badge":                ["Badge"],
    "select":               ["Select", "SelectModifier"],
    "video":                ["Video", "VideoModifier"],
    "canvas":               ["Canvas"],
    "tabs":                 ["Tabs", "TabContent", "TabsModifier"],
    "waterflow":            ["WaterFlow", "WaterFlowModifier"],
    "refresh":              ["Refresh", "RefreshModifier"],
    "scroll":               ["Scroll", "ScrollModifier", "Scroller"],
    "indexer":              ["AlphabetIndexer", "AlphabetIndexerModifier"],
    "patternlock":          ["PatternLock", "PatternLockModifier"],
    "picker":               ["DatePicker", "DatePickerModifier"],
    "calendar":             ["Calendar"],
    "calendar_picker":      ["CalendarPicker", "CalendarPickerModifier"],
    "time_picker":          ["TimePicker", "TimePickerModifier"],
    "texttimer":            ["TextTimer", "TextTimerModifier"],
    "counter":              ["Counter", "CounterModifier"],
    "divider":              ["Divider", "DividerModifier"],
    "blank":                ["Blank", "BlankModifier"],
    "hyperlink":            ["Hyperlink", "HyperlinkModifier"],
    "side_bar":             ["SideBarContainer", "SideBarContainerModifier"],
    "linear_layout":        ["Column", "Row", "ColumnModifier", "RowModifier"],
    "flex":                 ["Flex", "FlexModifier"],
    "stack":                ["Stack", "StackModifier"],
    "linear_split":         ["ColumnSplit", "RowSplit", "ColumnSplitModifier", "RowSplitModifier"],
    "stepper":              ["Stepper", "StepperItem", "StepperModifier", "StepperItemModifier"],
    "panel":                ["Panel", "PanelModifier"],
    "particle":             ["Particle", "ParticleModifier"],
    "menu":                 ["Menu", "MenuItem", "MenuItemGroup", "MenuModifier", "MenuItemModifier"],
    "relative_container":   ["RelativeContainer"],
    # --- NEW ENTRIES: HIGH priority (SDK declarations + XTS tests) ---
    "gesture":              ["GestureGroup", "TapGesture", "LongPressGesture",
                             "PanGesture", "PinchGesture", "RotationGesture", "SwipeGesture"],
    "xcomponent":           ["XComponent", "XComponentController"],
    "web":                  ["Web", "WebviewController"],
    "form":                 ["FormComponent", "FormLink"],
    "folder_stack":         ["FolderStack"],
    "animator":             ["Animator"],
    "scroll_bar":           ["ScrollBar"],
    "toast":                ["promptAction"],
    "sheet":                ["bindSheet", "SheetSize"],
    "action_sheet":         ["ActionSheet"],
    "bubble":               ["Popup", "bindPopup"],
    "symbol":               ["SymbolGlyph", "SymbolSpan", "SymbolSpanModifier"],
    "security_component":   ["LocationButton", "PasteButton", "SaveButton"],
    "navrouter":            ["NavRouter", "NavDestination"],
    "navigator":            ["Navigator"],
    "toolbaritem":          ["ToolBar", "ToolBarItem"],
    # --- NEW ENTRIES: MEDIUM priority (internal, but XTS-linked) ---
    "text_field":           ["TextInput", "TextArea", "TextInputModifier", "TextAreaModifier"],
    "scrollable":           ["Scroll", "List", "Grid", "WaterFlow"],
    "node_container":       ["NodeContainer"],
    "effect_component":     ["EffectComponent"],
    "form_link":            ["FormLink"],
    "grid_container":       ["GridContainer"],
    "swiper_indicator":     ["Swiper", "SwiperModifier"],
    "render_node":          ["RenderNode", "FrameNode", "BuilderNode"],
}

GENERIC_COVERAGE_TOKENS: set[str] = set()
COVERAGE_FAMILY_GROUP_OVERRIDES: dict[str, str] = {}
COVERAGE_CAPABILITY_GROUP_OVERRIDES: dict[str, str] = {}
SCOPE_GAIN_MULTIPLIER: dict[str, float] = {}
BUCKET_GAIN_MULTIPLIER: dict[str, float] = {}

DEFAULT_COMPOSITE_MAPPINGS = {
    "content_modifier_helper_accessor": {
        "families": [
            "button", "checkbox", "checkboxgroup", "datapanel", "gauge",
            "loadingprogress", "menuitem", "progress", "radio", "rating",
            "select", "slider", "textclock", "texttimer", "toggle",
        ],
        "project_hints": ["contentmodifier"],
        "method_hints": ["contentModifier"],
        "type_hints": ["ContentModifier"],
        "symbols": ["ContentModifier"],
        "method_hint_required": True,
    },
    "common_method_modifier": {
        "project_hints": list(COMMON_PROJECT_HINTS),
        "symbols": ["CommonModifier", "ModifierUtils"],
    },
    "common_view_model_ng": {
        "project_hints": ["commonattrs"],
        "symbols": ["CommonModifier", "ModifierUtils"],
    },
}


def snake_to_pascal(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\-.]+", name) if part)


def pascal_to_snake(name: str) -> str:
    """Convert PascalCase to lowercase (component name format).

    This is used for component names where the convention is to lowercase
    PascalCase without inserting underscores, matching the pattern used in
    ark_direct_component file names (e.g., datapanel, patternlock, textclock).

    Examples:
        ArkCheckbox -> checkbox
        ArkDataPanel -> datapanel
        ArkPatternLock -> patternlock
        ArkSymbolGlyph -> symbolglyph
        ArkTextClock -> textclock
        ArkRichEditor -> richeditor
    """
    # Simply lowercase the string
    return name.lower()


# ---------------------------------------------------------------------------
# Tree-sitter C++ / TypeScript tracing for shared files and generated .ets
# ---------------------------------------------------------------------------
# These functions use tree-sitter to:
# 1. Build an index of (component, SetXxxImpl) → [called symbols] from
#    *_static_modifier.cpp files.
# 2. Trace shared headers (converter.h, callback_helper.h, etc.) through
#    call chains to discover affected components.
# 3. Trace generated .ets files to extract SDK API method names from
#    changed ranges.

_TS_CPP_PARSER: "tree_sitter.Parser | None" = None
_TS_CPP_LANG: "tree_sitter.Language | None" = None
_TS_TS_PARSER: "tree_sitter.Parser | None" = None
_TS_TS_LANG: "tree_sitter.Language | None" = None
_TS_SM_INDEX: dict[str, dict[str, list[str]]] | None = None
"""Cache: basename -> {func_name -> [called_symbols]} for static modifier files."""


def _get_ts_cpp_parser() -> tuple["tree_sitter.Parser", "tree_sitter.Language"]:
    """Return a lazily-initialized tree-sitter C++ parser."""
    global _TS_CPP_PARSER, _TS_CPP_LANG
    if _TS_CPP_PARSER is None:
        import tree_sitter as ts
        import tree_sitter_cpp as tscpp
        _TS_CPP_LANG = ts.Language(tscpp.language())
        _TS_CPP_PARSER = ts.Parser(_TS_CPP_LANG)
    return _TS_CPP_PARSER, _TS_CPP_LANG


def _get_ts_ts_parser() -> tuple["tree_sitter.Parser", "tree_sitter.Language"]:
    """Return a lazily-initialized tree-sitter TypeScript parser."""
    global _TS_TS_PARSER, _TS_TS_LANG
    if _TS_TS_PARSER is None:
        import tree_sitter as ts
        import tree_sitter_typescript as tsts
        _TS_TS_LANG = ts.Language(tsts.language_typescript())
        _TS_TS_PARSER = ts.Parser(_TS_TS_LANG)
    return _TS_TS_PARSER, _TS_TS_LANG


def _ts_extract_func_name(decl_node, code_bytes: bytes) -> str | None:
    """Extract the function name from a function_declarator node.

    Handles simple identifiers (foo), qualified identifiers (Class::foo),
    and complex qualified identifiers with templates (std::optional<T> foo).
    Always returns the rightmost simple identifier.
    """
    for child in decl_node.children:
        if child.type == "identifier":
            return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
        if child.type == "field_identifier":
            return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
        if child.type == "qualified_identifier":
            # Find the rightmost simple identifier child
            raw = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
            if "::" in raw:
                # For complex qualified identifiers like "std::optional<T> FuncName",
                # extract the last simple identifier by walking child nodes
                def _find_last_identifier(node):
                    best = None
                    for c in node.children:
                        if c.type == "identifier":
                            best = code_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="replace")
                        sub = _find_last_identifier(c)
                        if sub:
                            best = sub
                    return best
                last_id = _find_last_identifier(child)
                if last_id:
                    return last_id
            return raw
    return None


def _ts_extract_calls(node, code_bytes: bytes) -> list[str]:
    """Extract all call expression callee names from a subtree."""
    calls: list[str] = []
    def walk(n):
        if n.type == "call_expression":
            callee = n.child_by_field_name("function")
            if callee:
                name = code_bytes[callee.start_byte:callee.end_byte].decode("utf-8", errors="replace")
                if "::" in name:
                    name = name.rsplit("::", 1)[-1]
                calls.append(name)
        for child in n.children:
            walk(child)
    walk(node)
    return calls


def _ts_collect_functions(root_node, code_bytes: bytes) -> dict[str, list[str]]:
    """Walk AST and collect {func_name: [called_symbols]} for all function definitions."""
    result: dict[str, list[str]] = {}

    def visit(node):
        if node.type == "function_definition":
            name = None
            body = None
            for child in node.children:
                if child.type == "function_declarator":
                    name = _ts_extract_func_name(child, code_bytes)
                elif child.type == "compound_statement":
                    body = child
            if name and body:
                calls = _ts_extract_calls(body, code_bytes)
                result[name] = calls
        for child in node.children:
            visit(child)

    visit(root_node)
    return result


def _ts_get_static_modifier_index(repo_root: Path) -> dict[str, dict[str, list[str]]]:
    """Build and cache an index of static modifier files -> {func: [calls]}.

    Returns {component_name: {SetXxxImpl: [called_symbol, ...]}} where
    component_name is extracted from the directory path
    (e.g., checkbox from pattern/checkbox/bridge/checkbox_static_modifier.cpp).
    """
    global _TS_SM_INDEX
    if _TS_SM_INDEX is not None:
        return _TS_SM_INDEX

    parser, _ = _get_ts_cpp_parser()
    index: dict[str, dict[str, list[str]]] = {}

    # Walk pattern/*/bridge/*_static_modifier.cpp
    bridge_base = repo_root / "frameworks" / "core" / "components_ng" / "pattern"
    if not bridge_base.is_dir():
        _TS_SM_INDEX = index
        return index

    for bridge_dir in sorted(bridge_base.iterdir()):
        bridge_sub = bridge_dir / "bridge"
        if not bridge_sub.is_dir():
            continue
        for sm_file in sorted(bridge_sub.glob("*_static_modifier.cpp")):
            component = sm_file.name.replace("_static_modifier.cpp", "")
            try:
                code = sm_file.read_bytes()
            except OSError:
                continue
            tree = parser.parse(code)
            funcs = _ts_collect_functions(tree.root_node, code)
            if funcs:
                index[component] = funcs

    _TS_SM_INDEX = index
    return index


def _impl_to_sdk_method(impl_name: str) -> str | None:
    """Convert a SetXxxImpl C++ function name to an SDK method name.

    SetSelectedColorImpl -> selectedColor
    SetSelectImpl -> select
    SetCheckboxOptionsImpl -> None (not a setter attribute)
    ConstructImpl -> None
    """
    if not impl_name.startswith("Set"):
        return None
    name = impl_name[3:]
    if name.endswith("Impl"):
        name = name[:-4]
    if not name:
        return None
    # First character lowercase: SelectedColor -> selectedColor
    return name[0].lower() + name[1:]


def trace_shared_file_to_components(
    changed_file: Path,
    changed_ranges: list[tuple[int, int]] | None,
    repo_root: Path,
) -> dict[str, list[str]] | None:
    """Trace a shared C++ header to discover affected components and methods.

    Returns {component_name: [sdk_method_name, ...]} or None if the file
    is not a traceable shared header or tree-sitter is unavailable.

    This works by:
    1. Parsing the changed header with tree-sitter C++ to extract function
       names defined in changed line ranges.
    2. Looking up the static modifier index to find which components' Set*Impl
       functions call those extracted symbols.
    3. Converting SetXxxImpl names to SDK method names.
    """
    # Only trace well-known shared infrastructure headers
    try:
        rel = changed_file.relative_to(repo_root)
    except ValueError:
        return None
    rel_str = str(rel).replace("\\", "/")
    rel_lower = rel_str.lower()

    # Recognized shared header directories/patterns
    shared_patterns = (
        "core/interfaces/native/utility/",
        "core/interfaces/native/ace/",
        "core/common/",
    )
    if not any(p in rel_lower for p in shared_patterns):
        return None

    # Must be a header file
    if changed_file.suffix.lower() not in (".h", ".hpp", ".hh"):
        return None

    try:
        parser, lang = _get_ts_cpp_parser()
    except ImportError:
        return None

    try:
        code = changed_file.read_bytes()
    except OSError:
        return None

    tree = parser.parse(code)

    # Extract all function/declaration names from changed ranges
    # If no ranges provided, extract all top-level names
    defined_symbols: set[str] = set()

    if changed_ranges:
        # Convert to byte ranges for tree-sitter
        lines = code.split(b"\n")
        byte_offsets: list[int] = []
        offset = 0
        for line in lines:
            byte_offsets.append(offset)
            offset += len(line) + 1  # +1 for \n

        for start_line, end_line in changed_ranges:
            # tree-sitter uses 0-based rows; changed_ranges are 1-based
            start_row = max(0, start_line - 1)
            end_row = end_line  # exclusive in our range
            start_byte = byte_offsets[start_row] if start_row < len(byte_offsets) else len(code)
            end_byte = byte_offsets[end_row] if end_row < len(byte_offsets) else len(code)

            # Find nodes overlapping with the changed range
            def collect_names(node):
                if (
                    node.start_byte >= end_byte
                    or node.end_byte <= start_byte
                    or node.start_point[0] > end_row
                    or node.end_point[0] < start_row
                ):
                    return
                if node.type in ("function_definition", "declaration"):
                    for child in node.children:
                        if child.type == "function_declarator":
                            name = _ts_extract_func_name(child, code)
                            if name:
                                defined_symbols.add(name)
                        elif child.type in ("identifier", "qualified_identifier"):
                            defined_symbols.add(
                                code[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                            )
                for child in node.children:
                    collect_names(child)

            collect_names(tree.root_node)
    else:
        # No ranges: extract all function/declaration names from the file
        def collect_all_names(node):
            if node.type in ("function_definition", "declaration"):
                for child in node.children:
                    if child.type == "function_declarator":
                        name = _ts_extract_func_name(child, code)
                        if name:
                            defined_symbols.add(name)
                    elif child.type in ("identifier", "qualified_identifier"):
                        defined_symbols.add(
                            code[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                        )
            for child in node.children:
                collect_all_names(child)

        collect_all_names(tree.root_node)

    if not defined_symbols:
        return None

    # Look up which components' static modifier functions call these symbols
    sm_index = _ts_get_static_modifier_index(repo_root)
    result: dict[str, list[str]] = {}

    for component, funcs in sm_index.items():
        matched_methods: list[str] = []
        for func_name, calls in funcs.items():
            # Check if any of the defined symbols are called in this function
            if defined_symbols & set(calls):
                sdk_method = _impl_to_sdk_method(func_name)
                if sdk_method:
                    matched_methods.append(sdk_method)
        if matched_methods:
            result[component] = sorted(set(matched_methods))

    return result if result else None


def _ts_find_component_methods(
    root_node, code_bytes: bytes, changed_ranges: list[tuple[int, int]] | None,
) -> list[str]:
    """Find SDK method names in a generated .ets file using tree-sitter TS.

    Looks for class methods (e.g., onChange, selectedColor) in ArkXxx classes,
    optionally limited to changed line ranges.
    """
    methods: list[str] = []

    def visit(node):
        # Look for method signatures within classes
        if node.type == "public_field_definition" or node.type == "method_definition":
            # Get the name
            name_node = node.child_by_field_name("name")
            if name_node:
                method_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                # Skip private/internal methods
                if method_name and not method_name.startswith("_"):
                    if changed_ranges:
                        # Check if this node overlaps with any changed range
                        start_line = node.start_point[0] + 1  # 1-based
                        end_line = node.end_point[0] + 1
                        for rs, re_ in changed_ranges:
                            if start_line <= re_ and end_line >= rs:
                                methods.append(method_name)
                                break
                    else:
                        methods.append(method_name)
        for child in node.children:
            visit(child)

    visit(root_node)
    return methods


def trace_generated_ets_to_methods(
    changed_file: Path,
    changed_ranges: list[tuple[int, int]] | None,
) -> list[str] | None:
    """Trace a generated .ets file to extract SDK method names from changed ranges.

    Returns a list of method names (e.g., ['select', 'selectedColor', 'onChange'])
    or None if tree-sitter is unavailable or the file is not a generated .ets.
    """
    rel_lower = changed_file.name.lower()
    # Only trace generated .ets files (in arkui-ohos or generated directories)
    path_str = str(changed_file).replace("\\", "/").lower()
    if not (rel_lower.endswith(".ets") and ("generated" in path_str or "arkui-ohos" in path_str)):
        return None

    try:
        parser, lang = _get_ts_ts_parser()
    except ImportError:
        return None

    try:
        code = changed_file.read_bytes()
    except OSError:
        return None

    tree = parser.parse(code)
    methods = _ts_find_component_methods(tree.root_node, code, changed_ranges)
    return methods if methods else None


# ---------------------------------------------------------------------------
# Universal symbol-to-component index for C++ files
# ---------------------------------------------------------------------------
# Scans components_ng/pattern/*/ for CamelCase identifiers and builds a
# reverse index: symbol -> set of components. At query time, symbols from
# changed C++ files are looked up to discover affected components.

_SYM_COMP_INDEX: dict[str, set[str]] | None = None
"""Cache: CamelCase symbol -> set of component names."""


def _build_symbol_component_index(repo_root: Path) -> dict[str, set[str]]:
    """Build a reverse index from CamelCase symbols to component names.

    Scans all .cpp/.h files under components_ng/pattern/*/ and collects
    CamelCase identifiers (class names, method names, etc). Returns a dict
    mapping each symbol to the set of components that reference it.
    """
    pattern_dir = repo_root / "frameworks" / "core" / "components_ng" / "pattern"
    if not pattern_dir.is_dir():
        return {}

    index: dict[str, set[str]] = {}
    _camel_re = re.compile(r"\b([A-Z][a-zA-Z]{2,})\b")

    for comp_dir in pattern_dir.iterdir():
        if not comp_dir.is_dir():
            continue
        component = comp_dir.name
        for f in comp_dir.rglob("*"):
            if f.suffix not in (".cpp", ".h", ".hpp", ".cc", ".cxx"):
                continue
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            for sym in set(_camel_re.findall(text)):
                if sym not in index:
                    index[sym] = set()
                index[sym].add(component)

    return index


def _get_symbol_component_index(repo_root: Path) -> dict[str, set[str]]:
    """Return the cached symbol-to-component index, building if needed."""
    global _SYM_COMP_INDEX
    if _SYM_COMP_INDEX is None:
        _SYM_COMP_INDEX = _build_symbol_component_index(repo_root)
    return _SYM_COMP_INDEX


def trace_symbols_to_components(
    changed_file: Path,
    changed_ranges: list[tuple[int, int]] | None,
    repo_root: Path,
) -> dict[str, int]:
    """Trace symbols from a changed C++ file to affected components.

    Extracts CamelCase identifiers from the file (optionally limited to
    changed line ranges), looks them up in the symbol-to-component index,
    and returns {component_name: hit_count} for components that reference
    the extracted symbols.

    Only returns components with ≥2 symbol matches (or ≥1 if very few
    symbols extracted), to filter noise from common infrastructure names.
    """
    try:
        parser, lang = _get_ts_cpp_parser()
    except ImportError:
        return {}

    try:
        code = changed_file.read_bytes()
    except OSError:
        return {}

    index = _get_symbol_component_index(repo_root)
    if not index:
        return {}

    tree = parser.parse(code)

    # Extract symbols from changed ranges (or full file)
    _camel_re = re.compile(r"\b([A-Z][a-zA-Z]{3,}(?:Property|Model|Modifier|Pattern|Wrapper|Node|Component|Painter|Manager|Handler|Event|Gesture|Layout|Render|Context|Animation|Thread|Engine|Service))\b")

    if changed_ranges:
        # Extract text from changed ranges only
        lines = code.decode("utf-8", errors="ignore").split("\n")
        range_texts = []
        for rs, re_ in changed_ranges:
            range_texts.append("\n".join(lines[max(0, rs - 1):re_]))
        scan_text = "\n".join(range_texts)
    else:
        scan_text = code.decode("utf-8", errors="ignore")

    # Method 1: Regex CamelCase symbols (high precision)
    regex_symbols = set(_camel_re.findall(scan_text))

    # Method 2: AST function/class names from changed ranges
    ast_symbols = set()
    if changed_ranges:
        def visit(node):
            for rs, re_ in changed_ranges:
                rs0 = rs - 1
                if node.end_point[0] < rs0 or node.start_point[0] > re_:
                    continue
                if node.type == "function_definition":
                    for child in node.children:
                        if child.type == "function_declarator":
                            name = _ts_extract_func_name(child, code)
                            if name and len(name) > 3:
                                ast_symbols.add(name)
                if node.type == "class_specifier":
                    for child in node.children:
                        if child.type == "type_identifier":
                            ast_symbols.add(
                                code[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                            )
            for child in node.children:
                visit(child)
        visit(tree.root_node)
    else:
        # Full file: extract all function/class names
        def visit_all(node):
            if node.type == "function_definition":
                for child in node.children:
                    if child.type == "function_declarator":
                        name = _ts_extract_func_name(child, code)
                        if name and len(name) > 3:
                            ast_symbols.add(name)
            if node.type == "class_specifier":
                for child in node.children:
                    if child.type == "type_identifier":
                        ast_symbols.add(
                            code[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                        )
            for child in node.children:
                visit_all(child)
        visit_all(tree.root_node)

    # Combine and filter noise
    noise = {"NULL", "CHECK", "ACE", "OHOS", "CONST", "VOID", "TAG", "FUNC", "DEBUG"}
    all_symbols = (regex_symbols | ast_symbols) - noise

    # Only keep symbols that exist in the index
    matching_symbols = {s for s in all_symbols if s in index}

    if not matching_symbols:
        return {}

    # Count component hits
    component_hits: dict[str, int] = {}
    for sym in matching_symbols:
        for comp in index.get(sym, set()):
            component_hits[comp] = component_hits.get(comp, 0) + 1

    # Filter: adaptive threshold based on how many components match.
    # Infrastructure files (FrameNode, Component, etc.) hit 50+ components.
    # We want only the most-specific matches.
    if not component_hits:
        return {}
    max_hits = max(component_hits.values())
    total_components = len(component_hits)
    if total_components > 20:
        # Too many components — only keep the top tier
        threshold = max(max_hits * 2 // 3, 3)
        return {c: cnt for c, cnt in component_hits.items() if cnt >= threshold}
    if len(matching_symbols) > 3:
        return {c: cnt for c, cnt in component_hits.items() if cnt >= 2}
    return component_hits


def resolve_ace_engine_components(rel: str) -> list[tuple[str, str]]:
    """Resolve component name(s) from ace_engine source file path.

    Uses deterministic architectural conventions:
    - components_ng/pattern/{component}/         -> {component}
    - components/{component}/                    -> {component} (old pre-ng)
    - interfaces/native/implementation/{x}_modifier.cpp -> {x} (strip _modifier)
    - interfaces/native/implementation/{x}_accessor.cpp -> {x} (strip suffix)
    - generated/component/{component}.ets        -> {component}
    - bridge/.../generated/component/{component}.ets -> {component}

    Returns list of (component_name, source) tuples, where source is one of:
    - "pattern_dir": resolved from components_ng/pattern/{component}/
    - "old_component": resolved from components/{component}/
    - "implementation": resolved from interfaces/native/implementation/
    - "generated_ets": resolved from generated/component/*.ets
    Returns empty list if no match.
    """
    rel_lower = rel.lower()

    # 1. components_ng/pattern/{component}/ — covers most C++ implementation files
    m = re.search(r"components_ng/pattern/([^/]+)/", rel)
    if m:
        component = m.group(1).lower()
        return [(component, "pattern_dir")]

    # 2. components/{component}/ — old pre-ng component directory
    m = re.search(r"core/components/([^/]+)/", rel_lower)
    if m:
        name = m.group(1)
        if name not in ("common", "declaration", "display", "coverage",
                        "foreach", "drag_bar", "box"):
            return [(name, "old_component")]
        return []

    # 3. interfaces/native/implementation/{name}_modifier.cpp
    m = re.search(r"interfaces/native/implementation/([^/]+)_modifier\.", rel_lower)
    if m:
        name = m.group(1)
        if name not in ("common", "common_method", "common_shape_method", "component_root",
                        "base", "base_shape", "ui_state"):
            return [(name, "implementation")]
        return []

    # 4. interfaces/native/implementation/{name}_ops_accessor.cpp
    m = re.search(r"interfaces/native/implementation/([^/]+)_ops_accessor\.", rel_lower)
    if m:
        name = m.group(1)
        if name not in ("common_method", "base_event", "base_gesture_event"):
            return [(name, "implementation")]
        return []

    # 5. interfaces/native/implementation/{name}_extender_accessor.cpp
    m = re.search(r"interfaces/native/implementation/([^/]+)_extender_accessor\.", rel_lower)
    if m:
        name = m.group(1)
        if name not in ("common",):
            return [(name, "implementation")]
        return []

    # 6. interfaces/native/implementation/{name}_accessor.cpp (plain accessor)
    #    These are API object accessors (canvas_gradient, alert_dialog, etc.)
    #    Strip _accessor to get the API object name.
    m = re.search(r"interfaces/native/implementation/([^/]+)_accessor\.", rel_lower)
    if m:
        name = m.group(1)
        # Skip shared/generic ones — these have no specific component
        if name not in ("base_event", "base_gesture_event", "base_shape"):
            return [(name, "implementation")]
        return []

    # 7. generated/component/{name}.ets — Arkoala generated files
    m = re.search(r"generated/component/([^/]+)\.ets", rel_lower)
    if m:
        name = m.group(1)
        if name not in ("common", "enums", "idlize", "focus", "inspector", "builder",
                        "contentslot", "units", "withtheme", "screen", "styledstring",
                        "textcommon", "imagecommon", "securitycomponent",
                        "embeddedcomponent", "uipickercomponent", "uicomponent",
                        "lazyforeach", "lazygridlayout", "flowitem"):
            return [(name, "generated_ets")]
        return []

    # 8. interfaces/native/utility/ — shared utility files, no component mapping
    if "interfaces/native/utility/" in rel_lower:
        return []

    # 9. interfaces/native/common/ — shared common files
    if "interfaces/native/common/" in rel_lower:
        return []

    return []


def apply_ranking_rules_config(config: RankingRulesConfig) -> None:
    global ACTIVE_RANKING_RULES
    global LOW_SIGNAL_SPECIFICITY_TOKENS
    global GENERIC_SCOPE_TOKENS
    global GENERIC_PATH_TOKENS
    global GENERIC_COVERAGE_TOKENS
    global COVERAGE_FAMILY_GROUP_OVERRIDES
    global COVERAGE_CAPABILITY_GROUP_OVERRIDES
    global SCOPE_GAIN_MULTIPLIER
    global BUCKET_GAIN_MULTIPLIER

    ACTIVE_RANKING_RULES = config
    LOW_SIGNAL_SPECIFICITY_TOKENS = set(config.low_signal_specificity_tokens)
    GENERIC_SCOPE_TOKENS = set(config.generic_scope_tokens)
    GENERIC_PATH_TOKENS = set(config.generic_path_tokens)
    GENERIC_COVERAGE_TOKENS = (
        GENERIC_PATH_TOKENS
        | GENERIC_SCOPE_TOKENS
        | LOW_SIGNAL_SPECIFICITY_TOKENS
        | set(config.generic_coverage_extra_tokens)
    )
    COVERAGE_FAMILY_GROUP_OVERRIDES = dict(config.coverage_family_group_overrides)
    COVERAGE_CAPABILITY_GROUP_OVERRIDES = dict(config.coverage_capability_group_overrides)
    SCOPE_GAIN_MULTIPLIER = dict(config.scope_gain_multiplier)
    BUCKET_GAIN_MULTIPLIER = dict(config.bucket_gain_multiplier)


apply_ranking_rules_config(load_ranking_rules_config(default_ranking_rules_file()))


def _build_family_token_alias_index() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for family_name, family_aliases in PATTERN_ALIAS.items():
        canonical = compact_token(family_name)
        if canonical:
            aliases.setdefault(canonical, canonical)
        for raw_alias in family_aliases:
            normalized = compact_token(
                str(raw_alias)
                .replace("Modifier", "")
                .replace("Configuration", "")
                .replace("Controller", "")
            )
            if normalized:
                aliases.setdefault(normalized, canonical)
    return aliases


FAMILY_TOKEN_ALIAS_INDEX = _build_family_token_alias_index()


def coverage_family_key(token: str) -> str:
    normalized = compact_token(token)
    if not normalized or normalized in GENERIC_COVERAGE_TOKENS:
        return ""
    if normalized in FAMILY_TOKEN_ALIAS_INDEX:
        canonical = FAMILY_TOKEN_ALIAS_INDEX[normalized]
    elif normalized in COVERAGE_FAMILY_GROUP_OVERRIDES:
        canonical = normalized
    else:
        # Fallback for unregistered tokens: allow them as family keys only if
        # they look like reasonable component names (not path concatenations).
        _MAX_FAMILY_TOKEN_LEN = 18
        _PATH_NOISE_PREFIXES = ("arkts", "static", "declarative")
        if len(normalized) > _MAX_FAMILY_TOKEN_LEN or any(normalized.startswith(p) for p in _PATH_NOISE_PREFIXES):
            return ""
        canonical = normalized
    grouped = COVERAGE_FAMILY_GROUP_OVERRIDES.get(canonical, canonical)
    if not grouped or grouped in GENERIC_COVERAGE_TOKENS:
        return ""
    return grouped


def is_registered_family_token(token: str) -> bool:
    """Return True if the token is a known, registered family key (not a fallback)."""
    normalized = compact_token(token)
    if not normalized or normalized in GENERIC_COVERAGE_TOKENS:
        return False
    return normalized in FAMILY_TOKEN_ALIAS_INDEX or normalized in COVERAGE_FAMILY_GROUP_OVERRIDES


def capability_family_key(capability: str) -> str:
    normalized = normalize_capability_name(capability)
    if not normalized:
        return ""
    if "." in normalized:
        return normalized.split(".", 1)[0]
    return normalized


def coverage_capability_key(token: str) -> str:
    normalized = compact_token(token)
    if not normalized or normalized in GENERIC_COVERAGE_TOKENS:
        return ""
    grouped = COVERAGE_CAPABILITY_GROUP_OVERRIDES.get(normalized, "")
    if not grouped and normalized in FAMILY_TOKEN_ALIAS_INDEX:
        grouped = COVERAGE_CAPABILITY_GROUP_OVERRIDES.get(FAMILY_TOKEN_ALIAS_INDEX[normalized], "")
    normalized_group = normalize_capability_name(grouped)
    if not normalized_group:
        return ""
    family_key = capability_family_key(normalized_group)
    if not family_key or family_key in GENERIC_COVERAGE_TOKENS:
        return ""
    return normalized_group


def extract_coverage_family_keys(tokens: Iterable[str]) -> set[str]:
    families: set[str] = set()
    for token in tokens:
        family = coverage_family_key(str(token))
        if family:
            families.add(family)
    return families


def extract_coverage_capability_keys(tokens: Iterable[str]) -> set[str]:
    capabilities: set[str] = set()
    for token in tokens:
        capability = coverage_capability_key(str(token))
        if capability:
            capabilities.add(capability)
    return capabilities


def extract_reason_family_tokens(reasons: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for reason in reasons:
        text = str(reason)
        if not text:
            continue
        if text.startswith("path matches "):
            matched = text.removeprefix("path matches ").strip()
            if matched:
                tokens.add(matched)
        for symbol in REASON_SYMBOL_RE.findall(text):
            normalized = symbol.replace("Modifier", "").replace("Configuration", "").replace("Controller", "")
            token = compact_token(normalized)
            if token:
                tokens.add(token)
    return tokens


def extract_focus_tokens(tokens: Iterable[str]) -> set[str]:
    return {
        token
        for token in (compact_token(str(item)) for item in tokens)
        if token and token not in GENERIC_COVERAGE_TOKENS
    }


GENERIC_PUBLIC_METHOD_HINTS = {
    "construct",
    "create",
    "fromptr",
    "getfinalizer",
    "getpeer",
}
GENERIC_TYPED_FIELD_NAMES = {"x", "y", "type"}
STRUCTURAL_TYPED_CALLBACK_TYPES = {
    compact_token("BaseEvent"),
    compact_token("Layoutable"),
    compact_token("Measurable"),
}


def related_signal_base_token(name: str) -> str:
    value = str(name).strip()
    for suffix in ("Modifier", "Configuration", "Controller", "Internal", "Options", "Proxy"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return compact_token(value)


def related_signal_family_token(name: str) -> str:
    base_token = related_signal_base_token(name)
    if not base_token:
        return ""
    canonical = FAMILY_TOKEN_ALIAS_INDEX.get(base_token, base_token)
    mapped_family = coverage_family_key(canonical) or coverage_family_key(base_token)
    return mapped_family or canonical


def ets_source_focus_tokens(source_families: set[str]) -> set[str]:
    roots: set[str] = set()
    for raw in source_families:
        token = compact_token(raw)
        if not token or token in GENERIC_PATH_TOKENS or token.startswith("tmp"):
            continue
        variants = {token}
        if token.endswith("ets") and len(token) > 3:
            variants.add(token[:-3])
        canonical = FAMILY_TOKEN_ALIAS_INDEX.get(token, token)
        variants.add(canonical)
        family = coverage_family_key(canonical) or coverage_family_key(token)
        if family:
            variants.add(compact_token(family))
        capability = coverage_capability_key(canonical) or coverage_capability_key(token)
        if capability:
            variants.update(
                compact_token(part) for part in str(capability).split(".") if compact_token(part)
            )
        for variant in variants:
            normalized = compact_token(variant)
            if (
                normalized
                and normalized not in GENERIC_PATH_TOKENS
                and normalized not in GENERIC_COVERAGE_TOKENS
                and not normalized.startswith("tmp")
            ):
                roots.add(normalized)
    return roots


def ets_name_matches_source_focus(base_token: str, source_focus: set[str]) -> bool:
    if not base_token:
        return False
    return any(
        base_token == token or base_token.startswith(token) or token.startswith(base_token)
        for token in source_focus
    )


def source_token_matches_source_focus(
    token: str,
    source_focus: set[str],
    source_families: set[str],
) -> bool:
    normalized = compact_token(token)
    if (
        not normalized
        or normalized in GENERIC_PATH_TOKENS
        or normalized in GENERIC_COVERAGE_TOKENS
    ):
        return False
    if any(
        normalized == focus_token or normalized.startswith(focus_token)
        for focus_token in source_focus
    ):
        return True
    if normalized in source_families:
        return True
    family_key = coverage_family_key(normalized)
    if family_key and family_key in source_families:
        return True
    capability_key = coverage_capability_key(normalized)
    capability_family = capability_family_key(capability_key) if capability_key else ""
    return bool(capability_family and capability_family in source_families)


def imported_ets_symbol_matches_source_focus(
    name: str,
    source_focus: set[str],
    source_families: set[str],
) -> bool:
    base_token = related_signal_base_token(name)
    if source_token_matches_source_focus(base_token, source_focus, source_families):
        return True
    family_token = related_signal_family_token(name)
    return source_token_matches_source_focus(family_token, source_focus, source_families)


def strip_ets_import_statements(text: str) -> str:
    stripped = IMPORT_BINDING_RE.sub(" ", text)
    stripped = DEFAULT_IMPORT_RE.sub(" ", stripped)
    return stripped


def imported_ets_symbol_used_in_body(
    name: str,
    body_identifier_calls: set[str],
    body_type_member_owners: set[str],
    body_words: set[str],
) -> bool:
    if name in body_identifier_calls or name in body_type_member_owners:
        return True
    normalized = compact_token(name)
    base_token = related_signal_base_token(name)
    return bool(
        (normalized and normalized in body_words)
        or (base_token and base_token in body_words)
    )


def ohos_module_signal_tokens(module_name: str) -> set[str]:
    tail = compact_token(module_name.rsplit(".", 1)[-1])
    tokens = {tail} if tail else set()
    return {
        token
        for token in tokens
        if token
        and len(token) >= 4
        and token != "ohos"
        and token not in GENERIC_PATH_TOKENS
        and token not in GENERIC_SCOPE_TOKENS
        and token not in LOW_SIGNAL_SPECIFICITY_TOKENS
        and token not in GENERIC_COVERAGE_TOKENS
    }


def classify_ohos_module_signal_strength(
    module_name: str,
    source_focus: set[str],
    source_families: set[str],
) -> str:
    tokens = ohos_module_signal_tokens(module_name)
    if not tokens:
        return ""
    if any(source_token_matches_source_focus(token, source_focus, source_families) for token in tokens):
        return "strong"
    return "weak"


def should_keep_ets_signal_name(
    name: str,
    source_families: set[str],
    allow_source_family_fallback: bool,
) -> bool:
    base_token = related_signal_base_token(name)
    family_token = related_signal_family_token(name)
    if not family_token:
        return False
    if family_token in source_families or is_registered_family_token(family_token):
        return True
    if coverage_capability_key(family_token) or coverage_capability_key(base_token):
        return True
    source_focus = ets_source_focus_tokens(source_families)
    if allow_source_family_fallback and ets_name_matches_source_focus(base_token, source_focus):
        return True
    return allow_source_family_fallback and len(source_focus) == 1


def build_source_profile(
    source_type: str,
    source_value: str,
    signals: dict[str, set[str]],
    raw_path: Path | None = None,
) -> dict[str, object]:
    raw_tokens = set(signals.get("family_tokens", set()))
    raw_tokens.update(signals.get("project_hints", set()))
    raw_tokens.update(specificity_target_tokens(signals))
    raw_tokens.update(
        compact_token(
            str(symbol)
            .replace("Modifier", "")
            .replace("Configuration", "")
            .replace("Controller", "")
        )
        for symbol in signals.get("symbols", set())
        if compact_token(
            str(symbol)
            .replace("Modifier", "")
            .replace("Configuration", "")
            .replace("Controller", "")
        )
    )
    if raw_path is not None:
        repo_path = repo_rel(raw_path)
        path_for_tokens = repo_path.lower()
        if os.path.isabs(path_for_tokens):
            path_for_tokens = raw_path.name.lower()
        raw_tokens.add(compact_token(raw_path.stem))
        raw_tokens.update(path_component_tokens(path_for_tokens))
    family_keys = sorted(extract_coverage_family_keys(raw_tokens))
    capability_keys = sorted(extract_coverage_capability_keys(raw_tokens))
    type_hint_keys = sorted(extract_type_hint_keys(signals.get("type_hints", set())))
    member_hint_keys = sorted(extract_member_hint_keys(signals.get("member_hints", set())))
    if capability_keys and not family_keys:
        family_keys = sorted({capability_family_key(item) for item in capability_keys if capability_family_key(item)})
    focus_tokens = sorted(
        extract_focus_tokens(
            raw_tokens
            | set(type_hint_keys)
            | {item.partition(".")[0] for item in member_hint_keys}
            | {item.partition(".")[2] for item in member_hint_keys if "." in item}
        )
    )
    return {
        "key": f"{source_type}:{source_value}",
        "type": source_type,
        "value": source_value,
        "family_keys": family_keys,
        "capability_keys": capability_keys,
        "type_hint_keys": type_hint_keys,
        "member_hint_keys": member_hint_keys,
        "focus_tokens": focus_tokens,
        "fallback_only": not bool(family_keys or capability_keys),
    }


def infer_project_family_profile(
    project: TestProjectIndex,
    project_reasons: list[str],
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
) -> dict[str, object]:
    project_path = f"{project.relative_root}/{Path(project.test_json).name}".lower()
    project_tokens = path_signal_tokens(project_path)
    project_focus_tokens = extract_focus_tokens(project_tokens)
    related_tokens = set(project_tokens)
    direct_tokens = set(extract_reason_family_tokens(project_reasons))
    generic_markers = {
        token
        for token in project_tokens
        if token in GENERIC_COVERAGE_TOKENS
    }
    family_quality: dict[str, float] = {}
    capability_quality: dict[str, float] = {}
    family_project_hits: dict[str, int] = {}
    family_path_hits: dict[str, int] = {}
    family_reason_hits: dict[str, int] = {}
    family_direct_file_hits: dict[str, int] = {}
    capability_project_hits: dict[str, int] = {}
    capability_path_hits: dict[str, int] = {}
    capability_reason_hits: dict[str, int] = {}
    capability_direct_file_hits: dict[str, int] = {}
    focus_token_counts: dict[str, int] = {}

    def _bump_quality(
        tokens: Iterable[str],
        amount: float,
        quality_map: dict[str, float],
        extractor: Callable[[Iterable[str]], set[str]],
    ) -> None:
        for key in extractor(tokens):
            quality_map[key] = quality_map.get(key, 1.0) + amount

    def _bump_family_quality(tokens: Iterable[str], amount: float) -> None:
        _bump_quality(tokens, amount, family_quality, extract_coverage_family_keys)

    def _bump_capability_quality(tokens: Iterable[str], amount: float) -> None:
        _bump_quality(tokens, amount, capability_quality, extract_coverage_capability_keys)

    def _bump_counter(
        tokens: Iterable[str],
        counter: dict[str, int],
        extractor: Callable[[Iterable[str]], set[str]],
        amount: int = 1,
    ) -> set[str]:
        keys = extractor(tokens)
        for key in keys:
            counter[key] = counter.get(key, 0) + amount
        return keys

    def _bump_family_counter(tokens: Iterable[str], counter: dict[str, int], amount: int = 1) -> set[str]:
        return _bump_counter(tokens, counter, extract_coverage_family_keys, amount)

    def _bump_capability_counter(tokens: Iterable[str], counter: dict[str, int], amount: int = 1) -> set[str]:
        return _bump_counter(tokens, counter, extract_coverage_capability_keys, amount)

    def _bump_direct_hits(keys: Iterable[str], counter: dict[str, int]) -> None:
        for key in keys:
            counter[key] = counter.get(key, 0) + 1

    def _bump_focus_token_counts(tokens: Iterable[str], amount: int = 1) -> None:
        for token in extract_focus_tokens(tokens):
            focus_token_counts[token] = focus_token_counts.get(token, 0) + amount

    def _finalize_quality_scores(
        keys: list[str],
        direct_keys: list[str],
        quality_map: dict[str, float],
        project_hits: dict[str, int],
        path_hits: dict[str, int],
        reason_hits: dict[str, int],
        direct_file_hits: dict[str, int],
        umbrella_penalty: float,
    ) -> tuple[dict[str, float], dict[str, float]]:
        normalized_quality: dict[str, float] = {}
        representative_quality: dict[str, float] = {}
        direct_key_set = set(direct_keys)
        purity_penalty = min(
            ACTIVE_RANKING_RULES.representative_extra_family_penalty_cap,
            ACTIVE_RANKING_RULES.representative_extra_family_penalty * max(0, len(keys) - 1),
        )
        for key in keys:
            quality = quality_map.get(key, 1.0)
            if key in direct_key_set and len(direct_key_set) == 1:
                quality += ACTIVE_RANKING_RULES.family_quality_direct_single_family_bonus
            if key in direct_key_set and len(keys) <= 2:
                quality += ACTIVE_RANKING_RULES.family_quality_direct_small_family_bonus
            normalized_quality[key] = round(min(ACTIVE_RANKING_RULES.family_quality_maximum, quality), 3)
            representative = quality
            representative += project_hits.get(key, 0) * ACTIVE_RANKING_RULES.representative_project_family_hit
            representative += path_hits.get(key, 0) * ACTIVE_RANKING_RULES.representative_file_family_hit
            representative += reason_hits.get(key, 0) * ACTIVE_RANKING_RULES.representative_reason_family_hit
            representative += direct_file_hits.get(key, 0) * ACTIVE_RANKING_RULES.representative_direct_file_hit
            if key in direct_key_set:
                representative += ACTIVE_RANKING_RULES.representative_direct_family_bonus
            if len(keys) == 1:
                representative += ACTIVE_RANKING_RULES.representative_single_family_bonus
            elif len(keys) <= 2 and key in direct_key_set:
                representative += ACTIVE_RANKING_RULES.representative_small_family_bonus
            representative -= purity_penalty
            representative -= umbrella_penalty * ACTIVE_RANKING_RULES.representative_umbrella_penalty_weight
            representative_quality[key] = round(
                max(
                    ACTIVE_RANKING_RULES.representative_minimum_quality,
                    min(ACTIVE_RANKING_RULES.representative_maximum_quality, representative),
                ),
                3,
            )
        return normalized_quality, representative_quality

    _bump_focus_token_counts(project_focus_tokens)
    _bump_family_counter(project_tokens, family_project_hits)
    _bump_capability_counter(project_tokens, capability_project_hits)

    for _file_score, test_file, reasons in file_hits[:5]:
        path_tokens = path_signal_tokens(test_file.relative_path.lower())
        reason_tokens = extract_reason_family_tokens(reasons)
        path_focus_tokens = extract_focus_tokens(path_tokens)
        reason_focus_tokens = extract_focus_tokens(reason_tokens)
        related_tokens.update(path_tokens)
        related_tokens.update(reason_tokens)
        _bump_focus_token_counts(path_focus_tokens)
        _bump_focus_token_counts(reason_focus_tokens)
        path_families = _bump_family_counter(path_tokens, family_path_hits)
        reason_families = _bump_family_counter(reason_tokens, family_reason_hits)
        path_capabilities = _bump_capability_counter(path_tokens, capability_path_hits)
        reason_capabilities = _bump_capability_counter(reason_tokens, capability_reason_hits)
        _bump_family_quality(path_tokens, ACTIVE_RANKING_RULES.family_quality_related_file_path)
        _bump_capability_quality(path_tokens, ACTIVE_RANKING_RULES.family_quality_related_file_path)
        if any(_is_direct_evidence_reason(reason) for reason in reasons):
            direct_tokens.update(path_tokens)
            direct_tokens.update(reason_tokens)
            _bump_family_quality(path_tokens, ACTIVE_RANKING_RULES.family_quality_direct_file_path)
            _bump_family_quality(reason_tokens, ACTIVE_RANKING_RULES.family_quality_direct_reason_tokens)
            _bump_capability_quality(path_tokens, ACTIVE_RANKING_RULES.family_quality_direct_file_path)
            _bump_capability_quality(reason_tokens, ACTIVE_RANKING_RULES.family_quality_direct_reason_tokens)
            _bump_direct_hits(path_families | reason_families, family_direct_file_hits)
            _bump_direct_hits(path_capabilities | reason_capabilities, capability_direct_file_hits)

    _bump_family_quality(project_tokens, ACTIVE_RANKING_RULES.family_quality_project_tokens)
    _bump_capability_quality(project_tokens, ACTIVE_RANKING_RULES.family_quality_project_tokens)

    family_keys = sorted(extract_coverage_family_keys(related_tokens))
    direct_family_keys = sorted(extract_coverage_family_keys(direct_tokens))
    capability_keys = sorted(extract_coverage_capability_keys(related_tokens))
    direct_capability_keys = sorted(extract_coverage_capability_keys(direct_tokens))
    if capability_keys:
        family_keys = sorted(set(family_keys) | {capability_family_key(item) for item in capability_keys if capability_family_key(item)})
    if direct_capability_keys:
        direct_family_keys = sorted(set(direct_family_keys) | {capability_family_key(item) for item in direct_capability_keys if capability_family_key(item)})
    umbrella_penalty = 0.0
    for marker, penalty in ACTIVE_RANKING_RULES.umbrella_marker_penalties.items():
        if marker in generic_markers:
            umbrella_penalty += penalty
    threshold = ACTIVE_RANKING_RULES.umbrella_family_count_threshold
    if threshold and len(family_keys) >= threshold:
        umbrella_penalty += min(
            ACTIVE_RANKING_RULES.umbrella_family_count_penalty_cap,
            ACTIVE_RANKING_RULES.umbrella_family_count_penalty * (len(family_keys) - (threshold - 1)),
        )
    normalized_family_quality, family_representative_quality = _finalize_quality_scores(
        family_keys,
        direct_family_keys,
        family_quality,
        family_project_hits,
        family_path_hits,
        family_reason_hits,
        family_direct_file_hits,
        umbrella_penalty,
    )
    normalized_capability_quality, capability_representative_quality = _finalize_quality_scores(
        capability_keys,
        direct_capability_keys,
        capability_quality,
        capability_project_hits,
        capability_path_hits,
        capability_reason_hits,
        capability_direct_file_hits,
        umbrella_penalty,
    )
    return {
        "family_keys": family_keys,
        "direct_family_keys": direct_family_keys,
        "family_quality": normalized_family_quality,
        "family_representative_quality": family_representative_quality,
        "capability_keys": capability_keys,
        "direct_capability_keys": direct_capability_keys,
        "capability_quality": normalized_capability_quality,
        "capability_representative_quality": capability_representative_quality,
        "focus_token_counts": focus_token_counts,
        "generic_markers": sorted(generic_markers),
        "umbrella_penalty": round(min(ACTIVE_RANKING_RULES.umbrella_penalty_cap, umbrella_penalty), 3),
    }


def suite_source_family_gains(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_families = set(source_profile.get("family_keys", []))
    suite_families = set(project_entry.get("family_keys", []))
    direct_suite_families = set(project_entry.get("direct_family_keys", []))
    if not source_families:
        return {}

    scope_multiplier = SCOPE_GAIN_MULTIPLIER.get(str(project_entry.get("scope_tier", "focused")), 1.0)
    bucket_multiplier = BUCKET_GAIN_MULTIPLIER.get(str(project_entry.get("bucket", "possible related")), 0.65)
    umbrella_penalty = float(project_entry.get("umbrella_penalty", 0.0) or 0.0)
    umbrella_factor = max(ACTIVE_RANKING_RULES.umbrella_min_factor, 1.0 - umbrella_penalty)
    family_quality = {
        str(key): float(value)
        for key, value in dict(project_entry.get("family_quality") or {}).items()
    }

    gains: dict[str, float] = {}
    direct_overlap = source_families & direct_suite_families
    related_overlap = (source_families & suite_families) - direct_overlap
    for family in direct_overlap:
        quality_factor = max(ACTIVE_RANKING_RULES.family_gain_min_direct_quality, family_quality.get(family, 1.0))
        gains[family] = round(
            ACTIVE_RANKING_RULES.family_gain_direct_base
            * scope_multiplier
            * bucket_multiplier
            * umbrella_factor
            * quality_factor,
            6,
        )
    for family in related_overlap:
        quality_factor = max(ACTIVE_RANKING_RULES.family_gain_min_related_quality, family_quality.get(family, 1.0))
        gains[family] = round(
            ACTIVE_RANKING_RULES.family_gain_related_base
            * scope_multiplier
            * bucket_multiplier
            * umbrella_factor
            * quality_factor,
            6,
        )
    return gains


def suite_source_family_representative_scores(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_families = set(source_profile.get("family_keys", []))
    source_focus_tokens = set(source_profile.get("focus_tokens", []))
    suite_families = set(project_entry.get("family_keys", []))
    direct_suite_families = set(project_entry.get("direct_family_keys", []))
    representative_quality = {
        str(key): float(value)
        for key, value in dict(project_entry.get("family_representative_quality") or {}).items()
    }
    focus_token_counts = {
        str(key): int(value)
        for key, value in dict(project_entry.get("focus_token_counts") or {}).items()
    }
    if not source_families:
        return {}

    scores: dict[str, float] = {}
    direct_overlap = source_families & direct_suite_families
    related_overlap = (source_families & suite_families) - direct_overlap
    token_overlap = sum(focus_token_counts.get(token, 0) for token in source_focus_tokens)
    overlap_bonus = min(
        ACTIVE_RANKING_RULES.representative_source_token_overlap_cap,
        token_overlap * ACTIVE_RANKING_RULES.representative_source_token_overlap_weight,
    )
    for family in direct_overlap:
        base = representative_quality.get(family, 1.0) + overlap_bonus
        scores[family] = round(base * ACTIVE_RANKING_RULES.representative_direct_overlap_multiplier, 6)
    for family in related_overlap:
        base = representative_quality.get(family, 1.0) + overlap_bonus
        scores[family] = round(base * ACTIVE_RANKING_RULES.representative_related_overlap_multiplier, 6)
    return scores


def suite_source_capability_gains(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_capabilities = set(source_profile.get("capability_keys", []))
    suite_capabilities = set(project_entry.get("capability_keys", []))
    direct_suite_capabilities = set(project_entry.get("direct_capability_keys", []))
    if not source_capabilities:
        return {}

    scope_multiplier = SCOPE_GAIN_MULTIPLIER.get(str(project_entry.get("scope_tier", "focused")), 1.0)
    bucket_multiplier = BUCKET_GAIN_MULTIPLIER.get(str(project_entry.get("bucket", "possible related")), 0.65)
    umbrella_penalty = float(project_entry.get("umbrella_penalty", 0.0) or 0.0)
    umbrella_factor = max(ACTIVE_RANKING_RULES.umbrella_min_factor, 1.0 - umbrella_penalty)
    capability_quality = {
        str(key): float(value)
        for key, value in dict(project_entry.get("capability_quality") or {}).items()
    }

    gains: dict[str, float] = {}
    direct_overlap = source_capabilities & direct_suite_capabilities
    related_overlap = (source_capabilities & suite_capabilities) - direct_overlap
    for capability in direct_overlap:
        quality_factor = max(ACTIVE_RANKING_RULES.family_gain_min_direct_quality, capability_quality.get(capability, 1.0))
        gains[capability] = round(
            ACTIVE_RANKING_RULES.family_gain_direct_base
            * scope_multiplier
            * bucket_multiplier
            * umbrella_factor
            * quality_factor,
            6,
        )
    for capability in related_overlap:
        quality_factor = max(ACTIVE_RANKING_RULES.family_gain_min_related_quality, capability_quality.get(capability, 1.0))
        gains[capability] = round(
            ACTIVE_RANKING_RULES.family_gain_related_base
            * scope_multiplier
            * bucket_multiplier
            * umbrella_factor
            * quality_factor,
            6,
        )
    return gains


def suite_source_capability_representative_scores(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_capabilities = set(source_profile.get("capability_keys", []))
    source_focus_tokens = set(source_profile.get("focus_tokens", []))
    suite_capabilities = set(project_entry.get("capability_keys", []))
    direct_suite_capabilities = set(project_entry.get("direct_capability_keys", []))
    representative_quality = {
        str(key): float(value)
        for key, value in dict(project_entry.get("capability_representative_quality") or {}).items()
    }
    focus_token_counts = {
        str(key): int(value)
        for key, value in dict(project_entry.get("focus_token_counts") or {}).items()
    }
    if not source_capabilities:
        return {}

    scores: dict[str, float] = {}
    direct_overlap = source_capabilities & direct_suite_capabilities
    related_overlap = (source_capabilities & suite_capabilities) - direct_overlap
    token_overlap = sum(focus_token_counts.get(token, 0) for token in source_focus_tokens)
    overlap_bonus = min(
        ACTIVE_RANKING_RULES.representative_source_token_overlap_cap,
        token_overlap * ACTIVE_RANKING_RULES.representative_source_token_overlap_weight,
    )
    for capability in direct_overlap:
        base = representative_quality.get(capability, 1.0) + overlap_bonus
        scores[capability] = round(base * ACTIVE_RANKING_RULES.representative_direct_overlap_multiplier, 6)
    for capability in related_overlap:
        base = representative_quality.get(capability, 1.0) + overlap_bonus
        scores[capability] = round(base * ACTIVE_RANKING_RULES.representative_related_overlap_multiplier, 6)
    return scores


def extract_type_hint_keys(values: Iterable[str]) -> set[str]:
    keys: set[str] = set()
    for value in values:
        key = compact_token(value)
        if (
            key
            and key not in GENERIC_COVERAGE_TOKENS
            and key not in STRUCTURAL_TYPED_CALLBACK_TYPES
        ):
            keys.add(key)
    return keys


def normalize_member_hint(value: str) -> str:
    owner, separator, member = str(value or "").partition(".")
    owner_token = compact_token(owner)
    member_token = compact_token(member)
    if not separator or not owner_token or not member_token:
        return ""
    if owner_token in STRUCTURAL_TYPED_CALLBACK_TYPES or member_token in GENERIC_TYPED_FIELD_NAMES:
        return ""
    return f"{owner_token}.{member_token}"


def extract_member_hint_keys(values: Iterable[str]) -> set[str]:
    keys: set[str] = set()
    for value in values:
        normalized = normalize_member_hint(str(value))
        if normalized:
            keys.add(normalized)
    return keys


def _typed_owner_tokens(values: Iterable[str]) -> set[str]:
    owners: set[str] = set()
    for value in values:
        owner, _separator, _member = str(value or "").partition(".")
        owner_token = compact_token(owner)
        if owner_token:
            owners.add(owner_token)
    return owners


def _typed_member_tokens(values: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = normalize_member_hint(str(value))
        if normalized:
            tokens.add(normalized)
    return tokens


def extract_exported_type_names(
    text: str,
    *,
    changed_ranges: Iterable[tuple[int, int]] | None = None,
) -> set[str]:
    exported: set[str] = set()
    normalized_ranges = merge_changed_ranges(changed_ranges)
    line_offsets = build_line_start_offsets(text) if normalized_ranges else []
    for pattern in (EXPORT_CLASS_RE, EXPORT_INTERFACE_RE):
        for match in pattern.finditer(text):
            if normalized_ranges and not span_overlaps_changed_ranges(
                match.start(),
                match.end(),
                line_offsets=line_offsets,
                changed_ranges=normalized_ranges,
            ):
                continue
            exported.add(match.group(1))
    return exported


def extract_exported_interface_member_hints(
    text: str,
    source_families: set[str],
    *,
    changed_ranges: Iterable[tuple[int, int]] | None = None,
) -> set[str]:
    hints: set[str] = set()
    normalized_ranges = merge_changed_ranges(changed_ranges)
    line_offsets = build_line_start_offsets(text) if normalized_ranges else []
    for interface_match in EXPORT_INTERFACE_BLOCK_RE.finditer(text):
        owner = interface_match.group(1)
        body = interface_match.group("body")
        body_offset = interface_match.start("body")
        for property_match in INTERFACE_PROPERTY_RE.finditer(body):
            if normalized_ranges and not span_overlaps_changed_ranges(
                body_offset + property_match.start(),
                body_offset + property_match.end(),
                line_offsets=line_offsets,
                changed_ranges=normalized_ranges,
            ):
                continue
            member_name = property_match.group(1)
            normalized = normalize_member_hint(f"{owner}.{member_name}")
            if normalized:
                hints.add(f"{owner}.{member_name}")
        for method_match in INTERFACE_METHOD_RE.finditer(body):
            method_name = method_match.group(1)
            if compact_token(method_name) in GENERIC_PUBLIC_METHOD_HINTS:
                continue
            if normalized_ranges and not span_overlaps_changed_ranges(
                body_offset + method_match.start(),
                body_offset + method_match.end(),
                line_offsets=line_offsets,
                changed_ranges=normalized_ranges,
            ):
                continue
            normalized = normalize_member_hint(f"{owner}.{method_name}")
            if normalized:
                hints.add(f"{owner}.{method_name}")
    return hints


def infer_project_type_hint_profile(
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
    signals: dict[str, set[str]],
) -> dict[str, object]:
    source_type_hint_keys = extract_type_hint_keys(signals.get("type_hints", set()))
    if not source_type_hint_keys:
        return {
            "type_hint_keys": [],
            "direct_type_hint_keys": [],
            "focus_token_counts": {},
        }

    matched_type_hints: set[str] = set()
    direct_type_hints: set[str] = set()
    focus_token_counts: dict[str, int] = {}
    for _file_score, test_file, _reasons in file_hits:
        related_tokens = {
            compact_token(item)
            for item in (
                set(test_file.imported_symbols)
                | set(test_file.identifier_calls)
                | set(test_file.words)
            )
            if compact_token(item)
        }
        related_tokens.update(_typed_owner_tokens(test_file.type_member_calls))
        direct_tokens = _typed_owner_tokens(test_file.typed_field_accesses)
        related_tokens.update(direct_tokens)
        for type_hint_key in source_type_hint_keys:
            if type_hint_key in related_tokens:
                matched_type_hints.add(type_hint_key)
                focus_token_counts[type_hint_key] = focus_token_counts.get(type_hint_key, 0) + 1
            if type_hint_key in direct_tokens:
                direct_type_hints.add(type_hint_key)
                focus_token_counts[type_hint_key] = focus_token_counts.get(type_hint_key, 0) + 2
    return {
        "type_hint_keys": sorted(matched_type_hints),
        "direct_type_hint_keys": sorted(direct_type_hints),
        "focus_token_counts": focus_token_counts,
    }


def infer_project_member_hint_profile(
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
    signals: dict[str, set[str]],
) -> dict[str, object]:
    source_member_hint_keys = extract_member_hint_keys(signals.get("member_hints", set()))
    if not source_member_hint_keys:
        return {
            "member_hint_keys": [],
            "direct_member_hint_keys": [],
            "focus_token_counts": {},
        }

    matched_member_hints: set[str] = set()
    direct_member_hints: set[str] = set()
    focus_token_counts: dict[str, int] = {}
    for _file_score, test_file, _reasons in file_hits:
        direct_members = _typed_member_tokens(test_file.typed_field_accesses)
        related_members = direct_members | _typed_member_tokens(test_file.type_member_calls)
        for member_hint_key in source_member_hint_keys:
            if member_hint_key in related_members:
                matched_member_hints.add(member_hint_key)
                focus_token_counts[member_hint_key] = focus_token_counts.get(member_hint_key, 0) + 1
            if member_hint_key in direct_members:
                direct_member_hints.add(member_hint_key)
                focus_token_counts[member_hint_key] = focus_token_counts.get(member_hint_key, 0) + 2
    return {
        "member_hint_keys": sorted(matched_member_hints),
        "direct_member_hint_keys": sorted(direct_member_hints),
        "focus_token_counts": focus_token_counts,
    }


def suite_source_type_hint_gains(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_type_hints = set(source_profile.get("type_hint_keys", []))
    suite_type_hints = set(project_entry.get("type_hint_keys", []))
    direct_suite_type_hints = set(project_entry.get("direct_type_hint_keys", []))
    if not source_type_hints:
        return {}

    scope_multiplier = SCOPE_GAIN_MULTIPLIER.get(str(project_entry.get("scope_tier", "focused")), 1.0)
    bucket_multiplier = BUCKET_GAIN_MULTIPLIER.get(str(project_entry.get("bucket", "possible related")), 0.65)
    direct_overlap = source_type_hints & direct_suite_type_hints
    related_overlap = (source_type_hints & suite_type_hints) - direct_overlap

    gains: dict[str, float] = {}
    for type_hint_key in direct_overlap:
        gains[type_hint_key] = round(
            ACTIVE_RANKING_RULES.family_gain_direct_base * 1.15 * scope_multiplier * bucket_multiplier,
            6,
        )
    for type_hint_key in related_overlap:
        gains[type_hint_key] = round(
            ACTIVE_RANKING_RULES.family_gain_related_base * 0.95 * scope_multiplier * bucket_multiplier,
            6,
        )
    return gains


def suite_source_member_hint_gains(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_member_hints = set(source_profile.get("member_hint_keys", []))
    suite_member_hints = set(project_entry.get("member_hint_keys", []))
    direct_suite_member_hints = set(project_entry.get("direct_member_hint_keys", []))
    if not source_member_hints:
        return {}

    scope_multiplier = SCOPE_GAIN_MULTIPLIER.get(str(project_entry.get("scope_tier", "focused")), 1.0)
    bucket_multiplier = BUCKET_GAIN_MULTIPLIER.get(str(project_entry.get("bucket", "possible related")), 0.65)
    direct_overlap = source_member_hints & direct_suite_member_hints
    related_overlap = (source_member_hints & suite_member_hints) - direct_overlap

    gains: dict[str, float] = {}
    for member_hint_key in direct_overlap:
        gains[member_hint_key] = round(
            ACTIVE_RANKING_RULES.family_gain_direct_base * 1.35 * scope_multiplier * bucket_multiplier,
            6,
        )
    for member_hint_key in related_overlap:
        gains[member_hint_key] = round(
            ACTIVE_RANKING_RULES.family_gain_related_base * 1.15 * scope_multiplier * bucket_multiplier,
            6,
        )
    return gains


def suite_source_member_hint_representative_scores(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_member_hints = set(source_profile.get("member_hint_keys", []))
    suite_member_hints = set(project_entry.get("member_hint_keys", []))
    direct_suite_member_hints = set(project_entry.get("direct_member_hint_keys", []))
    focus_token_counts = {
        str(key): int(value)
        for key, value in dict(project_entry.get("member_hint_focus_counts") or {}).items()
    }
    if not source_member_hints:
        return {}

    scores: dict[str, float] = {}
    direct_overlap = source_member_hints & direct_suite_member_hints
    related_overlap = (source_member_hints & suite_member_hints) - direct_overlap
    for member_hint_key in direct_overlap:
        scores[member_hint_key] = round(
            2.5 + min(1.5, focus_token_counts.get(member_hint_key, 0) * 0.15),
            6,
        )
    for member_hint_key in related_overlap:
        scores[member_hint_key] = round(
            1.5 + min(1.0, focus_token_counts.get(member_hint_key, 0) * 0.1),
            6,
        )
    return scores


def suite_source_type_hint_representative_scores(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> dict[str, float]:
    source_type_hints = set(source_profile.get("type_hint_keys", []))
    suite_type_hints = set(project_entry.get("type_hint_keys", []))
    direct_suite_type_hints = set(project_entry.get("direct_type_hint_keys", []))
    focus_token_counts = {
        str(key): int(value)
        for key, value in dict(project_entry.get("type_hint_focus_counts") or {}).items()
    }
    if not source_type_hints:
        return {}

    scores: dict[str, float] = {}
    direct_overlap = source_type_hints & direct_suite_type_hints
    related_overlap = (source_type_hints & suite_type_hints) - direct_overlap
    for type_hint_key in direct_overlap:
        scores[type_hint_key] = round(
            2.0 + min(1.0, focus_token_counts.get(type_hint_key, 0) * 0.15),
            6,
        )
    for type_hint_key in related_overlap:
        scores[type_hint_key] = round(
            1.0 + min(0.6, focus_token_counts.get(type_hint_key, 0) * 0.1),
            6,
        )
    return scores


def suite_source_focus_token_overlap(
    project_entry: dict[str, object],
    source_profile: dict[str, object],
) -> int:
    source_focus_tokens = set(source_profile.get("focus_tokens", []))
    focus_token_counts = {
        str(key): int(value)
        for key, value in dict(project_entry.get("focus_token_counts") or {}).items()
    }
    return sum(focus_token_counts.get(token, 0) for token in source_focus_tokens)


def normalize_type_hint(name: str) -> str:
    value = re.sub(r"(?:Accessor|Peer)$", "", name.strip())
    if not value:
        return ""
    if "_" in value or "-" in value:
        return snake_to_pascal(value)
    return value


def extract_native_accessor_type_hints(text: str) -> set[str]:
    hints: set[str] = set()
    for raw in GENERATED_ACCESSOR_NAMESPACE_RE.findall(text):
        hint = normalize_type_hint(raw)
        if hint:
            hints.add(hint)
    for raw in GET_ACCESSOR_RE.findall(text):
        hint = normalize_type_hint(raw)
        if hint:
            hints.add(hint)
    for raw in PEER_INCLUDE_RE.findall(text):
        hint = normalize_type_hint(raw)
        if hint:
            hints.add(hint)
    return hints


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def load_json_file(path: Path) -> dict:
    text = read_text(path)
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid json in {path}: {exc}") from exc


def resolve_path(value: str | None, default: Path, repo_root: Path) -> Path:
    return resolve_workspace_path(value=value, default=default, repo_root=repo_root)


def normalize_git_host_kind(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "auto"}:
        return "auto"
    if normalized in {"gitcode"}:
        return "gitcode"
    if normalized in {"codehub", "codehub-y", "cr-y.codehub", "opencodehub"}:
        return "codehub"
    return normalized


def _load_ini_git_host_section(parser: ConfigParser, section: str) -> tuple[str | None, str | None]:
    if not parser.has_section(section):
        return None, None
    normalized_kind = normalize_git_host_kind(section)
    option_names: list[str]
    if normalized_kind == "gitcode":
        option_names = ["gitcode-url", "url"]
    elif normalized_kind == "codehub":
        option_names = [f"{section}-url", "codehub-url", "url"]
    else:
        option_names = ["url"]
    url = next((parser.get(section, option, fallback=None) for option in option_names if parser.has_option(section, option)), None)
    token = parser.get(section, "token", fallback=None)
    return url, token


def load_ini_git_host_config(path_value: str | None, repo_root: Path, host_kind: str) -> tuple[str | None, str | None]:
    if not path_value:
        return None, None
    path = resolve_path(path_value, repo_root, repo_root)
    if not path.exists():
        return None, None
    parser = ConfigParser()
    parser.read(path, encoding="utf-8-sig")
    normalized_kind = normalize_git_host_kind(host_kind)
    if normalized_kind == "gitcode":
        sections_to_try = ("gitcode",)
    elif normalized_kind == "codehub":
        sections_to_try = CODEHUB_SECTION_NAMES
    else:
        sections_to_try = ("gitcode", *CODEHUB_SECTION_NAMES)
    for section in sections_to_try:
        url, token = _load_ini_git_host_section(parser, section)
        if url or token:
            return url, token
    return None, None


def load_ini_gitcode_config(path_value: str | None, repo_root: Path) -> tuple[str | None, str | None]:
    return load_ini_git_host_config(path_value, repo_root, "gitcode")


def add_family_symbol(mapping: dict[str, set[str]], family: str, symbol: str) -> None:
    family_key = compact_token(family)
    if not family_key or not symbol:
        return
    mapping.setdefault(family_key, set()).add(symbol)


def build_content_modifier_index() -> ContentModifierIndex:
    index = ContentModifierIndex()
    candidate_files: list[Path] = []
    search_roots = [
        REPO_ROOT / "foundation/arkui/ace_engine",
        REPO_ROOT / "interface",
        REPO_ROOT / "arkcompiler",
    ]
    patterns = {
        "arkui-contentmodifier.idl",
        "arkgen-config.json",
        "config-arkui.json",
        "subset-arkts-config.json",
        "ContentModifierHooks.ets",
    }
    skip_dirs = {".git", ".repo", "node_modules", ".staging", "out"}
    seen_paths: set[Path] = set()
    for root in search_roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _exc: None):
            dirnames[:] = [name for name in dirnames if name not in skip_dirs]
            for filename in filenames:
                if filename not in patterns:
                    continue
                resolved = (Path(dirpath) / filename).resolve()
                if resolved not in seen_paths:
                    candidate_files.append(resolved)
                    seen_paths.add(resolved)
    for path in candidate_files:
        text = read_text(path)
        if not text:
            continue
        for raw in IDL_CONTENT_MODIFIER_RE.findall(text):
            family = compact_token(raw)
            if not family:
                continue
            index.families.add(family)
            add_family_symbol(index.family_to_symbols, family, raw)
            add_family_symbol(index.family_to_symbols, family, f"{raw}Modifier")
            add_family_symbol(index.family_to_symbols, family, f"{raw}Configuration")
        for raw in HOOK_CONTENT_MODIFIER_RE.findall(text):
            family = compact_token(raw)
            if not family:
                continue
            index.families.add(family)
            add_family_symbol(index.family_to_symbols, family, raw)
            add_family_symbol(index.family_to_symbols, family, f"{raw}Modifier")
            add_family_symbol(index.family_to_symbols, family, f"hook{raw}ContentModifier")
    return index


def load_json_if_exists(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    return load_json_file(path)


def merge_mapping_dict(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def default_path_rules_file() -> Path | None:
    candidate = DEFAULT_CONFIG_DIR / "path_rules.json"
    return candidate if candidate.exists() else None


def default_composite_mappings_file() -> Path | None:
    candidate = DEFAULT_CONFIG_DIR / "composite_mappings.json"
    return candidate if candidate.exists() else None


def default_changed_file_exclusions_file() -> Path | None:
    candidate = DEFAULT_CONFIG_DIR / "changed_file_exclusions.json"
    return candidate if candidate.exists() else None


def load_mapping_config(
    path_rules_file: Path | None,
    composite_mappings_file: Path | None,
    *,
    lineage_auto_alias: dict[str, list[str]] | None = None,
) -> MappingConfig:
    path_rules_data = load_json_if_exists(path_rules_file)
    composite_data = load_json_if_exists(composite_mappings_file)
    special_path_rules = merge_mapping_dict(SPECIAL_PATH_RULES, path_rules_data.get("special_path_rules", {}))
    # When config provides a full pattern_alias, replace rather than merge
    # to avoid conflicts. Fallback to hardcoded PATTERN_ALIAS when absent.
    config_pattern_alias = path_rules_data.get("pattern_alias", {})
    if config_pattern_alias:
        pattern_alias = merge_mapping_dict(PATTERN_ALIAS, config_pattern_alias)
    else:
        pattern_alias = dict(PATTERN_ALIAS)
    # Merge auto-derived aliases from lineage map as fallback (lower priority).
    # Manual entries always take precedence; auto entries fill gaps.
    if lineage_auto_alias:
        for family, symbols in lineage_auto_alias.items():
            if family not in pattern_alias:
                pattern_alias[family] = list(symbols)
            else:
                existing = set(pattern_alias[family])
                for sym in symbols:
                    if sym not in existing:
                        pattern_alias[family] = pattern_alias[family] + [sym]
    composite_mappings = merge_mapping_dict(DEFAULT_COMPOSITE_MAPPINGS, composite_data.get("composite_mappings", {}))
    return MappingConfig(
        special_path_rules=special_path_rules,
        pattern_alias=pattern_alias,
        composite_mappings=composite_mappings,
    )


@dataclass
class SdkIndex:
    component_names: set[str] = field(default_factory=set)
    modifier_names: set[str] = field(default_factory=set)
    top_level_modules: set[str] = field(default_factory=set)
    component_file_bases: dict[str, str] = field(default_factory=dict)
    modifier_file_bases: dict[str, str] = field(default_factory=dict)


@dataclass
class ContentModifierIndex:
    families: set[str] = field(default_factory=set)
    family_to_symbols: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class MappingConfig:
    special_path_rules: dict[str, dict] = field(default_factory=dict)
    pattern_alias: dict[str, list[str]] = field(default_factory=dict)
    composite_mappings: dict[str, dict] = field(default_factory=dict)


@dataclass
class ChangedFileExclusionConfig:
    path_prefixes: list[str] = field(default_factory=list)
    rules: list[dict[str, object]] = field(default_factory=list)


@dataclass
class AppConfig:
    repo_root: Path
    xts_root: Path
    sdk_api_root: Path
    cache_file: Path | None
    git_repo_root: Path
    git_remote: str
    git_base_branch: str
    git_host_kind: str = "auto"
    git_host_api_url: str | None = None
    git_host_token: str | None = None
    git_host_config_path: Path | None = None
    server_host: str | None = None
    server_user: str | None = None
    device: str | None = None
    devices: list[str] = field(default_factory=list)
    gitcode_api_url: str | None = None
    gitcode_token: str | None = None
    acts_out_root: Path | None = None
    path_rules_file: Path | None = None
    composite_mappings_file: Path | None = None
    ranking_rules_file: Path | None = None
    changed_file_exclusions_file: Path | None = None
    product_name: str | None = None
    system_size: str = "standard"
    xts_suitetype: str | None = None
    selector_repo_root: Path | None = None
    run_label: str | None = None
    run_store_root: Path | None = None
    runtime_state_root: Path | None = None
    shard_mode: str = "mirror"
    device_lock_timeout: float = 30.0
    daily_build_tag: str | None = None
    daily_component: str = DEFAULT_DAILY_COMPONENT
    daily_branch: str = "master"
    daily_date: str | None = None
    daily_cache_root: Path | None = None
    daily_prebuilt: PreparedDailyPrebuilt | None = None
    daily_prebuilt_ready: bool = False
    daily_prebuilt_note: str = ""
    quick_mode: bool = False
    sdk_build_tag: str | None = None
    sdk_component: str = DEFAULT_SDK_COMPONENT
    sdk_branch: str = "master"
    sdk_date: str | None = None
    sdk_cache_root: Path | None = None
    firmware_build_tag: str | None = None
    firmware_component: str = DEFAULT_FIRMWARE_COMPONENT
    firmware_branch: str = "master"
    firmware_date: str | None = None
    firmware_cache_root: Path | None = None
    flash_firmware_path: Path | None = None
    flash_py_path: Path | None = None
    hdc_path: Path | None = None
    hdc_endpoint: str | None = None


@dataclass
class TestFileIndex:
    relative_path: str
    surface: str = "utility"
    imports: set[str] = field(default_factory=set)
    imported_symbols: set[str] = field(default_factory=set)
    identifier_calls: set[str] = field(default_factory=set)
    member_calls: set[str] = field(default_factory=set)
    type_member_calls: set[str] = field(default_factory=set)
    typed_field_accesses: set[str] = field(default_factory=set)
    typed_modifier_bases: set[str] = field(default_factory=set)
    words: set[str] = field(default_factory=set)
    # Phase 5: evidence kind tracking
    evidence_kinds: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "relative_path": self.relative_path,
            "surface": self.surface,
            "imports": sorted(self.imports),
            "imported_symbols": sorted(self.imported_symbols),
            "identifier_calls": sorted(self.identifier_calls),
            "member_calls": sorted(self.member_calls),
            "type_member_calls": sorted(self.type_member_calls),
            "typed_field_accesses": sorted(self.typed_field_accesses),
            "typed_modifier_bases": sorted(self.typed_modifier_bases),
            "words": sorted(self.words),
            "evidence_kinds": dict(self.evidence_kinds),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestFileIndex":
        return cls(
            relative_path=data["relative_path"],
            surface=data.get("surface", "utility"),
            imports=set(data["imports"]),
            imported_symbols=set(data["imported_symbols"]),
            identifier_calls=set(data["identifier_calls"]),
            member_calls=set(data["member_calls"]),
            type_member_calls=set(data.get("type_member_calls", [])),
            typed_field_accesses=set(data.get("typed_field_accesses", [])),
            typed_modifier_bases=set(data.get("typed_modifier_bases", [])),
            words=set(data["words"]),
            evidence_kinds=data.get("evidence_kinds", {}),
        )


@dataclass
class TestProjectIndex:
    relative_root: str
    test_json: str
    bundle_name: str | None
    files: list[TestFileIndex] = field(default_factory=list)
    path_key: str = ""
    variant: str = "unknown"
    surface: str = "unknown"
    supported_surfaces: set[str] = field(default_factory=set)
    search_summary_ready: bool = False
    search_imports: set[str] = field(default_factory=set)
    search_imported_symbols: set[str] = field(default_factory=set)
    search_imported_symbol_tokens: set[str] = field(default_factory=set)
    search_identifier_calls: set[str] = field(default_factory=set)
    search_identifier_call_tokens: set[str] = field(default_factory=set)
    search_member_call_tokens: set[str] = field(default_factory=set)
    search_type_owner_tokens: set[str] = field(default_factory=set)
    search_typed_field_types: set[str] = field(default_factory=set)
    search_exact_member_keys: set[str] = field(default_factory=set)
    search_typed_modifier_bases: set[str] = field(default_factory=set)
    search_words: set[str] = field(default_factory=set)
    search_path_tokens: set[str] = field(default_factory=set)
    search_project_path_compact: str = ""
    search_file_path_compacts: list[str] = field(default_factory=list)
    search_evidence_kinds: dict[str, str] = field(default_factory=dict)
    _serialized_files: list[dict] | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        payload = {
            "relative_root": self.relative_root,
            "test_json": self.test_json,
            "bundle_name": self.bundle_name,
            "path_key": self.path_key,
            "variant": self.variant,
            "surface": self.surface,
            "supported_surfaces": sorted(self.supported_surfaces),
            "files": self._serialized_files if self._serialized_files is not None else [item.to_dict() for item in self.files],
        }
        if self.search_summary_ready:
            payload["search_summary"] = {
                "imports": sorted(self.search_imports),
                "imported_symbols": sorted(self.search_imported_symbols),
                "imported_symbol_tokens": sorted(self.search_imported_symbol_tokens),
                "identifier_calls": sorted(self.search_identifier_calls),
                "identifier_call_tokens": sorted(self.search_identifier_call_tokens),
                "member_call_tokens": sorted(self.search_member_call_tokens),
                "type_owner_tokens": sorted(self.search_type_owner_tokens),
                "typed_field_types": sorted(self.search_typed_field_types),
                "exact_member_keys": sorted(self.search_exact_member_keys),
                "typed_modifier_bases": sorted(self.search_typed_modifier_bases),
                "words": sorted(self.search_words),
                "path_tokens": sorted(self.search_path_tokens),
                "project_path_compact": self.search_project_path_compact,
                "file_path_compacts": list(self.search_file_path_compacts),
                "evidence_kinds": dict(self.search_evidence_kinds),
            }
        return payload

    @classmethod
    def from_dict(cls, data: dict, *, lazy_files: bool = False) -> "TestProjectIndex":
        summary = data.get("search_summary")
        raw_files = data.get("files", [])
        serialized_files = None
        files: list[TestFileIndex]
        if lazy_files and isinstance(summary, dict) and isinstance(raw_files, list):
            files = []
            serialized_files = raw_files
        else:
            files = [TestFileIndex.from_dict(item) for item in raw_files]
        project = cls(
            relative_root=data["relative_root"],
            test_json=data["test_json"],
            bundle_name=data.get("bundle_name"),
            path_key=data["path_key"],
            variant=data.get("variant", "unknown"),
            surface=data.get("surface", data.get("variant", "unknown")),
            supported_surfaces=set(data.get("supported_surfaces", [])),
            files=files,
            _serialized_files=serialized_files,
        )
        if isinstance(summary, dict):
            project.search_summary_ready = True
            project.search_imports = set(summary.get("imports", []))
            project.search_imported_symbols = set(summary.get("imported_symbols", []))
            project.search_imported_symbol_tokens = set(summary.get("imported_symbol_tokens", []))
            project.search_identifier_calls = set(summary.get("identifier_calls", []))
            project.search_identifier_call_tokens = set(summary.get("identifier_call_tokens", []))
            project.search_member_call_tokens = set(summary.get("member_call_tokens", []))
            project.search_type_owner_tokens = set(summary.get("type_owner_tokens", []))
            project.search_typed_field_types = set(summary.get("typed_field_types", []))
            project.search_exact_member_keys = set(summary.get("exact_member_keys", []))
            project.search_typed_modifier_bases = set(summary.get("typed_modifier_bases", []))
            project.search_words = set(summary.get("words", []))
            project.search_path_tokens = set(summary.get("path_tokens", []))
            project.search_project_path_compact = str(summary.get("project_path_compact", ""))
            project.search_file_path_compacts = [str(item) for item in summary.get("file_path_compacts", [])]
            project.search_evidence_kinds = dict(summary.get("evidence_kinds", {}))
        return project



def repo_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def ensure_project_search_summary(project: TestProjectIndex) -> TestProjectIndex:
    if project.search_summary_ready:
        return project

    project_path_compact = compact_token(project.path_key)
    path_tokens = {
        compact_token(part)
        for part in tokenize_path_parts(project.path_key.lower())
        if compact_token(part)
    }
    path_tokens.update(path_component_tokens(project.path_key.lower()))

    file_path_compacts: list[str] = []
    for file_index in project.files:
        file_path_compact = compact_token(file_index.relative_path)
        if file_path_compact:
            file_path_compacts.append(file_path_compact)
        lower_relative_path = file_index.relative_path.lower()
        path_tokens.update(
            compact_token(part)
            for part in tokenize_path_parts(lower_relative_path)
            if compact_token(part)
        )
        path_tokens.update(path_component_tokens(lower_relative_path))
        project.search_imports.update(file_index.imports)
        project.search_imported_symbols.update(file_index.imported_symbols)
        project.search_identifier_calls.update(file_index.identifier_calls)
        project.search_imported_symbol_tokens.update(
            compact_token(symbol)
            for symbol in file_index.imported_symbols
            if compact_token(symbol)
        )
        project.search_identifier_call_tokens.update(
            compact_token(identifier)
            for identifier in file_index.identifier_calls
            if compact_token(identifier)
        )
        project.search_member_call_tokens.update(
            compact_token(member)
            for member in file_index.member_calls
            if compact_token(member)
        )
        for entry in file_index.type_member_calls:
            owner, _separator, _member = entry.partition(".")
            owner_token = compact_token(owner)
            if owner_token:
                project.search_type_owner_tokens.add(owner_token)
            normalized = normalize_member_hint(entry)
            if normalized:
                project.search_exact_member_keys.add(normalized)
        for entry in file_index.typed_field_accesses:
            owner, _separator, _field = entry.partition(".")
            owner_token = compact_token(owner)
            if owner_token:
                project.search_typed_field_types.add(owner_token)
            normalized = normalize_member_hint(entry)
            if normalized:
                project.search_exact_member_keys.add(normalized)
        project.search_typed_modifier_bases.update(file_index.typed_modifier_bases)
        project.search_words.update(compact_token(word) for word in file_index.words if compact_token(word))
        project.search_evidence_kinds.update(file_index.evidence_kinds)

    project.search_path_tokens = {token for token in path_tokens if token}
    project.search_project_path_compact = project_path_compact
    project.search_file_path_compacts = file_path_compacts
    project.search_summary_ready = True
    return project


def ensure_project_files_loaded(project: TestProjectIndex) -> TestProjectIndex:
    if project.files or not project._serialized_files:
        return project
    project.files = [TestFileIndex.from_dict(item) for item in project._serialized_files if isinstance(item, dict)]
    return project


def project_matches_exact_api_prefilter(project: TestProjectIndex, signals: dict[str, set[str]]) -> bool:
    ensure_project_search_summary(project)
    exact_api_entities = {str(item) for item in signals.get("exact_api_prefilter_entities", set()) if "." in str(item)}
    exact_member_hints = extract_member_hint_keys(signals.get("member_hints", set()))
    if not exact_api_entities and not exact_member_hints:
        return False

    exact_member_keys = set(project.search_exact_member_keys)
    for member_hint in sorted(exact_member_hints):
        if member_hint in exact_member_keys:
            return True
    for api_entity in sorted(exact_api_entities):
        normalized = normalize_member_hint(api_entity)
        if normalized and normalized in exact_member_keys:
            return True

    type_tokens = (
        set(project.search_type_owner_tokens)
        | set(project.search_imported_symbol_tokens)
        | set(project.search_identifier_call_tokens)
    )
    member_tokens = set(project.search_member_call_tokens)
    for api_entity in sorted(exact_api_entities):
        owner, separator, method = api_entity.partition(".")
        if not separator or not owner or not method:
            continue
        owner_token = compact_token(owner)
        method_token = compact_token(method)
        if owner_token and method_token and owner_token in type_tokens and method_token in member_tokens:
            return True
    return False


def project_might_match(
    project: TestProjectIndex,
    signals: dict[str, set[str]],
    *,
    exact_api_prefilter_mode: bool | None = None,
) -> bool:
    ensure_project_search_summary(project)
    exact_api_prefilter = (
        bool(signals.get("exact_api_prefilter_entities"))
        or bool(extract_member_hint_keys(signals.get("member_hints", set())))
        or any("." in item for item in signals.get("symbols", set()))
    ) if exact_api_prefilter_mode is None else bool(exact_api_prefilter_mode)

    if exact_api_prefilter:
        return project_matches_exact_api_prefilter(project, signals)

    if signals["modules"] & project.search_imports:
        return True

    for token in signals.get("project_hints", set()):
        if not token:
            continue
        if token in project.search_path_tokens or token in project.search_words:
            return True
        if token in project.search_project_path_compact:
            return True
        if any(token in file_path for file_path in project.search_file_path_compacts):
            return True

    for method in signals.get("method_hints", set()):
        method_token = compact_token(method)
        if method_token and method_token in project.search_member_call_tokens:
            return True

    for hint in signals.get("type_hints", set()):
        hint_token = compact_token(hint)
        if not hint_token:
            continue
        if (
            hint_token in project.search_type_owner_tokens
            or hint_token in project.search_imported_symbol_tokens
            or hint_token in project.search_identifier_call_tokens
            or hint_token in project.search_typed_field_types
        ):
            return True

    for symbol in signals.get("symbols", set()):
        symbol_token = compact_token(symbol)
        if symbol in project.search_imported_symbols or symbol in project.search_identifier_calls:
            return True
        if symbol_token and (
            symbol_token in project.search_imported_symbol_tokens
            or symbol_token in project.search_identifier_call_tokens
            or symbol_token in project.search_member_call_tokens
            or symbol_token in project.search_type_owner_tokens
            or symbol_token in project.search_typed_field_types
            or symbol_token in project.search_words
        ):
            return True
        if symbol.endswith("Modifier"):
            base_token = compact_token(symbol[:-8])
            if base_token and base_token in project.search_typed_modifier_bases:
                return True

    # Weak symbol fallback — only check if no strong match yet
    weak_symbols = signals.get("weak_symbols", set())
    if weak_symbols:
        project_identifier_calls = project.search_identifier_calls
        if weak_symbols & project_identifier_calls:
            return True

    return False


def select_candidate_projects(
    projects: list[TestProjectIndex],
    signals: dict[str, set[str]],
    variants_mode: str,
) -> tuple[list[TestProjectIndex], list[TestProjectIndex]]:
    variant_projects = [project for project in projects if variant_matches(project.variant, variants_mode)]
    exact_shortlisted: list[TestProjectIndex] = []
    if signals.get("exact_api_prefilter_entities"):
        exact_shortlisted = [
            project
            for project in variant_projects
            if project_might_match(project, signals, exact_api_prefilter_mode=True)
        ]
        if exact_shortlisted:
            return variant_projects, exact_shortlisted

    shortlisted = [
        project
        for project in variant_projects
        if project_might_match(project, signals, exact_api_prefilter_mode=False)
    ]
    if not shortlisted:
        return variant_projects, variant_projects
    return variant_projects, shortlisted


def normalize_changed_files(values: Iterable[str], base_roots: Iterable[Path] | None = None) -> list[Path]:
    candidate_roots: list[Path] = []
    seen_roots: set[Path] = set()
    for root in list(base_roots or []) + [REPO_ROOT]:
        resolved_root = root.resolve()
        if resolved_root in seen_roots:
            continue
        seen_roots.add(resolved_root)
        candidate_roots.append(resolved_root)
    result: list[Path] = []
    for value in values:
        raw = value.strip()
        if not raw:
            continue
        path = Path(raw)
        if path.is_absolute():
            result.append(path.resolve())
            continue

        candidate_paths = [(root / raw).resolve() for root in candidate_roots] or [(REPO_ROOT / raw).resolve()]
        existing = next((candidate for candidate in candidate_paths if candidate.exists()), None)
        result.append(existing or candidate_paths[0])
    return result


def parse_changed_ranges(
    values: Iterable[str],
    *,
    changed_files: Iterable[Path],
    base_roots: Iterable[Path] | None = None,
) -> dict[Path, list[tuple[int, int]]]:
    changed_file_list = [path.resolve() for path in changed_files]
    result: dict[Path, list[tuple[int, int]]] = {}
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        parts = raw.rsplit(":", 2)
        target_path: Path
        start_raw: str
        end_raw: str
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            if len(changed_file_list) != 1:
                raise ValueError(f"Ambiguous changed range '{raw}': file path is required when multiple changed files are present.")
            target_path = changed_file_list[0]
            start_raw, end_raw = parts
        elif len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            path_value, start_raw, end_raw = parts
            normalized_paths = normalize_changed_files([path_value], base_roots=base_roots)
            if not normalized_paths:
                raise ValueError(f"Unable to resolve changed range path from '{raw}'.")
            target_path = normalized_paths[0].resolve()
        else:
            raise ValueError(f"Invalid changed range '{raw}'. Expected 'start:end' or 'path:start:end'.")

        start = max(1, int(start_raw))
        end = max(start, int(end_raw))
        result.setdefault(target_path, []).append((start, end))
    return result


def merge_changed_ranges(ranges: Iterable[tuple[int, int]] | None) -> list[tuple[int, int]]:
    normalized: list[tuple[int, int]] = []
    for start, end in ranges or []:
        start_line = max(1, int(start))
        end_line = max(start_line, int(end))
        normalized.append((start_line, end_line))
    if not normalized:
        return []
    normalized.sort()
    merged = [normalized[0]]
    for start, end in normalized[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def merge_changed_range_maps(
    *range_maps: dict[Path, list[tuple[int, int]]] | None,
) -> dict[Path, list[tuple[int, int]]]:
    merged: dict[Path, list[tuple[int, int]]] = {}
    for range_map in range_maps:
        for path, ranges in (range_map or {}).items():
            merged.setdefault(path.resolve(), []).extend(list(ranges or []))
    return {path: merge_changed_ranges(ranges) for path, ranges in merged.items()}


def build_line_start_offsets(text: str) -> list[int]:
    offsets = [0]
    for match in re.finditer(r"\n", text):
        offsets.append(match.end())
    return offsets


def offset_to_line_number(offsets: list[int], offset: int) -> int:
    return max(1, bisect_right(offsets, max(0, offset)))


def span_overlaps_changed_ranges(
    span_start: int,
    span_end: int,
    *,
    line_offsets: list[int],
    changed_ranges: Iterable[tuple[int, int]] | None,
) -> bool:
    normalized_ranges = merge_changed_ranges(changed_ranges)
    if not normalized_ranges:
        return True
    start_line = offset_to_line_number(line_offsets, span_start)
    end_line = offset_to_line_number(line_offsets, max(span_start, span_end - 1))
    return any(not (end_line < range_start or start_line > range_end) for range_start, range_end in normalized_ranges)


def extract_text_in_changed_ranges(text: str, changed_ranges: list[tuple[int, int]] | None) -> str:
    if not changed_ranges:
        return text
    lines = text.split("\n")
    selected: list[str] = []
    for start, end in changed_ranges:
        for i in range(max(0, start - 1), min(len(lines), end)):
            selected.append(lines[i])
    return "\n".join(selected)


def parse_unified_diff_changed_ranges(patch_text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for start_raw, count_raw in UNIFIED_DIFF_HUNK_RE.findall(str(patch_text or "")):
        start = max(1, int(start_raw))
        count = int(count_raw) if count_raw else 1
        if count <= 0:
            ranges.append((start, start))
            continue
        ranges.append((start, start + count - 1))
    return merge_changed_ranges(ranges)


def extract_patch_text_from_pr_file_item(item: dict[str, object]) -> str:
    for key in ("patch", "diff_hunk", "diff", "changes"):
        raw_value = item.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value
        if isinstance(raw_value, dict):
            for nested_key in ("diff", "diff_hunk", "patch", "changes"):
                nested_value = raw_value.get(nested_key)
                if isinstance(nested_value, str) and nested_value.strip():
                    return nested_value
    return ""


def load_changed_file_exclusion_config(path_value: Path | None) -> ChangedFileExclusionConfig:
    data = load_json_if_exists(path_value)
    configured_prefixes = data.get("path_prefixes", []) if isinstance(data, dict) else []
    configured_rules = data.get("rules", []) if isinstance(data, dict) else []
    prefixes: list[str] = []
    rules: list[dict[str, object]] = []
    for raw_rule in list(DEFAULT_CHANGED_FILE_EXCLUSION_RULES.get("rules", [])) + list(configured_rules):
        if not isinstance(raw_rule, dict):
            continue
        path_prefix = raw_rule.get("path_prefix")
        if not isinstance(path_prefix, str):
            continue
        normalized = path_prefix.replace('\\', '/').strip().lstrip('./').lower()
        if normalized and not normalized.endswith('/'):
            normalized += '/'
        if not normalized or normalized in prefixes:
            continue
        prefixes.append(normalized)
        rules.append(
            {
                "id": str(raw_rule.get("id") or normalized.rstrip('/').split('/')[-1] or "rule"),
                "category": str(raw_rule.get("category") or "generic_exclusion"),
                "path_prefix": normalized,
                "description": str(raw_rule.get("description") or ""),
                "how_to_identify": [
                    str(item)
                    for item in raw_rule.get("how_to_identify", [])
                    if isinstance(item, str) and item.strip()
                ],
            }
        )
    for value in configured_prefixes:
        if not isinstance(value, str):
            continue
        normalized = value.replace('\\', '/').strip().lstrip('./').lower()
        if normalized and not normalized.endswith('/'):
            normalized += '/'
        if not normalized or normalized in prefixes:
            continue
        prefixes.append(normalized)
        rules.append(
            {
                "id": normalized.rstrip('/').split('/')[-1] or "legacy_prefix",
                "category": "legacy_prefix_exclusion",
                "path_prefix": normalized,
                "description": "Legacy path-prefix exclusion loaded from path_prefixes.",
                "how_to_identify": [f"Path starts with {normalized}"],
            }
        )
    return ChangedFileExclusionConfig(path_prefixes=prefixes, rules=rules)


def changed_file_match_keys(path: Path, git_repo_root: Path) -> set[str]:
    candidates: set[str] = set()
    raw = str(path).replace('\\', '/').strip()
    if raw:
        candidates.add(raw.lower().lstrip('./'))
    resolved = path.resolve()
    for root in (REPO_ROOT, git_repo_root):
        try:
            rel = resolved.relative_to(root.resolve()).as_posix().lower()
        except ValueError:
            continue
        if rel:
            candidates.add(rel.lstrip('./'))
    return {item for item in candidates if item}


def describe_changed_file(path: Path, git_repo_root: Path) -> str:
    keys = changed_file_match_keys(path, git_repo_root)
    preferred = sorted(keys, key=len)
    if preferred:
        return preferred[0]
    return str(path).replace('\\', '/')


def match_changed_file_exclusion(
    path: Path,
    git_repo_root: Path,
    exclusion_config: ChangedFileExclusionConfig,
) -> dict | None:
    keys = changed_file_match_keys(path, git_repo_root)
    for rule in exclusion_config.rules:
        prefix = str(rule.get("path_prefix") or "")
        if any(key.startswith(prefix) for key in keys):
            return {
                "changed_file": describe_changed_file(path, git_repo_root),
                "reason": "excluded_from_xts_analysis",
                "matched_prefix": prefix,
                "rule_id": rule.get("id", ""),
                "category": rule.get("category", ""),
                "description": rule.get("description", ""),
                "how_to_identify": list(rule.get("how_to_identify", [])),
            }
    return None


def filter_changed_files_for_xts(
    changed_files: list[Path],
    git_repo_root: Path,
    exclusion_config: ChangedFileExclusionConfig,
) -> tuple[list[Path], list[dict]]:
    kept: list[Path] = []
    excluded: list[dict] = []
    for path in changed_files:
        match = match_changed_file_exclusion(path, git_repo_root, exclusion_config)
        if match:
            excluded.append(match)
            continue
        kept.append(path)
    return kept, excluded


def git_changed_files(repo_root: Path, diff_ref: str) -> list[Path]:
    command = ["git", "-C", str(repo_root), "diff", "--name-only", diff_ref]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git diff failed")
    return normalize_changed_files(completed.stdout.splitlines(), base_roots=[repo_root])


def run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def parse_pr_number(pr_url: str) -> str:
    if pr_url.isdigit():
        return pr_url
    parsed = urlparse(pr_url)
    match = re.search(r"/(?:pulls?|merge_requests)/(\d+)", parsed.path)
    if not match:
        raise RuntimeError(f"could not parse PR number from URL: {pr_url}")
    return match.group(1)


def parse_owner_repo_from_pr(pr_ref: str) -> tuple[str, str] | None:
    if pr_ref.isdigit():
        return None
    parsed = urlparse(pr_ref)
    match = re.search(r"/([^/]+)/([^/]+)/(?:pulls?|merge_requests)/\d+", parsed.path)
    if not match:
        return None
    return match.group(1), match.group(2)


def parse_owner_repo_from_remote_url(remote_url: str) -> tuple[str, str] | None:
    value = remote_url.strip()
    if not value:
        return None
    if value.endswith(".git"):
        value = value[:-4]
    if "://" in value:
        parsed = urlparse(value)
        parts = [part for part in parsed.path.split("/") if part]
    elif "@" in value and ":" in value:
        parts = [part for part in value.split(":", 1)[1].split("/") if part]
    else:
        parts = [part for part in value.split("/") if part]
    if len(parts) < 2:
        return None
    return parts[-2], parts[-1]


def discover_owner_repo_from_git_remote(repo_root: Path, remote: str) -> tuple[str, str] | None:
    completed = run_git(repo_root, ["config", "--get", f"remote.{remote}.url"])
    if completed.returncode != 0:
        return None
    return parse_owner_repo_from_remote_url(completed.stdout.strip())


def resolve_pr_owner_repo(pr_ref: str, repo_root: Path, remote: str) -> tuple[str, str] | None:
    return parse_owner_repo_from_pr(pr_ref) or discover_owner_repo_from_git_remote(repo_root, remote)


def fetch_pr_changed_files(repo_root: Path, remote: str, base_branch: str, pr_ref: str) -> list[Path]:
    pr_number = parse_pr_number(pr_ref)
    base_ref = f"refs/tmp/arkui_xts_selector/pr/{pr_number}/base"
    head_ref = f"refs/tmp/arkui_xts_selector/pr/{pr_number}/head"
    base_specs = [
        f"refs/heads/{base_branch}:{base_ref}",
        f"{base_branch}:{base_ref}",
    ]
    fetch_specs = [
        f"refs/pull/{pr_number}/head:{head_ref}",
        f"pull/{pr_number}/head:{head_ref}",
        f"refs/merge-requests/{pr_number}/head:{head_ref}",
    ]
    last_error = "unknown fetch error"
    base_ready = False
    for base_spec in base_specs:
        completed = run_git(repo_root, ["fetch", "--depth=400", remote, base_spec])
        if completed.returncode == 0:
            base_ready = True
            break
        last_error = completed.stderr.strip() or completed.stdout.strip() or last_error
    if not base_ready:
        raise RuntimeError(last_error)
    for spec in fetch_specs:
        completed = run_git(repo_root, ["fetch", "--depth=400", remote, spec])
        if completed.returncode == 0:
            diff = run_git(repo_root, ["diff", "--name-only", f"{base_ref}...{head_ref}"])
            if diff.returncode != 0:
                raise RuntimeError(diff.stderr.strip() or "git diff failed")
            return normalize_changed_files(diff.stdout.splitlines(), base_roots=[repo_root])
        last_error = completed.stderr.strip() or completed.stdout.strip() or last_error
    raise RuntimeError(last_error)


def infer_git_host_kind(
    pr_ref: str,
    *,
    configured_kind: str | None = None,
    api_url: str | None = None,
) -> str:
    normalized_kind = normalize_git_host_kind(configured_kind)
    if normalized_kind != "auto":
        return normalized_kind

    parsed_pr = urlparse(pr_ref) if not str(pr_ref).isdigit() else None
    if parsed_pr is not None:
        pr_host = parsed_pr.netloc.lower()
        pr_path = parsed_pr.path.lower()
        if "codehub" in pr_host:
            return "codehub"
        if "gitcode" in pr_host:
            return "gitcode"
        if "/merge_requests/" in pr_path:
            return "codehub"
        if re.search(r"/pulls?/\d+", pr_path):
            return "gitcode"

    parsed_api = urlparse(api_url or "")
    api_host = parsed_api.netloc.lower()
    if "codehub" in api_host:
        return "codehub"
    if "gitcode" in api_host:
        return "gitcode"
    return "gitcode"


def resolve_pr_api_credentials(app_config: AppConfig, pr_ref: str) -> tuple[str, str | None, str | None]:
    host_kind = infer_git_host_kind(
        pr_ref,
        configured_kind=app_config.git_host_kind,
        api_url=app_config.git_host_api_url or app_config.gitcode_api_url,
    )
    api_url = app_config.git_host_api_url or app_config.gitcode_api_url
    token = app_config.git_host_token or app_config.gitcode_token
    if (not api_url or not token) and app_config.git_host_config_path:
        ini_url, ini_token = load_ini_git_host_config(
            str(app_config.git_host_config_path),
            app_config.repo_root,
            host_kind,
        )
        api_url = api_url or ini_url
        token = token or ini_token
    return host_kind, api_url, token


def fetch_git_host_api_json(api_kind: str, api_url: str, token: str, api_path: str | Iterable[str]) -> object:
    base = api_url.rstrip("/")
    api_paths = [api_path] if isinstance(api_path, str) else [str(item) for item in api_path if str(item)]
    last_error = f"{api_kind} api failed"
    for candidate_path in api_paths:
        requests_to_try: list[urllib.request.Request]
        if api_kind == "gitcode":
            separator = "&" if "?" in candidate_path else "?"
            requests_to_try = [
                urllib.request.Request(
                    f"{base}{candidate_path}{separator}{urllib.parse.urlencode({'access_token': token})}",
                    headers={"Accept": "application/json"},
                ),
                urllib.request.Request(
                    f"{base}{candidate_path}",
                    headers={"Accept": "application/json", "private-token": token},
                ),
            ]
        else:
            requests_to_try = [
                urllib.request.Request(
                    f"{base}{candidate_path}",
                    headers={"Accept": "application/json", "Private-Token": token},
                ),
            ]
        path_missing = True
        for request in requests_to_try:
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_error = f"{api_kind} api failed: {exc}"
                path_missing = path_missing and exc.code in {404, 410}
            except urllib.error.URLError as exc:
                last_error = f"{api_kind} api failed: {exc}"
                path_missing = False
            except json.JSONDecodeError as exc:
                last_error = f"{api_kind} api returned invalid json: {exc}"
                path_missing = False
        if not path_missing:
            break
    raise RuntimeError(last_error)


def fetch_pr_metadata_via_api(api_kind: str, api_url: str, token: str, owner: str, repo: str, pr_ref: str) -> dict:
    pr_number = parse_pr_number(pr_ref)
    if api_kind == "codehub":
        project_id = urllib.parse.quote(f"{owner}/{repo}", safe="")
        api_path: str | list[str] = [
            f"/api/v4/projects/{project_id}/isource/merge_requests/{pr_number}",
            f"/api/v4/projects/{project_id}/merge_requests/{pr_number}",
        ]
    else:
        api_path = f"/api/v5/repos/{owner}/{repo}/pulls/{pr_number}"
    data = fetch_git_host_api_json(api_kind, api_url, token, api_path)
    if not isinstance(data, dict):
        raise RuntimeError(f"{api_kind} api unexpected PR response: {data}")
    return data


def fetch_pr_changed_files_via_api(
    api_kind: str,
    api_url: str,
    token: str,
    owner: str,
    repo: str,
    pr_ref: str,
    repo_root: Path,
) -> list[Path]:
    changed_files, _changed_ranges = fetch_pr_changed_files_and_ranges_via_api(
        api_kind=api_kind,
        api_url=api_url,
        token=token,
        owner=owner,
        repo=repo,
        pr_ref=pr_ref,
        repo_root=repo_root,
    )
    return changed_files


def fetch_pr_changed_files_and_ranges_via_api(
    api_kind: str,
    api_url: str,
    token: str,
    owner: str,
    repo: str,
    pr_ref: str,
    repo_root: Path,
) -> tuple[list[Path], dict[Path, list[tuple[int, int]]]]:
    pr_number = parse_pr_number(pr_ref)
    changed_files: list[Path] = []
    changed_ranges_by_file: dict[Path, list[tuple[int, int]]] = {}

    def _append_item(path_value: str | None, item: dict[str, object]) -> None:
        if not path_value:
            return
        normalized_paths = normalize_changed_files([path_value], base_roots=[repo_root])
        if not normalized_paths:
            return
        normalized_path = normalized_paths[0]
        changed_files.append(normalized_path)
        patch_text = extract_patch_text_from_pr_file_item(item)
        parsed_ranges = parse_unified_diff_changed_ranges(patch_text)
        if parsed_ranges:
            resolved_path = normalized_path.resolve()
            changed_ranges_by_file[resolved_path] = merge_changed_ranges(
                list(changed_ranges_by_file.get(resolved_path, [])) + parsed_ranges
            )

    if api_kind == "codehub":
        project_id = urllib.parse.quote(f"{owner}/{repo}", safe="")
        data = fetch_git_host_api_json(
            api_kind,
            api_url,
            token,
            [
                f"/api/v4/projects/{project_id}/isource/merge_requests/{pr_number}/changes",
                f"/api/v4/projects/{project_id}/merge_requests/{pr_number}/changes",
            ],
        )
        if isinstance(data, dict):
            data = data.get("changes") or data.get("files") or data.get("data") or data.get("changed_files")
        if not isinstance(data, list):
            raise RuntimeError(f"{api_kind} api unexpected response: {data}")
        for item in data:
            if not isinstance(item, dict):
                continue
            _append_item(
                item.get("new_path") or item.get("old_path") or item.get("filename"),
                item,
            )
    else:
        data = fetch_git_host_api_json(api_kind, api_url, token, f"/api/v5/repos/{owner}/{repo}/pulls/{pr_number}/files")
        if isinstance(data, dict):
            data = data.get("files") or data.get("data") or data.get("changed_files")
        if not isinstance(data, list):
            raise RuntimeError(f"{api_kind} api unexpected response: {data}")
        for item in data:
            if not isinstance(item, dict):
                continue
            _append_item(
                item.get("filename") or item.get("new_path") or item.get("old_path"),
                item,
            )

    deduped_files: list[Path] = []
    seen_paths: set[Path] = set()
    for changed_file in changed_files:
        resolved = changed_file.resolve()
        if resolved in seen_paths:
            continue
        deduped_files.append(changed_file)
        seen_paths.add(resolved)
    return deduped_files, changed_ranges_by_file


def resolve_pr_changed_files(app_config: AppConfig, pr_ref: str, pr_source: str) -> list[Path]:
    changed_files, _changed_ranges = resolve_pr_changed_files_with_ranges(app_config, pr_ref, pr_source)
    return changed_files


def resolve_pr_changed_files_with_ranges(
    app_config: AppConfig,
    pr_ref: str,
    pr_source: str,
) -> tuple[list[Path], dict[Path, list[tuple[int, int]]]]:
    owner_repo = resolve_pr_owner_repo(pr_ref, app_config.git_repo_root, app_config.git_remote)
    api_error: RuntimeError | None = None
    if pr_source in ("auto", "api"):
        api_kind, api_url, token = resolve_pr_api_credentials(app_config, pr_ref)
        if not api_url or not token:
            api_error = RuntimeError(
                "PR API mode requires git host credentials; pass --git-host-token/--git-host-url or --git-host-config with [gitcode]/[codehub] token/url."
            )
        elif owner_repo is None:
            api_error = RuntimeError("could not determine owner/repo for PR API mode from --pr-url or local git remote")
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
            raise api_error if api_error is not None else RuntimeError("PR API mode failed")

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


def extract_typed_field_accesses(text: str) -> set[str]:
    # Keep this wrapper for backwards compatibility with existing tests and
    # call sites while routing extraction to the semantic parser module.
    return extract_typed_field_accesses_semantic(text)


def parse_test_file(path: Path) -> TestFileIndex:
    text = read_text(path)
    surface_profile = classify_xts_file_surface(path, text)
    semantics = extract_consumer_semantics(text)
    return TestFileIndex(
        relative_path=repo_rel(path),
        surface=surface_profile.surface,
        imports=semantics.imports,
        imported_symbols=semantics.imported_symbols,
        identifier_calls=semantics.identifier_calls,
        member_calls=semantics.member_calls,
        type_member_calls=semantics.type_member_calls,
        typed_field_accesses=semantics.typed_field_accesses,
        typed_modifier_bases=semantics.typed_modifier_bases,
        words=semantics.words,
        evidence_kinds=semantics.evidence_kinds,
    )


def parse_bundle_name(test_json: Path) -> str | None:
    text = read_text(test_json)
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data.get("driver", {}).get("bundle-name")


def parse_test_file_names_from_test_json(test_json: Path) -> list[str]:
    text = read_text(test_json)
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    result: list[str] = []
    for kit in data.get("kits", []):
        if not isinstance(kit, dict):
            continue
        names = kit.get("test-file-name", [])
        if isinstance(names, list):
            result.extend([item for item in names if isinstance(item, str)])
    return result


def _classify_project_variant_from_names(relative_root: str, test_file_names: list[str]) -> str:
    markers: set[str] = set()
    root_lower = relative_root.lower()
    if 'static' in root_lower:
        markers.add('static')
    if 'dynamic' in root_lower:
        markers.add('dynamic')
    for item in test_file_names:
        lower = item.lower()
        if 'statictest' in lower or 'hap_static' in lower or '_static' in lower:
            markers.add('static')
        if 'dynamictest' in lower or 'hap_dynamic' in lower or '_dynamic' in lower:
            markers.add('dynamic')
    if markers == {'static', 'dynamic'}:
        return 'both'
    if 'static' in markers:
        return 'static'
    if 'dynamic' in markers:
        return 'dynamic'
    return 'unknown'


def classify_project_variant(
    relative_root: str,
    test_file_names: list[str],
    files: list[TestFileIndex] | None = None,
) -> str:
    if files is not None:
        semantic = classify_xts_project_surface(file_index.surface for file_index in files)
        if semantic.variant != "unknown":
            return semantic.variant
    return _classify_project_variant_from_names(relative_root, test_file_names)



def parse_test_json(path_value: str, repo_root: Path | None = None) -> dict:
    repo_root = repo_root or REPO_ROOT
    return load_json_file(resolve_path(path_value, repo_root, repo_root))


def parse_test_file_names(test_json_path: str, repo_root: Path | None = None) -> list[str]:
    data = parse_test_json(test_json_path, repo_root=repo_root)
    result: list[str] = []
    for kit in data.get("kits", []):
        if not isinstance(kit, dict):
            continue
        names = kit.get("test-file-name", [])
        if isinstance(names, list):
            for item in names:
                if isinstance(item, str):
                    result.append(item)
    return result


def infer_xdevice_module_name(test_json_path: str, repo_root: Path | None = None) -> str | None:
    for name in parse_test_file_names(test_json_path, repo_root=repo_root):
        if name.endswith(".hap"):
            stem = Path(name).stem
            if stem:
                return stem
    return None


def guess_build_target(project_root: str) -> str:
    return Path(project_root).name


def xts_source_files(xts_root: Path) -> list[Path]:
    skip_dirs = {".git", ".ohpm", "node_modules", "oh_modules", "out"}
    paths: set[Path] = set()
    if not xts_root.exists():
        return []
    for dirpath, dirnames, filenames in os.walk(xts_root, topdown=True, onerror=lambda _exc: None):
        dirnames[:] = [name for name in dirnames if name not in skip_dirs]
        base = Path(dirpath)
        for filename in filenames:
            if filename == "Test.json" or filename.endswith((".ets", ".ts", ".js")):
                paths.add((base / filename).resolve())
    return sorted(paths)


def build_manifest_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        stat = path.stat()
        digest.update(repo_rel(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def discover_projects(xts_root: Path) -> list[TestProjectIndex]:
    projects: list[TestProjectIndex] = []
    skip_dirs = {".git", ".ohpm", "node_modules", "oh_modules", "out"}
    for test_json in sorted(xts_root.rglob("Test.json")):
        if any(part in skip_dirs for part in test_json.parts):
            continue
        root = test_json.parent
        files: list[TestFileIndex] = []
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _exc: None):
            dirnames[:] = [name for name in dirnames if name not in skip_dirs]
            base = Path(dirpath)
            for filename in filenames:
                if not filename.endswith((".ets", ".ts", ".js")):
                    continue
                source = (base / filename).resolve()
                files.append(parse_test_file(source))
        relative_root = repo_rel(root)
        test_json_rel = repo_rel(test_json)
        test_file_names = parse_test_file_names_from_test_json(test_json)
        surface_profile = classify_xts_project_surface(file_index.surface for file_index in files)
        projects.append(
            TestProjectIndex(
                relative_root=relative_root,
                test_json=test_json_rel,
                bundle_name=parse_bundle_name(test_json),
                files=files,
                path_key=str(root.relative_to(xts_root)).replace(os.sep, "/").lower(),
                variant=classify_project_variant(relative_root, test_file_names, files=files),
                surface=surface_profile.surface,
                supported_surfaces=set(surface_profile.supported_surfaces),
            )
        )
    return projects


def _build_xts_workspace_signature(xts_root: Path) -> str:
    return _capture_xts_workspace_snapshot(xts_root).signature


def _capture_xts_workspace_snapshot(xts_root: Path) -> XtsWorkspaceSnapshot:
    skip_dirs = {".git", ".ohpm", "node_modules", "oh_modules", "out"}
    h = hashlib.sha256()
    file_count = 0
    newest_mtime_ns = 0
    for dirpath, dirnames, filenames in os.walk(xts_root, topdown=True, onerror=lambda _exc: None):
        dirnames[:] = sorted(name for name in dirnames if name not in skip_dirs)
        try:
            newest_mtime_ns = max(newest_mtime_ns, int(Path(dirpath).stat().st_mtime_ns))
        except OSError:
            pass
        base = Path(dirpath)
        for filename in sorted(filenames):
            if filename != "Test.json" and not filename.endswith((".ets", ".ts", ".js")):
                continue
            path = base / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = str(path.relative_to(xts_root)).replace(os.sep, "/")
            h.update(f"{rel}:{stat.st_mtime_ns}:{stat.st_size}\n".encode())
            file_count += 1
            newest_mtime_ns = max(newest_mtime_ns, int(stat.st_mtime_ns))
    return XtsWorkspaceSnapshot(
        signature=f"{file_count}:{h.hexdigest()}",
        newest_mtime_ns=newest_mtime_ns,
    )


def _build_project_hash(project_root: Path, skip_dirs: set[str]) -> str:
    """Compute hash for a single project based on its relevant source files."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(project_root, topdown=True, onerror=lambda _exc: None):
        dirnames[:] = sorted(name for name in dirnames if name not in skip_dirs)
        base = Path(dirpath)
        for filename in sorted(filenames):
            if filename != "Test.json" and not filename.endswith((".ets", ".ts", ".js")):
                continue
            path = base / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = str(path.relative_to(project_root)).replace(os.sep, "/")
            h.update(f"{rel}:{stat.st_mtime_ns}:{stat.st_size}\n".encode())
    return h.hexdigest()


def _build_single_project(
    test_json: Path,
    root: Path,
    xts_root: Path,
) -> TestProjectIndex:
    """Build index for a single project directory."""
    skip_dirs = {".git", ".ohpm", "node_modules", "oh_modules", "out"}
    files: list[TestFileIndex] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _exc: None):
        dirnames[:] = [name for name in dirnames if name not in skip_dirs]
        base = Path(dirpath)
        for filename in filenames:
            if not filename.endswith((".ets", ".ts", ".js")):
                continue
            source = (base / filename).resolve()
            files.append(parse_test_file(source))
    relative_root = repo_rel(root)
    test_json_rel = repo_rel(test_json)
    test_file_names = parse_test_file_names_from_test_json(test_json)
    surface_profile = classify_xts_project_surface(file_index.surface for file_index in files)
    return TestProjectIndex(
        relative_root=relative_root,
        test_json=test_json_rel,
        bundle_name=parse_bundle_name(test_json),
        files=files,
        path_key=str(root.relative_to(xts_root)).replace(os.sep, "/").lower(),
        variant=classify_project_variant(relative_root, test_file_names, files=files),
        surface=surface_profile.surface,
        supported_surfaces=set(surface_profile.supported_surfaces),
    )


def _projects_from_cache_payload(cache_data: dict[str, object], *, lazy_files: bool) -> list[TestProjectIndex]:
    return [
        TestProjectIndex.from_dict(item["data"], lazy_files=lazy_files)
        for _key, item in sorted((cache_data.get("projects", {}) or {}).items())
        if isinstance(item, dict) and isinstance(item.get("data"), dict)
    ]


def load_or_build_projects(xts_root: Path, cache_file: Path | None) -> tuple[list[TestProjectIndex], bool]:
    CACHE_VERSION = 5

    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_meta_file = default_cache_meta_path(cache_file) if cache_file else None

    # Fast path: validate the workspace against a tiny sidecar metadata file.
    if cache_file and cache_file.exists() and cache_meta_file and cache_meta_file.exists():
        try:
            meta_payload = json.loads(read_text(cache_meta_file))
            if meta_payload.get("version") == CACHE_VERSION:
                workspace_snapshot = _capture_xts_workspace_snapshot(xts_root)
                if meta_payload.get("workspace_signature") == workspace_snapshot.signature:
                    cache_data = json.loads(read_text(cache_file))
                    if cache_data.get("version") == CACHE_VERSION:
                        projects = _projects_from_cache_payload(cache_data, lazy_files=True)
                        for project in projects:
                            if not project.search_summary_ready:
                                ensure_project_search_summary(project)
                        return projects, len(projects) > 0
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            pass

    # Compatibility fast path: older caches may not have a sidecar yet.
    # If the workspace-specific cache file is newer than every relevant source
    # file and directory in the workspace, the cache cannot be stale for this
    # workspace snapshot, so we can safely restore it and backfill the sidecar.
    if cache_file and cache_file.exists() and cache_meta_file and not cache_meta_file.exists():
        try:
            workspace_snapshot = _capture_xts_workspace_snapshot(xts_root)
            cache_stat = cache_file.stat()
            cache_data = json.loads(read_text(cache_file))
            if cache_data.get("version") == CACHE_VERSION and int(cache_stat.st_mtime_ns) >= workspace_snapshot.newest_mtime_ns:
                projects = _projects_from_cache_payload(cache_data, lazy_files=True)
                for project in projects:
                    if not project.search_summary_ready:
                        ensure_project_search_summary(project)
                cache_meta_file.write_text(
                    json.dumps(
                        {
                            "version": CACHE_VERSION,
                            "workspace_signature": workspace_snapshot.signature,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return projects, len(projects) > 0
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            pass

    # Discover all project directories
    skip_dirs = {".git", ".ohpm", "node_modules", "oh_modules", "out"}
    project_dirs: list[tuple[Path, Path]] = []  # (test_json, root)
    for test_json in sorted(xts_root.rglob("Test.json")):
        if any(part in skip_dirs for part in test_json.parts):
            continue
        project_dirs.append((test_json, test_json.parent))

    # Load old cache
    old_cache: dict[str, dict] = {}
    if cache_file and cache_file.exists():
        try:
            cache_data = json.loads(read_text(cache_file))
            if cache_data.get("version") == CACHE_VERSION:
                old_cache = cache_data.get("projects", {})
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Build incrementally
    new_cache: dict[str, dict] = {}
    projects: list[TestProjectIndex] = []
    cache_hits = 0
    cache_changed = False

    for test_json, root in project_dirs:
        proj_hash = _build_project_hash(root, skip_dirs)
        rel_key = str(root.relative_to(xts_root)).replace(os.sep, "/")

        if rel_key in old_cache and old_cache[rel_key].get("hash") == proj_hash:
            # Cache hit
            try:
                project = TestProjectIndex.from_dict(old_cache[rel_key]["data"])
                if not project.search_summary_ready:
                    ensure_project_search_summary(project)
                projects.append(project)
                new_cache[rel_key] = old_cache[rel_key]
                cache_hits += 1
                continue
            except (KeyError, TypeError):
                pass

        # Cache miss — rebuild
        project = _build_single_project(test_json, root, xts_root)
        ensure_project_search_summary(project)
        projects.append(project)
        new_cache[rel_key] = {"hash": proj_hash, "data": project.to_dict()}
        cache_changed = True

    # Save updated cache
    if len(old_cache) != len(new_cache):
        cache_changed = True
    if cache_file and cache_changed:
        cache_payload = {
            "version": CACHE_VERSION,
            "projects": new_cache,
        }
        cache_file.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")
    if cache_file and cache_meta_file and (cache_changed or not cache_meta_file.exists()):
        workspace_signature = _build_xts_workspace_signature(xts_root)
        cache_meta_file.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "workspace_signature": workspace_signature,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    cache_used = cache_hits == len(project_dirs) and len(project_dirs) > 0
    return projects, cache_used


def load_sdk_index(sdk_api_root: Path) -> SdkIndex:
    index = SdkIndex()
    sdk_component_root = sdk_api_root / "arkui/component"
    sdk_arkui_root = sdk_api_root / "arkui"

    for path in sorted(sdk_component_root.glob("*.static.d.ets")):
        base = path.name[: -len(".static.d.ets")]
        symbol = snake_to_pascal(base)
        if base not in {"common", "builder", "enums", "units", "resources"}:
            index.component_names.add(symbol)
            index.component_file_bases[compact_token(base)] = symbol

    for path in sorted(sdk_arkui_root.glob("*Modifier.d.ts")) + sorted(sdk_arkui_root.glob("*Modifier.static.d.ets")):
        base = path.name
        if base.endswith(".d.ts"):
            symbol = base[:-len(".d.ts")]
        else:
            symbol = base[:-len(".static.d.ets")]
        index.modifier_names.add(symbol)
        index.modifier_file_bases[compact_token(symbol.replace("Modifier", ""))] = symbol

    for path in sorted(sdk_api_root.glob("@ohos.*")):
        name = path.name
        for suffix in (".d.ts", ".d.ets", ".static.d.ets"):
            if name.endswith(suffix):
                index.top_level_modules.add(name[: -len(suffix)])
                break

    return index


def normalize_ohos_module(module: str, sdk_modules: set[str]) -> str | None:
    if module in sdk_modules:
        return module
    prefixes = [candidate for candidate in sdk_modules if module.startswith(candidate + ".")]
    if prefixes:
        return max(prefixes, key=len)
    return None


def tokenize_path_parts(path: str) -> list[str]:
    return [part for part in re.split(r"[\/._-]+", path) if part]


def path_component_tokens(path: str) -> set[str]:
    return {
        compact_token(part)
        for part in re.split(r"[\/]+", path)
        if part and compact_token(part)
    }


def path_signal_tokens(path: str) -> set[str]:
    tokens = set(path_component_tokens(path))
    tokens.update(
        compact_token(part)
        for part in tokenize_path_parts(path)
        if compact_token(part)
    )
    return {token for token in tokens if token}


def family_tokens_from_path(rel: str, sdk_index: SdkIndex) -> set[str]:
    rel_lower = rel.lower()
    parts = tokenize_path_parts(rel_lower)
    families = {
        compact_token(part) for part in parts
        if len(part) >= 3 and compact_token(part) not in GENERIC_PATH_TOKENS
    }
    families.update(
        token for token in path_component_tokens(rel_lower)
        if token and token not in GENERIC_PATH_TOKENS
    )

    pattern_match = re.search(r"components_ng/pattern/([^/]+)/", rel)
    if pattern_match:
        families.add(compact_token(pattern_match.group(1)))

    for part in parts:
        compact = compact_token(part)
        if compact in sdk_index.component_file_bases:
            families.add(compact)
        if compact in sdk_index.modifier_file_bases:
            families.add(compact)
    return {item for item in families if item}



def dynamic_module_symbols(
    module_name: str,
    sdk_index: SdkIndex,
    content_index: ContentModifierIndex,
    mapping_config: MappingConfig,
) -> set[str]:
    family = compact_token(module_name)
    symbols: set[str] = {module_name}
    if family in sdk_index.component_file_bases:
        symbols.add(sdk_index.component_file_bases[family])
    if family in sdk_index.modifier_file_bases:
        symbols.add(sdk_index.modifier_file_bases[family])
    symbols.add(f"{module_name}Modifier")
    symbols.update(mapping_config.pattern_alias.get(module_name.lower(), []))
    symbols.update(content_index.family_to_symbols.get(family, set()))
    return {item for item in symbols if item}


def composite_mapping_matches(mapping_key: str, changed_file: Path, rel_lower: str) -> bool:
    compact_key = compact_token(mapping_key)
    stem = compact_token(changed_file.stem)
    rel_compact = compact_token(rel_lower)
    if compact_key and (compact_key in stem or compact_key in rel_compact):
        return True
    key_tokens = {compact_token(part) for part in tokenize_path_parts(mapping_key) if compact_token(part)}
    if not key_tokens:
        return False
    stem_tokens = {compact_token(part) for part in tokenize_path_parts(changed_file.stem.lower()) if compact_token(part)}
    rel_tokens = {compact_token(part) for part in tokenize_path_parts(rel_lower) if compact_token(part)}
    return key_tokens.issubset(stem_tokens) or key_tokens.issubset(rel_tokens)


def apply_composite_mapping(
    changed_file: Path,
    rel_lower: str,
    signals: dict[str, set[str]],
    content_index: ContentModifierIndex,
    mapping_config: MappingConfig,
) -> None:
    for key, rule in mapping_config.composite_mappings.items():
        if not composite_mapping_matches(key, changed_file, rel_lower):
            continue
        signals["modules"].update(rule.get("modules", []))
        signals["symbols"].update(rule.get("symbols", []))
        for family in rule.get("families", []):
            family_key = compact_token(family)
            if family_key:
                signals["project_hints"].add(family_key)
                signals["family_tokens"].add(family_key)
                signals["symbols"].update(content_index.family_to_symbols.get(family_key, set()))
        signals["project_hints"].update(rule.get("project_hints", []))
        signals["method_hints"].update(rule.get("method_hints", []))
        signals["type_hints"].update(rule.get("type_hints", []))
        if rule.get("method_hint_required", False):
            signals["method_hint_required"] = True


def infer_signals(
    changed_file: Path,
    sdk_index: SdkIndex,
    content_index: ContentModifierIndex,
    mapping_config: MappingConfig,
    changed_ranges: Iterable[tuple[int, int]] | None = None,
    api_lineage_map: ApiLineageMap | None = None,
    repo_root: Path | None = None,
) -> dict[str, set[str]]:
    rel = repo_rel(changed_file)
    if os.path.isabs(rel):
        path_parts = [part for part in changed_file.parts if part]
        if "generated" in path_parts:
            rel = "/".join(path_parts[path_parts.index("generated"):])
        else:
            rel = "/".join(path_parts[-4:])
    rel_lower = rel.lower()
    parts = tokenize_path_parts(rel_lower)
    compact_parts = {compact_token(part) for part in parts if part}
    compact_parts.update(path_component_tokens(rel_lower))
    families = family_tokens_from_path(rel, sdk_index)

    # Detect stateManagement infrastructure files BEFORE path truncation.
    # Use full changed_file path to catch these directories even when rel
    # is later truncated to last 4 parts.
    _full_path_lower = str(changed_file).lower()
    is_state_management = (
        "statemanagement" in _full_path_lower
        or "state_mgmt" in _full_path_lower
    )

    signals = {
        "modules": set(),
        "weak_modules": set(),
        "symbols": set(),
        "weak_symbols": set(),
        "project_hints": set(),
        "method_hints": set(),
        "type_hints": set(),
        "member_hints": set(),
        "raw_tokens": {part for part in parts if len(part) >= 4},
        "family_tokens": set(families),
        "method_hint_required": False,
    }

    for key, rule in mapping_config.special_path_rules.items():
        if key in compact_parts:
            signals["modules"].update(rule.get("modules", []))
            signals["symbols"].update(rule.get("symbols", []))
            signals["project_hints"].add(key)
            signals["method_hints"].update(rule.get("method_hints", []))
            signals["type_hints"].update(rule.get("type_hints", []))
            signals["member_hints"].update(rule.get("member_hints", []))

    pattern_match = re.search(r"components_ng/pattern/([^/]+)/", rel)
    if pattern_match:
        pattern = pattern_match.group(1)
        compact = compact_token(pattern)
        signals["project_hints"].add(compact)
        if compact in sdk_index.component_file_bases:
            signals["symbols"].add(sdk_index.component_file_bases[compact])
        if compact in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[compact])
        signals["symbols"].update(mapping_config.pattern_alias.get(pattern, []))

    # ark_component/src/Ark{Component}.ts — declarative frontend component wrappers
    # Extract component name from filename: ArkCheckbox.ts -> checkbox
    ark_component_match = re.search(r"ark_component/src/Ark([^.]+)\.ts$", rel)
    if ark_component_match:
        pascal_name = ark_component_match.group(1)
        # Convert PascalCase to lowercase: ArkDataPanel -> datapanel
        component_name = pascal_to_snake(pascal_name)
        # Exclude common utility files
        if component_name not in ("common", "classdefine", "classmock", "component", "commonshape"):
            compact = compact_token(component_name)
            signals["project_hints"].add(compact)
            signals["family_tokens"].add(compact)
            pascal = snake_to_pascal(component_name)
            signals["type_hints"].add(pascal)
            signals["symbols"].add(pascal)
            signals["symbols"].add(f"{pascal}Modifier")
            if compact in sdk_index.component_file_bases:
                signals["symbols"].add(sdk_index.component_file_bases[compact])
            if compact in sdk_index.modifier_file_bases:
                signals["symbols"].add(sdk_index.modifier_file_bases[compact])

    # ark_direct_component/src/ark{Component}.ts — direct component wrappers
    # Extract component name from filename: arkcounter.ts -> counter
    ark_direct_match = re.search(r"ark_direct_component/src/ark([^.]+)\.ts$", rel_lower)
    if ark_direct_match:
        component_name = ark_direct_match.group(1)
        # Component name is already lowercase in this pattern
        if component_name not in ("common",):
            compact = compact_token(component_name)
            signals["project_hints"].add(compact)
            signals["family_tokens"].add(compact)
            pascal = snake_to_pascal(component_name)
            signals["type_hints"].add(pascal)
            signals["symbols"].add(pascal)
            signals["symbols"].add(f"{pascal}Modifier")
            if compact in sdk_index.component_file_bases:
                signals["symbols"].add(sdk_index.component_file_bases[compact])
            if compact in sdk_index.modifier_file_bases:
                signals["symbols"].add(sdk_index.modifier_file_bases[compact])

    # Architecture-aware component resolution: deterministic mapping from
    # ace_engine file paths to component names, bypassing fuzzy token matching.
    # For files inside components_ng/pattern/, this supplements existing signals.
    # For files outside (implementation/, generated/), this provides the primary mapping.
    resolved_components = resolve_ace_engine_components(rel)
    for comp, source in resolved_components:
        compact = compact_token(comp)
        if compact:
            signals["project_hints"].add(compact)
            signals["family_tokens"].add(compact)
            pascal = snake_to_pascal(comp)
            # Use PATTERN_ALIAS-derived names when available for correct casing
            # (e.g., "checkboxgroup" -> "CheckboxGroup" not "Checkboxgroup")
            alias_symbols = (
                mapping_config.pattern_alias.get(comp, [])
                or mapping_config.pattern_alias.get(compact, [])
            )
            if alias_symbols:
                # First alias entry is typically the component class name
                canonical_name = alias_symbols[0]
                signals["type_hints"].add(canonical_name)
                signals["symbols"].update(alias_symbols)
            else:
                signals["type_hints"].add(pascal)
                signals["symbols"].add(pascal)
                signals["symbols"].add(f"{pascal}Modifier")
            if compact in sdk_index.component_file_bases:
                signals["symbols"].add(sdk_index.component_file_bases[compact])
            if compact in sdk_index.modifier_file_bases:
                signals["symbols"].add(sdk_index.modifier_file_bases[compact])

    # Universal symbol tracing for C++ files not resolved by path patterns.
    # Extracts CamelCase identifiers from the file and maps them to components
    # via the pre-built symbol-to-component index.
    if (not resolved_components
        and changed_file.suffix.lower() in (".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh")
        and repo_root):
        sym_components = trace_symbols_to_components(
            changed_file, list(changed_ranges or []), repo_root,
        )
        if sym_components:
            # Sort by hit count (most specific first), take top components
            for comp, hits in sorted(sym_components.items(), key=lambda x: -x[1]):
                compact = compact_token(comp)
                if not compact:
                    continue
                signals["project_hints"].add(compact)
                signals["family_tokens"].add(compact)
                pascal = snake_to_pascal(comp)
                alias_symbols = (
                    mapping_config.pattern_alias.get(comp, [])
                    or mapping_config.pattern_alias.get(compact, [])
                )
                if alias_symbols:
                    signals["type_hints"].add(alias_symbols[0])
                    signals["symbols"].update(alias_symbols)
                else:
                    signals["type_hints"].add(pascal)
                    signals["symbols"].add(pascal)
                if compact in sdk_index.component_file_bases:
                    signals["symbols"].add(sdk_index.component_file_bases[compact])
                if compact in sdk_index.modifier_file_bases:
                    signals["symbols"].add(sdk_index.modifier_file_bases[compact])

    # Generated .ets method-level tracing: parse with tree-sitter TypeScript
    # to find which SDK API methods overlap with changed_ranges.
    if resolved_components and changed_file.suffix.lower() == ".ets":
        ets_methods = trace_generated_ets_to_methods(
            changed_file, list(changed_ranges or []),
        )
        if ets_methods:
            signals["method_hints"].update(ets_methods)
            # Add member_hints for exact matching
            for comp, _source in resolved_components:
                alias_syms = (
                    mapping_config.pattern_alias.get(comp, [])
                    or mapping_config.pattern_alias.get(compact_token(comp), [])
                )
                attr_name = alias_syms[0] if alias_syms else snake_to_pascal(comp)
                for method in ets_methods:
                    signals["member_hints"].add(f"{attr_name}Attribute.{method}")
            if ets_methods:
                signals["method_hint_required"] = True

    if "ark_modifier" in rel_lower or "modifier" in parts:
        basename = compact_token(changed_file.stem)
        if basename in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[basename])
        if "common" in basename or "common" in compact_parts:
            signals["symbols"].update({"CommonModifier", "ModifierUtils"})
            signals["project_hints"].update(COMMON_PROJECT_HINTS)

    if "common" in compact_parts:
        signals["project_hints"].update(COMMON_PROJECT_HINTS)

    if "/interfaces/ets/ani/" in rel:
        name = changed_file.name
        if name.startswith("@ohos.") and name.endswith(".ets"):
            signals["modules"].add(name[:-4])

    if "uicontext" in compact_parts or "ui_context" in rel_lower:
        signals["modules"].add("@ohos.arkui.UIContext")
        signals["symbols"].update({"UIContext", "OverlayManager", "Router"})

    for family in families:
        canonical_family = FAMILY_TOKEN_ALIAS_INDEX.get(family, family)
        if family in sdk_index.component_file_bases:
            signals["symbols"].add(sdk_index.component_file_bases[family])
            signals["project_hints"].add(family)
        if family in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[family])
            signals["project_hints"].add(family)
        signals["symbols"].update(mapping_config.pattern_alias.get(canonical_family, []))
        if canonical_family != family:
            signals["project_hints"].add(canonical_family)

    if changed_file.suffix.lower() == ".ets":
        text = read_text(changed_file)
        normalized_changed_ranges = merge_changed_ranges(changed_ranges)
        source_families = {FAMILY_TOKEN_ALIAS_INDEX.get(family, family) for family in signals["family_tokens"]}
        source_focus = ets_source_focus_tokens(source_families)
        body_text = strip_ets_import_statements(text)
        body_identifier_calls = set(IDENTIFIER_CALL_RE.findall(body_text))
        body_type_member_owners = {owner for owner, _member in TYPE_MEMBER_CALL_RE.findall(body_text)}
        body_words = {word.lower() for word in WORD_RE.findall(body_text)}

        for match in OHOS_MODULE_RE.findall(text):
            module_names = {match}
            normalized_module = normalize_ohos_module(match, sdk_index.top_level_modules)
            if normalized_module:
                module_names.add(normalized_module)
            for module_name in module_names:
                strength = classify_ohos_module_signal_strength(module_name, source_focus, source_families)
                if strength == "strong":
                    signals["modules"].add(module_name)
                elif strength == "weak":
                    signals["weak_modules"].add(module_name)

        def _add_ets_type_signal(name: str, strength: str) -> None:
            cleaned = str(name).strip()
            if not cleaned:
                return
            if strength == "strong":
                signals["symbols"].add(cleaned)
                signals["type_hints"].add(cleaned)
            elif strength == "weak":
                signals["weak_symbols"].add(cleaned)
            else:
                return
            family_token = related_signal_family_token(cleaned)
            mapped_family = coverage_family_key(family_token) or coverage_family_key(related_signal_base_token(cleaned))
            if strength == "strong" and mapped_family:
                signals["family_tokens"].add(mapped_family)
                signals["project_hints"].add(mapped_family)
                signals["symbols"].update(mapping_config.pattern_alias.get(mapped_family, []))

        exported_type_names = extract_exported_type_names(
            text,
            changed_ranges=normalized_changed_ranges or None,
        )
        for name in sorted(exported_type_names):
            if not source_families or should_keep_ets_signal_name(name, source_families, allow_source_family_fallback=True):
                _add_ets_type_signal(name, "strong")
        exported_member_hints = extract_exported_interface_member_hints(
            text,
            source_families,
            changed_ranges=normalized_changed_ranges or None,
        )
        signals["member_hints"].update(exported_member_hints)
        for member_hint in sorted(exported_member_hints):
            owner, _separator, _member = str(member_hint).partition(".")
            if owner:
                _add_ets_type_signal(owner, "strong")

        imported_type_names: set[str] = set()
        for match in IMPORT_BINDING_RE.finditer(text):
            for part in match.group(1).split(","):
                token = part.strip().split(" as ", 1)[0].strip()
                if token and token[:1].isupper():
                    imported_type_names.add(token)
        for match in DEFAULT_IMPORT_RE.finditer(text):
            token = match.group(1).strip()
            if token and token[:1].isupper():
                imported_type_names.add(token)
        for name in sorted(imported_type_names):
            source_owned = imported_ets_symbol_matches_source_focus(name, source_focus, source_families)
            used_in_body = imported_ets_symbol_used_in_body(
                name,
                body_identifier_calls,
                body_type_member_owners,
                body_words,
            )
            if source_owned:
                _add_ets_type_signal(name, "strong")
            elif used_in_body and should_keep_ets_signal_name(name, source_families, allow_source_family_fallback=False):
                _add_ets_type_signal(name, "weak")

        public_methods: list[str] = []
        public_method_line_offsets = build_line_start_offsets(text) if normalized_changed_ranges else []
        for public_method_match in PUBLIC_METHOD_RE.finditer(text):
            method_name = public_method_match.group(1)
            if compact_token(method_name) in GENERIC_PUBLIC_METHOD_HINTS:
                continue
            if normalized_changed_ranges and not span_overlaps_changed_ranges(
                public_method_match.start(),
                public_method_match.end(),
                line_offsets=public_method_line_offsets,
                changed_ranges=normalized_changed_ranges,
            ):
                continue
            public_methods.append(method_name)
        if 1 <= len(public_methods) <= 6 and (
            1 <= len(source_focus) <= 2 or len(exported_type_names) == 1
        ):
            signals["method_hints"].update(sorted(set(public_methods)))

        # Tree-sitter tracing for generated .ets files (e.g., arkui-ohos/generated/)
        # Extracts method names from changed ranges for precise matching.
        if "generated" in rel_lower or "arkui-ohos" in rel_lower:
            ts_methods = trace_generated_ets_to_methods(
                changed_file, normalized_changed_ranges
            )
            if ts_methods:
                signals["method_hints"].update(ts_methods)

    ts_suffixes = {".ts"}
    is_ts = changed_file.suffix.lower() in ts_suffixes
    is_dts = changed_file.name.endswith(".d.ts")

    # stateManagement / state_mgmt — framework infrastructure affecting ALL components.
    # These directories contain decorator implementations, state observation,
    # persistent storage, etc. Changes here have broad impact.
    if is_state_management:
        signals["project_hints"].update(COMMON_PROJECT_HINTS)
        signals["method_hint_required"] = False
        # Extract exported types from the file for additional signal precision.
        # This avoids hardcoding specific component names — the types found in
        # the file itself drive the matching.
        _sm_text = read_text(changed_file)
        if _sm_text:
            for _pat in (EXPORT_CLASS_RE, EXPORT_INTERFACE_RE, TS_EXPORT_TYPE_RE):
                for _m in _pat.finditer(_sm_text):
                    _name = _m.group(1)
                    if _name and _name[:1].isupper():
                        signals["type_hints"].add(_name)
                        signals["symbols"].add(_name)

    if is_ts or is_dts:
        text = read_text(changed_file)
        normalized_ts_ranges = merge_changed_ranges(changed_ranges)
        source_families = {FAMILY_TOKEN_ALIAS_INDEX.get(family, family) for family in signals["family_tokens"]}
        source_focus = ets_source_focus_tokens(source_families)

        # Extract @ohos.* module references
        for match in OHOS_MODULE_RE.findall(text):
            module_names = {match}
            normalized_module = normalize_ohos_module(match, sdk_index.top_level_modules)
            if normalized_module:
                module_names.add(normalized_module)
            for module_name in module_names:
                strength = classify_ohos_module_signal_strength(module_name, source_focus, source_families)
                if strength == "strong":
                    signals["modules"].add(module_name)
                elif strength == "weak":
                    signals["weak_modules"].add(module_name)

        # Extract exported interface/type names
        for pattern in (EXPORT_CLASS_RE, EXPORT_INTERFACE_RE, TS_EXPORT_TYPE_RE):
            for match in pattern.finditer(text):
                name = match.group(1)
                if name and name[:1].isupper():
                    signals["type_hints"].add(name)
                    signals["symbols"].add(name)
                    family_token = related_signal_family_token(name)
                    mapped_family = coverage_family_key(family_token) or coverage_family_key(related_signal_base_token(name))
                    if mapped_family:
                        signals["family_tokens"].add(mapped_family)
                        signals["project_hints"].add(mapped_family)

        # Extract interface member declarations → member_hints
        exported_member_hints = extract_exported_interface_member_hints(
            text,
            source_families,
            changed_ranges=normalized_ts_ranges or None,
        )
        signals["member_hints"].update(exported_member_hints)
        for member_hint in sorted(exported_member_hints):
            owner, _separator, _member = str(member_hint).partition(".")
            if owner:
                signals["type_hints"].add(owner)
                signals["symbols"].add(owner)

        # Extract declare function signatures → method_hints
        scan_text = extract_text_in_changed_ranges(text, normalized_ts_ranges) if normalized_ts_ranges else text
        for match in DECLARE_FUNCTION_RE.finditer(scan_text):
            func_name = match.group(1)
            if func_name:
                signals["method_hints"].add(func_name)

        # For .d.ts files, also extract declare interface/type as strong signals
        if is_dts:
            for match in DECLARE_INTERFACE_RE.finditer(scan_text):
                name = match.group(1)
                if name:
                    signals["type_hints"].add(name)
                    signals["symbols"].add(name)
            for match in DECLARE_TYPE_RE.finditer(scan_text):
                name = match.group(1)
                if name:
                    signals["type_hints"].add(name)
                    signals["symbols"].add(name)
            for match in DECLARE_MODULE_RE.finditer(scan_text):
                module_name = match.group(1)
                if module_name:
                    signals["modules"].add(module_name)

    native_suffixes = {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh"}
    if changed_file.suffix.lower() in native_suffixes:
        text = read_text(changed_file)
        text_lower = text.lower()
        normalized_native_ranges = merge_changed_ranges(changed_ranges)
        # When ranges are provided, scan only the changed lines for identifier-level signals.
        # File-level structural signals (includes, dynamic modules) remain full-file.
        scan_text = extract_text_in_changed_ranges(text, normalized_native_ranges) if normalized_native_ranges else text
        scan_text_lower = scan_text.lower()

        dynamic_modules = {match for match in DYNAMIC_MODULE_RE.findall(text)}

        for match in OHOS_MODULE_RE.findall(scan_text):
            signals["modules"].add(match)
            module = normalize_ohos_module(match, sdk_index.top_level_modules)
            if module:
                signals["modules"].add(module)

        for ident in CPP_IDENTIFIER_RE.findall(scan_text):
            compact_ident = compact_token(ident.replace("Modifier", ""))
            if compact_ident in families:
                signals["symbols"].add(ident)

        accessor_type_hints = extract_native_accessor_type_hints(scan_text)
        if accessor_type_hints:
            signals["type_hints"].update(accessor_type_hints)
            signals["symbols"].update(accessor_type_hints)
            signals["project_hints"].update(
                compact_token(hint) for hint in accessor_type_hints if compact_token(hint)
            )

        for include_family in INCLUDE_PATTERN_COMPONENT_RE.findall(scan_text):
            family = compact_token(include_family)
            if family:
                signals["family_tokens"].add(family)

        for family in families:
            if family and family in scan_text_lower:
                signals["project_hints"].add(family)

        for raw, aliases in mapping_config.pattern_alias.items():
            compact = compact_token(raw)
            if compact in families:
                signals["symbols"].update(aliases)

        for key, rule in mapping_config.special_path_rules.items():
            if key in scan_text_lower:
                signals["modules"].update(rule.get("modules", []))
                signals["symbols"].update(rule.get("symbols", []))
                signals["project_hints"].add(key)
                signals["method_hints"].update(rule.get("method_hints", []))
                signals["type_hints"].update(rule.get("type_hints", []))
                signals["member_hints"].update(rule.get("member_hints", []))

        for module_name in dynamic_modules:
            family = compact_token(module_name)
            if family:
                signals["family_tokens"].add(family)
                signals["project_hints"].add(family)
            signals["symbols"].update(dynamic_module_symbols(module_name, sdk_index, content_index, mapping_config))

        uses_content_modifier = (
            "contentmodifier" in compact_token(changed_file.stem)
            or "content_modifier" in rel_lower
            or "contentmodifier" in text_lower
            or bool(CONTENT_MODIFIER_CUSTOM_RE.search(text))
        )
        if uses_content_modifier:
            signals["symbols"].add("ContentModifier")
            signals["project_hints"].add("contentmodifier")
            signals["method_hints"].add("contentModifier")
            signals["type_hints"].add("ContentModifier")
            candidate_families = set(dynamic_modules)
            if len(dynamic_modules) >= 3:
                candidate_families.update(content_index.families)
            for module_name in candidate_families:
                family = compact_token(module_name)
                if family:
                    signals["project_hints"].add(family)
                    signals["family_tokens"].add(family)
                    signals["symbols"].update(content_index.family_to_symbols.get(family, set()))

        # When changed_ranges are provided, extract function names from changed lines
        # and add them as method hints to narrow matching for wide-scope files like
        # common_method_modifier.cpp (e.g. SetOnClick → onClick, SetGesture → gesture).
        if normalized_native_ranges:
            cpp_func_names = CPP_FUNCTION_DEF_RE.findall(scan_text)
            for func_name in cpp_func_names:
                stripped = func_name.strip()
                if not stripped or len(stripped) < 3:
                    continue
                # Common patterns: SetOnClick → onClick, SetGesture → gesture
                # Also keep the raw name as a symbol hint
                signals["symbols"].add(stripped)
                compact_func = compact_token(stripped)
                if compact_func in families:
                    signals["project_hints"].add(compact_func)
                # Map SetXxx → xxx as a method hint
                if stripped.startswith("Set"):
                    method_hint = stripped[3:]
                    if method_hint and method_hint[0].isupper():
                        method_hint = method_hint[0].lower() + method_hint[1:]
                    if method_hint:
                        signals["method_hints"].add(method_hint)
            cpp_method_names = CPP_METHOD_DEF_RE.findall(scan_text)
            for class_name, method_name in cpp_method_names:
                signals["symbols"].add(class_name.strip())
                compact_class = compact_token(class_name.strip())
                if compact_class in families:
                    signals["project_hints"].add(compact_class)
                signals["method_hints"].add(method_name.strip())

    # --- Tree-sitter shared file tracing ---
    # For shared infrastructure headers (converter.h, callback_helper.h, etc.),
    # trace which components' static modifier functions call symbols defined in
    # the changed ranges. This gives method-level precision for shared files.
    if changed_file.suffix.lower() in (".h", ".hpp", ".hh") and repo_root:
        shared_trace = trace_shared_file_to_components(
            changed_file, changed_ranges, repo_root
        )
        if shared_trace:
            for component, methods in shared_trace.items():
                compact = compact_token(component)
                signals["project_hints"].add(compact)
                signals["family_tokens"].add(compact)
                pascal = snake_to_pascal(component)
                signals["type_hints"].add(pascal)
                signals["symbols"].add(pascal)
                signals["symbols"].add(f"{pascal}Modifier")
                signals["method_hints"].update(methods)
                # member_hints: ComponentAttribute.methodName
                for method in methods:
                    signals["member_hints"].add(f"{pascal}Attribute.{method}")
            # For shared files traced to specific components, require at least
            # one method match to avoid false positives from broad signals.
            signals["method_hint_required"] = True

    apply_composite_mapping(changed_file, rel_lower, signals, content_index, mapping_config)

    signals["modules"] = {item for item in signals["modules"] if item}
    signals["weak_modules"] = {item for item in signals.get("weak_modules", set()) if item and item not in signals["modules"]}
    signals["symbols"] = {item for item in signals["symbols"] if item}
    signals["weak_symbols"] = {
        item for item in signals.get("weak_symbols", set())
        if item and item not in signals["symbols"]
    }
    signals["project_hints"] = {
        compact_token(item)
        for item in signals["project_hints"]
        if item and compact_token(item) not in GENERIC_PATH_TOKENS and compact_token(item) not in CONTENT_MODIFIER_NOISE
    }
    signals["family_tokens"] = {
        item for item in signals["family_tokens"]
        if item not in GENERIC_PATH_TOKENS and item not in CONTENT_MODIFIER_NOISE
    }
    signals["method_hints"] = {item for item in signals["method_hints"] if item}
    signals["type_hints"] = {item for item in signals["type_hints"] if item}
    signals["member_hints"] = {item for item in signals.get("member_hints", set()) if normalize_member_hint(str(item))}
    return signals


def apply_api_lineage_signals(
    changed_file: Path,
    signals: dict[str, set[str]],
    api_lineage_map: ApiLineageMap | None,
    repo_root: Path,
    changed_symbols: Iterable[str] | None = None,
    changed_ranges: Iterable[tuple[int, int]] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    if api_lineage_map is None:
        return [], [], []

    file_level_affected_api_entities = api_lineage_map.apis_for_source(changed_file, repo_root=repo_root)
    derived_source_symbols = [str(item).strip() for item in (changed_symbols or []) if str(item).strip()]
    if not derived_source_symbols and changed_ranges:
        derived_source_symbols = api_lineage_map.symbols_for_source_ranges(
            changed_file,
            changed_ranges,
            repo_root=repo_root,
        )
    narrowed_api_entities = api_lineage_map.apis_for_source_symbols(
        changed_file,
        derived_source_symbols,
        repo_root=repo_root,
    ) if derived_source_symbols else []
    affected_api_entities = narrowed_api_entities or file_level_affected_api_entities
    lineage_symbols: set[str] = set()
    lineage_project_hints: set[str] = set()
    lineage_family_tokens: set[str] = set()
    lineage_method_hints: set[str] = set()
    lineage_type_hints: set[str] = set()
    lineage_member_hints: set[str] = set()
    exact_api_prefilter_entities: set[str] = set()
    for api_entity in affected_api_entities:
        lineage_symbols.add(api_entity)
        owner, _separator, method_name = str(api_entity).partition(".")
        if owner:
            lineage_type_hints.add(owner)
        if owner and method_name:
            exact_api_prefilter_entities.add(str(api_entity))
            lineage_member_hints.add(f"{owner}.{method_name}")
        for suffix in ("Modifier", "Attribute", "Configuration", "Controller"):
            owner = owner.replace(suffix, "")
        base = compact_token(owner)
        if base:
            lineage_project_hints.add(base)
            lineage_family_tokens.add(base)
        if method_name:
            lineage_method_hints.add(method_name)
    if narrowed_api_entities:
        signals["symbols"] = lineage_symbols
        signals["project_hints"] = lineage_project_hints
        signals["family_tokens"] = lineage_family_tokens
        signals["method_hints"] = lineage_method_hints
        signals["type_hints"] = lineage_type_hints
        signals["member_hints"] = lineage_member_hints
    else:
        signals["symbols"].update(lineage_symbols)
        signals["project_hints"].update(lineage_project_hints)
        signals["family_tokens"].update(lineage_family_tokens)
        signals["method_hints"].update(lineage_method_hints)
        signals["type_hints"].update(lineage_type_hints)
        signals["member_hints"].update(lineage_member_hints)
    if exact_api_prefilter_entities:
        signals["exact_api_prefilter_entities"] = exact_api_prefilter_entities
    return affected_api_entities, file_level_affected_api_entities, derived_source_symbols


def collect_source_only_consumers(
    affected_api_entities: list[str],
    api_lineage_map: ApiLineageMap | None,
    *,
    top_projects: int,
    top_files: int,
) -> list[dict[str, object]]:
    if api_lineage_map is None or not affected_api_entities:
        return []

    affected_set = set(affected_api_entities)
    project_entries: dict[str, dict[str, object]] = {}
    for api_entity in affected_api_entities:
        for consumer_project in api_lineage_map.consumer_projects_for_api(api_entity, kind="source_only"):
            entry = project_entries.setdefault(
                consumer_project,
                {
                    "project": consumer_project,
                    "consumer_kind": "source_only",
                    "matched_api_entities": set(),
                    "files": [],
                },
            )
            entry["matched_api_entities"].add(api_entity)

    for consumer_project, entry in project_entries.items():
        matched_files: list[dict[str, object]] = []
        for consumer_file in api_lineage_map.consumer_files_for_project(consumer_project):
            matched_file_apis = sorted(api_lineage_map.consumer_file_to_apis.get(consumer_file, set()) & affected_set)
            if not matched_file_apis:
                continue
            matched_files.append(
                {
                    "file": consumer_file,
                    "matched_api_entities": matched_file_apis,
                }
            )
        matched_files.sort(key=lambda item: (-len(item.get("matched_api_entities", [])), str(item.get("file", ""))))
        entry["matched_api_entities"] = sorted(entry["matched_api_entities"])
        entry["files"] = matched_files[:top_files]
        entry["matched_file_count"] = len(matched_files)

    ordered = sorted(
        project_entries.values(),
        key=lambda item: (
            -len(item.get("matched_api_entities", [])),
            -int(item.get("matched_file_count", 0)),
            str(item.get("project", "")),
        ),
    )
    return ordered if top_projects <= 0 else ordered[:top_projects]


def symbol_score(
    signal_symbol: str,
    file_index: TestFileIndex,
    family_tokens: set[str],
    lowered_member_calls: set[str],
    weak: bool = False,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    lower = signal_symbol.lower()
    base = compact_token(signal_symbol.replace("Modifier", ""))
    path_key = compact_token(file_index.relative_path)
    path_supports = base and base in path_key
    family_supports = base and base in family_tokens
    is_ubiquitous = base in UBIQUITOUS_BASES
    strong = (not is_ubiquitous) or path_supports or family_supports
    reason_prefix = "weak " if weak else ""

    if signal_symbol in file_index.imported_symbols:
        if weak:
            score += 2 if strong else 1
        else:
            score += 7 if strong else 1
        reasons.append(f"{reason_prefix}imports symbol {signal_symbol}")
    if signal_symbol in file_index.identifier_calls:
        if weak:
            if signal_symbol in file_index.imported_symbols:
                call_pts = 2 if strong else 1
            else:
                call_pts = 1
        else:
            # If the symbol is also explicitly imported, the call is
            # confirmation evidence that adds less marginal value than the
            # import itself. If NOT imported (ArkUI components are globally
            # available in ETS without explicit import), the call is still
            # valid usage evidence but weaker than an explicit SDK import.
            #   import + call  → 7 + 3 = 10  (explicitly imported and used)
            #   call only      → 4            (globally used, no import)
            if signal_symbol in file_index.imported_symbols:
                call_pts = 3 if strong else 1
            else:
                call_pts = 4 if strong else 1
        score += call_pts
        reasons.append(f"{reason_prefix}calls {signal_symbol}()")
    if lower in lowered_member_calls:
        score += 1 if weak else (4 if strong else 1)
        reasons.append(f"{reason_prefix}member call .{lower}()")
    if lower in file_index.words:
        if weak:
            word_score = 0
        else:
            word_score = 2 if strong and not is_ubiquitous else (1 if strong else 0)
        score += word_score
        if word_score:
            reasons.append(f"{reason_prefix}mentions {lower}")
    return score, reasons


def score_file(file_index: TestFileIndex, signals: dict[str, set[str]]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    lowered_member_calls = {compact_token(member) for member in file_index.member_calls}
    identifier_call_tokens = {compact_token(identifier) for identifier in file_index.identifier_calls}
    imported_symbol_tokens = {compact_token(symbol) for symbol in file_index.imported_symbols}
    exact_member_keys = _typed_member_tokens(file_index.typed_field_accesses) | _typed_member_tokens(file_index.type_member_calls)
    type_member_calls_by_token: dict[str, set[str]] = {}
    for entry in file_index.type_member_calls:
        owner, separator, member = entry.partition(".")
        owner_token = compact_token(owner)
        if owner_token and separator and member:
            type_member_calls_by_token.setdefault(owner_token, set()).add(member)
    typed_field_accesses_by_token: dict[str, set[str]] = {}
    for entry in file_index.typed_field_accesses:
        owner, separator, field_name = entry.partition(".")
        owner_token = compact_token(owner)
        field_token = compact_token(field_name)
        if owner_token and separator and field_name and field_token not in GENERIC_TYPED_FIELD_NAMES:
            typed_field_accesses_by_token.setdefault(owner_token, set()).add(field_name)

    for module in sorted(signals["modules"]):
        if module in file_index.imports:
            score += 10
            reasons.append(f"imports {module}")
    for module in sorted(signals.get("weak_modules", set())):
        if module in file_index.imports:
            score += 2
            reasons.append(f"weak imports {module}")

    typed_modifier_matches: list[str] = []
    for symbol in sorted(signals["symbols"]):
        delta, symbol_reasons = symbol_score(
            symbol,
            file_index,
            signals["family_tokens"],
            lowered_member_calls,
        )
        score += delta
        reasons.extend(symbol_reasons)
        if symbol.endswith("Modifier") and compact_token(symbol[:-8]) in file_index.typed_modifier_bases:
            typed_modifier_matches.append(symbol)
    for symbol in sorted(signals.get("weak_symbols", set())):
        delta, symbol_reasons = symbol_score(
            symbol,
            file_index,
            signals["family_tokens"],
            lowered_member_calls,
            weak=True,
        )
        score += delta
        reasons.extend(symbol_reasons)

    if typed_modifier_matches:
        score += 5
        reasons.append(f"typed modifier evidence for {', '.join(sorted(typed_modifier_matches))}")

    method_member_matches: list[str] = []
    for method in sorted(signals.get("method_hints", set())):
        method_token = compact_token(method)
        if method_token and method_token in lowered_member_calls:
            method_member_matches.append(method)

    type_hints_by_token: dict[str, str] = {}
    for hint in sorted(signals.get("method_hints", set())):
        hint_token = compact_token(hint)
        if hint_token and hint_token not in type_hints_by_token:
            type_hints_by_token[hint_token] = hint
    for hint in sorted(signals.get("type_hints", set())):
        hint_token = compact_token(hint)
        if hint_token:
            type_hints_by_token[hint_token] = hint

    constructor_matches: list[str] = []
    import_matches: list[str] = []
    type_member_matches: list[str] = []
    typed_field_matches: list[str] = []
    for hint_token, hint in sorted(type_hints_by_token.items()):
        if hint_token in identifier_call_tokens:
            constructor_matches.append(hint)
        if hint_token in imported_symbol_tokens:
            import_matches.append(hint)
        members = sorted(type_member_calls_by_token.get(hint_token, set()))
        if members:
            type_member_matches.extend(f"{hint}.{member}()" for member in members)
        fields = sorted(typed_field_accesses_by_token.get(hint_token, set()))
        if fields:
            typed_field_matches.extend(f"{hint}.{field}" for field in fields)

    if method_member_matches:
        score += 5
        if len(method_member_matches) == 1:
            reasons.append(f"calls .{method_member_matches[0]}()")
        else:
            reasons.append(f"calls methods {', '.join(sorted(method_member_matches))}")
    if constructor_matches:
        score += 5
        reasons.append(f"constructs hinted type {', '.join(sorted(constructor_matches))}")
    if import_matches:
        score += 3
        reasons.append(f"imports hinted type {', '.join(sorted(import_matches))}")
    if type_member_matches:
        score += 5
        reasons.append(f"calls hinted type member {', '.join(sorted(type_member_matches))}")
    if typed_field_matches:
        score += 9
        reasons.append(f"reads/writes fields of hinted type {', '.join(sorted(typed_field_matches))}")

    exact_member_matches = []
    for member_hint in sorted(signals.get("member_hints", set())):
        normalized = normalize_member_hint(member_hint)
        if normalized and normalized in exact_member_keys:
            exact_member_matches.append(str(member_hint))
    if exact_member_matches:
        score += 11
        reasons.append(f"matches exact changed member {', '.join(sorted(exact_member_matches))}")

    for token in sorted(signals["project_hints"]):
        if token and token in compact_token(file_index.relative_path):
            score += 3
            reasons.append(f"path matches {token}")

    deduped: list[str] = []
    seen = set()
    for reason in reasons:
        if reason not in seen:
            deduped.append(reason)
            seen.add(reason)

    # --- Method hint negative correction ---
    method_hints = signals.get("method_hints", set())
    method_hint_required = signals.get("method_hint_required", False)

    if method_hints and score > 0:
        method_tokens = {compact_token(m) for m in method_hints if compact_token(m)}
        matched_methods = method_tokens & lowered_member_calls
        unmatched_methods = method_tokens - lowered_member_calls

        if method_hint_required:
            # Require at least ONE method match. If zero matched, cap score.
            if not matched_methods and method_tokens:
                if score > 5:
                    penalty = score - 5
                    score = 5
                    deduped.append(
                        f"capped: no matched required method "
                        f"(needed one of {', '.join(sorted(method_tokens))}) (-{penalty})"
                    )
        elif unmatched_methods:
            # Soft correction: -2 per unmatched method, max -4
            penalty = min(4, len(unmatched_methods) * 2)
            score = max(0, score - penalty)
            if penalty > 0:
                deduped.append(
                    f"missing method hint "
                    f"{', '.join(sorted(unmatched_methods))} (-{penalty})"
                )

    return score, deduped


def score_project(project: TestProjectIndex, signals: dict[str, set[str]]) -> tuple[int, list[str], list[tuple[int, TestFileIndex, list[str]]]]:
    ensure_project_files_loaded(project)
    project_score = 0
    project_reasons: list[str] = []
    path_key = compact_token(project.path_key)

    for hint in sorted(signals["project_hints"]):
        if hint and hint in path_key:
            project_score += 10
            project_reasons.append(f"path matches {hint}")

    file_hits: list[tuple[int, TestFileIndex, list[str]]] = []
    for test_file in project.files:
        file_score, file_reasons = score_file(test_file, signals)
        if file_score > 0:
            file_hits.append((file_score, test_file, file_reasons))

    file_hits.sort(key=lambda item: (-item[0], item[1].relative_path))
    if file_hits:
        project_score += file_hits[0][0]
        project_reasons.append(f"best file score {file_hits[0][0]}")
        if len(file_hits) > 1:
            # Convergence bonus: multiple independent files matching the same
            # signals strengthen the case that this project covers the queried
            # entity. The bonus is logarithmic so it never overwhelms the
            # primary file score.
            #   2 files → +1   4 files → +2   8 files → +3   16 files → +4
            convergence = math.floor(math.log2(len(file_hits)))
            if convergence > 0:
                project_score += convergence
                project_reasons.append(f"convergence +{convergence} ({len(file_hits)} files)")
    return project_score, project_reasons, file_hits


def confidence(score: int) -> str:
    if score >= 24:
        return "high"
    if score >= 12:
        return "medium"
    return "low"


def project_has_non_lexical_evidence(
    project_reasons: list[str],
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
) -> bool:
    for reason in project_reasons:
        if reason.startswith('imports '):
            return True
    for _file_score, _test_file, reasons in file_hits[:3]:
        for reason in reasons:
            if (
                reason.startswith('imports ')
                or reason.startswith('calls ')
                or reason.startswith('member call .')
                or reason.startswith('constructs hinted type ')
                or reason.startswith('imports hinted type ')
                or reason.startswith('calls hinted type member ')
                or reason.startswith('reads/writes fields of hinted type ')
            ):
                return True
    return False


def candidate_bucket(score: int, has_non_lexical_evidence: bool) -> str:
    if score >= 24 and has_non_lexical_evidence:
        return 'must-run'
    if score >= 12 and has_non_lexical_evidence:
        return 'high-confidence related'
    return 'possible related'


def filter_project_results_by_relevance(
    project_results: list[dict],
    relevance_mode: str,
) -> tuple[list[dict], dict[str, object]]:
    allowed_buckets = {
        "all": {"must-run", "high-confidence related", "possible related"},
        "balanced": {"must-run", "high-confidence related"},
        "strict": {"must-run"},
    }
    allowed = allowed_buckets.get(relevance_mode, allowed_buckets["all"])
    counts_before = {
        "must-run": 0,
        "high-confidence related": 0,
        "possible related": 0,
    }
    for item in project_results:
        bucket = str(item.get("bucket") or "possible related")
        if bucket in counts_before:
            counts_before[bucket] += 1
    filtered = [item for item in project_results if str(item.get("bucket") or "possible related") in allowed]
    counts_after = {
        "must-run": 0,
        "high-confidence related": 0,
        "possible related": 0,
    }
    for item in filtered:
        bucket = str(item.get("bucket") or "possible related")
        if bucket in counts_after:
            counts_after[bucket] += 1
    return filtered, {
        "mode": relevance_mode,
        "total_before": len(project_results),
        "total_after": len(filtered),
        "filtered_out": len(project_results) - len(filtered),
        "counts_before": counts_before,
        "counts_after": counts_after,
    }


def specificity_target_tokens(signals: dict[str, set[str]]) -> set[str]:
    tokens = {
        compact_token(token)
        for token in signals.get("project_hints", set())
        if compact_token(token)
    }
    if not tokens:
        tokens = {
            compact_token(token)
            for token in signals.get("family_tokens", set())
            if compact_token(token)
        }
    if not tokens:
        tokens = {
            compact_token(
                str(symbol).replace("Modifier", "").replace("Configuration", "")
            )
            for symbol in signals.get("symbols", set())
            if compact_token(
                str(symbol).replace("Modifier", "").replace("Configuration", "")
            )
        }
    return {
        token
        for token in tokens
        if token
        and token not in GENERIC_PATH_TOKENS
        and token not in LOW_SIGNAL_SPECIFICITY_TOKENS
    }


def _is_direct_evidence_reason(reason: str) -> bool:
    return reason.startswith(
        (
            "imports ",
            "imports symbol ",
            "calls ",
            "member call .",
            "typed modifier evidence for ",
            "calls .",
            "calls methods ",
            "constructs hinted type ",
            "imports hinted type ",
            "calls hinted type member ",
            "reads/writes fields of hinted type ",
        )
    )


def classify_project_scope(
    project: TestProjectIndex,
    signals: dict[str, set[str]],
    project_reasons: list[str],
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
) -> tuple[str, int, list[str]]:
    target_tokens = specificity_target_tokens(signals)
    project_tokens = {
        compact_token(part)
        for part in tokenize_path_parts(project.path_key or project.relative_root.lower())
        if compact_token(part)
    }
    project_tokens.update(
        token for token in path_component_tokens(project.path_key or project.relative_root.lower())
        if token
    )
    generic_project_tokens = sorted(token for token in project_tokens if token in GENERIC_SCOPE_TOKENS)
    project_target_tokens = sorted(
        target
        for target in target_tokens
        if any(target in token or token in target for token in project_tokens)
    )

    top_hits = file_hits[:3]
    top_hit_target_tokens: set[str] = set()
    direct_evidence_count = 0
    target_path_match_count = 0
    total_file_score = sum(file_score for file_score, _file_index, _reasons in file_hits)
    top_score = file_hits[0][0] if file_hits else 0
    top_share = (top_score / total_file_score) if total_file_score else 0.0

    for _file_score, file_index, reasons in top_hits:
        path_compact = compact_token(file_index.relative_path)
        matched_tokens = {token for token in target_tokens if token in path_compact}
        if matched_tokens:
            target_path_match_count += 1
            top_hit_target_tokens.update(matched_tokens)
        direct_evidence_count += sum(1 for reason in reasons if _is_direct_evidence_reason(reason))

    specificity_score = 0
    scope_reasons: list[str] = []

    if top_hit_target_tokens:
        path_bonus = 6 if len(top_hit_target_tokens) >= 2 else 4
        specificity_score += path_bonus
        scope_reasons.append(
            f"top matching files stay in target API paths: {', '.join(sorted(top_hit_target_tokens))}"
        )
    if project_target_tokens:
        specificity_score += 4
        scope_reasons.append(
            f"project path aligns with target family: {', '.join(sorted(project_target_tokens))}"
        )

    if direct_evidence_count >= 4:
        specificity_score += 5
        scope_reasons.append("top matching files contain strong direct API usage evidence")
    elif direct_evidence_count >= 2:
        specificity_score += 3
        scope_reasons.append("top matching files contain direct API usage evidence")
    elif direct_evidence_count >= 1:
        specificity_score += 1
        scope_reasons.append("matching files contain some direct API usage evidence")

    if top_share >= 0.6:
        specificity_score += 4
        scope_reasons.append("evidence is tightly concentrated in the best file")
    elif top_share >= 0.4:
        specificity_score += 2
        scope_reasons.append("evidence is concentrated in the top files")

    if len(file_hits) <= 2 and file_hits:
        specificity_score += 2
        scope_reasons.append("only a small number of files match")
    elif len(file_hits) >= 6:
        specificity_score -= 2
        scope_reasons.append("matches are spread across many files")

    if len(generic_project_tokens) >= 2:
        specificity_score -= 4
        scope_reasons.append(
            f"project path looks broad or umbrella-like: {', '.join(generic_project_tokens[:3])}"
        )
    elif len(generic_project_tokens) == 1:
        specificity_score -= 2
        scope_reasons.append(
            f"project path has a broad marker: {generic_project_tokens[0]}"
        )

    broad_by_shape = (
        (len(generic_project_tokens) >= 1 and not project_target_tokens)
        or (len(file_hits) >= 5 and direct_evidence_count <= 1)
    )
    direct_candidate = (
        project_target_tokens
        and direct_evidence_count >= 2
        and top_share >= 0.35
        and len(generic_project_tokens) == 0
    )

    if direct_candidate and specificity_score >= 8:
        scope_tier = "direct"
    elif not broad_by_shape and specificity_score >= 4:
        scope_tier = "focused"
    else:
        scope_tier = "broad"

    if not scope_reasons:
        scope_reasons = list(project_reasons[:2]) if project_reasons else ["scope inferred from aggregate ranking evidence"]
    return scope_tier, max(0, specificity_score), scope_reasons


def scope_sort_key(scope_tier: str) -> int:
    return SCOPE_TIER_ORDER.get(str(scope_tier), 99)


def bucket_sort_key(bucket: str) -> int:
    return BUCKET_ORDER.get(str(bucket), 99)


def project_result_sort_tuple(item: dict) -> tuple[object, ...]:
    return (
        scope_sort_key(str(item.get("scope_tier", "broad"))),
        bucket_sort_key(str(item.get("bucket", "possible related"))),
        -int(item.get("specificity_score", 0) or 0),
        -int(item.get("score", 0) or 0),
        str(item.get("project", "")),
    )


def sort_project_results(project_results: list[dict]) -> None:
    project_results.sort(key=project_result_sort_tuple)


def split_scope_groups(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    primary = [item for item in entries if str(item.get("scope_tier", "broad")) in PRIMARY_SCOPE_TIERS]
    broader = [item for item in entries if str(item.get("scope_tier", "broad")) not in PRIMARY_SCOPE_TIERS]
    return primary, broader


def matched_file_surfaces(file_hits: list[tuple[int, TestFileIndex, list[str]]]) -> set[str]:
    return {
        file_index.surface
        for _score, file_index, _reasons in file_hits
        if file_index.surface in {STATIC, DYNAMIC}
    }


def should_keep_project_for_surface(
    project: TestProjectIndex,
    file_hits: list[tuple[int, TestFileIndex, list[str]]],
    requested_mode: str,
) -> bool:
    if requested_mode in {"auto", "both"}:
        return True
    hit_surfaces = matched_file_surfaces(file_hits)
    if hit_surfaces:
        return requested_mode in hit_surfaces
    if project.supported_surfaces:
        return requested_mode in project.supported_surfaces
    return False


def project_entry_primary_surfaces(project_entry: dict) -> set[str]:
    matched_surfaces = {
        surface
        for surface in project_entry.get("matched_surfaces", [])
        if surface in {STATIC, DYNAMIC}
    }
    if matched_surfaces:
        return matched_surfaces
    supported_surfaces = {
        surface
        for surface in project_entry.get("supported_surfaces", [])
        if surface in {STATIC, DYNAMIC}
    }
    if supported_surfaces:
        return supported_surfaces
    variant = str(project_entry.get("variant") or "")
    if variant in {STATIC, DYNAMIC}:
        return {variant}
    if variant == BOTH:
        return {STATIC, DYNAMIC}
    return set()


def project_entry_supports_surface(project_entry: dict, surface: str) -> bool:
    return surface in project_entry_primary_surfaces(project_entry)


def project_entry_is_surface_exclusive(project_entry: dict, surface: str) -> bool:
    return project_entry_primary_surfaces(project_entry) == {surface}


def restrict_explicit_surface_projects(
    project_results: list[dict],
    requested_surface: str,
    explicit_surface_query: bool,
) -> list[dict]:
    if not explicit_surface_query or requested_surface not in {STATIC, DYNAMIC}:
        return project_results

    exclusive = [
        item for item in project_results
        if project_entry_is_surface_exclusive(item, requested_surface)
    ]
    if exclusive:
        return exclusive

    supporting = [
        item for item in project_results
        if project_entry_supports_surface(item, requested_surface)
    ]
    if supporting:
        return supporting
    return project_results


def diversify_symbol_query_projects(project_results: list[dict], top_projects: int) -> list[dict]:
    shown = list(project_results if top_projects <= 0 else project_results[:top_projects])
    if len(shown) < 2:
        return shown

    replace_cursor = len(shown) - 1
    for surface in (STATIC, DYNAMIC):
        if any(project_entry_is_surface_exclusive(item, surface) for item in shown):
            continue
        shown_paths = {item.get("project") for item in shown}
        candidate = next(
            (
                item
                for item in project_results
                if item.get("project") not in shown_paths
                and project_entry_is_surface_exclusive(item, surface)
            ),
            None,
        )
        if candidate is None:
            candidate = next(
                (
                    item
                    for item in project_results
                    if item.get("project") not in shown_paths
                    and project_entry_supports_surface(item, surface)
                ),
                None,
            )
        if candidate is None or candidate in shown:
            continue
        while replace_cursor >= 0 and shown[replace_cursor].get("project") == candidate.get("project"):
            replace_cursor -= 1
        if replace_cursor < 0:
            break
        shown[replace_cursor] = candidate
        replace_cursor -= 1
    return shown


def variant_matches(project_variant: str, variants_mode: str) -> bool:
    if variants_mode in {'auto', 'both'}:
        return True
    if project_variant == 'both':
        return True
    if project_variant == 'unknown':
        return False
    return project_variant == variants_mode


def resolve_variants_mode(variants_mode: str, changed_file: Path | None = None) -> str:
    if variants_mode != 'auto':
        return variants_mode
    if changed_file is None:
        return 'both'
    profile = classify_ace_engine_surface(changed_file, read_text(changed_file))
    return surface_to_variants_mode(profile.surface)


def coverage_signature(
    file_hits: list[tuple[int, "TestFileIndex", list[str]]],
    project_path_key: str = "",
) -> frozenset[str]:
    """Compute a query-scoped coverage fingerprint for a project.

    The signature is the union of all signal-matching reasons across every
    scoring file in the project (e.g. 'imports symbol Button',
    'calls Button()', 'member call .borderColor()').

    To avoid over-collapsing weak call-only suites, the signature also includes
    normalized member-call tokens from the matched files. This keeps
    `scrollToIndex()` and `justifyContent()` style scaffolding projects from
    being treated as identical when their reason strings are otherwise the same.

    When ``project_path_key`` is provided, the last meaningful segment of
    the project path (with common prefixes/suffixes stripped) is added to the
    signature so that projects testing different attributes (e.g. borderColor
    vs backgroundColor) are not collapsed even when their reason sets match.

    Two projects with the same signature provide *identical* evidence for the
    current query — running both gives the developer no additional confidence.
    Deduplication keeps only the top-N representatives per signature.

    Note: the signature is computed per-query at scoring time, not stored on
    disk. Two projects that are duplicates for ButtonModifier may be unique
    for ListModifier.
    """
    reasons = {reason for _, _, reasons in file_hits for reason in reasons}
    member_tokens = {
        f"_member:{compact_token(member)}"
        for _, file_index, _ in file_hits
        for member in file_index.member_calls
        if compact_token(member)
    }

    path_category: set[str] = set()
    if project_path_key:
        last_segment = project_path_key.rsplit("/", 1)[-1] if "/" in project_path_key else project_path_key
        for prefix in ("ace_ets_component_", "ace_ets_module_", "ace_c_arkui_"):
            if last_segment.startswith(prefix):
                last_segment = last_segment[len(prefix):]
                break
        for suffix in ("_static", "_dynamic"):
            if last_segment.endswith(suffix):
                last_segment = last_segment[:-len(suffix)]
        path_category.add(f"_category:{compact_token(last_segment)}")

    return frozenset(reasons | member_tokens | path_category)


def deduplicate_by_coverage_signature(
    ranked: list[dict],
    keep_per_signature: int,
) -> list[dict]:
    """Remove coverage-duplicate projects from a ranked list.

    Projects are processed in score order (highest first). When
    ``keep_per_signature`` representatives with the same evidence fingerprint
    have already been kept, subsequent projects with that fingerprint are
    discarded.

    Args:
        ranked: projects already sorted by score descending.
        keep_per_signature: max representatives per unique signature.
            0 (or negative) disables deduplication — all projects pass through.
            1 = strict: one representative per coverage pattern.
            2 = safe default: guards against a single flaky test masking a bug.

    The internal ``_coverage_sig`` key is stripped from all output dicts.
    """
    if keep_per_signature <= 0:
        for item in ranked:
            item.pop("_coverage_sig", None)
        return ranked

    seen: dict[frozenset, int] = {}
    result: list[dict] = []
    for item in ranked:
        sig = item.pop("_coverage_sig", None)
        if sig is None:
            result.append(item)
            continue
        count = seen.get(sig, 0)
        if count < keep_per_signature:
            result.append(item)
            seen[sig] = count + 1
    return result


def make_coverage_source(source_type: str, source_value: str) -> dict[str, str]:
    return {
        "key": f"{source_type}:{source_value}",
        "type": source_type,
        "value": source_value,
    }


def coverage_rank_weight(rank: int) -> float:
    normalized = max(ACTIVE_RANKING_RULES.rank_weight_floor, int(rank or 1))
    return 1.0 / float(normalized ** ACTIVE_RANKING_RULES.rank_weight_power)


def _build_selection_signals(candidate: dict, target: dict) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    source_reasons = dict(candidate.get("source_reasons") or {})
    sources = dict(candidate.get("sources") or {})

    for source_key in sorted(set(str(k) for k in source_reasons.keys())):
        source_info = sources.get(source_key, {})
        reasons = source_reasons.get(source_key, [])
        signal: dict[str, object] = {
            "source_key": source_key,
            "source_type": str(source_info.get("type") or ""),
            "source_value": str(source_info.get("value") or ""),
        }
        match_types: list[str] = []
        matched_keys: list[str] = []
        for reason in reasons:
            reason_str = str(reason or "")
            if not reason_str:
                continue
            reason_lower = reason_str.lower()
            if "family" in reason_lower:
                match_types.append("family")
            elif "capability" in reason_lower:
                match_types.append("capability")
            elif "type_hint" in reason_lower or "type hint" in reason_lower:
                match_types.append("type_hint")
            elif "member" in reason_lower:
                match_types.append("member_hint")
            else:
                match_types.append(reason_str)
            matched_keys.append(reason_str)
        if match_types:
            signal["match_types"] = sorted(set(match_types))
        if matched_keys:
            signal["matched_keys"] = matched_keys
        signals.append(signal)

    covered_families = sorted(candidate.get("covered_families", set()))
    covered_capabilities = sorted(candidate.get("covered_capabilities", set()))
    covered_type_hints = sorted(candidate.get("covered_type_hints", set()))
    covered_member_hints = sorted(candidate.get("covered_member_hints", set()))

    if covered_families:
        signals.append({"match_type": "family", "matched_keys": covered_families})
    if covered_capabilities:
        signals.append({"match_type": "capability", "matched_keys": covered_capabilities})
    if covered_type_hints:
        signals.append({"match_type": "type_hint", "matched_keys": covered_type_hints})
    if covered_member_hints:
        signals.append({"match_type": "member_hint", "matched_keys": covered_member_hints})

    return signals


def build_global_coverage_recommendations(
    candidate_entries: list[dict[str, object]],
    repo_root: Path,
    acts_out_root: Path | None,
    device: str | None,
    built_artifact_index: dict[str, object] | None = None,
) -> dict[str, object]:
    if not candidate_entries:
        return {
            "source_count": 0,
            "candidate_count": 0,
            "recommended": [],
            "optional_duplicates": [],
            "ordered_targets": [],
            "recommended_target_keys": [],
            "optional_target_keys": [],
            "ordered_target_keys": [],
            "covered_source_keys": [],
            "uncovered_sources": [],
            "unavailable_targets": [],
        }

    def _unit_key_for_source(source_profile: dict[str, object], unit_key: str, unit_kind: str) -> str:
        source_key = str(source_profile.get("key") or "")
        source_type = str(source_profile.get("type") or "")
        if unit_key:
            if source_type == "changed_file":
                return f"changed_{unit_kind}:{unit_key}"
            return f"{source_key}|{unit_kind}:{unit_key}"
        return source_key

    candidates_by_key: dict[str, dict[str, object]] = {}
    all_sources: dict[str, dict[str, object]] = {}
    all_units: dict[str, dict[str, object]] = {}
    unavailable_targets: dict[str, dict[str, object]] = {}
    for entry in candidate_entries:
        project_entry = dict(entry.get("project_entry") or {})
        if not project_entry:
            continue
        source = dict(entry.get("source") or {})
        source_profile = dict(entry.get("source_profile") or source)
        source_key = str(source_profile.get("key") or source.get("key") or "")
        if not source_key:
            continue
        all_sources[source_key] = {
            "type": str(source_profile.get("type") or source.get("type") or ""),
            "value": str(source_profile.get("value") or source.get("value") or ""),
            "family_keys": list(source_profile.get("family_keys", [])),
            "capability_keys": list(source_profile.get("capability_keys", [])),
            "type_hint_keys": list(source_profile.get("type_hint_keys", [])),
            "member_hint_keys": list(source_profile.get("member_hint_keys", [])),
        }
        target = build_run_target_entry(
            project_entry,
            repo_root=repo_root,
            acts_out_root=acts_out_root,
            built_artifact_index=built_artifact_index,
            device=device,
        )
        target_key = target.get("target_key") or target.get("test_json") or target.get("project") or ""
        if not target_key:
            continue
        if str(target.get("artifact_status") or "") == "missing":
            unavailable_targets.setdefault(
                str(target_key),
                {
                    "target_key": str(target_key),
                    "project": target.get("project", ""),
                    "test_json": target.get("test_json", ""),
                    "build_target": target.get("build_target", ""),
                    "xdevice_module_name": target.get("xdevice_module_name", ""),
                    "artifact_status": target.get("artifact_status", "missing"),
                    "artifact_reason": target.get("artifact_reason", ""),
                },
            )
            continue
        candidate = candidates_by_key.setdefault(
            str(target_key),
            {
                "key": str(target_key),
                "target": target,
                "source_keys": set(),
                "sources": {},
                "source_reasons": {},
                "source_ranks": {},
                "unit_gains": {},
                "unit_representative_scores": {},
                "unit_focus_overlaps": {},
                "unit_source_gains": {},
                "unit_sources": {},
                "covered_families": set(),
                "covered_capabilities": set(),
                "covered_type_hints": set(),
                "covered_member_hints": set(),
                "aggregate_type_hint_keys": set(),
                "aggregate_direct_type_hint_keys": set(),
                "aggregate_type_hint_focus_counts": {},
                "aggregate_member_hint_keys": set(),
                "aggregate_direct_member_hint_keys": set(),
                "aggregate_member_hint_focus_counts": {},
            },
        )
        existing_target = candidate["target"]
        if project_result_sort_tuple(project_entry) < project_result_sort_tuple(existing_target):
            candidate["target"] = target
            existing_target = target
        candidate["aggregate_type_hint_keys"].update(
            str(item)
            for item in project_entry.get("type_hint_keys", [])
            if str(item).strip()
        )
        candidate["aggregate_direct_type_hint_keys"].update(
            str(item)
            for item in project_entry.get("direct_type_hint_keys", [])
            if str(item).strip()
        )
        aggregate_focus_counts = candidate["aggregate_type_hint_focus_counts"]
        for raw_key, raw_value in dict(project_entry.get("type_hint_focus_counts") or {}).items():
            normalized_key = str(raw_key).strip()
            if not normalized_key:
                continue
            try:
                normalized_value = int(raw_value or 0)
            except (TypeError, ValueError):
                continue
            previous_value = int(aggregate_focus_counts.get(normalized_key, 0) or 0)
            if normalized_value > previous_value:
                aggregate_focus_counts[normalized_key] = normalized_value
        candidate["aggregate_member_hint_keys"].update(
            str(item)
            for item in project_entry.get("member_hint_keys", [])
            if str(item).strip()
        )
        candidate["aggregate_direct_member_hint_keys"].update(
            str(item)
            for item in project_entry.get("direct_member_hint_keys", [])
            if str(item).strip()
        )
        aggregate_member_focus_counts = candidate["aggregate_member_hint_focus_counts"]
        for raw_key, raw_value in dict(project_entry.get("member_hint_focus_counts") or {}).items():
            normalized_key = str(raw_key).strip()
            if not normalized_key:
                continue
            try:
                normalized_value = int(raw_value or 0)
            except (TypeError, ValueError):
                continue
            previous_value = int(aggregate_member_focus_counts.get(normalized_key, 0) or 0)
            if normalized_value > previous_value:
                aggregate_member_focus_counts[normalized_key] = normalized_value
        candidate["source_keys"].add(source_key)
        candidate["sources"][source_key] = all_sources[source_key]
        candidate["source_reasons"].setdefault(source_key, list(project_entry.get("scope_reasons", [])))
        source_rank = int(entry.get("source_rank", 999) or 999)
        candidate["source_ranks"][source_key] = min(
            int(candidate["source_ranks"].get(source_key, 999) or 999),
            source_rank,
        )
        member_hint_keys = list(source_profile.get("member_hint_keys", []))
        type_hint_keys = list(source_profile.get("type_hint_keys", []))
        capability_keys = list(source_profile.get("capability_keys", []))
        family_keys = list(source_profile.get("family_keys", []))
        member_hint_gains = suite_source_member_hint_gains(project_entry, source_profile)
        member_hint_representative_scores = suite_source_member_hint_representative_scores(project_entry, source_profile)
        type_hint_gains = suite_source_type_hint_gains(project_entry, source_profile)
        type_hint_representative_scores = suite_source_type_hint_representative_scores(project_entry, source_profile)
        capability_gains = suite_source_capability_gains(project_entry, source_profile)
        capability_representative_scores = suite_source_capability_representative_scores(project_entry, source_profile)
        family_gains = suite_source_family_gains(project_entry, source_profile)
        family_representative_scores = suite_source_family_representative_scores(project_entry, source_profile)
        focus_overlap = suite_source_focus_token_overlap(project_entry, source_profile)
        member_hint_owner_keys = {
            str(item).partition(".")[0]
            for item in member_hint_keys
            if "." in str(item)
        }
        if member_hint_keys:
            for member_hint_key in member_hint_keys:
                unit_key = _unit_key_for_source(source_profile, member_hint_key, "member")
                all_units.setdefault(
                    unit_key,
                    {
                        "key": unit_key,
                        "unit_kind": "member_hint",
                        "member_hint_key": member_hint_key,
                        "type_hint_key": str(member_hint_key).partition(".")[0],
                        "family_key": "",
                        "capability_key": "",
                        "type": str(source_profile.get("type") or ""),
                        "sources": [],
                    },
                )
                source_entry = {
                    "type": str(source_profile.get("type") or ""),
                    "value": str(source_profile.get("value") or ""),
                }
                if source_entry not in all_units[unit_key]["sources"]:
                    all_units[unit_key]["sources"].append(source_entry)
                gain = float(member_hint_gains.get(member_hint_key, 0.0) or 0.0)
                if gain <= 0:
                    continue
                weighted_gain = gain * coverage_rank_weight(source_rank)
                source_gains = candidate["unit_source_gains"].setdefault(unit_key, {})
                previous_gain = float(source_gains.get(source_key, 0.0) or 0.0)
                if weighted_gain > previous_gain:
                    source_gains[source_key] = weighted_gain
                    candidate["unit_gains"][unit_key] = round(sum(float(value or 0.0) for value in source_gains.values()), 6)
                    candidate["unit_sources"][unit_key] = list(all_units[unit_key]["sources"])
                representative_score = float(member_hint_representative_scores.get(member_hint_key, 0.0) or 0.0)
                previous_representative_score = float(candidate["unit_representative_scores"].get(unit_key, 0.0) or 0.0)
                if representative_score > previous_representative_score:
                    candidate["unit_representative_scores"][unit_key] = representative_score
                previous_focus_overlap = int(candidate["unit_focus_overlaps"].get(unit_key, 0) or 0)
                if focus_overlap > previous_focus_overlap:
                    candidate["unit_focus_overlaps"][unit_key] = focus_overlap
                candidate["covered_member_hints"].add(member_hint_key)
        if type_hint_keys:
            for type_hint_key in type_hint_keys:
                candidate_member_hint_keys = {
                    str(item).partition(".")[0]
                    for item in project_entry.get("member_hint_keys", [])
                    if "." in str(item)
                }
                if type_hint_key in member_hint_owner_keys and type_hint_key not in candidate_member_hint_keys:
                    continue
                unit_key = _unit_key_for_source(source_profile, type_hint_key, "type")
                all_units.setdefault(
                    unit_key,
                    {
                        "key": unit_key,
                        "unit_kind": "type_hint",
                        "type_hint_key": type_hint_key,
                        "family_key": "",
                        "capability_key": "",
                        "type": str(source_profile.get("type") or ""),
                        "sources": [],
                    },
                )
                source_entry = {
                    "type": str(source_profile.get("type") or ""),
                    "value": str(source_profile.get("value") or ""),
                }
                if source_entry not in all_units[unit_key]["sources"]:
                    all_units[unit_key]["sources"].append(source_entry)
                gain = float(type_hint_gains.get(type_hint_key, 0.0) or 0.0)
                if type_hint_key in member_hint_owner_keys:
                    gain *= 0.35
                if gain <= 0:
                    continue
                weighted_gain = gain * coverage_rank_weight(source_rank)
                source_gains = candidate["unit_source_gains"].setdefault(unit_key, {})
                previous_gain = float(source_gains.get(source_key, 0.0) or 0.0)
                if weighted_gain > previous_gain:
                    source_gains[source_key] = weighted_gain
                    candidate["unit_gains"][unit_key] = round(sum(float(value or 0.0) for value in source_gains.values()), 6)
                    candidate["unit_sources"][unit_key] = list(all_units[unit_key]["sources"])
                representative_score = float(type_hint_representative_scores.get(type_hint_key, 0.0) or 0.0)
                previous_representative_score = float(candidate["unit_representative_scores"].get(unit_key, 0.0) or 0.0)
                if representative_score > previous_representative_score:
                    candidate["unit_representative_scores"][unit_key] = representative_score
                previous_focus_overlap = int(candidate["unit_focus_overlaps"].get(unit_key, 0) or 0)
                if focus_overlap > previous_focus_overlap:
                    candidate["unit_focus_overlaps"][unit_key] = focus_overlap
                candidate["covered_type_hints"].add(type_hint_key)
        if capability_keys:
            for capability_key in capability_keys:
                unit_key = _unit_key_for_source(source_profile, capability_key, "capability")
                all_units.setdefault(
                    unit_key,
                    {
                        "key": unit_key,
                        "unit_kind": "capability",
                        "capability_key": capability_key,
                        "family_key": capability_family_key(capability_key),
                        "type": str(source_profile.get("type") or ""),
                        "sources": [],
                    },
                )
                source_entry = {
                    "type": str(source_profile.get("type") or ""),
                    "value": str(source_profile.get("value") or ""),
                }
                if source_entry not in all_units[unit_key]["sources"]:
                    all_units[unit_key]["sources"].append(source_entry)
                gain = float(capability_gains.get(capability_key, 0.0) or 0.0)
                if gain <= 0:
                    continue
                weighted_gain = gain * coverage_rank_weight(source_rank)
                source_gains = candidate["unit_source_gains"].setdefault(unit_key, {})
                previous_gain = float(source_gains.get(source_key, 0.0) or 0.0)
                if weighted_gain > previous_gain:
                    source_gains[source_key] = weighted_gain
                    candidate["unit_gains"][unit_key] = round(sum(float(value or 0.0) for value in source_gains.values()), 6)
                    candidate["unit_sources"][unit_key] = list(all_units[unit_key]["sources"])
                representative_score = float(capability_representative_scores.get(capability_key, 0.0) or 0.0)
                previous_representative_score = float(candidate["unit_representative_scores"].get(unit_key, 0.0) or 0.0)
                if representative_score > previous_representative_score:
                    candidate["unit_representative_scores"][unit_key] = representative_score
                previous_focus_overlap = int(candidate["unit_focus_overlaps"].get(unit_key, 0) or 0)
                if focus_overlap > previous_focus_overlap:
                    candidate["unit_focus_overlaps"][unit_key] = focus_overlap
                candidate["covered_capabilities"].add(capability_key)
                family_key = capability_family_key(capability_key)
                if family_key:
                    candidate["covered_families"].add(family_key)
        if family_keys:
            for family_key in family_keys:
                unit_key = _unit_key_for_source(source_profile, family_key, "family")
                all_units.setdefault(
                    unit_key,
                    {
                        "key": unit_key,
                        "unit_kind": "family",
                        "family_key": family_key,
                        "capability_key": "",
                        "type": str(source_profile.get("type") or ""),
                        "sources": [],
                    },
                )
                source_entry = {
                    "type": str(source_profile.get("type") or ""),
                    "value": str(source_profile.get("value") or ""),
                }
                if source_entry not in all_units[unit_key]["sources"]:
                    all_units[unit_key]["sources"].append(source_entry)
                gain = float(family_gains.get(family_key, 0.0) or 0.0)
                if gain <= 0:
                    continue
                weighted_gain = gain * coverage_rank_weight(source_rank)
                source_gains = candidate["unit_source_gains"].setdefault(unit_key, {})
                previous_gain = float(source_gains.get(source_key, 0.0) or 0.0)
                if weighted_gain > previous_gain:
                    source_gains[source_key] = weighted_gain
                    candidate["unit_gains"][unit_key] = round(sum(float(value or 0.0) for value in source_gains.values()), 6)
                    candidate["unit_sources"][unit_key] = list(all_units[unit_key]["sources"])
                representative_score = float(family_representative_scores.get(family_key, 0.0) or 0.0)
                previous_representative_score = float(candidate["unit_representative_scores"].get(unit_key, 0.0) or 0.0)
                if representative_score > previous_representative_score:
                    candidate["unit_representative_scores"][unit_key] = representative_score
                previous_focus_overlap = int(candidate["unit_focus_overlaps"].get(unit_key, 0) or 0)
                if focus_overlap > previous_focus_overlap:
                    candidate["unit_focus_overlaps"][unit_key] = focus_overlap
                candidate["covered_families"].add(family_key)
        if not type_hint_keys and not capability_keys and not family_keys:
            unit_key = source_key
            all_units.setdefault(
                unit_key,
                {
                    "key": unit_key,
                    "unit_kind": "source",
                    "family_key": "",
                    "capability_key": "",
                    "type": str(source_profile.get("type") or ""),
                    "sources": [{"type": str(source_profile.get("type") or ""), "value": str(source_profile.get("value") or "")}],
                },
            )
            scope_multiplier = SCOPE_GAIN_MULTIPLIER.get(str(project_entry.get("scope_tier", "focused")), 1.0)
            bucket_multiplier = BUCKET_GAIN_MULTIPLIER.get(str(project_entry.get("bucket", "possible related")), 0.65)
            weighted_gain = (
                ACTIVE_RANKING_RULES.planner_fallback_no_family_gain
                * scope_multiplier
                * bucket_multiplier
                * coverage_rank_weight(source_rank)
            )
            previous_gain = float(candidate["unit_gains"].get(unit_key, 0.0) or 0.0)
            if weighted_gain > previous_gain:
                candidate["unit_gains"][unit_key] = weighted_gain
                candidate["unit_sources"][unit_key] = list(all_units[unit_key]["sources"])
            previous_focus_overlap = int(candidate["unit_focus_overlaps"].get(unit_key, 0) or 0)
            if focus_overlap > previous_focus_overlap:
                candidate["unit_focus_overlaps"][unit_key] = focus_overlap
            previous_representative_score = float(candidate["unit_representative_scores"].get(unit_key, 0.0) or 0.0)
            if float(focus_overlap) > previous_representative_score:
                candidate["unit_representative_scores"][unit_key] = float(focus_overlap)

    ordered_candidates: list[dict[str, object]] = []
    unit_winners: dict[str, dict[str, object]] = {}
    for candidate_key, candidate in candidates_by_key.items():
        target = dict(candidate["target"])
        for unit_key, gain in candidate.get("unit_gains", {}).items():
            representative_score = float(candidate.get("unit_representative_scores", {}).get(unit_key, 0.0) or 0.0)
            existing = unit_winners.get(unit_key)
            focus_overlap = int(candidate.get("unit_focus_overlaps", {}).get(unit_key, 0) or 0)
            umbrella_penalty = float(target.get("umbrella_penalty", 0.0) or 0.0)
            family_count = len(target.get("family_keys", []) or [])
            if existing is None:
                unit_winners[unit_key] = {
                    "candidate_key": candidate_key,
                    "representative_score": representative_score,
                    "gain": float(gain),
                    "focus_overlap": focus_overlap,
                    "umbrella_penalty": umbrella_penalty,
                    "family_count": family_count,
                    "sort_key": project_result_sort_tuple(target),
                }
                continue
            existing_representative_score = float(existing.get("representative_score", 0.0) or 0.0)
            existing_gain = float(existing.get("gain", 0.0) or 0.0)
            existing_focus_overlap = int(existing.get("focus_overlap", 0) or 0)
            existing_umbrella_penalty = float(existing.get("umbrella_penalty", 0.0) or 0.0)
            existing_family_count = int(existing.get("family_count", 0) or 0)
            if representative_score > existing_representative_score or (
                math.isclose(representative_score, existing_representative_score)
                and (
                    float(gain) > existing_gain or (
                        math.isclose(float(gain), existing_gain)
                        and (
                            focus_overlap > existing_focus_overlap
                            or (
                                focus_overlap == existing_focus_overlap
                                and (
                                    umbrella_penalty < existing_umbrella_penalty
                                    or (
                                        math.isclose(umbrella_penalty, existing_umbrella_penalty)
                                        and (
                                            family_count < existing_family_count
                                            or (
                                                family_count == existing_family_count
                                                and project_result_sort_tuple(target) < tuple(existing.get("sort_key", ()))
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            ):
                unit_winners[unit_key] = {
                    "candidate_key": candidate_key,
                    "representative_score": representative_score,
                    "gain": float(gain),
                    "focus_overlap": focus_overlap,
                    "umbrella_penalty": umbrella_penalty,
                    "family_count": family_count,
                    "sort_key": project_result_sort_tuple(target),
                }
    for candidate_key, candidate in candidates_by_key.items():
        candidate["planning_unit_gains"] = {
            unit_key: gain
            for unit_key, gain in candidate.get("unit_gains", {}).items()
            if unit_winners.get(unit_key, {}).get("candidate_key") == candidate_key
        }

    uncovered = set(all_units.keys())
    remaining = [candidate for candidate in candidates_by_key.values() if candidate.get("unit_gains")]
    while remaining:
        best_index = 0
        best_key: tuple[object, ...] | None = None
        for index, candidate in enumerate(remaining):
            all_unit_gains = candidate.get("unit_gains", {})
            all_covered_units = set(all_unit_gains.keys())
            planning_unit_gains = candidate.get("planning_unit_gains", {})
            planned_units = set(planning_unit_gains.keys())
            new_keys = planned_units & uncovered
            target = candidate["target"]
            new_score = sum(float(planning_unit_gains.get(key, 0.0) or 0.0) for key in new_keys)
            planning_total_score = sum(float(planning_unit_gains.get(key, 0.0) or 0.0) for key in planned_units)
            total_score = sum(float(all_unit_gains.get(key, 0.0) or 0.0) for key in all_covered_units)
            tie_key = (
                -new_score,
                -len(new_keys),
                -planning_total_score,
                -len(planned_units),
                -total_score,
                -len(all_covered_units),
                scope_sort_key(str(target.get("scope_tier", "broad"))),
                bucket_sort_key(str(target.get("bucket", "possible related"))),
                -int(target.get("specificity_score", 0) or 0),
                -int(target.get("score", 0) or 0),
                str(target.get("project", "")),
            )
            if best_key is None or tie_key < best_key:
                best_key = tie_key
                best_index = index
        candidate = remaining.pop(best_index)
        all_unit_gains = candidate.get("unit_gains", {})
        all_covered_units = set(all_unit_gains.keys())
        planning_unit_gains = candidate.get("planning_unit_gains", {})
        planned_units = set(planning_unit_gains.keys())
        new_keys = sorted(planned_units & uncovered)
        uncovered -= set(new_keys)
        target = dict(candidate["target"])
        source_keys = set(candidate["source_keys"])
        covered_sources = [
            {"type": info["type"], "value": info["value"]}
            for key, info in sorted(candidate["sources"].items())
        ]
        target["covered_source_keys"] = sorted(planned_units)
        target["covered_sources"] = covered_sources
        target["new_coverage_count"] = len(new_keys)
        target["total_coverage_count"] = len(all_covered_units)
        target["new_coverage_score"] = round(sum(float(planning_unit_gains.get(key, 0.0) or 0.0) for key in new_keys), 6)
        target["total_coverage_score"] = round(sum(float(all_unit_gains.get(key, 0.0) or 0.0) for key in all_covered_units), 6)
        target["type_hint_keys"] = sorted(candidate.get("aggregate_type_hint_keys", set()))
        target["direct_type_hint_keys"] = sorted(candidate.get("aggregate_direct_type_hint_keys", set()))
        target["type_hint_focus_counts"] = {
            str(key): int(value)
            for key, value in dict(candidate.get("aggregate_type_hint_focus_counts") or {}).items()
        }
        target["member_hint_keys"] = sorted(candidate.get("aggregate_member_hint_keys", set()))
        target["direct_member_hint_keys"] = sorted(candidate.get("aggregate_direct_member_hint_keys", set()))
        target["member_hint_focus_counts"] = {
            str(key): int(value)
            for key, value in dict(candidate.get("aggregate_member_hint_focus_counts") or {}).items()
        }
        target["covered_families"] = sorted(candidate.get("covered_families", set()))
        target["covered_capabilities"] = sorted(candidate.get("covered_capabilities", set()))
        target["covered_type_hints"] = sorted(candidate.get("covered_type_hints", set()))
        target["covered_member_hints"] = sorted(candidate.get("covered_member_hints", set()))
        target["new_families"] = sorted(
            {
                str(all_units[key].get("family_key") or "")
                for key in new_keys
                if str(all_units[key].get("family_key") or "")
            }
        )
        target["new_capabilities"] = sorted(
            {
                str(all_units[key].get("capability_key") or "")
                for key in new_keys
                if str(all_units[key].get("capability_key") or "")
            }
        )
        target["new_type_hints"] = sorted(
            {
                str(all_units[key].get("type_hint_key") or "")
                for key in new_keys
                if str(all_units[key].get("type_hint_key") or "")
            }
        )
        target["new_member_hints"] = sorted(
            {
                str(all_units[key].get("member_hint_key") or "")
                for key in new_keys
                if str(all_units[key].get("member_hint_key") or "")
            }
        )
        target["covered_units"] = [
            {
                "type": str(all_units[key].get("type") or ""),
                "unit_kind": str(all_units[key].get("unit_kind") or ""),
                "family_key": str(all_units[key].get("family_key") or ""),
                "capability_key": str(all_units[key].get("capability_key") or ""),
                "type_hint_key": str(all_units[key].get("type_hint_key") or ""),
                "member_hint_key": str(all_units[key].get("member_hint_key") or ""),
                "sources": list(all_units[key].get("sources", [])),
            }
            for key in sorted(all_covered_units)
        ]
        new_sources: list[dict[str, str]] = []
        seen_new_source_keys: set[tuple[str, str]] = set()
        for key in new_keys:
            for source in candidate.get("unit_sources", {}).get(key, []):
                normalized = {
                    "type": str(source.get("type") or ""),
                    "value": str(source.get("value") or ""),
                }
                dedupe_key = (normalized["type"], normalized["value"])
                if dedupe_key in seen_new_source_keys:
                    continue
                seen_new_source_keys.add(dedupe_key)
                new_sources.append(normalized)
        target["new_sources"] = new_sources
        target["execution_sources"] = covered_sources
        target["coverage_source_reasons"] = {
            key: candidate["source_reasons"].get(key, [])
            for key in sorted(source_keys)
        }
        target["selection_signals"] = _build_selection_signals(candidate, target)
        ordered_candidates.append(target)

    # Phase 3: Apply fan-out limits from ranking_rules.json
    fanout_limits = getattr(ACTIVE_RANKING_RULES, "family_fanout_limits", {})
    default_limit = fanout_limits.get("default", {"max_type_representatives": 5, "max_family_representatives": 10})
    precision_budget = getattr(ACTIVE_RANKING_RULES, "precision_budget", {})
    member_max_required = precision_budget.get("member_aware_max_required", 30)
    type_max_required = precision_budget.get("type_level_max_required", 100)
    family_max_required = precision_budget.get("family_level_max_required", 200)

    for target in ordered_candidates:
        covered_type_hints = set(target.get("covered_type_hints", []) or [])
        covered_families = set(target.get("covered_families", []) or [])
        covered_member_hints = set(target.get("covered_member_hints", []) or [])

        # Extract component families from the changed source file paths
        # (e.g. components_ng/pattern/toast/ → "toast")
        source_comp_families: set[str] = set()
        for src in target.get("execution_sources", []):
            src_str = str(src)
            m = re.search(r"components_ng/(?:pattern|render|event)/([^/]+)/", src_str)
            if m:
                source_comp_families.add(compact_token(m.group(1)))
        target["source_component_families"] = sorted(source_comp_families)

        # Determine precision mode based on evidence level
        if covered_member_hints:
            max_required = member_max_required
            target["precision_mode"] = "member"
        elif covered_type_hints:
            max_required = type_max_required
            target["precision_mode"] = "type"
        else:
            max_required = family_max_required
            target["precision_mode"] = "family"

        # Apply per-family type representative limits
        for family_key in list(target.get("covered_families", [])):
            limit = fanout_limits.get(family_key, default_limit)
            max_types = limit.get("max_type_representatives", default_limit["max_type_representatives"])
            if len(covered_type_hints) > max_types:
                # Suppress lowest-scoring type hints by marking excess as suppressed
                sorted_types = sorted(covered_type_hints)
                for extra_type in sorted_types[max_types:]:
                    target.setdefault("suppressed_type_hints", set()).add(extra_type)

        # Apply per-family family representative limits
        for family_key in list(target.get("covered_families", [])):
            limit = fanout_limits.get(family_key, default_limit)
            max_families = limit.get("max_family_representatives", default_limit["max_family_representatives"])
            if len(covered_families) > max_families:
                sorted_families = sorted(covered_families)
                for extra_family in sorted_families[max_families:]:
                    target.setdefault("suppressed_families", set()).add(extra_family)

        # Convert accumulator sets to sorted lists for JSON serialisation
        if isinstance(target.get("suppressed_type_hints"), set):
            target["suppressed_type_hints"] = sorted(target["suppressed_type_hints"])
        if isinstance(target.get("suppressed_families"), set):
            target["suppressed_families"] = sorted(target["suppressed_families"])

    required: list[dict[str, object]] = []
    recommended_additional: list[dict[str, object]] = []
    optional_duplicates = [target for target in ordered_candidates if int(target.get("new_coverage_count", 0)) <= 0]
    for target in ordered_candidates:
        new_coverage_count = int(target.get("new_coverage_count", 0) or 0)
        direct_member_hints = set(target.get("direct_member_hint_keys", []) or [])
        covered_member_hints = set(target.get("covered_member_hints", []) or [])
        matched_direct_member_hints = sorted(direct_member_hints & covered_member_hints)
        direct_type_hints = set(target.get("direct_type_hint_keys", []) or [])
        covered_type_hints = set(target.get("covered_type_hints", []) or [])
        matched_direct_type_hints = sorted(direct_type_hints & covered_type_hints)
        if new_coverage_count <= 0:
            # Direct component path match boost: if the test's project family
            # directly matches the component directory in the changed file path,
            # elevate to required even without new coverage or member hints.
            source_component_families = set(target.get("source_component_families", []) or [])
            target_project_families = covered_families
            direct_path_match = bool(source_component_families & target_project_families)
            if direct_path_match and str(target.get("bucket") or "") == "must-run":
                target["coverage_status"] = "required"
                target["coverage_reason"] = (
                    "direct component path match: test project covers the same component family as the changed file"
                )
                required.append(target)
                continue
            if matched_direct_member_hints:
                if str(target.get("bucket") or "") == "must-run":
                    target["coverage_status"] = "required"
                    target["coverage_reason"] = (
                        "adds no new planner unit, but directly validates changed member(s): "
                        + ", ".join(matched_direct_member_hints)
                    )
                    required.append(target)
                    continue
                if str(target.get("bucket") or "") == "high-confidence related":
                    target["coverage_status"] = "recommended"
                    target["coverage_reason"] = (
                        "adds no new planner unit, but directly validates changed member(s): "
                        + ", ".join(matched_direct_member_hints)
                    )
                    recommended_additional.append(target)
                    continue
            if matched_direct_type_hints:
                if str(target.get("bucket") or "") == "must-run":
                    target["coverage_status"] = "required"
                    target["coverage_reason"] = (
                        "adds no new planner unit, but directly reads/writes fields of changed type(s): "
                        + ", ".join(matched_direct_type_hints)
                    )
                    required.append(target)
                    continue
                if str(target.get("bucket") or "") == "high-confidence related":
                    target["coverage_status"] = "recommended"
                    target["coverage_reason"] = (
                        "adds no new planner unit, but provides direct field-read/write validation for changed type(s): "
                        + ", ".join(matched_direct_type_hints)
                    )
                    recommended_additional.append(target)
                    continue
            target["coverage_status"] = "optional"
            target["coverage_reason"] = "covers only functionality already covered by earlier selected suites"
            continue
        if str(target.get("bucket") or "") == "must-run":
            target["coverage_status"] = "required"
            target["coverage_reason"] = f"adds {new_coverage_count} new functional area(s) with strong direct coverage"
            required.append(target)
        else:
            target["coverage_status"] = "recommended"
            target["coverage_reason"] = f"adds {new_coverage_count} new functional area(s) but with weaker evidence"
            recommended_additional.append(target)
    recommended = required + recommended_additional
    covered_unit_keys = sorted(
        {
            key
            for target in recommended
            for key in target.get("covered_source_keys", [])
            if key
        }
    )
    uncovered_sources = [
        {
            "type": str(info.get("type") or ""),
            "value": str(
                info.get("type_hint_key")
                or info.get("capability_key")
                or info.get("family_key")
                or (info.get("sources") or [{"value": ""}])[0].get("value", "")
            ),
        }
        for key, info in sorted(all_units.items())
        if key not in covered_unit_keys
    ]
    return {
        "source_count": len(all_units),
        "candidate_count": len(ordered_candidates),
        "required": required,
        "recommended": recommended,
        "recommended_additional": recommended_additional,
        "optional_duplicates": optional_duplicates,
        "ordered_targets": ordered_candidates,
        "required_target_keys": [str(target.get("target_key") or "") for target in required],
        "recommended_target_keys": [str(target.get("target_key") or "") for target in recommended],
        "recommended_additional_target_keys": [str(target.get("target_key") or "") for target in recommended_additional],
        "optional_target_keys": [str(target.get("target_key") or "") for target in optional_duplicates],
        "ordered_target_keys": [str(target.get("target_key") or "") for target in ordered_candidates],
        "covered_source_keys": covered_unit_keys,
        "uncovered_sources": uncovered_sources,
        "unavailable_targets": list(unavailable_targets.values()),
    }


def test_json_data(path_value: str, repo_root: Path | None = None) -> dict:
    return parse_test_json(path_value, repo_root=repo_root)


def driver_module_name(test_json_path: str, repo_root: Path | None = None) -> str | None:
    return test_json_data(test_json_path, repo_root=repo_root).get("driver", {}).get("module-name")


def driver_type(test_json_path: str, repo_root: Path | None = None) -> str | None:
    return test_json_data(test_json_path, repo_root=repo_root).get("driver", {}).get("type")


def build_query_signals(
    query: str,
    sdk_index: SdkIndex,
    content_index: ContentModifierIndex,
    mapping_config: MappingConfig,
) -> dict[str, set[str]]:
    compact = compact_token(query)
    parts = [part for part in re.split(r"[\s/._-]+", query) if part]
    query_tokens = {compact_token(part) for part in parts if compact_token(part)}
    signals = {
        "modules": set(),
        "weak_modules": set(),
        "symbols": set(),
        "weak_symbols": set(),
        "project_hints": set(),
        "method_hints": set(),
        "type_hints": set(),
        "member_hints": set(),
        "raw_tokens": set(parts),
        "family_tokens": set(),
        "method_hint_required": False,
    }
    if not compact:
        return signals

    signals["symbols"].add(query)
    signals["project_hints"].add(compact)
    signals["family_tokens"].add(compact)

    base = compact_token(query.replace("Modifier", "").replace("Configuration", ""))
    if base:
        signals["project_hints"].add(base)
        signals["family_tokens"].add(base)
        if base in sdk_index.component_file_bases:
            signals["symbols"].add(sdk_index.component_file_bases[base])
        if base in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[base])
        signals["symbols"].update(mapping_config.pattern_alias.get(base, []))
        signals["symbols"].update(content_index.family_to_symbols.get(base, set()))

    if query in sdk_index.component_names or query in sdk_index.modifier_names:
        signals["symbols"].add(query)

    normalized_member = normalize_member_hint(query)
    if normalized_member:
        owner, _separator, member = query.partition(".")
        signals["member_hints"].add(query)
        if owner:
            signals["type_hints"].add(owner)
        if member:
            signals["method_hints"].add(member)

    component_tokens = {
        token for token in query_tokens
        if token in sdk_index.component_file_bases
        or token in sdk_index.modifier_file_bases
        or token in content_index.family_to_symbols
        or token in mapping_config.pattern_alias
    }
    for token in component_tokens:
        signals["project_hints"].add(token)
        signals["family_tokens"].add(token)
        if token in sdk_index.component_file_bases:
            symbol = sdk_index.component_file_bases[token]
            signals["symbols"].add(symbol)
        if token in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[token])
        signals["symbols"].update(mapping_config.pattern_alias.get(token, []))
        signals["symbols"].update(content_index.family_to_symbols.get(token, set()))

    if "attribute" in query_tokens:
        signals["project_hints"].add("attribute")
        signals["symbols"].add("AttributeModifier")
        signals["method_hints"].add("attributeModifier")
        for token in component_tokens:
            component_symbol = sdk_index.component_file_bases.get(token)
            if not component_symbol:
                continue
            signals["type_hints"].add(f"{component_symbol}Attribute")
            signals["symbols"].add(f"{component_symbol}Attribute")
            signals["method_hints"].add(f"get{component_symbol}Attribute")

    for key, rule in mapping_config.composite_mappings.items():
        compact_key = compact_token(key)
        # Token-based matching: exact compact match OR all key tokens present
        # in query tokens. Prevents short queries like "content" from matching
        # "content_modifier_helper_accessor".
        key_tokens = {compact_token(t) for t in tokenize_path_parts(key) if compact_token(t)}
        if compact == compact_key or key_tokens.issubset(query_tokens):
            signals["symbols"].update(rule.get("symbols", []))
            signals["project_hints"].update(rule.get("project_hints", []))
            signals["method_hints"].update(rule.get("method_hints", []))
            signals["type_hints"].update(rule.get("type_hints", []))
            for family in rule.get("families", []):
                family_key = compact_token(family)
                signals["family_tokens"].add(family_key)
                signals["project_hints"].add(family_key)
                signals["symbols"].update(content_index.family_to_symbols.get(family_key, set()))
            if rule.get("method_hint_required", False):
                signals["method_hint_required"] = True

    return {
        "modules": {item for item in signals["modules"] if item},
        "weak_modules": {item for item in signals.get("weak_modules", set()) if item},
        "symbols": {item for item in signals["symbols"] if item},
        "weak_symbols": {item for item in signals.get("weak_symbols", set()) if item},
        "project_hints": {
            compact_token(item) for item in signals["project_hints"]
            if item and compact_token(item) not in CONTENT_MODIFIER_NOISE
        },
        "method_hints": {item for item in signals["method_hints"] if item},
        "type_hints": {item for item in signals["type_hints"] if item},
        "raw_tokens": signals["raw_tokens"],
        "family_tokens": {
            compact_token(item) for item in signals["family_tokens"]
            if item and compact_token(item) not in CONTENT_MODIFIER_NOISE
        },
        "method_hint_required": signals["method_hint_required"],
    }


def explain_symbol_query_sources(query: str, xts_root: Path, limit: int = 20) -> dict:
    compact_query = compact_token(query)
    exact_hits: list[str] = []
    related_hits: list[str] = []
    if not compact_query or not xts_root.exists():
        return {"exact_hits": exact_hits, "related_hits": related_hits}

    for path in xts_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".ets", ".ts", ".js"}:
            continue
        text = read_text(path)
        rel = repo_rel(path)
        rel_compact = compact_token(rel)
        if query in text or compact_query in rel_compact:
            exact_hits.append(rel)
            continue
        if query.endswith("Modifier"):
            base = query[:-8]
            if base and (f"AttributeModifier<{base}Attribute>" in text or f"extends {query}" in text):
                related_hits.append(rel)
    return {
        "exact_hits": exact_hits[:limit],
        "related_hits": related_hits[:limit],
    }


def search_code_matches(
    keyword: str,
    code_root: Path,
    limit: int = 20,
) -> list[dict]:
    compact_keyword = compact_token(keyword)
    if not compact_keyword or not code_root.exists():
        return []
    candidates: list[dict] = []
    for path in code_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh", ".ets", ".ts", ".js"}:
            continue
        rel = repo_rel(path)
        rel_compact = compact_token(rel)
        text = read_text(path)
        score = 0
        reasons: list[str] = []
        if compact_keyword in rel_compact:
            score += 10
            reasons.append("path match")
        if keyword in text:
            score += 8
            reasons.append("exact text match")
        elif compact_keyword in compact_token(text[:50000]):
            score += 4
            reasons.append("compact text match")
        if score > 0:
            candidates.append({"file": rel, "score": score, "reasons": reasons[:3]})
    candidates.sort(key=lambda item: (-item["score"], item["file"]))
    return candidates[:limit]


def build_unresolved_analysis(
    signals: dict[str, set[str]],
    project_results: list[dict],
    *,
    affected_api_entities: Sequence[str] | None = None,
    derived_source_symbols: Sequence[str] | None = None,
) -> dict:
    top_score = project_results[0]["score"] if project_results else 0
    top_paths = [item["project"].lower() for item in project_results[:5]]
    broad_common_hits = sum(
        1 for path in top_paths
        if "common_seven_attrs" in path or "common_attrss" in path or "component_common" in path
    )
    has_content_modifier_signal = (
        "contentmodifier" in signals["project_hints"]
        or "ContentModifier" in signals["symbols"]
    )
    analysis = {
        "top_score": top_score,
        "top_paths": top_paths,
        "broad_common_hits": broad_common_hits,
        "has_content_modifier_signal": has_content_modifier_signal,
        "reason_class": None,
        "reason": None,
    }
    affected_api_entities = list(affected_api_entities or [])
    derived_source_symbols = list(derived_source_symbols or [])
    if not project_results:
        if affected_api_entities:
            analysis["reason_class"] = "consumer_evidence_gap"
            analysis["reason"] = "Changed APIs were mapped, but no XTS consumer evidence was found for them."
        elif derived_source_symbols:
            analysis["reason_class"] = "lineage_gap"
            analysis["reason"] = "Source symbols were detected, but they could not be mapped to XTS-covered APIs."
        else:
            analysis["reason_class"] = "no_matches"
            analysis["reason"] = "No XTS usages were found for this file."
        return analysis
    if top_score < 12:
        analysis["reason_class"] = "weak_signal"
        analysis["reason"] = "Only weak matches were found; test usage could not be determined reliably."
        return analysis
    if (
        has_content_modifier_signal
        and len(signals["family_tokens"]) >= 5
        and broad_common_hits >= min(3, len(top_paths))
        and not any("contentmodifier" in path for path in top_paths)
    ):
        analysis["reason_class"] = "broad_common_overmatch"
        analysis["reason"] = "Only broad/common ArkUI suites were matched; no reliable content-modifier-specific XTS usage was found."
    return analysis


def _classify_unresolved(
    changed_file: Path,
    signals: dict[str, set[str]],
    api_lineage_map: ApiLineageMap | None,
    consumer_semantics: list[dict],
) -> dict[str, str | None]:
    """Classify why a changed file is unresolved.

    Returns a dict with:
    - reason_class: one of 'no_source_member_mapping', 'no_consumer_member_evidence',
                    'lineage_gap', 'unsupported_generated_pattern'
    - reason: human-readable explanation
    """
    member_hints = signals.get("member_hints", set())
    type_hints = signals.get("type_hints", set())
    symbols = signals.get("symbols", set())
    project_hints = signals.get("project_hints", set())

    # Check if file is generated
    file_str = str(changed_file)
    is_generated = any(p in file_str for p in ("generated", "assembled", "koala"))

    # Check lineage map
    has_lineage = api_lineage_map is not None
    has_member_evidence = bool(member_hints)
    has_consumer_evidence = bool(consumer_semantics)

    # Generated files should be flagged first (before generic "no hints")
    if is_generated and not has_member_evidence:
        return {
            "reason_class": "unsupported_generated_pattern",
            "reason": "This is a generated file pattern that is not yet supported by the lineage resolver.",
        }

    if not has_member_evidence and not type_hints and not symbols:
        return {
            "reason_class": "lineage_gap",
            "reason": "No API lineage could be resolved for this file; it may be a framework-internal file without stable API exposure.",
        }

    if has_member_evidence and not has_consumer_evidence:
        return {
            "reason_class": "no_consumer_member_evidence",
            "reason": "Member-level API entities were resolved, but no XTS consumer evidence was found for them.",
        }

    if not has_lineage or not has_member_evidence:
        return {
            "reason_class": "no_source_member_mapping",
            "reason": "Source-side member mapping is incomplete for this file; it may require deeper semantic analysis.",
        }

    return {
        "reason_class": "lineage_gap",
        "reason": "Unresolved due to lineage traversal stopping at an unknown boundary.",
    }


def _api_owner_token(api_entity: str) -> str:
    owner = str(api_entity).partition(".")[0]
    for suffix in ("Modifier", "Attribute", "Configuration", "Controller"):
        owner = owner.replace(suffix, "")
    return compact_token(owner)


def build_function_coverage_rows(
    *,
    changed_file: Path,
    derived_source_symbols: list[str],
    affected_api_entities: list[str],
    api_lineage_map: ApiLineageMap | None,
    repo_root: Path,
    project_results: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not derived_source_symbols and not affected_api_entities:
        return []

    rows: list[dict[str, object]] = []
    symbol_list = list(derived_source_symbols) if derived_source_symbols else ["<file-level>"]
    for symbol in symbol_list:
        symbol_api_entities: list[str]
        if api_lineage_map is not None and symbol != "<file-level>":
            symbol_api_entities = api_lineage_map.apis_for_source_symbols(
                changed_file,
                [symbol],
                repo_root=repo_root,
            )
        else:
            symbol_api_entities = list(affected_api_entities)

        if not symbol_api_entities:
            rows.append(
                {
                    "symbol": symbol,
                    "status": "unresolved",
                    "mapped_api_entities": [],
                    "direct_projects": [],
                    "indirect_projects": [],
                    "not_covered_api_entities": [],
                }
            )
            continue

        covered_api_entities: set[str] = set()
        indirectly_covered_api_entities: set[str] = set()
        not_covered_api_entities: set[str] = set()
        direct_projects: set[str] = set()
        indirect_projects: set[str] = set()

        for api_entity in symbol_api_entities:
            owner_token = _api_owner_token(api_entity)
            direct_hits: set[str] = set()
            indirect_hits: set[str] = set()
            for project in project_results:
                project_name = str(project.get("project") or "").strip()
                direct_type_hints = {str(item).strip() for item in project.get("direct_type_hint_keys", []) if str(item).strip()}
                if owner_token and owner_token in direct_type_hints:
                    if project_name:
                        direct_hits.add(project_name)
                    continue
                family_keys = {str(item).strip() for item in project.get("family_keys", []) if str(item).strip()}
                direct_family_keys = {str(item).strip() for item in project.get("direct_family_keys", []) if str(item).strip()}
                if owner_token and (owner_token in family_keys or owner_token in direct_family_keys):
                    if project_name:
                        indirect_hits.add(project_name)

            if direct_hits:
                covered_api_entities.add(api_entity)
                direct_projects.update(direct_hits)
            elif indirect_hits:
                indirectly_covered_api_entities.add(api_entity)
                indirect_projects.update(indirect_hits)
            else:
                not_covered_api_entities.add(api_entity)

        if covered_api_entities:
            status = "covered"
        elif indirectly_covered_api_entities:
            status = "indirectly_covered"
        elif not_covered_api_entities:
            status = "not_covered"
        else:
            status = "unresolved"

        rows.append(
            {
                "symbol": symbol,
                "status": status,
                "mapped_api_entities": sorted(symbol_api_entities),
                "direct_projects": sorted(direct_projects),
                "indirect_projects": sorted(indirect_projects),
                "not_covered_api_entities": sorted(not_covered_api_entities),
            }
        )
    return rows


def _build_coverage_gap_report(
    affected_api_entities: list[str],
    project_results: list[dict[str, object]],
    api_lineage_map: "ApiLineageMap | None",
) -> dict[str, list]:
    """Classify each affected API entity by coverage evidence quality.

    Returns a dict with four lists:
    - covered: entities with direct type/member evidence in matched projects
    - indirectly_covered: entities with only family-level evidence
    - not_covered: entities with no evidence in any matched project
    - unresolved: entities with no consumer evidence anywhere in the lineage map
    """
    covered: list[str] = []
    indirectly_covered: list[str] = []
    not_covered: list[str] = []
    unresolved: list[dict[str, str]] = []

    all_direct_suites: set[str] = set()
    all_indirect_suites: set[str] = set()

    for entity in affected_api_entities:
        owner_token = _api_owner_token(entity)
        entity_key = normalize_member_hint(entity) if "." in str(entity) else compact_token(str(entity))
        direct_hits: set[str] = set()
        indirect_hits: set[str] = set()

        for project in project_results:
            project_name = str(project.get("project") or "").strip()
            direct_type_hints = {str(h).strip() for h in project.get("direct_type_hint_keys", []) if str(h).strip()}
            member_hints = {str(h).strip() for h in project.get("member_hint_keys", []) if str(h).strip()}
            if (owner_token and owner_token in direct_type_hints) or (entity_key and entity_key in member_hints):
                if project_name:
                    direct_hits.add(project_name)
                continue
            family_keys = {str(h).strip() for h in project.get("family_keys", []) if str(h).strip()}
            direct_family_keys = {str(h).strip() for h in project.get("direct_family_keys", []) if str(h).strip()}
            if owner_token and (owner_token in family_keys or owner_token in direct_family_keys):
                if project_name:
                    indirect_hits.add(project_name)

        if direct_hits:
            covered.append(entity)
            all_direct_suites.update(direct_hits)
        elif indirect_hits:
            indirectly_covered.append(entity)
            all_indirect_suites.update(indirect_hits)
        elif api_lineage_map is not None and not api_lineage_map.api_to_consumer_projects.get(entity):
            unresolved.append({"api_entity": entity, "reason": "no_consumer_evidence"})
        else:
            not_covered.append(entity)

    return {
        "covered": covered,
        "indirectly_covered": indirectly_covered,
        "not_covered": not_covered,
        "unresolved": unresolved,
        "direct_covering_suites": sorted(all_direct_suites),
        "indirectly_covering_suites": sorted(all_indirect_suites - all_direct_suites),
    }


def unresolved_reason(
    changed_file: Path,
    signals: dict[str, set[str]],
    project_results: list[dict],
) -> str | None:
    del changed_file
    return build_unresolved_analysis(signals, project_results)["reason"]


def emit_progress(enabled: bool, message: str) -> None:
    if not enabled:
        return
    print(f"phase: {message}", file=sys.stderr, flush=True)


def emit_subprogress(enabled: bool, prefix: str, message: str) -> None:
    if not enabled:
        return
    print(f"{prefix}: {message}", file=sys.stderr, flush=True)


def build_progress_callback(enabled: bool, changed_file_count: int = 0) -> Callable[[str], None] | None:
    if not enabled:
        return None
    if changed_file_count < PROGRESS_AGGREGATE_CHANGED_FILE_THRESHOLD:
        return lambda message: emit_progress(True, message)

    state = {"seen_changed_files": 0, "last_emitted_changed_file": 0}

    def _callback(message: str) -> None:
        if message.startswith("scoring changed file "):
            state["seen_changed_files"] += 1
            current = state["seen_changed_files"]
            should_emit = (
                current == 1
                or current == changed_file_count
                or (current - state["last_emitted_changed_file"]) >= PROGRESS_AGGREGATE_CHANGED_FILE_STEP
            )
            if should_emit:
                state["last_emitted_changed_file"] = current
                emit_progress(True, f"scoring changed files {current}/{changed_file_count}")
            return
        emit_progress(True, message)

    return _callback


def build_execution_progress_callback(enabled: bool) -> Callable[[dict[str, object]], None] | None:
    if not enabled:
        return None

    def _callback(event: dict[str, object]) -> None:
        kind = str(event.get("event") or "").strip()
        total = int(event.get("total") or 0)
        index = int(event.get("index") or event.get("completed") or 0)
        suite = str(event.get("suite") or "unknown-suite")
        device = str(event.get("device") or "default")
        tool = str(event.get("tool") or "-")
        estimated_duration = _format_duration_seconds(event.get("estimated_duration_s"))
        remaining_estimate = _format_duration_seconds(event.get("remaining_estimated_duration_s"))
        estimate_part = ""
        if estimated_duration != "-":
            estimate_part = f" est={estimated_duration}"
        remaining_part = ""
        if remaining_estimate != "-":
            remaining_part = f", batch_eta={remaining_estimate}"
        if kind == "started":
            print(
                f"phase: running {index}/{total} [{tool} {device}] {suite}{estimate_part}{remaining_part}",
                file=sys.stderr,
                flush=True,
            )
            return
        if kind == "completed":
            status = str(event.get("status") or "-")
            duration = _format_duration_seconds(event.get("duration_s"))
            duration_part = f" {duration}" if duration != "-" else ""
            summary = event.get("summary") if isinstance(event.get("summary"), dict) else {}
            case_summary = event.get("case_summary") if isinstance(event.get("case_summary"), dict) else {}
            counters = (
                f"passed={summary.get('passed', 0)} "
                f"failed={summary.get('failed', 0)} "
                f"blocked={summary.get('blocked', 0)} "
                f"timeout={summary.get('timeout', 0)} "
                f"unavailable={summary.get('unavailable', 0)} "
                f"skipped={summary.get('skipped', 0)}"
            )
            case_part = ""
            rendered_case = _format_case_summary(case_summary)
            if rendered_case != "-":
                case_part = f", suite_cases=({rendered_case})"
            print(
                f"phase: completed {index}/{total} [{tool} {device}] {suite} -> {status}{duration_part}{remaining_part} ({counters}{case_part})",
                file=sys.stderr,
                flush=True,
            )
            return
        if kind == "interrupted":
            completed = int(event.get("completed") or 0)
            print(
                f"phase: execution interrupted after {completed}/{total} completed target(s)",
                file=sys.stderr,
                flush=True,
            )

    return _callback


def _execution_artifact_rows(report: dict) -> list[list[str]]:
    rows: list[list[str]] = []
    for group in collect_unique_run_targets(report):
        target = group.get("representative", {})
        suite = _suite_label(target)
        candidates = list(target.get("execution_results") or []) or list(target.get("execution_plan") or [])
        for item in candidates:
            tool = str(item.get("selected_tool") or "-")
            device = str(item.get("device_label") or item.get("device") or "default")
            status = str(item.get("status") or "-")
            result_path = str(item.get("result_path") or "").strip()
            if result_path:
                rows.append([suite, device, tool, status, "result_path", result_path])
                summary_xml = Path(result_path).expanduser().resolve() / "summary_report.xml"
                if summary_xml.is_file():
                    rows.append([suite, device, tool, status, "summary_report_xml", str(summary_xml)])
                log_root = Path(result_path).expanduser().resolve() / "log"
                if log_root.is_dir():
                    for module_log in sorted(log_root.glob("**/module_run.log")):
                        rows.append([suite, device, tool, status, "module_run_log", str(module_log)])
    return rows


def write_execution_artifact_index(report: dict, output_dir: Path | None) -> Path | None:
    if output_dir is None:
        return None
    rows = _execution_artifact_rows(report)
    if not rows:
        return None
    target = output_dir.resolve() / "execution_artifacts.txt"
    lines = [
        f"Run Dir: {report.get('selector_run', {}).get('run_dir', '-')}",
        f"Report JSON: {report.get('json_output_path', '-')}",
        f"XDevice Reports Root: {report.get('execution_xdevice_reports_root', '-')}",
        "",
        "suite\tdevice\ttool\tstatus\tartifact_kind\tpath",
    ]
    lines.extend("\t".join(row) for row in rows)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _has_local_acts_artifacts(acts_out_root: Path | None) -> bool:
    if acts_out_root is None:
        return False
    root = acts_out_root.expanduser().absolute()
    testcases_dir = root / "testcases"
    if not testcases_dir.is_dir():
        return False
    return (testcases_dir / "module_info.list").is_file() or any(testcases_dir.glob("*.json"))


def _sync_prebuilt_acts_to_local_root(
    prepared: PreparedDailyPrebuilt | None,
    local_acts_root: Path | None,
    *,
    progress_enabled: bool,
) -> Path | None:
    if prepared is None or prepared.acts_out_root is None or local_acts_root is None:
        return None
    source = prepared.acts_out_root.expanduser().absolute()
    destination = local_acts_root.expanduser().absolute()
    if source == destination:
        return destination

    print(
        "warning: syncing downloaded ACTS artifacts to local output root and replacing existing contents: "
        f"{destination}",
        file=sys.stderr,
        flush=True,
    )
    emit_progress(progress_enabled, f"syncing acts artifacts to {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)

    extracted_root = prepared.extracted_root.expanduser().absolute()
    if extracted_root.exists() and extracted_root != destination:
        emit_progress(progress_enabled, f"cleaning extracted daily cache {extracted_root}")
        shutil.rmtree(extracted_root)
    return destination


def prepare_daily_prebuilt_from_config(app_config: AppConfig) -> PreparedDailyPrebuilt | None:
    if not app_config.daily_build_tag and not app_config.daily_date:
        return None
    build = resolve_daily_build(
        component=app_config.daily_component,
        build_tag=app_config.daily_build_tag,
        branch=app_config.daily_branch,
        build_date=app_config.daily_date,
        component_role="xts",
    )
    prepared = prepare_daily_prebuilt(
        build=build,
        cache_root=app_config.daily_cache_root or DEFAULT_DAILY_CACHE_ROOT,
    )
    app_config.daily_prebuilt = prepared
    if prepared.acts_out_root is not None:
        app_config.acts_out_root = prepared.acts_out_root
        app_config.daily_prebuilt_ready = True
        base_note = (
            f"Using prebuilt ACTS artifacts from daily build {prepared.build.tag} "
            f"({prepared.acts_out_root})."
        )
        prepared_note = getattr(prepared, "note", None)
        if prepared_note:
            base_note = f"{prepared_note} {base_note}"
        app_config.daily_prebuilt_note = base_note
    else:
        app_config.daily_prebuilt_ready = False
        app_config.daily_prebuilt_note = (
            f"Daily build {prepared.build.tag} was prepared, but no ACTS output root "
            "could be discovered under the extracted package."
        )
    return prepared


def prepare_daily_sdk_from_config(app_config: AppConfig) -> PreparedDailyArtifact:
    if not app_config.sdk_build_tag and not app_config.sdk_date:
        raise ValueError("sdk build tag or sdk date is required; provide --sdk-build-tag or --sdk-date")
    build = resolve_daily_build(
        component=app_config.sdk_component,
        build_tag=app_config.sdk_build_tag,
        branch=app_config.sdk_branch,
        build_date=app_config.sdk_date,
        component_role="generic",
    )
    return prepare_daily_sdk(
        build=build,
        cache_root=app_config.sdk_cache_root or DEFAULT_DAILY_CACHE_ROOT,
    )


def prepare_daily_firmware_from_config(app_config: AppConfig) -> PreparedDailyArtifact:
    if not app_config.firmware_build_tag and not app_config.firmware_date:
        raise ValueError("firmware build tag or firmware date is required; provide --firmware-build-tag or --firmware-date")
    try:
        build = resolve_daily_build(
            component=app_config.firmware_component,
            build_tag=app_config.firmware_build_tag,
            branch=app_config.firmware_branch,
            build_date=app_config.firmware_date,
            component_role="generic",
        )
    except FileNotFoundError as exc:
        build_date = app_config.firmware_date or derive_date_from_tag(app_config.firmware_build_tag)
        hint = (
            f"Run `ohos download firmware` to list recent firmware tags, or "
            f"`ohos download list-tags firmware --list-tags-count 20` for a longer list."
        )
        try:
            recent = list_daily_tags(
                component=app_config.firmware_component,
                branch=app_config.firmware_branch,
                count=5,
                before_date=build_date or None,
                lookback_days=14,
            )
        except Exception:
            recent = []
        if recent:
            recent_tags = ", ".join(build.tag for build in recent)
            raise FileNotFoundError(f"{exc}. Recent firmware tags: {recent_tags}. {hint}") from exc
        raise FileNotFoundError(f"{exc}. {hint}") from exc
    return prepare_daily_firmware(
        build=build,
        cache_root=app_config.firmware_cache_root or DEFAULT_DAILY_CACHE_ROOT,
    )


def resolve_local_firmware_root(path_value: Path) -> Path:
    candidate = path_value.expanduser().resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"firmware path does not exist: {candidate}")
    required = {"MiniLoaderAll.bin", "parameter.txt", "system.img"}
    if candidate.is_dir():
        try:
            names = {item.name for item in candidate.iterdir() if item.is_file()}
        except OSError as exc:
            raise ValueError(f"failed to inspect firmware path: {candidate}") from exc
        if required.issubset(names):
            return candidate
        discovered = discover_image_bundle_roots(candidate)
        if discovered:
            return discovered[0]
    raise ValueError(
        "firmware path must point to an unpacked image bundle root or a directory containing one"
    )


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
        date_range_note = f", date filter: {after_date or '...'} – {before_date or 'today'}"
    print(f"Listing {count} most recent {label} tags (component={component}, branch={branch}{date_range_note}):")
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
    written_json_path = write_json_report(report, json_to_stdout=json_to_stdout, json_output_path=json_output_path)
    if json_to_stdout:
        return
    print("utility_mode: daily_artifacts")
    operations = report.get("operations", {})
    for name, payload in operations.items():
        status = payload.get("status", "")
        print(f"{name}: {status}")
        if payload.get("error"):
            print(f"  error: {payload['error']}")
        for key in ("tag", "component", "role", "package_kind", "cache_root", "archive_path", "extracted_root", "primary_root"):
            value = payload.get(key)
            if value:
                print(f"  {key}: {value}")
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

    fixtures_dir = Path(args.benchmark_fixtures_dir) if args.benchmark_fixtures_dir else None
    if not fixtures_dir:
        fixtures_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "canonical_corpus"

    if not fixtures_dir.exists():
        print(f"error: benchmark fixtures directory not found: {fixtures_dir}", file=sys.stderr)
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
            results.append(BenchmarkResult(
                case_name=case.name,
                family=case.family,
                pass_fail=False,
                notes=f"SKIPPED: workspace not available for case {case.name!r}",
            ))
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
            results.append(BenchmarkResult(
                case_name=case.name,
                family=case.family,
                pass_fail=False,
                notes=f"ERROR: {exc}",
            ))

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
            print(f"    SKIPPED (no workspace)")
        if result.notes.startswith("ERROR"):
            print(f"    ERROR: {result.notes}")
        if result.notes.startswith("SKIPPED"):
            continue
        if not result.pass_fail:
            overall_pass = False

    print(f"\nTotal: {len(results)} cases, {'ALL PASS' if overall_pass else 'SOME FAILED'}")
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
            "consumer_files": sorted(lineage_map.api_to_consumer_files.get(entity, set())),
            "consumer_projects": sorted(lineage_map.api_to_consumer_projects.get(entity, set())),
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
            result["consumer_files"].extend(lineage_map.api_to_consumer_files.get(api, set()))
            result["consumer_projects"].extend(lineage_map.api_to_consumer_projects.get(api, set()))
        result["consumer_files"] = sorted(set(result["consumer_files"]))
        result["consumer_projects"] = sorted(set(result["consumer_projects"]))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.inspect_consumer_project:
        project = args.inspect_consumer_project
        result = {
            "consumer_project": project,
            "api_entities": sorted(lineage_map.consumer_project_to_apis.get(project, set())),
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
        emit_progress(progress_enabled, f"downloading daily tests {app_config.daily_build_tag or ''}".strip())
        try:
            prepared = prepare_daily_prebuilt_from_config(app_config)
            if prepared is None:
                raise ValueError("daily build tag is required; provide --daily-build-tag")
            report["operations"]["download_daily_tests"] = {
                **prepared.to_dict(),
                "role": "tests",
                "package_kind": "full",
                "status": "ready" if prepared.acts_out_root else "extracted",
                "primary_root": str(prepared.acts_out_root) if prepared.acts_out_root else "",
            }
        except (OSError, ValueError, FileNotFoundError, urllib.error.URLError) as exc:
            report["operations"]["download_daily_tests"] = {"status": "failed", "error": str(exc)}
            exit_code = 2

    firmware_prepared: PreparedDailyArtifact | None = None
    if args.download_daily_sdk:
        emit_progress(progress_enabled, f"downloading daily sdk {app_config.sdk_build_tag or ''}".strip())
        try:
            prepared_sdk = prepare_daily_sdk_from_config(app_config)
            report["operations"]["download_daily_sdk"] = prepared_sdk.to_dict()
        except (OSError, ValueError, FileNotFoundError, urllib.error.URLError) as exc:
            report["operations"]["download_daily_sdk"] = {"status": "failed", "error": str(exc)}
            exit_code = 2

    if args.download_daily_firmware or args.flash_daily_firmware:
        emit_progress(progress_enabled, f"downloading daily firmware {app_config.firmware_build_tag or ''}".strip())
        try:
            firmware_prepared = prepare_daily_firmware_from_config(app_config)
            report["operations"]["download_daily_firmware"] = firmware_prepared.to_dict()
        except (OSError, ValueError, FileNotFoundError, urllib.error.URLError) as exc:
            report["operations"]["download_daily_firmware"] = {"status": "failed", "error": str(exc)}
            exit_code = 2

    if args.flash_daily_firmware:
        emit_progress(progress_enabled, "flashing daily firmware")
        try:
            if firmware_prepared is None:
                raise ValueError("firmware package is not prepared")
            if firmware_prepared.primary_root is None:
                raise ValueError("no flashable image root was discovered in the firmware package")
            flash_result = flash_image_bundle(
                image_root=firmware_prepared.primary_root,
                flash_py_path=str(app_config.flash_py_path) if app_config.flash_py_path else None,
                hdc_path=str(app_config.hdc_path) if app_config.hdc_path else None,
                device=app_config.device,
                progress_callback=(lambda message: emit_subprogress(progress_enabled, "flash", message)),
            )
            report["operations"]["flash_daily_firmware"] = flash_result.to_dict()
            if flash_result.status != "completed":
                exit_code = max(exit_code, 1)
        except (OSError, ValueError, FileNotFoundError, RuntimeError, subprocess.TimeoutExpired) as exc:
            report["operations"]["flash_daily_firmware"] = {"status": "failed", "error": str(exc)}
            exit_code = max(exit_code, 2)

    if app_config.flash_firmware_path is not None:
        emit_progress(progress_enabled, f"flashing local firmware {app_config.flash_firmware_path}")
        try:
            image_root = resolve_local_firmware_root(app_config.flash_firmware_path)
            flash_result = flash_image_bundle(
                image_root=image_root,
                flash_py_path=str(app_config.flash_py_path) if app_config.flash_py_path else None,
                hdc_path=str(app_config.hdc_path) if app_config.hdc_path else None,
                device=app_config.device,
                progress_callback=(lambda message: emit_subprogress(progress_enabled, "flash", message)),
            )
            report["operations"]["flash_local_firmware"] = {
                **flash_result.to_dict(),
                "requested_path": str(app_config.flash_firmware_path),
            }
            if flash_result.status != "completed":
                exit_code = max(exit_code, 1)
        except (OSError, ValueError, FileNotFoundError, RuntimeError, subprocess.TimeoutExpired) as exc:
            report["operations"]["flash_local_firmware"] = {
                "status": "failed",
                "requested_path": str(app_config.flash_firmware_path),
                "error": str(exc),
            }
            exit_code = max(exit_code, 2)

    write_and_render_utility_report(report, json_to_stdout=json_to_stdout, json_output_path=json_output_path)
    return exit_code


def resolve_json_output_path(path_value: str | None) -> Path:
    if not path_value:
        return (Path.cwd() / DEFAULT_REPORT_FILE).resolve()
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def write_json_report(report: dict, json_to_stdout: bool, json_output_path: Path | None) -> Path | None:
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if json_to_stdout:
        print(payload)
        return None
    target = json_output_path or resolve_json_output_path(None)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    return target


def resolve_selected_tests_output_path(selector_report_path: Path | None) -> Path | None:
    if selector_report_path is None:
        return None
    return selector_report_path.resolve().with_name(SELECTED_TESTS_FILE_NAME)


def resolve_selected_tests_report_base_path(
    run_session: RunSession | None,
    json_output_path: Path | None,
) -> Path | None:
    if run_session is not None:
        return run_session.selector_report_path.resolve()
    if json_output_path is not None:
        return json_output_path.resolve()
    return None


def _selected_test_aliases(entry: dict[str, object]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    candidates = [
        entry.get("build_target"),
        entry.get("xdevice_module_name"),
        entry.get("project"),
        entry.get("test_json"),
        entry.get("target_key"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        for alias in (
            text,
            Path(text).stem,
            text.rstrip("/").rsplit("/", 1)[-1],
        ):
            normalized = alias.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            aliases.append(alias.strip())
    return aliases


def build_selected_tests_payload(report: dict, selector_report_path: Path | None) -> dict[str, object]:
    groups = collect_unique_run_targets(report)
    selected_keys = set(report.get("execution_overview", {}).get("selected_target_keys", []))
    requested_test_names = list(report.get("execution_overview", {}).get("requested_test_names", []))
    tests: list[dict[str, object]] = []
    for group in groups:
        representative = dict(group.get("representative", {}))
        tests.append(
            {
                "name": _suite_label(representative),
                "aliases": _selected_test_aliases(representative),
                "selected_by_default": group.get("key") in selected_keys,
                "build_target": representative.get("build_target"),
                "xdevice_module_name": representative.get("xdevice_module_name"),
                "artifact_status": representative.get("artifact_status", "unknown"),
                "artifact_reason": representative.get("artifact_reason", ""),
                "bucket": representative.get("bucket", ""),
                "scope_tier": representative.get("scope_tier", ""),
                "variant": representative.get("variant", ""),
                "project": representative.get("project", ""),
                "test_json": representative.get("test_json", ""),
                "target_key": group.get("key", ""),
            }
        )
    return {
        "selector_report_path": str(selector_report_path) if selector_report_path is not None else "",
        "available_target_count": len(groups),
        "selected_target_count": len(selected_keys),
        "requested_test_names": requested_test_names,
        "tests": tests,
    }


def write_selected_tests_report(report: dict, selector_report_path: Path | None) -> Path | None:
    target = resolve_selected_tests_output_path(selector_report_path)
    if target is None:
        return None
    payload = build_selected_tests_payload(report, selector_report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_selector_report(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"failed to load selector report {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"selector report {path} does not contain a JSON object")
    return payload


def resolve_selector_report_input(
    from_report: str | None,
    last_report: bool,
    run_store_root: Path,
) -> Path | None:
    if from_report:
        return resolve_json_output_path(from_report)
    if not last_report:
        return None
    manifest = resolve_latest_run(run_store_root)
    candidate = manifest.get("selector_report_path")
    if candidate:
        return Path(str(candidate)).expanduser().resolve()
    manifest_path = manifest.get("_manifest_path")
    if manifest_path:
        return Path(str(manifest_path)).expanduser().resolve().with_name("selector_report.json")
    raise FileNotFoundError(f"No selector report path was recorded in {run_store_root}")


def run_session_from_report(report: dict, report_path: Path) -> RunSession | None:
    selector_run = report.get("selector_run")
    if not isinstance(selector_run, dict):
        return None
    label = str(selector_run.get("label") or "").strip()
    if not label:
        return None
    label_key = str(selector_run.get("label_key") or normalize_run_label(label))
    timestamp = str(selector_run.get("timestamp") or report_path.parent.name or "")
    run_dir_value = selector_run.get("run_dir")
    report_value = selector_run.get("selector_report_path")
    manifest_value = selector_run.get("manifest_path")
    run_dir = Path(str(run_dir_value)).expanduser().resolve() if run_dir_value else report_path.parent.resolve()
    selector_report_path = Path(str(report_value)).expanduser().resolve() if report_value else report_path.resolve()
    manifest_path = (
        Path(str(manifest_value)).expanduser().resolve()
        if manifest_value
        else (run_dir / "run_manifest.json").resolve()
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunSession(
        label=label,
        label_key=label_key,
        timestamp=timestamp,
        run_dir=run_dir,
        selector_report_path=selector_report_path,
        manifest_path=manifest_path,
    )


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
    product_build = inspect_product_build(REPO_ROOT, app_config.product_name, acts_out_root)
    report = {
        "repo_root": str(REPO_ROOT),
        "xts_root": str(xts_root),
        "sdk_api_root": str(sdk_api_root),
        "git_repo_root": str(git_repo_root),
        "acts_out_root": str(acts_out_root or (REPO_ROOT / "out/release/suites/acts")),
        "cache_file": str(app_config.cache_file) if app_config.cache_file else None,
        "ranking_rules_file": str(app_config.ranking_rules_file) if app_config.ranking_rules_file else None,
        "runtime_state_root": str(app_config.runtime_state_root) if app_config.runtime_state_root else None,
        "runtime_history_file": str(default_runtime_history_file(app_config.runtime_state_root)),
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
                1 for kind in api_lineage_map.consumer_file_kinds.values() if kind == "source_only"
            ),
            "source_only_consumer_project_count": sum(
                1 for kind in api_lineage_map.consumer_project_kinds.values() if kind == "source_only"
            ),
        }
    coverage_candidates: list[dict[str, object]] = []
    report["timings_ms"]["report_setup"] = round((time.perf_counter() - setup_started) * 1000, 3)
    selected_build_targets: list[str] = []
    changed_started = time.perf_counter()
    for changed_file in changed_files:
        if progress_callback:
            progress_callback(f"scoring changed file {repo_rel(changed_file)}")
        rel = repo_rel(changed_file)
        changed_ranges = list((changed_ranges_by_file or {}).get(changed_file.resolve(), []))
        signals = infer_signals(
            changed_file,
            sdk_index,
            content_index,
            mapping_config,
            changed_ranges=changed_ranges,
            api_lineage_map=api_lineage_map,
            repo_root=app_config.repo_root,
        )
        affected_api_entities, file_level_affected_api_entities, derived_source_symbols = apply_api_lineage_signals(
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
            source_profile["changed_ranges"] = [f"{start}:{end}" for start, end in changed_ranges]
        if derived_source_symbols:
            source_profile["derived_source_symbols"] = derived_source_symbols
        if file_level_affected_api_entities != affected_api_entities:
            source_profile["file_level_affected_api_entities"] = file_level_affected_api_entities
        project_results = []
        all_variant_projects, candidate_projects = select_candidate_projects(
            projects,
            signals,
            effective_variants_mode,
        )
        for project in candidate_projects:
            score, project_reasons, file_hits = score_project(project, signals)
            if score <= 0:
                continue
            if not should_keep_project_for_surface(project, file_hits, effective_variants_mode):
                continue
            hit_surfaces = sorted(matched_file_surfaces(file_hits))
            _nlx = project_has_non_lexical_evidence(project_reasons, file_hits)
            _bucket = candidate_bucket(score, _nlx)
            scope_tier, specificity_score, scope_reasons = classify_project_scope(
                project,
                signals,
                project_reasons,
                file_hits,
            )
            family_profile = infer_project_family_profile(project, project_reasons, file_hits)
            type_hint_profile = infer_project_type_hint_profile(file_hits, signals)
            member_hint_profile = infer_project_member_hint_profile(file_hits, signals)
            project_entry = {
                # Only 'possible related' suites (call-only, no explicit import)
                # are eligible for coverage deduplication. Must-run and
                # high-confidence suites always pass through so that every
                # explicitly-tested suite is preserved regardless of keep_per_signature.
                "_coverage_sig": coverage_signature(file_hits, project_path_key=project.path_key) if _bucket == "possible related" else None,
                "score": score,
                "specificity_score": specificity_score,
                "scope_tier": scope_tier,
                "scope_reasons": scope_reasons if debug_trace else scope_reasons[:3],
                "confidence": confidence(score),
                "bucket": _bucket,
                "variant": project.variant,
                "surface": project.surface,
                "supported_surfaces": sorted(project.supported_surfaces),
                "matched_surfaces": hit_surfaces,
                "project": project.relative_root,
                "test_json": project.test_json,
                "bundle_name": project.bundle_name,
                "driver_module_name": driver_module_name(project.test_json, repo_root=app_config.repo_root),
                "xdevice_module_name": infer_xdevice_module_name(project.test_json, repo_root=app_config.repo_root),
                "build_target": guess_build_target(project.relative_root),
                "driver_type": driver_type(project.test_json, repo_root=app_config.repo_root),
                "family_keys": family_profile["family_keys"],
                "direct_family_keys": family_profile["direct_family_keys"],
                "family_quality": family_profile["family_quality"],
                "family_representative_quality": family_profile["family_representative_quality"],
                "capability_keys": family_profile["capability_keys"],
                "direct_capability_keys": family_profile["direct_capability_keys"],
                "capability_quality": family_profile["capability_quality"],
                "capability_representative_quality": family_profile["capability_representative_quality"],
                "type_hint_keys": type_hint_profile["type_hint_keys"],
                "direct_type_hint_keys": type_hint_profile["direct_type_hint_keys"],
                "type_hint_focus_counts": type_hint_profile["focus_token_counts"],
                "member_hint_keys": member_hint_profile["member_hint_keys"],
                "direct_member_hint_keys": member_hint_profile["direct_member_hint_keys"],
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
            project_results.append(project_entry)
        sort_project_results(project_results)
        project_results = deduplicate_by_coverage_signature(project_results, keep_per_signature)
        filtered_project_results, relevance_summary = filter_project_results_by_relevance(project_results, relevance_mode)
        shown_project_results = filtered_project_results if top_projects <= 0 else filtered_project_results[:top_projects]
        coverage_source = make_coverage_source("changed_file", rel)
        coverage_candidates.extend(
            {
                "source": coverage_source,
                "source_profile": source_profile,
                "project_entry": item,
                "source_rank": index,
            }
            for index, item in enumerate(filtered_project_results, start=1)
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
            row["symbol"] for row in function_coverage
            if row.get("status") not in {"covered", "indirectly_covered"}
        ]
        uncovered_apis = (
            api_coverage["not_covered"]
            + [e["api_entity"] for e in api_coverage["unresolved"]]
        )
        result_item = {
            "changed_file": rel,
            "changed_symbols": sorted(changed_symbols or []),
            "changed_ranges": [f"{start}:{end}" for start, end in changed_ranges],
            "derived_source_symbols": derived_source_symbols,
            "touched_source_functions": derived_source_symbols,
            "affected_api_entities": affected_api_entities,
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
        selected_build_targets.extend(guess_build_target(item["project"]) for item in shown_project_results)
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
        report["results"].append(result_item)
    report["timings_ms"]["changed_file_analysis"] = round((time.perf_counter() - changed_started) * 1000, 3)
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
        for project in candidate_projects:
            score, project_reasons, file_hits = score_project(project, signals)
            if score <= 0:
                continue
            if not should_keep_project_for_surface(project, file_hits, effective_variants_mode):
                continue
            hit_surfaces = sorted(matched_file_surfaces(file_hits))
            _nlx = project_has_non_lexical_evidence(project_reasons, file_hits)
            _bucket = candidate_bucket(score, _nlx)
            scope_tier, specificity_score, scope_reasons = classify_project_scope(
                project,
                signals,
                project_reasons,
                file_hits,
            )
            family_profile = infer_project_family_profile(project, project_reasons, file_hits)
            type_hint_profile = infer_project_type_hint_profile(file_hits, signals)
            member_hint_profile = infer_project_member_hint_profile(file_hits, signals)
            project_entry = {
                "_coverage_sig": coverage_signature(file_hits, project_path_key=project.path_key) if _bucket == "possible related" else None,
                "score": score,
                "specificity_score": specificity_score,
                "scope_tier": scope_tier,
                "scope_reasons": scope_reasons if debug_trace else scope_reasons[:3],
                "confidence": confidence(score),
                "bucket": _bucket,
                "variant": project.variant,
                "surface": project.surface,
                "supported_surfaces": sorted(project.supported_surfaces),
                "matched_surfaces": hit_surfaces,
                "project": project.relative_root,
                "test_json": project.test_json,
                "bundle_name": project.bundle_name,
                "driver_module_name": driver_module_name(project.test_json, repo_root=app_config.repo_root),
                "xdevice_module_name": infer_xdevice_module_name(project.test_json, repo_root=app_config.repo_root),
                "build_target": guess_build_target(project.relative_root),
                "driver_type": driver_type(project.test_json, repo_root=app_config.repo_root),
                "test_haps": parse_test_file_names(project.test_json, repo_root=app_config.repo_root),
                "family_keys": family_profile["family_keys"],
                "direct_family_keys": family_profile["direct_family_keys"],
                "family_quality": family_profile["family_quality"],
                "family_representative_quality": family_profile["family_representative_quality"],
                "capability_keys": family_profile["capability_keys"],
                "direct_capability_keys": family_profile["direct_capability_keys"],
                "capability_quality": family_profile["capability_quality"],
                "capability_representative_quality": family_profile["capability_representative_quality"],
                "type_hint_keys": type_hint_profile["type_hint_keys"],
                "direct_type_hint_keys": type_hint_profile["direct_type_hint_keys"],
                "type_hint_focus_counts": type_hint_profile["focus_token_counts"],
                "member_hint_keys": member_hint_profile["member_hint_keys"],
                "direct_member_hint_keys": member_hint_profile["direct_member_hint_keys"],
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
            project_results.append(project_entry)
        sort_project_results(project_results)
        project_results = deduplicate_by_coverage_signature(project_results, keep_per_signature)
        filtered_project_results, relevance_summary = filter_project_results_by_relevance(project_results, relevance_mode)
        display_project_results = restrict_explicit_surface_projects(
            filtered_project_results,
            query_surface_intent.requested_surface,
            explicit_surface_query=bool(query_surface_intent.reasons),
        )
        shown_project_results = display_project_results if top_projects <= 0 else display_project_results[:top_projects]
        if effective_variants_mode == "both":
            shown_project_results = diversify_symbol_query_projects(display_project_results, top_projects)
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
        report["symbol_queries"].append(symbol_item)
        selected_build_targets.extend(guess_build_target(item["project"]) for item in shown_project_results)
    report["timings_ms"]["symbol_query_analysis"] = round((time.perf_counter() - symbol_started) * 1000, 3)
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
    report["timings_ms"]["code_query_analysis"] = round((time.perf_counter() - code_started) * 1000, 3)
    report["coverage_recommendations"] = build_global_coverage_recommendations(
        coverage_candidates,
        repo_root=REPO_ROOT,
        acts_out_root=acts_out_root,
        built_artifact_index=built_artifact_index,
        device=device,
    )
    if runtime_history_index is not None:
        annotate_report_runtime_estimates(report, runtime_history_index, requested_tool=requested_run_tool)
    if progress_callback:
        progress_callback("assembling build guidance")
    guidance_started = time.perf_counter()
    guidance = build_guidance(REPO_ROOT, report["built_artifacts"], report["product_build"], app_config, selected_build_targets)
    report["timings_ms"]["build_guidance"] = round((time.perf_counter() - guidance_started) * 1000, 3)
    if guidance:
        report["build_guidance"] = guidance
    report["timings_ms"]["report_total"] = round(sum(report["timings_ms"].values()), 3)
    return report


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


def _human_console() -> Console:
    stream = sys.stdout
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    width = shutil.get_terminal_size((120, 40)).columns if is_tty else 120
    return Console(
        file=stream,
        force_terminal=False,
        no_color=True,
        highlight=False,
        soft_wrap=False,
        width=width,
    )


def _add_table_column(table: Table, header: str) -> None:
    title = _human_value(header)
    compact = compact_token(title)
    kwargs: dict[str, object] = {"overflow": "fold", "vertical": "top"}
    if compact in {"#", "sel", "score", "rc"}:
        kwargs.update({"justify": "right", "no_wrap": True, "width": 3})
    elif compact in {"variant", "bucket", "confidence", "status", "tool", "device", "step", "priority"}:
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


def _print_human_table(headers: list[str], rows: list[list[object]] | list[tuple[object, ...]], indent: int = 0) -> None:
    console = _human_console()
    table = Table(
        box=box.ROUNDED,
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
    renderable = Padding(table, (0, 0, 0, indent)) if indent else table
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
        title_text = _single_line_comment_text(item.get("label") or item.get("step") or item.get("title"))
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


def _wrapper_or_direct_command_tokens(wrapper_subcommand: str | None = None) -> list[object]:
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


def _showing_summary_text(relevance_summary: dict[str, object], shown_count: int) -> str:
    shown = int(relevance_summary.get("shown", shown_count))
    total_after = int(relevance_summary.get("total_after", shown_count))
    total_before = int(relevance_summary.get("total_before", total_after))
    filtered_out = int(relevance_summary.get("filtered_out", max(total_before - total_after, 0)))
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


def _daily_selector_arg(flag: str, build_tag: str | None, build_date: str | None) -> list[str]:
    normalized_tag = str(build_tag or "").strip()
    normalized_date = str(build_date or "").strip() or derive_date_from_tag(normalized_tag)
    if normalized_tag:
        result = [flag, normalized_tag]
        if normalized_date:
            result.extend([flag.replace("build-tag", "date"), normalized_date])
        return result
    return [flag.replace("build-tag", "date"), normalized_date or "<YYYYMMDD>"]


@lru_cache(maxsize=32)
def _latest_daily_selector_metadata(component: str, branch: str, component_role: str) -> tuple[str, str]:
    normalized_component = str(component or "").strip()
    normalized_branch = str(branch or "").strip() or "master"
    candidates = daily_component_candidates(normalized_component, component_role=component_role)
    newest_tag = ""
    newest_date = ""
    for candidate in candidates:
        try:
            builds = list_daily_tags(component=candidate, branch=normalized_branch, count=1)
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
    normalized_tag = "" if is_placeholder_metadata(build_tag) else str(build_tag or "").strip()
    normalized_date = "" if is_placeholder_metadata(build_date) else str(build_date or "").strip()
    if not normalized_tag and not normalized_date:
        normalized_tag, normalized_date = _latest_daily_selector_metadata(component, branch, component_role)
    return _daily_selector_arg(flag, normalized_tag or None, normalized_date or None)


def _cache_state_text(cache_used: bool, cache_file: object | None) -> str:
    state = "hit" if cache_used else "miss"
    if cache_file:
        return f"{state} ({cache_file})"
    return state


def _preparation_summary(report: dict) -> str:
    built = report.get("built_artifacts", {})
    daily_prebuilt = report.get("daily_prebuilt", {})
    has_acts = bool(built.get("testcases_dir_exists")) and bool(built.get("module_info_exists"))
    if has_acts or daily_prebuilt.get("acts_out_root"):
        return "ready"
    return "missing"


def _base_selector_run_command(report: dict, app_config: AppConfig, args: argparse.Namespace) -> list[object]:
    if _uses_wrapper_commands():
        run_command: list[object] = _wrapper_or_direct_command_tokens("run")
    else:
        run_command = [*_wrapper_or_direct_command_tokens(), "--repo-root", app_config.repo_root]
    selector_report_path = str(report.get("selector_run", {}).get("selector_report_path", "")).strip()
    if selector_report_path:
        run_command.extend(["--from-report", selector_report_path])
    else:
        for changed_file in args.changed_file:
            run_command.extend(["--changed-file", changed_file])
        for changed_symbol in getattr(args, "changed_symbol", []):
            run_command.extend(["--changed-symbol", changed_symbol])
        for changed_range in getattr(args, "changed_range", []):
            run_command.extend(["--changed-range", changed_range])
        for symbol_query in args.symbol_query:
            run_command.extend(["--symbol-query", symbol_query])
        for code_query in args.code_query:
            run_command.extend(["--code-query", code_query])
        if args.changed_files_from:
            run_command.extend(["--changed-files-from", args.changed_files_from])
        if args.git_diff:
            run_command.extend(["--git-diff", args.git_diff])
        if args.pr_url:
            run_command.extend(["--pr-url", args.pr_url])
        if args.pr_number:
            run_command.extend(["--pr-number", args.pr_number])
        if args.pr_source != "auto":
            run_command.extend(["--pr-source", args.pr_source])
        if getattr(args, "git_host_kind", "auto") != "auto":
            run_command.extend(["--git-host-kind", args.git_host_kind])
        if args.git_host_config:
            run_command.extend(["--git-host-config", args.git_host_config])
        if getattr(args, "git_host_url", None):
            run_command.extend(["--git-host-url", args.git_host_url])
        if args.gitcode_api_url:
            run_command.extend(["--gitcode-api-url", args.gitcode_api_url])
        run_command.extend(["--variants", args.variants, "--relevance-mode", args.relevance_mode])
        if args.top_projects > 0:
            run_command.extend(["--top-projects", args.top_projects])
        if args.keep_per_signature:
            run_command.extend(["--keep-per-signature", args.keep_per_signature])
    if app_config.runtime_state_root and app_config.runtime_state_root != default_runtime_state_root():
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


def _repeat_this_run_command_tokens(report: dict, app_config: AppConfig, args: argparse.Namespace) -> list[object]:
    """Shell tokens to replay the current run: same report, devices, HDC, and run flags."""
    command = list(_base_selector_run_command(report, app_config, args))
    if not _uses_wrapper_commands():
        command.append("--run-now")
    command.extend(["--run-tool", str(getattr(args, "run_tool", "auto") or "auto")])
    command.extend(["--run-priority", str(getattr(args, "run_priority", "recommended") or "recommended")])
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
    run_label = str(getattr(args, "run_label", None) or "").strip() or str(getattr(app_config, "run_label", None) or "").strip()
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


def _build_compare_command(base_label: str, target_label: str, run_store_root: Path | None) -> str:
    if _uses_wrapper_commands():
        return _shell_join([*_wrapper_or_direct_command_tokens("compare"), base_label, target_label])
    resolved_run_store = (run_store_root or default_run_store_root(PROJECT_ROOT)).resolve()
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


def _find_compare_base_label(run_store_root: Path | None, current_label: str | None) -> str | None:
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


def build_coverage_run_commands(report: dict, app_config: AppConfig, args: argparse.Namespace) -> list[dict[str, str]]:
    coverage = report.get("coverage_recommendations", {})
    commands: list[dict[str, str]] = []
    for priority, label, why in (
        ("required", "Run required batch", "Only strongest unique coverage."),
        ("recommended", "Run recommended batch", "Strong plus additional unique coverage."),
        ("all", "Run full batch", "Includes duplicate fallback coverage."),
    ):
        target_count = _run_priority_target_count(coverage, priority)
        command = _base_selector_run_command(report, app_config, args)
        if not _uses_wrapper_commands():
            command.append("--run-now")
        if args.run_tool != "auto":
            command.extend(["--run-tool", args.run_tool])
        command.extend(["--run-priority", priority])
        if target_count > 0:
            command.extend(["--run-top-targets", target_count])
        if args.parallel_jobs > 1:
            command.extend(["--parallel-jobs", args.parallel_jobs])
        if app_config.shard_mode != "mirror":
            command.extend(["--shard-mode", app_config.shard_mode])
        if args.run_timeout > 0:
            command.extend(["--run-timeout", args.run_timeout])
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


def build_next_steps(report: dict, app_config: AppConfig, args: argparse.Namespace) -> list[dict[str, str]]:
    sdk_root_value = str(report.get("sdk_api_root") or "").strip()
    sdk_root_exists = bool(sdk_root_value) and Path(sdk_root_value).exists()
    run_only_flow = bool(getattr(args, "from_report", None) or getattr(args, "last_report", False))
    built_artifacts = report.get("built_artifacts", {})
    has_acts_artifacts = bool(built_artifacts.get("testcases_dir_exists")) and bool(built_artifacts.get("module_info_exists"))
    daily_prebuilt_ready = bool(getattr(app_config, "daily_prebuilt_ready", False))
    coverage = report.get("coverage_recommendations", {})
    selector_run = report.get("selector_run", {}) if isinstance(report.get("selector_run"), dict) else {}
    current_run_label = str(selector_run.get("label") or app_config.run_label or "").strip()
    required_target_count = len(coverage.get("required_target_keys", []))
    recommended_target_count = len(coverage.get("recommended_target_keys", []))
    selected_targets = int(report.get("execution_overview", {}).get("selected_target_count", 0))
    run_blocked = recommended_target_count <= 0 or (not has_acts_artifacts and not daily_prebuilt_ready)
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
                "step": "Switch SDK For Selection" if sdk_root_exists else "Download SDK For Selection",
                "status": "optional",
                "why": (
                    "Optional: use this only to rescore the selector against another SDK build. It is not required to run selected tests."
                    if sdk_root_exists
                    else "Optional: adding an SDK can improve selector matching for ArkUI API symbols, but it is not required to execute selected tests."
                ),
                "command": _shell_join(
                    [
                        *(_wrapper_download_command_tokens("sdk") if _uses_wrapper_commands() else _wrapper_or_direct_command_tokens(None)),
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
            "status": "recommended" if not has_acts_artifacts and not daily_prebuilt_ready else "optional",
            "why": (
                "ACTS artifacts are missing."
                if not has_acts_artifacts and not daily_prebuilt_ready
                else "Use this to switch to another prebuilt test package."
            ),
            "command": _shell_join(
                [
                    *(_wrapper_download_command_tokens("tests") if _uses_wrapper_commands() else _wrapper_or_direct_command_tokens(None)),
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
                    *(_wrapper_download_command_tokens("firmware") if _uses_wrapper_commands() else _wrapper_or_direct_command_tokens(None)),
                    *([] if _uses_wrapper_commands() else ["--download-daily-firmware"]),
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
                    *(_wrapper_device_flash_command_tokens() if _uses_wrapper_commands() else _wrapper_or_direct_command_tokens(None)),
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
        ("required", "Run required tests", required_target_count, f"{required_target_count} strongest unique target(s) are ready to run."),
        ("recommended", "Run recommended tests", recommended_target_count, f"{recommended_target_count} unique target(s) are ready to run."),
        ("all", "Run all coverage", _run_priority_target_count(coverage, "all"), f"{_run_priority_target_count(coverage, 'all')} total target(s), including duplicates, are ready to run."),
    ):
        command = _base_selector_run_command(report, app_config, args)
        if not _uses_wrapper_commands():
            command.append("--run-now")
        if args.run_tool != "auto":
            command.extend(["--run-tool", args.run_tool])
        command.extend(["--run-priority", priority])
        if count > 0:
            command.extend(["--run-top-targets", count])
        if args.parallel_jobs > 1:
            command.extend(["--parallel-jobs", args.parallel_jobs])
        if app_config.shard_mode != "mirror":
            command.extend(["--shard-mode", app_config.shard_mode])
        if args.run_timeout > 0:
            command.extend(["--run-timeout", args.run_timeout])
        steps.append(
            {
                "step": label,
                "status": "blocked" if run_blocked or count <= 0 else "ready",
                "why": run_block_reason if run_blocked else (why if count > 0 else "No targets available in this priority tier."),
                "command": _shell_join(command),
            }
        )
    compare_base_label = _find_compare_base_label(app_config.run_store_root, current_run_label)
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
                "command": _build_compare_command(compare_base_label, current_run_label, app_config.run_store_root),
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
        if str((result.get("source_profile") or result.get("source") or {}).get("type", "")) == "changed_file"
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
    est_required = _format_duration_seconds(coverage.get("estimated_required_duration_s"))
    est_recommended = _format_duration_seconds(coverage.get("estimated_recommended_duration_s"))
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

    total_suites = len(required_targets) + len(recommended_targets) + len(optional_targets)
    if total_suites > 0:
        total_duration = est_all if est_all != "-" else (est_recommended if est_recommended != "-" else "-")
        duration_note = f", {total_duration} estimated" if total_duration != "-" else ""
        suite_suffix = "s" if total_suites != 1 else ""
        print(f"TESTS TO RUN ({total_suites} suite{suite_suffix}{duration_note})")
        print(thin_separator)
        print(f" {'Priority':<10}  {'Suites':>6}  {'Est. Time':>10}")
        print(f" {'─' * 10}  {'─' * 6}  {'─' * 10}")
        if required_targets:
            print(f" {'MUST RUN':<10}  {len(required_targets):>6}  {est_required:>10}")
        if recommended_targets:
            high_duration = est_recommended if est_recommended != "-" and not required_targets else "-"
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


def print_human(report: dict, cache_used: bool | None = None, json_report_path: Path | None = None) -> None:
    selected_tests_json_path = str(report.get("selected_tests_json_path", "")).strip()
    unique_run_targets = collect_unique_run_targets(report)
    selected_target_count = len(report.get("execution_overview", {}).get("selected_target_keys", []))
    compact_changed_file_sections = len(report.get("results", [])) >= HUMAN_COMPACT_CHANGED_FILE_THRESHOLD

    def _selected_run_target_groups() -> list[dict]:
        selected_keys = {
            str(item).strip()
            for item in report.get("execution_overview", {}).get("selected_target_keys", [])
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
            summary_rows.append(("Execution Artifact Index", report["execution_artifact_index_path"]))
        if report.get("execution_xdevice_reports_root"):
            summary_rows.append(("XDevice Reports Root", report["execution_xdevice_reports_root"]))
        requested_names = list(report.get("execution_overview", {}).get("requested_test_names", []))
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
            display_limit = HUMAN_RUN_TARGET_DISPLAY_LIMIT if len(selected_groups) > HUMAN_RUN_TARGET_DISPLAY_LIMIT else None
            display_groups = selected_groups[:display_limit] if display_limit else selected_groups
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
                        or ("selected" if target.get("selected_for_execution") else "pending"),
                    ]
                )
            _print_human_table(["#", "Suite", "Artifacts", "Tool", "Device", "Status"], test_rows, indent=2)
            print()
            if display_limit and len(selected_groups) > display_limit:
                note_rows: list[tuple[object, object]] = [
                    ("Visible", f"{display_limit} of {len(selected_groups)}"),
                    ("Note", "Full selected suite list remains in selected_tests.json."),
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
                execution_rows.append(("preflight_errors", _human_preview(preflight.get("errors", [])[:5], limit=5)))
            if preflight.get("warnings"):
                execution_rows.append(("preflight_warnings", _human_preview(preflight.get("warnings", [])[:5], limit=5)))
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
                        "-" if result.get("returncode") is None else result.get("returncode"),
                        _format_case_summary(result.get("case_summary")),
                        result.get("result_path") or "-",
                    ]
                )
        if result_rows:
            print("Execution Results")
            _print_human_table(
                ["#", "Suite", "Device", "Status", "Tool", "Duration", "RC", "Case Summary", "Result Path"],
                result_rows,
                indent=2,
            )
            print()
        if plan_rows and (not result_rows or report.get("execution_interrupted")):
            print("Execution Plan" if not report.get("execution_interrupted") else "Remaining Execution Plan")
            _print_human_table(
                ["#", "Suite", "Device", "Status", "Tool", "Reason"],
                plan_rows,
                indent=2,
            )
            print()

        next_steps = list(report.get("next_steps") or [])
        if next_steps:
            status_rank = {"recommended": 0, "ready": 1, "follow-up": 2, "optional": 3, "blocked": 4}

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
        recommended_additional_targets = list(recommendations.get("recommended_additional", []))
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

        def _coverage_label_items(target: dict[str, object], primary_only: bool) -> list[str]:
            capabilities = list(target.get("new_capabilities" if primary_only else "covered_capabilities", []))
            if capabilities:
                return [str(item) for item in capabilities if str(item).strip()]
            families = list(target.get("new_families" if primary_only else "covered_families", []))
            if families:
                return [str(item) for item in families if str(item).strip()]
            sources = target.get("new_sources" if primary_only else "covered_sources", [])
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
            ("Est. Required", _format_duration_seconds(recommendations.get("estimated_required_duration_s"))),
            ("Est. Recommended", _format_duration_seconds(recommendations.get("estimated_recommended_duration_s"))),
            ("Est. Full", _format_duration_seconds(recommendations.get("estimated_all_duration_s"))),
        ]
        uncovered_sources = recommendations.get("uncovered_sources", [])
        unavailable_targets = list(recommendations.get("unavailable_targets", []))
        if uncovered_sources:
            coverage_rows.append(
                (
                    "Uncovered",
                    _human_preview(
                        [f"{item.get('type')}={item.get('value')}" for item in uncovered_sources],
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
                ]
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
            display_targets = targets[:display_limit] if display_limit and display_limit > 0 else targets
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
                        _human_preview(_coverage_label_items(target, primary_only=True), limit=4),
                        target.get("coverage_reason", "-"),
                    ]
                )
            _print_human_table(
                ["#", "Suite", "New Coverage", "Total Coverage", "Scope", "Surface", "Priority", "Est.", "Covers", "Why First"],
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
        _print_coverage_group("Recommended Additional Coverage", recommended_additional_targets)
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
                    item.get("build_target") or item.get("xdevice_module_name") or item.get("project") or "-",
                    item.get("artifact_reason") or "-",
                ]
                for index, item in enumerate(unavailable_targets, start=1)
            ]
            _print_human_table(["#", "Suite", "Why Skipped"], rows, indent=2)
            print()

    def print_run_targets(targets: list[dict], relevance_summary: dict[str, object] | None = None) -> None:
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
            display_limit = HUMAN_RUN_TARGET_DISPLAY_LIMIT if len(grouped_targets) > HUMAN_RUN_TARGET_DISPLAY_LIMIT else None
            display_targets = grouped_targets[:display_limit] if display_limit else grouped_targets
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
                            ([target.get("artifact_reason")] if target.get("artifact_status") == "missing" else [])
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
                            "-" if result.get("returncode") is None else result.get("returncode"),
                            _format_case_summary(result.get("case_summary")),
                            _tail_hint(result),
                            result.get("result_path") or "-",
                        ]
                    )
            _print_human_table(
                ["#", "Suite", "Artifacts", "Scope", "Surface", "Priority", "Est.", "Why First", "Project"],
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
            missing_targets = [target for target in grouped_targets if str(target.get("artifact_status") or "") == "missing"]
            if missing_targets:
                _print_actionable_command_list(
                    "Unavailable Suites",
                    [
                        {
                            "label": _suite_label(target),
                            "why": target.get("artifact_reason") or "suite is absent from the active ACTS artifacts",
                            "command": "",
                        }
                        for target in missing_targets
                    ],
                )
            show_plan = bool(result_rows) or any(row[2] != "pending" for row in plan_rows)
            if plan_rows and show_plan:
                print("Execution Plan")
                _print_human_table(["#", "Device", "Status", "Tool", "Available", "Reason", "Result Path"], plan_rows, indent=2)
                print()
            if result_rows:
                print("Execution Results")
                _print_human_table(["#", "Device", "Status", "Tool", "Duration", "RC", "Case Summary", "Hint", "Result Path"], result_rows, indent=2)
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
        def _print_project_group(group_title: str, grouped_projects: list[dict]) -> None:
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
                _print_human_table(["#", "Project", "File Score", "File", "Why It Matched"], file_rows, indent=2)
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
                ("selector_run", f"label={selector_run.get('label', '-')}, status={selector_run.get('status', '-')}, run_dir={selector_run.get('run_dir', '-')}"),
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
            command_rows.append(["product", guidance.get("full_code_build_command", "-")])
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
                ]
            )

    next_steps = report.get("next_steps", [])
    if next_steps:
        status_rank = {"recommended": 0, "ready": 1, "follow-up": 2, "optional": 3, "blocked": 4}

        def _next_step_sort_key_main(item: dict[str, object]) -> tuple[object, ...]:
            step = str(item.get("step", ""))
            prefix = 0 if step == "Repeat this run" else 1
            return (prefix, status_rank.get(str(item.get("status", "")), 99), step)

        ordered_next_steps = sorted(next_steps, key=_next_step_sort_key_main)
        _print_actionable_command_list("Next Steps", ordered_next_steps)

    if unique_run_targets:
        runnable_inventory_count = sum(1 for group in unique_run_targets if _run_target_has_inventory(group))
        unavailable_inventory_count = max(len(unique_run_targets) - runnable_inventory_count, 0)
        runnable_rows: list[tuple[object, object]] = [
            ("Selected Inventory Entries", len(unique_run_targets)),
            ("Selected By Analysis", selected_target_count),
            ("Runnable In Current Inventory", runnable_inventory_count),
            (
                "Meaning",
                "\"Runnable Tests\" is shorthand only: selection comes from source/API analysis, and actual execution still depends on the current ACTS/build artifacts.",
            ),
            ("Manual Selection", "Use --run-test-name <name> or --run-test-names-file <file> with the run command."),
        ]
        if unavailable_inventory_count > 0:
            runnable_rows.append(("Unavailable In Current Inventory", unavailable_inventory_count))
        if selected_tests_json_path:
            runnable_rows.append(("JSON", selected_tests_json_path))
        requested_names = list(report.get("execution_overview", {}).get("requested_test_names", []))
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
            execution_rows.append(("preflight_errors", _human_preview(preflight.get("errors", [])[:5], limit=5)))
        if preflight.get("warnings"):
            execution_rows.append(("preflight_warnings", _human_preview(preflight.get("warnings", [])[:5], limit=5)))
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
        _print_human_table(["Metric", "Value"], [[key, value] for key, value in timings.items()], indent=2)
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
            [("Visibility", "hidden by default; use --show-source-evidence to inspect matching source files")],
        )
    if compact_changed_file_sections and report["results"]:
        print("Changed Files Summary")
        changed_summary_rows: list[list[object]] = []
        for index, item in enumerate(report["results"], start=1):
            primary_projects, broader_projects = split_scope_groups(item.get("projects", []))
            affected_apis = list(item.get("affected_api_entities", [])) or list(item.get("file_level_affected_api_entities", []))
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
            ["#", "Changed File", "APIs", "Tests", "Run Targets", "Primary", "Broader", "Detail"],
            changed_summary_rows,
            indent=2,
        )
        print()
        compact_note_rows: list[tuple[object, object]] = [
            ("Mode", f"compact (auto-enabled for {len(report['results'])} changed files)"),
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
        primary_projects, broader_projects = split_scope_groups(item.get("projects", []))
        changed_rows: list[tuple[object, object]] = [
            ("Surface", item.get("effective_variants_mode", report.get("variants_mode", "auto"))),
            ("Families", _human_preview(item.get("coverage_families", []))),
            ("Capabilities", _human_preview(item.get("coverage_capabilities", []))),
            ("Relevance", relevance_summary.get("mode", report.get("relevance_mode", "all"))),
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
                    _human_preview([entry.get("project", "-") for entry in source_only_consumers], limit=4),
                )
            )
        if item.get("changed_symbols"):
            changed_rows.append(("Changed Symbols", _human_preview(item.get("changed_symbols", []), limit=4)))
        if item.get("changed_ranges"):
            changed_rows.append(("Changed Ranges", _human_preview(item.get("changed_ranges", []), limit=4)))
        if item.get("derived_source_symbols"):
            changed_rows.append(("Derived Symbols", _human_preview(item.get("derived_source_symbols", []), limit=4)))
        if item.get("affected_api_entities"):
            changed_rows.append(("Affected APIs", _human_preview(item.get("affected_api_entities", []), limit=4)))
        file_level_apis = list(item.get("file_level_affected_api_entities", []))
        if file_level_apis and file_level_apis != item.get("affected_api_entities", []):
            changed_rows.append(("File-level APIs", _human_preview(file_level_apis, limit=4)))
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
                    ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items())),
                )
            )
            if not_covered_symbols:
                changed_rows.append(
                    ("Not Covered", _human_preview(not_covered_symbols, limit=4))
                )
            if unresolved_symbols:
                changed_rows.append(
                    ("Unresolved Functions", _human_preview(unresolved_symbols, limit=4))
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
            before = debug.get("candidate_projects_before_prefilter", debug.get("candidate_project_count", 0))
            after = debug.get("candidate_projects_after_prefilter", debug.get("candidate_project_count", 0))
            changed_rows.append(
                (
                    "debug",
                    f"candidate_projects={debug.get('candidate_project_count', 0)}, prefilter={before}->{after}, matched_projects={debug.get('matched_project_count', 0)}",
                )
            )
        if report.get("debug_trace") and item.get("unresolved_debug"):
            debug = item["unresolved_debug"]
            changed_rows.append(
                ("unresolved_debug", f"top_score={debug.get('top_score', '-')}, broad_common_hits={debug.get('broad_common_hits', '-')}")
            )
        _print_key_value_section(f"Changed File: {item['changed_file']}", changed_rows)
        if not item["projects"]:
            print("No candidate XTS projects found")
            print()
            continue
        print_run_targets(item["run_targets"], relevance_summary)
        if show_source_evidence:
            print_projects(item["projects"])

    if report["unresolved_files"]:
        print("Unresolved Files")
        has_reason_class = any(item.get("reason_class") for item in report["unresolved_files"])
        headers = ["Changed File", "Reason", "Class"] if has_reason_class else ["Changed File", "Reason"]
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
        primary_projects, broader_projects = split_scope_groups(item.get("projects", []))
        signal_rows: list[tuple[object, object]] = [
            ("Surface", item.get("effective_variants_mode", report.get("variants_mode", "auto"))),
            ("Families", _human_preview(item.get("coverage_families", []))),
            ("Capabilities", _human_preview(item.get("coverage_capabilities", []))),
            ("Relevance", relevance_summary.get("mode", report.get("relevance_mode", "all"))),
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
                    ("Weak Symbols", _human_preview(item["signals"].get("weak_symbols", []))),
                    ("Project Hints", _human_preview(item["signals"].get("project_hints", []))),
                    ("Method Hints", _human_preview(item["signals"].get("method_hints", []))),
                    ("Type Hints", _human_preview(item["signals"].get("type_hints", []))),
                    ("Member Hints", _human_preview(item["signals"].get("member_hints", []))),
                ]
            )
        if item.get("debug"):
            debug = item["debug"]
            before = debug.get("candidate_projects_before_prefilter", debug.get("candidate_project_count", 0))
            after = debug.get("candidate_projects_after_prefilter", debug.get("candidate_project_count", 0))
            signal_rows.append(
                (
                    "debug",
                    f"candidate_projects={debug.get('candidate_project_count', 0)}, prefilter={before}->{after}, matched_projects={debug.get('matched_project_count', 0)}",
                )
            )
        _print_key_value_section(f"Symbol Query: {item['query']}", signal_rows)
        evidence = item.get("code_search_evidence", {})
        evidence_rows = [["exact", match] for match in evidence.get("exact_hits", [])[:5]]
        evidence_rows.extend(["related", match] for match in evidence.get("related_hits", [])[:5])
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
        _print_key_value_section(f"Code Query: {item['query']}", [("matches", len(item.get("matches", [])))])
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    progress_group = parser.add_mutually_exclusive_group()
    json_group = parser.add_mutually_exclusive_group()
    parser.add_argument("--config", help="JSON config file.")
    parser.add_argument("--changed-file", action="append", default=[], help="Changed file path. Can be repeated.")
    parser.add_argument("--changed-symbol", action="append", default=[], help="Optional changed symbol/function name used to narrow affected APIs for changed-file analysis. Can be repeated.")
    parser.add_argument("--changed-range", action="append", default=[], help="Optional changed line range used to derive touched source symbols, in 'start:end' or 'path:start:end' form. Can be repeated.")
    parser.add_argument("--symbol-query", action="append", default=[], help="Find XTS tests by component/symbol name, e.g. ButtonModifier.")
    parser.add_argument("--code-query", action="append", default=[], help="Find code files by keyword, e.g. ButtonModifier.")
    parser.add_argument("--changed-files-from", help="Text file with one changed file path per line.")
    parser.add_argument("--git-diff", help="Optional git diff ref, for example HEAD~1..HEAD.")
    parser.add_argument("--git-root", help="Git root to use with --git-diff.")
    parser.add_argument("--pr-url", help="GitCode/CodeHub PR or MR URL, for example https://gitcode.com/.../pull/82225 or https://codehub.example.com/.../merge_requests/12")
    parser.add_argument("--pr-number", help="Git host PR/MR number.")
    parser.add_argument(
        "--pr-source",
        choices=PR_SOURCE_CHOICES,
        default="auto",
        help="How to resolve PR/MR changed files: auto prefers the detected host API when token/config is available, api forces API mode, git forces git-fetch mode.",
    )
    parser.add_argument("--git-remote", help="Git remote for PR fetching.")
    parser.add_argument("--git-base-branch", help="Base branch for PR diff. Default: master.")
    parser.add_argument("--git-host-kind", choices=GIT_HOST_KIND_CHOICES, default="auto", help="PR API host kind. auto detects from the PR URL and falls back to GitCode-compatible behavior.")
    parser.add_argument("--git-host-url", help="Git host base URL for API mode, for example https://gitcode.com or https://codehub.example.com")
    parser.add_argument("--git-host-token", help="Git host access token for API mode.")
    parser.add_argument("--gitcode-api-url", help="Deprecated alias for --git-host-url, kept for backward compatibility.")
    parser.add_argument("--gitcode-token", help="Deprecated alias for --git-host-token, kept for backward compatibility.")
    parser.add_argument("--git-host-config", help="Path to INI config with [gitcode] or [codehub] token/url entries.")
    parser.add_argument("--repo-root", help="Explicit OHOS workspace root. By default the CLI auto-discovers the workspace, including sibling ohos_master trees.")
    parser.add_argument("--xts-root", help="Absolute or relative path to XTS root.")
    parser.add_argument("--sdk-api-root", help="Absolute or relative path to SDK api root.")
    parser.add_argument("--acts-out-root", help="Built ACTS output root, for xdevice command generation.")
    parser.add_argument("--path-rules-file", help="Optional JSON file with path and alias mapping rules.")
    parser.add_argument("--composite-mappings-file", help="Optional JSON file with multi-component mapping rules.")
    parser.add_argument("--ranking-rules-file", help="Optional JSON file with family-group, generic-token, umbrella, and planner ranking rules.")
    parser.add_argument("--changed-file-exclusions-file", help="Optional JSON file with changed-file path prefixes to exclude from XTS analysis.")
    parser.add_argument("--device", help="Optional device serial/connect key visible from the selected HDC server.")
    parser.add_argument("--devices", action="append", default=[], help="Comma-separated device serial list for command generation and execution.")
    parser.add_argument("--devices-from", help="File with one device serial per line (comments with # are ignored).")
    parser.add_argument("--server-host", help="Optional remote Linux execution host for wrapper-driven `ohos xts ...` flows.")
    parser.add_argument("--server-user", help="Optional remote Linux user for --server-host. Default: current user on the caller side.")
    parser.add_argument("--product-name", help="Product name for build guidance. Default: rk3568.")
    parser.add_argument("--system-size", help="System size for build guidance. Default: standard.")
    parser.add_argument("--xts-suitetype", help="Optional xts_suitetype for build guidance, for example hap_static or hap_dynamic.")
    parser.add_argument("--run-now", action="store_true", help="Immediately execute selected run targets after report generation.")
    parser.add_argument("--from-report", help="Reuse a previously saved selector JSON report instead of recomputing selection.")
    parser.add_argument("--last-report", action="store_true", help="Reuse the latest saved selector JSON report from the run store.")
    parser.add_argument("--run-label", help="Optional label for storing this planned/executed selector run, for example baseline or v1.")
    parser.add_argument("--run-store-root", help="Directory used to persist labeled selector runs. Default: <selector_repo>/.runs")
    parser.add_argument("--runtime-state-root", help="Shared runtime state directory for device locks and runtime history. Default: /tmp/arkui_xts_selector_state")
    parser.add_argument("--daily-build-tag", help="Daily build tag for prebuilt suites, for example 20260403_120242.")
    parser.add_argument(
        "--daily-component",
        help=(
            "Daily build component name for prebuilt ACTS packages, for example "
            f"{DEFAULT_DAILY_COMPONENT}. Plain board aliases such as dayu200 are "
            "still accepted and will first try <board>_Dyn_Sta_XTS."
        ),
    )
    parser.add_argument("--daily-branch", help="Daily build branch filter. Default: master.")
    parser.add_argument("--daily-date", help="Daily build date in YYYYMMDD or YYYY-MM-DD. Defaults to the date derived from --daily-build-tag.")
    parser.add_argument("--daily-cache-root", help=f"Cache directory for downloaded/extracted daily full packages. Default: {DEFAULT_DAILY_CACHE_ROOT}")
    parser.add_argument("--quick", action="store_true", help="Quick mode: skip daily download and use only local ACTS artifacts. Use when you have a built tree or want fast analysis with reduced accuracy.")
    parser.add_argument("--benchmark", action="store_true", help="Run benchmark cases from canonical corpus and exit with code 1 if any fail.")
    parser.add_argument("--benchmark-fixtures-dir", help="Directory containing canonical corpus benchmark fixtures. Default: tests/fixtures/canonical_corpus")
    parser.add_argument("--inspect", action="store_true", help="Enable inspect mode for querying the persisted dependency/lineage map.")
    parser.add_argument("--inspect-api-entity", help="Inspect mode: show all source files, consumers, and projects that reference this API entity.")
    parser.add_argument("--inspect-source-file", help="Inspect mode: show all API entities and consumers reachable from this source file.")
    parser.add_argument("--inspect-consumer-project", help="Inspect mode: show all API entities and source files reachable from this consumer project.")
    parser.add_argument("--download-daily-tests", action="store_true", help="Download and extract the daily XTS package described by --daily-* options, then exit.")
    parser.add_argument("--download-daily-sdk", action="store_true", help="Download and extract the daily SDK package described by --sdk-* options, then exit.")
    parser.add_argument("--download-daily-firmware", action="store_true", help="Download and extract the daily firmware image package described by --firmware-* options, then exit.")
    parser.add_argument("--flash-daily-firmware", action="store_true", help="Download/extract the daily firmware image package described by --firmware-* options and flash it to the connected device, then exit.")
    parser.add_argument("--sdk-build-tag", help="Daily SDK build tag, for example 20260404_120537.")
    parser.add_argument("--sdk-component", help=f"Daily SDK component name. Default: {DEFAULT_SDK_COMPONENT}.")
    parser.add_argument("--sdk-branch", help="Daily SDK branch filter. Default: master.")
    parser.add_argument("--sdk-date", help="Daily SDK build date in YYYYMMDD or YYYY-MM-DD. Defaults to the date derived from --sdk-build-tag.")
    parser.add_argument("--sdk-cache-root", help=f"Cache directory for downloaded/extracted daily SDK packages. Default: {DEFAULT_SDK_CACHE_ROOT}")
    parser.add_argument("--firmware-build-tag", help="Daily firmware build tag, for example 20260404_120244.")
    parser.add_argument("--firmware-component", help=f"Daily firmware component name. Default: {DEFAULT_FIRMWARE_COMPONENT}.")
    parser.add_argument("--firmware-branch", help="Daily firmware branch filter. Default: master.")
    parser.add_argument("--firmware-date", help="Daily firmware build date in YYYYMMDD or YYYY-MM-DD. Defaults to the date derived from --firmware-build-tag.")
    parser.add_argument("--firmware-cache-root", help=f"Cache directory for downloaded/extracted daily firmware packages. Default: {DEFAULT_FIRMWARE_CACHE_ROOT}")
    parser.add_argument("--flash-firmware-path", help="Path to an unpacked local firmware image bundle root, or a parent directory containing one, to flash directly.")
    parser.add_argument(
        "--list-daily-tags", metavar="TYPE",
        help="List recent daily build tags and exit. TYPE: tests (default), sdk, firmware.",
    )
    parser.add_argument("--list-tags-count", type=int, default=10, metavar="N",
        help="Number of tags to show with --list-daily-tags. Default: 10.")
    parser.add_argument("--list-tags-after", metavar="DATE",
        help="Only list tags on or after this date (YYYYMMDD or YYYY-MM-DD).")
    parser.add_argument("--list-tags-before", metavar="DATE",
        help="Only list tags on or before this date (YYYYMMDD or YYYY-MM-DD). Default: today.")
    parser.add_argument("--list-tags-lookback", type=int, default=30, metavar="DAYS",
        help="How many days back to search when listing tags. Default: 30.")
    parser.add_argument("--flash-py-path", help="Path to the Rockchip flash.py helper used for board flashing.")
    parser.add_argument("--hdc-path", help="Path to hdc used for generated commands, execution preflight, and flashing.")
    parser.add_argument("--hdc-endpoint", help="Remote HDC server endpoint HOST:PORT used for generated commands, preflight, and execution.")
    parser.add_argument("--run-tool", choices=RUN_TOOL_CHOICES, default="auto", help="Execution tool to use for --run-now. Default: auto.")
    parser.add_argument("--skip-install", action="store_true", default=False, help="Skip automatic HAP installation before aa_test execution. Use when HAPs are already installed on the device.")
    parser.add_argument("--run-priority", choices=RUN_PRIORITY_CHOICES, default="recommended", help="Execution priority for --run-now. required = strongest unique coverage, recommended = required plus additional unique coverage, all = include duplicate fallback coverage.")
    parser.add_argument("--shard-mode", choices=SHARD_MODE_CHOICES, default="mirror", help="Execution distribution mode. mirror = all selected targets on every device; split = shard unique targets across devices.")
    parser.add_argument("--parallel-jobs", type=int, default=1, help="Maximum number of device queues to execute in parallel for --run-now. Same-device commands stay sequential.")
    parser.add_argument("--device-lock-timeout", type=float, default=30.0, help="Wait up to N seconds for an exclusive device lock before blocking that device queue. Default: 30.")
    parser.add_argument("--run-top-targets", type=int, default=0, help="Execute at most N unique run targets. 0 = all.")
    parser.add_argument("--run-test-name", action="append", default=[], help="Run only the named suite. Can be repeated. Matches names and aliases from selected_tests.json.")
    parser.add_argument("--run-test-names-file", help="Text file with one or comma-separated suite names per line for manual run selection.")
    parser.add_argument("--run-timeout", type=float, default=0.0, help="Per-command timeout in seconds for --run-now. 0 = disabled.")
    parser.add_argument("--relevance-mode", choices=RELEVANCE_MODE_CHOICES, default="all", help="Filter ranked projects by relevance. all = current behavior, balanced = must-run + high-confidence, strict = must-run only.")
    parser.add_argument("--variants", choices=["auto", "static", "dynamic", "both"], default="auto", help="Filter returned candidates by variant. Default: auto.")
    parser.add_argument("--top-projects", type=int, default=12, help="Number of ranked suites to display per source. 0 = show all. Default: 12.")
    parser.add_argument("--top-files", type=int, default=5)
    parser.add_argument(
        "--keep-per-signature", type=int, default=0,
        help=(
            "Deduplicate output by coverage signature. "
            "Keep at most N projects that provide identical evidence for the query. "
            "0 = disabled (default). 2 = recommended: keeps 2 representatives per "
            "coverage pattern as a guard against flaky tests."
        ),
    )
    parser.add_argument("--cache-file", default=str(DEFAULT_CACHE_FILE))
    parser.add_argument("--debug-trace", action="store_true", help="Include timing metadata and extra ranking diagnostics in the report.")
    parser.add_argument("--show-source-evidence", action="store_true", help="Show per-source Changed File evidence blocks even in combined multi-source PR/MR reports.")
    progress_group.add_argument("--progress", action="store_true", help="Explicitly enable phase-progress messages (default behavior).")
    progress_group.add_argument("--no-progress", action="store_true", help="Disable phase-progress messages.")
    parser.add_argument("--no-cache", action="store_true")
    json_group.add_argument("--json", action="store_true", help="Write machine-readable JSON to stdout instead of the default report file.")
    json_group.add_argument("--json-out", help="Write machine-readable JSON to the specified file path.")
    return parser.parse_args()


def load_app_config(args: argparse.Namespace) -> AppConfig:
    selector_repo_root = PROJECT_ROOT
    cfg = load_json_file(resolve_path(args.config, selector_repo_root, selector_repo_root)) if args.config else {}
    repo_root = discover_repo_root(
        explicit_root=args.repo_root or cfg.get("repo_root"),
        selector_repo_root=selector_repo_root,
    )
    git_host_kind = normalize_git_host_kind(args.git_host_kind or cfg.get("git_host_kind"))
    git_host_config_value = args.git_host_config or cfg.get("git_host_config")
    git_host_config_path = resolve_path(git_host_config_value, repo_root, repo_root) if git_host_config_value else None
    ini_url, ini_token = load_ini_git_host_config(
        git_host_config_value,
        repo_root,
        git_host_kind if git_host_kind != "auto" else "gitcode",
    )
    xts_root = resolve_path(args.xts_root or cfg.get("xts_root"), default_xts_root(repo_root), repo_root)
    sdk_api_root = resolve_path(args.sdk_api_root or cfg.get("sdk_api_root"), default_sdk_api_root(repo_root), repo_root)
    git_repo_root = resolve_path(args.git_root or cfg.get("git_repo_root"), default_git_repo_root(repo_root), repo_root)
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
    devices_from_path = resolve_path(devices_from_value, repo_root, repo_root) if devices_from_value else None
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
    acts_out_root = resolve_path(args.acts_out_root or cfg.get("acts_out_root"), default_acts_out_root(repo_root), repo_root)
    path_rules_file = resolve_path(
        args.path_rules_file or cfg.get("path_rules_file"),
        default_path_rules_file() or repo_root,
        repo_root,
    ) if (args.path_rules_file or cfg.get("path_rules_file") or default_path_rules_file()) else None
    composite_mappings_file = resolve_path(
        args.composite_mappings_file or cfg.get("composite_mappings_file"),
        default_composite_mappings_file() or repo_root,
        repo_root,
    ) if (args.composite_mappings_file or cfg.get("composite_mappings_file") or default_composite_mappings_file()) else None
    ranking_rules_file = resolve_path(
        args.ranking_rules_file or cfg.get("ranking_rules_file"),
        default_ranking_rules_file() or repo_root,
        repo_root,
    ) if (args.ranking_rules_file or cfg.get("ranking_rules_file") or default_ranking_rules_file()) else None
    changed_file_exclusions_file = resolve_path(
        args.changed_file_exclusions_file or cfg.get("changed_file_exclusions_file"),
        default_changed_file_exclusions_file() or repo_root,
        repo_root,
    ) if (args.changed_file_exclusions_file or cfg.get("changed_file_exclusions_file") or default_changed_file_exclusions_file()) else None
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
        args.firmware_cache_root or cfg.get("firmware_cache_root") or str(DEFAULT_FIRMWARE_CACHE_ROOT),
        DEFAULT_FIRMWARE_CACHE_ROOT,
        selector_repo_root,
    )
    flash_py_path = resolve_path(
        args.flash_py_path or cfg.get("flash_py_path"),
        selector_repo_root,
        selector_repo_root,
    ) if (args.flash_py_path or cfg.get("flash_py_path")) else None
    flash_firmware_path = resolve_path(
        args.flash_firmware_path or cfg.get("flash_firmware_path"),
        selector_repo_root,
        selector_repo_root,
    ) if (args.flash_firmware_path or cfg.get("flash_firmware_path")) else None
    hdc_path = resolve_path(
        args.hdc_path or cfg.get("hdc_path"),
        selector_repo_root,
        selector_repo_root,
    ) if (args.hdc_path or cfg.get("hdc_path")) else None
    hdc_endpoint = args.hdc_endpoint or cfg.get("hdc_endpoint")
    git_host_api_url = args.git_host_url or cfg.get("git_host_api_url") or args.gitcode_api_url or cfg.get("gitcode_api_url") or ini_url
    git_host_token = args.git_host_token or cfg.get("git_host_token") or args.gitcode_token or cfg.get("gitcode_token") or ini_token
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
        device_lock_timeout=float(args.device_lock_timeout if args.device_lock_timeout is not None else (cfg.get("device_lock_timeout") or 30.0)),
        daily_build_tag=args.daily_build_tag or cfg.get("daily_build_tag"),
        daily_component=args.daily_component or cfg.get("daily_component") or DEFAULT_DAILY_COMPONENT,
        daily_branch=args.daily_branch or cfg.get("daily_branch") or "master",
        daily_date=args.daily_date or cfg.get("daily_date"),
        daily_cache_root=daily_cache_root,
        quick_mode=bool(args.quick),
        sdk_build_tag=args.sdk_build_tag or cfg.get("sdk_build_tag"),
        sdk_component=args.sdk_component or cfg.get("sdk_component") or DEFAULT_SDK_COMPONENT,
        sdk_branch=args.sdk_branch or cfg.get("sdk_branch") or "master",
        sdk_date=args.sdk_date or cfg.get("sdk_date"),
        sdk_cache_root=sdk_cache_root,
        firmware_build_tag=args.firmware_build_tag or cfg.get("firmware_build_tag"),
        firmware_component=args.firmware_component or cfg.get("firmware_component") or DEFAULT_FIRMWARE_COMPONENT,
        firmware_branch=args.firmware_branch or cfg.get("firmware_branch") or "master",
        firmware_date=args.firmware_date or cfg.get("firmware_date"),
        firmware_cache_root=firmware_cache_root,
        flash_firmware_path=flash_firmware_path,
        flash_py_path=flash_py_path,
        hdc_path=hdc_path,
        hdc_endpoint=hdc_endpoint,
    )


def validate_inputs(args: argparse.Namespace, app_config: AppConfig) -> list[str]:
    """Return early syntax-level input errors only."""
    del app_config
    errors: list[str] = []
    pr_url = str(getattr(args, "pr_url", None) or "").strip()
    if not pr_url:
        return errors
    parsed = urlparse(pr_url)
    if not parsed.scheme or not parsed.netloc:
        errors.append(f"invalid PR URL format: {pr_url!r} - expected https://gitcode.com/.../pull/NNN")
    elif "/pull/" not in parsed.path and "/pulls/" not in parsed.path:
        errors.append(f"PR URL does not look like a pull request URL: {pr_url!r}")
    return errors


def main() -> int:
    global REPO_ROOT
    runtime_started = time.perf_counter()
    args = parse_args()
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
        emit_progress(progress_enabled, "quick mode enabled (using local ACTS artifacts only)")
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
        emit_progress(progress_enabled, f"preparing daily prebuilt {app_config.daily_build_tag or app_config.daily_date}")
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
        emit_progress(progress_enabled, f"preparing daily prebuilt {app_config.daily_date}")
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
                    print(f"warning: daily prebuilt sync failed: {exc}", file=sys.stderr)
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
            emit_progress(progress_enabled, f"auto-downloading daily SDK {app_config.sdk_build_tag or app_config.sdk_date}")
            try:
                prepared_sdk = prepare_daily_sdk_from_config(app_config)
                if prepared_sdk.primary_root is not None:
                    app_config.sdk_api_root = prepared_sdk.primary_root
            except (OSError, ValueError, FileNotFoundError, urllib.error.URLError) as exc:
                print(f"warning: SDK auto-download failed: {exc}", file=sys.stderr)

    source_report_path = resolve_selector_report_input(
        args.from_report,
        bool(args.last_report),
        app_config.run_store_root or default_run_store_root(PROJECT_ROOT),
    )
    source_report = load_selector_report(source_report_path) if source_report_path is not None else None
    run_session = (
        create_run_session(
            app_config.run_label,
            run_store_root=app_config.run_store_root,
            selector_repo_root=app_config.selector_repo_root,
        )
        if app_config.run_label
        else (run_session_from_report(source_report, source_report_path) if source_report is not None and source_report_path is not None else None)
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
    xdevice_reports_root = (run_session.run_dir / "xdevice_reports") if run_session is not None else None
    changed_inputs = list(args.changed_file)
    changed_symbols = [item.strip() for item in args.changed_symbol if item and item.strip()]
    symbol_queries = [item.strip() for item in args.symbol_query if item and item.strip()]
    code_queries = [item.strip() for item in args.code_query if item and item.strip()]
    requested_test_names_path = (
        resolve_path(args.run_test_names_file, app_config.repo_root, app_config.repo_root)
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
        changed_inputs.extend(read_text(resolve_path(args.changed_files_from, app_config.repo_root, app_config.repo_root)).splitlines())

    if source_report is not None:
        report = source_report
        report["human_mode"] = "run_only"
        report["timings_ms"] = {}
        report["json_output_mode"] = "stdout" if json_to_stdout else "file"
        report["requested_devices"] = list(app_config.devices)
        report["execution_server_host"] = app_config.server_host or ""
        report["execution_server_user"] = app_config.server_user or ""
        report["execution_xdevice_reports_root"] = str(xdevice_reports_root) if xdevice_reports_root is not None else ""
        report["execution_summary"] = {}
        selected_tests_report_base_path = resolve_selected_tests_report_base_path(run_session, json_output_path)
        if json_output_path is not None:
            report["json_output_path"] = str(json_output_path)
            selected_tests_json_path = resolve_selected_tests_output_path(selected_tests_report_base_path)
            if selected_tests_json_path is not None:
                report["selected_tests_json_path"] = str(selected_tests_json_path)
        if run_session is not None:
            report["selector_run"] = {
                "label": run_session.label,
                "label_key": run_session.label_key,
                "timestamp": run_session.timestamp,
                "status": str(report.get("selector_run", {}).get("status", "planned")),
                "run_dir": str(run_session.run_dir),
                "run_store_root": str((app_config.run_store_root or default_run_store_root(PROJECT_ROOT)).resolve()),
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
                status = "completed_with_failures" if execution_summary.get("has_failures") else "completed"
            report["selector_run"]["status"] = status
        if execution_summary is not None:
            report["runtime_history_update"] = update_runtime_history(
                default_runtime_history_file(app_config.runtime_state_root),
                report,
                run_label=str(report.get("selector_run", {}).get("label") or app_config.run_label or ""),
            )
        else:
            report["runtime_history_update"] = {
                "history_file": str(default_runtime_history_file(app_config.runtime_state_root)),
                "updated_targets": 0,
                "updated_samples": 0,
                "significant_updates": 0,
            }

        artifact_output_dir = run_session.run_dir if run_session is not None else (json_output_path.parent if json_output_path is not None else None)
        artifact_index_path = write_execution_artifact_index(report, artifact_output_dir)
        if artifact_index_path is not None:
            report["execution_artifact_index_path"] = str(artifact_index_path)

        emit_progress(progress_enabled, "writing JSON report")
        written_json_path = write_json_report(report, json_to_stdout=json_to_stdout, json_output_path=json_output_path)
        selected_tests_report_base_path = resolve_selected_tests_report_base_path(run_session, written_json_path)
        if selected_tests_report_base_path is not None:
            selected_tests_path = write_selected_tests_report(report, selected_tests_report_base_path)
            if selected_tests_path is not None:
                report["selected_tests_json_path"] = str(selected_tests_path)
                if written_json_path is not None:
                    write_json_report(report, json_to_stdout=False, json_output_path=written_json_path)
        if run_session is not None:
            manifest = build_run_manifest(
                report,
                selector_repo_root=app_config.selector_repo_root or PROJECT_ROOT,
                run_store_root=app_config.run_store_root or default_run_store_root(PROJECT_ROOT),
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

    changed_files = normalize_changed_files(changed_inputs, base_roots=[app_config.repo_root, app_config.git_repo_root])
    if args.git_diff:
        try:
            changed_files.extend(git_changed_files(app_config.git_repo_root, args.git_diff))
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
            print(f"error: {XtsUserError(f'cannot fetch PR diff: {message}', hint=hint)}", file=sys.stderr)
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
        print("No changed files, symbol queries, or code queries were provided.", file=sys.stderr)
        return 2

    exclusion_started = time.perf_counter()
    exclusion_config = load_changed_file_exclusion_config(app_config.changed_file_exclusions_file)
    changed_files, excluded_inputs = filter_changed_files_for_xts(
        changed_files,
        app_config.git_repo_root,
        exclusion_config,
    )
    changed_file_filtering_ms = round((time.perf_counter() - exclusion_started) * 1000, 3)

    progress_callback = build_progress_callback(progress_enabled, len(changed_files))

    emit_progress(progress_enabled, "loading XTS project index")
    load_started = time.perf_counter()
    projects, cache_used = load_or_build_projects(app_config.xts_root, app_config.cache_file)
    load_projects_ms = round((time.perf_counter() - load_started) * 1000, 3)
    emit_progress(progress_enabled, "loading SDK index")
    sdk_started = time.perf_counter()
    sdk_index = load_sdk_index(app_config.sdk_api_root)
    load_sdk_index_ms = round((time.perf_counter() - sdk_started) * 1000, 3)
    emit_progress(progress_enabled, "building content modifier index")
    content_started = time.perf_counter()
    content_index = build_content_modifier_index()
    build_content_modifier_index_ms = round((time.perf_counter() - content_started) * 1000, 3)
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
        build_api_lineage_map_ms = round((time.perf_counter() - lineage_started) * 1000, 3)
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
    runtime_history_index = build_runtime_history_index(default_runtime_history_file(app_config.runtime_state_root))
    load_runtime_history_ms = round((time.perf_counter() - runtime_history_started) * 1000, 3)
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
        build_api_lineage_map_ms = round((time.perf_counter() - lineage_started) * 1000, 3)
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
    report["acts_out_root"] = str(app_config.acts_out_root or (app_config.repo_root / "out/release/suites/acts"))
    report["excluded_inputs"] = excluded_inputs
    report["timings_ms"].update({
        "changed_file_filtering": changed_file_filtering_ms,
        "load_projects": load_projects_ms,
        "load_sdk_index": load_sdk_index_ms,
        "build_content_modifier_index": build_content_modifier_index_ms,
        "load_mapping_config": load_mapping_config_ms,
        "load_runtime_history": load_runtime_history_ms,
        "build_api_lineage_map": build_api_lineage_map_ms,
        "main_report_call": round((time.perf_counter() - report_started) * 1000, 3),
    })
    report["timings_ms"]["total_runtime"] = round((time.perf_counter() - runtime_started) * 1000, 3)
    report["json_output_mode"] = "stdout" if json_to_stdout else "file"
    report["requested_devices"] = list(app_config.devices)
    report["execution_server_host"] = app_config.server_host or ""
    report["execution_server_user"] = app_config.server_user or ""
    report["execution_xdevice_reports_root"] = str(xdevice_reports_root) if xdevice_reports_root is not None else ""
    if app_config.daily_prebuilt is not None:
        report["daily_prebuilt"] = {
            **app_config.daily_prebuilt.to_dict(),
            "note": app_config.daily_prebuilt_note,
        }
    selected_tests_report_base_path = resolve_selected_tests_report_base_path(run_session, json_output_path)
    if json_output_path is not None:
        report["json_output_path"] = str(json_output_path)
        selected_tests_json_path = resolve_selected_tests_output_path(selected_tests_report_base_path)
        if selected_tests_json_path is not None:
            report["selected_tests_json_path"] = str(selected_tests_json_path)
    if run_session is not None:
        report["selector_run"] = {
            "label": run_session.label,
            "label_key": run_session.label_key,
            "timestamp": run_session.timestamp,
            "status": "planned",
            "run_dir": str(run_session.run_dir),
            "run_store_root": str((app_config.run_store_root or default_run_store_root(PROJECT_ROOT)).resolve()),
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
    report["coverage_run_commands"] = build_coverage_run_commands(report, app_config, args)
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
            status = "completed_with_failures" if execution_summary.get("has_failures") else "completed"
        report["selector_run"]["status"] = status
    if execution_summary is not None:
        report["runtime_history_update"] = update_runtime_history(
            default_runtime_history_file(app_config.runtime_state_root),
            report,
            run_label=app_config.run_label,
        )
    else:
        report["runtime_history_update"] = {
            "history_file": str(default_runtime_history_file(app_config.runtime_state_root)),
            "updated_targets": 0,
            "updated_samples": 0,
            "significant_updates": 0,
        }

    artifact_output_dir = run_session.run_dir if run_session is not None else (json_output_path.parent if json_output_path is not None else None)
    artifact_index_path = write_execution_artifact_index(report, artifact_output_dir)
    if artifact_index_path is not None:
        report["execution_artifact_index_path"] = str(artifact_index_path)

    emit_progress(progress_enabled, "writing JSON report")
    written_json_path = write_json_report(report, json_to_stdout=json_to_stdout, json_output_path=json_output_path)
    selected_tests_report_base_path = resolve_selected_tests_report_base_path(run_session, written_json_path)
    if selected_tests_report_base_path is not None:
        selected_tests_path = write_selected_tests_report(report, selected_tests_report_base_path)
        if selected_tests_path is not None:
            report["selected_tests_json_path"] = str(selected_tests_path)
            if written_json_path is not None:
                write_json_report(report, json_to_stdout=False, json_output_path=written_json_path)
    if run_session is not None:
        manifest = build_run_manifest(
            report,
            selector_repo_root=app_config.selector_repo_root or PROJECT_ROOT,
            run_store_root=app_config.run_store_root or default_run_store_root(PROJECT_ROOT),
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
