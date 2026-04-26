"""
Tests for Phase 5 P5-001: Evidence Kind Propagation.

Verifies that evidence_kinds from consumer_semantics flow into TestFileIndex
and are preserved in to_dict/from_dict round-trip.

Run:
    python3 -m unittest tests.test_evidence_kind_propagation -v
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arkui_xts_selector.cli import TestFileIndex, TestProjectIndex, ensure_project_search_summary
from arkui_xts_selector.consumer_semantics import extract_consumer_semantics


class EvidenceKindPropagationTests(unittest.TestCase):
    """Test that evidence_kinds flow from consumer_semantics into TestFileIndex."""

    def test_import_evidence_kind_in_test_file_index(self) -> None:
        """Import evidence kind should be preserved."""
        semantics = extract_consumer_semantics("import { Button } from '@ohos.arkui.component'")
        index = TestFileIndex(
            relative_path="test.ts",
            surface="static",
            imports=semantics.imports,
            imported_symbols=semantics.imported_symbols,
            identifier_calls=semantics.identifier_calls,
            member_calls=semantics.member_calls,
            type_member_calls=semantics.type_member_calls,
            typed_field_accesses=semantics.typed_field_accesses,
            typed_modifier_bases=semantics.typed_modifier_bases,
            words=semantics.words,
            evidence_kinds=semantics.evidence_kinds,
        )
        self.assertEqual(index.evidence_kinds.get("Button"), "import")

    def test_type_member_call_evidence_kind_in_test_file_index(self) -> None:
        """Type member call evidence kind should be preserved."""
        semantics = extract_consumer_semantics("ButtonAttribute.role()")
        index = TestFileIndex(
            relative_path="test.ts",
            surface="static",
            imports=semantics.imports,
            imported_symbols=semantics.imported_symbols,
            identifier_calls=semantics.identifier_calls,
            member_calls=semantics.member_calls,
            type_member_calls=semantics.type_member_calls,
            typed_field_accesses=semantics.typed_field_accesses,
            typed_modifier_bases=semantics.typed_modifier_bases,
            words=semantics.words,
            evidence_kinds=semantics.evidence_kinds,
        )
        self.assertEqual(index.evidence_kinds.get("ButtonAttribute.role"), "type_member_call")

    def test_field_read_evidence_kind_in_test_file_index(self) -> None:
        """Field read evidence kind should be preserved."""
        semantics = extract_consumer_semantics("const slider: Slider = { padding: 10 }")
        index = TestFileIndex(
            relative_path="test.ts",
            surface="static",
            imports=semantics.imports,
            imported_symbols=semantics.imported_symbols,
            identifier_calls=semantics.identifier_calls,
            member_calls=semantics.member_calls,
            type_member_calls=semantics.type_member_calls,
            typed_field_accesses=semantics.typed_field_accesses,
            typed_modifier_bases=semantics.typed_modifier_bases,
            words=semantics.words,
            evidence_kinds=semantics.evidence_kinds,
        )
        self.assertEqual(index.evidence_kinds.get("Slider.padding"), "field_write")

    def test_event_type_field_evidence_kind_in_test_file_index(self) -> None:
        """EventType field evidence kind should be preserved."""
        semantics = extract_consumer_semantics("ClickEvent.globalX")
        index = TestFileIndex(
            relative_path="test.ts",
            surface="static",
            imports=semantics.imports,
            imported_symbols=semantics.imported_symbols,
            identifier_calls=semantics.identifier_calls,
            member_calls=semantics.member_calls,
            type_member_calls=semantics.type_member_calls,
            typed_field_accesses=semantics.typed_field_accesses,
            typed_modifier_bases=semantics.typed_modifier_bases,
            words=semantics.words,
            evidence_kinds=semantics.evidence_kinds,
        )
        self.assertEqual(index.evidence_kinds.get("ClickEvent.globalX"), "event_type_field")

    def test_empty_evidence_kinds_for_empty_text(self) -> None:
        """Empty text should produce empty evidence_kinds."""
        semantics = extract_consumer_semantics("")
        index = TestFileIndex(
            relative_path="test.ts",
            surface="static",
            imports=semantics.imports,
            imported_symbols=semantics.imported_symbols,
            identifier_calls=semantics.identifier_calls,
            member_calls=semantics.member_calls,
            type_member_calls=semantics.type_member_calls,
            typed_field_accesses=semantics.typed_field_accesses,
            typed_modifier_bases=semantics.typed_modifier_bases,
            words=semantics.words,
            evidence_kinds=semantics.evidence_kinds,
        )
        self.assertEqual(index.evidence_kinds, {})

    def test_to_dict_preserves_evidence_kinds(self) -> None:
        """to_dict should include evidence_kinds."""
        semantics = extract_consumer_semantics("import { Button } from '@ohos.arkui.component'")
        index = TestFileIndex(
            relative_path="test.ts",
            surface="static",
            imports=semantics.imports,
            imported_symbols=semantics.imported_symbols,
            identifier_calls=semantics.identifier_calls,
            member_calls=semantics.member_calls,
            type_member_calls=semantics.type_member_calls,
            typed_field_accesses=semantics.typed_field_accesses,
            typed_modifier_bases=semantics.typed_modifier_bases,
            words=semantics.words,
            evidence_kinds=semantics.evidence_kinds,
        )
        d = index.to_dict()
        self.assertIn("evidence_kinds", d)
        self.assertEqual(d["evidence_kinds"].get("Button"), "import")

    def test_from_dict_restores_evidence_kinds(self) -> None:
        """from_dict should restore evidence_kinds."""
        semantics = extract_consumer_semantics("ButtonAttribute.role()")
        index = TestFileIndex(
            relative_path="test.ts",
            surface="static",
            imports=semantics.imports,
            imported_symbols=semantics.imported_symbols,
            identifier_calls=semantics.identifier_calls,
            member_calls=semantics.member_calls,
            type_member_calls=semantics.type_member_calls,
            typed_field_accesses=semantics.typed_field_accesses,
            typed_modifier_bases=semantics.typed_modifier_bases,
            words=semantics.words,
            evidence_kinds=semantics.evidence_kinds,
        )
        d = index.to_dict()
        restored = TestFileIndex.from_dict(d)
        self.assertEqual(restored.evidence_kinds.get("ButtonAttribute.role"), "type_member_call")

    def test_round_trip_preserves_evidence_kinds(self) -> None:
        """Full round-trip should preserve evidence_kinds."""
        semantics = extract_consumer_semantics(
            "import { Button } from '@ohos.arkui.component'\nButtonAttribute.role()"
        )
        index = TestFileIndex(
            relative_path="test.ts",
            surface="static",
            imports=semantics.imports,
            imported_symbols=semantics.imported_symbols,
            identifier_calls=semantics.identifier_calls,
            member_calls=semantics.member_calls,
            type_member_calls=semantics.type_member_calls,
            typed_field_accesses=semantics.typed_field_accesses,
            typed_modifier_bases=semantics.typed_modifier_bases,
            words=semantics.words,
            evidence_kinds=semantics.evidence_kinds,
        )
        d = index.to_dict()
        restored = TestFileIndex.from_dict(d)
        self.assertEqual(restored.evidence_kinds.get("Button"), "import")
        self.assertEqual(restored.evidence_kinds.get("ButtonAttribute.role"), "type_member_call")


class EvidenceKindProjectAggregationTests(unittest.TestCase):
    """Test that evidence_kinds aggregate from files into TestProjectIndex.search_evidence_kinds."""

    def _make_file_index(self, text: str, path: str = "test.ts") -> TestFileIndex:
        semantics = extract_consumer_semantics(text)
        return TestFileIndex(
            relative_path=path,
            surface="static",
            imports=semantics.imports,
            imported_symbols=semantics.imported_symbols,
            identifier_calls=semantics.identifier_calls,
            member_calls=semantics.member_calls,
            type_member_calls=semantics.type_member_calls,
            typed_field_accesses=semantics.typed_field_accesses,
            typed_modifier_bases=semantics.typed_modifier_bases,
            words=semantics.words,
            evidence_kinds=semantics.evidence_kinds,
        )

    def test_project_aggregates_evidence_kinds_from_files(self) -> None:
        """ensure_project_search_summary must merge evidence_kinds from all files."""
        f1 = self._make_file_index("import { Button } from '@ohos.arkui.component'", "f1.ts")
        f2 = self._make_file_index("ButtonAttribute.role()", "f2.ts")
        project = TestProjectIndex(
            relative_root="test/xts/acts/arkui/button_static",
            test_json="test/xts/acts/arkui/button_static/Test.json",
            bundle_name=None,
            path_key="test/xts/acts/arkui/button_static",
            files=[f1, f2],
        )
        ensure_project_search_summary(project)
        self.assertEqual(project.search_evidence_kinds.get("Button"), "import")
        self.assertEqual(project.search_evidence_kinds.get("ButtonAttribute.role"), "type_member_call")

    def test_project_evidence_kinds_round_trip(self) -> None:
        """Project evidence_kinds survive to_dict/from_dict round-trip."""
        f1 = self._make_file_index("ButtonAttribute.role()", "f1.ts")
        project = TestProjectIndex(
            relative_root="test/xts/acts/arkui/button_static",
            test_json="test/xts/acts/arkui/button_static/Test.json",
            bundle_name=None,
            path_key="test/xts/acts/arkui/button_static",
            files=[f1],
        )
        ensure_project_search_summary(project)
        d = project.to_dict()
        restored = TestProjectIndex.from_dict(d)
        self.assertEqual(restored.search_evidence_kinds.get("ButtonAttribute.role"), "type_member_call")

    def test_project_evidence_kinds_empty_when_no_files(self) -> None:
        """Project with no files should have empty search_evidence_kinds."""
        project = TestProjectIndex(
            relative_root="test/xts/acts/arkui/empty",
            test_json="test/xts/acts/arkui/empty/Test.json",
            bundle_name=None,
            path_key="test/xts/acts/arkui/empty",
            files=[],
        )
        ensure_project_search_summary(project)
        self.assertEqual(project.search_evidence_kinds, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
