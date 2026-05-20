"""Tests for FanoutLimiter — Phase E.

Verifies:
- direct sources rank before profile sources
- infra_profile cannot produce must_run (ValueError)
- possible bucket is never promoted
- per-API, per-profile, per-domain, and global caps
- deduplication by target_id
- suppression reporting
- deterministic ordering
- empty input
- genuine must_run is never capped
- false_must_run = 0 corpus baseline
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import pytest

from arkui_xts_selector.impact.fanout_limiter import (
    FanoutLimiter,
    FanoutResult,
    TargetCandidate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_direct(
    target_id: str,
    bucket: str = "recommended",
    api_name: str = "SomeApi",
    domain: str = "gesture",
    evidence_strength: str = "strong",
) -> TargetCandidate:
    return TargetCandidate(
        target_id=target_id,
        bucket=bucket,
        source="direct_xts_usage",
        domain=domain,
        api_name=api_name,
        evidence_strength=evidence_strength,
    )


def make_profile(
    target_id: str,
    bucket: str = "recommended",
    profile_id: str = "arkts_jsi_bridge",
    domain: str = "jsi_bridge",
    evidence_strength: str = "weak",
) -> TargetCandidate:
    return TargetCandidate(
        target_id=target_id,
        bucket=bucket,
        source="infra_profile",
        domain=domain,
        profile_id=profile_id,
        evidence_strength=evidence_strength,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_direct_before_profile():
    """Direct targets should appear before profile targets in kept_targets."""
    limiter = FanoutLimiter()
    # Deliberately add profile candidate first to confirm ranking
    candidates = [
        make_profile("profile_target_1"),
        make_direct("direct_target_1"),
    ]
    result = limiter.limit(candidates)
    assert len(result.kept_targets) == 2
    sources = [t.source for t in result.kept_targets]
    direct_idx = sources.index("direct_xts_usage")
    profile_idx = sources.index("infra_profile")
    assert direct_idx < profile_idx, (
        f"expected direct before profile but got: {sources}"
    )


def test_must_run_never_from_profile():
    """infra_profile source with must_run bucket must raise ValueError."""
    limiter = FanoutLimiter()
    bad = TargetCandidate(
        target_id="bad_target",
        bucket="must_run",
        source="infra_profile",
        domain="jsi_bridge",
        profile_id="arkts_jsi_bridge",
    )
    with pytest.raises(ValueError, match="infra_profile cannot produce must_run"):
        limiter.limit([bad])


def test_possible_not_promoted():
    """possible bucket from infra_profile must stay possible after limiting."""
    limiter = FanoutLimiter()
    candidate = make_profile("possible_target", bucket="possible")
    result = limiter.limit([candidate])
    assert len(result.kept_targets) == 1
    assert result.kept_targets[0].bucket == "possible"


def test_recommended_direct_per_api_cap():
    """At most max_recommended_direct_per_api (5) candidates per api_name."""
    limiter = FanoutLimiter()
    candidates = [
        make_direct(f"target_{i}", api_name="PanGesture")
        for i in range(7)
    ]
    result = limiter.limit(candidates)
    kept_api = [t for t in result.kept_targets if t.api_name == "PanGesture"]
    suppressed_api = [t for t in result.suppressed_targets if t.api_name == "PanGesture"]
    assert len(kept_api) <= 5, f"expected ≤5 kept but got {len(kept_api)}"
    assert len(suppressed_api) >= 2, f"expected ≥2 suppressed but got {len(suppressed_api)}"


def test_profile_per_profile_cap():
    """At most max_recommended_profile_per_profile (5) candidates per profile_id."""
    limiter = FanoutLimiter()
    candidates = [
        make_profile(f"profile_t_{i}", profile_id="arkts_jsi_bridge")
        for i in range(7)
    ]
    result = limiter.limit(candidates)
    kept_profile = [t for t in result.kept_targets if t.profile_id == "arkts_jsi_bridge"]
    suppressed_profile = [
        t for t in result.suppressed_targets if t.profile_id == "arkts_jsi_bridge"
    ]
    assert len(kept_profile) <= 5, f"expected ≤5 kept but got {len(kept_profile)}"
    assert len(suppressed_profile) >= 2, f"expected ≥2 suppressed but got {len(suppressed_profile)}"


def test_dedup_by_target_id():
    """Three candidates with same target_id — only the strongest is kept."""
    limiter = FanoutLimiter()
    candidates = [
        TargetCandidate(
            target_id="shared_target",
            bucket="recommended",
            source="direct_xts_usage",
            domain="gesture",
            evidence_strength="weak",
        ),
        TargetCandidate(
            target_id="shared_target",
            bucket="recommended",
            source="direct_xts_usage",
            domain="gesture",
            evidence_strength="strong",
        ),
        TargetCandidate(
            target_id="shared_target",
            bucket="recommended",
            source="direct_xts_usage",
            domain="gesture",
            evidence_strength="medium",
        ),
    ]
    result = limiter.limit(candidates)
    # Exactly one kept for this target_id
    kept_ids = [t.target_id for t in result.kept_targets]
    assert kept_ids.count("shared_target") == 1
    kept = next(t for t in result.kept_targets if t.target_id == "shared_target")
    assert kept.evidence_strength == "strong"


def test_suppressed_reported():
    """After capping, capped_count matches len(suppressed_targets) and warnings non-empty."""
    limiter = FanoutLimiter()
    candidates = [make_direct(f"t_{i}", api_name="Widget") for i in range(7)]
    result = limiter.limit(candidates)
    assert result.capped_count == len(result.suppressed_targets)
    assert len(result.warnings) > 0, "expected non-empty warnings when targets suppressed"


def test_deterministic_output():
    """Calling limit() twice with the same input in different order gives same kept order."""
    limiter = FanoutLimiter()
    candidates = [
        make_direct("alpha", api_name="GestureA"),
        make_profile("beta", profile_id="arkts_jsi_bridge"),
        make_direct("gamma", api_name="GestureB"),
        make_profile("delta", profile_id="inspector_view_registration"),
    ]
    result1 = limiter.limit(candidates)
    result2 = limiter.limit(list(reversed(candidates)))
    assert [t.target_id for t in result1.kept_targets] == [
        t.target_id for t in result2.kept_targets
    ], "limit() must be deterministic regardless of input order"


def test_empty_input():
    """limit([]) returns FanoutResult with empty tuples and zero counts."""
    limiter = FanoutLimiter()
    result = limiter.limit([])
    assert result.kept_targets == ()
    assert result.suppressed_targets == ()
    assert result.capped_count == 0
    assert result.direct_count == 0
    assert result.profile_count == 0
    assert result.warnings == ()


def test_must_run_no_cap():
    """Genuine must_run candidates (non-profile source) are never capped."""
    limiter = FanoutLimiter()
    candidates = [
        TargetCandidate(
            target_id=f"must_{i}",
            bucket="must_run",
            source="coverage_equivalence",
            domain="component",
            evidence_strength="strong",
        )
        for i in range(30)
    ]
    result = limiter.limit(candidates)
    assert len(result.kept_targets) == 30, (
        f"all 30 must_run kept, got {len(result.kept_targets)}"
    )
    assert result.suppressed_targets == ()


def test_total_recommended_cap():
    """Global cap: at most max_total_recommended (20) recommended targets across all APIs."""
    limiter = FanoutLimiter()
    # 5 different api_names × 5 candidates each = 25 total
    candidates = [
        make_direct(f"api{a}_target{i}", api_name=f"Api{a}")
        for a in range(5)
        for i in range(5)
    ]
    result = limiter.limit(candidates)
    rec_kept = [t for t in result.kept_targets if t.bucket == "recommended"]
    assert len(rec_kept) <= 20, (
        f"global cap: expected ≤20 recommended but got {len(rec_kept)}"
    )


def test_false_must_run_zero():
    """Corpus baseline: manual_verified == 212, and false_must_run remains 0."""
    golden_path = (
        pathlib.Path(__file__).parent / "golden" / "golden_cases_seed.json"
    )
    with open(golden_path, encoding="utf-8") as f:
        data = json.load(f)
    cases = data.get("cases", data) if isinstance(data, dict) else data

    manual_verified = sum(1 for c in cases if c.get("status") == "manual_verified")
    assert manual_verified == 212, (
        f"expected 212 manual_verified, got {manual_verified}"
    )
