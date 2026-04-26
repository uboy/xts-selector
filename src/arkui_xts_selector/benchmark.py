"""Benchmark runner infrastructure for arkui-xts-selector.

Provides structured benchmark cases and a runner that evaluates selector
output against must_have / must_not_have expectations.

Run:
    python3 -m unittest tests.test_benchmark_runner -v
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BenchmarkCase:
    """A single benchmark case loaded from a canonical corpus fixture."""

    name: str
    family: str
    input_changed_files: list[str]
    expected_variant: str | None
    expected_surface: str | None
    expected_abstention: bool
    must_have: list[str] = field(default_factory=list)
    must_not_have: list[str] = field(default_factory=list)
    precision_budget: dict = field(default_factory=dict)
    allowed_unresolved: list[str] = field(default_factory=list)
    exact_variant_expectations: dict[str, str] = field(default_factory=dict)
    reference_set: dict = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """Evaluation result for a single benchmark case."""

    case_name: str
    family: str
    recall: float = 0.0
    precision: float = 0.0
    noise_violations: list[str] = field(default_factory=list)
    variant_correct: bool = False
    surface_correct: bool = False
    abstention_correct: bool = False
    unresolved_classes: list[str] = field(default_factory=list)
    total_output_projects: int = 0
    pass_fail: bool = False
    notes: str = ""


class BenchmarkRunner:
    """Loads fixtures and evaluates selector reports against benchmark expectations."""

    def __init__(self, fixtures_dir: Path | str) -> None:
        self.fixtures_dir = Path(fixtures_dir)
        self._cache: dict[str, BenchmarkCase] = {}

    def load_case(self, name: str) -> BenchmarkCase:
        """Load a single benchmark case from fixture JSON."""
        if name in self._cache:
            return self._cache[name]

        fixture_path = self.fixtures_dir / f"{name}.json"
        self.assertTrue(
            fixture_path.exists(),
            f"Benchmark fixture not found: {fixture_path}",
        )

        with fixture_path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        case = BenchmarkCase(
            name=name,
            family=data["family"],
            input_changed_files=data["input_changed_files"],
            expected_variant=data.get("expected_variant"),
            expected_surface=data.get("expected_surface"),
            expected_abstention=data.get("expected_abstention", False),
            precision_budget=data.get("precision_budget", {}),
            reference_set=data.get("reference_set", {}),
        )

        # Load must_have / must_not_have from referenced txt files
        # must_have_source paths are relative to the project root (parent of fixtures_dir.parent.parent)
        project_root = self.fixtures_dir.parent.parent
        must_have_source = data.get("must_have_source")
        if must_have_source:
            must_have_path = project_root / must_have_source
            case.must_have = self._load_fixture_lines(must_have_path)

        must_not_have_source = data.get("must_not_have_source")
        if must_not_have_source:
            must_not_have_path = project_root / must_not_have_source
            case.must_not_have = self._load_fixture_lines(must_not_have_path)

        self._cache[name] = case
        return case

    def load_all_cases(self) -> list[BenchmarkCase]:
        """Load all benchmark cases from the fixtures directory."""
        cases: list[BenchmarkCase] = []
        for path in sorted(self.fixtures_dir.glob("*.json")):
            name = path.stem
            cases.append(self.load_case(name))
        return cases

    def evaluate(self, case: BenchmarkCase, report: dict) -> BenchmarkResult:
        """Evaluate a selector report against a benchmark case."""
        result = BenchmarkResult(
            case_name=case.name,
            family=case.family,
        )

        # Collect all output project paths
        output_paths: list[str] = []
        for result_entry in report.get("results", []):
            for proj in result_entry.get("projects", []):
                output_paths.append(proj.get("project", ""))
        for sq in report.get("symbol_queries", []):
            for proj in sq.get("projects", []):
                output_paths.append(proj.get("project", ""))

        result.total_output_projects = len(output_paths)

        # Recall: must_have entries found in output
        if case.must_have:
            found = sum(
                1
                for expected in case.must_have
                if any(expected in path for path in output_paths)
            )
            result.recall = found / len(case.must_have) if case.must_have else 0.0
        else:
            result.recall = 1.0  # no must_have means recall is trivially satisfied

        # Precision: top-N correct (must_have in top-N)
        if case.must_have and output_paths:
            top_n = min(len(output_paths), case.precision_budget.get("max_required_count", 100))
            top_n_paths = output_paths[:top_n]
            found_in_top = sum(
                1
                for expected in case.must_have
                if any(expected in path for path in top_n_paths)
            )
            result.precision = found_in_top / len(case.must_have) if case.must_have else 0.0

        # Noise: must_not_have in top-5
        top_5 = output_paths[:5]
        for forbidden in case.must_not_have:
            hits = [p for p in top_5 if forbidden in p]
            if hits:
                result.noise_violations.append(f"{forbidden!r} in top-5: {hits}")

        # Variant check
        for result_entry in report.get("results", []):
            mode = result_entry.get("effective_variants_mode")
            if mode:
                result.variant_correct = True

        for sq in report.get("symbol_queries", []):
            mode = sq.get("effective_variants_mode")
            if mode:
                result.variant_correct = True

        # Abstention check
        if case.expected_abstention:
            # Abstention expected: check that output is very small or empty
            result.abstention_correct = result.total_output_projects <= 10
        else:
            # Abstention not expected: check that we have results
            result.abstention_correct = result.total_output_projects > 0

        # Pass/fail
        passes = []
        if case.must_have:
            passes.append(result.recall >= 0.9)
        if result.noise_violations:
            passes.append(False)
        else:
            passes.append(True)
        passes.append(result.abstention_correct)

        result.pass_fail = all(passes) if passes else False
        result.notes = (
            f"recall={result.recall:.2f}, precision={result.precision:.2f}, "
            f"noise_violations={len(result.noise_violations)}, "
            f"abstention={'correct' if result.abstention_correct else 'WRONG'}, "
            f"output_projects={result.total_output_projects}"
        )

        return result

    @staticmethod
    def _load_fixture_lines(path: Path) -> list[str]:
        """Load non-empty, non-comment lines from a fixture file."""
        if not path.exists():
            return []
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(stripped)
        return lines

    @staticmethod
    def assertTrue(condition: bool, msg: str = "") -> None:
        """Helper for assertions in a non-test context."""
        if not condition:
            raise AssertionError(msg or "Assertion failed")


def run_suite(
    fixtures_dir: Path | str,
    reports: dict[str, dict],
) -> list[BenchmarkResult]:
    """Convenience function: load all cases and evaluate provided reports.

    Args:
        fixtures_dir: Path to the canonical_corpus fixtures directory.
        reports: Mapping of case_name -> selector report dict.

    Returns:
        List of BenchmarkResult objects.
    """
    runner = BenchmarkRunner(fixtures_dir)
    results: list[BenchmarkResult] = []
    for case in runner.load_all_cases():
        report = reports.get(case.name)
        if report is None:
            results.append(BenchmarkResult(
                case_name=case.name,
                family=case.family,
                pass_fail=False,
                notes=f"No report provided for case {case.name!r}",
            ))
            continue
        results.append(runner.evaluate(case, report))
    return results
