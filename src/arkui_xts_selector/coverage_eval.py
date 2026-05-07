"""Coverage evaluation metrics and regression gating."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict


class GoldenFixtureEntry(TypedDict):
    high_confidence: list[str]
    medium_confidence: list[str]
    must_run_patterns: list[str]
    recommended_count_max: int


class GoldenFixtures(TypedDict):
    version: int
    pr_number: int


@dataclass(frozen=True)
class PrMetrics:
    pr_number: int
    recall_strict: float
    recall_relaxed: float
    precision: float
    f1: float
    must_run_recall: float
    golden_count: int
    selected_count: int
    intersection_count: int


@dataclass
class CoverageReport:
    pr_metrics: dict[int, PrMetrics] = field(default_factory=dict)
    aggregated: dict[str, float] = field(default_factory=dict)
    regression_detected: bool = False
    regression_message: str = ""

    def to_dict(self) -> dict:
        return {
            "pr_metrics": {
                pr: {
                    "recall_strict": m.recall_strict,
                    "recall_relaxed": m.recall_relaxed,
                    "precision": m.precision,
                    "f1": m.f1,
                    "must_run_recall": m.must_run_recall,
                    "golden_count": m.golden_count,
                    "selected_count": m.selected_count,
                    "intersection_count": m.intersection_count,
                }
                for pr, m in self.pr_metrics.items()
            },
            "aggregated": self.aggregated,
            "regression_detected": self.regression_detected,
            "regression_message": self.regression_message,
        }

    def format_report_md(self) -> str:
        lines = [
            "# Coverage Evaluation Report\n",
            "## Aggregated Metrics\n",
        ]

        for metric, value in self.aggregated.items():
            lines.append(f"- **{metric}**: {value:.2%}")

        lines.append("\n## Per-PR Metrics\n")
        lines.append("| PR | Recall (strict) | Recall (relaxed) | Precision | F1 | Must-Run Recall |")
        lines.append("|----|-----------------|------------------|-----------|----|-----------------|")

        for pr in sorted(self.pr_metrics.keys()):
            m = self.pr_metrics[pr]
            lines.append(
                f"| {pr} | {m.recall_strict:.2%} | {m.recall_relaxed:.2%} | {m.precision:.2%} | "
                f"{m.f1:.2%} | {m.must_run_recall:.2%} |"
            )

        if self.regression_detected:
            lines.append(f"\n## Regression Detected\n\n{self.regression_message}")

        return "\n".join(lines)


@dataclass
class CoverageEvaluator:
    batch_results: list[dict]
    golden_fixtures: dict[int, GoldenFixtureEntry] = field(default_factory=dict)
    baseline_metrics: dict[str, float] | None = None

    def _extract_selected_targets(self, pr_entry: dict) -> set[str]:
        selected = set()
        gs = pr_entry.get("graph_selection", {})

        for entry in gs.get("entries", []):
            projects = entry.get("consumer_projects", [])
            selected.update(projects)

        if gs.get("fallback_applied"):
            selected.update(gs.get("fallback_extra_targets", []))

        return selected

    def _extract_golden_targets(self, pr_number: int) -> tuple[set[str], set[str]]:
        if pr_number not in self.golden_fixtures:
            return set(), set()

        fixture = self.golden_fixtures[pr_number]

        high = set(fixture.get("high_confidence", []))
        medium = set(fixture.get("medium_confidence", []))
        must_run = set(fixture.get("must_run_patterns", []))

        all_golden = high | medium | must_run
        return all_golden, must_run

    def _compute_pr_metrics(self, pr_entry: dict) -> PrMetrics | None:
        pr_number = pr_entry["pr_number"]
        selected = self._extract_selected_targets(pr_entry)
        golden, must_run = self._extract_golden_targets(pr_number)

        if not golden and not must_run:
            return None

        intersection = selected & golden
        must_run_intersection = selected & must_run

        recall_strict = len(must_run_intersection) / len(must_run) if must_run else 0.0
        recall_relaxed = len(intersection) / len(golden) if golden else 0.0
        precision = len(intersection) / len(selected) if selected else 0.0

        if precision + recall_relaxed == 0:
            f1 = 0.0
        else:
            f1 = 2 * (precision * recall_relaxed) / (precision + recall_relaxed)

        must_run_recall = len(must_run_intersection) / len(must_run) if must_run else 0.0

        return PrMetrics(
            pr_number=pr_number,
            recall_strict=recall_strict,
            recall_relaxed=recall_relaxed,
            precision=precision,
            f1=f1,
            must_run_recall=must_run_recall,
            golden_count=len(golden),
            selected_count=len(selected),
            intersection_count=len(intersection),
        )

    def evaluate(self) -> CoverageReport:
        pr_metrics: dict[int, PrMetrics] = {}

        for pr_entry in self.batch_results:
            metrics = self._compute_pr_metrics(pr_entry)
            if metrics:
                pr_metrics[metrics.pr_number] = metrics

        if not pr_metrics:
            return CoverageReport()

        aggregated: dict[str, float] = {
            "recall_strict": sum(m.recall_strict for m in pr_metrics.values()) / len(pr_metrics),
            "recall_relaxed": sum(m.recall_relaxed for m in pr_metrics.values()) / len(pr_metrics),
            "precision": sum(m.precision for m in pr_metrics.values()) / len(pr_metrics),
            "f1": sum(m.f1 for m in pr_metrics.values()) / len(pr_metrics),
            "must_run_recall": sum(m.must_run_recall for m in pr_metrics.values()) / len(pr_metrics),
        }

        regression_detected = False
        regression_message = ""

        if self.baseline_metrics:
            for metric, baseline_value in self.baseline_metrics.items():
                current_value = aggregated.get(metric, 0.0)
                drop = baseline_value - current_value
                if drop >= 0.05:
                    regression_detected = True
                    regression_message += (
                        f"Regression: {metric} dropped {drop:.2%} "
                        f"(from {baseline_value:.2%} to {current_value:.2%})\n"
                    )

        return CoverageReport(
            pr_metrics=pr_metrics,
            aggregated=aggregated,
            regression_detected=regression_detected,
            regression_message=regression_message.strip(),
        )

    def check_regression_gate(self) -> int:
        report = self.evaluate()

        if report.regression_detected:
            return 2

        return 0


def load_golden_fixtures(path: Path) -> dict[int, GoldenFixtureEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))

    fixtures: dict[int, GoldenFixtureEntry] = {}
    for key, value in data.items():
        if key == "version":
            continue
        try:
            pr_number = int(key)
            fixtures[pr_number] = value
        except (ValueError, TypeError):
            continue

    return fixtures


def load_baseline_metrics(path: Path) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("aggregated", {})
