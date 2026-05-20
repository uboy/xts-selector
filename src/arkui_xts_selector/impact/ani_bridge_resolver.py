"""AniBridgeResolver — Universal Impact Resolution Phase B.3.

Maps ani_bridge ``SourceImpactEntity`` records to ``ImpactTopic`` and
``SdkApiTopic`` records defined in ``config/api_topics.json``.

Scope: ``interfaces/native/ani/**`` only.

This module is additive and does NOT change production selector output.
Results are informational only.

Safety contract (non-negotiable):
- ``max_bucket`` is NEVER ``"must_run"`` from this resolver.
- ANI symbol names (CanvasAniModifier, XComponentAniModifier, etc.) must
  NEVER appear in ``SdkApiTopic.public_names`` — only SDK-visible names are
  allowed (Canvas, CanvasRenderingContext2D, XComponent, XComponentController).
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
    AniBridgeResolutionResult,
    Domain,
    FanoutKind,
    ImpactTopic,
    SdkApiTopic,
)
from arkui_xts_selector.impact.gesture_sdk_validator import GestureSdkValidator
from arkui_xts_selector.impact.native_peer_resolver import _NativePeerXtsLinker
from arkui_xts_selector.impact.gesture_xts_linker import ConsumerUsageEdge


# ---------------------------------------------------------------------------
# ANI internal names that must NEVER appear as public SDK API names
# ---------------------------------------------------------------------------

_ANI_INTERNAL_NAMES: frozenset[str] = frozenset({
    "CanvasAniModifier",
    "DrawingAniModifier",
    "XComponentAniModifier",
    "CanvasAni",
    "DrawingAni",
    "XComponentAni",
    "AniModifier",
    "AniBinding",
    "AniCanvas",
    "AniXComponent",
    "CanvasAniImpl",
    "XComponentAniImpl",
})

# ---------------------------------------------------------------------------
# Path routing table for ani_bridge layer
# Each entry: (path_token, topic_ids, confidence, limitations, max_bucket)
# ---------------------------------------------------------------------------

_ROUTING: list[tuple[str, list[str], ConfidenceLevel, list[str], str]] = [
    # Canvas ANI
    (
        "canvas",
        ["ani.canvas"],
        "medium",
        [],
        "possible",
    ),
    # XComponent ANI — more specific before generic
    (
        "x_component",
        ["ani.xcomponent"],
        "medium",
        [],
        "possible",
    ),
    (
        "xcomponent",
        ["ani.xcomponent"],
        "medium",
        [],
        "possible",
    ),
]

# Layer handled by this resolver
_HANDLED_LAYER = "ani_bridge"


class AniBridgeResolver:
    """Maps ani_bridge source entities to ImpactTopics and SdkApiTopics.

    Scope: ``interfaces/native/ani/**`` only (``layer="ani_bridge"``).

    ANI class/function names (e.g. ``CanvasAniModifier``) are treated as
    bridge evidence only and must never appear as public SDK API names.

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
        self._xts_linker = _NativePeerXtsLinker(xts_root=_xts_root)

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

    def resolve(self, entity: SourceImpactEntity) -> AniBridgeResolutionResult:
        """Resolve an ani_bridge-layer source entity to topics and SDK APIs.

        Only handles entities with ``layer="ani_bridge"``.
        Out-of-scope entities receive an empty/unresolved result.

        Parameters
        ----------
        entity:
            A classified ``SourceImpactEntity`` from ``SourceClassifier``.

        Returns
        -------
        AniBridgeResolutionResult
            Populated result.  ``max_bucket`` is never ``"must_run"``.
        """
        if entity.layer != _HANDLED_LAYER:
            return self._empty_result(entity, ["entity_not_in_ani_bridge_scope"])

        route = self._route_entity(entity)
        if route is None:
            return self._empty_result(entity, ["unsupported_ani_topic"])

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
        max_bucket = self._compute_max_bucket(
            base_max_bucket=max_bucket,
            sdk_api_topics=sdk_api_topics,
            consumer_usage_edges=consumer_usage_edges,
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
            "AniBridgeResolver: max_bucket must_run is forbidden"
        )

        return AniBridgeResolutionResult(
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
    ) -> list[AniBridgeResolutionResult]:
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
        if "ani_symbol_is_bridge_evidence_only" in entity.limitations:
            all_limitations.append("ani_symbol_is_bridge_evidence_only_inherited")
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

        ANI symbol names must NOT appear as public_names.
        Only SDK-visible names from api_topics.json queries are used.
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

                # Safety: ANI internal names must not appear as public_names
                if public_name in _ANI_INTERNAL_NAMES:
                    topic_unresolved.append(
                        f"ani_internal_name_in_sdk_query:{public_name}"
                    )
                    continue

                # No inline index — emit as not-yet-validated
                declarations.append(
                    ApiDeclarationRef(
                        public_name=public_name,
                        kind=kind,
                        sdk_path_hint=sdk_path_hint,
                    )
                )
                public_names.append(public_name)
                topic_unresolved.append("sdk_not_validated")

            # Deduplicate
            seen: set[str] = set()
            deduped: list[str] = []
            for r in topic_unresolved:
                if r not in seen:
                    seen.add(r)
                    deduped.append(r)

            # ANI bridge = indirect evidence → medium confidence at best
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
    # max_bucket computation
    # ------------------------------------------------------------------

    def _compute_max_bucket(
        self,
        base_max_bucket: str,
        sdk_api_topics: tuple[SdkApiTopic, ...],
        consumer_usage_edges: list[ConsumerUsageEdge],
    ) -> str:
        has_sdk_topics = any(len(t.public_names) > 0 for t in sdk_api_topics)
        has_strong_xts_usage = any(
            edge.usage_kind != "import_only" and edge.confidence in ("strong", "medium")
            for edge in consumer_usage_edges
        )

        if has_sdk_topics and has_strong_xts_usage:
            result = "recommended"
        else:
            result = base_max_bucket

        # Safety gate: never must_run
        assert result != "must_run", (
            "AniBridgeResolver._compute_max_bucket: must_run is forbidden"
        )
        return result

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
    ) -> AniBridgeResolutionResult:
        return AniBridgeResolutionResult(
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
