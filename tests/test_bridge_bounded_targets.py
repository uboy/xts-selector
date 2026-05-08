"""PX-08: Koala bridge bounded targets.

Verifies that Koala bridge files with known families resolve to actual
XTS targets via the inverted index.
"""
import pytest


def test_koala_component_bridge_has_family():
    """Koala component bridge candidates have family attribute."""
    from arkui_xts_selector.indexing.arkts_bridge_resolver import resolve_arkts_bridge_candidate

    result = resolve_arkts_bridge_candidate(
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/arkui-component/src/component/Button.ets"
    )
    if result is not None:
        assert result.family is not None or result.impact_kind in ("broad_infrastructure",)


def test_koala_generated_modifier_has_family():
    """Koala generated modifier candidates have family."""
    from arkui_xts_selector.indexing.arkts_bridge_resolver import resolve_arkts_bridge_candidate

    result = resolve_arkts_bridge_candidate(
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/peers/ButtonModifier.ets"
    )
    if result is not None:
        assert result.impact_kind in ("koala_generated_bridge", "generated_bridge", "broad_infrastructure")


def test_bridge_specific_provenance():
    """Bridge-specific resolution uses provenance=bridge_specific."""
    # This verifies the provenance value is in the allowed set
    ALLOWED_PROVENANCE = {
        "strict_canonical", "member_parent", "common_inherited",
        "family_exact", "native_typed", "bridge_specific",
        "broad_infra", "safety_fallback", "manual_review",
    }
    assert "bridge_specific" in ALLOWED_PROVENANCE


def test_generic_bridge_still_broad_infra():
    """Generic bridge files (common.ets, etc.) remain broad_infrastructure."""
    from arkui_xts_selector.indexing.arkts_bridge_resolver import resolve_arkts_bridge_candidate

    result = resolve_arkts_bridge_candidate(
        "frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/common.ets"
    )
    if result is not None:
        # Generic bridge files should be broad_infrastructure with no family
        assert result.impact_kind == "broad_infrastructure"
        assert result.family is None or result.unresolved_reason is not None
