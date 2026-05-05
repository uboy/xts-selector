"""ETS test file indexer.

This module indexes ETS test files and extracts API references from parsed usages.

Import boundary: standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ets_parser import EtsUsage, EtsParseResult


@dataclass(frozen=True)
class EtsTestEntry:
    """An ETS test file entry with extracted API references."""
    file_path: str
    test_module: str  # Derived from directory structure
    usages: tuple["EtsUsage", ...] = ()
    api_references: tuple[str, ...] = ()  # API symbol names referenced
    entry_kind: str = "consumer"  # "consumer" (XTS test file) or "bridge" (generated/sdk source)

    @property
    def is_consumer(self) -> bool:
        """True if this is a consumer (XTS test) entry."""
        return self.entry_kind == "consumer"

    @property
    def is_bridge(self) -> bool:
        """True if this is a bridge (generated/sdk source) entry."""
        return self.entry_kind == "bridge"

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        d: dict[str, object] = {
            "file_path": self.file_path,
            "test_module": self.test_module,
            "api_references": list(self.api_references),
        }
        if self.entry_kind != "consumer":
            d["entry_kind"] = self.entry_kind
        if self.usages:
            d["usages"] = [usage.to_dict() for usage in self.usages]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> EtsTestEntry:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        # Handle usages - they may not be included in dict
        usages_data = data.get("usages")
        usages: tuple["EtsUsage", ...] = ()
        if usages_data:
            from .ets_parser import EtsUsage
            usages = tuple(EtsUsage.from_dict(u) for u in usages_data)

        return cls(
            file_path=data.get("file_path", ""),
            test_module=data.get("test_module", ""),
            usages=usages,
            api_references=tuple(data.get("api_references", [])),
            entry_kind=data.get("entry_kind", "consumer"),
        )


@dataclass(frozen=True)
class EtsIndexError:
    """An error that occurred during ETS indexing."""
    file_path: str
    error: str

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "file_path": self.file_path,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EtsIndexError:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        return cls(
            file_path=data.get("file_path", ""),
            error=data.get("error", ""),
        )


@dataclass(frozen=True)
class EtsIndexResult:
    """Result of indexing ETS test files."""
    entries: tuple[EtsTestEntry, ...] = ()
    errors: tuple[EtsIndexError, ...] = ()
    total_usages: int = 0
    index_time_ms: float = 0.0
    source: str = "ets_indexer"

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "errors": [error.to_dict() for error in self.errors],
            "total_usages": self.total_usages,
            "index_time_ms": self.index_time_ms,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EtsIndexResult:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        entries_data = data.get("entries", [])
        errors_data = data.get("errors", [])
        return cls(
            entries=tuple(EtsTestEntry.from_dict(e) for e in entries_data),
            errors=tuple(EtsIndexError.from_dict(e) for e in errors_data),
            total_usages=data.get("total_usages", 0),
            index_time_ms=data.get("index_time_ms", 0.0),
            source=data.get("source", "ets_indexer"),
        )


def _extract_test_module(file_path: Path | str, xts_root: Path) -> str:
    """Extract the test module name from the file path relative to xts_root.

    Args:
        file_path: Path to the .ets file (Path or string)
        xts_root: Root directory of XTS tests

    Returns:
        Test module name (e.g., "ActsButtonTest")
    """
    try:
        # Convert to Path if needed
        if isinstance(file_path, str):
            file_path = Path(file_path)
        rel_path = file_path.relative_to(xts_root)
        # The module is typically the parent directory name
        if rel_path.parent != Path("."):
            return rel_path.parent.name
    except ValueError:
        pass
    return "unknown"


def _extract_api_references(usages: tuple["EtsUsage", ...]) -> tuple[str, ...]:
    """Extract unique API symbol names from usages.

    Args:
        usages: Tuple of EtsUsage objects

    Returns:
        Tuple of unique API symbol names
    """
    api_symbols = set()
    for usage in usages:
        # Add the symbol name
        api_symbols.add(usage.symbol_name)

        # For property accesses, also add the type part
        if usage.usage_type == "property_access" and "." in usage.symbol_name:
            type_part = usage.symbol_name.split(".")[0]
            api_symbols.add(type_part)

    return tuple(sorted(api_symbols))


# Bridge path indicators — generated/sdk source files, not XTS test consumers
_BRIDGE_PATH_INDICATORS = (
    "generated/src",
    "arkoala",
    "sdk/api",
    "interface/sdk",
    ".sdk_cache",
    "build-tools",
    "compiler_api",
)


def _classify_entry(file_path: str) -> str:
    """Classify an ETS file as 'consumer' or 'bridge'.

    Bridge entries are generated SDK sources or framework glue code.
    Consumer entries are actual XTS test files.

    Args:
        file_path: Path to the .ets file

    Returns:
        "consumer" or "bridge"
    """
    lower_path = file_path.lower().replace("\\", "/")
    for indicator in _BRIDGE_PATH_INDICATORS:
        if indicator in lower_path:
            return "bridge"
    return "consumer"


def _walk_depth(root: Path, max_depth: int):
    """Walk directory tree up to max_depth, yielding Path entries."""
    import os
    root_str = str(root)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root_str):].count(os.sep)
        if depth >= max_depth:
            dirnames.clear()  # Don't descend further
        for filename in filenames:
            yield Path(dirpath) / filename


def build_ets_index(xts_root: Path, max_depth: int | None = None) -> EtsIndexResult:
    """Build an index of ETS test files and extract API references.

    Args:
        xts_root: Root directory containing XTS test files
        max_depth: Optional max directory depth for file search.
                   None = unlimited (default).

    Returns:
        EtsIndexResult with entries, errors, and usage counts
    """
    import time

    start_time = time.time()

    # Find all .ets files
    ets_files: list[Path] = []
    if xts_root.is_dir():
        if max_depth is not None:
            # Use depth-limited walk instead of rglob + filter
            for entry in _walk_depth(xts_root, max_depth):
                if entry.is_file() and entry.suffix == ".ets":
                    ets_files.append(entry)
            ets_files.sort()
        else:
            ets_files = sorted(xts_root.rglob("*.ets"))

    from .ets_parser import parse_ets_file, EtsParseResult

    entries: list[EtsTestEntry] = []
    errors: list[EtsIndexError] = []
    total_usages = 0

    for ets_file in ets_files:
        try:
            parse_result: EtsParseResult = parse_ets_file(ets_file)

            test_module = _extract_test_module(ets_file, xts_root)
            api_refs = _extract_api_references(parse_result.usages)

            entry = EtsTestEntry(
                file_path=str(ets_file),
                test_module=test_module,
                usages=parse_result.usages,
                api_references=api_refs,
                entry_kind=_classify_entry(str(ets_file)),
            )
            entries.append(entry)
            total_usages += len(parse_result.usages)

        except Exception as e:
            errors.append(EtsIndexError(
                file_path=str(ets_file),
                error=str(e),
            ))

    index_time = (time.time() - start_time) * 1000

    return EtsIndexResult(
        entries=tuple(entries),
        errors=tuple(errors),
        total_usages=total_usages,
        index_time_ms=index_time,
    )
