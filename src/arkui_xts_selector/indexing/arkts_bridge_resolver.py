"""ArkTS bridge resolver for Koala/Arkoala generated and authored files.

Handles three categories of bridge files:
1. Generated component bridges: koala_projects/.../generated/component/<name>.ets
2. Authored component bridges: koala_projects/.../src/component/<name>.ets
3. Generic/utility bridge files: common.ets, builder.ets, enums.ets, etc.

Returns typed ImpactCandidate objects, not raw XTS directory selections.
"""
from __future__ import annotations

import re
from typing import Optional

# Path patterns for Koala/Arkoala bridge files
_GENERATED_COMPONENT_RE = re.compile(
    r"arkts_frontend/koala_projects/[^/]+/[^/]+/generated/component/([\w]+)\.ets$"
)

_AUTHORED_COMPONENT_RE = re.compile(
    r"arkts_frontend/koala_projects/[^/]+/[^/]+/src/component/([\w]+)\.ets$"
)

# Koala projects expansion patterns (Sprint D.1)
_KOALA_ARKUI_COMPONENT_RE = re.compile(
    r"frameworks/bridge/arkts_frontend/koala_projects/[^/]+/arkui-component/.*?/component/(\w+)\.ets$"
)
_KOALA_GENERATED_MODIFIER_RE = re.compile(
    r"frameworks/bridge/arkts_frontend/koala_projects/[^/]+/arkui-(?:component|ohos)/generated/.*?(\w+)Modifier\.ets$"
)
_KOALA_INTERFACE_RE = re.compile(
    r"frameworks/bridge/arkts_frontend/koala_projects/[^/]+/arkui-(?:component|ohos|common)/.*?/interface/(\w+)\.(?:ets|d\.ets)$"
)

# Generic files that affect all components, not a single one
_GENERIC_BRIDGE_FILES = frozenset({
    "common.ets", "Common.ets",
    "builder.ets", "Builder.ets",
    "enums.ets", "Enums.ets",
    "units.ets",
    "resources.ets", "Resources.ets",
    "idlize.ets",
    "component_storage.ets",
    "componentDrawered.ets",
    "componentUtils.ets",
    "peerModel.ets",
    "staticCommon.ets",
    "typePeers.ets",
    "ArkCommonProps.ets",
    "ArkComponent.ets",
    "ArkStructCommon.ets",
})

# Family name normalization: camelCase component name -> snake_case family
_CAMEL_TO_SNAKE_PATTERNS = [
    (re.compile(r"([a-z])([A-Z])"), r"\1_\2"),  # camelCase -> camel_Case
]


def _normalize_family(name: str) -> str:
    """Normalize camelCase component name to snake_case family key.

    Examples:
        dynamicComponent -> dynamic_component
        symbolglyph -> symbolglyph (already lowercase)
        textInput -> text_input
        menuItem -> menu_item
    """
    result = name
    for pattern, replacement in _CAMEL_TO_SNAKE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result.lower()


def _camel_to_snake(name: str) -> str:
    """RichEditor → rich_editor; ButtonAttribute → button_attribute."""
    s = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
    return s


def resolve_arkts_bridge_candidate(file_path: str) -> Optional["ImpactCandidate"]:
    """Resolve an ArkTS bridge file to a typed impact candidate.

    Args:
        file_path: Absolute or relative path to the bridge file.

    Returns:
        ImpactCandidate with appropriate impact_kind, family, and risk level,
        or None if the file is not a recognized bridge file.
    """
    from arkui_xts_selector.indexing.impact import ImpactCandidate

    # Koala expansion patterns (Sprint D.1) - check first as they are more specific
    # Koala component .ets files
    m = _KOALA_ARKUI_COMPONENT_RE.search(file_path)
    if m:
        family_camel = m.group(1)
        family = _camel_to_snake(family_camel)
        return ImpactCandidate(
            changed_file=file_path,
            impact_kind="koala_component_bridge",
            family=family,
            source_confidence="weak",
            provenance="path_rule",
            parser_level=1,
            relation_scope="family",
            false_negative_risk="high",
        )

    # Koala generated modifier .ets files
    m = _KOALA_GENERATED_MODIFIER_RE.search(file_path)
    if m:
        family_camel = m.group(1)
        family = _camel_to_snake(family_camel)
        return ImpactCandidate(
            changed_file=file_path,
            impact_kind="koala_generated_bridge",
            family=family,
            source_confidence="weak",
            provenance="path_rule",
            parser_level=1,
            relation_scope="family",
            false_negative_risk="high",
        )

    # Koala interface .ets/.d.ets files
    m = _KOALA_INTERFACE_RE.search(file_path)
    if m:
        family_camel = m.group(1)
        family = _camel_to_snake(family_camel)
        return ImpactCandidate(
            changed_file=file_path,
            impact_kind="koala_interface_bridge",
            family=family,
            source_confidence="weak",
            provenance="path_rule",
            parser_level=1,
            relation_scope="family",
            false_negative_risk="high",
        )

    # Check generated component bridge
    m = _GENERATED_COMPONENT_RE.search(file_path)
    if m:
        component_name = m.group(1)
        basename = component_name.split("/")[-1] + ".ets"

        # Check if it's a generic utility file
        if basename in _GENERIC_BRIDGE_FILES:
            return ImpactCandidate(
                changed_file=file_path,
                impact_kind="broad_infrastructure",
                family=None,
                source_confidence="weak",
                provenance="path_rule",
                parser_level=1,
                relation_scope="generic",
                false_negative_risk="critical",
                unresolved_reason="generic_bridge_file_affects_multiple_components",
            )

        family = _normalize_family(component_name)
        return ImpactCandidate(
            changed_file=file_path,
            impact_kind="generated_bridge",
            family=family,
            source_confidence="weak",
            provenance="path_rule",
            parser_level=1,
            relation_scope="family",
            false_negative_risk="high",
        )

    # Check authored component bridge
    m = _AUTHORED_COMPONENT_RE.search(file_path)
    if m:
        component_name = m.group(1)
        basename = component_name.split("/")[-1] + ".ets"

        if basename in _GENERIC_BRIDGE_FILES:
            return ImpactCandidate(
                changed_file=file_path,
                impact_kind="broad_infrastructure",
                family=None,
                source_confidence="weak",
                provenance="path_rule",
                parser_level=1,
                relation_scope="generic",
                false_negative_risk="critical",
                unresolved_reason="generic_authored_bridge_file",
            )

        family = _normalize_family(component_name)
        return ImpactCandidate(
            changed_file=file_path,
            impact_kind="authored_bridge",
            family=family,
            source_confidence="medium",
            provenance="path_rule",
            parser_level=1,
            relation_scope="family",
            false_negative_risk="high",
        )

    return None
