"""Tests for audit recorder and analyzer (Phase 11, T11.12-T11.14)."""

from __future__ import annotations

import json
from datetime import date, timedelta


from arkui_xts_selector.audit.recorder import record_run, load_audit_entries
from arkui_xts_selector.audit.analyzer import compute_fn_rate, format_fn_rate_report


# ── Recorder tests ───────────────────────────────────────────────────


class TestRecorder:
    def test_record_creates_file(self, tmp_path):
        path = record_run(
            pr_number=123,
            selected=["test_a", "test_b"],
            ran=["test_a", "test_b", "test_x"],
            failed=["test_a", "test_x"],
            audit_dir=tmp_path,
        )
        assert path.exists()
        assert path.suffix == ".jsonl"

    def test_record_entry_fields(self, tmp_path):
        record_run(
            pr_number=456,
            selected=["test_a"],
            ran=["test_a", "test_b"],
            failed=["test_b"],
            audit_dir=tmp_path,
        )
        entries = load_audit_entries(tmp_path)
        assert len(entries) == 1
        e = entries[0]
        assert e["pr_number"] == 456
        assert e["selected"] == ["test_a"]
        assert e["ran"] == ["test_a", "test_b"]
        assert e["failed"] == ["test_b"]
        assert e["selected_caught"] == []
        assert e["missed_failures"] == ["test_b"]
        assert e["has_missed"] is True

    def test_record_no_missed(self, tmp_path):
        record_run(
            pr_number=789,
            selected=["test_a"],
            ran=["test_a", "test_b"],
            failed=["test_a"],
            audit_dir=tmp_path,
        )
        entries = load_audit_entries(tmp_path)
        assert entries[0]["missed_failures"] == []
        assert entries[0]["has_missed"] is False

    def test_record_with_selector_report(self, tmp_path):
        report = {
            "fallback_applied": True,
            "fallback_level": "rescue",
            "overall_false_negative_risk": "critical",
            "fallback_reason": "test",
        }
        record_run(1, [], [], [], selector_report=report, audit_dir=tmp_path)
        entries = load_audit_entries(tmp_path)
        assert entries[0]["fallback_applied"] is True
        assert entries[0]["selector_meta"]["fallback_level"] == "rescue"

    def test_multiple_entries_same_day(self, tmp_path):
        record_run(1, ["a"], ["a"], [], audit_dir=tmp_path)
        record_run(2, ["b"], ["b"], ["b"], audit_dir=tmp_path)
        record_run(3, ["c"], ["c", "d"], ["d"], audit_dir=tmp_path)
        entries = load_audit_entries(tmp_path)
        assert len(entries) == 3


# ── Load entries tests ───────────────────────────────────────────────


class TestLoadEntries:
    def test_empty_dir(self, tmp_path):
        entries = load_audit_entries(tmp_path)
        assert entries == []

    def test_days_filter(self, tmp_path):
        today = date.today()
        old_date = (today - timedelta(days=60)).isoformat()
        recent_date = today.isoformat()

        # Write old entry
        old_file = tmp_path / f"{old_date}.jsonl"
        old_file.write_text(json.dumps({"pr_number": 1, "timestamp": old_date}) + "\n")

        # Write recent entry
        recent_file = tmp_path / f"{recent_date}.jsonl"
        recent_file.write_text(
            json.dumps({"pr_number": 2, "timestamp": recent_date}) + "\n"
        )

        entries = load_audit_entries(tmp_path, days=30)
        assert len(entries) == 1
        assert entries[0]["pr_number"] == 2


# ── Analyzer tests ───────────────────────────────────────────────────


class TestAnalyzer:
    def test_empty_audit(self, tmp_path):
        report = compute_fn_rate(tmp_path)
        assert report.total_runs == 0
        assert report.fn_rate == 0.0

    def test_no_failures(self, tmp_path):
        record_run(1, ["a"], ["a"], [], audit_dir=tmp_path)
        record_run(2, ["b"], ["b"], [], audit_dir=tmp_path)
        report = compute_fn_rate(tmp_path)
        assert report.total_runs == 2
        assert report.runs_with_failure == 0
        assert report.fn_rate == 0.0

    def test_all_caught(self, tmp_path):
        record_run(1, ["a", "b"], ["a", "b"], ["a"], audit_dir=tmp_path)
        report = compute_fn_rate(tmp_path)
        assert report.runs_with_failure == 1
        assert report.runs_with_missed_failure == 0
        assert report.fn_rate == 0.0

    def test_all_missed(self, tmp_path):
        record_run(1, ["a"], ["a", "b"], ["b"], audit_dir=tmp_path)
        report = compute_fn_rate(tmp_path)
        assert report.runs_with_failure == 1
        assert report.runs_with_missed_failure == 1
        assert report.fn_rate == 1.0
        assert report.total_missed_tests == 1

    def test_mixed_results(self, tmp_path):
        record_run(1, ["a"], ["a"], [], audit_dir=tmp_path)  # no failure
        record_run(2, ["a"], ["a", "b"], ["a"], audit_dir=tmp_path)  # caught
        record_run(3, ["a"], ["a", "b"], ["b"], audit_dir=tmp_path)  # missed
        report = compute_fn_rate(tmp_path)
        assert report.total_runs == 3
        assert report.runs_with_failure == 2
        assert report.runs_with_missed_failure == 1
        assert abs(report.fn_rate - 0.5) < 0.01

    def test_breakdown_by_risk(self, tmp_path):
        report_data = {
            "overall_false_negative_risk": "critical",
            "fallback_applied": True,
            "fallback_level": "rescue",
        }
        record_run(
            1, ["a"], ["a", "b"], ["b"], selector_report=report_data, audit_dir=tmp_path
        )
        report = compute_fn_rate(tmp_path)
        assert "critical" in report.breakdown_by_risk

    def test_format_report(self, tmp_path):
        record_run(1, ["a"], ["a", "b"], ["b"], audit_dir=tmp_path)
        report = compute_fn_rate(tmp_path)
        text = format_fn_rate_report(report)
        assert "FN rate:" in text
        assert "Total runs:" in text
