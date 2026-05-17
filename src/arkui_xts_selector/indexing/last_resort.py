"""Last-resort path-token matching for unresolved files.

When all typed resolvers fail, this module provides a final fallback that
finds XTS test modules whose names share token overlap with the changed file path.
Results are always low-confidence (score capped at 0.25).
"""

from __future__ import annotations

from dataclasses import dataclass

_STOPWORDS: frozenset[str] = frozenset(
    {
        "ace",
        "arkui",
        "component",
        "components",
        "core",
        "cpp",
        "engine",
        "ets",
        "foundation",
        "frameworks",
        "interfaces",
        "module",
        "pattern",
        "src",
        "test",
        "common",
        "base",
        "impl",
        "ng",
        "the",
        "and",
        "for",
        "lib",
        "include",
        "adapter",
        "helper",
        "util",
        "utils",
        "inner",
        "system",
        "sys",
        "ext",
        "static",
        "dynamic",
        "accessibility",
    }
)


@dataclass(frozen=True)
class LastResortMatch:
    module_name: str
    project_path: str
    score: float


def _extract_tokens(text: str) -> set[str]:
    """Extract meaningful tokens from a path or name string."""
    tokens: set[str] = set()
    for part in text.replace("\\", "/").split("/"):
        for segment in part.split("_"):
            for piece in segment.split("."):
                piece = piece.lower().strip()
                if len(piece) >= 3 and piece not in _STOPWORDS:
                    tokens.add(piece)
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def last_resort_targets(
    rel_path: str,
    target_index: object,
    min_jaccard: float = 0.5,
    top_k: int = 5,
) -> list[LastResortMatch]:
    """Find target modules with similar path tokens using Jaccard similarity.

    Args:
        rel_path: Changed file relative path
        target_index: TargetIndexResult with .entries iterable of entries
            having .module_name and .project_path attributes
        min_jaccard: Minimum similarity threshold
        top_k: Maximum number of results

    Returns:
        List of matches sorted by score descending, score capped at 0.25.
    """
    source_tokens = _extract_tokens(rel_path)
    if not source_tokens:
        return []

    candidates: list[tuple[LastResortMatch, float]] = []
    seen_modules: set[str] = set()

    for entry in target_index.entries:
        module_name = getattr(entry, "module_name", None) or ""
        if not module_name or module_name in seen_modules:
            continue
        seen_modules.add(module_name)

        target_tokens = _extract_tokens(module_name)
        score = _jaccard(source_tokens, target_tokens)
        if score >= min_jaccard:
            project_path = getattr(entry, "project_path", module_name)
            candidates.append(
                (
                    LastResortMatch(
                        module_name=module_name,
                        project_path=str(project_path),
                        score=min(0.25, score),
                    ),
                    score,
                )
            )

    candidates.sort(key=lambda x: -x[1])
    return [match for match, _ in candidates[:top_k]]
