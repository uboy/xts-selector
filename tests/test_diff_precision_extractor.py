"""Tests for diff_precision_extractor — Phase H Track D.

Covers:
- Parsing hunk headers to correct line ranges.
- Symbol derivation when hunks overlap known symbol spans.
- Graceful handling of non-existent git refs.
- Graceful degradation when git is unavailable.
- Pure-deletion hunks (count=0) are skipped.
- Diff with no newline marker is tolerated.
"""
from __future__ import annotations

import subprocess
import sys
import pathlib
import tempfile
import textwrap
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from arkui_xts_selector.impact.diff_precision_extractor import (
    extract_precision_from_git_diff,
    _parse_diff,
    _is_safe_rev,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal unified diff string for unit testing _parse_diff
# ---------------------------------------------------------------------------

def _make_diff(hunks: list[tuple[str, int, int]]) -> str:
    """Build a synthetic unified-diff string with the given (path, start, count) hunks."""
    lines = []
    current_path = None
    for path, start, count in hunks:
        if path != current_path:
            current_path = path
            lines.append(f"diff --git a/{path} b/{path}")
            lines.append(f"--- a/{path}")
            lines.append(f"+++ b/{path}")
        lines.append(f"@@ -{start},{count} +{start},{count} @@ some_context")
        for i in range(count):
            lines.append(f"+line {start + i}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Unit tests: _parse_diff
# ---------------------------------------------------------------------------

class TestParseDiffLineRanges(unittest.TestCase):
    """Test that _parse_diff correctly extracts changed line ranges."""

    def test_single_hunk_single_file(self):
        diff = _make_diff([("frameworks/core/foo.cpp", 10, 5)])
        entries = _parse_diff(diff)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["path"], "frameworks/core/foo.cpp")
        self.assertEqual(len(entry["changed_lines"]), 1)
        start, end = entry["changed_lines"][0]
        self.assertEqual(start, 10)
        self.assertEqual(end, 14)  # 10 + 5 - 1

    def test_multiple_hunks_same_file(self):
        diff = _make_diff([
            ("foo.cpp", 5, 3),
            ("foo.cpp", 20, 2),
        ])
        entries = _parse_diff(diff)
        self.assertEqual(len(entries), 1)
        ranges = entries[0]["changed_lines"]
        self.assertEqual(len(ranges), 2)
        self.assertEqual(ranges[0], (5, 7))
        self.assertEqual(ranges[1], (20, 21))

    def test_multiple_files(self):
        diff = _make_diff([
            ("a.cpp", 1, 1),
            ("b.cpp", 10, 3),
        ])
        entries = _parse_diff(diff)
        paths = {e["path"] for e in entries}
        self.assertIn("a.cpp", paths)
        self.assertIn("b.cpp", paths)

    def test_pure_deletion_hunk_skipped(self):
        """A hunk with count=0 on the + side (pure deletion) must be ignored."""
        lines = [
            "diff --git a/del.cpp b/del.cpp",
            "--- a/del.cpp",
            "+++ b/del.cpp",
            "@@ -5,3 +5,0 @@ some_context",
            "-line 5",
            "-line 6",
            "-line 7",
        ]
        entries = _parse_diff("\n".join(lines))
        if entries:
            self.assertEqual(entries[0]["changed_lines"], [])

    def test_hunk_count_one_no_comma(self):
        """@@ -a +c @@ (no comma) means count=1."""
        lines = [
            "diff --git a/x.cpp b/x.cpp",
            "--- a/x.cpp",
            "+++ b/x.cpp",
            "@@ -1 +1 @@ func",
            "+changed line",
        ]
        entries = _parse_diff("\n".join(lines))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["changed_lines"], [(1, 1)])

    def test_no_newline_marker_tolerated(self):
        """A diff containing '\\No newline at end of file' must not crash."""
        lines = [
            "diff --git a/x.cpp b/x.cpp",
            "--- a/x.cpp",
            "+++ b/x.cpp",
            "@@ -1,1 +1,1 @@ func",
            "-old",
            "\\ No newline at end of file",
            "+new",
            "\\ No newline at end of file",
        ]
        entries = _parse_diff("\n".join(lines))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], "x.cpp")


# ---------------------------------------------------------------------------
# Unit tests: symbol extraction from hunks
# ---------------------------------------------------------------------------

class TestParseDiffSymbolExtraction(unittest.TestCase):
    """Test that touched symbols are derived from hunks using SymbolSpanIndex."""

    def _make_cpp_content(self) -> str:
        """Create C++ content with PanRecognizer::OnEvent at line 5-15."""
        lines = ["// header"] * 4
        lines.append("void PanRecognizer::OnEvent(const Event& e) {")
        lines += ["    handle(e);"] * 9
        lines.append("}")
        return "\n".join(lines)

    def test_hunk_inside_known_symbol_yields_symbol(self):
        """A hunk overlapping a C++ symbol's line range returns that symbol."""
        content = self._make_cpp_content()
        diff_text = "\n".join([
            "diff --git a/pan_recognizer.cpp b/pan_recognizer.cpp",
            "--- a/pan_recognizer.cpp",
            "+++ b/pan_recognizer.cpp",
            "@@ -6,3 +6,3 @@ PanRecognizer",
            "-old_handle",
            "+new_handle",
        ])

        # Patch find_touched_symbols so we control what symbols come back
        from arkui_xts_selector.impact.precision_models import SymbolSpan
        mock_span = SymbolSpan(
            path="pan_recognizer.cpp",
            symbol="PanRecognizer",
            start_line=5,
            end_line=15,
            kind="method",
            confidence="weak",
        )

        with patch(
            "arkui_xts_selector.impact.diff_precision_extractor.SymbolSpanIndex"
        ) as MockIndex:
            instance = MockIndex.return_value
            instance.find_touched_symbols.return_value = ([mock_span], [])
            entries = _parse_diff(diff_text)

        self.assertEqual(len(entries), 1)
        self.assertIn("PanRecognizer", entries[0]["changed_symbols"])

    def test_hunk_outside_all_symbols_yields_empty_symbols(self):
        """A hunk that does not overlap any known symbol returns empty changed_symbols."""
        diff_text = "\n".join([
            "diff --git a/nofile.cpp b/nofile.cpp",
            "--- a/nofile.cpp",
            "+++ b/nofile.cpp",
            "@@ -1,1 +1,1 @@ top",
            "+changed",
        ])

        with patch(
            "arkui_xts_selector.impact.diff_precision_extractor.SymbolSpanIndex"
        ) as MockIndex:
            instance = MockIndex.return_value
            instance.find_touched_symbols.return_value = ([], ["hunk_symbol_not_found"])
            entries = _parse_diff(diff_text)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["changed_symbols"], [])


# ---------------------------------------------------------------------------
# Integration tests: graceful error handling
# ---------------------------------------------------------------------------

class TestExtractPrecisionGracefulErrors(unittest.TestCase):
    """Test graceful handling of invalid refs and missing git."""

    def test_nonexistent_ref_returns_error_entry(self):
        """A non-existent base_rev must return a list with an invalid_ref reason."""
        entries = extract_precision_from_git_diff(
            base_rev="nonexistent_ref_xyz_abc_9999",
            head_rev="HEAD",
            repo_path="/data/shared/common/projects/ohos-helper/ohos_helper/arkui-xts-selector",
        )
        # Must return a list (not raise)
        self.assertIsInstance(entries, list)
        # At minimum one entry with an unresolved reason
        if entries:
            reasons = entries[0].get("unresolved_reasons", [])
            # Should have invalid_ref or git_diff_error
            self.assertTrue(
                any(r in ("invalid_ref", "git_diff_error", "git_unavailable") for r in reasons),
                f"Expected error reason in {reasons}",
            )

    def test_git_unavailable_returns_error_entry(self):
        """When git is not found, must return graceful error, not raise."""
        with patch(
            "arkui_xts_selector.impact.diff_precision_extractor.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            entries = extract_precision_from_git_diff(
                base_rev="HEAD~1",
                head_rev="HEAD",
                repo_path=".",
            )
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 1)
        self.assertIn("git_unavailable", entries[0]["unresolved_reasons"])

    def test_git_timeout_returns_error_entry(self):
        """Timeout from git is caught gracefully."""
        with patch(
            "arkui_xts_selector.impact.diff_precision_extractor.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=60),
        ):
            entries = extract_precision_from_git_diff("HEAD~1")
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 1)
        self.assertIn("git_timeout", entries[0]["unresolved_reasons"])

    def test_unsafe_rev_rejected(self):
        """A rev containing shell metacharacters returns invalid_ref immediately."""
        entries = extract_precision_from_git_diff(
            base_rev="HEAD; rm -rf /",
            head_rev="HEAD",
            repo_path=".",
        )
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 1)
        self.assertIn("invalid_ref", entries[0]["unresolved_reasons"])

    def test_empty_diff_returns_empty_list(self):
        """An empty diff output (no changed files) returns an empty list."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch(
            "arkui_xts_selector.impact.diff_precision_extractor.subprocess.run",
            return_value=mock_result,
        ):
            entries = extract_precision_from_git_diff("HEAD~1")
        self.assertIsInstance(entries, list)
        self.assertEqual(entries, [])

    def test_no_crash_on_git_nonzero_exit(self):
        """Non-zero git exit with unknown error returns error entry, no crash."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: something went wrong"
        with patch(
            "arkui_xts_selector.impact.diff_precision_extractor.subprocess.run",
            return_value=mock_result,
        ):
            entries = extract_precision_from_git_diff("HEAD~1")
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 1)
        self.assertTrue(len(entries[0]["unresolved_reasons"]) > 0)


# ---------------------------------------------------------------------------
# Unit tests: _is_safe_rev
# ---------------------------------------------------------------------------

class TestIsSafeRev(unittest.TestCase):
    """Test revision safety validation."""

    def test_head_is_safe(self):
        self.assertTrue(_is_safe_rev("HEAD"))

    def test_head_tilde_is_safe(self):
        self.assertTrue(_is_safe_rev("HEAD~1"))

    def test_sha_is_safe(self):
        self.assertTrue(_is_safe_rev("a1b2c3d4e5f6"))

    def test_branch_name_is_safe(self):
        self.assertTrue(_is_safe_rev("feature/my-branch"))

    def test_tag_is_safe(self):
        self.assertTrue(_is_safe_rev("v1.2.3"))

    def test_semicolon_is_unsafe(self):
        self.assertFalse(_is_safe_rev("HEAD;rm -rf /"))

    def test_space_is_unsafe(self):
        self.assertFalse(_is_safe_rev("HEAD something"))

    def test_newline_is_unsafe(self):
        self.assertFalse(_is_safe_rev("HEAD\nrm"))


if __name__ == "__main__":
    unittest.main()
