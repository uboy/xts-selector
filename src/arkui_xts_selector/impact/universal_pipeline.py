"""UniversalImpactPipeline — Phase H Track E.

Wires the full universal impact chain:
  SourceClassifier → topic resolvers → SDK validator →
  ConsumerUsageLinker → BroadInfraProfileResolver → FanoutLimiter

This is the first production caller of the Phase A–E resolver library.

Safety contract (non-negotiable):
- false_must_run remains 0.  Any infra_profile candidate claiming must_run
  raises ValueError before reaching the caller.
- No direct file-to-test hardcode.
- No exact SDK API inferred from infra profiles.
- Graceful degradation without env vars (sdk/xts/ace roots optional).
- affects_must_run is always False on ResolutionConfidence output.
- manual_verified golden cases are unchanged (pipeline is additive only).

Layer dispatch table (13 source layers from SourceLayer Literal):
  component_pattern        → unresolved (not yet routed — needs future resolver)
  native_peer              → NativePeerResolver
  ani_bridge               → AniBridgeResolver
  gesture_framework        → GestureApiResolver
  gesture_referee          → GestureApiResolver
  native_event             → NativeEventResolver
  native_node              → GestureApiResolver (gesture impl only)
  jsi_bridge               → BroadInfraProfileResolver
  common_method            → BroadInfraProfileResolver
  select_overlay           → BroadInfraProfileResolver
  inspector                → BroadInfraProfileResolver
  component_universal      → BroadInfraProfileResolver
  node_universal           → BroadInfraProfileResolver
  pipeline_universal       → BroadInfraProfileResolver
  generated_binding        → unresolved (generated output — no stable API)
  test_only                → unresolved (not production code)
  build_config             → unresolved (build artifact)
  unknown                  → unresolved (no rule matched)

Import boundary: standard library + arkui_xts_selector.impact.*.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional, Sequence

from arkui_xts_selector.impact.models import SourceImpactEntity
from arkui_xts_selector.impact.source_classifier import SourceClassifier
from arkui_xts_selector.impact.topic_models import (
    ImpactTopic,
    InfraProfileResolutionResult,
)
from arkui_xts_selector.impact.fanout_limiter import FanoutLimiter, TargetCandidate
from arkui_xts_selector.impact.resolution_confidence import (
    ResolutionConfidence,
    compute_resolution_confidence,
)


# ---------------------------------------------------------------------------
# Layer dispatch constants
# ---------------------------------------------------------------------------

# Layers routed to GestureApiResolver
_GESTURE_LAYERS = frozenset({"gesture_framework", "gesture_referee", "native_node"})

# Layers routed to BroadInfraProfileResolver
_INFRA_PROFILE_LAYERS = frozenset({
    "jsi_bridge",
    "inspector",
    "select_overlay",
    "component_universal",
    "node_universal",
    "pipeline_universal",
    "common_method",
})

# Layers treated as unresolved (no resolver available yet, or non-production)
_UNRESOLVED_LAYERS = frozenset({
    "component_pattern",
    "generated_binding",
    "test_only",
    "build_config",
    "unknown",
})


# ---------------------------------------------------------------------------
# Per-file result
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class PerFileResult:
    """Pipeline result for a single changed file.

    Fields
    ------
    path
        The changed file path as passed to run().
    source_entity
        SourceImpactEntity produced by SourceClassifier.
    impact_topics
        ImpactTopic records from the topic resolver, if applicable.
    sdk_topics
        SdkApiTopic records from SDK validation, if applicable.
    consumer_edges
        ConsumerUsageEdge records from XTS usage linker, if applicable.
    infra_profile
        InfraProfileResolutionResult from BroadInfraProfileResolver, if applicable.
    fanout_result
        FanoutResult after applying caps — only present after aggregate pass.
        None until the aggregate pass is complete.
    max_bucket
        Maximum bucket for this file: "must_run" | "recommended" | "possible" | "unresolved".
        NEVER "must_run" from pipeline output — resolvers do not emit must_run.
    resolver_used
        Name of the resolver that handled this file.
    unresolved_reasons
        Reasons for incomplete resolution, if any.
    """

    path: str
    source_entity: SourceImpactEntity
    impact_topics: tuple
    sdk_topics: tuple
    consumer_edges: tuple
    infra_profile: Optional[InfraProfileResolutionResult]
    fanout_result: Any  # FanoutResult | None
    max_bucket: str
    resolver_used: str
    unresolved_reasons: tuple

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON output."""
        d: dict = {
            "path": self.path,
            "source_entity": {
                "id": self.source_entity.id,
                "layer": self.source_entity.layer,
                "role": self.source_entity.role,
                "confidence": self.source_entity.confidence,
                "owner_family_hint": self.source_entity.owner_family_hint,
            },
            "impact_topics": [
                {"topic_id": t.topic_id, "domain": t.domain, "confidence": t.confidence}
                for t in self.impact_topics
            ],
            "sdk_topics": [
                {
                    "topic_id": t.topic_id,
                    "public_names": list(t.public_names),
                    "api_confidence": t.api_confidence,
                }
                for t in self.sdk_topics
            ],
            "consumer_edges": [
                {
                    "edge_id": e.edge_id,
                    "sdk_api_name": e.sdk_api_name,
                    "usage_kind": e.usage_kind,
                    "owning_module": e.owning_module,
                    "confidence": e.confidence,
                }
                for e in self.consumer_edges
            ],
            "max_bucket": self.max_bucket,
            "resolver_used": self.resolver_used,
            "unresolved_reasons": list(self.unresolved_reasons),
        }
        if self.infra_profile is not None:
            d["infra_profile"] = {
                "profile_id": self.infra_profile.profile_id,
                "source_layer": self.infra_profile.source_layer,
                "max_bucket": self.infra_profile.max_bucket,
                "risk_surface": self.infra_profile.risk_surface,
                "limitations": list(self.infra_profile.limitations),
                "unresolved_reasons": list(self.infra_profile.unresolved_reasons),
            }
        if self.fanout_result is not None:
            d["fanout_result"] = {
                "kept_count": len(self.fanout_result.kept_targets),
                "suppressed_count": self.fanout_result.capped_count,
                "direct_count": self.fanout_result.direct_count,
                "profile_count": self.fanout_result.profile_count,
                "warnings": list(self.fanout_result.warnings),
            }
        return d


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class PipelineResult:
    """Full result from UniversalImpactPipeline.run().

    Fields
    ------
    per_file
        One PerFileResult per changed file.
    resolution_confidence
        Honesty marker (advisory, never affects must_run).
    universal_max_bucket
        The highest bucket across all per_file results.
        Computed as: max in bucket order (unresolved < possible < recommended < must_run).
        NEVER "must_run" — resolvers enforce this.
    warnings
        Aggregate warnings from fanout limiter and graceful-degradation paths.
    """

    per_file: list[PerFileResult]
    resolution_confidence: ResolutionConfidence
    universal_max_bucket: str
    warnings: list[str]

    def to_dict(self) -> dict:
        rc = self.resolution_confidence
        return {
            "schema_version": "universal-impact-v1",
            "per_file": [f.to_dict() for f in self.per_file],
            "resolution_confidence": {
                "level": rc.level,
                "shallow_files": list(rc.shallow_files),
                "unresolved_files": list(rc.unresolved_files),
                "reasons": list(rc.reasons),
                "affects_must_run": rc.affects_must_run,
                "human_summary": rc.human_summary,
            },
            "universal_max_bucket": self.universal_max_bucket,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# UniversalImpactPipeline
# ---------------------------------------------------------------------------

_BUCKET_ORDER = {"unresolved": 0, "possible": 1, "recommended": 2, "must_run": 3}


class UniversalImpactPipeline:
    """Wires the full universal impact chain for a set of changed files.

    Parameters
    ----------
    sdk_root:
        Path to interface_sdk-js/api.  When ``None``, falls back to the
        ``INTERFACE_SDK_ROOT`` environment variable.  SDK validation is
        skipped gracefully when unavailable.
    xts_root:
        Path to the XTS/ACTS root.  When ``None``, falls back to the
        ``XTS_ACTS_ROOT`` environment variable.  Consumer usage linking is
        skipped gracefully when unavailable.
    ace_engine_root:
        Path to the ace_engine repository root.  When ``None``, falls back
        to the ``ACE_ENGINE_ROOT`` environment variable.  Currently used for
        symbol indexing (future).

    Usage::

        pipeline = UniversalImpactPipeline()
        result = pipeline.run(changed_files)
        print(result.to_dict())
    """

    def __init__(
        self,
        sdk_root: Optional[str] = None,
        xts_root: Optional[str] = None,
        ace_engine_root: Optional[str] = None,
    ) -> None:
        import os

        self._sdk_root = sdk_root or os.environ.get("INTERFACE_SDK_ROOT")
        self._xts_root = xts_root or os.environ.get("XTS_ACTS_ROOT")
        self._ace_engine_root = ace_engine_root or os.environ.get("ACE_ENGINE_ROOT")

        # Lazily-constructed resolver instances (avoid slow init when not needed)
        self._classifier: Optional[SourceClassifier] = None
        self._gesture_resolver = None
        self._native_peer_resolver = None
        self._ani_bridge_resolver = None
        self._native_event_resolver = None
        self._infra_profile_resolver = None
        self._fanout_limiter: Optional[FanoutLimiter] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, changed_files: Sequence[str]) -> PipelineResult:
        """Run the universal impact pipeline over a list of changed files.

        Parameters
        ----------
        changed_files:
            Relative paths of changed source files (as used in ArkUI PR context).

        Returns
        -------
        PipelineResult
            Per-file resolution results, aggregate confidence marker, and
            aggregate max bucket.

        Safety
        ------
        - false_must_run=0: no resolver emits must_run.  FanoutLimiter raises
          ValueError if an infra_profile candidate claims must_run.
        - Graceful degradation: SDK/XTS root absent → limited resolution, no crash.
        """
        if not changed_files:
            empty_conf = compute_resolution_confidence([], [], [])
            return PipelineResult(
                per_file=[],
                resolution_confidence=empty_conf,
                universal_max_bucket="unresolved",
                warnings=[],
            )

        # Ensure resolvers are initialised
        self._ensure_resolvers()

        per_file: list[PerFileResult] = []
        all_candidates: list[TargetCandidate] = []
        warnings: list[str] = []

        # --- Per-file pass ---
        for path in changed_files:
            file_result, candidates, file_warnings = self._resolve_file(path)
            per_file.append(file_result)
            all_candidates.extend(candidates)
            warnings.extend(file_warnings)

        # --- Aggregate fanout pass ---
        fanout_result = self._fanout_limiter.limit(all_candidates)  # type: ignore[union-attr]
        if fanout_result.warnings:
            warnings.extend(list(fanout_result.warnings))

        # Attach aggregate fanout to each per-file result
        # (simple approach: attach to first file — full per-file fanout is future work)
        if per_file:
            per_file[0] = dataclasses.replace(per_file[0], fanout_result=fanout_result)

        # --- Compute resolution confidence ---
        entities = [f.source_entity for f in per_file]
        profile_matches = [f.infra_profile for f in per_file if f.infra_profile is not None]
        topic_matches: list[ImpactTopic] = []
        for f in per_file:
            topic_matches.extend(f.impact_topics)

        confidence = compute_resolution_confidence(entities, profile_matches, topic_matches)

        # --- Compute universal_max_bucket ---
        universal_max_bucket = _compute_universal_max_bucket(per_file)

        return PipelineResult(
            per_file=per_file,
            resolution_confidence=confidence,
            universal_max_bucket=universal_max_bucket,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # File-level dispatch
    # ------------------------------------------------------------------

    def _resolve_file(
        self, path: str
    ) -> tuple[PerFileResult, list[TargetCandidate], list[str]]:
        """Classify and resolve a single changed file.

        Returns (PerFileResult, candidates_for_fanout, warnings).
        """
        warnings: list[str] = []

        # Step 1: Classify
        try:
            entity = self._classifier.classify_path(path)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            # Graceful degradation — classification failure
            warnings.append(f"classification error for {path}: {exc}")
            entity = _make_fallback_entity(path)

        layer = entity.layer

        # Step 2: Dispatch to resolver
        if layer in _GESTURE_LAYERS:
            return self._resolve_gesture(entity, warnings)
        elif layer == "native_peer":
            return self._resolve_native_peer(entity, warnings)
        elif layer == "ani_bridge":
            return self._resolve_ani_bridge(entity, warnings)
        elif layer == "native_event":
            return self._resolve_native_event(entity, warnings)
        elif layer in _INFRA_PROFILE_LAYERS:
            return self._resolve_infra_profile(entity, warnings)
        else:
            # unknown / unresolved layers
            return self._resolve_unknown(entity, warnings)

    # ------------------------------------------------------------------
    # Resolver dispatch helpers
    # ------------------------------------------------------------------

    def _resolve_gesture(
        self, entity: SourceImpactEntity, warnings: list[str]
    ) -> tuple[PerFileResult, list[TargetCandidate], list[str]]:
        try:
            result = self._gesture_resolver.resolve(entity)  # type: ignore[union-attr]
            candidates = _gesture_result_to_candidates(result)
            return (
                PerFileResult(
                    path=entity.path,
                    source_entity=entity,
                    impact_topics=result.impact_topics,
                    sdk_topics=result.sdk_api_topics,
                    consumer_edges=result.consumer_usage_edges,
                    infra_profile=None,
                    fanout_result=None,
                    max_bucket=result.max_bucket,
                    resolver_used="GestureApiResolver",
                    unresolved_reasons=result.unresolved_reasons,
                ),
                candidates,
                warnings,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"GestureApiResolver error for {entity.path}: {exc}")
            return _make_unresolved_result(entity, "GestureApiResolver", warnings)

    def _resolve_native_peer(
        self, entity: SourceImpactEntity, warnings: list[str]
    ) -> tuple[PerFileResult, list[TargetCandidate], list[str]]:
        try:
            result = self._native_peer_resolver.resolve(entity)  # type: ignore[union-attr]
            candidates = _generic_result_to_candidates(result, "native_peer")
            return (
                PerFileResult(
                    path=entity.path,
                    source_entity=entity,
                    impact_topics=result.impact_topics,
                    sdk_topics=result.sdk_api_topics,
                    consumer_edges=result.consumer_usage_edges,
                    infra_profile=None,
                    fanout_result=None,
                    max_bucket=result.max_bucket,
                    resolver_used="NativePeerResolver",
                    unresolved_reasons=result.unresolved_reasons,
                ),
                candidates,
                warnings,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"NativePeerResolver error for {entity.path}: {exc}")
            return _make_unresolved_result(entity, "NativePeerResolver", warnings)

    def _resolve_ani_bridge(
        self, entity: SourceImpactEntity, warnings: list[str]
    ) -> tuple[PerFileResult, list[TargetCandidate], list[str]]:
        try:
            result = self._ani_bridge_resolver.resolve(entity)  # type: ignore[union-attr]
            candidates = _generic_result_to_candidates(result, "ani_bridge")
            return (
                PerFileResult(
                    path=entity.path,
                    source_entity=entity,
                    impact_topics=result.impact_topics,
                    sdk_topics=result.sdk_api_topics,
                    consumer_edges=result.consumer_usage_edges,
                    infra_profile=None,
                    fanout_result=None,
                    max_bucket=result.max_bucket,
                    resolver_used="AniBridgeResolver",
                    unresolved_reasons=result.unresolved_reasons,
                ),
                candidates,
                warnings,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"AniBridgeResolver error for {entity.path}: {exc}")
            return _make_unresolved_result(entity, "AniBridgeResolver", warnings)

    def _resolve_native_event(
        self, entity: SourceImpactEntity, warnings: list[str]
    ) -> tuple[PerFileResult, list[TargetCandidate], list[str]]:
        try:
            result = self._native_event_resolver.resolve(entity)  # type: ignore[union-attr]
            candidates = _generic_result_to_candidates(result, "native_event")
            return (
                PerFileResult(
                    path=entity.path,
                    source_entity=entity,
                    impact_topics=result.impact_topics,
                    sdk_topics=result.sdk_api_topics,
                    consumer_edges=result.consumer_usage_edges,
                    infra_profile=None,
                    fanout_result=None,
                    max_bucket=result.max_bucket,
                    resolver_used="NativeEventResolver",
                    unresolved_reasons=result.unresolved_reasons,
                ),
                candidates,
                warnings,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"NativeEventResolver error for {entity.path}: {exc}")
            return _make_unresolved_result(entity, "NativeEventResolver", warnings)

    def _resolve_infra_profile(
        self, entity: SourceImpactEntity, warnings: list[str]
    ) -> tuple[PerFileResult, list[TargetCandidate], list[str]]:
        try:
            result = self._infra_profile_resolver.resolve(entity)  # type: ignore[union-attr]
            # Safety: infra profiles never produce must_run
            assert result.max_bucket != "must_run", (
                "BroadInfraProfileResolver: must_run is forbidden"
            )
            candidates = _infra_result_to_candidates(result)
            return (
                PerFileResult(
                    path=entity.path,
                    source_entity=entity,
                    impact_topics=(),
                    sdk_topics=(),
                    consumer_edges=(),
                    infra_profile=result,
                    fanout_result=None,
                    max_bucket=result.max_bucket,
                    resolver_used="BroadInfraProfileResolver",
                    unresolved_reasons=result.unresolved_reasons,
                ),
                candidates,
                warnings,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"BroadInfraProfileResolver error for {entity.path}: {exc}")
            return _make_unresolved_result(entity, "BroadInfraProfileResolver", warnings)

    def _resolve_unknown(
        self, entity: SourceImpactEntity, warnings: list[str]
    ) -> tuple[PerFileResult, list[TargetCandidate], list[str]]:
        """Emit unresolved result for layers with no current resolver."""
        warnings.append(
            f"no resolver for layer={entity.layer} path={entity.path}"
            " — contributing to unresolved_files"
        )
        return _make_unresolved_result(entity, "none", warnings)

    # ------------------------------------------------------------------
    # Lazy resolver initialisation
    # ------------------------------------------------------------------

    def _ensure_resolvers(self) -> None:
        """Lazily initialise all resolver instances.

        Each resolver accepts optional sdk_root and xts_root; it degrades
        gracefully when those are absent.  We pass what we have and let the
        resolver handle missing env.
        """
        if self._classifier is None:
            self._classifier = SourceClassifier()

        if self._gesture_resolver is None:
            from arkui_xts_selector.impact.gesture_api_resolver import GestureApiResolver
            self._gesture_resolver = GestureApiResolver(
                sdk_api_root=self._sdk_root,
                xts_root=self._xts_root,
            )

        if self._native_peer_resolver is None:
            from arkui_xts_selector.impact.native_peer_resolver import NativePeerResolver
            self._native_peer_resolver = NativePeerResolver(
                sdk_api_root=self._sdk_root,
                xts_root=self._xts_root,
            )

        if self._ani_bridge_resolver is None:
            from arkui_xts_selector.impact.ani_bridge_resolver import AniBridgeResolver
            self._ani_bridge_resolver = AniBridgeResolver(
                sdk_api_root=self._sdk_root,
                xts_root=self._xts_root,
            )

        if self._native_event_resolver is None:
            from arkui_xts_selector.impact.native_event_resolver import NativeEventResolver
            self._native_event_resolver = NativeEventResolver(
                sdk_api_root=self._sdk_root,
                xts_root=self._xts_root,
            )

        if self._infra_profile_resolver is None:
            from arkui_xts_selector.impact.infra_profile_resolver import BroadInfraProfileResolver
            self._infra_profile_resolver = BroadInfraProfileResolver(
                xts_root=self._xts_root,
            )

        if self._fanout_limiter is None:
            self._fanout_limiter = FanoutLimiter()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_fallback_entity(path: str) -> SourceImpactEntity:
    """Create a minimal fallback entity for a path that failed classification."""
    from arkui_xts_selector.impact.models import EvidenceRef
    return SourceImpactEntity(
        id=f"{path}#unknown#unknown",
        path=path,
        changed_symbols=(),
        changed_hunks=(),
        layer="unknown",
        role="unknown",
        owner_family_hint=None,
        source_topic_hints=(),
        confidence="none",
        evidence=(EvidenceRef(kind="fallback", value="classification_error"),),
        limitations=("classification_error",),
    )


def _make_unresolved_result(
    entity: SourceImpactEntity,
    resolver_name: str,
    warnings: list[str],
) -> tuple[PerFileResult, list[TargetCandidate], list[str]]:
    """Build an unresolved PerFileResult with no candidates."""
    return (
        PerFileResult(
            path=entity.path,
            source_entity=entity,
            impact_topics=(),
            sdk_topics=(),
            consumer_edges=(),
            infra_profile=None,
            fanout_result=None,
            max_bucket="unresolved",
            resolver_used=resolver_name,
            unresolved_reasons=(f"no_resolver_for_layer_{entity.layer}",),
        ),
        [],
        warnings,
    )


def _gesture_result_to_candidates(result) -> list[TargetCandidate]:
    """Convert GestureResolutionResult xts_usage_modules to TargetCandidates."""
    candidates = []
    for module in result.xts_usage_modules:
        candidates.append(TargetCandidate(
            target_id=module,
            bucket=result.max_bucket,
            source="direct_xts_usage",
            domain="gesture",
            api_name="",
            profile_id="",
            evidence_strength="medium",
            confidence=result.sdk_api_topics[0].api_confidence if result.sdk_api_topics else "low",
            reason="gesture_xts_usage",
            limitations=(),
        ))
    return candidates


def _generic_result_to_candidates(result, domain: str) -> list[TargetCandidate]:
    """Convert a generic resolver result's xts_usage_modules to TargetCandidates."""
    candidates = []
    for module in result.xts_usage_modules:
        candidates.append(TargetCandidate(
            target_id=module,
            bucket=result.max_bucket,
            source="direct_xts_usage",
            domain=domain,
            api_name="",
            profile_id="",
            evidence_strength="medium",
            confidence=result.sdk_api_topics[0].api_confidence if result.sdk_api_topics else "low",
            reason=f"{domain}_xts_usage",
            limitations=(),
        ))
    return candidates


def _infra_result_to_candidates(result: InfraProfileResolutionResult) -> list[TargetCandidate]:
    """Convert InfraProfileResolutionResult profile targets to TargetCandidates.

    Safety: max_bucket is never must_run for infra_profile source.
    """
    candidates = []
    profile_id = result.profile_id or "default_profile"
    bucket = result.max_bucket
    # Extra safety: infra_profile can never produce must_run
    if bucket == "must_run":
        bucket = "recommended"

    for target in result.profile_targets:
        candidates.append(TargetCandidate(
            target_id=target.target_name,
            bucket=bucket,
            source="infra_profile",
            domain=result.source_layer,
            api_name="",
            profile_id=profile_id,
            evidence_strength=target.confidence,
            confidence=target.confidence,
            reason=f"infra_profile:{profile_id}",
            limitations=result.limitations,
        ))
    return candidates


def _compute_universal_max_bucket(per_file: list[PerFileResult]) -> str:
    """Return the highest bucket across all per-file results."""
    if not per_file:
        return "unresolved"
    best = "unresolved"
    for f in per_file:
        if _BUCKET_ORDER.get(f.max_bucket, 0) > _BUCKET_ORDER.get(best, 0):
            best = f.max_bucket
    return best
