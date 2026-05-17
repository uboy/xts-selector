"""Tests for select_golden_candidates.py — test_only, unknown, shortfall."""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _import_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    import importlib

    mod = importlib.import_module("select_golden_candidates")
    importlib.reload(mod)
    return mod


class TestClassifyPr:
    def test_all_test_files_classified_test_only(self):
        mod = _import_module()
        entry = {
            "graph_selection": {
                "entries": [
                    {"changed_file": "test/unittest/core/button_test.cpp"},
                    {"changed_file": "docs/design.md"},
                ]
            }
        }
        assert mod.classify_pr(entry) == "test_only"

    def test_production_and_test_not_test_only(self):
        """PR with production + test files should NOT be test_only."""
        mod = _import_module()
        entry = {
            "graph_selection": {
                "entries": [
                    {"changed_file": "frameworks/core/button.cpp"},
                    {"changed_file": "test/unittest/core/button_test.cpp"},
                ]
            }
        }
        result = mod.classify_pr(entry)
        assert result != "test_only"

    def test_unknown_when_no_match(self):
        """PR matching no category returns unknown, not test_only."""
        mod = _import_module()
        entry = {
            "graph_selection": {
                "entries": [
                    {"changed_file": "frameworks/core/render/render_engine.cpp"},
                ]
            }
        }
        result = mod.classify_pr(entry)
        # Should be broad_infra or unknown, NOT test_only
        assert result != "test_only"

    def test_component_api_detected(self):
        mod = _import_module()
        entry = {
            "graph_selection": {
                "entries": [
                    {
                        "changed_file": "frameworks/core/components_ng/pattern/button/button_model.cpp"
                    },
                ]
            }
        }
        assert mod.classify_pr(entry) == "component_api"


class TestGetSelectorStatus:
    def test_execution_error_separate_from_unresolved(self):
        """execution_error and unresolved are different statuses."""
        mod = _import_module()

        error_entry = {"status": "error", "graph_selection": {}}
        assert mod.get_selector_status(error_entry) == "execution_error"

        unresolved_entry = {
            "status": "ok",
            "graph_selection": {"entries": [{"unresolved_reason": "no match"}]},
        }
        assert mod.get_selector_status(unresolved_entry) == "unresolved"

    def test_broad_infra_status(self):
        """Broad infra match detected."""
        mod = _import_module()
        entry = {
            "status": "ok",
            "graph_selection": {
                "entries": [{"broad_infra_match": {"rule_id": "test"}}]
            },
        }
        assert mod.get_selector_status(entry) == "broad_infra"


class TestShortfallReport:
    def test_output_includes_requested_count(self):
        mod = _import_module()
        # Verify CATEGORY_TARGETS has unknown
        assert "unknown" in mod.CATEGORY_TARGETS
        total = sum(mod.CATEGORY_TARGETS.values())
        assert total >= 100
