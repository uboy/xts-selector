"""Oracle self-validation: sanity checks on oracle output quality."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OracleValidationResult:
    total_changes: int = 0
    high_count: int = 0
    medium_count: int = 0
    unmapped_count: int = 0
    high_precision: float = 0.0
    passes: bool = False
    message: str = ""


MIN_HIGH_PRECISION = 0.7


def validate_oracle_output(mappings: list[dict]) -> OracleValidationResult:
    """Validate oracle output quality on a set of PR results.

    Checks:
    - high_precision >= 0.7 (fraction of changes with high confidence)
    - At least some changes are detected
    """
    total = len(mappings)
    if total == 0:
        return OracleValidationResult(
            passes=False,
            message="No changes detected by oracle",
        )

    high = sum(1 for m in mappings if m.get("confidence") == "high")
    medium = sum(1 for m in mappings if m.get("confidence") == "medium")
    unmapped = sum(1 for m in mappings if m.get("confidence") == "unmapped")

    high_precision = high / total if total > 0 else 0.0

    passes = high_precision >= MIN_HIGH_PRECISION

    return OracleValidationResult(
        total_changes=total,
        high_count=high,
        medium_count=medium,
        unmapped_count=unmapped,
        high_precision=high_precision,
        passes=passes,
        message="OK"
        if passes
        else f"high_precision={high_precision:.2f} < {MIN_HIGH_PRECISION}",
    )
