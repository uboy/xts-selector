"""AceEngine indexer for C++ source files.

This module provides:
- AceIndexEntry: An AceEngine source file entry with parsed C++ information
- AceIndexResult: Result of indexing AceEngine source files
- build_ace_index(): Build an index from AceEngine C++ source files

The indexer walks pattern/, interfaces/native/implementation/,
interfaces/native/node/, and bridge/declarative_frontend/jsview/ directories
to classify files by role (pattern, model_static, native_modifier, etc.)
and parse them to extract classes, methods, and includes.

Import boundary: standard library + arkui_xts_selector.indexing.file_role,
arkui_xts_selector.indexing.cpp_parser, arkui_xts_selector.indexing.cpp_macro_patterns only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path

from .cpp_macro_patterns import (
    MacroPattern,
    generate_synthetic_method_name,
    load_macro_patterns,
    match_macro_in_source,
)
from .cpp_parser import CppClass, CppMethod, parse_cpp_file
from .file_role import FileRole, classify


@dataclass(frozen=True)
class AceIndexEntry:
    """An AceEngine source file entry with parsed C++ information."""

    file_path: str
    role: FileRole
    family: str | None = None
    classes: tuple[CppClass, ...] = ()
    free_functions: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    paired_header: str | None = None
    """For .cpp files, the .h file in the same directory with matching stem, if any."""

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d: dict[str, object] = {
            "file_path": self.file_path,
            "role": self.role,
        }
        if self.family is not None:
            d["family"] = self.family
        if self.classes:
            d["classes"] = [cls.to_dict() for cls in self.classes]
        if self.free_functions:
            d["free_functions"] = list(self.free_functions)
        if self.includes:
            d["includes"] = list(self.includes)
        if self.paired_header is not None:
            d["paired_header"] = self.paired_header
        return d

    @classmethod
    def from_dict(cls, data: dict) -> AceIndexEntry:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        classes_data = data.get("classes", [])
        return cls(
            file_path=data.get("file_path", ""),
            role=data.get("role", "unknown"),
            family=data.get("family"),
            classes=tuple(_class_from_dict(c) for c in classes_data),
            free_functions=tuple(data.get("free_functions", ())),
            includes=tuple(data.get("includes", ())),
            paired_header=data.get("paired_header"),
        )


@dataclass(frozen=True)
class AceIndexResult:
    """Result of indexing AceEngine source files."""

    entries: tuple[AceIndexEntry, ...] = ()
    errors: tuple[str, ...] = ()  # Error messages for files that couldn't be parsed
    index_time_ms: float = 0.0
    source: str = "ace_indexer_cpp"

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "errors": list(self.errors),
            "index_time_ms": self.index_time_ms,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AceIndexResult:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        entries_data = data.get("entries", [])
        return cls(
            entries=tuple(AceIndexEntry.from_dict(e) for e in entries_data),
            errors=tuple(data.get("errors", ())),
            index_time_ms=data.get("index_time_ms", 0.0),
            source=data.get("source", "ace_indexer_cpp"),
        )


def _class_from_dict(data: dict) -> CppClass:
    """Helper to reconstruct CppClass from dict."""
    methods_data = data.get("methods", [])
    return CppClass(
        name=data.get("name", ""),
        base_class=data.get("base_class"),
        line=data.get("line"),
        end_line=data.get("end_line"),
        methods=tuple(_method_from_dict(m) for m in methods_data),
    )


def _method_from_dict(data: dict) -> CppMethod:
    """Helper to reconstruct CppMethod from dict."""
    return CppMethod(
        name=data.get("name", ""),
        parent_class=data.get("parent_class"),
        qualified=data.get("qualified"),
        line=data.get("line"),
        end_line=data.get("end_line"),
        body_span=tuple(data.get("body_span", ())) if data.get("body_span") else None,
        confidence=data.get("confidence", "strong"),
    )


# AceSourceEntry: Legacy type for backwards compatibility (deprecated)
@dataclass(frozen=True)
class AceSourceEntry:
    """An AceEngine source file entry (legacy, deprecated)."""

    file_path: str
    family: str | None = None
    surface: str = "static"
    provides_modifiers: tuple[str, ...] = ()
    implements_components: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d: dict[str, object] = {
            "file_path": self.file_path,
            "surface": self.surface,
        }
        if self.family is not None:
            d["family"] = self.family
        if self.provides_modifiers:
            d["provides_modifiers"] = list(self.provides_modifiers)
        if self.implements_components:
            d["implements_components"] = list(self.implements_components)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> AceSourceEntry:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        prov_mod = data.get("provides_modifiers")
        impl_comp = data.get("implements_components")
        return cls(
            file_path=data.get("file_path", ""),
            family=data.get("family"),
            surface=data.get("surface", "static"),
            provides_modifiers=tuple(prov_mod) if prov_mod else (),
            implements_components=tuple(impl_comp) if impl_comp else (),
        )


# Legacy AceIndexResult for backwards compatibility (deprecated)
@dataclass(frozen=True)
class _LegacyAceIndexResult:
    """Result of indexing AceEngine source files (legacy, deprecated)."""

    entries: tuple[AceSourceEntry, ...] = ()
    index_time_ms: float = 0.0
    source: str = "ace_source_parser"

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "index_time_ms": self.index_time_ms,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> _LegacyAceIndexResult:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        entries_data = data.get("entries", [])
        return cls(
            entries=tuple(AceSourceEntry.from_dict(e) for e in entries_data),
            index_time_ms=data.get("index_time_ms", 0.0),
            source=data.get("source", "ace_source_parser"),
        )


def _apply_macro_expansion_to_class(
    cpp_class: CppClass,
    source_content: str,
    macro_patterns: list[MacroPattern],
) -> CppClass:
    """Apply macro expansion to add synthetic methods to a class.

    Args:
        cpp_class: The class to potentially add methods to
        source_content: Source code content to scan for macro invocations
        macro_patterns: List of macro patterns to match against

    Returns:
        New CppClass with synthetic methods added (if any matches found)
    """
    # Match macro invocations in source
    match = match_macro_in_source(source_content, macro_patterns)
    if not match:
        return cpp_class

    pattern, arg1 = match

    # Generate synthetic method name
    synthetic_name = generate_synthetic_method_name(
        pattern.synthetic_method_pattern,
        [arg1],
    )
    if not synthetic_name:
        return cpp_class

    # Check if method already exists to avoid duplicates
    for existing_method in cpp_class.methods:
        if existing_method.name == synthetic_name:
            return cpp_class

    # Create synthetic method
    synthetic_method = CppMethod(
        name=synthetic_name,
        parent_class=cpp_class.name,
        qualified=f"{cpp_class.name}::{synthetic_name}",
        line=cpp_class.line,
        confidence=pattern.confidence,  # type: ignore
    )

    # Add to class methods
    existing_methods = list(cpp_class.methods)
    existing_methods.append(synthetic_method)

    # Return new class with synthetic method
    return replace(
        cpp_class,
        methods=tuple(existing_methods),
    )


def build_ace_index(
    ace_root: Path | str,
    families: list[str] | None = None,
    extensions: tuple[str, ...] = (".cpp", ".h"),
) -> AceIndexResult:
    """Build an index from AceEngine C++ source files.

    Walks the following directories under ace_root:
    - frameworks/core/components_ng/pattern/
    - frameworks/core/interfaces/native/implementation/
    - frameworks/core/interfaces/native/node/
    - frameworks/bridge/declarative_frontend/jsview/

    For each .cpp/.h file, classifies role via file_role.classify()
    and parses via cpp_parser.parse_cpp_file().

    Args:
        ace_root: Path to the AceEngine root directory
        families: Optional list of families to include. If None, includes all.
        extensions: File extensions to index (default: .cpp, .h)

    Returns:
        AceIndexResult with entries for each indexed file
    """
    start_time = time.perf_counter()
    ace_root = Path(ace_root) if isinstance(ace_root, str) else ace_root

    entries: list[AceIndexEntry] = []
    errors: list[str] = []

    # Load macro expansion patterns once (A.4: C++ Macro Expansion Table)
    macro_patterns = load_macro_patterns()

    # Directories to walk (Phase 6.3: expanded roots)
    directories = [
        ace_root / "frameworks" / "core" / "components_ng" / "pattern",
        ace_root / "frameworks" / "core" / "interfaces" / "native" / "implementation",
        ace_root / "frameworks" / "core" / "interfaces" / "native" / "node",
        ace_root / "frameworks" / "core" / "interfaces" / "native" / "generated",
        ace_root / "frameworks" / "core" / "interfaces" / "native" / "utility",
        ace_root / "frameworks" / "core" / "components_v2",
        ace_root / "frameworks" / "bridge" / "declarative_frontend" / "jsview",
    ]

    # Phase 6.3: koala_projects root — skip node_modules
    _KOALA_ROOT = (
        ace_root / "frameworks" / "bridge" / "arkts_frontend" / "koala_projects"
    )

    # Collect all file paths first for header pairing (Phase 6.2)
    all_file_paths: list[tuple[Path, str, FileRole, str | None]] = []

    for directory in directories:
        if not directory.is_dir():
            continue

        for ext in extensions:
            for file_path in sorted(directory.rglob(f"*{ext}")):
                try:
                    rel_path = file_path.relative_to(ace_root)
                except ValueError:
                    continue

                rel_path_str = str(rel_path).replace("\\", "/")
                role, family = classify(rel_path_str)

                if families is not None and family not in families:
                    continue

                # Skip infrastructure (but keep unknown for unresolved tracking)
                if role == "infrastructure":
                    continue

                all_file_paths.append((file_path, rel_path_str, role, family))

    # Phase 6.3: koala_projects — generated/component/ and src/component/
    # Bridge files are .ets, not .cpp/.h, so scan with .ets explicitly
    _KOALA_EXTENSIONS = extensions + (".ets",)
    if _KOALA_ROOT.is_dir():
        for ext in _KOALA_EXTENSIONS:
            for file_path in sorted(_KOALA_ROOT.rglob(f"*{ext}")):
                # Skip node_modules
                if "node_modules" in str(file_path):
                    continue
                try:
                    rel_path = file_path.relative_to(ace_root)
                except ValueError:
                    continue
                rel_path_str = str(rel_path).replace("\\", "/")
                # Classify as "jsview_dynamic" for bridge files
                role: FileRole = "unknown"
                family: str | None = None
                if (
                    "generated/component/" in rel_path_str
                    or "src/component/" in rel_path_str
                ):
                    role = "jsview_dynamic"
                all_file_paths.append((file_path, rel_path_str, role, family))

    # Phase 6.2: Build stem → header map for pairing
    _stem_to_header: dict[str, str] = {}
    for fp, rel, role_val, fam in all_file_paths:
        if fp.suffix in (".h",) and role_val != "unknown":
            stem = fp.stem
            _stem_to_header[f"{fp.parent}|{stem}"] = str(fp)

    # Walk all collected files and build entries
    for file_path, rel_path_str, role, family in all_file_paths:
        # Skip truly unknown files (no role match at all)
        if role == "unknown":
            continue

        # Phase 6.2: find paired header for .cpp files
        paired_header: str | None = None
        if file_path.suffix == ".cpp":
            key = f"{file_path.parent}|{file_path.stem}"
            paired_header = _stem_to_header.get(key)

        # Parse the file
        try:
            parse_result = parse_cpp_file(file_path)

            # A.4: Apply macro expansion to add synthetic methods
            expanded_classes: list[CppClass] = []
            if macro_patterns:
                try:
                    # Read source content for macro matching
                    source_content = file_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    for cpp_class in parse_result.classes:
                        # Only apply to pattern classes (not infrastructure)
                        if role == "pattern" and cpp_class.name:
                            expanded = _apply_macro_expansion_to_class(
                                cpp_class,
                                source_content,
                                macro_patterns,
                            )
                            expanded_classes.append(expanded)
                        else:
                            expanded_classes.append(cpp_class)
                except (OSError, IOError):
                    # If we can't read the file, use original classes
                    expanded_classes = list(parse_result.classes)
            else:
                expanded_classes = list(parse_result.classes)

            entry = AceIndexEntry(
                file_path=str(file_path),
                role=role,
                family=family,
                classes=tuple(expanded_classes),
                free_functions=parse_result.free_functions,
                includes=parse_result.includes,
                paired_header=paired_header,
            )
            entries.append(entry)
        except Exception as e:
            errors.append(f"Failed to parse {file_path}: {e}")

    index_time_ms = (time.perf_counter() - start_time) * 1000

    return AceIndexResult(
        entries=tuple(entries),
        errors=tuple(errors),
        index_time_ms=index_time_ms,
        source="ace_indexer_cpp",
    )
