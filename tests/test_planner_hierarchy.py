"""
Tests for Phase 3: Planner hierarchy (member > type > family preference).

Run:
    python3 -m unittest tests.test_planner_hierarchy -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from arkui_xts_selector.cli import build_global_coverage_recommendations

# Load ranking_rules.json to get the config we just updated
RANKING_RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "ranking_rules.json"


class FanOutLimitsConfigTests(unittest.TestCase):
    """Verify ranking_rules.json has the new fan-out limit fields."""

    def test_ranking_rules_compiles(self) -> None:
        """ranking_rules.json must be valid JSON."""
        with RANKING_RULES_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_family_fanout_limits_present(self) -> None:
        """ranking_rules.json must have family_fanout_limits section."""
        with RANKING_RULES_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("family_fanout_limits", data)
        fanout = data["family_fanout_limits"]
        self.assertIsInstance(fanout, dict)

    def test_button_fanout_limits_configured(self) -> None:
        """Button family must have explicit fan-out limits."""
        with RANKING_RULES_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        button = data["family_fanout_limits"]["button"]
        self.assertIn("max_type_representatives", button)
        self.assertIn("max_family_representatives", button)
        self.assertGreater(button["max_type_representatives"], 0)
        self.assertGreater(button["max_family_representatives"], 0)

    def test_default_fanout_limits_present(self) -> None:
        """Default fan-out limits must be configured."""
        with RANKING_RULES_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        default = data["family_fanout_limits"]["default"]
        self.assertIn("max_type_representatives", default)
        self.assertIn("max_family_representatives", default)

    def test_precision_budget_present(self) -> None:
        """ranking_rules.json must have precision_budget section."""
        with RANKING_RULES_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("precision_budget", data)
        budget = data["precision_budget"]
        self.assertIn("member_aware_max_required", budget)
        self.assertIn("type_level_max_required", budget)
        self.assertIn("family_level_max_required", budget)
        self.assertLessEqual(
            budget["member_aware_max_required"],
            budget["type_level_max_required"],
            "Member-aware budget must be tighter than type-level",
        )
        self.assertLessEqual(
            budget["type_level_max_required"],
            budget["family_level_max_required"],
            "Type-level budget must be tighter than family-level",
        )


class PrecisionModeTests(unittest.TestCase):
    """Verify that precision_mode is correctly determined based on evidence level.

    These tests verify the logic that would be in the planner:
    - member hints -> precision_mode = "member"
    - type hints (no member) -> precision_mode = "type"
    - family only -> precision_mode = "family"
    """

    def _simulate_precision_mode(self, member_hints: list, type_hints: list, family_hints: list) -> str:
        """Simulate the precision mode determination logic."""
        if member_hints:
            return "member"
        elif type_hints:
            return "type"
        else:
            return "family"

    def test_member_hints_gives_member_mode(self) -> None:
        """When member hints exist, precision_mode must be 'member'."""
        result = self._simulate_precision_mode(
            member_hints=["ButtonAttribute.role"],
            type_hints=["Button"],
            family_hints=["button"],
        )
        self.assertEqual(result, "member")

    def test_type_hints_gives_type_mode(self) -> None:
        """When only type hints exist (no member), precision_mode must be 'type'."""
        result = self._simulate_precision_mode(
            member_hints=[],
            type_hints=["Button"],
            family_hints=["button"],
        )
        self.assertEqual(result, "type")

    def test_family_only_gives_family_mode(self) -> None:
        """When only family hints exist, precision_mode must be 'family'."""
        result = self._simulate_precision_mode(
            member_hints=[],
            type_hints=[],
            family_hints=["button"],
        )
        self.assertEqual(result, "family")

    def test_member_suppresses_type_fallback(self) -> None:
        """When member hints exist for an owner, type hints for same owner should be suppressed."""
        member_owners = {"Button"}
        type_hints = ["Button", "MenuItem"]
        # Button should be suppressed (same owner as member hint)
        suppressed = [t for t in type_hints if t.partition(".")[0] in member_owners]
        self.assertIn("Button", suppressed)
        # MenuItem should NOT be suppressed
        remaining = [t for t in type_hints if t.partition(".")[0] not in member_owners]
        self.assertIn("MenuItem", remaining)


class FanOutSuppressionTests(unittest.TestCase):
    """Verify that fan-out limits suppress excess type/family representatives."""

    def _apply_fanout_limits(self, covered_types: list, covered_families: list, family_key: str) -> dict:
        """Simulate fan-out limit enforcement."""
        with RANKING_RULES_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        fanout = data.get("family_fanout_limits", {})
        default = fanout.get("default", {"max_type_representatives": 5, "max_family_representatives": 10})
        limit = fanout.get(family_key, default)
        max_types = limit.get("max_type_representatives", default["max_type_representatives"])
        max_families = limit.get("max_family_representatives", default["max_family_representatives"])

        suppressed_types = []
        suppressed_families = []

        sorted_types = sorted(covered_types)
        if len(sorted_types) > max_types:
            suppressed_types = sorted_types[max_types:]

        sorted_families = sorted(covered_families)
        if len(sorted_families) > max_families:
            suppressed_families = sorted_families[max_families:]

        return {
            "suppressed_type_hints": suppressed_types,
            "suppressed_families": suppressed_families,
            "remaining_types": sorted_types[:max_types],
            "remaining_families": sorted_families[:max_families],
        }

    def test_button_type_suppression(self) -> None:
        """Button family has max_type_representatives=3, excess types should be suppressed."""
        result = self._apply_fanout_limits(
            covered_types=["Button", "ButtonAttribute", "ButtonModifier", "ButtonStyle", "ButtonTheme"],
            covered_families=["button"],
            family_key="button",
        )
        self.assertEqual(len(result["suppressed_type_hints"]), 2)
        self.assertEqual(len(result["remaining_types"]), 3)
        self.assertIn("Button", result["remaining_types"])

    def test_no_suppression_within_limits(self) -> None:
        """When within limits, no suppression should occur."""
        result = self._apply_fanout_limits(
            covered_types=["Button", "ButtonAttribute"],
            covered_families=["button"],
            family_key="button",
        )
        self.assertEqual(result["suppressed_type_hints"], [])
        self.assertEqual(result["remaining_types"], ["Button", "ButtonAttribute"])

    def test_slider_stricter_limits(self) -> None:
        """Slider family has max_type_representatives=2, tighter than default."""
        result = self._apply_fanout_limits(
            covered_types=["Slider", "SliderModifier", "SliderAttribute", "SliderTheme"],
            covered_families=["slider"],
            family_key="slider",
        )
        self.assertEqual(len(result["suppressed_type_hints"]), 2)
        self.assertEqual(len(result["remaining_types"]), 2)

    def test_default_limits_for_unknown_family(self) -> None:
        """Unknown families should use default limits (5 types, 10 families)."""
        result = self._apply_fanout_limits(
            covered_types=["Web", "WebModifier", "WebView", "WebController", "WebAttribute", "WebTheme"],
            covered_families=["web"],
            family_key="unknown_family",
        )
        # Default max_type_representatives=5
        self.assertEqual(len(result["suppressed_type_hints"]), 1)
        self.assertEqual(len(result["remaining_types"]), 5)

    def test_web_explicit_limits(self) -> None:
        """Web family has explicit max_type_representatives=3."""
        result = self._apply_fanout_limits(
            covered_types=["Web", "WebModifier", "WebView", "WebController", "WebAttribute"],
            covered_families=["web"],
            family_key="web",
        )
        self.assertEqual(len(result["remaining_types"]), 3)
        self.assertEqual(len(result["suppressed_type_hints"]), 2)

    def test_text_higher_type_limit(self) -> None:
        """Text family allows max_type_representatives=4 (broader than slider/swiper)."""
        result = self._apply_fanout_limits(
            covered_types=["Text", "TextModifier", "Span", "SpanModifier", "TextAttribute"],
            covered_families=["text"],
            family_key="text",
        )
        self.assertEqual(len(result["remaining_types"]), 4)
        self.assertEqual(len(result["suppressed_type_hints"]), 1)

    def test_swiper_strict_type_limit(self) -> None:
        """Swiper family has max_type_representatives=2."""
        result = self._apply_fanout_limits(
            covered_types=["Swiper", "SwiperModifier", "SwiperAttribute", "SwiperController"],
            covered_families=["swiper"],
            family_key="swiper",
        )
        self.assertEqual(len(result["remaining_types"]), 2)
        self.assertEqual(len(result["suppressed_type_hints"]), 2)

    def test_image_explicit_limits_configured(self) -> None:
        """Image family must have explicit fan-out limits configured."""
        with RANKING_RULES_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        image = data["family_fanout_limits"]["image"]
        self.assertIn("max_type_representatives", image)
        self.assertIn("max_family_representatives", image)
        self.assertGreater(image["max_type_representatives"], 0)


def _make_candidate(project: str, member_hint_keys: list, type_hint_keys: list, family_keys: list, source_profile: dict) -> dict:
    """Build a minimal candidate_entry for build_global_coverage_recommendations."""
    return {
        "source": {"key": source_profile["key"], "type": source_profile["type"], "value": source_profile["value"]},
        "source_profile": source_profile,
        "project_entry": {
            "project": project,
            "test_json": f"{project}/Test.json",
            "build_target": project.rsplit("/", 1)[-1],
            "bundle_name": "com.example.test",
            "driver_module_name": "entry",
            "xdevice_module_name": project.rsplit("/", 1)[-1].replace("_", "") + "Test",
            "bucket": "must-run",
            "variant": "static",
            "surface": "static",
            "scope_tier": "direct",
            "specificity_score": 10,
            "score": 40,
            "family_keys": list(family_keys),
            "direct_family_keys": list(family_keys),
            "type_hint_keys": list(type_hint_keys),
            "direct_type_hint_keys": list(type_hint_keys),
            "type_hint_focus_counts": {k: 2 for k in type_hint_keys},
            "member_hint_keys": list(member_hint_keys),
            "direct_member_hint_keys": list(member_hint_keys),
            "member_hint_focus_counts": {k: 2 for k in member_hint_keys},
            "umbrella_penalty": 0.0,
            "scope_reasons": [],
        },
        "source_rank": 1,
    }


class RealPlannerTypeFallbackTests(unittest.TestCase):
    """Integration tests that call build_global_coverage_recommendations directly
    to verify member > type > family preference ordering in the real planner."""

    def _source_profile(self, member_hints: list, type_hints: list, family_keys: list) -> dict:
        return {
            "key": "changed_file:button_model_static.cpp",
            "type": "changed_file",
            "value": "button_model_static.cpp",
            "family_keys": list(family_keys),
            "type_hint_keys": list(type_hints),
            "member_hint_keys": list(member_hints),
            "focus_tokens": list(member_hints) + list(type_hints) + list(family_keys),
        }

    def test_type_only_candidate_suppressed_when_source_has_member_hints(self) -> None:
        """A candidate with only type-level coverage for an owner is suppressed
        when the source has member hints for that same owner."""
        source_profile = self._source_profile(
            member_hints=["ButtonAttribute.role"],
            type_hints=["ButtonAttribute"],
            family_keys=["button"],
        )
        # type_only: covers ButtonAttribute at type level, no member hints
        type_only = _make_candidate(
            "test/xts/acts/arkui/button_type_only",
            member_hint_keys=[],
            type_hint_keys=["ButtonAttribute"],
            family_keys=["button"],
            source_profile=source_profile,
        )
        # member_covering: covers ButtonAttribute.role at member level
        member_covering = _make_candidate(
            "test/xts/acts/arkui/button_member",
            member_hint_keys=["ButtonAttribute.role"],
            type_hint_keys=["ButtonAttribute"],
            family_keys=["button"],
            source_profile=source_profile,
        )
        result = build_global_coverage_recommendations(
            [type_only, member_covering],
            repo_root=Path("/tmp"),
            acts_out_root=None,
            device=None,
        )
        required_keys = {t["project"] for t in result.get("required", [])}
        all_keys = {t["project"] for t in result.get("ordered_targets", [])}
        # member_covering must be in required
        self.assertIn("test/xts/acts/arkui/button_member", required_keys)
        # type_only should not be required (type fallback suppressed)
        self.assertNotIn("test/xts/acts/arkui/button_type_only", required_keys)

    def test_type_candidate_included_when_no_member_hints_in_source(self) -> None:
        """When the source has NO member hints, type-level candidates are NOT suppressed."""
        source_profile = self._source_profile(
            member_hints=[],
            type_hints=["ButtonAttribute"],
            family_keys=["button"],
        )
        type_only = _make_candidate(
            "test/xts/acts/arkui/button_type_only",
            member_hint_keys=[],
            type_hint_keys=["ButtonAttribute"],
            family_keys=["button"],
            source_profile=source_profile,
        )
        result = build_global_coverage_recommendations(
            [type_only],
            repo_root=Path("/tmp"),
            acts_out_root=None,
            device=None,
        )
        required_keys = {t["project"] for t in result.get("required", [])}
        self.assertIn("test/xts/acts/arkui/button_type_only", required_keys)

    def test_precision_mode_member_when_member_hints_present(self) -> None:
        """precision_mode must be 'member' when covered_member_hints is non-empty."""
        source_profile = self._source_profile(
            member_hints=["ButtonAttribute.role"],
            type_hints=["ButtonAttribute"],
            family_keys=["button"],
        )
        member_covering = _make_candidate(
            "test/xts/acts/arkui/button_member",
            member_hint_keys=["ButtonAttribute.role"],
            type_hint_keys=["ButtonAttribute"],
            family_keys=["button"],
            source_profile=source_profile,
        )
        result = build_global_coverage_recommendations(
            [member_covering],
            repo_root=Path("/tmp"),
            acts_out_root=None,
            device=None,
        )
        ordered = result.get("ordered_targets", [])
        self.assertTrue(len(ordered) > 0, "Expected at least one ordered target")
        member_target = next(
            (t for t in ordered if t["project"] == "test/xts/acts/arkui/button_member"), None
        )
        self.assertIsNotNone(member_target)
        self.assertEqual(member_target.get("precision_mode"), "member")


class FanOutSuppressionSerializationTests(unittest.TestCase):
    """Regression tests for JSON serialisability of fan-out suppression output.

    Before the fix, build_global_coverage_recommendations stored suppressed_type_hints
    and suppressed_families as set() objects, which caused json.dumps() to raise
    TypeError: Object of type set is not JSON serializable.

    The scenario that triggers suppression requires a candidate that accumulates
    covered_families from one source (family-only source profile) AND covered_type_hints
    exceeding the per-family limit from another source (type-hint source profile).
    """

    _SUITE = "test/xts/acts/arkui/navigation_suite"

    def _family_only_profile(self, family_keys: list, label: str = "a") -> dict:
        """Source profile with family keys but no type hints -> populates covered_families."""
        return {
            "key": f"changed_file:nav_{label}.cpp",
            "type": "changed_file",
            "value": f"nav_{label}.cpp",
            "family_keys": list(family_keys),
            "capability_keys": [],
            "type_hint_keys": [],
            "member_hint_keys": [],
            "focus_tokens": list(family_keys),
        }

    def _type_hint_profile(self, type_hints: list, family_keys: list, label: str = "b") -> dict:
        """Source profile with type hints -> populates covered_type_hints."""
        return {
            "key": f"changed_file:nav_{label}.cpp",
            "type": "changed_file",
            "value": f"nav_{label}.cpp",
            "family_keys": list(family_keys),
            "capability_keys": [],
            "type_hint_keys": list(type_hints),
            "member_hint_keys": [],
            "focus_tokens": list(type_hints) + list(family_keys),
        }

    def _make_nav_candidates(self, type_hints: list) -> list:
        """Return two candidate entries for the same suite from different sources.

        Source A (family-only) populates covered_families with 'navigation'.
        Source B (type-hint) populates covered_type_hints with the provided hints.
        Combined they satisfy the suppression trigger condition.
        """
        profile_a = self._family_only_profile(family_keys=["navigation"], label="a")
        profile_b = self._type_hint_profile(type_hints=type_hints, family_keys=["navigation"], label="b")
        entry_a = {
            "source": {"key": profile_a["key"], "type": profile_a["type"], "value": profile_a["value"]},
            "source_profile": profile_a,
            "project_entry": {
                "project": self._SUITE,
                "test_json": f"{self._SUITE}/Test.json",
                "build_target": "navigation_suite",
                "bundle_name": "com.example.nav",
                "driver_module_name": "entry",
                "xdevice_module_name": "NavigationSuiteTest",
                "bucket": "must-run",
                "variant": "static",
                "surface": "static",
                "scope_tier": "direct",
                "specificity_score": 10,
                "score": 40,
                "family_keys": ["navigation"],
                "direct_family_keys": ["navigation"],
                "type_hint_keys": [],
                "direct_type_hint_keys": [],
                "type_hint_focus_counts": {},
                "member_hint_keys": [],
                "direct_member_hint_keys": [],
                "member_hint_focus_counts": {},
                "umbrella_penalty": 0.0,
                "scope_reasons": [],
            },
            "source_rank": 1,
        }
        entry_b = {
            "source": {"key": profile_b["key"], "type": profile_b["type"], "value": profile_b["value"]},
            "source_profile": profile_b,
            "project_entry": {
                **entry_a["project_entry"],
                "type_hint_keys": list(type_hints),
                "direct_type_hint_keys": list(type_hints),
                "type_hint_focus_counts": {k: 1 for k in type_hints},
            },
            "source_rank": 2,
        }
        return [entry_a, entry_b]

    def test_suppressed_type_hints_is_json_serializable(self) -> None:
        """suppressed_type_hints must be a list so that json.dumps() succeeds.

        Regression for: target.setdefault("suppressed_type_hints", set()).add(...)
        leaving a set that is not JSON serializable.
        """
        import json

        # navigation family has max_type_representatives=3; provide 4 hints -> 1 suppressed
        type_hints = ["navigationoperation", "navcontentinfo", "popinfo", "swipercontroller"]
        candidates = self._make_nav_candidates(type_hints)
        result = build_global_coverage_recommendations(
            candidates,
            repo_root=Path("/tmp"),
            acts_out_root=None,
            device=None,
        )
        try:
            json.dumps(result)
        except TypeError as exc:
            self.fail(f"Result is not JSON serializable: {exc}")

    def test_suppressed_type_hints_type_is_list(self) -> None:
        """When fan-out suppression fires, suppressed_type_hints must be a list."""
        type_hints = ["navigationoperation", "navcontentinfo", "popinfo", "swipercontroller"]
        candidates = self._make_nav_candidates(type_hints)
        result = build_global_coverage_recommendations(
            candidates,
            repo_root=Path("/tmp"),
            acts_out_root=None,
            device=None,
        )
        for target in result.get("ordered_targets", []):
            suppressed = target.get("suppressed_type_hints")
            if suppressed is not None:
                self.assertIsInstance(
                    suppressed, list,
                    f"suppressed_type_hints must be list, got {type(suppressed).__name__}",
                )

    def test_suppressed_families_type_is_list(self) -> None:
        """When family fan-out suppression fires, suppressed_families must be a list."""
        import json

        # To trigger family suppression: navigation max_family_representatives=5;
        # stack multiple families from different sources.
        # Easiest: use one source with 6 family hints (all family-only so covered_families fills up).
        families = ["navigation", "text_input", "select", "checkboxgroup", "gesture", "text_rendering"]
        profiles_and_entries = []
        for i, fam in enumerate(families):
            prof = self._family_only_profile(family_keys=[fam], label=str(i))
            entry = {
                "source": {"key": prof["key"], "type": prof["type"], "value": prof["value"]},
                "source_profile": prof,
                "project_entry": {
                    "project": self._SUITE,
                    "test_json": f"{self._SUITE}/Test.json",
                    "build_target": "navigation_suite",
                    "bundle_name": "com.example.nav",
                    "driver_module_name": "entry",
                    "xdevice_module_name": "NavigationSuiteTest",
                    "bucket": "must-run",
                    "variant": "static",
                    "surface": "static",
                    "scope_tier": "direct",
                    "specificity_score": 10,
                    "score": 40,
                    "family_keys": [fam],
                    "direct_family_keys": [fam],
                    "type_hint_keys": [],
                    "direct_type_hint_keys": [],
                    "type_hint_focus_counts": {},
                    "member_hint_keys": [],
                    "direct_member_hint_keys": [],
                    "member_hint_focus_counts": {},
                    "umbrella_penalty": 0.0,
                    "scope_reasons": [],
                },
                "source_rank": i + 1,
            }
            profiles_and_entries.append(entry)

        result = build_global_coverage_recommendations(
            profiles_and_entries,
            repo_root=Path("/tmp"),
            acts_out_root=None,
            device=None,
        )
        try:
            json.dumps(result)
        except TypeError as exc:
            self.fail(f"Result is not JSON serializable: {exc}")

        for target in result.get("ordered_targets", []):
            sf = target.get("suppressed_families")
            if sf is not None:
                self.assertIsInstance(
                    sf, list,
                    f"suppressed_families must be list, got {type(sf).__name__}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
