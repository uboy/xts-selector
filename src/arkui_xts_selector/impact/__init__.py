"""Universal Impact Resolution — Phase A: Source Classifier.

This package provides typed source entity classification for ArkUI AceEngine
source paths. It is additive-only and does not affect production selector
scoring, bucket assignment, or must_run logic.
"""

from arkui_xts_selector.impact.models import (
    ConfidenceLevel,
    EvidenceRef,
    SourceImpactEntity,
    SourceLayer,
    SourceRole,
)
from arkui_xts_selector.impact.source_classifier import SourceClassifier

__all__ = [
    "ConfidenceLevel",
    "EvidenceRef",
    "SourceClassifier",
    "SourceImpactEntity",
    "SourceLayer",
    "SourceRole",
]
