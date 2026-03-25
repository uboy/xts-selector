"""P4 regression benchmark for ButtonModifier with keep-per-signature=2."""
from __future__ import annotations

from test_benchmark_contract import (
    FIXTURES,
    WorkspaceAwareTestCase,
    _all_project_paths,
    _load_fixture_lines,
    _run_selector,
)


class ButtonModifierKeep2RegressionTests(WorkspaceAwareTestCase):
    """
    Regression benchmark for the P4 dedup tuning.

    These suites were called out in the backlog as missing under
    `--keep-per-signature 2` because the old coverage signature collapsed weak
    call-only projects with different member-call behavior.
    """

    FIXTURE_DIR = FIXTURES / "button_modifier_static"
    TOP_N = 1000

    EXPECTED_KEEP2 = [
        "ace_ets_module_scroll_list03",
        "ace_ets_module_scroll_grid02",
        "ace_ets_module_scroll_api20",
        "ace_ets_module_layout_column",
        "ace_ets_module_layout_api12",
        "ace_ets_module_commonevents",
        "ace_ets_module_commonattrsother_nowear_api11",
        "ace_ets_module_statemangagement02_api12",
    ]

    def _get_report(self) -> dict:
        return _run_selector(self.ws, [
            "--symbol-query", "ButtonModifier",
            "--variants", "static",
            "--top-projects", str(self.TOP_N),
            "--keep-per-signature", "2",
        ])

    def test_p4_expected_suites_survive_keep2_dedup(self) -> None:
        report = self._get_report()
        output_paths = [path.lower() for path in _all_project_paths(report)]
        missing = [
            expected for expected in self.EXPECTED_KEEP2
            if not any(expected in path for path in output_paths)
        ]
        if missing:
            self.fail(
                "P4 regression: expected keep=2 suites are still missing.\n\n"
                + "Missing:\n"
                + "\n".join(f"  - {item}" for item in missing)
            )

    def test_keep2_recall_remains_high_for_buttonmodifier_fixture(self) -> None:
        must_have = _load_fixture_lines(self.FIXTURE_DIR, "must_have.txt")
        if not must_have:
            self.skipTest("must_have.txt is empty or missing")

        report = self._get_report()
        output_paths = _all_project_paths(report)
        matched = sum(1 for expected in must_have if any(expected in path for path in output_paths))

        self.assertGreaterEqual(
            matched,
            80,
            f"Expected keep=2 recall to reach at least 80/83 after P4, got {matched}/{len(must_have)}",
        )
