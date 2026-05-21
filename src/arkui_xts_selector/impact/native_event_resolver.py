"""NativeEventResolver — Universal Impact Resolution Phase B.4.

Maps native_event and native_node (event role) ``SourceImpactEntity`` records
to ``ImpactTopic`` and ``SdkApiTopic`` records defined in
``config/api_topics.json``.

Scope: ``interfaces/native/event/**`` and ``interfaces/native/node/**``
       event/gesture files only (layers ``"native_event"`` and
       ``"native_node"``).

This module is additive and does NOT change production selector output.
Results are informational only.

Safety contract (non-negotiable):
- ``max_bucket`` is NEVER ``"must_run"`` from this resolver.
- No internal C++ / NDK event impl names (UIInputEventImpl, ArkUIEventConverter,
  EventConverterImpl, etc.) appear in ``SdkApiTopic.public_names``.
- No direct file-to-test hardcode.
- ``false_must_run`` remains 0.
- SDK env unavailable → graceful degradation, sdk_index_not_available.
- XTS env unavailable → graceful degradation, xts_index_not_available.
- Does NOT change GestureApiResolver behavior.

Import boundary: standard library + ``arkui_xts_selector.impact.*``.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Any, Optional

from arkui_xts_selector.impact.models import (
    ConfidenceLevel,
    SourceImpactEntity,
)
from arkui_xts_selector.impact.topic_models import (
    ApiDeclarationRef,
    Domain,
    FanoutKind,
    ImpactTopic,
    NativeEventResolutionResult,
    SdkApiTopic,
)
from arkui_xts_selector.impact.gesture_sdk_validator import GestureSdkValidator
from arkui_xts_selector.impact.gesture_xts_linker import (
    ConsumerUsageEdge,
    GestureXtsLinker,
    _scan_file_for_names,
    _MAX_FILES,
    _MAX_SCAN_SECONDS,
    _make_edge_id,
    _derive_project,
)
from arkui_xts_selector.impact.consumer_usage_linker import (
    ConsumerUsageLinker,
    compute_max_bucket,
)


# ---------------------------------------------------------------------------
# Internal NDK/C++ names that must NEVER appear as public SDK API names
# ---------------------------------------------------------------------------

_INTERNAL_NATIVE_NAMES: frozenset[str] = frozenset({
    "UIInputEventImpl",
    "ArkUIEventConverter",
    "EventConverterImpl",
    "NativeEventImpl",
    "NativeNodeEventImpl",
    "GestureEventImpl",
    "GestureImplInner",
    "NodeGestureImpl",
    "ArkUIGestureImpl",
    "NativeGestureImpl",
})

# ---------------------------------------------------------------------------
# Layers handled by this resolver
# ---------------------------------------------------------------------------

_HANDLED_LAYERS: frozenset[str] = frozenset({"native_event", "native_node"})

# ---------------------------------------------------------------------------
# Path routing table
# Each entry: (path_token, topic_ids, confidence, limitations, max_bucket)
# More specific matches listed before broader ones.
# ---------------------------------------------------------------------------

_ROUTING: list[tuple[str, list[str], ConfidenceLevel, list[str], str]] = [
    # ui_input_event files → ui_input + touch topics
    (
        "ui_input_event",
        ["native.event.ui_input", "native.event.touch"],
        "strong",
        [],
        "possible",
    ),
    # event_converter files → shared event infra converter topic
    (
        "event_converter",
        ["native.event.converter"],
        "medium",
        ["event_converter_is_shared_infra"],
        "possible",
    ),
    # gesture_impl files → gesture bridge topic
    # Note: preserves existing native.node.gesture from GestureApiResolver;
    # this resolver adds the bridge topic only.
    (
        "gesture_impl",
        ["native.event.gesture_bridge"],
        "medium",
        [],
        "possible",
    ),
]

# XTS directory hints for native NDK tests
_XTS_NATIVE_EVENT_DIR_HINTS = (
    "native",
    "ndk",
    "c_arkui",
    "c_arkui_test",
    "event",
    "gesture",
    "ActsAceEngineNDK",
    "ActsAceEngineNative",
)


class NativeEventResolver:
    """Maps native_event and native_node (event role) source entities to
    ImpactTopics and SdkApiTopics.

    Scope: ``interfaces/native/event/**`` and ``interfaces/native/node/**``
           event files only (``layer="native_event"`` or ``layer="native_node"``).

    Parameters
    ----------
    topics_config_path:
        Path to ``config/api_topics.json``.  When ``None``, the default
        config shipped with the package is used.
    sdk_api_root:
        Path to the ``interface_sdk-js/api`` directory.  When ``None``,
        defaults to the ``INTERFACE_SDK_JS_ROOT`` environment variable.
        When unavailable, ``"sdk_index_not_available"`` is recorded.
    xts_root:
        Path to the XTS/ACTS arkui directory.  When ``None``, defaults to
        the ``XTS_ACTS_ROOT`` environment variable.  When unavailable,
        ``"xts_index_not_available"`` is recorded.
    """

    def __init__(
        self,
        topics_config_path: Optional[str] = None,
        sdk_api_root: Optional[str] = None,
        xts_root: Optional[str] = None,
    ) -> None:
        if topics_config_path is None:
            pkg_root = pathlib.Path(__file__).parent.parent.parent.parent
            topics_config_path = str(pkg_root / "config" / "api_topics.json")
        self._topics_config_path = topics_config_path

        _sdk_root = sdk_api_root or os.environ.get("INTERFACE_SDK_JS_ROOT")
        _xts_root = xts_root or os.environ.get("XTS_ACTS_ROOT")
        self._sdk_validator = GestureSdkValidator(sdk_api_root=_sdk_root)
        self._xts_linker = _NativeEventXtsLinker(xts_root=_xts_root)
        # Phase C: generalised consumer linker (replaces _NativeEventXtsLinker)
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

    def resolve(self, entity: SourceImpactEntity) -> NativeEventResolutionResult:
        """Resolve a native_event- or native_node-layer source entity to topics
        and SDK APIs.

        Only handles entities with ``layer`` in ``{"native_event", "native_node"}``.
        Out-of-scope entities receive an empty/unresolved result.

        Parameters
        ----------
        entity:
            A classified ``SourceImpactEntity`` from ``SourceClassifier``.

        Returns
        -------
        NativeEventResolutionResult
            Populated result.  ``max_bucket`` is never ``"must_run"``.
        """
        if entity.layer not in _HANDLED_LAYERS:
            return self._empty_result(entity, ["entity_not_in_native_event_scope"])

        route = self._route_entity(entity)
        if route is None:
            return self._empty_result(entity, ["unsupported_native_event_topic"])

        topic_ids, confidence, limitations, max_bucket = route

        # Build ImpactTopics
        impact_topics = tuple(
            self._make_impact_topic(tid, entity, confidence, limitations)
            for tid in topic_ids
        )

        # Build SdkApiTopics from config
        sdk_api_topics_b1, sdk_reasons = self._resolve_sdk_topics(
            topic_ids, entity, confidence
        )

        # Re-validate against real SDK declaration files
        sdk_api_topics = tuple(
            self._sdk_validator.validate_sdk_topic(t) for t in sdk_api_topics_b1
        )

        # XTS consumer usage linking
        consumer_usage_edges, xts_modules, xts_reasons = self._run_xts_linking(
            sdk_api_topics
        )

        # Compute max_bucket from evidence
        max_bucket = compute_max_bucket(
            impact_topics,
            sdk_api_topics,
            tuple(consumer_usage_edges),
            filter_by_confidence=True,
        )

        # Collect recommended families
        recommended_families = self._collect_recommended_families(topic_ids)
        if consumer_usage_edges:
            recommended_families = self._augment_families_from_edges(
                recommended_families, consumer_usage_edges
            )

        # Collect all unresolved reasons
        unresolved: list[str] = list(sdk_reasons)
        if not self._sdk_validator.is_available:
            if "sdk_index_not_available" not in unresolved:
                unresolved.append("sdk_index_not_available")
        else:
            unresolved = [r for r in unresolved if r != "sdk_not_validated"]
        unresolved.extend(xts_reasons)

        # Safety gate: max_bucket must never be must_run from this resolver
        assert max_bucket != "must_run", (
            "NativeEventResolver: max_bucket must_run is forbidden"
        )

        return NativeEventResolutionResult(
            source_entity_id=entity.id,
            source_path=entity.path,
            impact_topics=impact_topics,
            sdk_api_topics=sdk_api_topics,
            consumer_usage_edges=tuple(consumer_usage_edges),
            xts_usage_modules=xts_modules,
            recommended_families=recommended_families,
            max_bucket=max_bucket,  # type: ignore[arg-type]
            unresolved_reasons=tuple(dict.fromkeys(unresolved)),
        )

    def resolve_batch(
        self, entities: list[SourceImpactEntity]
    ) -> list[NativeEventResolutionResult]:
        """Resolve a list of source entities."""
        return [self.resolve(e) for e in entities]

    # ------------------------------------------------------------------
    # Path routing
    # ------------------------------------------------------------------

    def _route_entity(
        self, entity: SourceImpactEntity
    ) -> Optional[tuple[list[str], ConfidenceLevel, list[str], str]]:
        """Match entity against routing table.

        Checks ``owner_family_hint``, ``source_topic_hints``, and path tokens.
        Returns (topic_ids, confidence, limitations, max_bucket) or None.
        """
        hint = (entity.owner_family_hint or "").lower()
        hints_str = " ".join(entity.source_topic_hints).lower()
        path_lower = entity.path.lower()

        # Combine all tokens for matching
        combined = f"{hint} {hints_str} {path_lower}"

        for token, topic_ids, confidence, limitations, max_bucket in _ROUTING:
            if token in combined:
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
        domain: Domain = cfg.get("domain", "native")  # type: ignore[assignment]
        name = topic_id.replace(".", " ").title()
        expected_sdk_kinds = tuple(
            q["kind"] for q in cfg.get("sdk_api_queries", [])
        )
        fanout_kind: FanoutKind = cfg.get("fanout_kind", "bounded_family")  # type: ignore[assignment]
        all_limitations = list(limitations)
        if "owner_family_hint_is_lookup_evidence_only" in entity.limitations:
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
        """Build SdkApiTopic records for the given topic IDs."""
        sdk_topics: list[SdkApiTopic] = []
        unresolved: list[str] = []
        seen_topic_ids: set[str] = set()

        for topic_id in topic_ids:
            # Deduplicate topic IDs (routing table may emit same ID twice)
            if topic_id in seen_topic_ids:
                continue
            seen_topic_ids.add(topic_id)

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

                # Safety: internal names must not appear as public_names
                if public_name in _INTERNAL_NATIVE_NAMES:
                    topic_unresolved.append(
                        f"internal_native_name_in_sdk_query:{public_name}"
                    )
                    continue

                declarations.append(
                    ApiDeclarationRef(
                        public_name=public_name,
                        kind=kind,
                        sdk_path_hint=sdk_path_hint,
                    )
                )
                public_names.append(public_name)
                topic_unresolved.append("sdk_not_validated")

            # Deduplicate unresolved reasons
            seen: set[str] = set()
            deduped: list[str] = []
            for r in topic_unresolved:
                if r not in seen:
                    seen.add(r)
                    deduped.append(r)

            # native_event = indirect evidence → medium confidence at best
            api_confidence: ConfidenceLevel = "medium" if public_names else "none"

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
    # XTS linking helper
    # ------------------------------------------------------------------

    def _run_xts_linking(
        self, sdk_topics: tuple[SdkApiTopic, ...]
    ) -> tuple[list[ConsumerUsageEdge], tuple[str, ...], list[str]]:
        xts_reasons: list[str] = []
        if not self._xts_linker.is_available:
            xts_reasons.append("xts_index_not_available")
            return [], (), xts_reasons

        edges = self._xts_linker.find_usage_edges_for_topics(list(sdk_topics))

        seen_modules: set[str] = set()
        modules: list[str] = []
        for edge in edges:
            proj = edge.consumer_project
            if proj and proj not in seen_modules:
                seen_modules.add(proj)
                modules.append(proj)

        return edges, tuple(modules), xts_reasons

    # ------------------------------------------------------------------
    # Recommended families
    # ------------------------------------------------------------------

    def _collect_recommended_families(self, topic_ids: list[str]) -> tuple[str, ...]:
        seen: set[str] = set()
        families: list[str] = []
        for topic_id in topic_ids:
            cfg = self._topics_by_id.get(topic_id, {})
            for fam in cfg.get("recommended_families", []):
                if fam not in seen:
                    seen.add(fam)
                    families.append(fam)
        return tuple(families)

    def _augment_families_from_edges(
        self,
        existing_families: tuple[str, ...],
        edges: list[ConsumerUsageEdge],
    ) -> tuple[str, ...]:
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
    ) -> NativeEventResolutionResult:
        return NativeEventResolutionResult(
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


# ---------------------------------------------------------------------------
# Internal XTS linker for native event domain
# ---------------------------------------------------------------------------


class _NativeEventXtsLinker(GestureXtsLinker):
    """XTS linker scoped to native/NDK event test directories.

    Reuses ``GestureXtsLinker`` search logic but with native-event-specific
    directory hints.  Searches for .ets, .c, and .cpp files.
    """

    def find_usage_edges(self, sdk_topic: SdkApiTopic) -> list[ConsumerUsageEdge]:
        """Search XTS source files for native event API usage."""
        self._ensure_available()
        if not self.is_available or not sdk_topic.public_names:
            return []

        assert self._xts_root is not None

        xts_root = self._xts_root
        public_names = frozenset(sdk_topic.public_names)
        edges: list[ConsumerUsageEdge] = []
        seen_edges: set[str] = set()
        file_count = 0
        start_time = time.monotonic()

        # Collect relevant directories using native NDK hints
        candidate_dirs: list[pathlib.Path] = []
        seen_dirs: set[pathlib.Path] = set()

        for hint in _XTS_NATIVE_EVENT_DIR_HINTS:
            for d in xts_root.rglob(hint):
                if d.is_dir() and d not in seen_dirs:
                    seen_dirs.add(d)
                    candidate_dirs.append(d)

        if not candidate_dirs:
            candidate_dirs = [xts_root]

        # Search both .ets (ArkTS tests) and .c/.cpp (NDK C tests)
        _EXTENSIONS = ("*.ets", "*.c", "*.cpp")

        for candidate_dir in candidate_dirs:
            if file_count >= _MAX_FILES or time.monotonic() - start_time > _MAX_SCAN_SECONDS:
                break
            for ext in _EXTENSIONS:
                for src_file in sorted(candidate_dir.rglob(ext)):
                    if file_count >= _MAX_FILES:
                        break
                    if time.monotonic() - start_time > _MAX_SCAN_SECONDS:
                        break

                    file_count += 1
                    hits = _scan_file_for_names(src_file, xts_root, public_names)
                    if not hits:
                        continue

                    try:
                        rel_path = str(src_file.relative_to(xts_root))
                    except ValueError:
                        rel_path = str(src_file)

                    consumer_project = _derive_project(rel_path)

                    for public_name, usage_kind, confidence, evidence in hits:
                        assert not (usage_kind == "import_only" and confidence == "strong")
                        limitations: tuple[str, ...] = ()
                        if usage_kind == "import_only":
                            limitations = ("import_only_cannot_reach_must_run",)

                        edge_id = _make_edge_id(sdk_topic.topic_id, rel_path, public_name)
                        if edge_id in seen_edges:
                            continue
                        seen_edges.add(edge_id)

                        edges.append(ConsumerUsageEdge(
                            edge_id=edge_id,
                            sdk_api_topic_id=sdk_topic.topic_id,
                            api_public_name=public_name,
                            consumer_file=rel_path,
                            consumer_project=consumer_project,
                            usage_kind=usage_kind,
                            confidence=confidence,
                            evidence=evidence,
                            limitations=limitations,
                        ))

        return edges
