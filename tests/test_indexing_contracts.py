"""Tests for indexing contract types.

Tests verify:
- ParserResult level → provenance mapping
- SymbolDiscovery to Evidence conversion
- Indexer entry round-trip serialization
- Artifact evidence is runnability-only
- Import boundaries are respected
"""
from __future__ import annotations

import ast
import importlib

import pytest

from arkui_xts_selector.indexing import (
    AceIndexEntry,
    AceIndexResult,
    AceSourceEntry,
    ArtifactEntry,
    ArtifactIndexResult,
    ParserResult,
    SdkIndexEntry,
    SdkIndexResult,
    SymbolDiscovery,
    XtsIndexResult,
    XtsProjectEntry,
    _level_to_provenance,
)
from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef


class TestParserResultLevelMapping:
    """Test parser_level → provenance mapping."""

    def test_parser_result_level_0_is_fallback(self):
        """parser_level=0 → provenance='fallback_heuristic'."""
        result = ParserResult(
            file_path="/path/to/file.ets",
            parser_name="test-parser",
            parser_level=0,
        )
        evidence = result.to_evidence()
        assert evidence.provenance == "fallback_heuristic"

    def test_parser_result_level_1_is_path_rule(self):
        """parser_level=1 → provenance='path_rule'."""
        result = ParserResult(
            file_path="/path/to/file.ets",
            parser_name="test-parser",
            parser_level=1,
        )
        evidence = result.to_evidence()
        assert evidence.provenance == "path_rule"

    def test_parser_result_level_2_is_import(self):
        """parser_level=2 → provenance='import'."""
        result = ParserResult(
            file_path="/path/to/file.ets",
            parser_name="test-parser",
            parser_level=2,
        )
        evidence = result.to_evidence()
        assert evidence.provenance == "import"

    def test_parser_result_level_3_is_parser(self):
        """parser_level=3 → provenance='parser'."""
        result = ParserResult(
            file_path="/path/to/file.ets",
            parser_name="test-parser",
            parser_level=3,
        )
        evidence = result.to_evidence()
        assert evidence.provenance == "parser"


class TestSymbolDiscoveryEvidence:
    """Test SymbolDiscovery → Evidence conversion."""

    def test_symbol_discovery_to_evidence_fallback_weak(self):
        """level 0 → confidence='weak'."""
        result = ParserResult(
            file_path="/path/to/file.ets",
            parser_name="test-parser",
            parser_level=0,
        )
        symbol = SymbolDiscovery(
            symbol="Text",
            line=10,
            kind="call",
            confidence="strong",  # will be downgraded to weak for fallback
        )
        evidence = symbol.to_evidence(result)
        assert evidence.confidence_level == "weak"
        assert evidence.provenance == "fallback_heuristic"

    def test_symbol_discovery_to_evidence_parser_strong(self):
        """level 3, kind='call' → provenance='parser'."""
        result = ParserResult(
            file_path="/path/to/file.ets",
            parser_name="tree-sitter-cpp",
            parser_level=3,
        )
        symbol = SymbolDiscovery(
            symbol="Text",
            line=10,
            kind="call",
            confidence="strong",
        )
        evidence = symbol.to_evidence(result)
        assert evidence.provenance == "parser"
        assert evidence.confidence_level == "strong"

    def test_symbol_discovery_import_level_non_import_kind(self):
        """level 2 (import) with non-import kind → confidence='medium'."""
        result = ParserResult(
            file_path="/path/to/file.ets",
            parser_name="import-parser",
            parser_level=2,
        )
        symbol = SymbolDiscovery(
            symbol="Text",
            line=10,
            kind="call",  # not import
            confidence="unknown",
        )
        evidence = symbol.to_evidence(result)
        assert evidence.provenance == "import"
        assert evidence.confidence_level == "medium"


class TestSdkIndexer:
    """Test SDK indexer types."""

    def test_sdk_index_entry_round_trip(self):
        """SdkIndexEntry to_dict/from_dict round-trip."""
        api_id = ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="component",
            module="ohos.arkui",
            public_name="Text",
        )
        declaration = ApiDeclarationRef(
            declaration_id=api_id.canonical(),
            file_path="/path/to/Text.ets",
            module="ohos.arkui",
            export_name="Text",
            line=42,
            parser_level=3,
        )
        entry = SdkIndexEntry(
            api_id=api_id,
            declaration=declaration,
        )
        restored = SdkIndexEntry.from_dict(entry.to_dict())
        assert restored == entry


class TestAceIndexer:
    """Test AceEngine indexer types."""

    def test_ace_source_entry_round_trip(self):
        """AceSourceEntry round-trip."""
        entry = AceSourceEntry(
            file_path="/path/to/Modifier.ets",
            family="generic",
            surface="static",
            provides_modifiers=("width", "height"),
            implements_components=(),
        )
        restored = AceSourceEntry.from_dict(entry.to_dict())
        assert restored == entry


class TestXtsIndexer:
    """Test XTS indexer types."""

    def test_xts_project_entry_round_trip(self):
        """XtsProjectEntry round-trip."""
        entry = XtsProjectEntry(
            project_id="ActsButtonTest",
            project_path="/acts/button",
            test_files=("test1.ets", "test2.ets"),
            target_id="ActsButtonTest",
        )
        restored = XtsProjectEntry.from_dict(entry.to_dict())
        assert restored == entry


class TestArtifactIndexer:
    """Test artifact indexer types."""

    def test_artifact_entry_always_artifact_provenance(self):
        """ArtifactEntry.provenance is always 'artifact'."""
        entry = ArtifactEntry(
            artifact_name="ActsButtonTest.hap",
            target_id="ActsButtonTest",
            artifact_type="hap",
        )
        assert entry.provenance == "artifact"

    def test_artifact_index_evidence_is_runnability_only(self):
        """ArtifactIndexResult.to_evidence() produces is_artifact=True, is_semantic=False."""
        result = ArtifactIndexResult(
            entries=(
                ArtifactEntry(
                    artifact_name="ActsButtonTest.hap",
                    target_id="ActsButtonTest",
                    artifact_type="hap",
                ),
            ),
            source="build_manifest",
        )
        evidence = result.to_evidence()
        assert evidence.is_artifact is True
        assert evidence.is_semantic is False
        assert evidence.provenance == "artifact"


class TestParserResultEvidence:
    """Test ParserResult.to_evidence()."""

    def test_parser_result_to_evidence(self):
        """ParserResult.to_evidence() creates valid Evidence."""
        result = ParserResult(
            file_path="/path/to/file.ets",
            language="ArkTS",
            parser_name="tree-sitter-arkts",
            parser_level=3,
            discovered_symbols=(
                SymbolDiscovery(
                    symbol="Text",
                    line=10,
                    kind="component_usage",
                ),
            ),
            limitations=("no-nested-support",),
            parse_time_ms=12.5,
        )
        evidence = result.to_evidence()
        assert evidence.source == "tree-sitter-arkts"
        assert evidence.file_path == "/path/to/file.ets"
        assert evidence.parser_level == 3
        assert evidence.provenance == "parser"
        assert evidence.limitations == ("no-nested-support",)


class TestImportBoundary:
    """Verify indexing module respects import boundaries."""

    def test_import_boundary(self):
        """indexing module imports only from model and standard library (verify no cli/reporting imports)."""
        # Get the indexing module directory
        import arkui_xts_selector.indexing as indexing_module
        import pathlib

        module_dir = pathlib.Path(indexing_module.__file__).parent
        assert module_dir.exists()

        # Collect all Python files in the indexing module
        py_files = list(module_dir.glob("*.py"))

        # Check imports in each file
        all_import_names = []
        for py_file in py_files:
            # Parse the file source
            with open(py_file, encoding="utf-8") as f:
                source = f.read()

            # Parse into AST
            tree = ast.parse(source)

            # Check imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        all_import_names.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        all_import_names.append(f"{module}.{alias.name}")

        # Verify no imports from cli, reporting, or other non-model modules
        forbidden_prefixes = ("arkui_xts_selector.cli", "arkui_xts_selector.report")
        for imp in all_import_names:
            for forbidden in forbidden_prefixes:
                assert not imp.startswith(forbidden), f"Import boundary violated: {imp}"

        # Verify imports from model are allowed (found in parser_contracts.py and artifact_indexer.py)
        # Note: relative imports show up as "model.evidence" not "arkui_xts_selector.model.evidence"
        model_imports = [imp for imp in all_import_names if imp.startswith("model.")]
        # We expect at least evidence model imports
        assert len(model_imports) > 0, "Expected imports from arkui_xts_selector.model (relative imports)"


class TestLevelToProvenance:
    """Test _level_to_provenance helper function."""

    def test_level_negative_defaults_to_fallback(self):
        """Negative level → fallback_heuristic."""
        assert _level_to_provenance(-1) == "fallback_heuristic"

    def test_level_zero_is_fallback(self):
        """Level 0 → fallback_heuristic."""
        assert _level_to_provenance(0) == "fallback_heuristic"

    def test_level_one_is_path_rule(self):
        """Level 1 → path_rule."""
        assert _level_to_provenance(1) == "path_rule"

    def test_level_two_is_import(self):
        """Level 2 → import."""
        assert _level_to_provenance(2) == "import"

    def test_level_three_is_parser(self):
        """Level 3 → parser."""
        assert _level_to_provenance(3) == "parser"

    def test_level_four_is_parser(self):
        """Level 4 (or higher) → parser."""
        assert _level_to_provenance(4) == "parser"


class TestIndexerResultSerialization:
    """Test indexer result round-trip serialization."""

    def test_sdk_index_result_round_trip(self):
        """SdkIndexResult to_dict/from_dict round-trip."""
        text_id = ApiEntityId.from_parts(
            namespace="arkui", surface="static",
            kind="component", module="ohos.arkui", public_name="Text",
        )
        button_id = ApiEntityId.from_parts(
            namespace="arkui", surface="static",
            kind="component", module="ohos.arkui", public_name="Button",
        )
        result = SdkIndexResult(
            entries=(
                SdkIndexEntry(
                    api_id=text_id,
                    declaration=ApiDeclarationRef(
                        declaration_id=text_id.canonical(),
                        file_path="/path/to/Text.ets",
                        export_name="Text",
                    ),
                ),
                SdkIndexEntry(
                    api_id=button_id,
                    declaration=ApiDeclarationRef(
                        declaration_id=button_id.canonical(),
                        file_path="/path/to/Button.ets",
                        export_name="Button",
                    ),
                ),
            ),
            index_time_ms=42.0,
            source="sdk_declaration_parser",
        )
        restored = SdkIndexResult.from_dict(result.to_dict())
        assert restored == result

    def test_ace_index_result_round_trip(self):
        """AceIndexResult to_dict/from_dict round-trip."""
        result = AceIndexResult(
            entries=(
                AceIndexEntry(
                    file_path="/path/to/Modifier.ets",
                    role="pattern",
                    family="generic",
                ),
            ),
            index_time_ms=15.0,
        )
        restored = AceIndexResult.from_dict(result.to_dict())
        assert restored == result

    def test_xts_index_result_round_trip(self):
        """XtsIndexResult to_dict/from_dict round-trip."""
        result = XtsIndexResult(
            entries=(
                XtsProjectEntry(
                    project_id="ActsButtonTest",
                    project_path="/acts/button",
                ),
            ),
            index_time_ms=8.0,
        )
        restored = XtsIndexResult.from_dict(result.to_dict())
        assert restored == result

    def test_artifact_index_result_round_trip(self):
        """ArtifactIndexResult to_dict/from_dict round-trip."""
        result = ArtifactIndexResult(
            entries=(
                ArtifactEntry(
                    artifact_name="ActsButtonTest.hap",
                    target_id="ActsButtonTest",
                    artifact_type="hap",
                ),
            ),
            index_time_ms=3.0,
        )
        restored = ArtifactIndexResult.from_dict(result.to_dict())
        assert restored == result
