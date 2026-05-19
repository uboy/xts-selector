"""Build 'explanation' fields for JSON report output.

This module derives human-readable WHY information from data already
present in the pipeline — no evidence is invented.  Missing data is
represented as a limitation entry, never as a fabricated fact.

Public surface
--------------
build_result_explanation(result_item, ...)  ->  dict
    Returns an 'explanation' dict suitable for embedding in a per-result
    JSON item (changed_file analysis or symbol query).

build_project_entry_explanation(entry)      ->  dict
    Returns an 'explanation' dict for a per-project (test) entry inside
    results[].projects[].

All output fields are backward-compatible additions.
"""

from __future__ import annotations

from typing import Sequence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nonempty(value: object) -> str | None:
    text = str(value or "").strip()
    return text if text else None


def _list_of_str(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


# ---------------------------------------------------------------------------
# Per-result explanation (changed_file / symbol_query)
# ---------------------------------------------------------------------------

def build_result_explanation(
    result_item: dict,
) -> dict:
    """Build 'explanation' dict for a changed-file or symbol-query result item.

    Derives content exclusively from fields already present in result_item.
    Any gap in the data is reported as a limitation.

    Returns
    -------
    dict with keys:
        summary          – one or two sentence description of why this was affected
        evidence_chain   – ordered list of steps explaining the selection path
        limitations      – list of what could not be resolved
        next_actions     – list of suggested actions when something is unresolved
    """
    changed_file: str = str(result_item.get("changed_file") or "").strip()
    query: str = str(result_item.get("query") or "").strip()
    source_label = changed_file or query or "this input"

    affected_apis: list[str] = _list_of_str(result_item.get("affected_api_entities"))
    file_level_apis: list[str] = _list_of_str(
        result_item.get("file_level_affected_api_entities")
    )
    api_details: list[dict] = list(result_item.get("affected_api_entity_details") or [])
    projects: list[dict] = list(result_item.get("projects") or [])
    unresolved_reason: str = str(result_item.get("unresolved_reason") or "").strip()
    unresolved_class: str = str(result_item.get("unresolved_reason_class") or "").strip()
    coverage_gap: list[str] = _list_of_str(result_item.get("uncovered_apis"))
    uncovered_functions: list[str] = _list_of_str(result_item.get("uncovered_functions"))
    signals: dict = result_item.get("signals") or {}
    families: list[str] = _list_of_str(result_item.get("coverage_families"))
    capabilities: list[str] = _list_of_str(result_item.get("coverage_capabilities"))

    evidence_chain: list[str] = []
    limitations: list[str] = []
    next_actions: list[str] = []

    # Step 1 – what changed
    if changed_file:
        evidence_chain.append(f"Changed file: {changed_file}")
    elif query:
        evidence_chain.append(f"Symbol/API query: {query}")

    # Step 2 – signals extracted
    type_hints = _list_of_str(signals.get("type_hints"))
    member_hints = _list_of_str(signals.get("member_hints"))
    family_tokens = _list_of_str(signals.get("family_tokens"))
    all_signals_preview: list[str] = []
    if type_hints:
        all_signals_preview.append(f"type hints: {', '.join(type_hints[:4])}")
    if member_hints:
        all_signals_preview.append(f"member hints: {', '.join(member_hints[:4])}")
    if family_tokens and not type_hints and not member_hints:
        all_signals_preview.append(f"family tokens: {', '.join(family_tokens[:4])}")
    if all_signals_preview:
        evidence_chain.append(
            "Extracted signals — " + "; ".join(all_signals_preview)
        )

    # Step 3 – API resolution
    if affected_apis:
        api_preview = ", ".join(affected_apis[:4])
        suffix = f" (+{len(affected_apis) - 4} more)" if len(affected_apis) > 4 else ""
        evidence_chain.append(
            f"Resolved to {len(affected_apis)} public SDK API(s): {api_preview}{suffix}"
        )
        # Annotate confidence where available
        strong_apis = [
            d["api_name"]
            for d in api_details
            if d.get("confidence") == "strong"
        ]
        limited_apis = [
            d["api_name"]
            for d in api_details
            if d.get("limitation") == "internal_name_only"
        ]
        if strong_apis:
            evidence_chain.append(
                f"SDK-verified APIs (strong confidence): {', '.join(strong_apis[:4])}"
            )
        if limited_apis:
            limitations.append(
                f"{len(limited_apis)} API name(s) inferred from suffix only "
                f"(not confirmed in interface_sdk-js/api): {', '.join(limited_apis[:4])}"
            )
    elif file_level_apis:
        api_preview = ", ".join(file_level_apis[:4])
        evidence_chain.append(
            f"File-level API associations (no symbol-precise mapping): {api_preview}"
        )
        limitations.append(
            "API association is file-level only; no symbol-precise lineage trace was possible"
        )
    else:
        limitations.append(
            "No public SDK API could be resolved from this input; "
            "selection relied on family/capability token matching only"
        )

    # Step 4 – test selection
    if projects:
        buckets: dict[str, int] = {}
        for p in projects:
            b = str(p.get("bucket") or "unknown")
            buckets[b] = buckets.get(b, 0) + 1
        bucket_summary = ", ".join(
            f"{b}={n}" for b, n in sorted(buckets.items())
        )
        evidence_chain.append(
            f"{len(projects)} test project(s) matched ({bucket_summary})"
        )
    else:
        limitations.append("No test projects matched this input")
        next_actions.append(
            "Verify that the changed file belongs to a component with XTS coverage; "
            "check --symbol-query for the expected API name"
        )

    # Step 5 – families / capabilities context
    if families:
        evidence_chain.append(
            f"Coverage families: {', '.join(families[:4])}"
        )
    if capabilities:
        evidence_chain.append(
            f"Coverage capabilities: {', '.join(capabilities[:4])}"
        )

    # Step 6 – coverage gaps
    if coverage_gap:
        preview = ", ".join(coverage_gap[:4])
        suffix = f" (+{len(coverage_gap) - 4} more)" if len(coverage_gap) > 4 else ""
        limitations.append(
            f"Coverage gap: {len(coverage_gap)} API(s) have no matching test coverage "
            f"— {preview}{suffix}"
        )
        next_actions.append(
            "Review coverage_gap APIs and consider adding targeted XTS tests"
        )
    if uncovered_functions:
        preview = ", ".join(uncovered_functions[:4])
        limitations.append(
            f"{len(uncovered_functions)} changed function(s) have no direct test coverage: "
            f"{preview}"
        )

    # Step 7 – unresolved
    if unresolved_reason:
        limitations.append(
            f"Unresolved: {unresolved_reason}"
            + (f" [{unresolved_class}]" if unresolved_class else "")
        )
        next_actions.append(
            "File is unresolved — use --debug-trace to inspect signals; "
            "check if the file's component has public SDK API entries in interface_sdk-js/api"
        )

    # Build summary sentence
    summary = _build_summary(
        source_label=source_label,
        affected_apis=affected_apis,
        file_level_apis=file_level_apis,
        projects=projects,
        unresolved_reason=unresolved_reason,
        families=families,
    )

    return {
        "summary": summary,
        "evidence_chain": evidence_chain,
        "limitations": limitations,
        "next_actions": next_actions,
    }


def _build_summary(
    source_label: str,
    affected_apis: list[str],
    file_level_apis: list[str],
    projects: list[dict],
    unresolved_reason: str,
    families: list[str],
) -> str:
    if unresolved_reason:
        return (
            f"{source_label} could not be fully resolved: {unresolved_reason}. "
            "Selection may be incomplete — manual review recommended."
        )

    if not affected_apis and not file_level_apis and not projects:
        return (
            f"{source_label} produced no matching tests. "
            "No public SDK API association or family token match was found."
        )

    api_part = ""
    if affected_apis:
        preview = ", ".join(affected_apis[:2])
        more = f" (+{len(affected_apis) - 2} more)" if len(affected_apis) > 2 else ""
        api_part = f" affecting public SDK APIs {preview}{more}"
    elif file_level_apis:
        preview = ", ".join(file_level_apis[:2])
        api_part = f" with file-level API associations {preview}"
    elif families:
        api_part = f" matching component families {', '.join(families[:2])}"

    test_part = ""
    if projects:
        test_part = f"; {len(projects)} test project(s) selected"

    return (
        f"{source_label} was analyzed{api_part}{test_part}."
    )


# ---------------------------------------------------------------------------
# Per-project (test entry) explanation
# ---------------------------------------------------------------------------

def build_project_entry_explanation(entry: dict) -> dict:
    """Build 'explanation' dict for a project entry in results[].projects[].

    Derives content from fields already in the project entry dict.

    Returns
    -------
    dict with keys:
        summary          – one sentence why this test was selected
        evidence_chain   – ordered steps explaining match
        limitations      – data gaps for this entry
        next_actions     – suggested actions if unresolved
    """
    project: str = str(entry.get("project") or "").strip()
    bucket: str = str(entry.get("bucket") or "unknown").strip()
    score: object = entry.get("score")
    confidence: str = str(entry.get("confidence") or "").strip()
    reasons: list[str] = _list_of_str(entry.get("reasons"))
    gate_passed: object = entry.get("bucket_gate_passed")
    gate_blockers: list[str] = _list_of_str(entry.get("bucket_gate_blockers"))
    family_keys: list[str] = _list_of_str(entry.get("family_keys"))
    type_hint_keys: list[str] = _list_of_str(entry.get("type_hint_keys"))
    member_hint_keys: list[str] = _list_of_str(entry.get("member_hint_keys"))
    scope_tier: str = str(entry.get("scope_tier") or "").strip()

    evidence_chain: list[str] = []
    limitations: list[str] = []
    next_actions: list[str] = []

    # Step 1 – what project
    label = project.rsplit("/", 1)[-1] if project else "unknown project"
    evidence_chain.append(f"Test project: {project or label}")

    # Step 2 – score and bucket
    score_str = str(score) if score is not None else "unknown"
    evidence_chain.append(
        f"Score: {score_str}, confidence: {confidence or 'unknown'}, bucket: {bucket}"
    )

    # Step 3 – evidence reasons (top 5 for brevity)
    if reasons:
        evidence_chain.append(
            "Match reasons: " + "; ".join(reasons[:5])
            + (f" (+{len(reasons) - 5} more)" if len(reasons) > 5 else "")
        )

    # Step 4 – type / member hints
    if type_hint_keys:
        evidence_chain.append(
            f"Type hint keys: {', '.join(type_hint_keys[:4])}"
        )
    if member_hint_keys:
        evidence_chain.append(
            f"Member hint keys: {', '.join(member_hint_keys[:4])}"
        )

    # Step 5 – families
    if family_keys:
        evidence_chain.append(
            f"Component family match: {', '.join(family_keys[:4])}"
        )

    # Step 6 – scope
    if scope_tier:
        evidence_chain.append(f"Scope tier: {scope_tier}")

    # Step 7 – bucket gate
    if gate_passed is False and gate_blockers:
        evidence_chain.append(
            f"Bucket gate blocked must_run — blockers: {', '.join(gate_blockers)}"
        )
        limitations.append(
            f"Bucket downgraded from must_run; gate blockers: {', '.join(gate_blockers)}"
        )
        next_actions.append(
            "Gate blockers indicate insufficient evidence for must_run; "
            "check coverage_equivalence and direct type/member usage"
        )

    # Build summary
    summary = _build_project_summary(
        label=label,
        bucket=bucket,
        score=score,
        reasons=reasons,
        gate_passed=gate_passed,
        gate_blockers=gate_blockers,
    )

    return {
        "summary": summary,
        "evidence_chain": evidence_chain,
        "limitations": limitations,
        "next_actions": next_actions,
    }


def _build_project_summary(
    label: str,
    bucket: str,
    score: object,
    reasons: list[str],
    gate_passed: object,
    gate_blockers: list[str],
) -> str:
    score_str = f" (score={score})" if score is not None else ""
    if gate_passed is False and gate_blockers:
        return (
            f"{label} selected as '{bucket}'{score_str}; "
            f"bucket gate blocked must_run due to: {gate_blockers[0]}"
        )
    if reasons:
        reason_preview = reasons[0]
        return (
            f"{label} selected as '{bucket}'{score_str} — "
            f"primary match reason: {reason_preview}"
        )
    return f"{label} selected as '{bucket}'{score_str}."
