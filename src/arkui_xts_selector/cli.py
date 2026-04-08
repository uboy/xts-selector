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
from pathlib import Path
from typing import Iterable, Callable
from urllib.parse import urlparse

from rich import box
from rich.console import Console
from rich.padding import Padding
from rich.table import Table

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
    DEFAULT_FIRMWARE_COMPONENT,
    DEFAULT_SDK_COMPONENT,
    PreparedDailyArtifact,
    PreparedDailyPrebuilt,
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
    RUN_TOOL_CHOICES,
    SHARD_MODE_CHOICES,
    attach_execution_plan,
    build_run_target_entry,
    execute_planned_targets,
    preflight_execution,
    resolve_devices,
)
from .flashing import flash_image_bundle
from .run_store import (
    build_run_manifest,
    create_run_session,
    default_run_store_root,
    write_run_artifacts,
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


def default_cache_path(xts_root: Path) -> Path:
    """Generate workspace-specific cache path to avoid race conditions."""
    workspace_hash = hashlib.sha256(str(xts_root.resolve()).encode()).hexdigest()[:12]
    return Path(f"/tmp/arkui_xts_selector_cache_{workspace_hash}.json")
DEFAULT_REPORT_FILE = "arkui_xts_selector_report.json"
RELEVANCE_MODE_CHOICES = ("all", "balanced", "strict")
PR_SOURCE_CHOICES = ("auto", "api", "git")
DEFAULT_CHANGED_FILE_EXCLUSION_RULES = {
    "path_prefixes": [
        "test/unittest/",
        "foundation/arkui/ace_engine/test/unittest/",
        "test/mock/",
        "foundation/arkui/ace_engine/test/mock/",
    ]
}

IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
IMPORT_BINDING_RE = re.compile(r"""import\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""", re.S)
DEFAULT_IMPORT_RE = re.compile(r"""import\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+['"]([^'"]+)['"]""")
IDENTIFIER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\s*\(""")
MEMBER_CALL_RE = re.compile(r"""\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
WORD_RE = re.compile(r"""\b[A-Za-z_][A-Za-z0-9_]{2,}\b""")
OHOS_MODULE_RE = re.compile(r"""@ohos\.[A-Za-z0-9._]+""")
CPP_IDENTIFIER_RE = re.compile(r"""\b[A-Z][A-Za-z0-9_]{2,}\b""")
TYPE_MEMBER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
EXPORT_CLASS_RE = re.compile(r"""\bexport\s+class\s+([A-Z][A-Za-z0-9_]*)\b""")
EXPORT_INTERFACE_RE = re.compile(r"""\bexport\s+interface\s+([A-Z][A-Za-z0-9_]*)\b""")
PUBLIC_METHOD_RE = re.compile(r"""\bpublic\s+(?:static\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
GENERATED_ACCESSOR_NAMESPACE_RE = re.compile(r"""GeneratedModifier::([A-Za-z_][A-Za-z0-9_]*)Accessor\b""")
GET_ACCESSOR_RE = re.compile(r"""\bGet([A-Za-z_][A-Za-z0-9_]*)Accessor\s*\(""")
PEER_INCLUDE_RE = re.compile(r"#include\s+\"[^\"]*/([a-z0-9_]+)_peer\.h\"")
DYNAMIC_MODULE_RE = re.compile(r"""GetDynamicModule\("([A-Za-z0-9_]+)"\)""")
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
        return ""
    grouped = COVERAGE_FAMILY_GROUP_OVERRIDES.get(canonical, canonical)
    if not grouped or grouped in GENERIC_COVERAGE_TOKENS:
        return ""
    return grouped


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


def should_keep_ets_signal_name(
    name: str,
    source_families: set[str],
    allow_source_family_fallback: bool,
) -> bool:
    base_token = related_signal_base_token(name)
    family_token = related_signal_family_token(name)
    if not family_token:
        return False
    if family_token in source_families or coverage_family_key(family_token):
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
    if capability_keys and not family_keys:
        family_keys = sorted({capability_family_key(item) for item in capability_keys if capability_family_key(item)})
    focus_tokens = sorted(extract_focus_tokens(raw_tokens))
    return {
        "key": f"{source_type}:{source_value}",
        "type": source_type,
        "value": source_value,
        "family_keys": family_keys,
        "capability_keys": capability_keys,
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


def load_ini_gitcode_config(path_value: str | None, repo_root: Path) -> tuple[str | None, str | None]:
    if not path_value:
        return None, None
    path = resolve_path(path_value, repo_root, repo_root)
    if not path.exists():
        return None, None
    parser = ConfigParser()
    parser.read(path, encoding="utf-8-sig")
    return (
        parser.get("gitcode", "gitcode-url", fallback=None),
        parser.get("gitcode", "token", fallback=None),
    )


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


@dataclass
class AppConfig:
    repo_root: Path
    xts_root: Path
    sdk_api_root: Path
    cache_file: Path | None
    git_repo_root: Path
    git_remote: str
    git_base_branch: str
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
    shard_mode: str = "mirror"
    daily_build_tag: str | None = None
    daily_component: str = DEFAULT_DAILY_COMPONENT
    daily_branch: str = "master"
    daily_date: str | None = None
    daily_cache_root: Path | None = None
    daily_prebuilt: PreparedDailyPrebuilt | None = None
    daily_prebuilt_ready: bool = False
    daily_prebuilt_note: str = ""
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


@dataclass
class TestFileIndex:
    relative_path: str
    surface: str = "utility"
    imports: set[str] = field(default_factory=set)
    imported_symbols: set[str] = field(default_factory=set)
    identifier_calls: set[str] = field(default_factory=set)
    member_calls: set[str] = field(default_factory=set)
    type_member_calls: set[str] = field(default_factory=set)
    typed_modifier_bases: set[str] = field(default_factory=set)
    words: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "relative_path": self.relative_path,
            "surface": self.surface,
            "imports": sorted(self.imports),
            "imported_symbols": sorted(self.imported_symbols),
            "identifier_calls": sorted(self.identifier_calls),
            "member_calls": sorted(self.member_calls),
            "type_member_calls": sorted(self.type_member_calls),
            "typed_modifier_bases": sorted(self.typed_modifier_bases),
            "words": sorted(self.words),
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
            typed_modifier_bases=set(data.get("typed_modifier_bases", [])),
            words=set(data["words"]),
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
    search_typed_modifier_bases: set[str] = field(default_factory=set)
    search_words: set[str] = field(default_factory=set)
    search_path_tokens: set[str] = field(default_factory=set)
    search_project_path_compact: str = ""
    search_file_path_compacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = {
            "relative_root": self.relative_root,
            "test_json": self.test_json,
            "bundle_name": self.bundle_name,
            "path_key": self.path_key,
            "variant": self.variant,
            "surface": self.surface,
            "supported_surfaces": sorted(self.supported_surfaces),
            "files": [item.to_dict() for item in self.files],
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
                "typed_modifier_bases": sorted(self.search_typed_modifier_bases),
                "words": sorted(self.search_words),
                "path_tokens": sorted(self.search_path_tokens),
                "project_path_compact": self.search_project_path_compact,
                "file_path_compacts": list(self.search_file_path_compacts),
            }
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> "TestProjectIndex":
        project = cls(
            relative_root=data["relative_root"],
            test_json=data["test_json"],
            bundle_name=data.get("bundle_name"),
            path_key=data["path_key"],
            variant=data.get("variant", "unknown"),
            surface=data.get("surface", data.get("variant", "unknown")),
            supported_surfaces=set(data.get("supported_surfaces", [])),
            files=[TestFileIndex.from_dict(item) for item in data["files"]],
        )
        summary = data.get("search_summary")
        if isinstance(summary, dict):
            project.search_summary_ready = True
            project.search_imports = set(summary.get("imports", []))
            project.search_imported_symbols = set(summary.get("imported_symbols", []))
            project.search_imported_symbol_tokens = set(summary.get("imported_symbol_tokens", []))
            project.search_identifier_calls = set(summary.get("identifier_calls", []))
            project.search_identifier_call_tokens = set(summary.get("identifier_call_tokens", []))
            project.search_member_call_tokens = set(summary.get("member_call_tokens", []))
            project.search_type_owner_tokens = set(summary.get("type_owner_tokens", []))
            project.search_typed_modifier_bases = set(summary.get("typed_modifier_bases", []))
            project.search_words = set(summary.get("words", []))
            project.search_path_tokens = set(summary.get("path_tokens", []))
            project.search_project_path_compact = str(summary.get("project_path_compact", ""))
            project.search_file_path_compacts = [str(item) for item in summary.get("file_path_compacts", [])]
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
        project.search_typed_modifier_bases.update(file_index.typed_modifier_bases)
        project.search_words.update(compact_token(word) for word in file_index.words if compact_token(word))

    project.search_path_tokens = {token for token in path_tokens if token}
    project.search_project_path_compact = project_path_compact
    project.search_file_path_compacts = file_path_compacts
    project.search_summary_ready = True
    return project


def project_might_match(project: TestProjectIndex, signals: dict[str, set[str]]) -> bool:
    ensure_project_search_summary(project)

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
            or symbol_token in project.search_words
        ):
            return True
        if symbol.endswith("Modifier"):
            base_token = compact_token(symbol[:-8])
            if base_token and base_token in project.search_typed_modifier_bases:
                return True

    return False


def select_candidate_projects(
    projects: list[TestProjectIndex],
    signals: dict[str, set[str]],
    variants_mode: str,
) -> tuple[list[TestProjectIndex], list[TestProjectIndex]]:
    variant_projects = [project for project in projects if variant_matches(project.variant, variants_mode)]
    shortlisted = [project for project in variant_projects if project_might_match(project, signals)]
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


def load_changed_file_exclusion_config(path_value: Path | None) -> ChangedFileExclusionConfig:
    data = load_json_if_exists(path_value)
    configured_prefixes = data.get("path_prefixes", []) if isinstance(data, dict) else []
    prefixes: list[str] = []
    for value in list(DEFAULT_CHANGED_FILE_EXCLUSION_RULES.get("path_prefixes", [])) + list(configured_prefixes):
        if not isinstance(value, str):
            continue
        normalized = value.replace('\\', '/').strip().lstrip('./').lower()
        if normalized and not normalized.endswith('/'):
            normalized += '/'
        if normalized and normalized not in prefixes:
            prefixes.append(normalized)
    return ChangedFileExclusionConfig(path_prefixes=prefixes)


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
    for prefix in exclusion_config.path_prefixes:
        if any(key.startswith(prefix) for key in keys):
            return {
                "changed_file": describe_changed_file(path, git_repo_root),
                "reason": "excluded_from_xts_analysis",
                "matched_prefix": prefix,
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


def fetch_gitcode_api_json(api_url: str, token: str, api_path: str) -> object:
    base = api_url.rstrip("/")
    separator = "&" if "?" in api_path else "?"
    requests_to_try = [
        urllib.request.Request(
            f"{base}{api_path}{separator}{urllib.parse.urlencode({'access_token': token})}",
            headers={"Accept": "application/json"},
        ),
        urllib.request.Request(
            f"{base}{api_path}",
            headers={"Accept": "application/json", "private-token": token},
        ),
    ]
    last_error = "gitcode api failed"
    for request in requests_to_try:
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            last_error = f"gitcode api failed: {exc}"
        except json.JSONDecodeError as exc:
            last_error = f"gitcode api returned invalid json: {exc}"
    raise RuntimeError(last_error)


def fetch_pr_metadata_via_api(api_url: str, token: str, owner: str, repo: str, pr_ref: str) -> dict:
    pr_number = parse_pr_number(pr_ref)
    data = fetch_gitcode_api_json(api_url, token, f"/api/v5/repos/{owner}/{repo}/pulls/{pr_number}")
    if not isinstance(data, dict):
        raise RuntimeError(f"gitcode api unexpected PR response: {data}")
    return data


def fetch_pr_changed_files_via_api(
    api_url: str,
    token: str,
    owner: str,
    repo: str,
    pr_ref: str,
    repo_root: Path,
) -> list[Path]:
    pr_number = parse_pr_number(pr_ref)
    data = fetch_gitcode_api_json(api_url, token, f"/api/v5/repos/{owner}/{repo}/pulls/{pr_number}/files")
    if isinstance(data, dict):
        data = data.get("files") or data.get("data") or data.get("changed_files")
    if not isinstance(data, list):
        raise RuntimeError(f"gitcode api unexpected response: {data}")

    changed_files: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        path_value = item.get("filename") or item.get("new_path") or item.get("old_path")
        if path_value:
            changed_files.append(path_value)
    return normalize_changed_files(changed_files, base_roots=[repo_root])


def resolve_pr_changed_files(app_config: AppConfig, pr_ref: str, pr_source: str) -> list[Path]:
    owner_repo = resolve_pr_owner_repo(pr_ref, app_config.git_repo_root, app_config.git_remote)
    api_error: RuntimeError | None = None
    if pr_source in ("auto", "api"):
        if not app_config.gitcode_api_url or not app_config.gitcode_token:
            api_error = RuntimeError(
                "PR API mode requires GitCode credentials; pass --gitcode-token or --git-host-config with [gitcode] token/url."
            )
        elif owner_repo is None:
            api_error = RuntimeError("could not determine owner/repo for PR API mode from --pr-url or local git remote")
        else:
            try:
                fetch_pr_metadata_via_api(
                    api_url=app_config.gitcode_api_url,
                    token=app_config.gitcode_token,
                    owner=owner_repo[0],
                    repo=owner_repo[1],
                    pr_ref=pr_ref,
                )
                return fetch_pr_changed_files_via_api(
                    api_url=app_config.gitcode_api_url,
                    token=app_config.gitcode_token,
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
        )
    except RuntimeError as exc:
        if api_error is not None and pr_source == "auto":
            raise RuntimeError(f"api failed: {api_error}; git failed: {exc}") from exc
        raise


def parse_test_file(path: Path) -> TestFileIndex:
    text = read_text(path)
    surface_profile = classify_xts_file_surface(path, text)
    imported_symbols: set[str] = set()
    typed_modifier_bases: set[str] = set()
    for match in IMPORT_BINDING_RE.finditer(text):
        for part in match.group(1).split(","):
            token = part.strip().split(" as ", 1)[0].strip()
            if token:
                imported_symbols.add(token)
    for match in DEFAULT_IMPORT_RE.finditer(text):
        imported_symbols.add(match.group(1))
    for raw in TYPED_ATTRIBUTE_MODIFIER_RE.findall(text):
        base = compact_token(raw)
        if base:
            typed_modifier_bases.add(base)
    for raw in EXTENDS_MODIFIER_RE.findall(text):
        base = compact_token(raw)
        if base:
            typed_modifier_bases.add(base)
    return TestFileIndex(
        relative_path=repo_rel(path),
        surface=surface_profile.surface,
        imports=set(IMPORT_RE.findall(text)),
        imported_symbols=imported_symbols,
        identifier_calls=set(IDENTIFIER_CALL_RE.findall(text)),
        member_calls=set(MEMBER_CALL_RE.findall(text)),
        type_member_calls={f"{owner}.{member}" for owner, member in TYPE_MEMBER_CALL_RE.findall(text)},
        typed_modifier_bases=typed_modifier_bases,
        words={word.lower() for word in WORD_RE.findall(text)},
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


def _build_project_hash(project_root: Path, source_files: list[Path]) -> str:
    """Compute hash for a single project based on its source files."""
    h = hashlib.sha256()
    for f in sorted(source_files):
        try:
            stat = f.stat()
            h.update(f"{f}:{stat.st_mtime_ns}:{stat.st_size}".encode())
        except OSError:
            h.update(f"{f}:missing".encode())
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


def load_or_build_projects(xts_root: Path, cache_file: Path | None) -> tuple[list[TestProjectIndex], bool]:
    CACHE_VERSION = 4

    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)

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

    for test_json, root in project_dirs:
        source_files = sorted(
            f.resolve() for f in root.rglob("*")
            if f.is_file() and (f.name == "Test.json" or f.suffix.lower() in {".ets", ".ts", ".js"})
            and not any(skip in f.parts for skip in skip_dirs)
        )
        proj_hash = _build_project_hash(root, source_files)
        rel_key = str(root.relative_to(xts_root)).replace(os.sep, "/")

        if rel_key in old_cache and old_cache[rel_key].get("hash") == proj_hash:
            # Cache hit
            try:
                project = TestProjectIndex.from_dict(old_cache[rel_key]["data"])
                ensure_project_search_summary(project)
                projects.append(project)
                new_cache[rel_key] = {"hash": proj_hash, "data": project.to_dict()}
                cache_hits += 1
                continue
            except (KeyError, TypeError):
                pass

        # Cache miss — rebuild
        project = _build_single_project(test_json, root, xts_root)
        ensure_project_search_summary(project)
        projects.append(project)
        new_cache[rel_key] = {"hash": proj_hash, "data": project.to_dict()}

    # Save updated cache
    if cache_file:
        cache_payload = {
            "version": CACHE_VERSION,
            "projects": new_cache,
        }
        cache_file.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")

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

    signals = {
        "modules": set(),
        "symbols": set(),
        "project_hints": set(),
        "method_hints": set(),
        "type_hints": set(),
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
        source_families = {FAMILY_TOKEN_ALIAS_INDEX.get(family, family) for family in signals["family_tokens"]}
        source_focus = ets_source_focus_tokens(source_families)

        for match in OHOS_MODULE_RE.findall(text):
            signals["modules"].add(match)
            module = normalize_ohos_module(match, sdk_index.top_level_modules)
            if module:
                signals["modules"].add(module)

        def _add_ets_type_signal(name: str, allow_source_family_fallback: bool) -> None:
            cleaned = str(name).strip()
            if not cleaned:
                return
            if not should_keep_ets_signal_name(cleaned, source_families, allow_source_family_fallback):
                return
            signals["symbols"].add(cleaned)
            signals["type_hints"].add(cleaned)
            family_token = related_signal_family_token(cleaned)
            mapped_family = coverage_family_key(family_token) or coverage_family_key(related_signal_base_token(cleaned))
            if mapped_family:
                signals["family_tokens"].add(mapped_family)
                signals["project_hints"].add(mapped_family)
                signals["symbols"].update(mapping_config.pattern_alias.get(mapped_family, []))

        exported_type_names = set(EXPORT_CLASS_RE.findall(text)) | set(EXPORT_INTERFACE_RE.findall(text))
        for name in sorted(exported_type_names):
            _add_ets_type_signal(name, allow_source_family_fallback=True)

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
            _add_ets_type_signal(name, allow_source_family_fallback=False)

        public_methods = [
            method
            for method in sorted(set(PUBLIC_METHOD_RE.findall(text)))
            if compact_token(method) not in GENERIC_PUBLIC_METHOD_HINTS
        ]
        if 1 <= len(public_methods) <= 6 and (
            1 <= len(source_focus) <= 2 or len(exported_type_names) == 1
        ):
            signals["method_hints"].update(public_methods)

    native_suffixes = {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh"}
    if changed_file.suffix.lower() in native_suffixes:
        text = read_text(changed_file)
        text_lower = text.lower()
        dynamic_modules = {match for match in DYNAMIC_MODULE_RE.findall(text)}

        for match in OHOS_MODULE_RE.findall(text):
            signals["modules"].add(match)
            module = normalize_ohos_module(match, sdk_index.top_level_modules)
            if module:
                signals["modules"].add(module)

        for ident in CPP_IDENTIFIER_RE.findall(text):
            compact_ident = compact_token(ident.replace("Modifier", ""))
            if compact_ident in families:
                signals["symbols"].add(ident)

        accessor_type_hints = extract_native_accessor_type_hints(text)
        if accessor_type_hints:
            signals["type_hints"].update(accessor_type_hints)
            signals["symbols"].update(accessor_type_hints)
            signals["project_hints"].update(
                compact_token(hint) for hint in accessor_type_hints if compact_token(hint)
            )

        for include_family in INCLUDE_PATTERN_COMPONENT_RE.findall(text):
            family = compact_token(include_family)
            if family:
                signals["family_tokens"].add(family)

        for family in families:
            if family and family in text_lower:
                signals["project_hints"].add(family)

        for raw, aliases in mapping_config.pattern_alias.items():
            compact = compact_token(raw)
            if compact in families:
                signals["symbols"].update(aliases)

        for key, rule in mapping_config.special_path_rules.items():
            if key in text_lower:
                signals["modules"].update(rule.get("modules", []))
                signals["symbols"].update(rule.get("symbols", []))
                signals["project_hints"].add(key)
                signals["method_hints"].update(rule.get("method_hints", []))
                signals["type_hints"].update(rule.get("type_hints", []))

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

    apply_composite_mapping(changed_file, rel_lower, signals, content_index, mapping_config)

    signals["modules"] = {item for item in signals["modules"] if item}
    signals["symbols"] = {item for item in signals["symbols"] if item}
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
    return signals


def symbol_score(
    signal_symbol: str,
    file_index: TestFileIndex,
    family_tokens: set[str],
    lowered_member_calls: set[str],
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

    if signal_symbol in file_index.imported_symbols:
        score += 7 if strong else 1
        reasons.append(f"imports symbol {signal_symbol}")
    if signal_symbol in file_index.identifier_calls:
        # If the symbol is also explicitly imported, the call is confirmation
        # evidence that adds less marginal value than the import itself.
        # If NOT imported (ArkUI components are globally available in ETS
        # without explicit import), the call is still valid usage evidence
        # but weaker than an explicit SDK import.
        #   import + call  → 7 + 3 = 10  (explicitly imported and used)
        #   call only      → 4            (globally used, no import)
        if signal_symbol in file_index.imported_symbols:
            call_pts = 3 if strong else 1
        else:
            call_pts = 4 if strong else 1
        score += call_pts
        reasons.append(f"calls {signal_symbol}()")
    if lower in lowered_member_calls:
        score += 4 if strong else 1
        reasons.append(f"member call .{lower}()")
    if lower in file_index.words:
        word_score = 2 if strong and not is_ubiquitous else (1 if strong else 0)
        score += word_score
        if word_score:
            reasons.append(f"mentions {lower}")
    return score, reasons


def score_file(file_index: TestFileIndex, signals: dict[str, set[str]]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    lowered_member_calls = {compact_token(member) for member in file_index.member_calls}
    identifier_call_tokens = {compact_token(identifier) for identifier in file_index.identifier_calls}
    imported_symbol_tokens = {compact_token(symbol) for symbol in file_index.imported_symbols}
    type_member_calls_by_token: dict[str, set[str]] = {}
    for entry in file_index.type_member_calls:
        owner, separator, member = entry.partition(".")
        owner_token = compact_token(owner)
        if owner_token and separator and member:
            type_member_calls_by_token.setdefault(owner_token, set()).add(member)

    for module in sorted(signals["modules"]):
        if module in file_index.imports:
            score += 10
            reasons.append(f"imports {module}")

    typed_modifier_matches: list[str] = []
    for symbol in sorted(signals["symbols"]):
        delta, symbol_reasons = symbol_score(symbol, file_index, signals["family_tokens"], lowered_member_calls)
        score += delta
        reasons.extend(symbol_reasons)
        if symbol.endswith("Modifier") and compact_token(symbol[:-8]) in file_index.typed_modifier_bases:
            typed_modifier_matches.append(symbol)

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
    for hint_token, hint in sorted(type_hints_by_token.items()):
        if hint_token in identifier_call_tokens:
            constructor_matches.append(hint)
        if hint_token in imported_symbol_tokens:
            import_matches.append(hint)
        members = sorted(type_member_calls_by_token.get(hint_token, set()))
        if members:
            type_member_matches.extend(f"{hint}.{member}()" for member in members)

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

        if unmatched_methods:
            if method_hint_required:
                # Hard correction: file does NOT use the required method.
                # Cap score at 5 (bucket = "possible related").
                if score > 5:
                    penalty = score - 5
                    score = 5
                    deduped.append(
                        f"capped: missing required method "
                        f"{', '.join(sorted(unmatched_methods))} (-{penalty})"
                    )
            else:
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
    shown = list(project_results[:top_projects])
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


def build_global_coverage_recommendations(
    candidate_entries: list[dict[str, object]],
    repo_root: Path,
    acts_out_root: Path | None,
    device: str | None,
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
        }
        target = build_run_target_entry(
            project_entry,
            repo_root=repo_root,
            acts_out_root=acts_out_root,
            device=device,
        )
        target_key = target.get("target_key") or target.get("test_json") or target.get("project") or ""
        if not target_key:
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
            },
        )
        existing_target = candidate["target"]
        if project_result_sort_tuple(project_entry) < project_result_sort_tuple(existing_target):
            candidate["target"] = target
            existing_target = target
        candidate["source_keys"].add(source_key)
        candidate["sources"][source_key] = all_sources[source_key]
        candidate["source_reasons"].setdefault(source_key, list(project_entry.get("scope_reasons", [])))
        source_rank = int(entry.get("source_rank", 999) or 999)
        candidate["source_ranks"][source_key] = min(
            int(candidate["source_ranks"].get(source_key, 999) or 999),
            source_rank,
        )
        capability_keys = list(source_profile.get("capability_keys", []))
        family_keys = list(source_profile.get("family_keys", []))
        capability_gains = suite_source_capability_gains(project_entry, source_profile)
        capability_representative_scores = suite_source_capability_representative_scores(project_entry, source_profile)
        family_gains = suite_source_family_gains(project_entry, source_profile)
        family_representative_scores = suite_source_family_representative_scores(project_entry, source_profile)
        focus_overlap = suite_source_focus_token_overlap(project_entry, source_profile)
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
        elif family_keys:
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
        else:
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
        target["covered_families"] = sorted(candidate.get("covered_families", set()))
        target["covered_capabilities"] = sorted(candidate.get("covered_capabilities", set()))
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
        target["covered_units"] = [
            {
                "type": str(all_units[key].get("type") or ""),
                "unit_kind": str(all_units[key].get("unit_kind") or ""),
                "family_key": str(all_units[key].get("family_key") or ""),
                "capability_key": str(all_units[key].get("capability_key") or ""),
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
        target["coverage_status"] = "recommended" if new_keys else "optional"
        target["coverage_reason"] = (
            f"adds {len(new_keys)} new functional area(s)"
            if new_keys
            else "covers only functionality already covered by earlier recommended suites"
        )
        target["coverage_source_reasons"] = {
            key: candidate["source_reasons"].get(key, [])
            for key in sorted(source_keys)
        }
        ordered_candidates.append(target)

    recommended = [target for target in ordered_candidates if int(target.get("new_coverage_count", 0)) > 0]
    optional_duplicates = [target for target in ordered_candidates if int(target.get("new_coverage_count", 0)) <= 0]
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
            "value": str(info.get("family_key") or (info.get("sources") or [{"value": ""}])[0].get("value", "")),
        }
        for key, info in sorted(all_units.items())
        if key not in covered_unit_keys
    ]
    return {
        "source_count": len(all_units),
        "candidate_count": len(ordered_candidates),
        "recommended": recommended,
        "optional_duplicates": optional_duplicates,
        "ordered_targets": ordered_candidates,
        "recommended_target_keys": [str(target.get("target_key") or "") for target in recommended],
        "optional_target_keys": [str(target.get("target_key") or "") for target in optional_duplicates],
        "ordered_target_keys": [str(target.get("target_key") or "") for target in ordered_candidates],
        "covered_source_keys": covered_unit_keys,
        "uncovered_sources": uncovered_sources,
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
        "symbols": set(),
        "project_hints": set(),
        "method_hints": set(),
        "type_hints": set(),
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
        "symbols": {item for item in signals["symbols"] if item},
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
        "reason": None,
    }
    if not project_results:
        analysis["reason"] = "No XTS usages were found for this file."
        return analysis
    if top_score < 12:
        analysis["reason"] = "Only weak matches were found; test usage could not be determined reliably."
        return analysis
    if (
        has_content_modifier_signal
        and len(signals["family_tokens"]) >= 5
        and broad_common_hits >= min(3, len(top_paths))
        and not any("contentmodifier" in path for path in top_paths)
    ):
        analysis["reason"] = "Only broad/common ArkUI suites were matched; no reliable content-modifier-specific XTS usage was found."
    return analysis


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
        app_config.daily_prebuilt_note = (
            f"Using prebuilt ACTS artifacts from daily build {prepared.build.tag} "
            f"({prepared.acts_out_root})."
        )
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
    elif tag_type == "firmware":
        component = app_config.firmware_component
        branch = app_config.firmware_branch
        label = "firmware"
    else:
        component = app_config.daily_component
        branch = app_config.daily_branch
        label = "XTS tests"

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
        for key in ("tag", "component", "role", "package_kind", "archive_path", "extracted_root", "primary_root"):
            value = payload.get(key)
            if value:
                print(f"  {key}: {value}")
        if payload.get("output_tail"):
            print("  output_tail:")
            for line in str(payload["output_tail"]).splitlines():
                print(f"    {line}")
    if written_json_path is not None:
        print(f"json_output_path: {written_json_path}")


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
    progress_callback: Callable[[str], None] | None = None,
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
        "timings_ms": {},
    }
    coverage_candidates: list[dict[str, object]] = []
    report["timings_ms"]["report_setup"] = round((time.perf_counter() - setup_started) * 1000, 3)
    selected_build_targets: list[str] = []
    changed_started = time.perf_counter()
    for changed_file in changed_files:
        if progress_callback:
            progress_callback(f"scoring changed file {repo_rel(changed_file)}")
        rel = repo_rel(changed_file)
        signals = infer_signals(changed_file, sdk_index, content_index, mapping_config)
        effective_variants_mode = resolve_variants_mode(variants_mode, changed_file)
        source_profile = build_source_profile(
            "changed_file",
            rel,
            signals,
            raw_path=changed_file,
        )
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
        shown_project_results = filtered_project_results[:top_projects]
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
        result_item = {
            "changed_file": rel,
            "signals": {
                "modules": sorted(signals["modules"]),
                "symbols": sorted(signals["symbols"]),
                "project_hints": sorted(signals["project_hints"]),
                "method_hints": sorted(signals.get("method_hints", set())),
                "type_hints": sorted(signals.get("type_hints", set())),
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
                    device=device,
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
        unresolved = build_unresolved_analysis(signals, project_results)
        if debug_trace:
            result_item["unresolved_debug"] = unresolved
        if unresolved["reason"]:
            result_item["unresolved_reason"] = unresolved["reason"]
            unresolved_entry = {
                "changed_file": rel,
                "reason": unresolved["reason"],
                "signals": result_item["signals"],
            }
            if debug_trace:
                unresolved_entry["debug"] = unresolved
            report["unresolved_files"].append(unresolved_entry)
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
        shown_project_results = display_project_results[:top_projects]
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
                "symbols": sorted(signals["symbols"]),
                "project_hints": sorted(signals["project_hints"]),
                "method_hints": sorted(signals.get("method_hints", set())),
                "type_hints": sorted(signals.get("type_hints", set())),
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
                    device=device,
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
        device=device,
    )
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
    return (
        f"total={summary.get('total_tests', 0)}, "
        f"passed={summary.get('pass_count', 0)}, "
        f"failed={summary.get('fail_count', 0)}, "
        f"blocked={summary.get('blocked_count', 0)}, "
        f"unknown={summary.get('unknown_count', 0)}"
    )


def _tail_hint(result: dict) -> str:
    if result.get("stderr_tail"):
        return result["stderr_tail"].splitlines()[-1]
    if result.get("stdout_tail") and result.get("status") != "passed":
        return result["stdout_tail"].splitlines()[-1]
    return "-"


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


def _showing_summary_text(relevance_summary: dict[str, object], shown_count: int) -> str:
    shown = int(relevance_summary.get("shown", shown_count))
    total_after = int(relevance_summary.get("total_after", shown_count))
    total_before = int(relevance_summary.get("total_before", total_after))
    filtered_out = int(relevance_summary.get("filtered_out", max(total_before - total_after, 0)))
    text = f"top {shown} of {total_after} matching tests"
    if filtered_out > 0:
        text = f"{text}; {filtered_out} were filtered out by relevance"
    if total_before > total_after:
        text = f"{text}; {total_before} were seen before filtering"
    return f"{text}. Increase --top-projects to see more."


def _daily_selector_arg(flag: str, build_tag: str | None, build_date: str | None) -> list[str]:
    if build_tag:
        result = [flag, build_tag]
        if build_date:
            result.extend([flag.replace("build-tag", "date"), build_date])
        return result
    return [flag.replace("build-tag", "date"), build_date or "<YYYYMMDD>"]


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


def build_next_steps(report: dict, app_config: AppConfig, args: argparse.Namespace) -> list[dict[str, str]]:
    command_name = "arkui-xts-selector"
    sdk_root_exists = Path(str(report.get("sdk_api_root") or "")).exists()
    built_artifacts = report.get("built_artifacts", {})
    has_acts_artifacts = bool(built_artifacts.get("testcases_dir_exists")) and bool(built_artifacts.get("module_info_exists"))
    daily_prebuilt_ready = bool(getattr(app_config, "daily_prebuilt_ready", False))
    selected_targets = int(report.get("execution_overview", {}).get("selected_target_count", 0))
    run_blocked = selected_targets <= 0 or (not has_acts_artifacts and not daily_prebuilt_ready)
    run_block_reason = (
        "No runnable targets were selected."
        if selected_targets <= 0
        else "ACTS artifacts are missing; download tests or prepare build artifacts first."
    )

    steps: list[dict[str, str]] = []
    steps.append(
        {
            "step": "Download SDK",
            "status": "optional" if sdk_root_exists else "recommended",
            "why": (
                "SDK root already exists; use this to switch to another SDK build by tag or date."
                if sdk_root_exists
                else "SDK root is missing or you want to switch SDK version."
            ),
            "command": _shell_join(
                [
                    command_name,
                    "--download-daily-sdk",
                    "--sdk-component",
                    app_config.sdk_component,
                    "--sdk-branch",
                    app_config.sdk_branch,
                    *_daily_selector_arg("--sdk-build-tag", app_config.sdk_build_tag, app_config.sdk_date),
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
                    command_name,
                    "--download-daily-tests",
                    "--daily-component",
                    app_config.daily_component,
                    "--daily-branch",
                    app_config.daily_branch,
                    *_daily_selector_arg("--daily-build-tag", app_config.daily_build_tag, app_config.daily_date),
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
                    command_name,
                    "--download-daily-firmware",
                    "--firmware-component",
                    app_config.firmware_component,
                    "--firmware-branch",
                    app_config.firmware_branch,
                    *_daily_selector_arg("--firmware-build-tag", app_config.firmware_build_tag, app_config.firmware_date),
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
                    command_name,
                    "--flash-daily-firmware",
                    "--firmware-component",
                    app_config.firmware_component,
                    "--firmware-branch",
                    app_config.firmware_branch,
                    *_daily_selector_arg("--firmware-build-tag", app_config.firmware_build_tag, app_config.firmware_date),
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
                    command_name,
                    "--flash-firmware-path",
                    app_config.flash_firmware_path or "<image_bundle_root>",
                    *(["--device", app_config.device] if app_config.device else []),
                ]
            ),
        }
    )

    run_command: list[object] = [command_name, "--repo-root", app_config.repo_root]
    for changed_file in args.changed_file:
        run_command.extend(["--changed-file", changed_file])
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
    if args.git_host_config:
        run_command.extend(["--git-host-config", args.git_host_config])
    if args.gitcode_api_url:
        run_command.extend(["--gitcode-api-url", args.gitcode_api_url])
    run_command.extend(["--variants", args.variants])
    run_command.extend(["--relevance-mode", args.relevance_mode])
    run_command.extend(["--top-projects", args.top_projects])
    if args.keep_per_signature:
        run_command.extend(["--keep-per-signature", args.keep_per_signature])
    if app_config.devices:
        run_command.extend(["--devices", ",".join(app_config.devices)])
    run_command.extend(["--run-now", "--run-tool", args.run_tool])
    if selected_targets > 0:
        run_command.extend(["--run-top-targets", selected_targets])
    if args.run_timeout > 0:
        run_command.extend(["--run-timeout", args.run_timeout])
    steps.append(
        {
            "step": "Run selected tests",
            "status": "blocked" if run_blocked else "ready",
            "why": run_block_reason if run_blocked else f"{selected_targets} selected target(s) are ready to run.",
            "command": _shell_join(run_command),
        }
    )
    return steps


def print_human(report: dict, cache_used: bool | None = None, json_report_path: Path | None = None) -> None:
    def print_coverage_recommendations(recommendations: dict[str, object]) -> None:
        ordered_targets = list(recommendations.get("ordered_targets", []))
        recommended_targets = list(recommendations.get("recommended", []))
        optional_targets = list(recommendations.get("optional_duplicates", []))
        if not ordered_targets and not recommended_targets and not optional_targets:
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
            ("Changed Areas", recommendations.get("source_count", 0)),
            ("Candidate Suites", recommendations.get("candidate_count", 0)),
            ("Recommended", len(recommended_targets)),
            ("Optional Duplicates", len(optional_targets)),
        ]
        uncovered_sources = recommendations.get("uncovered_sources", [])
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
        _print_key_value_section("Coverage Recommendations", coverage_rows)

        def _print_coverage_group(title: str, targets: list[dict[str, object]]) -> None:
            if not targets:
                return
            print(title)
            rows: list[list[object]] = []
            for index, target in enumerate(targets, start=1):
                rows.append(
                    [
                        index,
                        _suite_label(target),
                        target.get("new_coverage_count", 0),
                        target.get("total_coverage_count", 0),
                        target.get("scope_tier", "-"),
                        target.get("variant") or target.get("surface") or "-",
                        target.get("bucket", "-"),
                        _human_preview(_coverage_label_items(target, primary_only=True), limit=4),
                        target.get("coverage_reason", "-"),
                    ]
                )
            _print_human_table(
                ["#", "Suite", "New Coverage", "Total Coverage", "Scope", "Surface", "Priority", "Covers", "Why First"],
                rows,
                indent=2,
            )
            print()
            print("How To Run")
            command_rows: list[list[object]] = []
            command_index = 1
            for target in targets:
                for tool_name, command_key in (
                    ("aa_test", "aa_test_command"),
                    ("xdevice", "xdevice_command"),
                    ("runtest", "runtest_command"),
                ):
                    command = target.get(command_key)
                    if not command:
                        continue
                    command_rows.append(
                        [
                            command_index,
                            _suite_label(target),
                            tool_name,
                            _run_tool_purpose(tool_name),
                            command,
                        ]
                    )
                    command_index += 1
            _print_human_table(["#", "Suite", "Tool", "What It Does", "Command"], command_rows, indent=2)
            print()

        _print_coverage_group("Recommended Run Order", recommended_targets)
        _print_coverage_group("Optional Duplicate Coverage", optional_targets)

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
            for index, target in enumerate(grouped_targets, start=1):
                target_rows.append(
                    [
                        index,
                        _suite_label(target),
                        target.get("scope_tier", "-"),
                        target.get("variant", "-"),
                        target.get("bucket", "-"),
                        _human_preview(target.get("scope_reasons", []), limit=2),
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
                            "-" if result.get("returncode") is None else result.get("returncode"),
                            _format_case_summary(result.get("case_summary")),
                            _tail_hint(result),
                            result.get("result_path") or "-",
                        ]
                    )
            _print_human_table(
                ["#", "Suite", "Scope", "Surface", "Priority", "Why First", "Project"],
                target_rows,
                indent=2,
            )
            print()
            print("How To Run")
            command_rows: list[list[object]] = []
            command_index = 1
            for target in grouped_targets:
                for tool_name, command_key in (
                    ("aa_test", "aa_test_command"),
                    ("xdevice", "xdevice_command"),
                    ("runtest", "runtest_command"),
                ):
                    command = target.get(command_key)
                    if not command:
                        continue
                    command_rows.append(
                        [
                            command_index,
                            _suite_label(target),
                            tool_name,
                            _run_tool_purpose(tool_name),
                            command,
                        ]
                    )
                    command_index += 1
            _print_human_table(["#", "Suite", "Tool", "What It Does", "Command"], command_rows, indent=2)
            print()
            show_plan = bool(result_rows) or any(row[2] != "pending" for row in plan_rows)
            if plan_rows and show_plan:
                print("Execution Plan")
                _print_human_table(["#", "Device", "Status", "Tool", "Available", "Reason", "Result Path"], plan_rows, indent=2)
                print()
            if result_rows:
                print("Execution Results")
                _print_human_table(["#", "Device", "Status", "Tool", "RC", "Case Summary", "Hint", "Result Path"], result_rows, indent=2)
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
        ("SDK API", report.get("sdk_api_root")),
        ("ACE Engine", report.get("git_repo_root")),
        ("ACTS Out", report.get("acts_out_root")),
        ("Mode", report.get("variants_mode", "auto")),
        ("Index Cache", _cache_state_text(cache_used, report.get("cache_file"))),
    ]
    if report.get("ranking_rules_file"):
        summary_rows.append(("Ranking Rules", report.get("ranking_rules_file")))
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
            print("Local Build Commands")
            _print_human_table(["Scope", "Command"], command_rows, indent=2)
            print()

    next_steps = report.get("next_steps", [])
    if next_steps:
        print("Next Steps")
        _print_human_table(
            ["Step", "Status", "Why", "Command"],
            [
                [
                    item.get("step", "-"),
                    item.get("status", "-"),
                    item.get("why", "-"),
                    item.get("command", "-"),
                ]
                for item in next_steps
            ],
            indent=2,
        )
        print()

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
                    f"shard_mode={overview.get('shard_mode', 'mirror')}, "
                    f"unique_targets={overview.get('unique_target_count', 0)}, "
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
                    f"timeout={summary.get('timeout', 0)}, "
                    f"unavailable={summary.get('unavailable', 0)}"
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
            ["Changed File", "Reason", "Matched Prefix"],
            [
                [
                    item.get("changed_file", "-"),
                    item.get("reason", "-"),
                    item.get("matched_prefix", "-"),
                ]
                for item in excluded_inputs
            ],
            indent=2,
        )
        print()

    for item in report["results"]:
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
        if report.get("debug_trace"):
            changed_rows.extend(
                [
                    ("Modules", _human_preview(signals.get("modules", []))),
                    ("Symbols", _human_preview(signals.get("symbols", []))),
                    ("Project Hints", _human_preview(signals.get("project_hints", []))),
                    ("Method Hints", _human_preview(signals.get("method_hints", []))),
                    ("Type Hints", _human_preview(signals.get("type_hints", []))),
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
        print_projects(item["projects"])

    if report["unresolved_files"]:
        print("Unresolved Files")
        _print_human_table(
            ["Changed File", "Reason"],
            [[item.get("changed_file", "-"), item.get("reason", "-")] for item in report["unresolved_files"]],
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
                    ("Project Hints", _human_preview(item["signals"].get("project_hints", []))),
                    ("Method Hints", _human_preview(item["signals"].get("method_hints", []))),
                    ("Type Hints", _human_preview(item["signals"].get("type_hints", []))),
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
    parser.add_argument("--symbol-query", action="append", default=[], help="Find XTS tests by component/symbol name, e.g. ButtonModifier.")
    parser.add_argument("--code-query", action="append", default=[], help="Find code files by keyword, e.g. ButtonModifier.")
    parser.add_argument("--changed-files-from", help="Text file with one changed file path per line.")
    parser.add_argument("--git-diff", help="Optional git diff ref, for example HEAD~1..HEAD.")
    parser.add_argument("--git-root", help="Git root to use with --git-diff.")
    parser.add_argument("--pr-url", help="GitCode PR URL, for example https://gitcode.com/.../pull/82225")
    parser.add_argument("--pr-number", help="GitCode PR number.")
    parser.add_argument(
        "--pr-source",
        choices=PR_SOURCE_CHOICES,
        default="auto",
        help="How to resolve PR changed files: auto prefers GitCode API when token/config is available, api forces API mode, git forces git-fetch mode.",
    )
    parser.add_argument("--git-remote", help="Git remote for PR fetching.")
    parser.add_argument("--git-base-branch", help="Base branch for PR diff. Default: master.")
    parser.add_argument("--gitcode-api-url", help="GitCode base URL for API mode, for example https://gitcode.com")
    parser.add_argument("--gitcode-token", help="GitCode access token for API mode.")
    parser.add_argument("--git-host-config", help="Path to gitee_util/config.ini with [gitcode] token/url.")
    parser.add_argument("--repo-root", help="Explicit OHOS workspace root. By default the CLI auto-discovers the workspace, including sibling ohos_master trees.")
    parser.add_argument("--xts-root", help="Absolute or relative path to XTS root.")
    parser.add_argument("--sdk-api-root", help="Absolute or relative path to SDK api root.")
    parser.add_argument("--acts-out-root", help="Built ACTS output root, for xdevice command generation.")
    parser.add_argument("--path-rules-file", help="Optional JSON file with path and alias mapping rules.")
    parser.add_argument("--composite-mappings-file", help="Optional JSON file with multi-component mapping rules.")
    parser.add_argument("--ranking-rules-file", help="Optional JSON file with family-group, generic-token, umbrella, and planner ranking rules.")
    parser.add_argument("--changed-file-exclusions-file", help="Optional JSON file with changed-file path prefixes to exclude from XTS analysis.")
    parser.add_argument("--device", help="Optional HDC device serial/IP:PORT for generated aa test commands.")
    parser.add_argument("--devices", action="append", default=[], help="Comma-separated device serial list for command generation and execution.")
    parser.add_argument("--devices-from", help="File with one device serial per line (comments with # are ignored).")
    parser.add_argument("--product-name", help="Product name for build guidance. Default: rk3568.")
    parser.add_argument("--system-size", help="System size for build guidance. Default: standard.")
    parser.add_argument("--xts-suitetype", help="Optional xts_suitetype for build guidance, for example hap_static or hap_dynamic.")
    parser.add_argument("--run-now", action="store_true", help="Immediately execute selected run targets after report generation.")
    parser.add_argument("--run-label", help="Optional label for storing this planned/executed selector run, for example baseline or v1.")
    parser.add_argument("--run-store-root", help="Directory used to persist labeled selector runs. Default: <selector_repo>/.runs")
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
    parser.add_argument("--daily-cache-root", help="Cache directory for downloaded/extracted daily full packages. Default: /tmp/arkui_xts_selector_daily_cache")
    parser.add_argument("--download-daily-tests", action="store_true", help="Download and extract the daily XTS package described by --daily-* options, then exit.")
    parser.add_argument("--download-daily-sdk", action="store_true", help="Download and extract the daily SDK package described by --sdk-* options, then exit.")
    parser.add_argument("--download-daily-firmware", action="store_true", help="Download and extract the daily firmware image package described by --firmware-* options, then exit.")
    parser.add_argument("--flash-daily-firmware", action="store_true", help="Download/extract the daily firmware image package described by --firmware-* options and flash it to the connected device, then exit.")
    parser.add_argument("--sdk-build-tag", help="Daily SDK build tag, for example 20260404_120537.")
    parser.add_argument("--sdk-component", help=f"Daily SDK component name. Default: {DEFAULT_SDK_COMPONENT}.")
    parser.add_argument("--sdk-branch", help="Daily SDK branch filter. Default: master.")
    parser.add_argument("--sdk-date", help="Daily SDK build date in YYYYMMDD or YYYY-MM-DD. Defaults to the date derived from --sdk-build-tag.")
    parser.add_argument("--sdk-cache-root", help="Cache directory for downloaded/extracted daily SDK packages. Default: --daily-cache-root")
    parser.add_argument("--firmware-build-tag", help="Daily firmware build tag, for example 20260404_120244.")
    parser.add_argument("--firmware-component", help=f"Daily firmware component name. Default: {DEFAULT_FIRMWARE_COMPONENT}.")
    parser.add_argument("--firmware-branch", help="Daily firmware branch filter. Default: master.")
    parser.add_argument("--firmware-date", help="Daily firmware build date in YYYYMMDD or YYYY-MM-DD. Defaults to the date derived from --firmware-build-tag.")
    parser.add_argument("--firmware-cache-root", help="Cache directory for downloaded/extracted daily firmware packages. Default: --daily-cache-root")
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
    parser.add_argument("--hdc-path", help="Path to hdc used for switching a device into bootloader mode before flashing.")
    parser.add_argument("--run-tool", choices=RUN_TOOL_CHOICES, default="auto", help="Execution tool to use for --run-now. Default: auto.")
    parser.add_argument("--shard-mode", choices=SHARD_MODE_CHOICES, default="mirror", help="Execution distribution mode. mirror = all selected targets on every device; split = shard unique targets across devices.")
    parser.add_argument("--run-top-targets", type=int, default=0, help="Execute at most N unique run targets. 0 = all.")
    parser.add_argument("--run-timeout", type=float, default=0.0, help="Per-command timeout in seconds for --run-now. 0 = disabled.")
    parser.add_argument("--relevance-mode", choices=RELEVANCE_MODE_CHOICES, default="all", help="Filter ranked projects by relevance. all = current behavior, balanced = must-run + high-confidence, strict = must-run only.")
    parser.add_argument("--variants", choices=["auto", "static", "dynamic", "both"], default="auto", help="Filter returned candidates by variant. Default: auto.")
    parser.add_argument("--top-projects", type=int, default=12)
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
    ini_url, ini_token = load_ini_gitcode_config(args.git_host_config or cfg.get("git_host_config"), repo_root)
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
    daily_cache_root = resolve_path(
        args.daily_cache_root or cfg.get("daily_cache_root"),
        DEFAULT_DAILY_CACHE_ROOT,
        selector_repo_root,
    )
    sdk_cache_root = resolve_path(
        args.sdk_cache_root or cfg.get("sdk_cache_root") or str(daily_cache_root),
        daily_cache_root,
        selector_repo_root,
    )
    firmware_cache_root = resolve_path(
        args.firmware_cache_root or cfg.get("firmware_cache_root") or str(daily_cache_root),
        daily_cache_root,
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
        shard_mode=args.shard_mode or cfg.get("shard_mode") or "mirror",
        daily_build_tag=args.daily_build_tag or cfg.get("daily_build_tag"),
        daily_component=args.daily_component or cfg.get("daily_component") or DEFAULT_DAILY_COMPONENT,
        daily_branch=args.daily_branch or cfg.get("daily_branch") or "master",
        daily_date=args.daily_date or cfg.get("daily_date"),
        daily_cache_root=daily_cache_root,
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
    )


def main() -> int:
    global REPO_ROOT
    runtime_started = time.perf_counter()
    args = parse_args()
    progress_enabled = not args.no_progress
    json_to_stdout = bool(args.json)
    json_output_path = None if json_to_stdout else resolve_json_output_path(args.json_out)
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
    if app_config.daily_build_tag or app_config.daily_date:
        emit_progress(progress_enabled, f"preparing daily prebuilt {app_config.daily_build_tag or app_config.daily_date}")
        try:
            prepare_daily_prebuilt_from_config(app_config)
        except (OSError, ValueError, FileNotFoundError, urllib.error.URLError) as exc:
            print(f"daily prebuilt preparation failed: {exc}", file=sys.stderr)
            return 2
    run_session = (
        create_run_session(
            app_config.run_label,
            run_store_root=app_config.run_store_root,
            selector_repo_root=app_config.selector_repo_root,
        )
        if app_config.run_label
        else None
    )
    xdevice_reports_root = (run_session.run_dir / "xdevice_reports") if run_session is not None else None
    changed_inputs = list(args.changed_file)
    symbol_queries = [item.strip() for item in args.symbol_query if item and item.strip()]
    code_queries = [item.strip() for item in args.code_query if item and item.strip()]

    if args.changed_files_from:
        changed_inputs.extend(read_text(resolve_path(args.changed_files_from, app_config.repo_root, app_config.repo_root)).splitlines())

    changed_files = normalize_changed_files(changed_inputs, base_roots=[app_config.repo_root, app_config.git_repo_root])
    if args.git_diff:
        try:
            changed_files.extend(git_changed_files(app_config.git_repo_root, args.git_diff))
        except RuntimeError as exc:
            print(f"git diff failed: {exc}", file=sys.stderr)
            return 2
    if args.pr_url or args.pr_number:
        try:
            pr_ref = args.pr_url or args.pr_number
            changed_files.extend(resolve_pr_changed_files(app_config, pr_ref, args.pr_source))
        except RuntimeError as exc:
            print(f"pr diff failed: {exc}", file=sys.stderr)
            return 2

    deduped: list[Path] = []
    seen = set()
    for item in changed_files:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    changed_files = deduped

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

    progress_callback = (lambda message: emit_progress(progress_enabled, message)) if progress_enabled else None

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
    mapping_config = load_mapping_config(
        path_rules_file=app_config.path_rules_file,
        composite_mappings_file=app_config.composite_mappings_file,
    )
    load_mapping_config_ms = round((time.perf_counter() - mapping_started) * 1000, 3)
    emit_progress(progress_enabled, "building report")
    report_started = time.perf_counter()
    report = format_report(
        changed_files=changed_files,
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
        progress_callback=progress_callback,
    )
    report["acts_out_root"] = str(app_config.acts_out_root or (app_config.repo_root / "out/release/suites/acts"))
    report["excluded_inputs"] = excluded_inputs
    report["timings_ms"].update({
        "changed_file_filtering": changed_file_filtering_ms,
        "load_projects": load_projects_ms,
        "load_sdk_index": load_sdk_index_ms,
        "build_content_modifier_index": build_content_modifier_index_ms,
        "load_mapping_config": load_mapping_config_ms,
        "main_report_call": round((time.perf_counter() - report_started) * 1000, 3),
    })
    report["timings_ms"]["total_runtime"] = round((time.perf_counter() - runtime_started) * 1000, 3)
    report["json_output_mode"] = "stdout" if json_to_stdout else "file"
    report["requested_devices"] = list(app_config.devices)
    if app_config.daily_prebuilt is not None:
        report["daily_prebuilt"] = {
            **app_config.daily_prebuilt.to_dict(),
            "note": app_config.daily_prebuilt_note,
        }
    if json_output_path is not None:
        report["json_output_path"] = str(json_output_path)
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
    )
    report["next_steps"] = build_next_steps(report, app_config, args)
    execution_summary = None
    execution_preflight = None
    preflight_failed = False
    if args.run_now:
        emit_progress(progress_enabled, "preflighting execution")
        execution_preflight = preflight_execution(
            report,
            repo_root=app_config.repo_root,
            devices=app_config.devices,
        )
        report["execution_preflight"] = execution_preflight
        if execution_preflight.get("status") != "passed":
            preflight_failed = True
        else:
            emit_progress(progress_enabled, "running selected targets")
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
            )
    else:
        report["execution_preflight"] = {}

    if run_session is not None:
        status = "planned"
        if preflight_failed:
            status = "failed_preflight"
        elif execution_summary is not None:
            status = "completed_with_failures" if execution_summary.get("has_failures") else "completed"
        report["selector_run"]["status"] = status

    emit_progress(progress_enabled, "writing JSON report")
    written_json_path = write_json_report(report, json_to_stdout=json_to_stdout, json_output_path=json_output_path)
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
        print_human(report, cache_used, written_json_path)
    if args.run_now and preflight_failed:
        return 2
    if args.run_now and execution_summary and execution_summary.get("has_failures"):
        return 1
    return 0


def main_entry() -> None:
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
