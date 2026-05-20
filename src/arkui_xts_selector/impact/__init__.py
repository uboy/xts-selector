"""Universal Impact Resolution — Phase A/B: Source Classifier + Topic Resolver.

This package provides:
- Phase A: typed source entity classification for ArkUI AceEngine source paths.
- Phase B.1: gesture API topic resolution (GestureApiResolver).

All additions are additive-only and do not affect production selector
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
from arkui_xts_selector.impact.topic_models import (
    ApiDeclarationRef,
    Domain,
    FanoutKind,
    GestureResolutionResult,
    ImpactTopic,
    SdkApiTopic,
)
from arkui_xts_selector.impact.gesture_api_resolver import GestureApiResolver

__all__ = [
    # Phase A
    "ConfidenceLevel",
    "EvidenceRef",
    "SourceClassifier",
    "SourceImpactEntity",
    "SourceLayer",
    "SourceRole",
    # Phase B.1
    "ApiDeclarationRef",
    "Domain",
    "FanoutKind",
    "GestureApiResolver",
    "GestureResolutionResult",
    "ImpactTopic",
    "SdkApiTopic",
]
