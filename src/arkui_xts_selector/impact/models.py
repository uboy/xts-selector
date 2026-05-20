"""Data models for Universal Impact Resolution — Phase A.

These models are design-level contracts for the source entity classification
layer. They are additive and do not affect production selector output.

Import boundary: this module imports only the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Typed literals — design doc Section 5
# ---------------------------------------------------------------------------

SourceLayer = Literal[
    "component_pattern",
    "native_peer",
    "ani_bridge",
    "gesture_framework",
    "gesture_referee",
    "native_event",
    "native_node",
    "jsi_bridge",
    "common_method",
    "select_overlay",
    "inspector",
    "generated_binding",
    "test_only",
    "build_config",
    "unknown",
]

SourceRole = Literal[
    "sdk_peer_implementation",
    "ani_modifier_binding",
    "gesture_recognizer_core",
    "gesture_referee_core",
    "ndk_event_implementation",
    "ndk_node_gesture_implementation",
    "jsi_runtime_bridge",
    "jsi_native_module_bridge",
    "jsi_binding_definition",
    "common_method_dispatcher",
    "selection_overlay_runtime",
    "inspector_runtime",
    "component_behavior",
    "generated_output",
    "unit_test",
    "build_artifact",
    "unknown",
]

ConfidenceLevel = Literal["strong", "medium", "weak", "none"]


# ---------------------------------------------------------------------------
# Evidence reference
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRef:
    """Lightweight evidence pointer attached to a SourceImpactEntity.

    ``kind`` identifies the evidence type (e.g. ``"path_match"``,
    ``"symbol"``).  ``value`` is the rule id, symbol name, or other opaque
    identifier.
    """

    kind: str
    value: str


# ---------------------------------------------------------------------------
# Source impact entity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceImpactEntity:
    """A classified source file that may carry API impact.

    Fields
    ------
    id
        Stable identifier: ``f"{path}#{layer}#{role}"``.
    path
        Relative path within the repository (no absolute prefix).
    changed_symbols
        Optional symbols extracted from the diff.
    changed_hunks
        Optional hunk descriptions extracted from the diff.
    layer
        Structural layer of the source file (``SourceLayer``).
    role
        Functional role within the layer (``SourceRole``).
    owner_family_hint
        Tentative component family derived from the filename.
        This is lookup evidence only — it is NOT a public API claim.
    source_topic_hints
        Expanded topic strings for downstream resolvers.
        These are NOT SDK APIs; they are lookup hints.
    confidence
        Overall classification confidence.
    evidence
        Ordered evidence refs that justify the classification.
    limitations
        Known limitations or caveats for this entity.
    """

    id: str
    path: str
    changed_symbols: tuple[str, ...]
    changed_hunks: tuple[str, ...]
    layer: SourceLayer
    role: SourceRole
    owner_family_hint: str | None
    source_topic_hints: tuple[str, ...]
    confidence: ConfidenceLevel
    evidence: tuple[EvidenceRef, ...]
    limitations: tuple[str, ...]
