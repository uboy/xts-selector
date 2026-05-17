"""Map AST oracle MethodChange entries to canonical API IDs.

Bridges validation/ast_oracle output to the selector's API namespace
using file role classification and SDK index lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ConfidenceLevel = Literal["high", "medium", "unmapped"]


@dataclass(frozen=True)
class MappedApi:
    change_kind: str
    qualified_name: str
    parent_class: str | None
    method_name: str
    file_path: str
    file_role: str
    canonical_id: str | None = None
    sdk_family: str | None = None
    confidence: ConfidenceLevel = "unmapped"


def map_method_changes(
    method_changes: list[dict],
    family_lookup: dict[str, str] | None = None,
) -> list[MappedApi]:
    """Map MethodChange dicts to MappedApi with canonical IDs.

    Args:
        method_changes: List of MethodChange dicts from ast_oracle
        family_lookup: Optional mapping of file_path → family name

    Returns:
        List of MappedApi entries with confidence levels
    """
    from ..indexing.file_role import classify as classify_role

    results: list[MappedApi] = []

    for change in method_changes:
        file_path = change.get("file_path", "")
        parent_class = change.get("parent_class")
        method_name = change.get("method_name", "")
        qualified_name = change.get("qualified_name", "")
        change_kind = change.get("change_kind", "")

        role, family = classify_role(file_path)

        confidence = _compute_confidence(change_kind, role)

        canonical_id = None
        if family and method_name:
            canonical_id = f"{family}/{method_name}"

        family_name = family
        if family_lookup and file_path in family_lookup:
            family_name = family_lookup[file_path]

        results.append(
            MappedApi(
                change_kind=change_kind,
                qualified_name=qualified_name,
                parent_class=parent_class,
                method_name=method_name,
                file_path=file_path,
                file_role=role,
                canonical_id=canonical_id,
                sdk_family=family_name,
                confidence=confidence,
            )
        )

    return results


def _compute_confidence(change_kind: str, file_role: str) -> ConfidenceLevel:
    if change_kind in ("signature_modified", "added_method", "removed_method"):
        if file_role in ("model_static", "model_ng", "native_modifier"):
            return "high"
        if file_role in ("pattern", "infrastructure"):
            return "medium"
    if change_kind == "body_modified":
        if file_role in ("model_static", "model_ng"):
            return "high"
        if file_role in ("pattern", "native_modifier"):
            return "medium"
    return "unmapped"


def group_by_confidence(mappings: list[MappedApi]) -> dict[ConfidenceLevel, list[str]]:
    """Group mapped APIs by confidence level, returning canonical IDs."""
    result: dict[ConfidenceLevel, list[str]] = {
        "high": [],
        "medium": [],
        "unmapped": [],
    }
    for m in mappings:
        if m.canonical_id:
            result[m.confidence].append(m.canonical_id)
    return result
