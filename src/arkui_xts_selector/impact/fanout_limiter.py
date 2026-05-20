"""FanoutLimiter — Universal Impact Resolution Phase E.

Applies per-API, per-profile, per-domain, and global caps to ranked
TargetCandidate lists.  Never promotes bucket.  Infra profiles cannot
produce must_run.

Safety contract (non-negotiable):
- infra_profile source NEVER produces must_run.
- Bucket is NEVER raised here — caps only demote or suppress.
- false_must_run remains 0.
- Caps load from config/fanout_policies.json with graceful fallback to
  hardcoded defaults when the config file is absent.

Import boundary: standard library only.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetCandidate:
    """A single test target candidate with bucket, source, and evidence metadata.

    Fields
    ------
    target_id
        Stable identifier for the test target (module or file name).
    bucket
        Selection bucket: "must_run" | "recommended" | "possible" | "unresolved".
        must_run is never emitted from infra_profile source.
    source
        Evidence source that produced this candidate:
        "coverage_equivalence" | "direct_xts_usage" | "sdk_plus_usage" |
        "infra_profile" | "fallback".
    domain
        Impact domain (e.g. "gesture", "native_peer", "jsi_bridge").
    api_name
        Public SDK API name associated with this candidate (may be empty).
    profile_id
        Infra profile identifier when source == "infra_profile" (may be empty).
    evidence_strength
        "strong" | "medium" | "weak".
    confidence
        Resolver confidence for this candidate.
    reason
        Human-readable reason for inclusion.
    limitations
        Known limitations from the resolving evidence.
    """

    target_id: str
    bucket: str           # "must_run" | "recommended" | "possible" | "unresolved"
    source: str           # "coverage_equivalence" | "direct_xts_usage" | ...
    domain: str
    api_name: str = ""
    profile_id: str = ""
    evidence_strength: str = "weak"   # "strong" | "medium" | "weak"
    confidence: str = "low"
    reason: str = ""
    limitations: tuple[str, ...] = ()


@dataclass
class FanoutGroup:
    """A group of candidates sharing the same bucket and source."""

    bucket: str
    source: str
    candidates: list[TargetCandidate] = field(default_factory=list)


@dataclass(frozen=True)
class FanoutResult:
    """Result of applying fanout caps to a list of TargetCandidates.

    Fields
    ------
    kept_targets
        Candidates that survived all caps, in ranked order.
    suppressed_targets
        Candidates removed by cap policy.
    capped_count
        Number of suppressed candidates (== len(suppressed_targets)).
    direct_count
        Count of kept targets from direct evidence sources
        (coverage_equivalence, direct_xts_usage, sdk_plus_usage).
    profile_count
        Count of kept targets from infra_profile source.
    warnings
        Non-fatal policy warnings (e.g. "suppressed N targets due to cap policy").
    """

    kept_targets: tuple[TargetCandidate, ...]
    suppressed_targets: tuple[TargetCandidate, ...]
    capped_count: int
    direct_count: int
    profile_count: int
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------------
# FanoutLimiter
# ---------------------------------------------------------------------------


class FanoutLimiter:
    """Applies fanout caps and ranking to a list of TargetCandidates.

    Loads policy from config/fanout_policies.json.  Falls back to hardcoded
    defaults when the file is absent or unreadable — graceful degradation.

    Usage::

        limiter = FanoutLimiter()
        result = limiter.limit(candidates)

    The ``limit()`` method:
    - Raises ValueError if any infra_profile candidate claims must_run.
    - Deduplicates by target_id (keeps strongest evidence).
    - Ranks within each bucket by source type and evidence_strength.
    - Applies per-API, per-profile, per-domain, and global caps.
    - Never promotes any candidate's bucket.
    """

    # Hardcoded defaults — used when config file is absent
    _DEFAULT_POLICY: dict = {
        "direct_before_profile": True,
        "rank_order": [
            "coverage_equivalence",
            "direct_xts_usage",
            "sdk_plus_usage",
            "infra_profile",
            "fallback",
        ],
        "caps": {
            "max_recommended_direct_per_api": 5,
            "max_recommended_profile_per_profile": 5,
            "max_possible_per_domain": 5,
            "max_total_recommended": 20,
            "max_total_possible": 20,
        },
        "deduplicate_by_module": True,
        "preserve_one_per_direct_api": True,
        "suppress_broad_must_run": True,
        "explain_suppressed": True,
    }

    def __init__(self, policy_path: str | None = None) -> None:
        self._policy = self._load_policy(policy_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def limit(self, candidates: list[TargetCandidate]) -> FanoutResult:
        """Apply fanout caps and ranking.  Never promotes bucket.

        Parameters
        ----------
        candidates:
            Unordered list of TargetCandidates from all resolvers.

        Returns
        -------
        FanoutResult
            Kept and suppressed candidates with cap metrics.

        Raises
        ------
        ValueError
            If any infra_profile candidate has bucket == "must_run".
        """
        if not candidates:
            return FanoutResult((), (), 0, 0, 0, ())

        # Safety: assert no must_run from profile source
        for c in candidates:
            if c.source == "infra_profile" and c.bucket == "must_run":
                raise ValueError(
                    f"FanoutLimiter: infra_profile cannot produce must_run: {c.target_id}"
                )

        # 1. Deduplicate by target_id (keep highest evidence_strength)
        deduped = self._deduplicate(candidates)

        # 2. Sort within each bucket by evidence rank
        sorted_candidates = self._rank(deduped)

        # 3. Apply caps
        kept, suppressed = self._apply_caps(sorted_candidates)

        direct_count = sum(
            1 for t in kept
            if t.source in ("coverage_equivalence", "direct_xts_usage", "sdk_plus_usage")
        )
        profile_count = sum(1 for t in kept if t.source == "infra_profile")

        warnings: list[str] = []
        if suppressed:
            warnings.append(
                f"suppressed {len(suppressed)} targets due to cap policy"
            )

        return FanoutResult(
            kept_targets=tuple(kept),
            suppressed_targets=tuple(suppressed),
            capped_count=len(suppressed),
            direct_count=direct_count,
            profile_count=profile_count,
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _deduplicate(self, candidates: list[TargetCandidate]) -> list[TargetCandidate]:
        """Keep only the strongest candidate per target_id."""
        strength_order = {"strong": 0, "medium": 1, "weak": 2}
        seen: dict[str, TargetCandidate] = {}
        for c in candidates:
            key = c.target_id
            if key not in seen:
                seen[key] = c
            else:
                existing_rank = strength_order.get(seen[key].evidence_strength, 2)
                new_rank = strength_order.get(c.evidence_strength, 2)
                if new_rank < existing_rank:
                    seen[key] = c
        return list(seen.values())

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def _rank(self, candidates: list[TargetCandidate]) -> list[TargetCandidate]:
        """Sort candidates: bucket → source → evidence_strength → target_id."""
        rank_order: list[str] = self._policy.get("rank_order", [
            "coverage_equivalence",
            "direct_xts_usage",
            "sdk_plus_usage",
            "infra_profile",
            "fallback",
        ])
        bucket_order = {"must_run": 0, "recommended": 1, "possible": 2, "unresolved": 3}
        strength_order = {"strong": 0, "medium": 1, "weak": 2}

        def sort_key(c: TargetCandidate) -> tuple:
            bucket_rank = bucket_order.get(c.bucket, 99)
            source_rank = rank_order.index(c.source) if c.source in rank_order else 99
            strength_rank = strength_order.get(c.evidence_strength, 2)
            return (bucket_rank, source_rank, strength_rank, c.target_id)

        return sorted(candidates, key=sort_key)

    # ------------------------------------------------------------------
    # Cap application
    # ------------------------------------------------------------------

    def _apply_caps(
        self, candidates: list[TargetCandidate]
    ) -> tuple[list[TargetCandidate], list[TargetCandidate]]:
        """Apply per-API, per-profile, per-domain, and global caps."""
        caps: dict = self._policy.get("caps", {})
        max_rec_direct = caps.get("max_recommended_direct_per_api", 5)
        max_rec_profile = caps.get("max_recommended_profile_per_profile", 5)
        max_possible_domain = caps.get("max_possible_per_domain", 5)
        max_total_rec = caps.get("max_total_recommended", 20)
        max_total_possible = caps.get("max_total_possible", 20)

        kept: list[TargetCandidate] = []
        suppressed: list[TargetCandidate] = []
        per_api_rec: dict[str, int] = {}
        per_profile_rec: dict[str, int] = {}
        per_domain_possible: dict[str, int] = {}
        total_rec = 0
        total_possible = 0

        for c in candidates:
            if c.bucket == "must_run":
                # Genuine must_run is never capped — only direct evidence can produce it
                kept.append(c)
                continue

            if c.bucket == "recommended":
                if c.source == "infra_profile":
                    pid = c.profile_id or "default"
                    cnt = per_profile_rec.get(pid, 0)
                    if cnt >= max_rec_profile or total_rec >= max_total_rec:
                        suppressed.append(c)
                        continue
                    per_profile_rec[pid] = cnt + 1
                else:
                    api = c.api_name or "default"
                    cnt = per_api_rec.get(api, 0)
                    if cnt >= max_rec_direct or total_rec >= max_total_rec:
                        suppressed.append(c)
                        continue
                    per_api_rec[api] = cnt + 1
                total_rec += 1
                kept.append(c)

            elif c.bucket == "possible":
                domain = c.domain or "default"
                cnt = per_domain_possible.get(domain, 0)
                if cnt >= max_possible_domain or total_possible >= max_total_possible:
                    suppressed.append(c)
                    continue
                per_domain_possible[domain] = cnt + 1
                total_possible += 1
                kept.append(c)

            else:
                # unresolved or unknown bucket — pass through uncapped
                kept.append(c)

        return kept, suppressed

    # ------------------------------------------------------------------
    # Policy loading
    # ------------------------------------------------------------------

    def _load_policy(self, policy_path: str | None = None) -> dict:
        """Load fanout policy from config/fanout_policies.json.

        Falls back to _DEFAULT_POLICY when the file is absent or unreadable.
        """
        if policy_path is None:
            here = pathlib.Path(__file__).parent
            cfg = here.parent.parent.parent / "config" / "fanout_policies.json"
        else:
            cfg = pathlib.Path(policy_path)

        if cfg.exists():
            try:
                with open(cfg, encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("default_policy", self._DEFAULT_POLICY)
            except (OSError, json.JSONDecodeError):
                pass

        return dict(self._DEFAULT_POLICY)
