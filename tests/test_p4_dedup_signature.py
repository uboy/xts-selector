import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import TestFileIndex, coverage_signature, deduplicate_by_coverage_signature


class P4DedupSignatureTests(unittest.TestCase):
    def test_coverage_signature_includes_member_call_tokens(self) -> None:
        file_hits = [
            (
                5,
                TestFileIndex(
                    relative_path="a.ets",
                    member_calls={"scrollToIndex", "justifyContent"},
                ),
                ["calls Button()", "mentions button"],
            )
        ]

        sig = coverage_signature(file_hits)

        self.assertIn("calls Button()", sig)
        self.assertIn("_member:scrolltoindex", sig)
        self.assertIn("_member:justifycontent", sig)

    def test_coverage_signature_distinguishes_same_reasons_by_member_calls(self) -> None:
        file_hits_a = [
            (
                5,
                TestFileIndex(relative_path="scroll_list03.ets", member_calls={"scrollToIndex"}),
                ["calls Button()", "mentions button"],
            )
        ]
        file_hits_b = [
            (
                5,
                TestFileIndex(relative_path="layout_column.ets", member_calls={"justifyContent"}),
                ["calls Button()", "mentions button"],
            )
        ]

        self.assertNotEqual(coverage_signature(file_hits_a), coverage_signature(file_hits_b))

    def test_deduplicate_keeps_projects_with_distinct_member_call_signatures(self) -> None:
        sig_scroll = coverage_signature([
            (
                5,
                TestFileIndex(relative_path="scroll_list03.ets", member_calls={"scrollToIndex"}),
                ["calls Button()", "mentions button"],
            )
        ])
        sig_layout = coverage_signature([
            (
                5,
                TestFileIndex(relative_path="layout_column.ets", member_calls={"justifyContent"}),
                ["calls Button()", "mentions button"],
            )
        ])
        projects = [
            {"_coverage_sig": sig_scroll, "score": 5, "project": "scroll_list03"},
            {"_coverage_sig": sig_layout, "score": 5, "project": "layout_column"},
        ]

        result = deduplicate_by_coverage_signature(projects, keep_per_signature=1)

        self.assertEqual([item["project"] for item in result], ["scroll_list03", "layout_column"])


if __name__ == "__main__":
    unittest.main()
