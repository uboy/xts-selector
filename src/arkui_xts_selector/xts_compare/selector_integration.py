"""
Selector report integration for xts_compare.

Correlates selector-predicted XTS projects with actual regressions/improvements
observed between two XTS result runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import (
    ComparisonReport,
    SelectorChangedFileCorrelation,
    SelectorProjectCorrelation,
    TestIdentity,
)

_WORD_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_CAMEL_SPLIT_RE = re.compile(r"([a-z0-9])([A-Z])")
_TOKEN_STOPWORDS = {
    "ace",
    "acts",
    "api",
    "arkui",
    "attr",
    "attrs",
    "common",
    "component",
    "components",
    "dynamic",
    "ets",
    "module",
    "ohos",
    "seven",
    "static",
    "test",
    "tests",
    "xts",
}


def load_selector_report(path: str) -> dict:
    """Load a selector JSON report from disk."""
    report_path = Path(path).expanduser().resolve()
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(f"Cannot read selector report: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid selector report JSON: {path}") from exc

    if not isinstance(data, dict):
        raise ValueError("Selector report root must be a JSON object")
    return data


def _semantic_tokens(text: str) -> set[str]:
    """Extract comparable semantic tokens from a project path or module name."""
    if not text:
        return set()

    normalized = text.replace("\\", "/")
    normalized = _CAMEL_SPLIT_RE.sub(r"\1 \2", normalized)
    normalized = normalized.replace("_", " ").replace("-", " ").replace("/", " ")
    parts = _WORD_SPLIT_RE.split(normalized.lower())

    tokens = set()
    for part in parts:
        if len(part) < 3:
            continue
        if part.isdigit():
            continue
        if part in _TOKEN_STOPWORDS:
            continue
        tokens.add(part)
    return tokens


def _score_module_match(project_tokens: set[str], module_name: str) -> tuple[int, set[str]]:
    module_tokens = _semantic_tokens(module_name)
    overlap = project_tokens & module_tokens
    return len(overlap), overlap


def _match_modules(project_entry: dict, module_names: list[str]) -> list[str]:
    """Match one selector project to compared modules using token overlap."""
    token_sources = [
        str(project_entry.get("project", "")),
        str(project_entry.get("test_json", "")),
        str(project_entry.get("bundle_name", "")),
        str(project_entry.get("driver_module_name", "")),
    ]
    project_tokens: set[str] = set()
    for source in token_sources:
        project_tokens.update(_semantic_tokens(source))

    if not project_tokens:
        return []

    scored: list[tuple[int, str]] = []
    for module_name in module_names:
        score, overlap = _score_module_match(project_tokens, module_name)
        if score > 0:
            scored.append((score, module_name))

    if not scored:
        return []

    best_score = max(score for score, _ in scored)
    return sorted(module_name for score, module_name in scored if score == best_score)


def correlate_with_selector(
    comparison: ComparisonReport,
    selector_report: dict,
) -> list[SelectorChangedFileCorrelation]:
    """
    Cross-reference xts_compare results with selector predictions.

    Uses selector `results[*].projects[*]` as the machine-readable prediction source.
    """
    result_items = selector_report.get("results", [])
    if not isinstance(result_items, list):
        return []

    module_names = [module.module for module in comparison.modules]
    regressions_by_module: dict[str, list[TestIdentity]] = {}
    improvements_by_module: dict[str, list[TestIdentity]] = {}
    for transition in comparison.regressions:
        regressions_by_module.setdefault(transition.identity.module, []).append(transition.identity)
    for transition in comparison.improvements:
        improvements_by_module.setdefault(transition.identity.module, []).append(transition.identity)

    correlations: list[SelectorChangedFileCorrelation] = []
    for item in result_items:
        if not isinstance(item, dict):
            continue
        changed_file = str(item.get("changed_file", ""))
        projects = item.get("projects", [])
        if not changed_file or not isinstance(projects, list):
            continue

        predicted_projects: list[SelectorProjectCorrelation] = []
        predicted_modules: set[str] = set()
        for project_entry in projects:
            if not isinstance(project_entry, dict):
                continue
            matched_modules = _match_modules(project_entry, module_names)
            predicted_modules.update(matched_modules)

            regressions: list[TestIdentity] = []
            improvements: list[TestIdentity] = []
            for module_name in matched_modules:
                regressions.extend(regressions_by_module.get(module_name, []))
                improvements.extend(improvements_by_module.get(module_name, []))

            predicted_projects.append(
                SelectorProjectCorrelation(
                    project=str(project_entry.get("project", "")),
                    score=float(project_entry.get("score", 0.0)),
                    confidence=str(project_entry.get("confidence", "")),
                    bucket=str(project_entry.get("bucket", "")),
                    variant=str(project_entry.get("variant", "")),
                    matched_modules=matched_modules,
                    regressions=sorted(regressions, key=lambda identity: (identity.module, identity.suite, identity.case)),
                    improvements=sorted(improvements, key=lambda identity: (identity.module, identity.suite, identity.case)),
                    predicted_but_no_change=bool(matched_modules) and not regressions and not improvements,
                )
            )

        regression_not_predicted = sorted(
            [
                transition.identity
                for transition in comparison.regressions
                if transition.identity.module not in predicted_modules
            ],
            key=lambda identity: (identity.module, identity.suite, identity.case),
        )

        correlations.append(
            SelectorChangedFileCorrelation(
                changed_file=changed_file,
                predicted_projects=predicted_projects,
                regression_not_predicted=regression_not_predicted,
            )
        )

    return correlations
