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
# SdkIndexEntry – a single SDK declaration entry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SdkIndexEntry:
    """A single SDK declaration entry in the index."""

    api_id: ApiEntityId
    declaration: ApiDeclarationRef
    parent_api_id: ApiEntityId | None = None
    member_name: str | None = None

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
        return d

    @classmethod
    def from_dict(cls, data: dict) -> SdkIndexEntry:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        parent_id_data = data.get("parent_api_id")
        return cls(
            api_id=ApiEntityId.from_dict(data["api_id"]) if "api_id" in data else ApiEntityId(),
            declaration=ApiDeclarationRef.from_dict(data["declaration"]) if "declaration" in data else ApiDeclarationRef(),
            parent_api_id=ApiEntityId.from_dict(parent_id_data) if parent_id_data else None,
            member_name=data.get("member_name"),
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
    extends_graph: dict[str, list[str]] = field(default_factory=dict, repr=False, compare=False)
    alias_graph: dict[str, list[str]] = field(default_factory=dict, repr=False, compare=False)

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
        # First, try exact match on public_name
        for entry in self.entries:
            if entry.api_id.public_name == name:
                return entry

        # If not found, try member names
        for entry in self.entries:
            if entry.member_name and entry.api_id.member_of:
                full_member = f"{entry.api_id.member_of}.{entry.member_name}"
                if full_member == name:
                    return entry

        # Also try matching by member_name alone (for pattern role mappings)
        # But check for ambiguity first — bare member names like "role" can
        # belong to ButtonAttribute, CheckboxAttribute, etc.
        candidates: list[SdkIndexEntry] = []
        for entry in self.entries:
            if entry.api_id.member_name == name:
                candidates.append(entry)
            elif entry.member_name == name:
                candidates.append(entry)

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            # Ambiguous — return None so callers know the name is not unique
            return None

        # Last resort: check alias graph
        if self.alias_graph and name in self.alias_graph:
            for alias_target in self.alias_graph[name]:
                for entry in self.entries:
                    if entry.api_id.public_name == alias_target:
                        return entry

        return None

    def find_all(self, name: str) -> list[SdkIndexEntry]:
        """Find all entries matching a name (public or member).

        Unlike ``find()``, this does not treat ambiguity as a special case;
        it returns every match.  Useful for discovering all candidates when
        the parent context is unknown.
        """
        results: list[SdkIndexEntry] = []
        for entry in self.entries:
            if entry.api_id.public_name == name:
                results.append(entry)
                continue
            if entry.member_name and entry.api_id.member_of:
                full_member = f"{entry.api_id.member_of}.{entry.member_name}"
                if full_member == name:
                    results.append(entry)
                    continue
            if entry.api_id.member_name == name or entry.member_name == name:
                results.append(entry)
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

    def find_member(self, member_name: str, parent_name: str | None = None) -> SdkIndexEntry | None:
        """Find a member by name, optionally disambiguated by parent."""
        candidates: list[SdkIndexEntry] = []
        for entry in self.entries:
            if entry.member_name != member_name and entry.api_id.member_name != member_name:
                continue
            if parent_name:
                member_of = entry.api_id.member_of or ""
                parent_pub = entry.parent_api_id.public_name if entry.parent_api_id else ""
                if parent_name.lower() not in member_of.lower() and parent_name.lower() not in parent_pub.lower():
                    continue
            candidates.append(entry)

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            return None
        return None

    def find_attribute_member(self, member_name: str, family: str) -> SdkIndexEntry | None:
        """Find a member in <Family>Attribute or <Family>CommonMethod."""
        family_cap = family.capitalize()
        for parent_suffix in ("Attribute", "CommonMethod", "Interface"):
            parent = f"{family_cap}{parent_suffix}"
            result = self.find_member(member_name, parent)
            if result:
                return result
        return self.find_member(member_name, family)

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
    from .parser_contracts import SymbolDiscovery

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

    return SdkIndexEntry(
        api_id=api_id,
        declaration=declaration,
        member_name=member_name,
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
