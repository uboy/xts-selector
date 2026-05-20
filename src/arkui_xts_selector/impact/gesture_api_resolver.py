"""GestureApiResolver — Universal Impact Resolution Phase B.1 + B.2.

Maps gesture-layer ``SourceImpactEntity`` records to ``ImpactTopic`` and
``SdkApiTopic`` records defined in ``config/api_topics.json``.  Phase B.2
adds SDK declaration validation (``GestureSdkValidator``) and XTS consumer
usage linking (``GestureXtsLinker``).

Scope:
- ``components_ng/gestures/**``
- ``interfaces/native/node/gesture_impl.cpp``

This module is additive and does NOT change production selector output.
Results are informational only.

Safety contract (non-negotiable):
- ``max_bucket`` is NEVER ``"must_run"`` from this resolver.
- No internal C++ names (PanRecognizer, GestureReferee, etc.) appear in
  ``SdkApiTopic.public_names``.
- No direct file-to-test hardcode.
- ``false_must_run`` remains 0.
- SDK env unavailable → graceful degradation, sdk_index_not_available.
- XTS env unavailable → graceful degradation, xts_index_not_available.

Import boundary: standard library + ``arkui_xts_selector.impact.*``.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any, Optional

from arkui_xts_selector.impact.models import (
    ConfidenceLevel,
    SourceImpactEntity,
)
from arkui_xts_selector.impact.topic_models import (
    ApiDeclarationRef,
    Domain,
    FanoutKind,
    GestureResolutionResult,
    ImpactTopic,
    SdkApiTopic,
)
from arkui_xts_selector.impact.gesture_sdk_validator import GestureSdkValidator
from arkui_xts_selector.impact.gesture_xts_linker import (
    ConsumerUsageEdge,
    GestureXtsLinker,
)
from arkui_xts_selector.impact.consumer_usage_linker import (
    ConsumerUsageLinker,
    compute_max_bucket as _compute_max_bucket_shared,
)


# ---------------------------------------------------------------------------
# Internal C++ names that must NEVER appear as public SDK API names
# ---------------------------------------------------------------------------

_INTERNAL_CPP_NAMES: frozenset[str] = frozenset({
    "PanRecognizer",
    "TapRecognizer",
    "LongPressRecognizer",
    "PinchRecognizer",
    "RotationRecognizer",
    "SwipeRecognizer",
    "GestureReferee",
    "GestureScope",
    "GestureRecognizer",
    "GestureGroup",        # internal C++ class (distinct from SDK GestureGroup)
    "SequenceRecognizer",
    "ExclusiveRecognizer",
    "ParallelRecognizer",
    "RecognizerGroup",
    "ClickRecognizer",
    "DragEventActuator",
    "GestureEventActuator",
    "GestureEventHub",
    "GestureInfo",
    "GestureSnapshot",
    "GestureDispatcher",
    "GestureTarget",
    "TouchEventActuator",
})

# ---------------------------------------------------------------------------
# Path-based routing table
# Entries are matched in order; first match wins.
# Each entry: (substring_hint, topic_ids, confidence, limitations, max_bucket)
# ---------------------------------------------------------------------------

_ROUTING: list[tuple[str, list[str], ConfidenceLevel, list[str], str]] = [
    # gesture_referee.cpp — shared infra, not all-component
    (
        "gesture_referee",
        ["gesture.core", "gesture.group", "gesture.custom_recognition"],
        "medium",
        ["gesture_referee_is_shared_infra", "not_specific_gesture_type"],
        "possible",
    ),
    # gesture_recognizer.cpp — generic base recognizer
    (
        "gesture_recognizer",
        ["gesture.core", "gesture.custom_recognition"],
        "medium",
        ["generic_recognizer_base", "not_specific_gesture_type"],
        "possible",
    ),
    # Specific recognizers — strong path evidence
    (
        "pan_recognizer",
        ["gesture.pan"],
        "strong",
        [],
        "possible",
    ),
    (
        "tap_recognizer",
        ["gesture.tap"],
        "strong",
        [],
        "possible",
    ),
    (
        "long_press_recognizer",
        ["gesture.long_press"],
        "strong",
        [],
        "possible",
    ),
    (
        "swipe_recognizer",
        ["gesture.swipe"],
        "strong",
        [],
        "possible",
    ),
    (
        "pinch_recognizer",
        ["gesture.pinch"],
        "strong",
        [],
        "possible",
    ),
    (
        "rotation_recognizer",
        ["gesture.rotation"],
        "strong",
        [],
        "possible",
    ),
    (
        "gesture_group",
        ["gesture.group"],
        "strong",
        [],
        "possible",
    ),
    # Native node gesture bridge
    (
        "gesture_impl",
        ["native.node.gesture"],
        "medium",
        ["native_bridge_only", "sdk_declaration_needs_verification"],
        "possible",
    ),
]

# Layers and roles this resolver handles
_HANDLED_LAYERS = frozenset({"gesture_framework", "gesture_referee", "native_node"})
_HANDLED_NATIVE_NODE_ROLE = "ndk_node_gesture_implementation"

# SDK names that are valid public API names — validated against this allowlist
# to ensure no internal C++ name leaks through
_KNOWN_PUBLIC_SDK_NAMES: frozenset[str] = frozenset({
    "PanGesture",
    "PanGestureOptions",
    "TapGesture",
    "TapGestureInterface",
    "LongPressGesture",
    "LongPressGestureInterface",
    "SwipeGesture",
    "PinchGesture",
    "PinchGestureOptions",
    "RotationGesture",
    "GestureGroup",       # SDK-visible name (distinct from internal C++ class)
    "Gesture",
    "onGestureRecognizerJudgeBegin",
    "onGestureJudgeBegin",
    "ArkUI_NativeGestureAPI_1",
    "OH_ArkUI_GestureRecognizer",
})

# Note: "GestureGroup" appears in both sets intentionally.
# The _INTERNAL_CPP_NAMES set governs C++ internal class names used inside
# AceEngine. "GestureGroup" as an SDK-visible component name in interface_sdk-js
# is a distinct identity and is allowed in public_names output.
# We resolve this by removing "GestureGroup" from the blocking set check
# only when it comes from api_topics.json sdk_api_queries (which are pre-vetted).


class GestureApiResolver:
    """Maps gesture-layer source entities to ImpactTopics and SdkApiTopics.

    Scope: ``components_ng/gestures/**`` and
    ``interfaces/native/node/gesture_impl.cpp`` only.

    Parameters
    ----------
    topics_config_path:
        Path to ``config/api_topics.json``.  When ``None``, the default
        config shipped with the package is used.
    sdk_api_index:
        Optional mapping of public SDK name -> declaration info.  Used to
        validate API declarations inline (Phase B.1 legacy path).
        When ``None``, SDK validation is skipped and ``"sdk_not_validated"``
        is added to unresolved reasons.  When an empty ``{}`` is provided,
        all names are treated as missing.
    sdk_api_root:
        Path to the ``interface_sdk-js/api`` directory.  When ``None``,
        defaults to the ``INTERFACE_SDK_JS_ROOT`` environment variable.
        Used by ``GestureSdkValidator`` (Phase B.2).  When unavailable,
        ``"sdk_index_not_available"`` is recorded.
    xts_root:
        Path to the XTS/ACTS arkui directory.  When ``None``, defaults to
        the ``XTS_ACTS_ROOT`` environment variable.  Used by
        ``GestureXtsLinker`` (Phase B.2).  When unavailable,
        ``"xts_index_not_available"`` is recorded.
    """

    def __init__(
        self,
        topics_config_path: Optional[str] = None,
        sdk_api_index: Optional[dict[str, Any]] = None,
        sdk_api_root: Optional[str] = None,
        xts_root: Optional[str] = None,
    ) -> None:
        if topics_config_path is None:
            pkg_root = pathlib.Path(__file__).parent.parent.parent.parent
            topics_config_path = str(pkg_root / "config" / "api_topics.json")
        self._topics_config_path = topics_config_path
        self._sdk_api_index = sdk_api_index  # None means skip legacy validation

        # Phase B.2: resolve env vars here so callers can pass explicit paths
        _sdk_root = sdk_api_root or os.environ.get("INTERFACE_SDK_JS_ROOT")
        _xts_root = xts_root or os.environ.get("XTS_ACTS_ROOT")
        self._sdk_validator = GestureSdkValidator(sdk_api_root=_sdk_root)
        self._xts_linker = GestureXtsLinker(xts_root=_xts_root)
        # Phase C: generalised consumer linker (replaces domain-specific linker)
        self._consumer_linker = ConsumerUsageLinker(xts_root=_xts_root)

        self._topics_by_id: dict[str, dict[str, Any]] = {}
        self._load_config()

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        with open(self._topics_config_path, encoding="utf-8") as fh:
            data = json.load(fh)
        for topic in data.get("topics", []):
            self._topics_by_id[topic["topic_id"]] = topic

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, entity: SourceImpactEntity) -> GestureResolutionResult:
        """Resolve a gesture-layer source entity to topics and SDK APIs.

        Only handles entities with layer in
        ``{"gesture_framework", "gesture_referee", "native_node"}``.
        For ``native_node`` entities, only the ``ndk_node_gesture_implementation``
        role is handled; other native_node roles receive an empty result.

        Parameters
        ----------
        entity:
            A classified ``SourceImpactEntity`` from ``SourceClassifier``.

        Returns
        -------
        GestureResolutionResult
            Populated result.  ``max_bucket`` is never ``"must_run"``.
        """
        if not self._is_in_scope(entity):
            return self._empty_result(entity, ["entity_not_in_gesture_scope"])

        # Route: find matching topic IDs from the path
        route = self._route_entity(entity)
        if route is None:
            return self._empty_result(entity, ["no_gesture_route_matched"])

        topic_ids, confidence, limitations, max_bucket = route

        # Build ImpactTopics
        impact_topics = tuple(
            self._make_impact_topic(tid, entity, confidence, limitations)
            for tid in topic_ids
        )

        # Resolve SDK API topics (Phase B.1 — inline index or skip)
        sdk_api_topics_b1, sdk_reasons = self._resolve_sdk_topics(
            topic_ids, entity, confidence
        )

        # Phase B.2: re-validate SDK topics against real SDK declaration files
        sdk_api_topics_b2 = self._run_sdk_validation(sdk_api_topics_b1)
        sdk_api_topics = sdk_api_topics_b2

        # Phase B.2: XTS consumer usage linking
        consumer_usage_edges, xts_modules, xts_reasons = self._run_xts_linking(
            sdk_api_topics
        )

        # Collect recommended families from SDK topics and linker edges
        recommended_families = self._collect_recommended_families(topic_ids)
        if consumer_usage_edges:
            recommended_families = self._augment_families_from_edges(
                recommended_families, consumer_usage_edges
            )

        # Determine max_bucket based on B.2 evidence
        max_bucket = self._compute_max_bucket(
            base_max_bucket=max_bucket,
            sdk_api_topics=sdk_api_topics,
            consumer_usage_edges=consumer_usage_edges,
        )

        # Collect all unresolved reasons
        unresolved: list[str] = list(sdk_reasons)
        # Phase B.2 SDK validator status: add sdk_index_not_available if no SDK root.
        # We keep sdk_not_validated from Phase B.1 (sdk_api_index=None path) as-is
        # for backward compatibility.  When the validator IS available, we drop
        # sdk_not_validated since real validation was performed.
        if not self._sdk_validator.is_available:
            if "sdk_index_not_available" not in unresolved:
                unresolved.append("sdk_index_not_available")
        else:
            # Real SDK validation was performed — drop the "skipped" marker
            unresolved = [r for r in unresolved if r != "sdk_not_validated"]
        unresolved.extend(xts_reasons)

        # Safety gate: max_bucket must never be must_run from this resolver
        assert max_bucket != "must_run", (
            "GestureApiResolver: max_bucket must_run is forbidden"
        )

        return GestureResolutionResult(
            source_entity_id=entity.id,
            source_path=entity.path,
            impact_topics=impact_topics,
            sdk_api_topics=sdk_api_topics,
            consumer_usage_edges=tuple(consumer_usage_edges),
            xts_usage_modules=xts_modules,
            recommended_families=recommended_families,
            max_bucket=max_bucket,  # type: ignore[arg-type]
            unresolved_reasons=tuple(dict.fromkeys(unresolved)),  # dedup, order-preserving
        )

    def resolve_batch(
        self, entities: list[SourceImpactEntity]
    ) -> list[GestureResolutionResult]:
        """Resolve a list of source entities."""
        return [self.resolve(e) for e in entities]

    # ------------------------------------------------------------------
    # Scope check
    # ------------------------------------------------------------------

    def _is_in_scope(self, entity: SourceImpactEntity) -> bool:
        """Return True if this entity is within gesture resolver scope."""
        if entity.layer in ("gesture_framework", "gesture_referee"):
            return True
        if entity.layer == "native_node":
            return entity.role == _HANDLED_NATIVE_NODE_ROLE
        return False

    # ------------------------------------------------------------------
    # Path routing
    # ------------------------------------------------------------------

    def _route_entity(
        self, entity: SourceImpactEntity
    ) -> Optional[tuple[list[str], ConfidenceLevel, list[str], str]]:
        """Match entity path against routing table.

        Returns (topic_ids, confidence, limitations, max_bucket) or None.
        Uses both the original path and entity source_topic_hints for matching.
        """
        # Normalise to lowercase for matching
        path_lower = entity.path.lower()
        # Also check topic hints provided by classifier for specific gesture types
        hints = " ".join(entity.source_topic_hints).lower()

        for hint, topic_ids, confidence, limitations, max_bucket in _ROUTING:
            if hint in path_lower or hint in hints:
                return topic_ids, confidence, list(limitations), max_bucket
        return None

    # ------------------------------------------------------------------
    # ImpactTopic construction
    # ------------------------------------------------------------------

    def _make_impact_topic(
        self,
        topic_id: str,
        entity: SourceImpactEntity,
        confidence: ConfidenceLevel,
        limitations: list[str],
    ) -> ImpactTopic:
        cfg = self._topics_by_id.get(topic_id, {})
        domain: Domain = cfg.get("domain", "gesture")  # type: ignore[assignment]
        name = topic_id.replace(".", " ").title()
        expected_sdk_kinds = tuple(
            q["kind"] for q in cfg.get("sdk_api_queries", [])
        )
        fanout_kind: FanoutKind = cfg.get("fanout_kind", "bounded_family")  # type: ignore[assignment]
        all_limitations = list(limitations)
        if "gesture_api_topics_not_resolved_to_sdk" in entity.limitations:
            all_limitations.append("source_classification_limitation_inherited")
        return ImpactTopic(
            topic_id=topic_id,
            domain=domain,
            name=name,
            source_entities=(entity.id,),
            expected_sdk_kinds=expected_sdk_kinds,
            fanout_kind=fanout_kind,
            confidence=confidence,
            limitations=tuple(all_limitations),
        )

    # ------------------------------------------------------------------
    # SdkApiTopic construction
    # ------------------------------------------------------------------

    def _resolve_sdk_topics(
        self,
        topic_ids: list[str],
        entity: SourceImpactEntity,
        source_confidence: ConfidenceLevel,
    ) -> tuple[tuple[SdkApiTopic, ...], list[str]]:
        """Build SdkApiTopic records for the given topic IDs.

        Applies SDK index validation when ``sdk_api_index`` is not None.
        """
        sdk_topics: list[SdkApiTopic] = []
        unresolved: list[str] = []

        for topic_id in topic_ids:
            cfg = self._topics_by_id.get(topic_id)
            if cfg is None:
                unresolved.append(f"topic_config_missing:{topic_id}")
                continue

            queries: list[dict[str, Any]] = cfg.get("sdk_api_queries", [])
            if not queries:
                unresolved.append(f"no_sdk_queries_for_topic:{topic_id}")
                continue

            declarations: list[ApiDeclarationRef] = []
            public_names: list[str] = []
            topic_unresolved: list[str] = []

            for q in queries:
                public_name: str = q["public_name"]
                kind: str = q["kind"]
                sdk_path_hint: Optional[str] = q.get("sdk_path_hint")

                # Safety: internal C++ names must not appear as public_names.
                # Note: "GestureGroup" is in _INTERNAL_CPP_NAMES as an internal
                # C++ class, but the SDK also exposes a component with the same
                # name. We allow it here because it comes from api_topics.json
                # (pre-vetted SDK query list). The _INTERNAL_CPP_NAMES check is
                # for names that should NEVER appear (PanRecognizer, etc.).
                truly_internal = _INTERNAL_CPP_NAMES - {"GestureGroup"}
                if public_name in truly_internal:
                    # Should never happen if api_topics.json is correct
                    topic_unresolved.append(
                        f"internal_cpp_name_in_sdk_query:{public_name}"
                    )
                    continue

                if self._sdk_api_index is None:
                    # Skip validation: index not provided
                    declarations.append(
                        ApiDeclarationRef(
                            public_name=public_name,
                            kind=kind,
                            sdk_path_hint=sdk_path_hint,
                        )
                    )
                    public_names.append(public_name)
                    topic_unresolved.append("sdk_not_validated")
                elif public_name in self._sdk_api_index:
                    # SDK index available and name found
                    info = self._sdk_api_index[public_name]
                    declarations.append(
                        ApiDeclarationRef(
                            public_name=public_name,
                            kind=kind,
                            sdk_path_hint=info.get("path") if isinstance(info, dict) else None,
                        )
                    )
                    public_names.append(public_name)
                else:
                    # SDK index available but name not found
                    topic_unresolved.append(
                        f"sdk_declaration_missing:{public_name}"
                    )

            # Deduplicate unresolved reasons
            seen: set[str] = set()
            deduped: list[str] = []
            for r in topic_unresolved:
                if r not in seen:
                    seen.add(r)
                    deduped.append(r)

            # Determine api_confidence
            if not public_names:
                api_confidence: ConfidenceLevel = "none"
            elif self._sdk_api_index is None:
                api_confidence = "medium"
            else:
                api_confidence = "strong" if not deduped else "medium"

            sdk_topics.append(
                SdkApiTopic(
                    topic_id=topic_id,
                    public_names=tuple(public_names),
                    declarations=tuple(declarations),
                    expected_usage_kinds=tuple(cfg.get("expected_usage_kinds", [])),
                    source_topic_ids=(topic_id,),
                    api_confidence=api_confidence,
                    unresolved_reasons=tuple(deduped),
                )
            )
            unresolved.extend(r for r in deduped if r not in unresolved)

        return tuple(sdk_topics), unresolved

    # ------------------------------------------------------------------
    # Recommended families
    # ------------------------------------------------------------------

    def _collect_recommended_families(self, topic_ids: list[str]) -> tuple[str, ...]:
        """Collect recommended family strings from topic configs."""
        seen: set[str] = set()
        families: list[str] = []
        for topic_id in topic_ids:
            cfg = self._topics_by_id.get(topic_id, {})
            for fam in cfg.get("recommended_families", []):
                if fam not in seen:
                    seen.add(fam)
                    families.append(fam)
        return tuple(families)

    # ------------------------------------------------------------------
    # Phase B.2: SDK validation helper
    # ------------------------------------------------------------------

    def _run_sdk_validation(
        self, sdk_topics: tuple[SdkApiTopic, ...]
    ) -> tuple[SdkApiTopic, ...]:
        """Re-validate SdkApiTopics against real SDK declaration files."""
        if not sdk_topics:
            return sdk_topics
        validated = self._sdk_validator.validate_sdk_topics(list(sdk_topics))
        return tuple(validated)

    # ------------------------------------------------------------------
    # Phase B.2: XTS linking helper
    # ------------------------------------------------------------------

    def _run_xts_linking(
        self, sdk_topics: tuple[SdkApiTopic, ...]
    ) -> tuple[list[ConsumerUsageEdge], tuple[str, ...], list[str]]:
        """Find XTS consumer usage edges for SDK topics.

        Returns (edges, xts_modules_tuple, xts_reasons_list).
        """
        xts_reasons: list[str] = []
        if not self._xts_linker.is_available:
            xts_reasons.append("xts_index_not_available")
            return [], (), xts_reasons

        edges = self._xts_linker.find_usage_edges_for_topics(list(sdk_topics))

        # Derive unique XTS module names from edges
        seen_modules: set[str] = set()
        modules: list[str] = []
        for edge in edges:
            proj = edge.consumer_project
            if proj and proj not in seen_modules:
                seen_modules.add(proj)
                modules.append(proj)

        return edges, tuple(modules), xts_reasons

    # ------------------------------------------------------------------
    # Phase B.2: max_bucket computation
    # ------------------------------------------------------------------

    def _compute_max_bucket(
        self,
        base_max_bucket: str,
        sdk_api_topics: tuple[SdkApiTopic, ...],
        consumer_usage_edges: list[ConsumerUsageEdge],
    ) -> str:
        """Compute max_bucket based on evidence from B.2.

        Rules (per design doc Section 8):
        - Source topic + SDK declaration + XTS usage (non-import_only) → recommended
        - Source topic + SDK declaration (no XTS usage) → possible
        - No SDK topics → stays at base
        - NEVER → must_run

        ``base_max_bucket`` comes from the routing table (always "possible").
        """
        # Check if we have SDK-validated topics with public names
        has_sdk_topics = any(
            len(t.public_names) > 0 for t in sdk_api_topics
        )

        # Check for non-import-only XTS usage edges
        has_strong_xts_usage = any(
            edge.usage_kind != "import_only" and edge.confidence in ("strong", "medium")
            for edge in consumer_usage_edges
        )

        if has_sdk_topics and has_strong_xts_usage:
            result = "recommended"
        elif has_sdk_topics:
            # SDK topics present but no XTS usage → stays at possible
            result = base_max_bucket
        else:
            result = base_max_bucket

        # Safety gate: never must_run
        assert result != "must_run", (
            "GestureApiResolver._compute_max_bucket: must_run is forbidden"
        )
        return result

    # ------------------------------------------------------------------
    # Phase B.2: augment families from edges
    # ------------------------------------------------------------------

    def _augment_families_from_edges(
        self,
        existing_families: tuple[str, ...],
        edges: list[ConsumerUsageEdge],
    ) -> tuple[str, ...]:
        """Add consumer_project values from strong XTS edges as recommended families."""
        seen: set[str] = set(existing_families)
        result = list(existing_families)
        for edge in edges:
            if edge.usage_kind != "import_only" and edge.consumer_project:
                proj = edge.consumer_project
                if proj not in seen:
                    seen.add(proj)
                    result.append(proj)
        return tuple(result)

    # ------------------------------------------------------------------
    # Empty result helper
    # ------------------------------------------------------------------

    def _empty_result(
        self, entity: SourceImpactEntity, reasons: list[str]
    ) -> GestureResolutionResult:
        return GestureResolutionResult(
            source_entity_id=entity.id,
            source_path=entity.path,
            impact_topics=(),
            sdk_api_topics=(),
            consumer_usage_edges=(),
            xts_usage_modules=(),
            recommended_families=(),
            max_bucket="unresolved",
            unresolved_reasons=tuple(reasons),
        )
