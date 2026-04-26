from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


STATIC = "static"
DYNAMIC = "dynamic"
COMMON = "common"
UNKNOWN = "unknown"
UTILITY = "utility"
MIXED = "mixed"
BOTH = "both"

STATIC_USE_RE = re.compile(r"""^\s*['"]use static['"]\s*;?\s*$""", re.M)
DYNAMIC_UI_RE = re.compile(r"""@(Entry|Component|ComponentV2|Builder)\b""")
COMPONENT_STRUCT_RE = re.compile(r"""\bstruct\s+[A-Z][A-Za-z0-9_]*\b""")
STATIC_INCLUDE_RE = re.compile(r'#include\s+"[^"]*(?:_static(?:[./_]|")|static_[^"]*)')
STATIC_IDENTIFIER_RE = re.compile(r"""\b[A-Za-z_][A-Za-z0-9_]*Static\b""")
STATIC_GENERATED_RE = re.compile(r"""\bGet[A-Za-z0-9_]*Static[A-Za-z0-9_]*\s*\(""")
DYNAMIC_IDENTIFIER_RE = re.compile(r"""\b[A-Za-z_][A-Za-z0-9_]*Dynamic\b""")
DYNAMIC_HELPER_RE = re.compile(r"""\b(?:DynamicModuleHelper|GetDynamicModule)\b""")


def compact_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def tokenize_surface_text(text: str) -> list[str]:
    return [part for part in re.split(r"[\s/._-]+", text) if part]


def variant_to_supported_surfaces(variant: str) -> set[str]:
    if variant == STATIC:
        return {STATIC}
    if variant == DYNAMIC:
        return {DYNAMIC}
    if variant == BOTH:
        return {STATIC, DYNAMIC}
    return set()


@dataclass
class XtsFileSurfaceProfile:
    surface: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class XtsProjectSurfaceProfile:
    surface: str
    variant: str
    supported_surfaces: tuple[str, ...]
    static_file_count: int = 0
    dynamic_file_count: int = 0
    utility_file_count: int = 0


@dataclass
class AceEngineSurfaceProfile:
    surface: str
    layer: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class QuerySurfaceIntent:
    requested_surface: str
    reasons: list[str] = field(default_factory=list)


def classify_xts_file_surface(path: Path, text: str) -> XtsFileSurfaceProfile:
    if path.suffix.lower() != ".ets":
        return XtsFileSurfaceProfile(surface=UTILITY, reasons=["non-ets file"])

    static_reasons: list[str] = []
    if STATIC_USE_RE.search(text):
        static_reasons.append("use static directive")
    if "@ohos.arkui.component" in text:
        static_reasons.append("imports @ohos.arkui.component")
    if static_reasons:
        return XtsFileSurfaceProfile(surface=STATIC, reasons=static_reasons)

    dynamic_reasons: list[str] = []
    if DYNAMIC_UI_RE.search(text):
        dynamic_reasons.append("ui decorators")
    if COMPONENT_STRUCT_RE.search(text) and "build(" in text:
        dynamic_reasons.append("component struct with build()")
    if ".attributeModifier(" in text or ".contentModifier(" in text:
        dynamic_reasons.append("modifier chaining")
    if dynamic_reasons:
        return XtsFileSurfaceProfile(surface=DYNAMIC, reasons=dynamic_reasons)

    return XtsFileSurfaceProfile(surface=UTILITY, reasons=["no surface-specific markers"])


def classify_xts_project_surface(file_surfaces: Iterable[str]) -> XtsProjectSurfaceProfile:
    static_count = 0
    dynamic_count = 0
    utility_count = 0
    for surface in file_surfaces:
        if surface == STATIC:
            static_count += 1
        elif surface == DYNAMIC:
            dynamic_count += 1
        else:
            utility_count += 1

    if static_count and dynamic_count:
        return XtsProjectSurfaceProfile(
            surface=MIXED,
            variant=BOTH,
            supported_surfaces=(DYNAMIC, STATIC),
            static_file_count=static_count,
            dynamic_file_count=dynamic_count,
            utility_file_count=utility_count,
        )
    if static_count:
        return XtsProjectSurfaceProfile(
            surface=STATIC,
            variant=STATIC,
            supported_surfaces=(STATIC,),
            static_file_count=static_count,
            dynamic_file_count=dynamic_count,
            utility_file_count=utility_count,
        )
    if dynamic_count:
        return XtsProjectSurfaceProfile(
            surface=DYNAMIC,
            variant=DYNAMIC,
            supported_surfaces=(DYNAMIC,),
            static_file_count=static_count,
            dynamic_file_count=dynamic_count,
            utility_file_count=utility_count,
        )
    return XtsProjectSurfaceProfile(
        surface=UNKNOWN,
        variant=UNKNOWN,
        supported_surfaces=(),
        static_file_count=static_count,
        dynamic_file_count=dynamic_count,
        utility_file_count=utility_count,
    )


def classify_ace_engine_surface(path: Path, text: str = "") -> AceEngineSurfaceProfile:
    rel = str(path).replace("\\", "/").lower()
    path_tokens = {compact_token(part) for part in tokenize_surface_text(rel) if compact_token(part)}

    if "/frameworks/bridge/" in rel:
        if "koala_projects/" in rel or "/arkoala-arkts/" in rel or "/generated/component/" in rel:
            return AceEngineSurfaceProfile(surface=STATIC, layer="koala_generated_component", reasons=["koala-generated component"])
        return AceEngineSurfaceProfile(surface=DYNAMIC, layer="bridge", reasons=["frameworks/bridge layer"])
    if "/interfaces/ets/ani/" in rel:
        return AceEngineSurfaceProfile(surface=DYNAMIC, layer="ani", reasons=["interfaces/ets/ani layer"])

    layer = "other"
    if "/frameworks/core/interfaces/native/" in rel:
        layer = "core_interfaces"
    elif "/frameworks/core/components_ng/pattern/" in rel and "/bridge/" in rel:
        layer = "components_ng_bridge"
    elif "/frameworks/core/components_ng/pattern/" in rel:
        layer = "components_ng_backend"

    if layer == "components_ng_backend":
        return AceEngineSurfaceProfile(surface=COMMON, layer=layer, reasons=["components_ng backend layer"])

    static_score = 0
    dynamic_score = 0
    reasons: list[str] = []

    if "static" in path_tokens:
        static_score += 3
        reasons.append("path static token")
    if "dynamic" in path_tokens:
        dynamic_score += 3
        reasons.append("path dynamic token")
    if layer == "components_ng_bridge":
        dynamic_score += 1
        reasons.append("components_ng bridge adapter")

    if text:
        if STATIC_INCLUDE_RE.search(text):
            static_score += 2
            reasons.append("static includes")
        if STATIC_GENERATED_RE.search(text):
            static_score += 2
            reasons.append("static generated symbol")
        if STATIC_IDENTIFIER_RE.search(text):
            static_score += 1
            reasons.append("static identifiers")
        if DYNAMIC_HELPER_RE.search(text):
            dynamic_score += 1
            reasons.append("dynamic helper usage")
        if DYNAMIC_IDENTIFIER_RE.search(text):
            dynamic_score += 1
            reasons.append("dynamic identifiers")

    if static_score and static_score >= dynamic_score + 2:
        return AceEngineSurfaceProfile(surface=STATIC, layer=layer, reasons=reasons)
    if dynamic_score and dynamic_score >= static_score + 2:
        return AceEngineSurfaceProfile(surface=DYNAMIC, layer=layer, reasons=reasons)
    if static_score or dynamic_score:
        return AceEngineSurfaceProfile(surface=COMMON, layer=layer, reasons=reasons)
    return AceEngineSurfaceProfile(surface=UNKNOWN, layer=layer, reasons=reasons)


def surface_to_variants_mode(surface: str) -> str:
    if surface == STATIC:
        return STATIC
    if surface == DYNAMIC:
        return DYNAMIC
    return BOTH


def parse_query_surface_intent(query: str) -> QuerySurfaceIntent:
    lowered = query.lower()
    tokens = {compact_token(part) for part in tokenize_surface_text(lowered) if compact_token(part)}
    reasons: list[str] = []
    if "dynamic" in tokens or re.search(r"""\b1\.1\b""", lowered):
        reasons.append("explicit dynamic/1.1 query hint")
        return QuerySurfaceIntent(requested_surface=DYNAMIC, reasons=reasons)
    if "static" in tokens or re.search(r"""\b1\.2\b""", lowered):
        reasons.append("explicit static/1.2 query hint")
        return QuerySurfaceIntent(requested_surface=STATIC, reasons=reasons)
    return QuerySurfaceIntent(requested_surface=BOTH, reasons=reasons)
