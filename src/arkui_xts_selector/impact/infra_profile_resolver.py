"""BroadInfraProfileResolver — Universal Impact Resolution Phase D.

Maps broad infrastructure source entities (JSI bridge, inspector,
select overlay) to InfraProfileResolutionResult using profiles defined
in config/infra_profiles.json.

Safety contract (non-negotiable):
- max_bucket is NEVER "must_run" under any circumstances.
- affected_api_entities is ALWAYS empty — exact SDK API must not be inferred
  from infra profiles.
- Target discovery is bounded at MAX_TARGETS=20.
- Without XTS_ACTS_ROOT: graceful degradation, empty targets,
  unresolved_reasons includes "xts_index_not_available".
- false_must_run remains 0.

Import boundary: standard library + arkui_xts_selector.impact.*.
"""

from __future__ import annotations

import json
import pathlib
import time
from typing import Optional

from arkui_xts_selector.impact.models import SourceImpactEntity
from arkui_xts_selector.impact.topic_models import (
    InfraProfileResolutionResult,
    ProfileTargetCandidate,
)


class BroadInfraProfileResolver:
    """Resolves broad infrastructure source entities to infra profile results.

    Loads ``config/infra_profiles.json`` at init.  Matches entities by
    source layer or path hints.  Emits bounded candidate targets from XTS
    index when XTS_ACTS_ROOT is available.

    Parameters
    ----------
    xts_root:
        Path to the XTS/ACTS root directory.  When ``None``, falls back to
        the ``XTS_ACTS_ROOT`` environment variable.
    config_path:
        Path to ``config/infra_profiles.json``.  When ``None``, uses the
        default path relative to this module.
    """

    MAX_TARGETS = 20
    TIMEOUT_S = 20

    def __init__(
        self,
        xts_root: Optional[str] = None,
        config_path: Optional[str] = None,
    ) -> None:
        import os

        _xts_root = xts_root or os.environ.get("XTS_ACTS_ROOT")
        self._profiles = self._load_profiles(config_path)

        # Import lazily to avoid circular imports
        from arkui_xts_selector.impact.consumer_usage_linker import ConsumerUsageLinker
        self._linker = ConsumerUsageLinker(xts_root=_xts_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, entity: SourceImpactEntity) -> InfraProfileResolutionResult:
        """Resolve a source entity to an infra profile result.

        Parameters
        ----------
        entity:
            A classified ``SourceImpactEntity`` from ``SourceClassifier``.

        Returns
        -------
        InfraProfileResolutionResult
            Populated result.  ``max_bucket`` is never ``"must_run"``.
            ``affected_api_entities`` is always empty.
        """
        profile = self._match_profile(entity)

        if profile is None:
            return InfraProfileResolutionResult(
                profile_id=None,
                source_layer=entity.layer,
                source_path=entity.path,
                risk_surface="",
                candidate_query_terms=(),
                max_bucket="unresolved",
                confidence="none",
                unresolved_reasons=("unsupported_infra_layer",),
            )

        targets, unresolved = self._discover_targets(profile)
        # max_bucket is "recommended" when targets found, else "possible"
        # Safety: NEVER "must_run"
        bucket = "recommended" if targets else "possible"
        assert bucket != "must_run", (
            "BroadInfraProfileResolver: must_run is forbidden"
        )

        return InfraProfileResolutionResult(
            profile_id=profile["profile_id"],
            source_layer=entity.layer,
            source_path=entity.path,
            risk_surface=profile["risk_surface"],
            candidate_query_terms=tuple(profile["candidate_query_terms"]),
            max_bucket=bucket,
            confidence="medium",
            affected_api_entities=(),     # intentionally always empty
            profile_targets=tuple(targets),
            limitations=tuple(profile.get("limitations", [])),
            unresolved_reasons=tuple(unresolved),
        )

    def resolve_batch(
        self, entities: list[SourceImpactEntity]
    ) -> list[InfraProfileResolutionResult]:
        """Resolve a list of source entities."""
        return [self.resolve(e) for e in entities]

    def available(self) -> bool:
        """Resolver is always available; target discovery requires XTS env."""
        return True

    # ------------------------------------------------------------------
    # Profile matching
    # ------------------------------------------------------------------

    def _match_profile(self, entity: SourceImpactEntity) -> Optional[dict]:
        """Match entity against profiles by source_layer or path_hints.

        Source layer match takes priority; path hint match is a fallback
        for cases where classification differs from expected layer.
        """
        src_lower = entity.path.lower()

        for profile in self._profiles:
            # Primary: exact layer match
            if entity.layer in profile["source_layers"]:
                return profile

        # Secondary: path hint substring match (case-insensitive)
        for profile in self._profiles:
            hints = profile.get("path_hints", [])
            if any(hint.lower() in src_lower for hint in hints):
                return profile

        return None

    # ------------------------------------------------------------------
    # Target discovery
    # ------------------------------------------------------------------

    def _discover_targets(
        self, profile: dict
    ) -> tuple[list[ProfileTargetCandidate], list[str]]:
        """Discover candidate targets by searching XTS files.

        Returns (targets, unresolved_reasons).
        Empty targets + ["xts_index_not_available"] when XTS unavailable.
        """
        if not self._linker.available:
            reason = self._linker.unresolved_reason() or "xts_index_not_available"
            return [], [reason]

        query_terms = profile.get("candidate_query_terms", [])
        if not query_terms:
            return [], []

        targets: list[ProfileTargetCandidate] = []
        seen_files: set[str] = set()
        deadline = time.monotonic() + self.TIMEOUT_S

        for xts_file in self._linker._iter_xts_files():
            if time.monotonic() > deadline:
                break
            if len(targets) >= self.MAX_TARGETS:
                break

            try:
                content = xts_file.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue

            # Check each query term against file content
            for term in query_terms:
                if term.lower() in content.lower():
                    try:
                        rel_path = str(xts_file.relative_to(self._linker._xts_root))
                    except (ValueError, AttributeError):
                        rel_path = str(xts_file)

                    # De-duplicate by (file, term)
                    dedup_key = f"{rel_path}:{term}"
                    if dedup_key in seen_files:
                        continue
                    seen_files.add(dedup_key)

                    targets.append(
                        ProfileTargetCandidate(
                            target_name=xts_file.stem,
                            source_file=rel_path,
                            evidence_kind="query_term_match",
                            confidence="weak",
                            query_term=term,
                        )
                    )

                    if len(targets) >= self.MAX_TARGETS:
                        break

        return targets, []

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_profiles(self, config_path: Optional[str] = None) -> list[dict]:
        if config_path is None:
            here = pathlib.Path(__file__).parent
            config_path = str(
                here.parent.parent.parent / "config" / "infra_profiles.json"
            )
        with open(config_path, encoding="utf-8") as fh:
            return json.load(fh)["profiles"]
