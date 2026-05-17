"""Enrich string API names into structured affected_api_entity_details.

Legacy pipeline produces affected_api_entities as list[str].
This module converts strings to structured objects with kind/surface/confidence.

Rules:
- SDK-indexed names get real kind and strong confidence.
- Suffix-inferred names (Modifier, Attribute, etc) get kind but unknown confidence
  and a limitation flag — never promoted to public API.
- Completely unknown names stay unknown in all fields.
- Confidence never raised without evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from .api_lineage import ApiLineageMap
    from .models import SdkIndex

_SUFFIX_KIND_MAP = (
    ("Modifier", "modifier"),
    ("Attribute", "attribute"),
    ("Configuration", "configuration"),
    ("Controller", "controller"),
)


def enrich_api_entity(
    api_name: str,
    sdk_index: SdkIndex | None = None,
    api_lineage_map: ApiLineageMap | None = None,
) -> dict:
    """Convert a string API name to a structured detail dict.

    Uses SDK index and lineage map when available to populate
    kind, surface, confidence with real data. Falls back to
    suffix-based heuristics with appropriate caveats.
    """
    kind = "unknown"
    surface = "unknown"
    confidence = "unknown"
    evidence_types: list[str] = []
    limitation: str | None = None

    # SDK index lookup
    if sdk_index is not None:
        in_components = api_name in sdk_index.component_names
        in_modifiers = api_name in sdk_index.modifier_names
        if in_components or in_modifiers:
            if in_components:
                kind = "component"
            elif in_modifiers:
                kind = "modifier"
            evidence_types.append("sdk_declaration")
            confidence = "strong"

    # Fallback: infer kind from suffix
    if kind == "unknown":
        for suffix, mapped in _SUFFIX_KIND_MAP:
            if api_name.endswith(suffix):
                kind = mapped
                if not evidence_types:
                    limitation = "internal_name_only"
                break

    # Surface from lineage map
    if api_lineage_map is not None and api_name in api_lineage_map.api_to_surfaces:
        surfaces = api_lineage_map.api_to_surfaces[api_name]
        if surfaces:
            surface = sorted(surfaces)[0]
            if "sdk_declaration" not in evidence_types:
                evidence_types.append("source_symbol")
                if confidence == "unknown":
                    confidence = "medium"

    source_files: list[str] = []
    if api_lineage_map is not None:
        source_files = sorted(api_lineage_map.api_to_sources.get(api_name, set()))[:5]

    return {
        "api_name": api_name,
        "kind": kind,
        "surface": surface,
        "confidence": confidence,
        "evidence_types": evidence_types,
        "source_files": source_files,
        "limitation": limitation,
    }


def build_affected_api_entity_details(
    api_entities: Sequence[str],
    sdk_index: SdkIndex | None = None,
    api_lineage_map: ApiLineageMap | None = None,
) -> list[dict]:
    """Build structured detail objects from a sequence of API entity names."""
    return [enrich_api_entity(name, sdk_index, api_lineage_map) for name in api_entities]
