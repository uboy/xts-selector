from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .api_surface import compact_token
from .runtime_state import ensure_runtime_state_root


SCHEMA_VERSION = 2
API_LINEAGE_FILENAME = f"api_lineage_map.v{SCHEMA_VERSION}.json"
LINEAGE_CACHE_SIGNATURE_VERSION = 1
SOURCE_SCAN_ROOTS = (
    Path("frameworks/bridge/declarative_frontend/ark_modifier/src"),
    Path("frameworks/core/interfaces/native/node"),
    Path("frameworks/core/interfaces/native/implementation"),
    Path("frameworks/core/components_ng/pattern"),
)
SOURCE_FILE_SUFFIXES = {
    ".ts",
    ".js",
    ".ets",
    ".cpp",
    ".cc",
    ".cxx",
    ".c",
    ".hpp",
    ".hxx",
    ".hh",
    ".h",
}
SDK_COMPONENT_SKIP = {"common", "builder", "enums", "units", "resources"}
SOURCE_CONSUMER_ROOTS = (
    Path("foundation/arkui/ace_engine/examples"),
)
SOURCE_CONSUMER_SKIP_DIRS = {".git", ".ohpm", "node_modules", "oh_modules", "out", "hvigor", "AppScope"}
COMPONENT_ATTRIBUTE_METHOD_ALLOWLIST: dict[str, set[str]] = {
    "button": {"role", "buttonStyle", "controlSize", "contentModifier"},
    "checkbox": {"contentModifier"},
    "checkboxgroup": {"contentModifier"},
    "datapanel": {"contentModifier"},
    "gauge": {"contentModifier"},
    "loadingprogress": {"contentModifier"},
    "progress": {"contentModifier"},
    "radio": {"contentModifier"},
    "rating": {"contentModifier"},
    "select": {"menuItemContentModifier"},
    "slider": {"contentModifier"},
    "textclock": {"contentModifier"},
    "texttimer": {"contentModifier"},
    "toggle": {"contentModifier"},
}
INHERITED_COMMON_METHOD_ALLOWLIST: dict[str, set[str]] = {
    "button": {"padding"},
}
ENTITY_SUFFIXES = ("Modifier", "Attribute", "Configuration", "Controller")
INTERFACE_DECL_RE = re.compile(
    r"export\s+declare\s+interface\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:extends\s+([^{]+))?\s*\{",
    re.M,
)
INTERFACE_METHOD_RE = re.compile(
    r"^\s*(?:default\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*:\s*[^;]+;\s*$",
    re.M,
)
IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
IMPORT_BINDING_RE = re.compile(r"""import\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""", re.S)
DEFAULT_IMPORT_RE = re.compile(r"""import\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+['"]([^'"]+)['"]""")
IDENTIFIER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\s*\(""")
MEMBER_CALL_RE = re.compile(r"""\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
TYPE_MEMBER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
TYPED_ATTRIBUTE_MODIFIER_RE = re.compile(r"""AttributeModifier<([A-Za-z_][A-Za-z0-9_]*)Attribute>""")
EXTENDS_MODIFIER_RE = re.compile(r"""extends\s+([A-Za-z_][A-Za-z0-9_]*)Modifier\b""")
SOURCE_SYMBOL_HEADER_RE = re.compile(
    r"""
    ^\s*
    (?:
        (?:template\s*<[^>]+>\s*)|
        (?:(?:public|private|protected|static|virtual|inline|constexpr|friend|explicit|extern|async|readonly|override|final)\s+)|
        (?:[\w:<>,~*&\[\]\s]+\s+)
    )*
    (?P<name>(?:[A-Za-z_~][A-Za-z0-9_]*::)*[A-Za-z_~][A-Za-z0-9_]*)
    \s*\(
    """,
    re.X,
)
CONTROL_FLOW_SYMBOLS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "sizeof",
    "else",
    "do",
}

# Phase 2 P2-003: Source member extraction patterns
# Parse export interface TypeName { method1(): void; method2(value: X): this; }
SOURCE_MEMBER_DECL_RE = re.compile(
    r"^\s*(?:default\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*:\s*[^;]+;\s*$",
    re.M,
)
# Parse export function someFunction(): void
SOURCE_FUNCTION_DECL_RE = re.compile(
    r"export\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
)
# Parse proxy bind methods: bindPopup, bindSheet, bindContextMenu
PROXY_BIND_METHOD_RE = re.compile(
    r"\b(bind[A-Z][A-Za-z0-9_]*)\s*\(",
)
# Parse event declarations in interfaces: eventType?: ClickEvent
EVENT_DECL_RE = re.compile(
    r"(?:readonly\s+)?(\w+)\s*:\s*(ClickEvent|KeyEvent|TouchEvent|LongPressEvent|PanGesture|PinchGesture|RotationGesture|SwipeGesture)\b",
)


@dataclass(frozen=True)
class ExplicitSourceFanoutRule:
    family: str
    method_name: str
    symbol_hints: tuple[str, ...]


EXPLICIT_SOURCE_FANOUT_RULES: dict[str, tuple[ExplicitSourceFanoutRule, ...]] = {
    "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp": (
        ExplicitSourceFanoutRule(
            family="button",
            method_name="contentModifier",
            symbol_hints=("ContentModifierButtonImpl", "ResetContentModifierButtonImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="checkbox",
            method_name="contentModifier",
            symbol_hints=("ContentModifierCheckBoxImpl", "ResetContentModifierCheckBoxImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="checkboxgroup",
            method_name="contentModifier",
            symbol_hints=("ContentModifierCheckBoxGroupImpl", "ResetContentModifierCheckBoxGroupImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="datapanel",
            method_name="contentModifier",
            symbol_hints=("ContentModifierDataPanelImpl", "ResetContentModifierDataPanelImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="gauge",
            method_name="contentModifier",
            symbol_hints=("ContentModifierGaugeImpl", "ResetContentModifierGaugeImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="loadingprogress",
            method_name="contentModifier",
            symbol_hints=("ContentModifierLoadingProgressImpl", "ResetContentModifierLoadingProgressImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="progress",
            method_name="contentModifier",
            symbol_hints=("ContentModifierProgressImpl", "ResetContentModifierProgressImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="radio",
            method_name="contentModifier",
            symbol_hints=("ContentModifierRadioImpl", "ResetContentModifierRadioImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="rating",
            method_name="contentModifier",
            symbol_hints=("ContentModifierRatingImpl", "ResetContentModifierRatingImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="select",
            method_name="menuItemContentModifier",
            symbol_hints=("ContentModifierMenuItemImpl", "ResetContentModifierMenuItemImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="slider",
            method_name="contentModifier",
            symbol_hints=("ContentModifierSliderImpl", "ResetContentModifierSliderImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="textclock",
            method_name="contentModifier",
            symbol_hints=("ContentModifierTextClockImpl", "ResetContentModifierTextClockImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="texttimer",
            method_name="contentModifier",
            symbol_hints=("ContentModifierTextTimerImpl", "ResetContentModifierTextTimerImpl"),
        ),
        ExplicitSourceFanoutRule(
            family="toggle",
            method_name="contentModifier",
            symbol_hints=("ContentModifierToggleImpl", "ResetContentModifierToggleImpl"),
        ),
    ),
}


def snake_to_pascal(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\-.]+", name) if part)


def camel_to_pascal(name: str) -> str:
    if not name:
        return ""
    return name[0].upper() + name[1:]


def normalize_repo_rel(path: str | Path, repo_root: Path | None = None) -> str:
    candidate = Path(path)
    if candidate.is_absolute() and repo_root is not None:
        try:
            return str(candidate.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
        except ValueError:
            return str(candidate.resolve()).replace("\\", "/")
    return str(candidate).replace("\\", "/")


def default_api_lineage_map_file(runtime_state_root: Path | None) -> Path:
    root = ensure_runtime_state_root(runtime_state_root)
    return (root / API_LINEAGE_FILENAME).resolve()


def _tokenize_path(rel_path: str) -> set[str]:
    return {
        compact_token(part)
        for part in re.split(r"[\\/._-]+", rel_path.lower())
        if part and compact_token(part)
    }


def _path_component_tokens(rel_path: str) -> set[str]:
    return {
        compact_token(part)
        for part in rel_path.lower().replace("\\", "/").split("/")
        if part and compact_token(part)
    }


def _family_token_from_entity_name(symbol: str) -> str:
    value = str(symbol).partition(".")[0]
    for suffix in ENTITY_SUFFIXES:
        value = value.replace(suffix, "")
    return compact_token(value)


def _normalize_symbol_hint(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\(.*$", "", text)
    for separator in ("::", "->", "."):
        if separator in text:
            text = text.rsplit(separator, 1)[-1]
    return compact_token(text)


def _source_symbol_key(source_key: str, symbol_hint: str) -> str:
    normalized_symbol = _normalize_symbol_hint(symbol_hint)
    if not source_key or not normalized_symbol:
        return ""
    return f"{source_key}::{normalized_symbol}"


def _source_raw_symbol_key(source_key: str, symbol_name: str) -> str:
    text = str(symbol_name or "").strip()
    if not source_key or not text:
        return ""
    return f"{source_key}::{text}"


def _parse_interface_blocks(path: Path) -> dict[str, dict[str, object]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    interfaces: dict[str, dict[str, object]] = {}
    for match in INTERFACE_DECL_RE.finditer(text):
        name = match.group(1)
        extends_raw = match.group(2) or ""
        body_start = match.end() - 1
        depth = 0
        body_end = None
        for index in range(body_start, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    body_end = index
                    break
        if body_end is None:
            continue
        body = text[body_start + 1 : body_end]
        interfaces[name] = {
            "extends": [
                part.strip()
                for part in re.split(r"[,\s]+", extends_raw.strip())
                if part.strip()
            ],
            "methods": {item for item in INTERFACE_METHOD_RE.findall(body) if item},
        }
    return interfaces


def extract_source_members(text: str) -> dict[str, dict[str, object]]:
    """Extract member-level source semantics from generated .ets interface files.

    Parses koala-generated static interface files to find:
    - export interface TypeName { method1(): void; method2(value: X): this; }
    - export function someFunction(): void
    - event declarations in interfaces

    Returns a dict mapping type name -> {methods, functions, events}.
    """
    result: dict[str, dict[str, object]] = {}

    # First pass: find all interface declarations
    for match in INTERFACE_DECL_RE.finditer(text):
        type_name = match.group(1)
        body_start = match.end() - 1
        depth = 0
        body_end = None
        for index in range(body_start, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    body_end = index
                    break
        if body_end is None:
            continue
        body = text[match.end():body_end]

        result[type_name] = {
            "methods": set(),
            "functions": set(),
            "events": set(),
        }

        # Extract methods from this interface body
        for method_match in SOURCE_MEMBER_DECL_RE.finditer(body):
            result[type_name]["methods"].add(method_match.group(1))

        # Extract event declarations from this interface body
        for event_match in EVENT_DECL_RE.finditer(body):
            field_name = event_match.group(1)
            event_type = event_match.group(2)
            result[type_name]["events"].add(f"{event_type}.{field_name}")

    # Second pass: extract standalone function declarations
    functions: set[str] = set()
    for match in SOURCE_FUNCTION_DECL_RE.finditer(text):
        functions.add(match.group(1))
    if functions:
        result["__functions__"] = {"methods": set(), "functions": functions, "events": set()}

    return result


def extract_proxy_members(text: str) -> dict[str, set[str]]:
    """Extract proxy bind methods from koala-generated proxy files.

    Parses patterns like:
    - proxy.bindPopup(content)
    - proxy.bindSheet(menu)
    - proxy.bindContextMenu(context)

    Returns a dict mapping proxy variable name -> set of bind method names.
    """
    result: dict[str, set[str]] = {}
    for match in PROXY_BIND_METHOD_RE.finditer(text):
        bind_method = match.group(1)
        # Try to find the proxy variable name from context
        # Look backwards for a variable assignment
        start = max(0, match.start() - 200)
        context = text[start:match.start()]
        proxy_var = None
        # Pattern 1: let/var/const x = ...; x.bind*
        for var_match in re.finditer(r"\b(let|var|const)\s+(\w+)\s*=", context):
            proxy_var = var_match.group(2)
        # Pattern 2: x.bind* (direct usage)
        if proxy_var is None:
            for var_match in re.finditer(r"\b(\w+)\s*\.bind", context):
                proxy_var = var_match.group(1)
        if proxy_var is None:
            proxy_var = "proxy"
        result.setdefault(proxy_var, set()).add(bind_method)
    return result


def build_source_member_index(repo_root: Path) -> dict[str, dict[str, object]]:
    """Build a source member index from SDK static declaration files.

    Walks interface/sdk-js/api/**/*.static.d.ets files and extracts
    member-level semantics for each API entity.

    Returns a flat dict mapping type_name -> member info.
    """
    sdk_api = repo_root / "interface" / "sdk-js" / "api"
    if not sdk_api.exists():
        return {}

    index: dict[str, dict[str, object]] = {}
    for ets_path in sdk_api.rglob("*.static.d.ets"):
        text = ets_path.read_text(encoding="utf-8")
        members = extract_source_members(text)
        for type_name, info in members.items():
            if type_name == "__functions__":
                continue
            index[type_name] = {
                "file": str(ets_path.relative_to(repo_root)),
                "methods": sorted(info.get("methods", set())),
                "functions": sorted(info.get("functions", set())),
                "events": sorted(info.get("events", set())),
            }
    return index


def _matching_interface_name(interfaces: dict[str, dict[str, object]], family: str, suffix: str) -> str | None:
    family_key = compact_token(family)
    matches = [
        name
        for name in interfaces
        if name.endswith(suffix) and compact_token(name[: -len(suffix)]) == family_key
    ]
    return sorted(matches)[0] if matches else None


def _parse_source_consumer_file(path: Path, repo_root: Path) -> SourceConsumerFileIndex:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""

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

    return SourceConsumerFileIndex(
        relative_path=normalize_repo_rel(path, repo_root=repo_root),
        imports=set(IMPORT_RE.findall(text)),
        imported_symbols=imported_symbols,
        identifier_calls=set(IDENTIFIER_CALL_RE.findall(text)),
        member_calls=set(MEMBER_CALL_RE.findall(text)),
        type_member_calls={f"{owner}.{member}" for owner, member in TYPE_MEMBER_CALL_RE.findall(text)},
        typed_modifier_bases=typed_modifier_bases,
    )


def _discover_source_consumer_projects(repo_root: Path, consumer_root: Path) -> list[SourceConsumerProjectIndex]:
    if not consumer_root.is_dir():
        return []

    projects: list[SourceConsumerProjectIndex] = []
    for child in sorted(item for item in consumer_root.iterdir() if item.is_dir()):
        files: list[SourceConsumerFileIndex] = []
        for dirpath, dirnames, filenames in os.walk(child, topdown=True, onerror=lambda _exc: None):
            dirnames[:] = [name for name in dirnames if name not in SOURCE_CONSUMER_SKIP_DIRS]
            base = Path(dirpath)
            for filename in filenames:
                if not filename.endswith((".ets", ".ts", ".js")):
                    continue
                files.append(_parse_source_consumer_file((base / filename).resolve(), repo_root))
        if not files:
            continue
        relative_root = normalize_repo_rel(child.resolve(), repo_root=repo_root)
        projects.append(
            SourceConsumerProjectIndex(
                relative_root=relative_root,
                path_key=relative_root,
                files=files,
            )
        )
    return projects


@dataclass
class ApiLineageMap:
    schema_version: int = SCHEMA_VERSION
    metadata: dict[str, object] = field(default_factory=dict)
    source_to_apis: dict[str, set[str]] = field(default_factory=dict)
    source_symbol_to_apis: dict[str, set[str]] = field(default_factory=dict)
    source_symbol_spans: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    api_to_sources: dict[str, set[str]] = field(default_factory=dict)
    api_to_families: dict[str, set[str]] = field(default_factory=dict)
    api_to_surfaces: dict[str, set[str]] = field(default_factory=dict)
    consumer_file_to_apis: dict[str, set[str]] = field(default_factory=dict)
    api_to_consumer_files: dict[str, set[str]] = field(default_factory=dict)
    consumer_project_to_apis: dict[str, set[str]] = field(default_factory=dict)
    api_to_consumer_projects: dict[str, set[str]] = field(default_factory=dict)
    consumer_file_kinds: dict[str, str] = field(default_factory=dict)
    consumer_project_kinds: dict[str, str] = field(default_factory=dict)
    consumer_file_to_project: dict[str, str] = field(default_factory=dict)
    consumer_project_to_files: dict[str, set[str]] = field(default_factory=dict)
    source_member_index: dict[str, dict[str, object]] = field(default_factory=dict)

    def record_source_api(self, source_path: str | Path, api_entity: str, *, family: str | None = None) -> None:
        source_key = normalize_repo_rel(source_path)
        api_key = str(api_entity)
        self.source_to_apis.setdefault(source_key, set()).add(api_key)
        self.api_to_sources.setdefault(api_key, set()).add(source_key)
        family_key = compact_token(family or api_key.replace("Modifier", "").replace("Configuration", ""))
        if family_key:
            self.api_to_families.setdefault(api_key, set()).add(family_key)

    def record_source_symbol_api(self, source_path: str | Path, symbol_hint: str, api_entity: str) -> None:
        source_key = normalize_repo_rel(source_path)
        symbol_key = _source_symbol_key(source_key, symbol_hint)
        if not symbol_key:
            return
        self.source_symbol_to_apis.setdefault(symbol_key, set()).add(str(api_entity))

    def record_source_symbol_span(
        self,
        source_path: str | Path,
        symbol_name: str,
        start_line: int,
        end_line: int,
    ) -> None:
        source_key = normalize_repo_rel(source_path)
        span_key = _source_raw_symbol_key(source_key, symbol_name)
        if not span_key:
            return
        start = max(1, int(start_line))
        end = max(start, int(end_line))
        spans = self.source_symbol_spans.setdefault(span_key, [])
        candidate = (start, end)
        if candidate not in spans:
            spans.append(candidate)

    def record_api_surface(self, api_entity: str, surface: str) -> None:
        if surface:
            self.api_to_surfaces.setdefault(str(api_entity), set()).add(str(surface))

    def record_consumer_file_api(
        self,
        consumer_file: str | Path,
        api_entity: str,
        *,
        kind: str = "xts",
        consumer_project: str | Path | None = None,
    ) -> None:
        consumer_key = normalize_repo_rel(consumer_file)
        api_key = str(api_entity)
        self.consumer_file_to_apis.setdefault(consumer_key, set()).add(api_key)
        self.api_to_consumer_files.setdefault(api_key, set()).add(consumer_key)
        self.consumer_file_kinds.setdefault(consumer_key, kind)
        if consumer_project is not None:
            project_key = normalize_repo_rel(consumer_project)
            self.consumer_file_to_project[consumer_key] = project_key
            self.consumer_project_to_files.setdefault(project_key, set()).add(consumer_key)
            self.consumer_project_kinds.setdefault(project_key, kind)

    def record_consumer_project_api(self, consumer_project: str | Path, api_entity: str, *, kind: str = "xts") -> None:
        consumer_key = normalize_repo_rel(consumer_project)
        api_key = str(api_entity)
        self.consumer_project_to_apis.setdefault(consumer_key, set()).add(api_key)
        self.api_to_consumer_projects.setdefault(api_key, set()).add(consumer_key)
        self.consumer_project_kinds.setdefault(consumer_key, kind)

    def consumer_projects_for_api(self, api_entity: str, *, kind: str | None = None) -> list[str]:
        projects = sorted(self.api_to_consumer_projects.get(str(api_entity), set()))
        if kind is None:
            return projects
        return [project for project in projects if self.consumer_project_kinds.get(project) == kind]

    def consumer_files_for_project(self, consumer_project: str | Path) -> list[str]:
        project_key = normalize_repo_rel(consumer_project)
        return sorted(self.consumer_project_to_files.get(project_key, set()))

    def apis_for_source(self, source_path: str | Path, repo_root: Path | None = None) -> list[str]:
        source_key = normalize_repo_rel(source_path, repo_root=repo_root)
        return sorted(self.source_to_apis.get(source_key, set()))

    def apis_for_source_symbols(
        self,
        source_path: str | Path,
        source_symbols: Iterable[str] | None,
        *,
        repo_root: Path | None = None,
    ) -> list[str]:
        source_key = normalize_repo_rel(source_path, repo_root=repo_root)
        matched: set[str] = set()
        for symbol in source_symbols or []:
            symbol_key = _source_symbol_key(source_key, str(symbol))
            if not symbol_key:
                continue
            matched.update(self.source_symbol_to_apis.get(symbol_key, set()))
        return sorted(matched)

    def symbols_for_source_ranges(
        self,
        source_path: str | Path,
        source_ranges: Iterable[tuple[int, int]] | None,
        *,
        repo_root: Path | None = None,
    ) -> list[str]:
        source_key = normalize_repo_rel(source_path, repo_root=repo_root)
        prefix = f"{source_key}::"
        normalized_ranges = [
            (max(1, int(start)), max(int(start), int(end)))
            for start, end in (source_ranges or [])
        ]
        if not normalized_ranges:
            return []
        matched: set[str] = set()
        for span_key, spans in self.source_symbol_spans.items():
            if not span_key.startswith(prefix):
                continue
            for span_start, span_end in spans:
                if any(span_start <= end and start <= span_end for start, end in normalized_ranges):
                    matched.add(span_key[len(prefix):])
                    break
        return sorted(matched)

    def to_dict(self) -> dict[str, object]:
        def _serialize(payload: dict[str, set[str]]) -> dict[str, list[str]]:
            return {key: sorted(values) for key, values in sorted(payload.items())}

        return {
            "schema_version": self.schema_version,
            "metadata": dict(self.metadata),
            "source_to_apis": _serialize(self.source_to_apis),
            "source_symbol_to_apis": _serialize(self.source_symbol_to_apis),
            "source_symbol_spans": {
                key: [[start, end] for start, end in sorted(values)]
                for key, values in sorted(self.source_symbol_spans.items())
            },
            "api_to_sources": _serialize(self.api_to_sources),
            "api_to_families": _serialize(self.api_to_families),
            "api_to_surfaces": _serialize(self.api_to_surfaces),
            "consumer_file_to_apis": _serialize(self.consumer_file_to_apis),
            "api_to_consumer_files": _serialize(self.api_to_consumer_files),
            "consumer_project_to_apis": _serialize(self.consumer_project_to_apis),
            "api_to_consumer_projects": _serialize(self.api_to_consumer_projects),
            "consumer_file_kinds": dict(sorted(self.consumer_file_kinds.items())),
            "consumer_project_kinds": dict(sorted(self.consumer_project_kinds.items())),
            "consumer_file_to_project": dict(sorted(self.consumer_file_to_project.items())),
            "consumer_project_to_files": _serialize(self.consumer_project_to_files),
            "source_member_index": {
                type_name: {
                    "file": str(info.get("file", "")),
                    "methods": sorted(info.get("methods", set())),
                    "functions": sorted(info.get("functions", set())),
                    "events": sorted(info.get("events", set())),
                }
                for type_name, info in sorted(self.source_member_index.items())
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ApiLineageMap":
        def _restore(payload: object) -> dict[str, set[str]]:
            result: dict[str, set[str]] = {}
            if not isinstance(payload, dict):
                return result
            for key, values in payload.items():
                if isinstance(values, list):
                    result[str(key)] = {str(item) for item in values}
            return result

        return cls(
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            metadata=dict(data.get("metadata", {})) if isinstance(data.get("metadata"), dict) else {},
            source_to_apis=_restore(data.get("source_to_apis")),
            source_symbol_to_apis=_restore(data.get("source_symbol_to_apis")),
            source_symbol_spans={
                str(key): [
                    (max(1, int(item[0])), max(int(item[0]), int(item[1])))
                    for item in values
                    if isinstance(item, list) and len(item) == 2
                ]
                for key, values in (data.get("source_symbol_spans", {}) or {}).items()
                if isinstance(values, list)
            } if isinstance(data.get("source_symbol_spans"), dict) else {},
            api_to_sources=_restore(data.get("api_to_sources")),
            api_to_families=_restore(data.get("api_to_families")),
            api_to_surfaces=_restore(data.get("api_to_surfaces")),
            consumer_file_to_apis=_restore(data.get("consumer_file_to_apis")),
            api_to_consumer_files=_restore(data.get("api_to_consumer_files")),
            consumer_project_to_apis=_restore(data.get("consumer_project_to_apis")),
            api_to_consumer_projects=_restore(data.get("api_to_consumer_projects")),
            consumer_file_kinds={
                str(key): str(value)
                for key, value in (data.get("consumer_file_kinds", {}) or {}).items()
            } if isinstance(data.get("consumer_file_kinds"), dict) else {},
            consumer_project_kinds={
                str(key): str(value)
                for key, value in (data.get("consumer_project_kinds", {}) or {}).items()
            } if isinstance(data.get("consumer_project_kinds"), dict) else {},
            consumer_file_to_project={
                str(key): str(value)
                for key, value in (data.get("consumer_file_to_project", {}) or {}).items()
            } if isinstance(data.get("consumer_file_to_project"), dict) else {},
            consumer_project_to_files=_restore(data.get("consumer_project_to_files")),
            source_member_index={
                str(type_name): {
                    "file": str(info.get("file", "")),
                    "methods": list(info.get("methods", [])),
                    "functions": list(info.get("functions", [])),
                    "events": list(info.get("events", [])),
                }
                for type_name, info in (data.get("source_member_index") or {}).items()
                if isinstance(info, dict)
            } if isinstance(data.get("source_member_index"), dict) else {},
        )


@dataclass
class SourceConsumerFileIndex:
    relative_path: str
    imports: set[str] = field(default_factory=set)
    imported_symbols: set[str] = field(default_factory=set)
    identifier_calls: set[str] = field(default_factory=set)
    member_calls: set[str] = field(default_factory=set)
    type_member_calls: set[str] = field(default_factory=set)
    typed_modifier_bases: set[str] = field(default_factory=set)


@dataclass
class SourceConsumerProjectIndex:
    relative_root: str
    path_key: str
    files: list[SourceConsumerFileIndex] = field(default_factory=list)


def _load_sdk_entities(
    repo_root: Path,
    sdk_api_root: Path,
    lineage_map: ApiLineageMap,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    component_symbols_by_family: dict[str, set[str]] = {}
    modifier_symbols_by_family: dict[str, set[str]] = {}
    family_to_api_symbols: dict[str, set[str]] = {}
    method_entities_by_family: dict[str, set[str]] = {}
    attribute_interface_names_by_family: dict[str, str] = {}

    sdk_component_root = sdk_api_root / "arkui/component"
    sdk_arkui_root = sdk_api_root / "arkui"

    for path in sorted(sdk_component_root.glob("*.static.d.ets")):
        base = path.name[: -len(".static.d.ets")]
        if base in SDK_COMPONENT_SKIP:
            continue
        family = compact_token(base)
        if not family:
            continue
        symbol = snake_to_pascal(base)
        component_symbols_by_family.setdefault(family, set()).add(symbol)
        family_to_api_symbols.setdefault(family, set()).add(symbol)
        lineage_map.record_source_api(path.relative_to(repo_root), symbol, family=family)
        lineage_map.record_api_surface(symbol, "static")
        attribute_name = _matching_interface_name(_parse_interface_blocks(path), family, "Attribute")
        if attribute_name:
            attribute_interface_names_by_family[family] = attribute_name

    modifier_paths = sorted(sdk_arkui_root.glob("*Modifier.d.ts"))
    modifier_paths.extend(sorted(sdk_arkui_root.glob("*Modifier.static.d.ets")))
    for path in modifier_paths:
        name = path.name
        if name.endswith(".d.ts"):
            symbol = name[:-len(".d.ts")]
            surface = "dynamic"
        else:
            symbol = name[:-len(".static.d.ets")]
            surface = "static"
        family = compact_token(symbol.replace("Modifier", ""))
        if not family:
            continue
        modifier_symbols_by_family.setdefault(family, set()).add(symbol)
        family_to_api_symbols.setdefault(family, set()).add(symbol)
        lineage_map.record_source_api(path.relative_to(repo_root), symbol, family=family)
        lineage_map.record_api_surface(symbol, surface)

    common_static_path = sdk_component_root / "common.static.d.ets"
    common_interfaces = _parse_interface_blocks(common_static_path)
    common_method_methods = set(common_interfaces.get("CommonMethod", {}).get("methods", set()) or set())

    for family, allowed_methods in sorted(COMPONENT_ATTRIBUTE_METHOD_ALLOWLIST.items()):
        component_static_path = sdk_component_root / f"{family}.static.d.ets"
        interfaces = _parse_interface_blocks(component_static_path)
        attribute_name = attribute_interface_names_by_family.get(family) or _matching_interface_name(
            interfaces,
            family,
            "Attribute",
        )
        attribute_data = interfaces.get(attribute_name)
        if not attribute_data:
            continue
        direct_methods = set(attribute_data.get("methods", set()) or set())
        for method_name in sorted(direct_methods & allowed_methods):
            api_entity = f"{attribute_name}.{method_name}"
            method_entities_by_family.setdefault(family, set()).add(api_entity)
            lineage_map.record_source_api(component_static_path.relative_to(repo_root), api_entity, family=family)
            lineage_map.record_api_surface(api_entity, "static")

    for family, allowed_methods in sorted(INHERITED_COMMON_METHOD_ALLOWLIST.items()):
        attribute_name = attribute_interface_names_by_family.get(family)
        if not attribute_name:
            continue
        for method_name in sorted(common_method_methods & allowed_methods):
            api_entity = f"{attribute_name}.{method_name}"
            method_entities_by_family.setdefault(family, set()).add(api_entity)
            lineage_map.record_source_api(common_static_path.relative_to(repo_root), api_entity, family=family)
            lineage_map.record_api_surface(api_entity, "static")

    return component_symbols_by_family, modifier_symbols_by_family, family_to_api_symbols, method_entities_by_family


def _iter_source_files(ace_engine_root: Path) -> Iterable[Path]:
    for relative_root in SOURCE_SCAN_ROOTS:
        root = ace_engine_root / relative_root
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SOURCE_FILE_SUFFIXES:
                yield path


def _match_source_families(rel_path: str, family_to_api_symbols: dict[str, set[str]]) -> set[str]:
    rel_lower = rel_path.lower()
    matched: set[str] = set()
    tokens = _tokenize_path(rel_lower)
    tokens.update(_path_component_tokens(rel_lower))

    pattern_match = re.search(r"components_ng/pattern/([^/]+)/", rel_lower)
    if pattern_match:
        family = compact_token(pattern_match.group(1))
        if family in family_to_api_symbols:
            matched.add(family)

    for token in tokens:
        if token in family_to_api_symbols:
            matched.add(token)
    return matched


def _source_matches_method_entity(source_text: str, api_entity: str) -> bool:
    _owner, _separator, method_name = api_entity.partition(".")
    if not method_name:
        return False
    property_name = camel_to_pascal(method_name)
    patterns = [
        rf"\bSet{re.escape(property_name)}\s*\(",
        rf"\bUpdate{re.escape(property_name)}\s*\(",
        rf"\bReset{re.escape(property_name)}\s*\(",
        rf"\bGet{re.escape(property_name)}(?:Property)?\s*\(",
        rf"ACE_UPDATE_NODE_LAYOUT_PROPERTY\s*\([^)]*,\s*{re.escape(property_name)}\s*,",
        rf"ACE_RESET_NODE_LAYOUT_PROPERTY\s*\([^)]*,\s*{re.escape(property_name)}\s*,",
    ]
    return any(re.search(pattern, source_text) for pattern in patterns)


def _method_entity_symbol_hints(api_entity: str) -> set[str]:
    _owner, _separator, method_name = api_entity.partition(".")
    if not method_name:
        return set()
    property_name = camel_to_pascal(method_name)
    return {
        method_name,
        property_name,
        f"Set{property_name}",
        f"Update{property_name}",
        f"Reset{property_name}",
        f"Refresh{property_name}",
        f"Get{property_name}",
        f"Get{property_name}Property",
    }


def _find_block_end_line(lines: list[str], brace_line_index: int) -> int:
    depth = 0
    started = False
    for index in range(brace_line_index, len(lines)):
        for char in lines[index]:
            if char == "{":
                depth += 1
                started = True
            elif char == "}" and started:
                depth -= 1
                if depth == 0:
                    return index + 1
    return brace_line_index + 1


def _extract_source_symbol_spans(path: Path, source_text: str) -> list[tuple[str, int, int]]:
    if path.suffix.lower() not in SOURCE_FILE_SUFFIXES:
        return []
    lines = source_text.splitlines()
    spans: list[tuple[str, int, int]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            index += 1
            continue
        if "(" not in stripped:
            index += 1
            continue

        header_lines = [stripped]
        header_start = index
        cursor = index
        brace_line_index: int | None = index if "{" in stripped else None
        invalid = False
        while cursor + 1 < len(lines) and brace_line_index is None and cursor - header_start < 5:
            if ";" in lines[cursor]:
                invalid = True
                break
            cursor += 1
            next_stripped = lines[cursor].strip()
            if not next_stripped or next_stripped.startswith("//"):
                continue
            header_lines.append(next_stripped)
            if next_stripped == "{":
                brace_line_index = cursor
                break
            if "{" in next_stripped:
                brace_line_index = cursor
                break
            if ";" in next_stripped:
                invalid = True
                break
        if invalid:
            index += 1
            continue
        header_text = " ".join(part for part in header_lines if part != "{")
        match = SOURCE_SYMBOL_HEADER_RE.match(header_text)
        if not match:
            index += 1
            continue
        symbol_name = match.group("name")
        base_name = symbol_name.rsplit("::", 1)[-1]
        if compact_token(base_name) in CONTROL_FLOW_SYMBOLS:
            index += 1
            continue
        if brace_line_index is None:
            index += 1
            continue
        end_line = _find_block_end_line(lines, brace_line_index)
        spans.append((symbol_name, header_start + 1, end_line))
        index = max(index + 1, end_line)
    return spans


def _record_explicit_source_fanout(
    rel_path: str,
    lineage_map: ApiLineageMap,
    method_entities_by_family: dict[str, set[str]],
) -> None:
    for rule in EXPLICIT_SOURCE_FANOUT_RULES.get(rel_path, ()):
        matched_entities = [
            api_entity
            for api_entity in sorted(method_entities_by_family.get(rule.family, set()))
            if api_entity.endswith(f".{rule.method_name}")
        ]
        for api_entity in matched_entities:
            lineage_map.record_source_api(rel_path, api_entity, family=rule.family)
            for symbol_hint in rule.symbol_hints:
                lineage_map.record_source_symbol_api(rel_path, symbol_hint, api_entity)


def _build_source_edges(
    repo_root: Path,
    ace_engine_root: Path,
    lineage_map: ApiLineageMap,
    family_to_api_symbols: dict[str, set[str]],
    method_entities_by_family: dict[str, set[str]],
) -> None:
    for path in _iter_source_files(ace_engine_root):
        rel_path = normalize_repo_rel(path, repo_root=repo_root)
        matched_families = sorted(_match_source_families(rel_path, family_to_api_symbols))
        for family in matched_families:
            for api_entity in sorted(family_to_api_symbols.get(family, set())):
                lineage_map.record_source_api(rel_path, api_entity, family=family)
        relevant_method_entities = sorted(
            {
                api_entity
                for family in matched_families
                for api_entity in method_entities_by_family.get(family, set())
            }
        )
        needs_source_text = bool(relevant_method_entities) or rel_path in EXPLICIT_SOURCE_FANOUT_RULES
        if not needs_source_text:
            continue
        try:
            source_text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for symbol_name, start_line, end_line in _extract_source_symbol_spans(path, source_text):
            lineage_map.record_source_symbol_span(rel_path, symbol_name, start_line, end_line)
        _record_explicit_source_fanout(rel_path, lineage_map, method_entities_by_family)
        for api_entity in relevant_method_entities:
            if _source_matches_method_entity(source_text, api_entity):
                lineage_map.record_source_api(rel_path, api_entity, family=_family_token_from_entity_name(api_entity))
                for symbol_hint in sorted(_method_entity_symbol_hints(api_entity)):
                    lineage_map.record_source_symbol_api(rel_path, symbol_hint, api_entity)


def _record_consumer_matches(
    lineage_map: ApiLineageMap,
    project: object,
    file_index: object,
    known_api_entities: set[str],
    modifier_symbols_by_family: dict[str, set[str]],
    method_entities_by_family: dict[str, set[str]],
    *,
    consumer_kind: str = "xts",
) -> None:
    project_key = str(getattr(project, "relative_root", "") or getattr(project, "path_key", "") or "")
    file_key = str(getattr(file_index, "relative_path", "") or "")
    imported_symbols = set(getattr(file_index, "imported_symbols", set()) or set())
    identifier_calls = set(getattr(file_index, "identifier_calls", set()) or set())
    member_calls = set(getattr(file_index, "member_calls", set()) or set())
    type_member_calls = set(getattr(file_index, "type_member_calls", set()) or set())
    typed_modifier_bases = {
        compact_token(value)
        for value in (getattr(file_index, "typed_modifier_bases", set()) or set())
        if compact_token(value)
    }

    direct_apis = {symbol for symbol in (imported_symbols | identifier_calls) if symbol in known_api_entities}
    for api_entity in sorted(direct_apis):
        if file_key:
            lineage_map.record_consumer_file_api(file_key, api_entity, kind=consumer_kind, consumer_project=project_key)
        if project_key:
            lineage_map.record_consumer_project_api(project_key, api_entity, kind=consumer_kind)

    for family in sorted(typed_modifier_bases):
        for api_entity in sorted(modifier_symbols_by_family.get(family, set())):
            if file_key:
                lineage_map.record_consumer_file_api(file_key, api_entity, kind=consumer_kind, consumer_project=project_key)
            if project_key:
                lineage_map.record_consumer_project_api(project_key, api_entity, kind=consumer_kind)

    family_contexts = set(typed_modifier_bases)
    for symbol in imported_symbols | identifier_calls:
        family_contexts.add(_family_token_from_entity_name(symbol))
        if symbol in known_api_entities:
            family_contexts.update(lineage_map.api_to_families.get(symbol, set()))

    for entry in type_member_calls:
        owner, _separator, member = entry.partition(".")
        if not owner or not member:
            continue
        family_contexts.add(_family_token_from_entity_name(owner))
        explicit_entity = f"{owner}.{member}"
        if explicit_entity in known_api_entities:
            if file_key:
                lineage_map.record_consumer_file_api(
                    file_key,
                    explicit_entity,
                    kind=consumer_kind,
                    consumer_project=project_key,
                )
            if project_key:
                lineage_map.record_consumer_project_api(project_key, explicit_entity, kind=consumer_kind)

    member_call_tokens = {compact_token(item) for item in member_calls if compact_token(item)}
    for family in sorted(token for token in family_contexts if token in method_entities_by_family):
        for api_entity in sorted(method_entities_by_family.get(family, set())):
            _owner, _separator, method_name = api_entity.partition(".")
            if not method_name:
                continue
            if method_name in member_calls or compact_token(method_name) in member_call_tokens:
                if file_key:
                    lineage_map.record_consumer_file_api(file_key, api_entity, kind=consumer_kind, consumer_project=project_key)
                if project_key:
                    lineage_map.record_consumer_project_api(project_key, api_entity, kind=consumer_kind)


def _build_consumer_edges(
    lineage_map: ApiLineageMap,
    projects: Iterable[object] | None,
    modifier_symbols_by_family: dict[str, set[str]],
    method_entities_by_family: dict[str, set[str]],
    *,
    consumer_kind: str = "xts",
) -> None:
    if projects is None:
        return
    known_api_entities = set(lineage_map.api_to_sources)
    for project in projects:
        for file_index in list(getattr(project, "files", []) or []):
            _record_consumer_matches(
                lineage_map,
                project,
                file_index,
                known_api_entities,
                modifier_symbols_by_family,
                method_entities_by_family,
                consumer_kind=consumer_kind,
            )


def _build_source_only_consumer_edges(
    repo_root: Path,
    lineage_map: ApiLineageMap,
    modifier_symbols_by_family: dict[str, set[str]],
    method_entities_by_family: dict[str, set[str]],
    source_consumer_roots: Iterable[Path] | None,
) -> None:
    roots = list(source_consumer_roots or [])
    if not roots:
        roots = [(repo_root / relative_root).resolve() for relative_root in SOURCE_CONSUMER_ROOTS]
    for root in roots:
        for project in _discover_source_consumer_projects(repo_root, root.resolve()):
            _build_consumer_edges(
                lineage_map,
                [project],
                modifier_symbols_by_family,
                method_entities_by_family,
                consumer_kind="source_only",
            )


def write_api_lineage_map(path: Path, lineage_map: ApiLineageMap) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(lineage_map.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_api_lineage_map(path: Path) -> ApiLineageMap:
    return ApiLineageMap.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _build_tree_signature(
    root: Path,
    *,
    file_suffixes: Iterable[str],
    skip_dirs: Iterable[str] | None = None,
) -> dict[str, object]:
    resolved_root = root.resolve()
    suffixes = tuple(str(item).lower() for item in file_suffixes)
    skipped = set(skip_dirs or [])
    if not resolved_root.exists():
        return {
            "root": str(resolved_root),
            "file_count": 0,
            "sha256": "missing",
        }
    h = hashlib.sha256()
    file_count = 0
    for dirpath, dirnames, filenames in os.walk(resolved_root, topdown=True, onerror=lambda _exc: None):
        dirnames[:] = sorted(name for name in dirnames if name not in skipped)
        base = Path(dirpath)
        for filename in sorted(filenames):
            lower_name = filename.lower()
            if suffixes and not lower_name.endswith(suffixes):
                continue
            path = base / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = str(path.relative_to(resolved_root)).replace(os.sep, "/")
            h.update(f"{rel}:{stat.st_mtime_ns}:{stat.st_size}\n".encode())
            file_count += 1
    return {
        "root": str(resolved_root),
        "file_count": file_count,
        "sha256": h.hexdigest(),
    }


def _file_signature(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    resolved = path.resolve()
    if not resolved.exists():
        return {
            "path": str(resolved),
            "exists": False,
        }
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "exists": True,
        "mtime_ns": int(stat.st_mtime_ns),
        "size": int(stat.st_size),
    }


def _lineage_input_signatures(
    *,
    repo_root: Path,
    ace_engine_root: Path,
    sdk_api_root: Path,
    source_consumer_roots: Iterable[Path] | None,
    project_cache_file: Path | None,
) -> dict[str, object]:
    source_roots = [
        _build_tree_signature(
            (ace_engine_root / relative_root).resolve(),
            file_suffixes=SOURCE_FILE_SUFFIXES,
        )
        for relative_root in SOURCE_SCAN_ROOTS
    ]
    sdk_roots = [
        _build_tree_signature(
            (sdk_api_root / "arkui").resolve(),
            file_suffixes=(".d.ts", ".d.ets"),
        ),
        _build_tree_signature(
            (sdk_api_root / "arkui/component").resolve(),
            file_suffixes=(".d.ts", ".d.ets"),
        ),
    ]
    roots = list(source_consumer_roots or [])
    if not roots:
        roots = [(repo_root / relative_root).resolve() for relative_root in SOURCE_CONSUMER_ROOTS]
    source_consumer_signatures = [
        _build_tree_signature(
            root.resolve(),
            file_suffixes=(".ets", ".ts", ".js"),
            skip_dirs=SOURCE_CONSUMER_SKIP_DIRS,
        )
        for root in roots
    ]
    return {
        "version": LINEAGE_CACHE_SIGNATURE_VERSION,
        "project_cache_file": _file_signature(project_cache_file),
        "source_roots": source_roots,
        "sdk_roots": sdk_roots,
        "source_consumer_roots": source_consumer_signatures,
    }


def build_api_lineage_map(
    *,
    repo_root: Path,
    ace_engine_root: Path,
    sdk_api_root: Path,
    projects: Iterable[object] | None = None,
    runtime_state_root: Path | None = None,
    source_consumer_roots: Iterable[Path] | None = None,
    project_cache_file: Path | None = None,
) -> tuple[ApiLineageMap, Path]:
    target_path = default_api_lineage_map_file(runtime_state_root)
    input_signatures = _lineage_input_signatures(
        repo_root=repo_root,
        ace_engine_root=ace_engine_root,
        sdk_api_root=sdk_api_root,
        source_consumer_roots=source_consumer_roots,
        project_cache_file=project_cache_file,
    )
    if target_path.exists():
        try:
            cached_map = read_api_lineage_map(target_path)
            if cached_map.metadata.get("input_signatures") == input_signatures:
                return cached_map, target_path
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    lineage_map = ApiLineageMap(
        metadata={
            "repo_root": str(repo_root.resolve()),
            "ace_engine_root": str(ace_engine_root.resolve()),
            "sdk_api_root": str(sdk_api_root.resolve()),
            "input_signatures": input_signatures,
        }
    )
    _, modifier_symbols_by_family, family_to_api_symbols, method_entities_by_family = _load_sdk_entities(
        repo_root,
        sdk_api_root,
        lineage_map,
    )
    _build_source_edges(repo_root, ace_engine_root, lineage_map, family_to_api_symbols, method_entities_by_family)
    _build_consumer_edges(lineage_map, projects, modifier_symbols_by_family, method_entities_by_family)
    _build_source_only_consumer_edges(
        repo_root,
        lineage_map,
        modifier_symbols_by_family,
        method_entities_by_family,
        source_consumer_roots,
    )
    lineage_map.source_member_index = build_source_member_index(repo_root)
    write_api_lineage_map(target_path, lineage_map)
    return lineage_map, target_path
