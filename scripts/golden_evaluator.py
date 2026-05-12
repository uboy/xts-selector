#!/usr/bin/env python3
"""Golden PR evaluator for precision contract validation.

Usage:
    # Strict mode (default) — only approved PRs count
    python3 scripts/golden_evaluator.py \
        --golden config/golden_pr_set.json \
        --batch-results local/quality_runs/20260508_precision/batch_results.json \
        --output local/quality_runs/golden_eval.json

    # Diagnostic mode — includes auto-labeled PRs
    python3 scripts/golden_evaluator.py \
        --golden config/golden_pr_set.json \
        --batch-results local/quality_runs/20260508_precision/batch_results.json \
        --allow-auto-labels \
        --output local/quality_runs/golden_eval_diagnostic.json

Evaluates batch results against a golden PR set with reviewer-approved
must_run/must_not_run targets. In strict mode (default), only PRs with
annotation_status == "approved" contribute to gate metrics.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_golden(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return data.get("golden_prs", [])


def load_results(path: str) -> dict[int, dict]:
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict) and "pr_results" in data:
        results = data["pr_results"]
    elif isinstance(data, list):
        results = data
    else:
        results = []
    return {r["pr_number"]: r for r in results if "pr_number" in r}


def _shorten(path: str) -> str:
    """Strip known absolute path prefixes."""
    for prefix in [
        "/data/home/dmazur/proj/ohos_master/",
        "/data/shared/common/proj/ohos_master/",
    ]:
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


def _matches(pattern: str, target: str) -> bool:
    """Glob-like matching with path normalization."""
    pat = _shorten(pattern)
    tgt = _shorten(target)
    if pat.endswith("*"):
        return tgt.startswith(pat[:-1])
    return pat == tgt


def _get_actual_targets(result: dict) -> set[str]:
    """Extract all actual selected targets from a batch result, normalized."""
    gs = result.get("graph_selection", {})
    actual = set()
    for e in gs.get("entries", []):
        for p in e.get("consumer_projects", []):
            actual.add(_shorten(p))
    for p in gs.get("fallback_extra_targets", []):
        actual.add(_shorten(p))
    return actual


def _get_actual_policy(result: dict) -> str:
    """Get the actual CI policy recommendation from batch result."""
    return result.get("graph_selection", {}).get("ci_policy_recommendation", "ok")


def evaluate_pr(golden: dict, result: dict, *, strict: bool = True) -> dict:
    """Evaluate a single PR against golden expectations.

    In strict mode, only annotation_status == "approved" PRs count toward gate.
    """
    pr_num = golden["pr_number"]
    annotation_status = golden.get("annotation_status", "candidate")
    expected_selection = golden.get("expected_selection", "")

    # Get reviewer decision fields (v2 schema)
    reviewer = golden.get("reviewer_decision", {})
    must_run = reviewer.get("must_run", golden.get("must_run", []))
    should_run = reviewer.get("should_run", golden.get("should_run", []))
    must_not_run = reviewer.get("must_not_run", golden.get("must_not_run", []))
    allowed_extra = reviewer.get("allowed_extra_targets", [])
    expected_policy = reviewer.get("expected_policy", golden.get("expected_policy", ""))

    # Get actual targets
    actual_targets = _get_actual_targets(result)
    actual_policy = _get_actual_policy(result)

    # --- Check if this PR is eligible for gate evaluation ---
    is_approved = annotation_status == "approved"

    if strict and not is_approved:
        return {
            "pr_number": pr_num,
            "passed": False,
            "skipped_reason": f"annotation_status={annotation_status}, strict mode requires approved",
            "annotation_status": annotation_status,
            "expected_selection": expected_selection,
            "category": golden.get("category", "unknown"),
            "target_count": len(actual_targets),
        }

    # --- Must-run recall ---
    must_run_hits = 0
    must_run_misses = []
    for pattern in must_run:
        matches = [t for t in actual_targets if _matches(pattern, t)]
        if matches:
            must_run_hits += 1
        else:
            must_run_misses.append(pattern)

    # --- Must-not-run violations ---
    forbidden_hits = []
    for pattern in must_not_run:
        matches = [t for t in actual_targets if _matches(pattern, t)]
        if matches:
            forbidden_hits.extend(matches)

    # --- Extra target violations ---
    extra_violations = []
    if allowed_extra or must_not_run:
        permitted = set()
        for pattern in list(must_run) + list(should_run) + list(allowed_extra):
            for t in actual_targets:
                if _matches(pattern, t):
                    permitted.add(t)
        for t in sorted(actual_targets):
            if t not in permitted:
                extra_violations.append(t)

    # --- Policy match ---
    policy_match = actual_policy == expected_policy if expected_policy else None

    # --- Determine pass/fail ---
    selection_type = expected_selection
    if not selection_type:
        selection_type = "required_targets" if must_run else "none_required"

    passed = True
    fail_reasons = []

    if selection_type == "required_targets":
        if not must_run:
            passed = False
            fail_reasons.append("required_targets with empty must_run")
        elif must_run_hits < len(must_run):
            passed = False
            fail_reasons.append(f"must_run_recall {must_run_hits}/{len(must_run)}")
        if forbidden_hits:
            passed = False
            fail_reasons.append(f"must_not_run violations: {forbidden_hits}")
        if extra_violations:
            passed = False
            fail_reasons.append(f"extra target violations: {len(extra_violations)}")
        if expected_policy and not policy_match:
            passed = False
            fail_reasons.append(f"policy mismatch: expected={expected_policy} actual={actual_policy}")

    elif selection_type == "none_required":
        if must_run:
            fail_reasons.append("none_required with non-empty must_run (review)")
        if forbidden_hits:
            passed = False
            fail_reasons.append(f"must_not_run violations: {forbidden_hits}")
        # Precision check: none_required means NO targets should be needed
        if actual_targets:
            allowed = set()
            for pattern in list(allowed_extra):
                for t in actual_targets:
                    if _matches(pattern, t):
                        allowed.add(t)
            unexpected = actual_targets - allowed
            if unexpected:
                passed = False
                fail_reasons.append(f"none_required but selector found {len(unexpected)} unexpected targets")
        notes = reviewer.get("notes", golden.get("notes", ""))
        if not notes:
            passed = False
            fail_reasons.append("none_required without rationale in notes")

    elif selection_type == "manual_review_only":
        passed = None  # sentinel: excluded from recall computation
        if forbidden_hits:
            passed = False
            fail_reasons.append(f"must_not_run violations even for manual_review: {forbidden_hits}")

    elif selection_type == "broad_suite_required":
        if not must_run and not must_not_run:
            passed = False
            fail_reasons.append("broad_suite_required without any contract (empty must_run and must_not_run)")
        else:
            if must_run and must_run_hits < len(must_run):
                passed = False
                fail_reasons.append(f"must_run_recall {must_run_hits}/{len(must_run)}")
        if forbidden_hits:
            passed = False
            fail_reasons.append(f"must_not_run violations: {forbidden_hits}")
        if expected_policy and not policy_match:
            passed = False
            fail_reasons.append(f"policy mismatch: expected={expected_policy} actual={actual_policy}")

    return {
        "pr_number": pr_num,
        "passed": passed,
        "annotation_status": annotation_status,
        "expected_selection": selection_type,
        "category": golden.get("category", "unknown"),
        "must_run_total": len(must_run),
        "must_run_hits": must_run_hits,
        "must_run_misses": must_run_misses,
        "must_not_run_total": len(must_not_run),
        "must_not_run_violations": forbidden_hits,
        "allowed_extra_targets": len(allowed_extra),
        "extra_target_violations": extra_violations,
        "target_count": len(actual_targets),
        "expected_policy": expected_policy,
        "actual_policy": actual_policy,
        "policy_match": policy_match,
        "fail_reasons": fail_reasons,
        "label_source": golden.get("label_source", "unknown"),
    }


def compute_aggregate_metrics(evaluations: list[dict]) -> dict:
    """Compute aggregate metrics across all evaluated PRs."""
    valid_evals = [e for e in evaluations if "skipped_reason" not in e]
    approved_evals = [e for e in valid_evals if e.get("annotation_status") == "approved"]

    required_targets = [e for e in approved_evals if e.get("expected_selection") == "required_targets"]
    none_required = [e for e in approved_evals if e.get("expected_selection") == "none_required"]
    manual_review_only = [e for e in approved_evals if e.get("expected_selection") == "manual_review_only"]
    broad_suite = [e for e in approved_evals if e.get("expected_selection") == "broad_suite_required"]

    total_must_run = sum(e["must_run_total"] for e in required_targets)
    total_must_run_hits = sum(e["must_run_hits"] for e in required_targets)
    must_run_recall = total_must_run_hits / max(1, total_must_run)
    must_run_missed = total_must_run - total_must_run_hits

    total_must_not_run = sum(e["must_not_run_total"] for e in approved_evals)
    total_forbidden = sum(len(e.get("must_not_run_violations", [])) for e in approved_evals)
    must_not_run_violation_rate = total_forbidden / max(1, total_must_not_run)

    total_allowed_extra = sum(e.get("allowed_extra_targets", 0) for e in approved_evals)
    total_extra_violations = sum(len(e.get("extra_target_violations", [])) for e in approved_evals)
    extra_target_violation_rate = total_extra_violations / max(1, total_allowed_extra) if total_allowed_extra else 0.0

    policy_evals = [e for e in approved_evals if e.get("expected_policy")]
    policy_matches = sum(1 for e in policy_evals if e.get("policy_match") is True)
    policy_accuracy = policy_matches / max(1, len(policy_evals))

    total_selected = sum(e["target_count"] for e in approved_evals)
    total_required = sum(e["must_run_total"] + len(e.get("should_run") or []) for e in approved_evals)
    target_overselection_ratio = total_selected / max(1, total_required)

    by_category: dict[str, dict] = {}
    cats: dict[str, tuple[int, int]] = {}
    for e in required_targets:
        cat = e.get("category", "unknown")
        if cat not in cats:
            cats[cat] = (0, 0)
        h, t = cats[cat]
        cats[cat] = (h + e["must_run_hits"], t + e["must_run_total"])

    for cat, (hits, total) in sorted(cats.items()):
        by_category[cat] = {
            "must_run_recall": round(hits / max(1, total), 4),
            "must_run_hits": hits,
            "must_run_total": total,
        }

    return {
        "approved_must_run_recall": round(must_run_recall, 4),
        "approved_must_run_hits": total_must_run_hits,
        "approved_must_run_total": total_must_run,
        "approved_must_run_missed": must_run_missed,
        "must_not_run_violation_count": total_forbidden,
        "must_not_run_violation_rate": round(must_not_run_violation_rate, 4),
        "extra_target_violation_count": total_extra_violations,
        "extra_target_violation_rate": round(extra_target_violation_rate, 4),
        "policy_accuracy": round(policy_accuracy, 4),
        "target_overselection_ratio": round(target_overselection_ratio, 4),
        "approved_pr_count": len(approved_evals),
        "unapproved_pr_count": len(evaluations) - len(approved_evals),
        "manual_review_rate": round(len(manual_review_only) / max(1, len(approved_evals)), 4),
        "none_required_count": len(none_required),
        "broad_suite_required_count": len(broad_suite),
        "required_targets_count": len(required_targets),
        "must_run_recall_by_category": by_category,
    }


def main():
    parser = argparse.ArgumentParser(description="Golden PR evaluator")
    parser.add_argument("--golden", required=True, help="Path to golden_pr_set.json")
    parser.add_argument("--batch-results", required=True, help="Path to batch_results.json")
    parser.add_argument("--output", help="Output evaluation JSON path")
    parser.add_argument("--allow-auto-labels", action="store_true",
                        help="Include auto-labeled PRs in evaluation (diagnostic mode)")
    args = parser.parse_args()

    strict = not args.allow_auto_labels
    mode_name = "strict" if strict else "diagnostic"

    golden_prs = load_golden(args.golden)
    results = load_results(args.batch_results)

    approved_count = sum(1 for g in golden_prs if g.get("annotation_status") == "approved")
    if strict and approved_count == 0:
        print("ERROR: No approved golden PRs — strict gate requires annotation_status=approved. "
              "Use --allow-auto-labels for diagnostic mode.", file=sys.stderr)
        return 2

    evaluations = []
    for g in golden_prs:
        pr_num = g["pr_number"]
        result = results.get(pr_num)
        if result is None:
            evaluations.append({
                "pr_number": pr_num,
                "passed": False,
                "error": "PR not found in batch results",
                "annotation_status": g.get("annotation_status", "unknown"),
                "category": g.get("category", "unknown"),
            })
            continue
        evaluations.append(evaluate_pr(g, result, strict=strict))

    aggregate = compute_aggregate_metrics(evaluations)

    total = len(evaluations)
    skipped = sum(1 for e in evaluations if "skipped_reason" in e)
    errored = sum(1 for e in evaluations if "error" in e)
    evaluated = total - skipped - errored
    passed = sum(1 for e in evaluations if e.get("passed") is True)
    failed = sum(1 for e in evaluations if e.get("passed") is False)
    manual_review = sum(1 for e in evaluations if e.get("passed") is None)

    print(f"=== Golden PR Evaluation ({mode_name} mode) ===")
    print(f"  Total: {total}")
    print(f"  Evaluated: {evaluated}")
    print(f"  Skipped (not approved): {skipped}")
    print(f"  Not found in results: {errored}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Manual review (excluded from recall): {manual_review}")
    if manual_review > 0:
        print(f"  Note: {manual_review} manual_review_only PRs excluded from pass/fail rate")
    print()

    for e in evaluations:
        status = "PASS" if e.get("passed") is True else ("MANUAL_REVIEW" if e.get("passed") is None else "FAIL")
        ann = e.get("annotation_status", "?")
        sel = e.get("expected_selection", "?")
        print(f"  PR {e['pr_number']}: {status} [{ann}/{sel}]")
        if not e.get("passed") and e.get("fail_reasons"):
            for reason in e["fail_reasons"]:
                print(f"    {reason}")
        if e.get("must_run_misses"):
            print(f"    Missing must_run: {e['must_run_misses']}")
        if e.get("must_not_run_violations"):
            print(f"    Forbidden targets: {e['must_not_run_violations']}")

    print()
    print(f"=== Aggregate Metrics ({mode_name} mode) ===")
    print(f"Approved PR count:        {aggregate['approved_pr_count']}")
    print(f"Unapproved PR count:      {aggregate['unapproved_pr_count']}")
    print()

    if aggregate["approved_pr_count"] > 0:
        mr = aggregate["approved_must_run_recall"]
        hits = aggregate["approved_must_run_hits"]
        total_mr = aggregate["approved_must_run_total"]
        if total_mr > 0:
            print(f"approved_must_run_recall: {mr:.4f} ({hits}/{total_mr})")
        else:
            print(f"approved_must_run_recall: N/A (no required_targets PRs)")
        print(f"must_run_missed:          {aggregate['approved_must_run_missed']}")
        print(f"must_not_run_violations:  {aggregate['must_not_run_violation_count']} "
              f"(rate: {aggregate['must_not_run_violation_rate']*100:.2f}%)")
        print(f"extra_target_violations:  {aggregate['extra_target_violation_count']}")
        print(f"policy_accuracy:          {aggregate['policy_accuracy']*100:.1f}%")
        print(f"target_overselection:     {aggregate['target_overselection_ratio']:.4f}")
        print(f"manual_review_rate:       {aggregate['manual_review_rate']*100:.1f}%")
        print(f"none_required_count:      {aggregate['none_required_count']}")
        print(f"broad_suite_count:        {aggregate['broad_suite_required_count']}")
        print(f"required_targets_count:   {aggregate['required_targets_count']}")

        if aggregate["must_run_recall_by_category"]:
            print()
            print("By category (required_targets only):")
            for cat, metrics in sorted(aggregate["must_run_recall_by_category"].items()):
                recall = metrics["must_run_recall"]
                hits = metrics["must_run_hits"]
                total_cat = metrics["must_run_total"]
                print(f"  {cat:20s}: recall {recall:.4f} ({hits}/{total_cat})")
    else:
        print("(No approved PRs to evaluate)")

    if args.output:
        non_manual_evaluated = evaluated - manual_review
        pass_rate_excl = round(passed / max(1, non_manual_evaluated), 4)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump({
                "mode": mode_name,
                "total": total,
                "evaluated": evaluated,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "manual_review": manual_review,
                "pass_rate": round(passed / max(1, evaluated), 4),
                "pass_rate_excluding_manual": pass_rate_excl,
                "aggregate": aggregate,
                "evaluations": evaluations,
            }, f, indent=2, default=str)
        print(f"\nSaved to {args.output}")

    if strict and approved_count == 0:
        return 2
    if failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
