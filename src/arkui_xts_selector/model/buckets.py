"""Pure bucket-gate policy.

Implements the deterministic mapping from candidate evidence to a
SemanticBucket as described in
``docs/TARGET_ARCHITECTURE.md::F.BucketGatePolicy``.

The function is pure: it does not touch the filesystem, numeric ranking
scores, or rendering. Both the graph validation layer and any future
ranking/resolving layer should import this module instead of duplicating
the policy.

Import boundary: standard library + sibling model modules only.
"""

from __future__ import annotations

from dataclasses import dataclass

from .evidence import ConfidenceLevel
from .selection import SemanticBucket
from .usage import (
    CoverageEquivalenceClass,
    UsageKind,
)


_NON_MODULE_API_KINDS = frozenset({
    "component", "modifier", "attribute",
    "event_or_method", "configuration", "helper_family",
})

_COVERAGE_SPECIFIC_RULES = frozenset({
    "must_run_unresolved_coverage",
    "must_run_harness_only",
    "must_run_broad_fallback",
    "must_run_unknown_usage_shape",
    "must_run_import_only_non_module",
    "must_run_diff_args_better_test_exists",
})


@dataclass(frozen=True)
class BucketGateInputs:
    """Minimum information required to assign a semantic bucket.

    Numeric scores are intentionally absent: they may only sort
    candidates inside a bucket, never promote across buckets.
    """

    source_impact_confidence: ConfidenceLevel
    consumer_usage_confidence: ConfidenceLevel
    coverage_equivalence: CoverageEquivalenceClass
    usage_kind: UsageKind = "unknown"
    api_kind: str = ""                       # ApiEntityKind value
    only_fallback_source_evidence: bool = False
    only_path_rule_source_evidence: bool = False
    generic_fanout: bool = False
    no_better_exact_same_shape_test_exists: bool = False
    semantic_blockers: tuple[str, ...] = ()


def assign_bucket(inputs: BucketGateInputs) -> SemanticBucket:
    """Return the semantic bucket per the formal gate policy.

    See docs/TARGET_ARCHITECTURE.md, section F.BucketGatePolicy.
    """
    # 1. Hard blockers always win.
    if inputs.semantic_blockers:
        return "unresolved"
    if inputs.coverage_equivalence == "unresolved_coverage":
        return "unresolved"

    # 2. Harness-only never produces must_run.
    if inputs.coverage_equivalence == "harness_only_usage":
        return "possible"

    # 3. Import-only evidence for non-module API never reaches must_run.
    if (
        inputs.usage_kind == "import"
        and inputs.api_kind in _NON_MODULE_API_KINDS
    ):
        if inputs.consumer_usage_confidence in ("strong", "medium"):
            return "recommended"
        return "possible"

    # 4. Fallback / path-rule only as source evidence — possible.
    if inputs.only_fallback_source_evidence:
        return "possible"
    if inputs.only_path_rule_source_evidence:
        return "possible"

    # 5. Generic fan-out without strong direct consumer evidence — possible.
    if (
        inputs.generic_fanout
        and inputs.consumer_usage_confidence != "strong"
    ):
        return "possible"

    # 6. Broad fallback always degrades.
    if inputs.coverage_equivalence == "broad_fallback":
        return "possible"

    # 7. The two must_run shapes.
    if (
        inputs.source_impact_confidence == "strong"
        and inputs.consumer_usage_confidence == "strong"
        and inputs.coverage_equivalence == "exact_api_same_usage_shape"
    ):
        return "must_run"

    if (
        inputs.source_impact_confidence == "strong"
        and inputs.consumer_usage_confidence == "strong"
        and inputs.coverage_equivalence == "exact_api_different_arguments"
        and inputs.no_better_exact_same_shape_test_exists
    ):
        return "must_run"

    # 8. Recommended shapes.
    if inputs.coverage_equivalence in (
        "exact_api_different_arguments",
        "exact_api_different_call_style",
    ):
        return "recommended"
    if (
        inputs.source_impact_confidence in ("strong", "medium")
        and inputs.consumer_usage_confidence in ("strong", "medium")
    ):
        return "recommended"

    # 9. Anything else is possible.
    return "possible"


def violates_must_run_gate(inputs: BucketGateInputs) -> tuple[str, ...]:
    """Return tuple of rule ids that block must_run for these inputs.

    Empty tuple means must_run is allowed by the gate.  This is the
    canonical mirror used by graph.validation.validate_must_run_candidate.
    """
    rules: list[str] = []

    if inputs.semantic_blockers:
        rules.append("must_run_semantic_blocker_present")
    if inputs.coverage_equivalence == "unresolved_coverage":
        rules.append("must_run_unresolved_coverage")
    if inputs.coverage_equivalence == "harness_only_usage":
        rules.append("must_run_harness_only")
    if inputs.coverage_equivalence == "broad_fallback":
        rules.append("must_run_broad_fallback")
    if inputs.coverage_equivalence == "exact_api_unknown_usage_shape":
        rules.append("must_run_unknown_usage_shape")

    if (
        inputs.usage_kind == "import"
        and inputs.api_kind in _NON_MODULE_API_KINDS
    ):
        rules.append("must_run_import_only_non_module")

    if inputs.only_fallback_source_evidence:
        rules.append("must_run_fallback_only_source")
    if inputs.only_path_rule_source_evidence:
        rules.append("must_run_path_only_source")

    if (
        inputs.generic_fanout
        and inputs.consumer_usage_confidence != "strong"
    ):
        rules.append("must_run_generic_fanout_no_direct_consumer")

    # Confidence requirements.
    if inputs.source_impact_confidence != "strong":
        rules.append("must_run_source_not_strong")
    if inputs.consumer_usage_confidence != "strong":
        rules.append("must_run_consumer_not_strong")

    # Coverage equivalence requirement: only the two whitelisted classes
    # may reach must_run, and the second one needs the no-better flag.
    if inputs.coverage_equivalence == "exact_api_different_arguments":
        if not inputs.no_better_exact_same_shape_test_exists:
            rules.append("must_run_diff_args_better_test_exists")
    elif inputs.coverage_equivalence != "exact_api_same_usage_shape":
        # If no rule specific to this coverage equivalence has been
        # added, mark the candidate explicitly as "unsupported coverage".
        if not any(r in _COVERAGE_SPECIFIC_RULES for r in rules):
            rules.append("must_run_unsupported_coverage_equivalence")

    return tuple(rules)
