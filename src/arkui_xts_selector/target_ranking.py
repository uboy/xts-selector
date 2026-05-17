"""Target ranking with bucket model (D.1).

Classifies resolved targets into must_run/recommended/fallback buckets
with scoring and caps to prevent target explosion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TargetBucket = Literal["must_run", "recommended", "fallback"]

BUCKET_CAPS: dict[TargetBucket, int | None] = {
    "must_run": None,
    "recommended": 40,
    "fallback": 30,
}

# Scoring table: (has_canonical, has_direct_match, has_sdk_confirm) → bucket
_BUCKET_RULES: list[tuple[bool, bool, bool, TargetBucket]] = [
    (True, True, True, "must_run"),
    (True, True, False, "must_run"),
    (True, False, True, "must_run"),
    (True, False, False, "recommended"),
    (False, True, True, "recommended"),
    (False, True, False, "recommended"),
    (False, False, True, "recommended"),
    (False, False, False, "fallback"),
]


@dataclass(frozen=True)
class RankedTarget:
    project_path: str
    project_id: str
    family_keys: tuple[str, ...] = ()
    bucket: TargetBucket = "fallback"
    score: float = 0.0
    reasons: tuple[str, ...] = ()
    source_files: tuple[str, ...] = ()


@dataclass
class RankingResult:
    must_run: list[RankedTarget] = field(default_factory=list)
    recommended: list[RankedTarget] = field(default_factory=list)
    fallback: list[RankedTarget] = field(default_factory=list)
    dropped: list[RankedTarget] = field(default_factory=list)
    dropped_count: int = 0

    @property
    def all_targets(self) -> list[RankedTarget]:
        return self.must_run + self.recommended + self.fallback

    def to_dict(self) -> dict:
        return {
            "must_run": [t.project_id for t in self.must_run],
            "recommended": [t.project_id for t in self.recommended],
            "fallback": [t.project_id for t in self.fallback],
            "dropped": [
                {
                    "project_id": t.project_id,
                    "bucket": t.bucket,
                    "score": t.score,
                    "reasons": list(t.reasons),
                }
                for t in self.dropped
            ],
            "dropped_count": self.dropped_count,
            "total": len(self.all_targets),
        }


def _classify_bucket(
    has_canonical: bool,
    has_direct_match: bool,
    has_sdk_confirm: bool,
) -> TargetBucket:
    for canon, direct, sdk, bucket in _BUCKET_RULES:
        if (
            has_canonical == canon
            and has_direct_match == direct
            and has_sdk_confirm == sdk
        ):
            return bucket
    return "fallback"


def rank_targets(
    entries: list[dict],
) -> RankingResult:
    """Rank targets from pr_resolver entries into buckets.

    Each entry is a PrResolveEntry dict with:
    - consumer_projects: list of target project IDs
    - affected_apis: list of API names
    - canonical_affected_apis: list of canonical API IDs
    - selection_reasons: list of reason dicts
    - impact_candidates: list of candidate dicts
    """
    target_map: dict[str, _TargetAccum] = {}

    for entry in entries:
        has_canonical = bool(entry.get("canonical_affected_apis"))
        has_direct = any(
            r.get("confidence") == "strong" for r in entry.get("selection_reasons", [])
        )
        has_sdk = any(
            c.get("impact_kind") in ("generated_bridge", "authored_bridge")
            for c in entry.get("impact_candidates", [])
        )
        bucket = _classify_bucket(has_canonical, has_direct, has_sdk)

        for proj in entry.get("consumer_projects", []):
            if proj not in target_map:
                target_map[proj] = _TargetAccum(
                    project_id=proj,
                    best_bucket=bucket,
                    score=1.0 if has_canonical else 0.5,
                    reasons=(),
                    source_files=(),
                )
            else:
                accum = target_map[proj]
                bucket_order = {"must_run": 0, "recommended": 1, "fallback": 2}
                if bucket_order.get(bucket, 2) < bucket_order.get(accum.best_bucket, 2):
                    accum.best_bucket = bucket
                if has_canonical:
                    accum.score += 1.0
                else:
                    accum.score += 0.5

            changed_file = entry.get("changed_file", "")
            accum = target_map[proj]
            if changed_file and changed_file not in accum.source_files:
                accum.source_files = (*accum.source_files, changed_file)

    raw_must: list[RankedTarget] = []
    raw_rec: list[RankedTarget] = []
    raw_fall: list[RankedTarget] = []

    for proj_id, accum in target_map.items():
        rt = RankedTarget(
            project_path=proj_id,
            project_id=proj_id,
            bucket=accum.best_bucket,
            score=accum.score,
            reasons=accum.reasons,
            source_files=accum.source_files,
        )
        if accum.best_bucket == "must_run":
            raw_must.append(rt)
        elif accum.best_bucket == "recommended":
            raw_rec.append(rt)
        else:
            raw_fall.append(rt)

    for lst in (raw_must, raw_rec, raw_fall):
        lst.sort(key=lambda t: (-t.score, t.project_id))

    dropped_targets: list[RankedTarget] = []
    dropped_count = 0

    def _apply_cap(items: list[RankedTarget], cap: int | None) -> list[RankedTarget]:
        nonlocal dropped_count
        if cap is None or len(items) <= cap:
            return items
        dropped_count += len(items) - cap
        dropped_targets.extend(items[cap:])
        return items[:cap]

    return RankingResult(
        must_run=_apply_cap(raw_must, BUCKET_CAPS["must_run"]),
        recommended=_apply_cap(raw_rec, BUCKET_CAPS["recommended"]),
        fallback=_apply_cap(raw_fall, BUCKET_CAPS["fallback"]),
        dropped=dropped_targets,
        dropped_count=dropped_count,
    )


class _TargetAccum:
    __slots__ = ("project_id", "best_bucket", "score", "reasons", "source_files")

    def __init__(
        self,
        project_id: str,
        best_bucket: TargetBucket,
        score: float,
        reasons: tuple[str, ...],
        source_files: tuple[str, ...],
    ) -> None:
        self.project_id = project_id
        self.best_bucket = best_bucket
        self.score = score
        self.reasons = reasons
        self.source_files = source_files
