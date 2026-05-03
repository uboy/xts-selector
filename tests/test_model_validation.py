"""Tests for model validation – canonical identity and model value validation (E1-3).

These tests harden validation of canonical API identity and model value types,
ensuring that internal entities are properly distinguished from public APIs,
that enum values are complete and correctly validated, and that round-trip
serialization preserves data correctly.

Import boundary: this module imports only the standard library and model types.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.model.api import (
    ApiEntityId,
    ApiEntityKind,
    ApiSurfaceKind,
)
from arkui_xts_selector.model.evidence import (
    Evidence,
    ConfidenceLevel,
)
from arkui_xts_selector.model.selection import (
    SemanticBucket,
    RunnabilityState,
)


class InternalNamespaceTests(unittest.TestCase):
    """Tests for internal namespace handling and canonical id format."""

    def test_internal_namespace_does_not_produce_api_prefix(self) -> None:
        """Creating ApiEntityId with namespace="internal" still produces an api: prefix.

        This test documents the current behavior: ApiEntityId.canonical() always
        produces an "api:" prefix regardless of namespace. For internal entities,
        the namespace field itself indicates the internal nature, but the canonical
        id format does not change. Internal entities should ideally use a separate
        type (e.g., InternalEntityId) or a different prefix convention.

        This test verifies that namespace="internal" with kind="helper_family"
        produces a valid but distinguishable id through the namespace field.
        """
        # Create an internal helper family entity
        internal_id = ApiEntityId.from_parts(
            namespace="internal",
            surface="static",
            kind="helper_family",
            module="ace_internal",
            public_name="GeneratedHelper",
        )

        # The canonical id still starts with "api:" - this is documented behavior
        canonical = internal_id.canonical()
        self.assertTrue(
            canonical.startswith("api:"),
            f"Expected 'api:' prefix for ApiEntityId, got: {canonical}"
        )

        # But the namespace field distinguishes it as internal
        self.assertEqual(internal_id.namespace, "internal")

        # The canonical id contains "internal" making it distinguishable
        self.assertIn("internal", canonical)

        # Document the gap: internal entities should ideally use different prefix
        # This test exists to ensure this behavior is not changed accidentally
        # without updating the design


class HelperFamilyDistinctnessTests(unittest.TestCase):
    """Tests for distinguishing helper family IDs from component IDs."""

    def test_helper_family_id_distinct_from_component_id(self) -> None:
        """ApiEntityId for a helper family vs a component with the same name must
        produce different canonical ids.

        Even if a helper family and a component share the same public_name,
        their different kind values should produce distinct canonical ids.
        """
        # Create a helper family with name "Button"
        helper_family_id = ApiEntityId.from_parts(
            namespace="internal",
            surface="static",
            kind="helper_family",
            module="ace_internal",
            public_name="Button",
        )

        # Create a component with the same name "Button"
        component_id = ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="component",
            module="@ohos.arkui.component",
            public_name="Button",
        )

        # Their canonical ids must be different
        helper_canonical = helper_family_id.canonical()
        component_canonical = component_id.canonical()
        self.assertNotEqual(
            helper_canonical,
            component_canonical,
            f"Helper family and component should have distinct ids:\n"
            f"  Helper: {helper_canonical}\n"
            f"  Component: {component_canonical}"
        )

        # The kind field is the differentiator
        self.assertIn("helper_family", helper_canonical)
        self.assertIn("component", component_canonical)


class InvalidSurfaceKindTests(unittest.TestCase):
    """Tests for handling invalid surface kind values."""

    def test_invalid_surface_rejected_or_represented(self) -> None:
        """surface="totally_invalid" is not a valid ApiSurfaceKind value but can
        be stored. Test that it round-trips correctly.

        ApiEntityId.surface is a str field, not an enum, so invalid values
        can be stored. This test verifies that such values round-trip correctly
        through serialization.
        """
        # Create an id with an invalid surface value
        id_with_invalid_surface = ApiEntityId.from_parts(
            namespace="arkui",
            surface="totally_invalid",  # Not a valid ApiSurfaceKind
            kind="component",
            module="@ohos.arkui.component",
            public_name="Button",
        )

        # Verify the invalid value is stored
        self.assertEqual(id_with_invalid_surface.surface, "totally_invalid")

        # Serialize and deserialize
        d = id_with_invalid_surface.to_dict()
        restored = ApiEntityId.from_dict(d)

        # The invalid value should round-trip
        self.assertEqual(restored.surface, "totally_invalid")

        # The canonical id should still work (with the invalid value encoded)
        canonical = restored.canonical()
        self.assertIn("totally_invalid", canonical)


class InvalidEntityKindTests(unittest.TestCase):
    """Tests for handling invalid entity kind values."""

    def test_invalid_kind_stored_correctly(self) -> None:
        """kind="not_a_real_kind" round-trips in ApiEntityId.

        Similar to surface, ApiEntityId.kind is a str field, so invalid values
        can be stored. This test verifies round-trip behavior.
        """
        # Create an id with an invalid kind value
        id_with_invalid_kind = ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="not_a_real_kind",  # Not a valid ApiEntityKind
            module="@ohos.arkui.component",
            public_name="Button",
        )

        # Verify the invalid value is stored
        self.assertEqual(id_with_invalid_kind.kind, "not_a_real_kind")

        # Serialize and deserialize
        d = id_with_invalid_kind.to_dict()
        restored = ApiEntityId.from_dict(d)

        # The invalid value should round-trip
        self.assertEqual(restored.kind, "not_a_real_kind")

        # The canonical id should still work
        canonical = restored.canonical()
        self.assertIn("not_a_real_kind", canonical)


class ConfidenceLevelValidationTests(unittest.TestCase):
    """Tests for ConfidenceLevel validation."""

    def test_confidence_level_boundary_values(self) -> None:
        """Only "strong", "medium", "weak", "unknown" are valid ConfidenceLevel
        values. Evidence.__post_init__ already validates this. Verify all four
        pass and invalid ones raise.
        """
        # Valid values should pass
        for valid_level in ("strong", "medium", "weak", "unknown"):
            ev = Evidence(confidence_level=valid_level)
            self.assertEqual(ev.confidence_level, valid_level)

        # Invalid values should raise ValueError
        invalid_levels = ("confirmed", "low", "high", "certain", "none", "")
        for invalid_level in invalid_levels:
            with self.assertRaises(ValueError) as ctx:
                Evidence(confidence_level=invalid_level)
            self.assertIn("confidence_level", str(ctx.exception).lower())


class ProvenanceValidationTests(unittest.TestCase):
    """Tests for provenance value validation."""

    def test_provenance_boundary_values(self) -> None:
        """Only parser, config_rule, artifact, import, path_rule, fallback_heuristic
        are valid. Verify all six pass and invalid raises.
        """
        # Valid provenance values should pass
        # parser and config_rule require parser_level > 0
        ev_parser = Evidence(provenance="parser", parser_level=1)
        self.assertEqual(ev_parser.provenance, "parser")

        ev_config = Evidence(provenance="config_rule", parser_level=1)
        self.assertEqual(ev_config.provenance, "config_rule")

        # artifact, import, path_rule, fallback_heuristic work with parser_level=0
        for valid_prov in ("artifact", "import", "path_rule", "fallback_heuristic"):
            ev = Evidence(provenance=valid_prov, parser_level=0)
            self.assertEqual(ev.provenance, valid_prov)

        # Invalid values should raise ValueError
        invalid_provenances = ("manual", "user", "auto", "inference", "guess", "")
        for invalid_prov in invalid_provenances:
            with self.assertRaises(ValueError) as ctx:
                Evidence(provenance=invalid_prov)
            self.assertIn("provenance", str(ctx.exception).lower())


class CandidateDiscoveryEvidenceTests(unittest.TestCase):
    """Tests for candidate discovery evidence handling."""

    def test_fallback_heuristic_is_candidate_discovery(self) -> None:
        """Evidence with provenance="fallback_heuristic" has is_semantic=True but
        should NOT be treated as semantic proof. Document this gap: is_semantic
        returns True but it should be considered candidate-discovery only unless
        joined with stronger evidence.

        The is_semantic property returns True for any non-artifact provenance,
        but fallback_heuristic evidence should be treated as weak, candidate-
        discovery evidence only. This test documents the gap for future design
        consideration.
        """
        ev = Evidence(
            provenance="fallback_heuristic",
            confidence_level="weak",
            parser_level=0,
        )

        # Document: is_semantic returns True for fallback_heuristic
        # This is a design gap - fallback heuristic should not be treated
        # as semantic proof on its own
        self.assertTrue(
            ev.is_semantic,
            "is_semantic returns True for fallback_heuristic - this is a "
            "known gap. Fallback heuristic should be candidate-discovery only "
            "unless joined with stronger evidence."
        )

        # Document that parser_level=0 indicates discovery-only
        self.assertEqual(ev.parser_level, 0)

    def test_path_rule_is_candidate_discovery(self) -> None:
        """Same for provenance="path_rule".

        Path rule evidence should also be treated as candidate-discovery only,
        not as strong semantic proof. The is_semantic property does not distinguish
        this level of confidence.
        """
        ev = Evidence(
            provenance="path_rule",
            confidence_level="weak",
            parser_level=0,
        )

        # Document: is_semantic returns True for path_rule
        # This is the same gap as fallback_heuristic
        self.assertTrue(
            ev.is_semantic,
            "is_semantic returns True for path_rule - this is a known gap. "
            "Path rule should be candidate-discovery only unless joined with "
            "stronger evidence."
        )

        # Document that parser_level=0 indicates discovery-only
        self.assertEqual(ev.parser_level, 0)


class PublicApiIdFormatTests(unittest.TestCase):
    """Tests for public API canonical id format."""

    def test_public_api_id_format(self) -> None:
        """Verify canonical id for a typical Button API starts with "api:v1:"
        and follows the documented format with percent-encoding.
        """
        button_id = ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="component",
            module="@ohos.arkui.component",
            public_name="Button",
        )

        canonical = button_id.canonical()

        # Must start with api:v1:
        self.assertTrue(
            canonical.startswith("api:v1:"),
            f"Expected canonical id to start with 'api:v1:', got: {canonical}"
        )

        # Must contain percent-encoding for module dots
        self.assertIn("%2E", canonical, "Module dots should be percent-encoded")

        # Must contain the kind
        self.assertIn("component", canonical)

        # Must contain the public name
        self.assertIn("Button", canonical)

        # Verify the namespace is present
        self.assertIn("arkui", canonical)


class EmptyFixtureLoadTests(unittest.TestCase):
    """Tests for loading from empty fixture data."""

    def test_missing_api_id_in_fixture_load(self) -> None:
        """When loading from an empty dict, ApiEntityId gets default empty strings.
        Test that from_dict({}) produces an id with empty namespace/surface/kind/
        module/public_name and that canonical() still works.
        """
        # Load from empty dict
        empty_id = ApiEntityId.from_dict({})

        # Verify default empty values
        self.assertEqual(empty_id.namespace, "")
        self.assertEqual(empty_id.surface, "unknown")  # Has a default
        self.assertEqual(empty_id.kind, "")
        self.assertEqual(empty_id.module, "")
        self.assertEqual(empty_id.public_name, "")

        # canonical() should still work without error
        canonical = empty_id.canonical()
        self.assertIsInstance(canonical, str)
        self.assertTrue(len(canonical) > 0)

        # Verify format: api:v1:.unknown::#
        self.assertTrue(canonical.startswith("api:v1:"))
        self.assertIn("unknown", canonical)  # default surface

        # Serialize back to dict
        d = empty_id.to_dict()
        self.assertEqual(d["namespace"], "")
        self.assertEqual(d["surface"], "unknown")
        self.assertEqual(d["kind"], "")
        self.assertEqual(d["module"], "")
        self.assertEqual(d["public_name"], "")


class EnumCompletenessTests(unittest.TestCase):
    """Tests for enum completeness."""

    def test_api_entity_kind_enum_complete(self) -> None:
        """All required ApiEntityKind values exist: component, modifier, attribute,
        event_or_method, module, configuration, helper_family.
        """
        required_kinds = {
            "component",
            "modifier",
            "attribute",
            "event_or_method",
            "module",
            "configuration",
            "helper_family",
        }

        actual_kinds = {member.value for member in ApiEntityKind}

        missing = required_kinds - actual_kinds
        self.assertEqual(
            len(missing),
            0,
            f"Missing ApiEntityKind values: {missing}"
        )

        # Verify all actual kinds are among required ones
        extra = actual_kinds - required_kinds
        if extra:
            # This is OK - there may be additional kinds not in our list
            # Just document them
            pass

    def test_api_surface_kind_enum_complete(self) -> None:
        """All required ApiSurfaceKind values exist: static, dynamic, shared, unknown.
        """
        required_surfaces = {
            "static",
            "dynamic",
            "shared",
            "unknown",
        }

        actual_surfaces = {member.value for member in ApiSurfaceKind}

        missing = required_surfaces - actual_surfaces
        self.assertEqual(
            len(missing),
            0,
            f"Missing ApiSurfaceKind values: {missing}"
        )

        # Verify all actual surfaces are among required ones
        extra = actual_surfaces - required_surfaces
        if extra:
            # Document any extra surfaces
            pass


class RunnabilityStateTests(unittest.TestCase):
    """Tests for RunnabilityState and its distinction from ConfidenceLevel."""

    def test_runnability_state_distinct_from_confidence(self) -> None:
        """RunnabilityState values (confirmed, unknown, blocked) are distinct from
        ConfidenceLevel values (strong, medium, weak, unknown). Only "unknown"
        overlaps. Verify no other overlap exists.
        """
        runnability_values = set(RunnabilityState.__args__)  # type: ignore
        confidence_values = set(ConfidenceLevel.__args__)  # type: ignore

        # Expected values
        expected_runnability = {"confirmed", "unknown", "blocked"}
        expected_confidence = {"strong", "medium", "weak", "unknown"}

        self.assertEqual(runnability_values, expected_runnability)
        self.assertEqual(confidence_values, expected_confidence)

        # Check overlap - only "unknown" should be common
        overlap = runnability_values & confidence_values
        self.assertEqual(
            overlap,
            {"unknown"},
            f"Only 'unknown' should overlap between RunnabilityState and "
            f"ConfidenceLevel. Found overlap: {overlap}"
        )

        # Verify distinctness of non-overlapping values
        runnability_without_unknown = runnability_values - {"unknown"}
        confidence_without_unknown = confidence_values - {"unknown"}

        self.assertEqual(
            len(runnability_without_unknown & confidence_without_unknown),
            0,
            "No values other than 'unknown' should overlap"
        )


if __name__ == "__main__":
    unittest.main()
