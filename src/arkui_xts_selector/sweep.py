"""
Repository-wide validation sweep for ace_engine source files.

Walks all .cpp/.h/.ts files under foundation/arkui/ace_engine and collects
lineage metrics: how many files are resolved, what the fan-out distribution
looks like, and which file classes have the most gaps.

Requires a pre-built ApiLineageMap (from api_lineage.build_api_lineage_map).
Skips fan-out computation when lineage_map is None.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_SOURCE_SUFFIXES: frozenset[str] = frozenset({".cpp", ".cc", ".cxx", ".h", ".hpp", ".ts", ".js"})


def classify_source_file(rel_path: str) -> str:
    """Classify an ace_engine source file by its role in the framework.

    Returns one of: "pattern", "bridge", "native_node", "accessor",
                    "modifier", "unknown".
    """
    lower = rel_path.replace("\\", "/").lower()
    if "components_ng/pattern/" in lower:
        return "pattern"
    if "bridge/declarative_frontend" in lower:
        return "bridge"
    if "interfaces/native/node" in lower:
        return "native_node"
    if "interfaces/native/implementation" in lower:
        return "accessor"
    if "ark_modifier" in lower or "/modifier/" in lower:
        return "modifier"
    return "unknown"


@dataclass
class SweepFileResult:
    rel_path: str
    file_class: str
    api_entity_count: int
    consumer_project_count: int
    status: str  # "resolved" | "abstained"
    unresolved_class: str | None = None


@dataclass
class SweepReport:
    total_files: int
    resolved: int
    abstained: int
    error_buckets: dict[str, int]   # file_class -> abstained count
    worst_fanout: list[dict]        # top-10 highest consumer_project_count
    unresolved_distribution: dict[str, int]  # unresolved_class -> count


def _build_sweep_report(results: list[SweepFileResult]) -> SweepReport:
    """Aggregate a list of per-file results into a sweep summary."""
    total = len(results)
    resolved = sum(1 for r in results if r.status == "resolved")
    abstained = total - resolved

    error_buckets: dict[str, int] = {}
    unresolved_dist: dict[str, int] = {}
    for r in results:
        if r.status != "resolved":
            error_buckets[r.file_class] = error_buckets.get(r.file_class, 0) + 1
            if r.unresolved_class:
                unresolved_dist[r.unresolved_class] = (
                    unresolved_dist.get(r.unresolved_class, 0) + 1
                )

    worst_fanout = sorted(
        [
            {
                "rel_path": r.rel_path,
                "file_class": r.file_class,
                "api_entity_count": r.api_entity_count,
                "consumer_project_count": r.consumer_project_count,
            }
            for r in results
            if r.status == "resolved"
        ],
        key=lambda x: -x["consumer_project_count"],
    )[:10]

    return SweepReport(
        total_files=total,
        resolved=resolved,
        abstained=abstained,
        error_buckets=error_buckets,
        worst_fanout=worst_fanout,
        unresolved_distribution=unresolved_dist,
    )


def sweep_ace_engine(
    repo_root: Path,
    ace_engine_root: Path | None = None,
    *,
    lineage_map: object | None = None,
) -> SweepReport:
    """Walk source files under ace_engine and collect lineage metrics.

    Args:
        repo_root: Repository root (used to compute relative paths).
        ace_engine_root: Root of the ace_engine component. Defaults to
            ``repo_root / "foundation/arkui/ace_engine"``.
        lineage_map: Pre-built ApiLineageMap. When provided, fan-out stats
            are computed from the map. When None, all files are marked
            as abstained with no fan-out data.

    Returns:
        SweepReport with aggregate metrics.
    """
    if ace_engine_root is None:
        ace_engine_root = repo_root / "foundation" / "arkui" / "ace_engine"

    results: list[SweepFileResult] = []
    for path in _iter_source_files(ace_engine_root):
        try:
            rel_path = str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
        except ValueError:
            rel_path = str(path).replace("\\", "/")

        file_class = classify_source_file(rel_path)

        if lineage_map is not None:
            source_to_apis: dict = getattr(lineage_map, "source_to_apis", {})
            api_to_consumer_projects: dict = getattr(lineage_map, "api_to_consumer_projects", {})
            api_entities: set[str] = set(source_to_apis.get(rel_path, set()))
            consumer_projects: set[str] = set()
            for entity in api_entities:
                consumer_projects.update(api_to_consumer_projects.get(entity, set()))

            if api_entities:
                status = "resolved"
                unresolved_class = None
            else:
                status = "abstained"
                unresolved_class = "lineage_gap"
        else:
            api_entities = set()
            consumer_projects = set()
            status = "abstained"
            unresolved_class = None

        results.append(
            SweepFileResult(
                rel_path=rel_path,
                file_class=file_class,
                api_entity_count=len(api_entities),
                consumer_project_count=len(consumer_projects),
                status=status,
                unresolved_class=unresolved_class,
            )
        )

    return _build_sweep_report(results)


def sweep_report_to_dict(report: SweepReport) -> dict:
    """Serialize a SweepReport to a JSON-serializable dict."""
    return {
        "total_files": report.total_files,
        "resolved": report.resolved,
        "abstained": report.abstained,
        "resolution_rate": (
            round(report.resolved / report.total_files, 4)
            if report.total_files > 0
            else 0.0
        ),
        "error_buckets": dict(sorted(report.error_buckets.items())),
        "worst_fanout": report.worst_fanout,
        "unresolved_distribution": dict(sorted(report.unresolved_distribution.items())),
    }


def _iter_source_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES:
            yield path
