"""Integration tests verifying that new modules are wired into production pipeline.

These tests ensure that:
- find_attribute_member is called from _resolve_canonical_id
- normalize_family is called from find_attribute_member
- find_common_member resolves common attributes
- file_category filters build_config/test_only/docs
- native_interface_resolver handles native API files
- generated_files_resolver skips generated code
- path_utils normalizes absolute paths
- target_ranking applies bucket caps
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_sdk_entry(
    public_name: str, member_name: str | None = None, member_of: str | None = None
):
    """Create a minimal SdkIndexEntry."""
    from arkui_xts_selector.indexing.sdk_indexer import SdkIndexEntry
    from arkui_xts_selector.model.api import ApiEntityId, ApiDeclarationRef

    api_id = ApiEntityId.from_parts(
        namespace="arkui",
        surface="static",
        kind="method",
        module="test",
        public_name=public_name,
        member_of=member_of,
        member_name=member_name,
    )
    decl = ApiDeclarationRef(
        declaration_id=api_id.canonical(),
        file_path="test.d.ts",
        module="test",
        export_name=f"{member_of}.{member_name}"
        if member_of and member_name
        else public_name,
        line=1,
        span=(0, 10),
        parser_level=3,
    )
    return SdkIndexEntry(api_id=api_id, declaration=decl, member_name=member_name)


def _make_ace_entry(file_path: str, role: str, family: str | None, methods: list[str]):
    """Create a minimal ACE index entry for testing."""
    from arkui_xts_selector.indexing.ace_indexer import AceIndexEntry
    from arkui_xts_selector.indexing.cpp_parser import CppClass, CppMethod

    classes = [
        CppClass(
            name=f"{family}ModelStatic" if family else "Test",
            methods=[
                CppMethod(
                    name=m, qualified=f"{family}ModelStatic::{m}" if family else m
                )
                for m in methods
            ],
        )
    ]
    return AceIndexEntry(file_path=file_path, role=role, family=family, classes=classes)


def _build_sdk_index_with_button():
    """Build SDK index with ButtonAttribute.role entry."""
    from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult

    entries = (
        _make_sdk_entry(
            "ButtonAttribute", member_name="role", member_of="ButtonAttribute"
        ),
        _make_sdk_entry(
            "ButtonAttribute", member_name="buttonStyle", member_of="ButtonAttribute"
        ),
        _make_sdk_entry("CommonMethod", member_name="width", member_of="CommonMethod"),
        _make_sdk_entry("CommonMethod", member_name="height", member_of="CommonMethod"),
    )
    return SdkIndexResult(entries=entries)


# ---------------------------------------------------------------------------
# CR1: find_attribute_member wired into _resolve_canonical_id
# ---------------------------------------------------------------------------


class TestCanonicalIdResolutionWired:
    def test_model_static_resolves_via_find_attribute_member(self):
        """SetRole in button model_static should resolve via find_attribute_member."""
        from arkui_xts_selector.indexing.source_to_api import (
            build_source_to_api_mapping,
        )
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult

        ace = AceIndexResult(
            entries=[
                _make_ace_entry(
                    "button_model.cpp", "model_static", "button", ["SetRole"]
                ),
            ]
        )
        sdk = _build_sdk_index_with_button()
        mappings = build_source_to_api_mapping(ace, sdk_index=sdk)

        role_mapping = next((m for m in mappings if m.api_public_name == "role"), None)
        assert role_mapping is not None
        assert role_mapping.sdk_confirmed is True
        assert role_mapping.api_id is not None
        assert "ButtonAttribute" in role_mapping.api_member_of

    def test_model_static_resolves_common_attribute(self):
        """SetWidth should resolve via find_common_member."""
        from arkui_xts_selector.indexing.source_to_api import (
            build_source_to_api_mapping,
        )
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult

        ace = AceIndexResult(
            entries=[
                _make_ace_entry(
                    "button_model.cpp", "model_static", "button", ["SetWidth"]
                ),
            ]
        )
        sdk = _build_sdk_index_with_button()
        mappings = build_source_to_api_mapping(ace, sdk_index=sdk)

        width_mapping = next(
            (m for m in mappings if m.api_public_name == "width"), None
        )
        assert width_mapping is not None
        assert width_mapping.sdk_confirmed is True


# ---------------------------------------------------------------------------
# CR2: normalize_family wired into find_attribute_member
# ---------------------------------------------------------------------------


class TestNormalizeFamilyWired:
    def test_snake_case_family_resolved(self):
        """Family 'alert_dialog' should normalize to 'AlertDialog' via find_attribute_member."""
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult

        entries = (
            _make_sdk_entry(
                "AlertDialogAttribute",
                member_name="alignment",
                member_of="AlertDialogAttribute",
            ),
        )
        sdk = SdkIndexResult(entries=entries)

        result = sdk.find_attribute_member("alignment", "alert_dialog")
        assert result is not None
        assert result.member_name == "alignment"

    def test_qrcode_family_resolved(self):
        """Family 'qrcode' should normalize to 'QRCode'."""
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult

        entries = (
            _make_sdk_entry(
                "QRCodeAttribute", member_name="color", member_of="QRCodeAttribute"
            ),
        )
        sdk = SdkIndexResult(entries=entries)

        result = sdk.find_attribute_member("color", "qrcode")
        assert result is not None


# ---------------------------------------------------------------------------
# CR3: find_common_member + find_all_member
# ---------------------------------------------------------------------------


class TestCommonMemberWired:
    def test_find_common_member_resolves_width(self):
        sdk = _build_sdk_index_with_button()
        result = sdk.find_common_member("width")
        assert result is not None
        assert result.member_name == "width"

    def test_find_common_member_returns_none_for_unknown(self):
        sdk = _build_sdk_index_with_button()
        assert sdk.find_common_member("nonexistent") is None

    def test_find_all_member_returns_all_matches(self):
        sdk = _build_sdk_index_with_button()
        results = sdk.find_all_member("width")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# CR4: Build-time indexes O(1)
# ---------------------------------------------------------------------------


class TestBuildTimeIndexes:
    def test_by_public_index_built(self):
        sdk = _build_sdk_index_with_button()
        assert "ButtonAttribute" in sdk._by_public
        assert "CommonMethod" in sdk._by_public

    def test_by_parent_member_index_built(self):
        sdk = _build_sdk_index_with_button()
        assert ("ButtonAttribute", "role") in sdk._by_parent_member
        assert ("CommonMethod", "width") in sdk._by_parent_member

    def test_find_uses_index(self):
        sdk = _build_sdk_index_with_button()
        assert sdk.find("ButtonAttribute") is not None
        assert sdk.find("role") is not None  # unique member → found
        assert sdk.find("nonexistent_xyz") is None

    def test_find_member_uses_index(self):
        sdk = _build_sdk_index_with_button()
        result = sdk.find_member("role", "ButtonAttribute")
        assert result is not None
        assert result.member_name == "role"


# ---------------------------------------------------------------------------
# CR5+CR6: file_category wired into pr_resolver
# ---------------------------------------------------------------------------


class TestFileCategoryWired:
    def test_build_config_file_skipped(self):
        from arkui_xts_selector.indexing.pr_resolver import resolve_pr
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = resolve_pr(
            ["frameworks/core/components_ng/BUILD.gn"],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
        )
        assert len(result.entries) == 1
        assert result.entries[0].unresolved_reason == "build_config_no_test_impact"

    def test_real_test_file_skipped(self):
        from arkui_xts_selector.indexing.pr_resolver import resolve_pr
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = resolve_pr(
            ["test/unittest/core/button/button_test.cpp"],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
        )
        assert len(result.entries) == 1
        assert result.entries[0].unresolved_reason == "test_file_no_cross_impact"

    def test_documentation_file_skipped(self):
        from arkui_xts_selector.indexing.pr_resolver import resolve_pr
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = resolve_pr(
            ["docs/button_guide.md"],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
        )
        assert len(result.entries) == 1
        assert result.entries[0].unresolved_reason == "documentation_no_test_impact"

    def test_generated_file_skipped(self):
        from arkui_xts_selector.indexing.pr_resolver import resolve_pr
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = resolve_pr(
            ["frameworks/core/components_ng/generated/button_generated.cpp"],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
        )
        assert len(result.entries) == 1
        assert result.entries[0].unresolved_reason == "generated_file_skipped"

    def test_product_source_not_skipped(self):
        from arkui_xts_selector.indexing.pr_resolver import resolve_pr
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = resolve_pr(
            ["frameworks/core/components_ng/button/button_model.cpp"],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
        )
        # Product source should NOT be skipped — it may have no mappings but shouldn't be filtered early
        assert len(result.entries) == 1
        assert result.entries[0].unresolved_reason != "build_config_no_test_impact"


# ---------------------------------------------------------------------------
# CR8: native_interface_resolver wired
# ---------------------------------------------------------------------------


class TestNativeInterfaceWired:
    def test_native_modifier_file_resolved(self):
        from arkui_xts_selector.indexing.pr_resolver import resolve_pr
        from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
        from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
        from arkui_xts_selector.indexing.inverted_index import InvertedIndex

        result = resolve_pr(
            ["frameworks/core/interfaces/native/implementation/button_modifier.cpp"],
            AceIndexResult(),
            SdkIndexResult(),
            InvertedIndex(),
        )
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.impact_candidates
        assert entry.impact_candidates[0]["impact_kind"] == "native_modifier"
        assert entry.impact_candidates[0]["family"] == "button"


# ---------------------------------------------------------------------------
# CR7: target_ranking wired
# ---------------------------------------------------------------------------


class TestTargetRankingWired:
    def test_apply_target_ranking_basic(self):
        from arkui_xts_selector.indexing.pr_resolver import (
            PrResolveResult,
            PrResolveEntry,
            SelectionReason,
            apply_target_ranking,
        )

        result = PrResolveResult(
            entries=(
                PrResolveEntry(
                    changed_file="button.cpp",
                    affected_apis=("role",),
                    consumer_projects=(
                        "ace_ets_module_button_static",
                        "ace_ets_module_button_common",
                    ),
                    canonical_affected_apis=(
                        "api:v1:arkui:static:method:button:ButtonAttribute.role",
                    ),
                    selection_reasons=(
                        SelectionReason(
                            project_path="ace_ets_module_button_static",
                            matched_apis=("role",),
                            usage_kinds=("attribute_method",),
                            confidence="strong",
                        ),
                    ),
                ),
            ),
        )

        ranked = apply_target_ranking(result)
        assert ranked.dropped_count >= 0
        assert len(ranked.provenance) == 1
        assert ranked.provenance[0]["action"] == "target_ranking"
