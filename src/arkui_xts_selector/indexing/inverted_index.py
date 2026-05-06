"""Inverted index: API entity -> XTS consumer projects.

Maps each ApiEntityId canonical string to the list of XTS consumer projects
that use it. Built from extract_api_usages() output across XTS test files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..model.api import ApiEntityId
from .ets_indexer import build_ets_index, EtsIndexResult
from .sdk_indexer import SdkIndexResult
from .usage_extractor import extract_api_usages, ApiUsage


@dataclass(frozen=True)
class ConsumerEntry:
    """A consumer project that uses an API entity."""
    project_path: str        # e.g. "arkui/ace_ets_module_button_role_static"
    file_path: str           # e.g. ".../ButtonRoleTest.ets"
    line: int                # usage line
    usage_kind: str          # "component_instantiation" | "chained_modifier" | ...
    confidence: str

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "project_path": self.project_path,
            "file_path": self.file_path,
            "line": self.line,
            "usage_kind": self.usage_kind,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConsumerEntry:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        return cls(**data)


@dataclass
class InvertedIndex:
    """API entity -> list of consumer entries."""
    by_api: dict[str, list[ConsumerEntry]] = field(default_factory=dict)

    def consumers_for(self, api_id: ApiEntityId) -> list[ConsumerEntry]:
        """Look up consumers by exact ApiEntityId."""
        return self.by_api.get(api_id.canonical(), [])

    def consumers_for_api_id(self, api_id_str: str) -> list[ConsumerEntry]:
        """Look up consumers by canonical API id string (e.g. 'ButtonAttribute.role').

        This is the primary exact lookup path. Returns consumers whose
        canonical index key matches exactly.
        """
        return self.by_api.get(api_id_str, [])

    def consumers_for_canonical(self, canonical_id: str) -> list[ConsumerEntry]:
        """Look up consumers by canonical ID string.

        Tries exact match first, then member_name suffix match.

        TODO(api-xts-quality): R6 from REVIEW_FIX_COMMIT_1a33a0d — Phase 0.3 prerequisite.
        Substring fallback (lines 74-77) inflates exact_consumer_hit_rate.
        Replace with dedicated member_name index for precise lookup.
        """
        # Exact match
        entries = self.by_api.get(canonical_id, [])
        if entries:
            return entries

        # Try matching by the member portion (e.g. "role" from "ButtonAttribute.role")
        if "." in canonical_id:
            member = canonical_id.rsplit(".", 1)[-1]
            # Find entries where the canonical contains this member in context
            results = []
            for key, consumers in self.by_api.items():
                if key.endswith(f".{member}") or f".{member}:" in key:
                    results.extend(consumers)
            return results

        return []

    def consumers_for_name(self, public_name: str) -> list[ConsumerEntry]:
        """Look up consumers by public name (fuzzy substring).

        This is the fallback path with provenance=fuzzy_name_fallback.
        Prefer consumers_for_api_id() or consumers_for_canonical() for
        production paths.
        """
        results = []
        for canonical, entries in self.by_api.items():
            if public_name in canonical:
                results.extend(entries)
        return results

    def all_api_names(self) -> list[str]:
        """Return all indexed API canonical IDs."""
        return list(self.by_api.keys())

    def total_consumers(self) -> int:
        """Total consumer entries across all APIs."""
        return sum(len(entries) for entries in self.by_api.values())

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict."""
        return {
            "by_api": {
                api: [e.to_dict() for e in entries]
                for api, entries in self.by_api.items()
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> InvertedIndex:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        by_api = {}
        for api, entries in data.get("by_api", {}).items():
            by_api[api] = [ConsumerEntry.from_dict(e) for e in entries]
        return cls(by_api=by_api)


def build_inverted_index(
    xts_root: Path,
    sdk_index: SdkIndexResult,
    max_depth: int = 8,
) -> InvertedIndex:
    """Walk xts_root, extract usages, build api -> consumers map.

    Args:
        xts_root: Root directory of XTS test files
        sdk_index: SDK index for API resolution
        max_depth: Max directory depth for ETS file search (default 8).
                   Limits scope to avoid scanning 50K+ files.

    Returns:
        InvertedIndex mapping API canonical IDs to consumer entries
    """
    ets_result = build_ets_index(xts_root, max_depth=max_depth)
    # T9.2: Only use consumer entries for inverted index (exclude bridge/generated files)
    consumer_result = EtsIndexResult(
        entries=tuple(e for e in ets_result.entries if e.is_consumer),
        errors=ets_result.errors,
        total_usages=sum(len(e.usages) for e in ets_result.entries if e.is_consumer),
        index_time_ms=ets_result.index_time_ms,
    )
    usages = extract_api_usages(consumer_result, sdk_index=sdk_index)

    by_api: dict[str, list[ConsumerEntry]] = {}
    for usage in usages:
        # Find the test project (directory containing Test.json)
        proj = _find_test_project(Path(usage.source_file), xts_root)
        if proj is None:
            # Use parent directory as fallback
            proj = Path(usage.source_file).parent

        try:
            rel_path = str(proj.relative_to(xts_root))
        except ValueError:
            rel_path = str(proj)

        # Resolve api_name to ApiEntityId using sdk_index
        api_id = _resolve_api_entity_id(usage.api_name, sdk_index)
        canonical = api_id.canonical()

        by_api.setdefault(canonical, []).append(ConsumerEntry(
            project_path=rel_path,
            file_path=usage.source_file,
            line=usage.line or 0,
            usage_kind=usage.usage_type,
            confidence=usage.confidence,
        ))
    return InvertedIndex(by_api=by_api)


def _resolve_api_entity_id(api_name: str, sdk_index: SdkIndexResult) -> ApiEntityId:
    """Resolve an API name string to an ApiEntityId using the SDK index.

    Args:
        api_name: The API name string (e.g., "Button", "ButtonAttribute.type")
        sdk_index: SDK index to look up the API entity

    Returns:
        ApiEntityId for the given API name, or a minimal ApiEntityId if not found
    """
    # Try to find the entry in the SDK index
    entry = sdk_index.find(api_name)
    if entry is not None:
        return entry.api_id

    # If not found, create a minimal ApiEntityId with just the name
    # This allows the inverted index to still track the usage even if
    # the API is not in the SDK registry
    return ApiEntityId.from_parts(
        public_name=api_name,
    )


def _find_test_project(file: Path, root: Path) -> Path | None:
    """Walk up from file to find a directory containing Test.json.

    Args:
        file: Path to the test file
        root: Root directory to stop at

    Returns:
        Path to the project directory containing Test.json, or None if not found
    """
    current = file.parent
    while current != root and current != current.parent:
        if (current / "Test.json").exists():
            return current
        current = current.parent
    return None
