"""Tests for provenance tracking and caps in pr_resolver."""

from __future__ import annotations

from arkui_xts_selector.indexing.pr_resolver import (
    PrResolveEntry,
    PrResolveResult,
)


class TestProvenanceFields:
    def test_default_dropped_count(self):
        result = PrResolveResult()
        assert result.dropped_count == 0

    def test_default_provenance_empty(self):
        result = PrResolveResult()
        assert result.provenance == ()

    def test_provenance_with_trace(self):
        trace = ({"file": "button.cpp", "resolved_via": "family_match"},)
        result = PrResolveResult(provenance=trace)
        assert len(result.provenance) == 1
        assert result.provenance[0]["file"] == "button.cpp"

    def test_dropped_count_set(self):
        result = PrResolveResult(dropped_count=5)
        assert result.dropped_count == 5

    def test_frozen(self):
        result = PrResolveResult()
        try:
            result.dropped_count = 10
            assert False, "Should be frozen"
        except AttributeError:
            pass

    def test_backward_compat_no_new_fields(self):
        """Existing code creating PrResolveResult still works without new fields."""
        result = PrResolveResult(
            entries=(
                PrResolveEntry(
                    changed_file="a.cpp", affected_apis=(), consumer_projects=()
                ),
            ),
        )
        assert result.dropped_count == 0
        assert result.provenance == ()
