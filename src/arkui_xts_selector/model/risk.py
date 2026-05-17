"""False-negative risk model for API impact selection.

Risk levels indicate the likelihood that the selection missed a relevant test.
High and critical risk must be visible in output, not hidden behind a short must_run list.

Import boundary: this module imports only the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass

from .selection import FalseNegativeRisk


@dataclass(frozen=True)
class RiskAssessment:
    """Assessment of false-negative risk for a selection result.

    Risk levels:
      - low:      exact source-to-API and exact API-to-XTS chain exists
      - medium:   API is known, but only related/family coverage exists
      - high:     changed file maps to API family but not exact API,
                  or important indexes are partial
      - critical: broad shared infrastructure, generated bridge, generic helper,
                  or major index missing
    """

    risk: FalseNegativeRisk = "low"
    reasons: tuple[str, ...] = ()
    mitigating_factors: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "risk": self.risk,
            "reasons": list(self.reasons),
            "mitigating_factors": list(self.mitigating_factors),
        }
        return d

    @classmethod
    def from_dict(cls, data: dict) -> RiskAssessment:
        return cls(
            risk=data.get("risk", "low"),
            reasons=tuple(data.get("reasons", [])),
            mitigating_factors=tuple(data.get("mitigating_factors", [])),
        )
