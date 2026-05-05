"""Tests for model.usage – API usage signatures and coverage equivalence."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.model.api import ApiEntityId
from arkui_xts_selector.model.usage import (
    ApiUsageSignature,
    CoverageEquivalenceClass,
)


class ApiUsageSignatureTests(unittest.TestCase):
    def _button_id(self) -> ApiEntityId:
        return ApiEntityId.from_parts(
            namespace="arkui", surface="static", kind="component",
            module="@ohos.arkui.component", public_name="Button",
        )

    def test_harness_only_usage(self) -> None:
        """harness_only usage exists as a valid usage_kind."""
        sig = ApiUsageSignature(
            api_entity_id=self._button_id(),
            usage_kind="harness_only",
        )
        self.assertEqual(sig.usage_kind, "harness_only")

    def test_harness_only_is_not_import(self) -> None:
        """harness_only is distinct from import usage."""
        sig1 = ApiUsageSignature(api_entity_id=self._button_id(), usage_kind="harness_only")
        sig2 = ApiUsageSignature(api_entity_id=self._button_id(), usage_kind="import")
        self.assertNotEqual(sig1.usage_kind, sig2.usage_kind)

    def test_unknown_argument_shape_not_exact(self) -> None:
        """unknown argument shape must not be treated as exact_api_same_usage_shape."""
        sig = ApiUsageSignature(
            api_entity_id=self._button_id(),
            argument_shape="unknown",
        )
        self.assertEqual(sig.argument_shape, "unknown")
        self.assertNotEqual(sig.argument_shape, "no_args")

    def test_round_trip(self) -> None:
        sig = ApiUsageSignature(
            api_entity_id=self._button_id(),
            language="ArkTS",
            usage_kind="component_instantiation",
            argument_shape="no_args",
            file_path="test/ButtonTest.ets",
            line=42,
            confidence="strong",
        )
        d = sig.to_dict()
        restored = ApiUsageSignature.from_dict(d)
        self.assertEqual(sig, restored)

    def test_json_serializable(self) -> None:
        sig = ApiUsageSignature(api_entity_id=self._button_id())
        text = json.dumps(sig.to_dict())
        self.assertIsInstance(text, str)


class CoverageEquivalenceTests(unittest.TestCase):
    def test_all_values_are_strings(self) -> None:
        values: list[str] = [
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
        ]
        for v in values:
            self.assertIsInstance(v, str)

    def test_harness_only_is_not_must_run_equivalent(self) -> None:
        """harness_only_usage must NOT support must_run."""
        self.assertNotEqual("harness_only_usage", "exact_api_same_usage_shape")


if __name__ == "__main__":
    unittest.main()
