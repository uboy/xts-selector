"""Canonical corpus schema validation tests.

Tests that benchmark fixture data structures are graph-aware and validate
expected properties of canonical corpus entries.

Import boundary: imports model types and standard library only.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.selection import (
    FalseNegativeRisk,
    RunnabilityState,
    SemanticBucket,
)
from arkui_xts_selector.model.usage import CoverageEquivalenceClass


# ---------------------------------------------------------------------------
# Canonical corpus entries for testing
# ---------------------------------------------------------------------------

CORPUS_ENTRIES = [
    {
        "family": "Button",
        "affected_apis": [
            {
                "namespace": "arkui",
                "surface": "static",
                "kind": "component",
                "module": "@ohos.arkui.component",
                "public_name": "Button",
            },
            {
                "namespace": "arkui",
                "surface": "static",
                "kind": "modifier",
                "module": "@ohos.arkui.component.Button",
                "public_name": "ButtonModifier",
            },
            {
                "namespace": "arkui",
                "surface": "static",
                "kind": "attribute",
                "module": "@ohos.arkui.component.Button",
                "public_name": "ButtonAttribute",
            },
        ],
        "expected_coverage_equivalence": "exact_api_same_usage_shape",
        "expected_bucket": "must_run",
        "expected_false_negative_risk": "low",
        "expected_runnability_state": "confirmed",
    },
    {
        "family": "Slider",
        "affected_apis": [
            {
                "namespace": "arkui",
                "surface": "static",
                "kind": "component",
                "module": "@ohos.arkui.component",
                "public_name": "Slider",
            },
        ],
        "expected_coverage_equivalence": "exact_api_same_usage_shape",
        "expected_bucket": "must_run",
        "expected_false_negative_risk": "low",
        "expected_runnability_state": "confirmed",
    },
    {
        "family": "Navigation",
        "affected_apis": [
            {
                "namespace": "arkui",
                "surface": "static",
                "kind": "component",
                "module": "@ohos.arkui.component",
                "public_name": "Navigation",
            },
        ],
        "expected_coverage_equivalence": "exact_api_same_usage_shape",
        "expected_bucket": "must_run",
        "expected_false_negative_risk": "medium",
        "expected_runnability_state": "unknown",
    },
    {
        "family": "MenuItem",
        "affected_apis": [
            {
                "namespace": "arkui",
                "surface": "static",
                "kind": "component",
                "module": "@ohos.arkui.component",
                "public_name": "MenuItem",
            },
        ],
        "expected_coverage_equivalence": "same_family_related_api",
        "expected_bucket": "recommended",
        "expected_false_negative_risk": "medium",
        "expected_runnability_state": "unknown",
    },
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _build_api_id(api_dict: dict) -> ApiEntityId:
    """Build ApiEntityId from corpus entry dict."""
    return ApiEntityId.from_parts(
        namespace=api_dict["namespace"],
        surface=api_dict["surface"],
        kind=api_dict["kind"],
        module=api_dict["module"],
        public_name=api_dict["public_name"],
    )


def _get_valid_literals() -> dict:
    """Return valid literal values for enum-like types."""
    return {
        "coverage_equivalence": CoverageEquivalenceClass.__args__ if hasattr(CoverageEquivalenceClass, "__args__") else (
            "exact_api_same_usage_shape",
            "exact_api_different_arguments",
            "exact_api_different_call_style",
            "exact_api_unknown_usage_shape",
            "same_family_related_api",
            "same_modifier_or_attribute_family",
            "shared_helper_related_api",
            "harness_only_usage",
            "broad_fallback",
            "unresolved_coverage",
        ),
        "false_negative_risk": FalseNegativeRisk.__args__ if hasattr(FalseNegativeRisk, "__args__") else (
            "low",
            "medium",
            "high",
            "critical",
        ),
        "runnability_state": RunnabilityState.__args__ if hasattr(RunnabilityState, "__args__") else (
            "confirmed",
            "unknown",
            "blocked",
        ),
        "semantic_bucket": SemanticBucket.__args__ if hasattr(SemanticBucket, "__args__") else (
            "must_run",
            "recommended",
            "possible",
            "unresolved",
        ),
    }


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class ButtonFixtureValidationTests(unittest.TestCase):
    """Validate Button fixture has expected API entities."""

    def test_button_fixture_has_affected_api(self) -> None:
        """Button test suite should reference Button API entity."""
        button_entry = next(e for e in CORPUS_ENTRIES if e["family"] == "Button")
        self.assertGreater(len(button_entry["affected_apis"]), 0)

        # Verify at least one API has canonical format
        api_ids = [_build_api_id(api) for api in button_entry["affected_apis"]]
        canonical_ids = [api_id.canonical() for api_id in api_ids]

        # All should start with "api:v1:arkui.static:"
        for cid in canonical_ids:
            self.assertTrue(
                cid.startswith("api:v1:arkui.static:"),
                f"Button API ID {cid} should start with 'api:v1:arkui.static:'",
            )

        # Should include Button component
        self.assertTrue(
            any("Button" in cid and "component" in cid for cid in canonical_ids),
            f"Button fixture should include Button component API, got: {canonical_ids}",
        )


class SliderFixtureValidationTests(unittest.TestCase):
    """Validate Slider fixture has expected API entities."""

    def test_slider_fixture_has_affected_api(self) -> None:
        """Slider test suite should reference Slider API entity."""
        slider_entry = next(e for e in CORPUS_ENTRIES if e["family"] == "Slider")
        self.assertGreater(len(slider_entry["affected_apis"]), 0)

        api_ids = [_build_api_id(api) for api in slider_entry["affected_apis"]]
        canonical_ids = [api_id.canonical() for api_id in api_ids]

        # All should start with "api:v1:arkui.static:"
        for cid in canonical_ids:
            self.assertTrue(
                cid.startswith("api:v1:arkui.static:"),
                f"Slider API ID {cid} should start with 'api:v1:arkui.static:'",
            )

        # Should include Slider component
        self.assertTrue(
            any("Slider" in cid and "component" in cid for cid in canonical_ids),
            f"Slider fixture should include Slider component API, got: {canonical_ids}",
        )


class NavigationFixtureValidationTests(unittest.TestCase):
    """Validate Navigation fixture has expected API entities."""

    def test_navigation_fixture_has_affected_api(self) -> None:
        """Navigation test suite should reference Navigation API entity."""
        nav_entry = next(e for e in CORPUS_ENTRIES if e["family"] == "Navigation")
        self.assertGreater(len(nav_entry["affected_apis"]), 0)

        api_ids = [_build_api_id(api) for api in nav_entry["affected_apis"]]
        canonical_ids = [api_id.canonical() for api_id in api_ids]

        # All should start with "api:v1:arkui.static:"
        for cid in canonical_ids:
            self.assertTrue(
                cid.startswith("api:v1:arkui.static:"),
                f"Navigation API ID {cid} should start with 'api:v1:arkui.static:'",
            )

        # Should include Navigation component
        self.assertTrue(
            any("Navigation" in cid and "component" in cid for cid in canonical_ids),
            f"Navigation fixture should include Navigation component API, got: {canonical_ids}",
        )


class MenuItemFixtureValidationTests(unittest.TestCase):
    """Validate MenuItem fixture has expected API entities."""

    def test_menuitem_fixture_has_affected_api(self) -> None:
        """MenuItem test suite should reference MenuItem API entity."""
        menu_entry = next(e for e in CORPUS_ENTRIES if e["family"] == "MenuItem")
        self.assertGreater(len(menu_entry["affected_apis"]), 0)

        api_ids = [_build_api_id(api) for api in menu_entry["affected_apis"]]
        canonical_ids = [api_id.canonical() for api_id in api_ids]

        # All should start with "api:v1:arkui.static:"
        for cid in canonical_ids:
            self.assertTrue(
                cid.startswith("api:v1:arkui.static:"),
                f"MenuItem API ID {cid} should start with 'api:v1:arkui.static:'",
            )

        # Should include MenuItem component
        self.assertTrue(
            any("MenuItem" in cid and "component" in cid for cid in canonical_ids),
            f"MenuItem fixture should include MenuItem component API, got: {canonical_ids}",
        )


class CoverageEquivalenceEnumTests(unittest.TestCase):
    """Validate coverage equivalence values are from the valid enum."""

    def test_coverage_equivalence_is_valid_enum(self) -> None:
        """All coverage equivalence values in fixture data must be from CoverageEquivalenceClass."""
        valid_values = _get_valid_literals()["coverage_equivalence"]

        for entry in CORPUS_ENTRIES:
            ce = entry["expected_coverage_equivalence"]
            self.assertIn(
                ce,
                valid_values,
                f"Coverage equivalence {ce!r} for {entry['family']} is not a valid CoverageEquivalenceClass",
            )


class FalseNegativeRiskValidationTests(unittest.TestCase):
    """Validate false negative risk values are from the valid enum."""

    def test_false_negative_risk_is_valid(self) -> None:
        """All FNR values must be from FalseNegativeRisk Literal."""
        valid_values = _get_valid_literals()["false_negative_risk"]

        for entry in CORPUS_ENTRIES:
            fnr = entry["expected_false_negative_risk"]
            self.assertIn(
                fnr,
                valid_values,
                f"False negative risk {fnr!r} for {entry['family']} is not a valid FalseNegativeRisk",
            )


class RunnabilityStateValidationTests(unittest.TestCase):
    """Validate runnability state values are from the valid enum."""

    def test_runnability_state_is_valid(self) -> None:
        """All runnability state values must be from RunnabilityState Literal."""
        valid_values = _get_valid_literals()["runnability_state"]

        for entry in CORPUS_ENTRIES:
            rs = entry["expected_runnability_state"]
            self.assertIn(
                rs,
                valid_values,
                f"Runnability state {rs!r} for {entry['family']} is not a valid RunnabilityState",
            )


class SemanticBucketValidationTests(unittest.TestCase):
    """Validate semantic bucket values are from the valid enum."""

    def test_semantic_bucket_is_valid(self) -> None:
        """All bucket values must be from SemanticBucket Literal."""
        valid_values = _get_valid_literals()["semantic_bucket"]

        for entry in CORPUS_ENTRIES:
            bucket = entry["expected_bucket"]
            self.assertIn(
                bucket,
                valid_values,
                f"Semantic bucket {bucket!r} for {entry['family']} is not a valid SemanticBucket",
            )


class CanonicalIdFormatTests(unittest.TestCase):
    """Validate all canonical IDs follow the expected format."""

    def test_all_canonical_ids_follow_format(self) -> None:
        """All API entity IDs should have the canonical format: api:v1:namespace.surface:kind:module#name"""
        for entry in CORPUS_ENTRIES:
            for api_dict in entry["affected_apis"]:
                api_id = _build_api_id(api_dict)
                canonical = api_id.canonical()

                # Basic format validation
                parts = canonical.split(":")
                self.assertEqual(len(parts), 5, f"Canonical ID {canonical} should have 5 colon-separated parts")

                # First part should be "api"
                self.assertEqual(parts[0], "api", f"First part of {canonical} should be 'api'")

                # Second part should be "v1"
                self.assertEqual(parts[1], "v1", f"Second part of {canonical} should be 'v1'")

                # Third part should contain namespace and surface
                self.assertIn(".", parts[2], f"Third part {parts[2]} should contain '.' for namespace.surface")

                # Fourth part should be the kind
                self.assertEqual(parts[3], api_dict["kind"], f"Fourth part should be kind {api_dict['kind']}")

                # Fifth part should be module#name
                self.assertIn("#", parts[4], f"Fifth part {parts[4]} should contain '#' for module#name")


class ApiEntityKindTests(unittest.TestCase):
    """Validate API entity kinds are valid."""

    def test_all_api_kinds_are_valid(self) -> None:
        """All API entity kinds should be valid ApiEntityKind values."""
        valid_kinds = {
            "component",
            "modifier",
            "attribute",
            "event_or_method",
            "module",
            "configuration",
            "helper_family",
        }

        for entry in CORPUS_ENTRIES:
            for api_dict in entry["affected_apis"]:
                kind = api_dict["kind"]
                self.assertIn(
                    kind,
                    valid_kinds,
                    f"API kind {kind!r} for {entry['family']} is not a valid ApiEntityKind",
                )


class ApiSurfaceTests(unittest.TestCase):
    """Validate API surface kinds are valid."""

    def test_all_api_surfaces_are_valid(self) -> None:
        """All API surface kinds should be valid ApiSurfaceKind values."""
        valid_surfaces = {"static", "dynamic", "shared", "unknown"}

        for entry in CORPUS_ENTRIES:
            for api_dict in entry["affected_apis"]:
                surface = api_dict["surface"]
                self.assertIn(
                    surface,
                    valid_surfaces,
                    f"API surface {surface!r} for {entry['family']} is not a valid ApiSurfaceKind",
                )


class FamilySpecificityTests(unittest.TestCase):
    """Validate family-specific API associations."""

    def test_button_apis_include_button_family(self) -> None:
        """Button APIs should reference Button family components/modifiers."""
        button_entry = next(e for e in CORPUS_ENTRIES if e["family"] == "Button")

        for api_dict in button_entry["affected_apis"]:
            # At least Button component should reference Button in module or name
            if api_dict["kind"] == "component":
                self.assertIn(
                    "Button",
                    api_dict["public_name"],
                    f"Button component should have 'Button' in public_name, got {api_dict['public_name']}",
                )

    def test_slider_apis_include_slider_family(self) -> None:
        """Slider APIs should reference Slider family components."""
        slider_entry = next(e for e in CORPUS_ENTRIES if e["family"] == "Slider")

        for api_dict in slider_entry["affected_apis"]:
            if api_dict["kind"] == "component":
                self.assertIn(
                    "Slider",
                    api_dict["public_name"],
                    f"Slider component should have 'Slider' in public_name, got {api_dict['public_name']}",
                )


class CorpusEntryCompletenessTests(unittest.TestCase):
    """Validate corpus entries have all required fields."""

    def test_all_entries_have_required_fields(self) -> None:
        """Every corpus entry must have all required fields."""
        required_fields = {
            "family",
            "affected_apis",
            "expected_coverage_equivalence",
            "expected_bucket",
            "expected_false_negative_risk",
            "expected_runnability_state",
        }

        for entry in CORPUS_ENTRIES:
            missing = required_fields - set(entry.keys())
            self.assertEqual(
                missing,
                set(),
                f"Corpus entry for {entry.get('family', 'unknown')} missing required fields: {missing}",
            )

    def test_affected_apis_list_non_empty(self) -> None:
        """Every corpus entry must have at least one affected API."""
        for entry in CORPUS_ENTRIES:
            self.assertGreater(
                len(entry["affected_apis"]),
                0,
                f"Corpus entry for {entry['family']} has no affected APIs",
            )


if __name__ == "__main__":
    unittest.main()
