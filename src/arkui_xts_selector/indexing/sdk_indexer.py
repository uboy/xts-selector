"""SDK indexer for .d.ts files using tree-sitter TypeScript.

This module builds a complete registry of public API entities by parsing
.d.ts files and converting SymbolDiscovery objects into SdkIndexEntry records.

Import boundary: standard library + arkui_xts_selector.model only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parser_contracts import ParserResult

from ..model.api import ApiEntityId, ApiDeclarationRef


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

_COMMON_PARENTS = (
    "CommonMethod",
    "CommonAttribute",
    "CommonShapeMethod",
    "CommonTransition",
    "ContainerCommonMethod",
)


# ---------------------------------------------------------------------------
# SdkIndexEntry – a single SDK declaration entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SdkIndexEntry:
    """A single SDK declaration entry in the index."""

    api_id: ApiEntityId
    declaration: ApiDeclarationRef
    parent_api_id: ApiEntityId | None = None
    member_name: str | None = None
    api_version: str | None = None  # from ApiDeclarationRef.since_api
    declaration_kind: str | None = (
        None  # "component", "attribute", "method", "event", "enum", "interface", "namespace", "function"
    )
    dispatch_kind: str | None = (
        None  # "static", "instance", "dynamic", "generated_bridge", "common_inherited", "direct"
    )

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d: dict[str, object] = {
            "api_id": self.api_id.to_dict(),
            "declaration": self.declaration.to_dict(),
        }
        if self.parent_api_id is not None:
            d["parent_api_id"] = self.parent_api_id.to_dict()
        if self.member_name is not None:
            d["member_name"] = self.member_name
        if self.api_version is not None:
            d["api_version"] = self.api_version
        if self.declaration_kind is not None:
            d["declaration_kind"] = self.declaration_kind
        if self.dispatch_kind is not None:
            d["dispatch_kind"] = self.dispatch_kind
        return d

    @classmethod
    def from_dict(cls, data: dict) -> SdkIndexEntry:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        parent_id_data = data.get("parent_api_id")
        return cls(
            api_id=ApiEntityId.from_dict(data["api_id"])
            if "api_id" in data
            else ApiEntityId(),
            declaration=ApiDeclarationRef.from_dict(data["declaration"])
            if "declaration" in data
            else ApiDeclarationRef(),
            parent_api_id=ApiEntityId.from_dict(parent_id_data)
            if parent_id_data
            else None,
            member_name=data.get("member_name"),
            api_version=data.get("api_version"),
            declaration_kind=data.get("declaration_kind"),
            dispatch_kind=data.get("dispatch_kind"),
        )


# ---------------------------------------------------------------------------
# SdkIndexResult – result of indexing SDK declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SdkIndexResult:
    """Result of indexing SDK declarations."""

    entries: tuple[SdkIndexEntry, ...] = ()
    parse_errors: tuple[str, ...] = ()
    files_scanned: int = 0
    index_time_ms: float = 0.0
    source: str = "tree-sitter-typescript"
    extends_graph: dict[str, list[str]] = field(
        default_factory=dict, repr=False, compare=False
    )
    alias_graph: dict[str, list[str]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        # Build O(1) lookup indexes (frozen=True requires object.__setattr__)
        by_public: dict[str, SdkIndexEntry] = {}
        by_parent_member: dict[tuple[str, str], SdkIndexEntry] = {}
        by_parent_lower_member: dict[
            tuple[str, str], list[tuple[str, SdkIndexEntry]]
        ] = {}
        by_member_only: dict[str, list[SdkIndexEntry]] = {}
        for entry in self.entries:
            pn = entry.api_id.public_name
            if pn and pn not in by_public:
                by_public[pn] = entry
            mn = entry.member_name or entry.api_id.member_name
            if mn:
                parent_name = None
                if entry.parent_api_id and entry.parent_api_id.public_name:
                    parent_name = entry.parent_api_id.public_name
                elif entry.api_id.member_of:
                    parent_name = entry.api_id.member_of
                elif entry.api_id.member_name and pn:
                    parent_name = pn
                if parent_name:
                    pk = (parent_name, mn)
                    if pk not in by_parent_member:
                        by_parent_member[pk] = entry
                    # Case-insensitive index: group by (parent.lower(), member)
                    lk = (parent_name.lower(), mn)
                    by_parent_lower_member.setdefault(lk, []).append(
                        (parent_name, entry)
                    )
                by_member_only.setdefault(mn, []).append(entry)
        object.__setattr__(self, "_by_public", by_public)
        object.__setattr__(self, "_by_parent_member", by_parent_member)
        object.__setattr__(self, "_by_parent_lower_member", by_parent_lower_member)
        object.__setattr__(self, "_by_member_only", by_member_only)

    def find(self, name: str) -> SdkIndexEntry | None:
        """Find an entry by its public name (or member name).

        Args:
            name: The name to search for. Can be a simple name like "Button"
                  or a member name like "ButtonAttribute.role".

        Returns:
            The matching SdkIndexEntry, or None if not found.
            If ``name`` is a bare member name (no dot) and it matches
            multiple entries with *different* parents, returns None to
            signal ambiguity instead of silently returning the first match.
        """
        # O(1) public name lookup
        hit = self._by_public.get(name)
        if hit is not None:
            return hit

        # O(1) full member lookup (e.g. "ButtonAttribute.role")
        if "." in name:
            parent, member = name.split(".", 1)
            hit = self._by_parent_member.get((parent, member))
            if hit is not None:
                return hit

        # Bare member name — check ambiguity
        cands = self._by_member_only.get(name)
        if cands is not None:
            if len(cands) == 1:
                return cands[0]
            return None  # ambiguous

        # Last resort: check alias graph
        if self.alias_graph and name in self.alias_graph:
            for alias_target in self.alias_graph[name]:
                hit = self._by_public.get(alias_target)
                if hit is not None:
                    return hit

        return None

    def find_all(self, name: str) -> list[SdkIndexEntry]:
        """Find all entries matching a name (public or member).

        Unlike ``find()``, this does not treat ambiguity as a special case;
        it returns every match.  Useful for discovering all candidates when
        the parent context is unknown.
        """
        results: list[SdkIndexEntry] = []
        hit = self._by_public.get(name)
        if hit is not None:
            results.append(hit)
        results.extend(self._by_member_only.get(name, []))
        return results

    def find_descendants(self, parent_name: str, max_depth: int = 3) -> list[str]:
        """BFS traversal of extends_graph to find all descendant names."""
        if not self.extends_graph:
            return []
        visited: set[str] = set()
        queue: list[str] = [parent_name]
        descendants: list[str] = []
        depth = 0
        while queue and depth < max_depth:
            next_queue: list[str] = []
            for name in queue:
                children = self.extends_graph.get(name, [])
                for child in children:
                    if child not in visited:
                        visited.add(child)
                        descendants.append(child)
                        next_queue.append(child)
            queue = next_queue
            depth += 1
        return descendants

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "parse_errors": list(self.parse_errors),
            "files_scanned": self.files_scanned,
            "index_time_ms": self.index_time_ms,
            "source": self.source,
        }

    def find_member(
        self, member_name: str, parent_name: str | None = None
    ) -> SdkIndexEntry | None:
        """Find a member by name, optionally disambiguated by parent."""
        if parent_name:
            # O(1) lookup: (parent, member)
            hit = self._by_parent_member.get((parent_name, member_name))
            if hit is not None:
                return hit
            # O(1) case-insensitive lookup via lowercase index
            lk = (parent_name.lower(), member_name)
            cands = self._by_parent_lower_member.get(lk)
            if cands:
                if len(cands) == 1:
                    return cands[0][1]
                # Multiple parents match case-insensitively — ambiguous
                return None

        # Bare member name lookup
        cands = self._by_member_only.get(member_name)
        if cands is not None:
            if len(cands) == 1:
                return cands[0]
            return None  # ambiguous
        return None

    def find_attribute_member(
        self, member_name: str, family: str
    ) -> SdkIndexEntry | None:
        """Find a member in <Family>Attribute or <Family>Interface."""
        from .family_alias import normalize_family

        family_norm = normalize_family(family)
        for parent_suffix in ("Attribute", "Interface"):
            parent = f"{family_norm}{parent_suffix}"
            result = self.find_member(member_name, parent)
            if result:
                return result
        return self.find_member(member_name, family_norm)

    def find_common_member(self, member_name: str) -> SdkIndexEntry | None:
        """Find a member in common parent types (CommonMethod, etc.)."""
        for parent in _COMMON_PARENTS:
            entry = self.find_member(member_name, parent)
            if entry:
                return entry
        return None

    def find_all_member(self, member_name: str) -> list[SdkIndexEntry]:
        """Find all entries matching a bare member name across all parents."""
        return [
            e
            for e in self.entries
            if e.member_name == member_name or e.api_id.member_name == member_name
        ]

    def find_by_dispatch_kind(self, kind: str) -> list[SdkIndexEntry]:
        """Filter entries by dispatch_kind."""
        return [e for e in self.entries if e.dispatch_kind == kind]

    def find_by_version(self, min_version: str) -> list[SdkIndexEntry]:
        """Filter entries by api_version >= min_version."""

        def _version_key(v: str) -> tuple:
            parts = []
            for p in v.split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(0)
            return tuple(parts)

        min_key = _version_key(min_version)
        return [
            e
            for e in self.entries
            if e.api_version and _version_key(e.api_version) >= min_key
        ]

    @classmethod
    def from_dict(cls, data: dict) -> SdkIndexResult:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        entries_data = data.get("entries", [])
        return cls(
            entries=tuple(SdkIndexEntry.from_dict(e) for e in entries_data),
            parse_errors=tuple(data.get("parse_errors", [])),
            files_scanned=data.get("files_scanned", 0),
            index_time_ms=data.get("index_time_ms", 0.0),
            source=data.get("source", "tree-sitter-typescript"),
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _infer_dispatch_kind(symbol_kind: str, parent_name: str | None) -> str | None:
    """Infer dispatch kind from symbol kind and parent name."""
    if parent_name is None:
        return "static"
    if parent_name in _COMMON_PARENTS:
        return "common_inherited"
    if any(parent_name.endswith(s) for s in ("Attribute", "Interface")):
        return "instance"
    return "direct"


# ---------------------------------------------------------------------------
# build_sdk_index – main indexing function
# ---------------------------------------------------------------------------


def build_sdk_index(
    sdk_root: Path,
    namespace: str = "arkui",
    surface: str = "static",
) -> SdkIndexResult:
    """Build an SDK index from .d.ts files.

    Args:
        sdk_root: Root directory containing .d.ts files to index.
        namespace: Namespace for API IDs (default: "arkui").
        surface: API surface kind (default: "static").

    Returns:
        SdkIndexResult containing all indexed entries and any parse errors.
    """
    from .sdk_parser import parse_dts_file

    start_time = time.time()
    entries: list[SdkIndexEntry] = []
    parse_errors: list[str] = []
    files_scanned = 0
    all_aliases: list[tuple[str, str]] = []

    # Find all .d.ts files
    dts_files = list(sdk_root.rglob("*.d.ts"))

    for dts_file in dts_files:
        result: ParserResult = parse_dts_file(dts_file)
        files_scanned += 1

        # Collect any parse errors
        if result.limitations:
            parse_errors.append(f"{dts_file}: {', '.join(result.limitations)}")

        # Collect aliases for alias_graph
        all_aliases.extend(result.aliases)

        # Convert each SymbolDiscovery to an SdkIndexEntry
        for symbol in result.discovered_symbols:
            entry = _symbol_to_entry(
                symbol=symbol,
                file_path=str(dts_file),
                namespace=namespace,
                surface=surface,
            )
            if entry:
                entries.append(entry)

    index_time_ms = (time.time() - start_time) * 1000

    # Build extends_graph from parent_api_id relationships
    extends_graph: dict[str, list[str]] = {}
    for entry in entries:
        if entry.parent_api_id and entry.api_id.public_name:
            parent_name = entry.parent_api_id.public_name
            child_name = entry.api_id.public_name
            extends_graph.setdefault(parent_name, []).append(child_name)
    extends_graph = {k: list(set(v)) for k, v in extends_graph.items()}

    # Build alias_graph from collected aliases
    alias_graph: dict[str, list[str]] = {}
    for alias_name, original_name in all_aliases:
        alias_graph.setdefault(alias_name, [])
        if original_name not in alias_graph[alias_name]:
            alias_graph[alias_name].append(original_name)

    return SdkIndexResult(
        entries=tuple(entries),
        parse_errors=tuple(parse_errors),
        files_scanned=files_scanned,
        index_time_ms=index_time_ms,
        extends_graph=extends_graph,
        alias_graph=alias_graph,
    )


# ---------------------------------------------------------------------------
# _symbol_to_entry – convert SymbolDiscovery to SdkIndexEntry
# ---------------------------------------------------------------------------


def _symbol_to_entry(
    symbol: "SymbolDiscovery",
    file_path: str,
    namespace: str,
    surface: str,
) -> SdkIndexEntry | None:
    """Convert a SymbolDiscovery object to an SdkIndexEntry.

    Args:
        symbol: The SymbolDiscovery to convert.
        file_path: The file path where the symbol was found.
        namespace: The namespace for API IDs.
        surface: The API surface kind.

    Returns:
        An SdkIndexEntry, or None if the symbol cannot be converted.
    """
    module = _module_from_path(file_path)

    # Determine if this is a member or a top-level entity
    parent_name: str | None = None
    member_name: str | None = None
    public_name = symbol.symbol

    if "." in symbol.symbol:
        parts = symbol.symbol.split(".", 1)
        parent_name = parts[0]
        member_name = parts[1]
        public_name = parent_name

    # Create the API ID
    api_id = ApiEntityId.from_parts(
        namespace=namespace,
        surface=surface,
        kind=symbol.kind,
        module=module,
        public_name=public_name,
        member_of=parent_name,
        member_name=member_name,
    )

    # Create the declaration reference
    declaration = ApiDeclarationRef(
        declaration_id=api_id.canonical(),
        file_path=file_path,
        module=module,
        export_name=symbol.symbol,
        line=symbol.line,
        span=symbol.span,
        parser_level=3,  # AST-level
    )

    # Populate new metadata fields
    api_version = declaration.since_api  # from ApiDeclarationRef
    declaration_kind = symbol.kind  # "interface", "class", "method", "property", "enum"
    dispatch_kind = _infer_dispatch_kind(symbol.kind, parent_name)

    return SdkIndexEntry(
        api_id=api_id,
        declaration=declaration,
        member_name=member_name,
        api_version=api_version,
        declaration_kind=declaration_kind,
        dispatch_kind=dispatch_kind,
    )


# ---------------------------------------------------------------------------
# _module_from_path – derive module name from file path
# ---------------------------------------------------------------------------


def _module_from_path(file_path: str) -> str:
    """Derive a stable module name from a file path.

    Priority order:
      1. ``ohos.<name>`` segment right after ``interface/sdk-js/api``
      2. ``<name>`` segment right after a plain ``api/`` directory
      3. Parent directory of the .d.ts file (fallback)

    This ensures Button, ButtonAttribute, and ButtonModifier that live
    in the same ``button.d.ts`` all get the same module id.
    """
    path = Path(file_path)
    parts = path.parts

    # Pattern: .../interface/sdk-js/api/<module>/...
    for i, part in enumerate(parts):
        if part == "api" and i + 1 < len(parts):
            potential = parts[i + 1]
            if potential.startswith("ohos."):
                return potential
            # Non-ohos module under api/ — still stable
            if not potential.endswith(".d.ts"):
                return potential

    # Fallback: parent directory name (e.g. "button" from button/button.d.ts)
    if len(parts) >= 2:
        parent = parts[-2]
        # Avoid using the filename stem itself
        if parent != path.stem:
            return parent

    return "unknown"
