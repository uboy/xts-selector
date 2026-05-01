"""API usage signature and coverage equivalence types.

This module defines how a consumer (test) uses an API and how different
usage patterns relate for coverage equivalence.

Import boundary: this module imports only the standard library and model.api.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .api import ApiEntityId
from .evidence import ConfidenceLevel


UsageKind = Literal[
    "import",
    "component_instantiation",
    "chained_modifier",
    "static_modifier",
    "method_call",
    "member_access",
    "event_handler",
    "config_object",
    "resource_reference",
    "type_reference",
    "harness_only",
    "unknown",
]

ArgumentShape = Literal[
    "no_args",
    "primitive",
    "enum",
    "object_literal",
    "callback",
    "lambda",
    "resource",
    "mixed",
    "unknown",
]

CoverageEquivalenceClass = Literal[
    "exact_api_same_usage_shape",
    "exact_api_different_arguments",
    "exact_api_different_call_style",
    "exact_api_unknown_usage_shape",
    "same_family_related_api",
    "same_modifier_or_attribute_family",
    "shared_helper_related_api",
    "harness_only_usage",
    "broad_fallback",
    "unresolved_coverage",
]


@dataclass(frozen=True)
class ApiUsageSignature:
    """How a consumer (test) uses an API.

    ``harness_only`` usage must not support ``must_run`` validation.
    ``unknown`` argument shape must not silently become ``exact_api_same_usage_shape``.
    """

    api_entity_id: ApiEntityId
    language: str = "unknown"        # ArkTS, TS, JS, ETS, unknown
    usage_kind: UsageKind = "unknown"
    argument_shape: ArgumentShape = "unknown"
    receiver_type: str | None = None
    component_family: str | None = None
    call_name: str | None = None
    member_name: str | None = None
    import_name: str | None = None
    file_path: str = ""
    line: int | None = None
    span: tuple[int, int] | None = None
    test_case_name: str | None = None
    project_id: str = ""
    parser_provenance: str = ""
    parser_level: int = 0
    confidence: ConfidenceLevel = "unknown"

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "api_entity_id": self.api_entity_id.to_dict(),
            "language": self.language,
            "usage_kind": self.usage_kind,
            "argument_shape": self.argument_shape,
        }
        if self.receiver_type is not None:
            d["receiver_type"] = self.receiver_type
        if self.component_family is not None:
            d["component_family"] = self.component_family
        if self.call_name is not None:
            d["call_name"] = self.call_name
        if self.member_name is not None:
            d["member_name"] = self.member_name
        if self.import_name is not None:
            d["import_name"] = self.import_name
        if self.file_path:
            d["file_path"] = self.file_path
        if self.line is not None:
            d["line"] = self.line
        if self.span is not None:
            d["span"] = list(self.span)
        if self.test_case_name is not None:
            d["test_case_name"] = self.test_case_name
        if self.project_id:
            d["project_id"] = self.project_id
        if self.parser_provenance:
            d["parser_provenance"] = self.parser_provenance
        d["parser_level"] = self.parser_level
        d["confidence"] = self.confidence
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ApiUsageSignature:
        span = data.get("span")
        return cls(
            api_entity_id=ApiEntityId.from_dict(data["api_entity_id"]) if "api_entity_id" in data else ApiEntityId(),
            language=data.get("language", "unknown"),
            usage_kind=data.get("usage_kind", "unknown"),
            argument_shape=data.get("argument_shape", "unknown"),
            receiver_type=data.get("receiver_type"),
            component_family=data.get("component_family"),
            call_name=data.get("call_name"),
            member_name=data.get("member_name"),
            import_name=data.get("import_name"),
            file_path=data.get("file_path", ""),
            line=data.get("line"),
            span=tuple(span) if span is not None else None,
            test_case_name=data.get("test_case_name"),
            project_id=data.get("project_id", ""),
            parser_provenance=data.get("parser_provenance", ""),
            parser_level=data.get("parser_level", 0),
            confidence=data.get("confidence", "unknown"),
        )
