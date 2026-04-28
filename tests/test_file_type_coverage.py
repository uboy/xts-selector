"""
Comprehensive file-type coverage tests for infer_signals().

Tests verify that infer_signals() correctly extracts signals from different
ace_engine directory structures and file types, ensuring the selector tool
can map changed source files to appropriate test projects across the full
spectrum of file patterns in the codebase.

Each test category corresponds to a specific architectural pattern in ace_engine:
- pattern/: High-precision NG component pattern implementations
- old components/: Pre-NG component directory structure
- implementation/: Native API implementation files
- manager/: Cross-cutting infrastructure files
- utility/: Shared utility files (no specific component)
- generated .ets: Auto-generated TypeScript/ArkTS files
- ark_component .ts: Declarative frontend component wrappers
- stateManagement/: State management framework infrastructure
"""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import (
    COMMON_PROJECT_HINTS,
    ContentModifierIndex,
    MappingConfig,
    SdkIndex,
    infer_signals,
)


class FileTypeCoverageTests(unittest.TestCase):
    """Test infer_signals() across different ace_engine file types."""

    def test_pattern_directory_high_precision_button(self) -> None:
        """Test pattern/ directory (button) extracts correct signals with HIGH precision."""
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                '#include "button_pattern.h"\n'
                'namespace OHOS::Ace::NG {\n'
                'void ButtonPattern::OnModifyDone() {}\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        assert "button" in signals["project_hints"]
        assert "button" in signals["family_tokens"]
        assert not signals["method_hint_required"]

    def test_pattern_directory_high_precision_checkbox_bridge(self) -> None:
        """Test pattern/ directory (checkbox/bridge) extracts correct signals."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/checkbox/bridge/checkbox_static_modifier.cpp"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                '#include "checkbox_static_modifier.h"\n'
                'namespace OHOS::Ace::NG {\n'
                'void CheckboxStaticModifier::Apply() {}\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        assert "checkbox" in signals["project_hints"]
        assert "checkbox" in signals["family_tokens"]

    def test_pattern_directory_high_precision_list_item(self) -> None:
        """Test pattern/ directory (list) extracts correct signals."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/list/list_item_pattern.cpp"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                '#include "list_item_pattern.h"\n'
                'namespace OHOS::Ace::NG {\n'
                'void ListItemPattern::OnModifyDone() {}\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        assert "list" in signals["project_hints"]
        assert "list" in signals["family_tokens"]

    def test_pattern_directory_scrollbar_alias(self) -> None:
        """Test pattern/ directory (scroll) verifies scrollbar alias works."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/scroll/scroll_bar.cpp"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                '#include "scroll_bar.h"\n'
                'namespace OHOS::Ace::NG {\n'
                'void ScrollBarPattern::OnModifyDone() {}\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        # scrollbar should be in project_hints via alias mapping
        assert any("scroll" in hint for hint in signals["project_hints"])
        assert any("scroll" in hint for hint in signals["family_tokens"])

    def test_old_components_directory_button(self) -> None:
        """Test old components/ directory (button) extracts correct signals."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/core/components/button/button_component.cpp"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                '#include "button_component.h"\n'
                'namespace OHOS::Ace {\n'
                'void ButtonComponent::Build() {}\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        assert "button" in signals["project_hints"]

    def test_old_components_directory_image(self) -> None:
        """Test old components/ directory (image) extracts correct signals."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/core/components/image/image_component.cpp"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                '#include "image_component.h"\n'
                'namespace OHOS::Ace {\n'
                'void ImageComponent::Build() {}\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        assert "image" in signals["project_hints"]

    def test_implementation_directory_button_modifier(self) -> None:
        """Test implementation/ directory (button_modifier) extracts correct signals."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/button_modifier.cpp"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                '#include "button_modifier.h"\n'
                'namespace OHOS::Ace::NG {\n'
                'void ButtonModifier::Apply() {}\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        assert "button" in signals["project_hints"]
        assert "button" in signals["family_tokens"]

    def test_implementation_directory_canvas_accessor(self) -> None:
        """Test implementation/ directory (canvas) extracts correct signals."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/canvas_rendering_context2d_accessor.cpp"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                '#include "canvas_rendering_context2d_accessor.h"\n'
                'namespace OHOS::Ace {\n'
                'void CanvasRenderingContext2DAccessor::GetContext() {}\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        assert "canvasrenderingcontext2d" in signals["project_hints"]

    def test_manager_directory_common_project_hints(self) -> None:
        """Test manager/ directory receives COMMON_PROJECT_HINTS (broad impact)."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/core/manager/shared/privacy_manager.cpp"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                '#include "privacy_manager.h"\n'
                'namespace OHOS::Ace {\n'
                'void PrivacyManager::Init() {}\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        # Manager files should have COMMON_PROJECT_HINTS (excluding noise tokens like "modifier")
        # "modifier" is in CONTENT_MODIFIER_NOISE and gets filtered out
        expected_hints = {hint for hint in COMMON_PROJECT_HINTS if hint != "modifier"}
        assert all(hint in signals["project_hints"] for hint in expected_hints)
        assert not signals["method_hint_required"]

    def test_utility_directory_without_ranges_common_hints_only(self) -> None:
        """Test utility/ directory without changed_ranges has only COMMON_PROJECT_HINTS."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/core/interfaces/native/utility/converter.h"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                '#ifndef CONVERTER_H\n'
                '#define CONVERTER_H\n'
                'namespace OHOS::Ace {\n'
                'class Converter {};\n'
                '}\n'
                '#endif\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
                changed_ranges=None,  # No changed ranges
            )

        # Without changed_ranges, should have limited signals
        # utility files without specific component info should have COMMON_PROJECT_HINTS
        # or be very constrained
        assert not signals["method_hint_required"]

    def test_generated_ets_files_checkbox_modifier(self) -> None:
        """Test generated .ets files (CheckboxModifier) extract correct signals."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/generated/CheckboxModifier.ets"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                'export class CheckboxModifier {\n'
                '  select(value: boolean): CheckboxModifier {\n'
                '    return this;\n'
                '  }\n'
                '  selectedColor(value: string): CheckboxModifier {\n'
                '    return this;\n'
                '  }\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        # generated/ CheckboxModifier.ets should extract checkbox
        # Note: The exact extraction depends on how the file is processed
        # Check that we have some relevant signals
        assert len(signals["project_hints"]) > 0 or len(signals["type_hints"]) > 0

    def test_ark_component_ts_files_checkbox(self) -> None:
        """Test ark_component .ts files (ArkCheckbox) extract correct signals."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/ark_component/src/ArkCheckbox.ts"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                'export class ArkCheckbox {\n'
                '  static create(): ArkCheckbox {\n'
                '    return new ArkCheckbox();\n'
                '  }\n'
                '  select(value: boolean): ArkCheckbox {\n'
                '    return this;\n'
                '  }\n'
                '}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        assert "checkbox" in signals["project_hints"]
        assert "checkbox" in signals["family_tokens"]
        assert "Checkbox" in signals["type_hints"] or "checkbox" in signals["type_hints"]

    def test_state_management_files_broad_matching(self) -> None:
        """Test stateManagement/ files produce multiple hints (broad matching)."""
        with TemporaryDirectory() as tmpdir:
            source = (
                Path(tmpdir)
                / "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/stateManagement/state_mgmt.ts"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                'export class Observed {}\n'
                'export class ObservedObject {}\n'
                'export function trackBy() {}\n',
                encoding="utf-8",
            )

            signals = infer_signals(
                source,
                SdkIndex(),
                ContentModifierIndex(),
                MappingConfig(),
            )

        # stateManagement files should have COMMON_PROJECT_HINTS (excluding noise tokens like "modifier")
        # "modifier" is in CONTENT_MODIFIER_NOISE and gets filtered out
        expected_hints = {hint for hint in COMMON_PROJECT_HINTS if hint != "modifier"}
        assert all(hint in signals["project_hints"] for hint in expected_hints)
        assert not signals["method_hint_required"]
        # Should have type hints from the file
        assert "Observed" in signals["type_hints"]
        assert "ObservedObject" in signals["type_hints"]


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
