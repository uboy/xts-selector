"""Tests for Session 1: summary buckets, provenance in reasons, dropped targets."""

from __future__ import annotations


class TestSummaryBuckets:
    def test_buckets_populated_from_provenance(self):
        from arkui_xts_selector.batch_validate import _summarize_result

        result = {
            "pr_number": 1,
            "status": "ok",
            "graph_selection": {
                "entries": [
                    {
                        "changed_file": "x.cpp",
                        "affected_apis": [],
                        "consumer_projects": ["t1"],
                        "selection_reasons": [],
                        "impact_candidates": [],
                        "parser_level": 0,
                    },
                ],
                "provenance": [
                    {
                        "action": "target_ranking",
                        "ranking": {
                            "must_run": ["t1"],
                            "recommended": ["t2", "t3"],
                            "fallback": [],
                            "dropped_count": 5,
                            "total": 3,
                        },
                    },
                ],
            },
        }
        summary = _summarize_result(result)
        assert summary["buckets"] == {
            "must_run": 1,
            "recommended": 2,
            "fallback": 0,
            "dropped": 5,
        }

    def test_buckets_empty_when_no_ranking(self):
        from arkui_xts_selector.batch_validate import _summarize_result

        result = {
            "pr_number": 2,
            "status": "ok",
            "graph_selection": {"entries": [], "provenance": []},
        }
        summary = _summarize_result(result)
        assert summary["buckets"] == {
            "must_run": 0,
            "recommended": 0,
            "fallback": 0,
            "dropped": 0,
        }

    def test_buckets_zero_when_no_provenance_key(self):
        from arkui_xts_selector.batch_validate import _summarize_result

        result = {
            "pr_number": 3,
            "status": "ok",
            "graph_selection": {"entries": []},
        }
        summary = _summarize_result(result)
        assert summary["buckets"]["must_run"] == 0
