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

from .build_state import (
    build_aa_test_command,
    build_guidance,
    build_runtest_command,
    build_xdevice_command,
    inspect_product_build,
)
from .built_artifacts import inspect_built_artifacts, load_built_artifact_index
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

UBIQUITOUS_BASES = {"button", "text", "column", "row", "toggle", "stack", "flex"}
COMMON_PROJECT_HINTS = ("commonattrs", "modifier", "interactiveattributes", "dragcontrol", "focuscontrol")
GENERIC_PATH_TOKENS = {
    "ace", "arkui", "ani", "component", "components", "core", "cpp", "engine", "ets",
    "foundation", "frameworks", "interfaces", "pattern", "src",
}
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
    "web":                  ["Web", "WebviewController", "RichText"],
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


def compact_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


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
    parser.read(path, encoding="utf-8")
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
    gitcode_api_url: str | None = None
    gitcode_token: str | None = None
    acts_out_root: Path | None = None
    path_rules_file: Path | None = None
    composite_mappings_file: Path | None = None
    changed_file_exclusions_file: Path | None = None
    product_name: str | None = None
    system_size: str = "standard"
    xts_suitetype: str | None = None


@dataclass
class TestFileIndex:
    relative_path: str
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

    def to_dict(self) -> dict:
        return {
            "relative_root": self.relative_root,
            "test_json": self.test_json,
            "bundle_name": self.bundle_name,
            "path_key": self.path_key,
            "variant": self.variant,
            "files": [item.to_dict() for item in self.files],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestProjectIndex":
        return cls(
            relative_root=data["relative_root"],
            test_json=data["test_json"],
            bundle_name=data.get("bundle_name"),
            path_key=data["path_key"],
            variant=data.get("variant", "unknown"),
            files=[TestFileIndex.from_dict(item) for item in data["files"]],
        )



def repo_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def normalize_changed_files(values: Iterable[str]) -> list[Path]:
    result: list[Path] = []
    for value in values:
        raw = value.strip()
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = REPO_ROOT / raw
        result.append(path.resolve())
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
    return normalize_changed_files(completed.stdout.splitlines())


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
    match = re.search(r"/pull/(\d+)", parsed.path)
    if not match:
        raise RuntimeError(f"could not parse PR number from URL: {pr_url}")
    return match.group(1)


def parse_owner_repo_from_pr(pr_ref: str) -> tuple[str, str] | None:
    if pr_ref.isdigit():
        return None
    parsed = urlparse(pr_ref)
    match = re.search(r"/([^/]+)/([^/]+)/pull/\d+", parsed.path)
    if not match:
        return None
    return match.group(1), match.group(2)


def fetch_pr_changed_files(repo_root: Path, remote: str, base_branch: str, pr_ref: str) -> list[Path]:
    pr_number = parse_pr_number(pr_ref)
    fetch_specs = [
        f"refs/pull/{pr_number}/head",
        f"pull/{pr_number}/head",
        f"refs/merge-requests/{pr_number}/head",
    ]
    last_error = "unknown fetch error"
    for spec in fetch_specs:
        completed = run_git(repo_root, ["fetch", "--depth=1", remote, spec])
        if completed.returncode == 0:
            diff = run_git(repo_root, ["diff", "--name-only", f"{remote}/{base_branch}...FETCH_HEAD"])
            if diff.returncode != 0:
                raise RuntimeError(diff.stderr.strip() or "git diff failed")
            return normalize_changed_files(diff.stdout.splitlines())
        last_error = completed.stderr.strip() or completed.stdout.strip() or last_error
    raise RuntimeError(last_error)


def fetch_pr_changed_files_via_api(api_url: str, token: str, owner: str, repo: str, pr_ref: str) -> list[Path]:
    pr_number = parse_pr_number(pr_ref)
    base = api_url.rstrip("/")
    requests_to_try = [
        urllib.request.Request(
            f"{base}/api/v5/repos/{owner}/{repo}/pulls/{pr_number}/files?{urllib.parse.urlencode({'access_token': token})}",
            headers={"Accept": "application/json"},
        ),
        urllib.request.Request(
            f"{base}/api/v5/repos/{owner}/{repo}/pulls/{pr_number}/files",
            headers={"Accept": "application/json", "private-token": token},
        ),
    ]
    data = None
    last_error = "gitcode api failed"
    for request in requests_to_try:
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
                break
        except urllib.error.URLError as exc:
            last_error = f"gitcode api failed: {exc}"
        except json.JSONDecodeError as exc:
            last_error = f"gitcode api returned invalid json: {exc}"
    if data is None:
        raise RuntimeError(last_error)

    if not isinstance(data, list):
        raise RuntimeError(f"gitcode api unexpected response: {data}")

    changed_files: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        path_value = item.get("filename") or item.get("new_path") or item.get("old_path")
        if path_value:
            changed_files.append(path_value)
    return normalize_changed_files(changed_files)


def parse_test_file(path: Path) -> TestFileIndex:
    text = read_text(path)
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


def classify_project_variant(relative_root: str, test_file_names: list[str]) -> str:
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
        projects.append(
            TestProjectIndex(
                relative_root=relative_root,
                test_json=test_json_rel,
                bundle_name=parse_bundle_name(test_json),
                files=files,
                path_key=str(root.relative_to(xts_root)).replace(os.sep, "/").lower(),
                variant=classify_project_variant(relative_root, test_file_names),
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
    return TestProjectIndex(
        relative_root=relative_root,
        test_json=test_json_rel,
        bundle_name=parse_bundle_name(test_json),
        files=files,
        path_key=str(root.relative_to(xts_root)).replace(os.sep, "/").lower(),
        variant=classify_project_variant(relative_root, test_file_names),
    )


def load_or_build_projects(xts_root: Path, cache_file: Path | None) -> tuple[list[TestProjectIndex], bool]:
    CACHE_VERSION = 2

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
                projects.append(project)
                new_cache[rel_key] = old_cache[rel_key]
                cache_hits += 1
                continue
            except (KeyError, TypeError):
                pass

        # Cache miss — rebuild
        project = _build_single_project(test_json, root, xts_root)
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
        if family in sdk_index.component_file_bases:
            signals["symbols"].add(sdk_index.component_file_bases[family])
            signals["project_hints"].add(family)
        if family in sdk_index.modifier_file_bases:
            signals["symbols"].add(sdk_index.modifier_file_bases[family])
            signals["project_hints"].add(family)

    native_suffixes = {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh"}
    if changed_file.suffix.lower() in native_suffixes:
        text = read_text(changed_file)
        text_lower = text.lower()
        dynamic_modules = {match for match in DYNAMIC_MODULE_RE.findall(text)}

        for match in OHOS_MODULE_RE.findall(text):
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


def variant_matches(project_variant: str, variants_mode: str) -> bool:
    if variants_mode in {'auto', 'both'}:
        return True
    if project_variant in {'both', 'unknown'}:
        # 'both': explicitly covers both variants.
        # 'unknown': no variant marker was found (no _static/_dynamic suffix, no HAP name
        # pattern). For a high-recall selector these suites must never be silently dropped —
        # an unknown variant is not the same as "wrong variant".
        return True
    return project_variant == variants_mode


def resolve_variants_mode(variants_mode: str, changed_file: Path | None = None) -> str:
    if variants_mode != 'auto':
        return variants_mode
    if changed_file is None:
        return 'both'
    rel = repo_rel(changed_file).lower()
    compact_parts = path_component_tokens(rel)
    if 'static' in compact_parts or '_static' in rel or '/static/' in rel:
        return 'static'
    if (
        'dynamic' in compact_parts
        or '_dynamic' in rel
        or '/dynamic/' in rel
        or '/bridge/' in rel
        or '/interfaces/ets/ani/' in rel
    ):
        return 'dynamic'
    # Pattern implementation files (components_ng/pattern/) implement static rendering;
    # they do not belong to the bridge layer, so dynamic-only tests are not relevant.
    if '/components_ng/pattern/' in rel:
        return 'static'
    return 'both'


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
    parts = tokenize_path_parts(query)
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

    for key, rule in mapping_config.composite_mappings.items():
        compact_key = compact_token(key)
        # Token-based matching: exact compact match OR all key tokens present
        # in query tokens. Prevents short queries like "content" from matching
        # "content_modifier_helper_accessor".
        key_tokens = {compact_token(t) for t in tokenize_path_parts(key) if compact_token(t)}
        query_tokens = {compact_token(t) for t in tokenize_path_parts(query) if compact_token(t)}
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
        "built_artifacts": built_artifacts,
        "built_artifact_index": built_artifact_index,
        "product_build": product_build,
        "cache_used": cache_used,
        "debug_trace": debug_trace,
        "variants_mode": variants_mode,
        "excluded_inputs": [],
        "results": [],
        "symbol_queries": [],
        "code_queries": [],
        "unresolved_files": [],
        "timings_ms": {},
    }
    report["timings_ms"]["report_setup"] = round((time.perf_counter() - setup_started) * 1000, 3)
    selected_build_targets: list[str] = []
    changed_started = time.perf_counter()
    for changed_file in changed_files:
        if progress_callback:
            progress_callback(f"scoring changed file {repo_rel(changed_file)}")
        rel = repo_rel(changed_file)
        signals = infer_signals(changed_file, sdk_index, content_index, mapping_config)
        effective_variants_mode = resolve_variants_mode(variants_mode, changed_file)
        project_results = []
        candidate_projects = [project for project in projects if variant_matches(project.variant, effective_variants_mode)]
        for project in candidate_projects:
            score, project_reasons, file_hits = score_project(project, signals)
            if score <= 0:
                continue
            _nlx = project_has_non_lexical_evidence(project_reasons, file_hits)
            _bucket = candidate_bucket(score, _nlx)
            project_entry = {
                # Only 'possible related' suites (call-only, no explicit import)
                # are eligible for coverage deduplication. Must-run and
                # high-confidence suites always pass through so that every
                # explicitly-tested suite is preserved regardless of keep_per_signature.
                "_coverage_sig": coverage_signature(file_hits, project_path_key=project.path_key) if _bucket == "possible related" else None,
                "score": score,
                "confidence": confidence(score),
                "bucket": _bucket,
                "variant": project.variant,
                "project": project.relative_root,
                "test_json": project.test_json,
                "bundle_name": project.bundle_name,
                "driver_module_name": driver_module_name(project.test_json, repo_root=app_config.repo_root),
                "driver_type": driver_type(project.test_json, repo_root=app_config.repo_root),
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
        project_results.sort(key=lambda item: (-item["score"], item["project"]))
        project_results = deduplicate_by_coverage_signature(project_results, keep_per_signature)
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
            "effective_variants_mode": effective_variants_mode,
            "projects": project_results[:top_projects],
            "run_targets": [
                {
                    "project": item["project"],
                    "test_json": item["test_json"],
                    "bundle_name": item["bundle_name"],
                    "driver_module_name": item["driver_module_name"],
                    "test_haps": parse_test_file_names(item["test_json"], repo_root=app_config.repo_root),
                    "xdevice_module_name": infer_xdevice_module_name(item["test_json"], repo_root=app_config.repo_root),
                    "build_target": guess_build_target(item["project"]),
                    "driver_type": item["driver_type"],
                    "confidence": item["confidence"],
                    "bucket": item["bucket"],
                    "variant": item["variant"],
                    "aa_test_command": build_aa_test_command(
                        bundle_name=item["bundle_name"],
                        module_name=item["driver_module_name"],
                        project_path=item["project"],
                        device=device,
                    ),
                    "xdevice_command": build_xdevice_command(
                        repo_root=REPO_ROOT,
                        module_name=infer_xdevice_module_name(item["test_json"], repo_root=app_config.repo_root),
                        device=device,
                        acts_out_root=acts_out_root,
                    ),
                    "runtest_command": build_runtest_command(
                        build_target=guess_build_target(item["project"]),
                        device=device,
                    ),
                }
                for item in project_results[:top_projects]
            ],
        }
        if debug_trace:
            result_item["debug"] = {
                "candidate_project_count": len(candidate_projects),
                "matched_project_count": len(project_results),
            }
        selected_build_targets.extend(
            guess_build_target(item["project"]) for item in project_results[:top_projects]
        )
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
        effective_variants_mode = resolve_variants_mode(variants_mode)
        project_results = []
        candidate_projects = [project for project in projects if variant_matches(project.variant, effective_variants_mode)]
        for project in candidate_projects:
            score, project_reasons, file_hits = score_project(project, signals)
            if score <= 0:
                continue
            _nlx = project_has_non_lexical_evidence(project_reasons, file_hits)
            _bucket = candidate_bucket(score, _nlx)
            project_entry = {
                "_coverage_sig": coverage_signature(file_hits, project_path_key=project.path_key) if _bucket == "possible related" else None,
                "score": score,
                "confidence": confidence(score),
                "bucket": _bucket,
                "variant": project.variant,
                "project": project.relative_root,
                "test_json": project.test_json,
                "bundle_name": project.bundle_name,
                "driver_module_name": driver_module_name(project.test_json, repo_root=app_config.repo_root),
                "test_haps": parse_test_file_names(project.test_json, repo_root=app_config.repo_root),
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
        project_results.sort(key=lambda item: (-item["score"], item["project"]))
        project_results = deduplicate_by_coverage_signature(project_results, keep_per_signature)
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
            "code_search_evidence": explain_symbol_query_sources(query, xts_root),
            "effective_variants_mode": effective_variants_mode,
            "projects": project_results[:top_projects],
        }
        if debug_trace:
            symbol_item["debug"] = {
                "candidate_project_count": len(candidate_projects),
                "matched_project_count": len(project_results),
            }
        report["symbol_queries"].append(symbol_item)
        selected_build_targets.extend(
            guess_build_target(item["project"]) for item in project_results[:top_projects]
        )
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
    if progress_callback:
        progress_callback("assembling build guidance")
    guidance_started = time.perf_counter()
    guidance = build_guidance(REPO_ROOT, report["built_artifacts"], report["product_build"], app_config, selected_build_targets)
    report["timings_ms"]["build_guidance"] = round((time.perf_counter() - guidance_started) * 1000, 3)
    if guidance:
        report["build_guidance"] = guidance
    report["timings_ms"]["report_total"] = round(sum(report["timings_ms"].values()), 3)
    return report


def print_human(report: dict, cache_used: bool | None = None, json_report_path: Path | None = None) -> None:
    print(f"repo_root: {report['repo_root']}")
    print(f"xts_root: {report['xts_root']}")
    print(f"sdk_api_root: {report['sdk_api_root']}")
    print(f"git_repo_root: {report['git_repo_root']}")
    print(f"acts_out_root: {report['acts_out_root']}")
    print(f"variants_mode: {report.get('variants_mode', 'auto')}")
    if json_report_path is not None:
        print(f"json_report: {json_report_path}")
    product_build = report["product_build"]
    print(
        "product_build: "
        f"status={product_build.get('status', '-')}, "
        f"out_dir_exists={'yes' if product_build.get('out_dir_exists') else 'no'}, "
        f"build_log_exists={'yes' if product_build.get('build_log_exists') else 'no'}, "
        f"error_log_exists={'yes' if product_build.get('error_log_exists') else 'no'}, "
        f"error_log_size={product_build.get('error_log_size', 0)}"
    )
    if product_build.get("reason"):
        print(f"product_build_reason: {product_build['reason']}")
    built = report["built_artifacts"]
    print(
        "built_artifacts: "
        f"status={built.get('status', '-')}, "
        f"testcases_dir_exists={'yes' if built['testcases_dir_exists'] else 'no'}, "
        f"module_info_exists={'yes' if built['module_info_exists'] else 'no'}, "
        f"testcase_json_count={built['testcase_json_count']}, "
        f"module_info_entry_count={built.get('module_info_entry_count', 0)}"
    )
    artifact_index = report.get("built_artifact_index", {})
    if artifact_index:
        print(
            "built_artifact_index: "
            f"status={artifact_index.get('status', '-')}, "
            f"testcase_modules={artifact_index.get('testcase_modules_count', 0)}, "
            f"hap_runtime_modules={artifact_index.get('hap_runtime_modules_count', 0)}"
        )
    if report.get("build_guidance"):
        guidance = report["build_guidance"]
        print(f"build_required: {'yes' if guidance['required'] else 'no'}")
        print(f"build_reason: {guidance['reason']}")
        if guidance.get('code_build_required'):
            print(f"build_code_command: {guidance['full_code_build_command']}")
        if guidance.get('acts_build_required'):
            print(f"build_acts_command: {guidance['full_acts_build_command']}")
        for command in guidance["target_build_commands"][:5]:
            print(f"build_target_command: {command}")
    if cache_used is None:
        cache_used = bool(report.get("cache_used"))
    print(f"cache_used: {'yes' if cache_used else 'no'}")
    timings = report.get("timings_ms", {})
    if timings:
        timing_parts = [f"{key}={value}" for key, value in timings.items()]
        print(f"timings_ms: {', '.join(timing_parts)}")
    excluded_inputs = report.get("excluded_inputs", [])
    if excluded_inputs:
        print(f"excluded_inputs: {len(excluded_inputs)}")
        for item in excluded_inputs:
            print(f"  {item['changed_file']}: {item['reason']} ({item.get('matched_prefix', '-')})")
    print()
    for item in report["results"]:
        print(f"changed_file: {item['changed_file']}")
        signals = item["signals"]
        print(f"  modules: {', '.join(signals['modules']) or '-'}")
        print(f"  symbols: {', '.join(signals['symbols']) or '-'}")
        print(f"  project_hints: {', '.join(signals['project_hints']) or '-'}")
        print(f"  method_hints: {', '.join(signals.get('method_hints', [])) or '-'}")
        print(f"  type_hints: {', '.join(signals.get('type_hints', [])) or '-'}")
        print(f"  family_tokens: {', '.join(signals['family_tokens']) or '-'}")
        if item.get("unresolved_reason"):
            print(f"  unresolved: {item['unresolved_reason']}")
        if item.get("debug"):
            debug = item["debug"]
            print(f"  debug: candidate_projects={debug['candidate_project_count']}, matched_projects={debug['matched_project_count']}")
        if report.get("debug_trace") and item.get("unresolved_debug"):
            debug = item["unresolved_debug"]
            print(f"  unresolved_debug: top_score={debug['top_score']}, broad_common_hits={debug['broad_common_hits']}")
        if not item["projects"]:
            print("  no candidate XTS projects found")
            print()
            continue
        print("  run_targets:")
        for target in item["run_targets"]:
            bundle = target["bundle_name"] or "-"
            print(f"    {target['test_json']}  [bundle={bundle}, variant={target['variant']}, bucket={target['bucket']}, confidence={target['confidence']}]")
            if target["test_haps"]:
                print(f"      test_haps: {', '.join(target['test_haps'])}")
            if target["aa_test_command"]:
                print(f"      aa_test: {target['aa_test_command']}")
            if target["xdevice_command"]:
                print(f"      xdevice: {target['xdevice_command']}")
            if target["runtest_command"]:
                print(f"      runtest: {target['runtest_command']}")
        for project in item["projects"]:
            bundle = project["bundle_name"] or "-"
            print(
                f"  project: {project['project']}  "
                f"[score={project['score']}, bucket={project['bucket']}, variant={project['variant']}, confidence={project['confidence']}, bundle={bundle}]"
            )
            print(f"    test_json: {project['test_json']}")
            if project["reasons"]:
                print(f"    reasons: {', '.join(project['reasons'])}")
            for test_file in project["test_files"]:
                print(f"    file: {test_file['file']} [score={test_file['score']}]")
                if test_file["reasons"]:
                    print(f"      reasons: {', '.join(test_file['reasons'])}")
        print()
    if report["unresolved_files"]:
        print("unresolved_files:")
        for item in report["unresolved_files"]:
            print(f"  {item['changed_file']}: {item['reason']}")
        print()
    for item in report["symbol_queries"]:
        print(f"symbol_query: {item['query']}")
        signals = item["signals"]
        print(f"  symbols: {', '.join(signals['symbols']) or '-'}")
        print(f"  project_hints: {', '.join(signals['project_hints']) or '-'}")
        print(f"  method_hints: {', '.join(signals.get('method_hints', [])) or '-'}")
        print(f"  type_hints: {', '.join(signals.get('type_hints', [])) or '-'}")
        if item.get("debug"):
            debug = item["debug"]
            print(f"  debug: candidate_projects={debug['candidate_project_count']}, matched_projects={debug['matched_project_count']}")
        evidence = item.get("code_search_evidence", {})
        if evidence.get("exact_hits") or evidence.get("related_hits"):
            print("  code_search_evidence:")
            for match in evidence.get("exact_hits", [])[:5]:
                print(f"    exact: {match}")
            for match in evidence.get("related_hits", [])[:5]:
                print(f"    related: {match}")
        if not item["projects"]:
            print("  no candidate XTS projects found")
            print()
            continue
        for project in item["projects"]:
            bundle = project["bundle_name"] or "-"
            print(
                f"  project: {project['project']} "
                f"[score={project['score']}, confidence={project['confidence']}, bundle={bundle}]"
            )
            print(f"    test_json: {project['test_json']}")
            if project["test_haps"]:
                print(f"    test_haps: {', '.join(project['test_haps'])}")
            for test_file in project["test_files"]:
                print(f"    file: {test_file['file']} [score={test_file['score']}]")
                if test_file["reasons"]:
                    print(f"      reasons: {', '.join(test_file['reasons'])}")
        print()
    for item in report["code_queries"]:
        print(f"code_query: {item['query']}")
        if not item["matches"]:
            print("  no code matches found")
            print()
            continue
        for match in item["matches"]:
            print(f"  file: {match['file']} [score={match['score']}]")
            if match["reasons"]:
                print(f"    reasons: {', '.join(match['reasons'])}")
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
    parser.add_argument("--git-remote", help="Git remote for PR fetching.")
    parser.add_argument("--git-base-branch", help="Base branch for PR diff. Default: master.")
    parser.add_argument("--gitcode-api-url", help="GitCode base URL for API mode, for example https://gitcode.com")
    parser.add_argument("--gitcode-token", help="GitCode access token for API mode.")
    parser.add_argument("--git-host-config", help="Path to gitee_util/config.ini with [gitcode] token/url.")
    parser.add_argument("--xts-root", help="Absolute or relative path to XTS root.")
    parser.add_argument("--sdk-api-root", help="Absolute or relative path to SDK api root.")
    parser.add_argument("--acts-out-root", help="Built ACTS output root, for xdevice command generation.")
    parser.add_argument("--path-rules-file", help="Optional JSON file with path and alias mapping rules.")
    parser.add_argument("--composite-mappings-file", help="Optional JSON file with multi-component mapping rules.")
    parser.add_argument("--changed-file-exclusions-file", help="Optional JSON file with changed-file path prefixes to exclude from XTS analysis.")
    parser.add_argument("--device", help="Optional HDC device serial/IP:PORT for generated aa test commands.")
    parser.add_argument("--product-name", help="Product name for build guidance, for example rk3568 or m40.")
    parser.add_argument("--system-size", help="System size for build guidance. Default: standard.")
    parser.add_argument("--xts-suitetype", help="Optional xts_suitetype for build guidance, for example hap_static or hap_dynamic.")
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
    repo_root = discover_repo_root()
    cfg = load_json_file(resolve_path(args.config, repo_root, repo_root)) if args.config else {}
    repo_root = resolve_path(cfg.get("repo_root"), repo_root, repo_root) if cfg.get("repo_root") else repo_root
    ini_url, ini_token = load_ini_gitcode_config(args.git_host_config or cfg.get("git_host_config"), repo_root)
    xts_root = resolve_path(args.xts_root or cfg.get("xts_root"), default_xts_root(repo_root), repo_root)
    sdk_api_root = resolve_path(args.sdk_api_root or cfg.get("sdk_api_root"), default_sdk_api_root(repo_root), repo_root)
    git_repo_root = resolve_path(args.git_root or cfg.get("git_repo_root"), default_git_repo_root(repo_root), repo_root)
    git_remote = args.git_remote or cfg.get("git_remote") or "gitcode"
    git_base_branch = args.git_base_branch or cfg.get("git_base_branch") or "master"
    device = args.device or cfg.get("device")
    product_name = args.product_name or cfg.get("product_name")
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
    changed_file_exclusions_file = resolve_path(
        args.changed_file_exclusions_file or cfg.get("changed_file_exclusions_file"),
        default_changed_file_exclusions_file() or repo_root,
        repo_root,
    ) if (args.changed_file_exclusions_file or cfg.get("changed_file_exclusions_file") or default_changed_file_exclusions_file()) else None
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
        gitcode_api_url=gitcode_api_url,
        gitcode_token=gitcode_token,
        acts_out_root=acts_out_root,
        path_rules_file=path_rules_file,
        composite_mappings_file=composite_mappings_file,
        changed_file_exclusions_file=changed_file_exclusions_file,
        product_name=product_name,
        system_size=system_size,
        xts_suitetype=xts_suitetype,
    )


def main() -> int:
    global REPO_ROOT
    runtime_started = time.perf_counter()
    args = parse_args()
    app_config = load_app_config(args)
    REPO_ROOT = app_config.repo_root
    changed_inputs = list(args.changed_file)
    symbol_queries = [item.strip() for item in args.symbol_query if item and item.strip()]
    code_queries = [item.strip() for item in args.code_query if item and item.strip()]

    if args.changed_files_from:
        changed_inputs.extend(read_text(resolve_path(args.changed_files_from, app_config.repo_root, app_config.repo_root)).splitlines())

    changed_files = normalize_changed_files(changed_inputs)
    if args.git_diff:
        try:
            changed_files.extend(git_changed_files(app_config.git_repo_root, args.git_diff))
        except RuntimeError as exc:
            print(f"git diff failed: {exc}", file=sys.stderr)
            return 2
    if args.pr_url or args.pr_number:
        try:
            pr_ref = args.pr_url or args.pr_number
            owner_repo = parse_owner_repo_from_pr(pr_ref)
            if app_config.gitcode_api_url and app_config.gitcode_token and owner_repo:
                changed_files.extend(
                    fetch_pr_changed_files_via_api(
                        api_url=app_config.gitcode_api_url,
                        token=app_config.gitcode_token,
                        owner=owner_repo[0],
                        repo=owner_repo[1],
                        pr_ref=pr_ref,
                    )
                )
            else:
                changed_files.extend(
                    fetch_pr_changed_files(
                        repo_root=app_config.git_repo_root,
                        remote=app_config.git_remote,
                        base_branch=app_config.git_base_branch,
                        pr_ref=pr_ref,
                    )
                )
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

    progress_enabled = not args.no_progress
    progress_callback = (lambda message: emit_progress(progress_enabled, message)) if progress_enabled else None
    json_to_stdout = bool(args.json)
    json_output_path = None if json_to_stdout else resolve_json_output_path(args.json_out)

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
        keep_per_signature=args.keep_per_signature,
        cache_used=cache_used,
        debug_trace=args.debug_trace,
        progress_callback=progress_callback,
    )
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
    if json_output_path is not None:
        report["json_output_path"] = str(json_output_path)

    emit_progress(progress_enabled, "writing JSON report")
    written_json_path = write_json_report(report, json_to_stdout=json_to_stdout, json_output_path=json_output_path)

    if not json_to_stdout:
        emit_progress(progress_enabled, "rendering human report")
        print_human(report, cache_used, written_json_path)
    return 0


def main_entry() -> None:
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
