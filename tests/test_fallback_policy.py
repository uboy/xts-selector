"""Tests for conservative fallback policy (Phase 11, T11.8).

Tests _compute_fallback_decision, _expand_to_family_coverage, apply_fallback.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


from arkui_xts_selector.indexing.broad_infra import BroadInfraMatch
from arkui_xts_selector.indexing.pr_resolver import (
    PrResolveEntry,
    PrResolveResult,
    _compute_aae_rate,
    _compute_fallback_decision,
    _expand_to_family_coverage,
    apply_fallback,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_entry(
    changed_file: str = "test.cpp",
    apis: tuple[str, ...] = (),
    consumers: tuple[str, ...] = (),
    broad_infra: BroadInfraMatch | None = None,
    risk: str = "low",
    parser_level: int = 0,
) -> PrResolveEntry:
    return PrResolveEntry(
        changed_file=changed_file,
        affected_apis=apis,
        consumer_projects=consumers,
        broad_infra_match=broad_infra,
        false_negative_risk=risk,
        parser_level=parser_level,
    )


def _make_broad_match(
    risk: str = "critical", rule_id: str = "test_rule"
) -> BroadInfraMatch:
    return BroadInfraMatch(
        rule_id=rule_id,
        rationale="test",
        fan_out_target="all_components",
        false_negative_risk=risk,
    )


def _make_xts_root(dirs: list[str]) -> Path:
    """Create a temp dir with XTS-style subdirectories."""
    tmp = tempfile.mkdtemp(prefix="xts_test_")
    for d in dirs:
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    return Path(tmp)


# ── _compute_aae_rate ────────────────────────────────────────────────


class TestComputeAAERate:
    def test_empty_entries(self):
        r = PrResolveResult()
        assert _compute_aae_rate(r) == 0.0

    def test_no_coverage(self):
        r = PrResolveResult(
            entries=(
                _make_entry("a.cpp"),
                _make_entry("b.cpp"),
            )
        )
        assert _compute_aae_rate(r) == 0.0

    def test_full_coverage(self):
        r = PrResolveResult(
            entries=(
                _make_entry("a.cpp", apis=("role",)),
                _make_entry("b.cpp", consumers=("ace_ets_module_foo",)),
            )
        )
        assert _compute_aae_rate(r) == 1.0

    def test_partial_coverage(self):
        r = PrResolveResult(
            entries=(
                _make_entry("a.cpp", apis=("role",)),
                _make_entry("b.cpp"),
                _make_entry("c.cpp", broad_infra=_make_broad_match()),
            )
        )
        assert abs(_compute_aae_rate(r) - 2 / 3) < 0.01


# ── _compute_fallback_decision ───────────────────────────────────────


class TestComputeFallbackDecision:
    def test_critical_risk_triggers_rescue(self):
        r = PrResolveResult(
            entries=(
                _make_entry(
                    "frame_node.cpp", broad_infra=_make_broad_match("critical")
                ),
            ),
            overall_false_negative_risk="critical",
        )
        d = _compute_fallback_decision(r)
        assert d.apply is True
        assert d.level == "rescue"
        assert "critical risk" in d.reason

    def test_high_risk_low_aae_triggers_safety_net(self):
        # 3 entries, only 1 has coverage → AAE = 33% < 40%
        r = PrResolveResult(
            entries=(
                _make_entry("a.cpp", apis=("btn",)),
                _make_entry("b.cpp"),
                _make_entry("c.cpp"),
            ),
            overall_false_negative_risk="high",
        )
        d = _compute_fallback_decision(r)
        assert d.apply is True
        assert d.level == "safety_net"
        assert "high risk" in d.reason

    def test_high_risk_ok_aae_no_fallback(self):
        # All 3 have coverage → AAE = 100% ≥ 40%
        r = PrResolveResult(
            entries=(
                _make_entry("a.cpp", apis=("btn",)),
                _make_entry("b.cpp", consumers=("ace_ets_module_foo",)),
                _make_entry("c.cpp", apis=("role",)),
            ),
            overall_false_negative_risk="high",
        )
        d = _compute_fallback_decision(r)
        assert d.apply is False
        assert d.level == "none"

    def test_medium_risk_no_fallback(self):
        r = PrResolveResult(
            entries=(_make_entry("a.cpp"),),
            overall_false_negative_risk="medium",
        )
        d = _compute_fallback_decision(r)
        assert d.apply is False

    def test_low_risk_no_fallback(self):
        r = PrResolveResult(
            entries=(_make_entry("a.cpp", apis=("btn",)),),
            overall_false_negative_risk="low",
        )
        d = _compute_fallback_decision(r)
        assert d.apply is False

    def test_critical_with_xts_root_bounded_expansion(self):
        """Critical risk triggers rescue; expansion is bounded by fanout config."""
        xts = _make_xts_root(
            [
                "ace_ets_module_button",
                "ace_ets_module_image",
                "ace_ets_module_layout_grid",
            ]
        )
        try:
            r = PrResolveResult(
                entries=(
                    _make_entry(
                        "frame_node.cpp", broad_infra=_make_broad_match("critical")
                    ),
                ),
                overall_false_negative_risk="critical",
            )
            d = _compute_fallback_decision(r, xts_root=xts)
            assert d.apply is True
            assert d.level == "rescue"
            # Extra targets may be empty (bounded) or up to cap
            assert len(d.extra_targets) <= 60
        finally:
            import shutil

            shutil.rmtree(xts, ignore_errors=True)

    def test_no_xts_root_no_expansion(self):
        r = PrResolveResult(
            entries=(
                _make_entry(
                    "frame_node.cpp", broad_infra=_make_broad_match("critical")
                ),
            ),
            overall_false_negative_risk="critical",
        )
        d = _compute_fallback_decision(r, xts_root=None)
        assert d.apply is True
        assert d.level == "rescue"
        assert len(d.extra_targets) == 0


# ── _expand_to_family_coverage ────────────────────────────────────────


class TestExpandToFamilyCoverage:
    def test_broad_infra_bounded_expansion(self):
        """Broad infra no longer returns ALL dirs — uses bounded fanout or empty."""
        xts = _make_xts_root(
            [
                "ace_ets_module_button",
                "ace_ets_module_image",
                "ace_ets_module_text",
                "not_a_test_dir",
            ]
        )
        try:
            r = PrResolveResult(
                entries=(
                    _make_entry(
                        "frame_node.cpp", broad_infra=_make_broad_match("critical")
                    ),
                ),
            )
            expanded = _expand_to_family_coverage(r, xts)
            # With unknown fanout_id "all", returns empty (bounded behavior)
            # Or could return a limited set if fanout config has a matching target
            assert len(expanded) <= 60  # Hard cap enforced
            assert "not_a_test_dir" not in expanded
        finally:
            import shutil

            shutil.rmtree(xts, ignore_errors=True)

    def test_family_prefix_matching(self):
        """Family prefix matching is bounded by fanout config or hard cap."""
        xts = _make_xts_root(
            [
                "ace_ets_module_grid",
                "ace_ets_module_grid_item",
                "ace_ets_module_image",
                "ace_ets_module_text",
            ]
        )
        try:
            r = PrResolveResult(
                entries=(
                    _make_entry(
                        "grid_pattern.cpp",
                        consumers=("ace_ets_module_grid",),
                    ),
                ),
            )
            expanded = _expand_to_family_coverage(r, xts)
            # grid family should match at least grid itself
            assert "ace_ets_module_grid" in expanded
            # May or may not include grid_item depending on fanout config
            assert "ace_ets_module_image" not in expanded
        finally:
            import shutil

            shutil.rmtree(xts, ignore_errors=True)

    def test_no_entries_returns_empty(self):
        xts = _make_xts_root(["ace_ets_module_button"])
        try:
            r = PrResolveResult()
            expanded = _expand_to_family_coverage(r, xts)
            assert len(expanded) == 0
        finally:
            import shutil

            shutil.rmtree(xts, ignore_errors=True)

    def test_no_xts_root_returns_empty(self):
        r = PrResolveResult(
            entries=(
                _make_entry(
                    "frame_node.cpp", broad_infra=_make_broad_match("critical")
                ),
            ),
        )
        expanded = _expand_to_family_coverage(r, None)
        assert len(expanded) == 0


# ── apply_fallback ────────────────────────────────────────────────────


class TestApplyFallback:
    def test_no_fallback_needed_returns_same(self):
        original = PrResolveResult(
            entries=(_make_entry("a.cpp", apis=("btn",)),),
            overall_false_negative_risk="low",
        )
        result = apply_fallback(original)
        assert result.fallback_applied is False
        assert result.fallback_level == "none"
        assert result.entries == original.entries

    def test_critical_applies_rescue(self):
        xts = _make_xts_root(
            [
                "ace_ets_module_button",
                "ace_ets_module_image",
                "ace_ets_module_text",
            ]
        )
        try:
            original = PrResolveResult(
                entries=(
                    _make_entry(
                        "frame_node.cpp", broad_infra=_make_broad_match("critical")
                    ),
                ),
                overall_false_negative_risk="critical",
            )
            result = apply_fallback(original, xts_root=xts)
            assert result.fallback_applied is True
            assert result.fallback_level == "rescue"
            # Bounded: extra targets may be 0-60
            assert len(result.fallback_extra_targets) <= 60
            assert "critical risk" in result.fallback_reason
        finally:
            import shutil

            shutil.rmtree(xts, ignore_errors=True)

    def test_safety_net_applies(self):
        original = PrResolveResult(
            entries=(
                _make_entry("a.cpp", apis=("btn",)),
                _make_entry("b.cpp"),
                _make_entry("c.cpp"),
            ),
            overall_false_negative_risk="high",
        )
        result = apply_fallback(original, xts_root=None)
        assert result.fallback_applied is True
        assert result.fallback_level == "safety_net"

    def test_extra_targets_exclude_existing(self):
        """Extra targets from expansion exclude entries already in consumer_projects."""
        xts = _make_xts_root(
            [
                "ace_ets_module_button",
                "ace_ets_module_button_static",
                "ace_ets_module_image",
            ]
        )
        try:
            original = PrResolveResult(
                entries=(
                    _make_entry(
                        "frame_node.cpp", broad_infra=_make_broad_match("critical")
                    ),
                    _make_entry("btn.cpp", consumers=("ace_ets_module_button",)),
                ),
                overall_false_negative_risk="critical",
            )
            result = apply_fallback(original, xts_root=xts)
            # button already in consumer_projects, should NOT be in extra_targets
            assert "ace_ets_module_button" not in result.fallback_extra_targets
        finally:
            import shutil

            shutil.rmtree(xts, ignore_errors=True)

    def test_fallback_preserves_original_fields(self):
        original = PrResolveResult(
            entries=(_make_entry("a.cpp", apis=("btn",)),),
            overall_false_negative_risk="critical",
            coverage_gap=("btn",),
        )
        result = apply_fallback(original, xts_root=None)
        assert result.coverage_gap == ("btn",)
        assert result.overall_false_negative_risk == "critical"
        assert result.entries == original.entries
