"""Baseline vs new quality comparison for batch validation results.

Compares two batch result JSON files and produces a per-PR diff with summary metrics.
Designed for offline replay from cached results.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class PrDiff:
    """Per-PR comparison between baseline and new results."""
    pr_number: int
    baseline_status: str
    new_status: str
    baseline_target_count: int
    new_target_count: int
    target_count_delta: int
    baseline_api_count: int
    new_api_count: int
    api_count_delta: int
    baseline_unresolved: int
    new_unresolved: int
    unresolved_delta: int
    baseline_ci_policy: str
    new_ci_policy: str
    baseline_fallback: bool
    new_fallback: bool
    regression: bool
    regression_reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QualityComparisonReport:
    """Aggregate comparison report."""
    baseline_path: str
    new_path: str
    total_prs: int
    comparable_prs: int
    improved_prs: int
    regressed_prs: int
    unchanged_prs: int
    summary_metrics: dict[str, Any]
    pr_diffs: list[PrDiff]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pr_diffs"] = [p.to_dict() for p in self.pr_diffs]
        return d


def _summarize_batch(results: list[dict]) -> dict[str, Any]:
    """Compute aggregate metrics from a batch result list."""
    ok = [r for r in results if r.get("status") == "ok"]
    total = len(results)

    if not ok:
        return {"total": total, "ok": 0}

    targets = []
    api_counts = []
    unresolved = []
    fallback_count = 0

    for r in ok:
        gs = r.get("graph_selection", {})
        if not isinstance(gs, dict):
            continue

        entries = gs.get("entries", [])
        # Count unique consumer projects across all entries
        all_projs: set[str] = set()
        api_set: set[str] = set()
        unresolved_count = 0

        for e in entries:
            for p in e.get("consumer_projects", []):
                all_projs.add(p)
            for a in e.get("affected_apis", []):
                api_set.add(a)
            if e.get("unresolved_reason"):
                unresolved_count += 1

        for p in gs.get("fallback_extra_targets", []):
            all_projs.add(p)

        targets.append(len(all_projs))
        api_counts.append(len(api_set))
        unresolved.append(unresolved_count)
        if gs.get("fallback_applied"):
            fallback_count += 1

    n = len(targets)
    return {
        "total": total,
        "ok": len(ok),
        "errors": total - len(ok),
        "avg_target_count": sum(targets) / n if n else 0,
        "median_target_count": sorted(targets)[n // 2] if n else 0,
        "avg_api_count": sum(api_counts) / n if n else 0,
        "total_unresolved": sum(unresolved),
        "fallback_applied_count": fallback_count,
    }


def _compare_pr(baseline: dict, new: dict) -> PrDiff:
    """Compare a single PR between baseline and new results."""
    pr_number = baseline.get("pr_number", new.get("pr_number", 0))
    b_status = baseline.get("status", "error")
    n_status = new.get("status", "error")

    def _count_targets(r: dict) -> tuple[int, int, int, str, bool]:
        gs = r.get("graph_selection", {})
        if not isinstance(gs, dict):
            return 0, 0, 0, "unknown", False
        entries = gs.get("entries", [])
        projs: set[str] = set()
        apis: set[str] = set()
        unresolved = 0
        for e in entries:
            for p in e.get("consumer_projects", []):
                projs.add(p)
            for a in e.get("affected_apis", []):
                apis.add(a)
            if e.get("unresolved_reason"):
                unresolved += 1
        for p in gs.get("fallback_extra_targets", []):
            projs.add(p)
        ci = gs.get("ci_policy_recommendation", "unknown")
        fb = gs.get("fallback_applied", False)
        return len(projs), len(apis), unresolved, ci, fb

    b_targets, b_apis, b_unresolved, b_ci, b_fb = _count_targets(baseline)
    n_targets, n_apis, n_unresolved, n_ci, n_fb = _count_targets(new)

    # Detect regressions
    regressions: list[str] = []
    if n_status == "error" and b_status == "ok":
        regressions.append("new_result_error")
    if n_targets < b_targets and b_targets > 0:
        regressions.append(f"target_count_dropped:{b_targets}->{n_targets}")
    if n_unresolved > b_unresolved:
        regressions.append(f"unresolved_increased:{b_unresolved}->{n_unresolved}")
    if n_ci in ("manual_review",) and b_ci not in ("manual_review",):
        regressions.append(f"ci_policy_downgraded:{b_ci}->{n_ci}")

    return PrDiff(
        pr_number=pr_number,
        baseline_status=b_status,
        new_status=n_status,
        baseline_target_count=b_targets,
        new_target_count=n_targets,
        target_count_delta=n_targets - b_targets,
        baseline_api_count=b_apis,
        new_api_count=n_apis,
        api_count_delta=n_apis - b_apis,
        baseline_unresolved=b_unresolved,
        new_unresolved=n_unresolved,
        unresolved_delta=n_unresolved - b_unresolved,
        baseline_ci_policy=b_ci,
        new_ci_policy=n_ci,
        baseline_fallback=b_fb,
        new_fallback=n_fb,
        regression=len(regressions) > 0,
        regression_reasons=regressions,
    )


def compare_batch_results(
    baseline_path: Path,
    new_path: Path,
    output_path: Path | None = None,
) -> QualityComparisonReport:
    """Compare two batch result JSON files.

    Args:
        baseline_path: Path to baseline batch results JSON.
        new_path: Path to new batch results JSON.
        output_path: Optional path to write comparison report JSON.

    Returns:
        QualityComparisonReport with per-PR diffs and aggregate metrics.
    """
    baseline_results: list[dict] = json.loads(baseline_path.read_text(encoding="utf-8"))
    new_results: list[dict] = json.loads(new_path.read_text(encoding="utf-8"))

    # Index by PR number
    baseline_by_pr = {r["pr_number"]: r for r in baseline_results if "pr_number" in r}
    new_by_pr = {r["pr_number"]: r for r in new_results if "pr_number" in r}

    all_prs = sorted(set(baseline_by_pr) | set(new_by_pr))

    diffs: list[PrDiff] = []
    for pr in all_prs:
        b = baseline_by_pr.get(pr)
        n = new_by_pr.get(pr)
        if b is None or n is None:
            continue
        diffs.append(_compare_pr(b, n))

    improved = sum(1 for d in diffs if d.target_count_delta > 0 and not d.regression)
    regressed = sum(1 for d in diffs if d.regression)
    unchanged = len(diffs) - improved - regressed

    report = QualityComparisonReport(
        baseline_path=str(baseline_path),
        new_path=str(new_path),
        total_prs=len(all_prs),
        comparable_prs=len(diffs),
        improved_prs=improved,
        regressed_prs=regressed,
        unchanged_prs=unchanged,
        summary_metrics={
            "baseline": _summarize_batch(baseline_results),
            "new": _summarize_batch(new_results),
        },
        pr_diffs=diffs,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return report
