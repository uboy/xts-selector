"""Data models for Universal Impact Resolution — Phase B: Topic Resolver.

These models represent ImpactTopic, SdkApiTopic, ApiDeclarationRef,
ConsumerUsageEdge, and GestureResolutionResult.  They are additive and do
not affect production selector output.

Import boundary: this module imports only the standard library and
``arkui_xts_selector.impact.models``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

from arkui_xts_selector.impact.models import ConfidenceLevel

# ---------------------------------------------------------------------------
# Typed literals — design doc Section 5
# ---------------------------------------------------------------------------

FanoutKind = Literal["none", "bounded_family", "broad_profile"]
Domain = Literal[
    "component", "gesture", "native", "bridge", "common", "overlay", "inspector"
]


# ---------------------------------------------------------------------------
# ImpactTopic — maps source entity to API domain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImpactTopic:
    """A typed impact topic derived from a source entity.

    Fields
    ------
    topic_id
        Stable dotted identifier, e.g. ``"gesture.pan"``.
    domain
        High-level domain for the topic.
    name
        Human-readable short name.
    source_entities
        Entity IDs that produced this topic.
    expected_sdk_kinds
        SDK declaration kinds expected for this topic.
    fanout_kind
        Scope of downstream API/XTS fanout.
    confidence
        Topic confidence based on source evidence.
    limitations
        Known limitations or caveats.
    """

    topic_id: str
    domain: Domain
    name: str
    source_entities: Tuple[str, ...]
    expected_sdk_kinds: Tuple[str, ...]
    fanout_kind: FanoutKind
    confidence: ConfidenceLevel
    limitations: Tuple[str, ...]


# ---------------------------------------------------------------------------
# ApiDeclarationRef — pointer to a SDK declaration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiDeclarationRef:
    """A reference to a public SDK declaration.

    Fields
    ------
    public_name
        SDK-visible name, e.g. ``"PanGesture"``.
    kind
        Declaration kind: ``"component"``, ``"configuration"``,
        ``"event_or_method"``, or ``"module"``.
    sdk_path_hint
        Optional hint for where in the SDK this is declared.
    """

    public_name: str
    kind: str  # "component", "configuration", "event_or_method", "module"
    sdk_path_hint: Optional[str] = None


# ---------------------------------------------------------------------------
# SdkApiTopic — SDK-validated API surface for an impact topic
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SdkApiTopic:
    """SDK API topic produced by validating impact topics against the SDK index.

    Fields
    ------
    topic_id
        Matches an ``ImpactTopic.topic_id``.
    public_names
        SDK-visible public names.  These are the only names that may appear
        in public API impact output — internal C++ class names must NOT appear
        here.
    declarations
        SDK declaration references, one per ``public_names`` entry (when
        available).
    expected_usage_kinds
        XTS usage kinds to look for when linking consumer edges.
    source_topic_ids
        ImpactTopic IDs that produced this SDK API topic.
    api_confidence
        Confidence after SDK declaration validation.
    unresolved_reasons
        Reasons why SDK validation was incomplete or skipped.
    """

    topic_id: str
    public_names: Tuple[str, ...]
    declarations: Tuple[ApiDeclarationRef, ...]
    expected_usage_kinds: Tuple[str, ...]
    source_topic_ids: Tuple[str, ...]
    api_confidence: ConfidenceLevel
    unresolved_reasons: Tuple[str, ...]


# ---------------------------------------------------------------------------
# GestureResolutionResult — complete result from GestureApiResolver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GestureResolutionResult:
    """Resolution result for a single gesture-layer source entity.

    Fields
    ------
    source_entity_id
        ID of the classified ``SourceImpactEntity`` that was resolved.
    source_path
        Original source file path.
    impact_topics
        Typed impact topics derived from the source entity.
    sdk_api_topics
        SDK-validated API topics (Phase B.1 + B.2 validation).
    consumer_usage_edges
        XTS consumer usage edges found by Phase B.2 linker.
        Empty when XTS root is not available.
    xts_usage_modules
        XTS module names found via the XTS usage index (empty when index
        is not available).  Derived from ``consumer_usage_edges``.
    recommended_families
        Target family strings recommended for test selection.
    max_bucket
        Maximum allowed selector bucket for this result.  NEVER ``"must_run"``
        from this resolver — exact coverage equivalence is not proven here.
    unresolved_reasons
        Reasons for incomplete resolution at any layer.
    """

    source_entity_id: str
    source_path: str
    impact_topics: Tuple[ImpactTopic, ...]
    sdk_api_topics: Tuple[SdkApiTopic, ...]
    consumer_usage_edges: Tuple["ConsumerUsageEdge", ...]
    xts_usage_modules: Tuple[str, ...]
    recommended_families: Tuple[str, ...]
    max_bucket: Literal["must_run", "recommended", "possible", "unresolved"]
    unresolved_reasons: Tuple[str, ...]


# NOTE: ConsumerUsageEdge is defined in gesture_xts_linker.py.
# The type annotation "ConsumerUsageEdge" in GestureResolutionResult above
# uses a forward-reference string, resolved at runtime only if needed.
# Callers should import ConsumerUsageEdge from gesture_xts_linker directly.


# ---------------------------------------------------------------------------
# NativePeerResolutionResult — Phase B.3
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NativePeerResolutionResult:
    """Resolution result for a single native_peer-layer source entity.

    Fields
    ------
    source_entity_id
        ID of the classified ``SourceImpactEntity`` that was resolved.
    source_path
        Original source file path.
    impact_topics
        Typed impact topics derived from the source entity.
    sdk_api_topics
        SDK-validated API topics.
    consumer_usage_edges
        XTS consumer usage edges (empty when XTS root is not available).
    xts_usage_modules
        XTS module names derived from consumer_usage_edges.
    recommended_families
        Target family strings recommended for test selection.
    max_bucket
        Maximum allowed selector bucket.  NEVER ``"must_run"`` from this
        resolver — exact coverage equivalence is not proven here.
    unresolved_reasons
        Reasons for incomplete resolution at any layer.
    """

    source_entity_id: str
    source_path: str
    impact_topics: Tuple[ImpactTopic, ...]
    sdk_api_topics: Tuple[SdkApiTopic, ...]
    consumer_usage_edges: Tuple["ConsumerUsageEdge", ...]
    xts_usage_modules: Tuple[str, ...]
    recommended_families: Tuple[str, ...]
    max_bucket: Literal["must_run", "recommended", "possible", "unresolved"]
    unresolved_reasons: Tuple[str, ...]


# ---------------------------------------------------------------------------
# AniBridgeResolutionResult — Phase B.3
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AniBridgeResolutionResult:
    """Resolution result for a single ani_bridge-layer source entity.

    Fields
    ------
    source_entity_id
        ID of the classified ``SourceImpactEntity`` that was resolved.
    source_path
        Original source file path.
    impact_topics
        Typed impact topics derived from the source entity.
    sdk_api_topics
        SDK-validated API topics.  ANI symbol names must NOT appear as
        public_names — only SDK-visible names are allowed.
    consumer_usage_edges
        XTS consumer usage edges (empty when XTS root is not available).
    xts_usage_modules
        XTS module names derived from consumer_usage_edges.
    recommended_families
        Target family strings recommended for test selection.
    max_bucket
        Maximum allowed selector bucket.  NEVER ``"must_run"`` from this
        resolver — exact coverage equivalence is not proven here.
    unresolved_reasons
        Reasons for incomplete resolution at any layer.
    """

    source_entity_id: str
    source_path: str
    impact_topics: Tuple[ImpactTopic, ...]
    sdk_api_topics: Tuple[SdkApiTopic, ...]
    consumer_usage_edges: Tuple["ConsumerUsageEdge", ...]
    xts_usage_modules: Tuple[str, ...]
    recommended_families: Tuple[str, ...]
    max_bucket: Literal["must_run", "recommended", "possible", "unresolved"]
    unresolved_reasons: Tuple[str, ...]
