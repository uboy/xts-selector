"""Backwards-compatible re-export of bucket-gate policy.

The canonical implementation lives in :mod:`arkui_xts_selector.model.buckets`.
This module re-exports the public names so existing imports continue
to work during the transition.

Import boundary: standard library + arkui_xts_selector.model only.
"""

from arkui_xts_selector.model.buckets import (  # noqa: F401
    BucketGateInputs,
    assign_bucket,
    violates_must_run_gate,
)

__all__ = [
    "BucketGateInputs",
    "assign_bucket",
    "violates_must_run_gate",
]
