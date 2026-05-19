"""
XTS Usage Index v1 — textual heuristic scanner.

Scans XTS/ACTS .ets/.ts/.js sources and maps them to SDK-visible ArkUI API
usage with usage_kind, confidence, and provenance information.

Design constraints (see CLAUDE.md):
- Only SDK-visible names (component names, enum prefixes) become api_name.
- Internal C++ modifier names (ButtonModifier, SliderModifier, etc.) are NOT
  emitted as api_name values — they appear at most in evidence snippets.
- No coverage_equivalence is granted.
- No hardcoded test-to-API mappings.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Known SDK-visible ArkUI component names (from interface_sdk-js/api).
# This list is used to distinguish genuine component_creation patterns from
# plain function calls.  Only PascalCase names that exist as ArkUI built-in
# components or declarative structs are included.
# ---------------------------------------------------------------------------
KNOWN_ARKUI_COMPONENTS: frozenset[str] = frozenset(
    {
        # Basic components
        "Text",
        "Button",
        "Image",
        "TextInput",
        "TextArea",
        "Search",
        "Select",
        "Checkbox",
        "CheckboxGroup",
        "Radio",
        "Toggle",
        "Slider",
        "Rating",
        "Progress",
        "LoadingProgress",
        "Marquee",
        "TextClock",
        "TextTimer",
        "Divider",
        "Blank",
        "Span",
        "ImageSpan",
        "ContainerSpan",
        "SymbolSpan",
        "SymbolGlyph",
        # Layout
        "Row",
        "Column",
        "Stack",
        "Flex",
        "Grid",
        "GridItem",
        "GridRow",
        "GridCol",
        "List",
        "ListItem",
        "ListItemGroup",
        "Scroll",
        "Swiper",
        "Tabs",
        "TabContent",
        "TabBar",
        "WaterFlow",
        "FlowItem",
        "RelativeContainer",
        # Navigation
        "Navigation",
        "NavDestination",
        "NavRouter",
        "Navigator",
        "PageTransitionEnter",
        "PageTransitionExit",
        # Drawing
        "Canvas",
        "Shape",
        "Line",
        "Rect",
        "Circle",
        "Ellipse",
        "Path",
        "Polygon",
        "Polyline",
        # Advanced
        "XComponent",
        "Web",
        "Menu",
        "MenuItem",
        "MenuItemGroup",
        "Stepper",
        "StepperItem",
        "Gauge",
        "Badge",
        "AlphabetIndexer",
        "Panel",
        "Refresh",
        "Hyperlink",
        "RichEditor",
        "RichText",
        "QRCode",
        "DataPanel",
        "Chip",
        "CalendarPicker",
        "DatePicker",
        "TimePicker",
        "TextPicker",
        "Counter",
        "PluginComponent",
        "FormComponent",
        "RemoteWindow",
        "Video",
        "ScrollBar",
        "SideBarContainer",
        "WithTheme",
        "Scroll",
        "Column",
        "Row",
        "RowSplit",
        "ColumnSplit",
    }
)

# Enum prefixes that indicate SDK-visible enum_or_config usage.
# Pattern: `EnumName.Member` where EnumName is a known ArkUI enum.
KNOWN_ARKUI_ENUMS: frozenset[str] = frozenset(
    {
        "ButtonType",
        "ButtonStyleMode",
        "ButtonRole",
        "SliderStyle",
        "SliderChangeMode",
        "Color",
        "FontStyle",
        "FontWeight",
        "TextAlign",
        "TextOverflow",
        "ImageFit",
        "ImageRepeat",
        "ImageRenderMode",
        "Alignment",
        "FlexDirection",
        "FlexAlign",
        "FlexWrap",
        "ItemAlign",
        "LayoutWeight",
        "BarState",
        "ScrollDirection",
        "EdgeEffect",
        "Axis",
        "HorizontalAlign",
        "VerticalAlign",
        "BorderStyle",
        "Visibility",
        "DisplayPriority",
        "NavigationMode",
        "NavBarPosition",
        "TabBarMode",
        "BarPosition",
        "SwiperDisplayMode",
        "PanDirection",
        "SwipeDirection",
        "GestureMode",
        "GesturePriority",
        "GestureMask",
        "HitTestMode",
        "ResponseType",
        "MouseButton",
        "KeyType",
        "FocusPriority",
        "ObscuredReasons",
        "RenderFit",
        "ClickEffectLevel",
        "TextInputType",
        "EnterKeyType",
        "CancelButtonStyle",
        "ContentType",
        "SearchType",
        "ToggleType",
        "ProgressType",
        "RatingStyle",
        "DataPanelType",
        "ChipSize",
        "GaugeIndicatorType",
        "PanelMode",
        "PanelType",
        "RefreshStatus",
        "XComponentType",
        "SideBarContainerType",
        "CheckboxShape",
        "RadioStyle",
    }
)

# Common ArkUI attribute/event method names. Used to detect attribute/event
# usage when the receiver is not immediately inferrable.
_ATTRIBUTE_METHODS: frozenset[str] = frozenset(
    {
        "width",
        "height",
        "fontSize",
        "fontColor",
        "fontWeight",
        "fontFamily",
        "fontStyle",
        "lineHeight",
        "letterSpacing",
        "textAlign",
        "textOverflow",
        "decoration",
        "padding",
        "margin",
        "border",
        "borderRadius",
        "borderColor",
        "borderWidth",
        "borderStyle",
        "backgroundColor",
        "backgroundImage",
        "backgroundBlurStyle",
        "opacity",
        "visibility",
        "clip",
        "rotate",
        "scale",
        "translate",
        "transform",
        "shadow",
        "blur",
        "brightness",
        "contrast",
        "grayscale",
        "colorBlend",
        "renderFit",
        "align",
        "alignSelf",
        "layoutWeight",
        "flexGrow",
        "flexShrink",
        "flexBasis",
        "zIndex",
        "enabled",
        "clickEffect",
        "focusable",
        "defaultFocus",
        "tabIndex",
        "hitTestBehavior",
        "touchable",
        "draggable",
        "gesture",
        "sharedTransition",
        "geometryTransition",
        "motionPath",
        "key",
        "id",
        "type",
        "step",
        "style",
        "blockColor",
        "trackColor",
        "selectedColor",
        "minLabel",
        "maxLabel",
        "showTips",
        "showSteps",
        "controlSize",
        "buttonStyle",
        "role",
        "stateEffect",
        "searchButton",
        "textFont",
        "placeholderFont",
        "placeholderColor",
        "caretColor",
        "inputFilter",
        "copyOption",
        "showUnderline",
        "maxLength",
        "maxLines",
        "showCounter",
        "customKeyboard",
        "type",
        "enterKeyType",
        "selectionMenuHidden",
        "contentModifier",
    }
)

_EVENT_METHODS: frozenset[str] = frozenset(
    {
        "onClick",
        "onTouch",
        "onHover",
        "onFocus",
        "onBlur",
        "onKeyEvent",
        "onKeyPreIme",
        "onMouse",
        "onVisibleAreaChange",
        "onAreaChange",
        "onAppear",
        "onDisAppear",
        "onPageShow",
        "onPageHide",
        "onBackPressed",
        "onChange",
        "onSelect",
        "onSubmit",
        "onEditChange",
        "onCopy",
        "onCut",
        "onPaste",
        "onTextSelectionChange",
        "onContentScroll",
        "onWillInsert",
        "onDidInsert",
        "onWillDelete",
        "onDidDelete",
        "onDragStart",
        "onDragEnter",
        "onDragMove",
        "onDragLeave",
        "onDrop",
        "onPreDrag",
        "onScrollStart",
        "onScrollEnd",
        "onScrollStop",
        "onScrollFrameBegin",
        "onScroll",
        "onScrollEdge",
        "onItemMove",
        "onItemDragStart",
        "onItemDragEnter",
        "onItemDragMove",
        "onItemDragLeave",
        "onItemDrop",
        "onReachStart",
        "onReachEnd",
        "onSwipe",
        "onAnimationStart",
        "onAnimationEnd",
        "onGestureRecognizerJudgeBegin",
        "shouldBuiltInRecognizerParallelWith",
    }
)

# Regex patterns for detection
_RE_COMPONENT_CALL = re.compile(
    r"\b([A-Z][A-Za-z0-9]+)\s*[({]"
)
_RE_METHOD_CALL = re.compile(
    r"\.([a-z][A-Za-z0-9]+)\s*\("
)
_RE_ENUM_ACCESS = re.compile(
    r"\b([A-Z][A-Za-z0-9]+)\.([A-Z][A-Za-z0-9]+)\b"
)
_RE_COMPONENT_BLOCK = re.compile(
    r"^\s*([A-Z][A-Za-z0-9]+)\s*[({]",
    re.MULTILINE,
)
# Detects chain: Component(...)\n  .attribute( pattern
_RE_COMPONENT_WITH_ATTR = re.compile(
    r"\b([A-Z][A-Za-z0-9]+)\s*[({][^)]*[)}\n].*?\.([a-z][A-Za-z0-9]+)\s*\(",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class UsageEntry:
    api_name: str
    usage_kind: str  # component_creation | attribute | event_or_method | enum_or_config | unknown
    project: str
    path: str
    line: int
    confidence: str  # strong | medium | weak
    evidence: str
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Scanning helpers
# ---------------------------------------------------------------------------


def _derive_project_name(file_path: Path, xts_root: Path) -> str:
    """Derive a project/suite name from the file path relative to XTS root."""
    try:
        rel = file_path.relative_to(xts_root)
        parts = rel.parts
        # First meaningful directory component is the project name
        if parts:
            return parts[0]
        return str(rel.parent)
    except ValueError:
        return file_path.parts[-2] if len(file_path.parts) >= 2 else "unknown"


def _truncate_evidence(text: str, max_len: int = 120) -> str:
    """Truncate evidence to max_len chars, stripping leading whitespace."""
    text = text.strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def _scan_file(
    file_path: Path,
    xts_root: Path,
) -> list[UsageEntry]:
    """Scan a single ETS/TS/JS file and return usage entries."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    lines = text.splitlines()
    project = _derive_project_name(file_path, xts_root)
    try:
        rel_path = str(file_path.relative_to(xts_root))
    except ValueError:
        rel_path = str(file_path)

    entries: list[UsageEntry] = []

    for lineno, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()

        # Skip blank lines and comment lines
        if not stripped or stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue

        # --- enum_or_config detection ---
        for m in _RE_ENUM_ACCESS.finditer(raw_line):
            enum_name = m.group(1)
            if enum_name in KNOWN_ARKUI_ENUMS:
                entries.append(
                    UsageEntry(
                        api_name=enum_name,
                        usage_kind="enum_or_config",
                        project=project,
                        path=rel_path,
                        line=lineno,
                        confidence="strong",
                        evidence=_truncate_evidence(raw_line),
                    )
                )

        # --- component_creation detection ---
        for m in _RE_COMPONENT_CALL.finditer(raw_line):
            comp_name = m.group(1)
            if comp_name in KNOWN_ARKUI_COMPONENTS:
                # Check whether the next non-blank line contains a .attribute call
                # → stronger confidence
                has_following_attr = False
                for future_line in lines[lineno : lineno + 5]:
                    fl = future_line.strip()
                    if fl.startswith(".") and _RE_METHOD_CALL.search(fl):
                        has_following_attr = True
                        break
                    if fl and not fl.startswith("//"):
                        break  # non-blank, non-attribute line

                confidence = "strong" if has_following_attr else "medium"
                entries.append(
                    UsageEntry(
                        api_name=comp_name,
                        usage_kind="component_creation",
                        project=project,
                        path=rel_path,
                        line=lineno,
                        confidence=confidence,
                        evidence=_truncate_evidence(raw_line),
                        limitations=(
                            []
                            if has_following_attr
                            else ["no_following_attribute_chain"]
                        ),
                    )
                )

        # --- attribute / event_or_method detection ---
        for m in _RE_METHOD_CALL.finditer(raw_line):
            method_name = m.group(1)
            if method_name in _EVENT_METHODS:
                entries.append(
                    UsageEntry(
                        api_name=method_name,
                        usage_kind="event_or_method",
                        project=project,
                        path=rel_path,
                        line=lineno,
                        confidence="medium",
                        evidence=_truncate_evidence(raw_line),
                        limitations=["receiver_type_inferred_heuristically"],
                    )
                )
            elif method_name in _ATTRIBUTE_METHODS:
                entries.append(
                    UsageEntry(
                        api_name=method_name,
                        usage_kind="attribute",
                        project=project,
                        path=rel_path,
                        line=lineno,
                        confidence="medium",
                        evidence=_truncate_evidence(raw_line),
                        limitations=["receiver_type_inferred_heuristically"],
                    )
                )

    return entries


def _deduplicate(entries: list[UsageEntry]) -> list[UsageEntry]:
    """Remove exact duplicates (same api_name, usage_kind, path, line)."""
    seen: set[tuple] = set()
    result: list[UsageEntry] = []
    for e in entries:
        key = (e.api_name, e.usage_kind, e.path, e.line)
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_usage_index(
    xts_root: str | Path | None,
    *,
    max_files: int | None = None,
    subtrees: list[str] | None = None,
    file_extensions: tuple[str, ...] = (".ets", ".ts", ".js"),
) -> dict:
    """
    Scan XTS/ACTS sources and build a usage index.

    Parameters
    ----------
    xts_root:
        Path to the XTS/ACTS root directory. If None or non-existent, an empty
        index is returned with a limitation note.
    max_files:
        Optional limit on the number of files to scan (useful for testing and
        CI speed).
    subtrees:
        Optional list of sub-directory names (relative to xts_root) to restrict
        scanning. Defaults to scanning the entire tree.
    file_extensions:
        File extensions to scan. Defaults to .ets, .ts, .js.

    Returns
    -------
    dict with keys:
        entries     list[dict]   — serialised UsageEntry records
        summary     dict         — aggregate stats
        limitations list[str]   — index-level limitation notes
        schema_version str
    """
    index_limitations: list[str] = []

    if xts_root is None:
        index_limitations.append("xts_root_not_provided")
        return _empty_index(index_limitations)

    root = Path(xts_root)
    if not root.exists():
        index_limitations.append(f"xts_root_not_found: {root}")
        return _empty_index(index_limitations)

    # Collect files to scan
    search_roots: list[Path] = []
    if subtrees:
        for st in subtrees:
            candidate = root / st
            if candidate.is_dir():
                search_roots.append(candidate)
            else:
                index_limitations.append(f"subtree_not_found: {st}")
    if not search_roots:
        search_roots = [root]

    files: list[Path] = []
    for sr in search_roots:
        for ext in file_extensions:
            for f in sr.rglob(f"*{ext}"):
                files.append(f)
                if max_files is not None and len(files) >= max_files:
                    break
            if max_files is not None and len(files) >= max_files:
                break
        if max_files is not None and len(files) >= max_files:
            break

    if max_files is not None and len(files) >= max_files:
        index_limitations.append(
            f"scan_truncated_at_{max_files}_files: full_index_requires_larger_max_files"
        )

    # Scan
    all_entries: list[UsageEntry] = []
    for f in files:
        all_entries.extend(_scan_file(f, root))

    all_entries = _deduplicate(all_entries)

    # Build summary
    kind_counts: dict[str, int] = {}
    conf_counts: dict[str, int] = {}
    api_set: set[str] = set()
    project_set: set[str] = set()
    for e in all_entries:
        kind_counts[e.usage_kind] = kind_counts.get(e.usage_kind, 0) + 1
        conf_counts[e.confidence] = conf_counts.get(e.confidence, 0) + 1
        api_set.add(e.api_name)
        project_set.add(e.project)

    summary = {
        "files_scanned": len(files),
        "total_entries": len(all_entries),
        "unique_api_names": len(api_set),
        "unique_projects": len(project_set),
        "by_usage_kind": kind_counts,
        "by_confidence": conf_counts,
    }

    index_limitations += [
        "textual_heuristics_only_no_type_resolution",
        "attribute_and_event_receiver_not_verified",
        "no_coverage_equivalence_granted",
        "internal_modifier_names_excluded_from_api_name",
    ]

    return {
        "schema_version": "1.0",
        "entries": [e.to_dict() for e in all_entries],
        "summary": summary,
        "limitations": index_limitations,
    }


def _empty_index(limitations: list[str]) -> dict:
    return {
        "schema_version": "1.0",
        "entries": [],
        "summary": {
            "files_scanned": 0,
            "total_entries": 0,
            "unique_api_names": 0,
            "unique_projects": 0,
            "by_usage_kind": {},
            "by_confidence": {},
        },
        "limitations": limitations
        + [
            "textual_heuristics_only_no_type_resolution",
            "attribute_and_event_receiver_not_verified",
            "no_coverage_equivalence_granted",
            "internal_modifier_names_excluded_from_api_name",
        ],
    }


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build XTS usage index v1 (textual heuristics)"
    )
    parser.add_argument(
        "xts_root",
        nargs="?",
        default=os.environ.get("XTS_ACTS_ROOT"),
        help="Path to XTS/ACTS root (default: $XTS_ACTS_ROOT)",
    )
    parser.add_argument("--subtrees", nargs="*", help="Subdirectory names to scan")
    parser.add_argument(
        "--max-files", type=int, default=None, help="Max files to scan"
    )
    parser.add_argument(
        "--output", "-o", default=None, help="Output JSON file path (default: stdout)"
    )
    args = parser.parse_args(argv)

    index = build_usage_index(
        args.xts_root,
        max_files=args.max_files,
        subtrees=args.subtrees,
    )

    payload = json.dumps(index, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
