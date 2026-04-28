# ArkUI ACE Engine Directory Catalog

This document catalogs the major directories in the `arkui/ace_engine` repository, explaining their contents, their role in the ArkUI framework, and how the XTS selector processes files from each directory.

**Target Path**: `/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine/`

**Selector Reference**: `/data/shared/common/projects/ohos-helper/arkui-xts-selector/src/arkui_xts_selector/cli.py`

---

## Core Framework Directories

### `frameworks/core/components_ng/pattern/`

**Contents**: Component pattern implementations for the new NG (Next Generation) architecture. Each subdirectory contains the complete implementation of a single UI component including:
- Pattern classes (e.g., `button_pattern.h`, `button_pattern.cpp`)
- Model files (e.g., `button_model_ng.h`, `button_model_ng.cpp`)
- Event handlers (e.g., `button_event_hub.h`)
- Layout algorithms (e.g., `button_layout_algorithm.h`)
- Property definitions (e.g., `button_layout_property.h`)

Examples of components: `button/`, `text/`, `list/`, `grid/`, `image/`, `canvas/`, `slider/`, `checkbox/`, `swiper/`, `navigation/`, `tabs/`, etc.

**Framework role**: This is the heart of ArkUI's component system. Each pattern implements the complete lifecycle and behavior of a UI component in the NG architecture, including rendering, event handling, layout, and property management.

**Selector handling**: **HIGH PRIORITY - PRIMARY SIGNAL SOURCE**
- **Signal extraction method**: Path-based regex matching: `components_ng/pattern/{component}/`
- **Signal types generated**:
  - `project_hints`: Component name in compact form (e.g., `button` from `button/`)
  - `family_tokens`: Component name
  - `type_hints`: Component class names via `pattern_alias` mapping (e.g., `Button`, `ButtonModifier`, `Toggle`)
  - `symbols`: Component and modifier symbols from SDK index and pattern_alias
- **Priority/confidence**: Very high - deterministic path-based resolution
- **Known gaps or issues**: None significant

**Examples**:
- `frameworks/core/components_ng/pattern/button/button_pattern.h`
- `frameworks/core/components_ng/pattern/text/text_pattern.h`
- `frameworks/core/components_ng/pattern/navigation/navigation_pattern.h`

---

### `frameworks/core/interfaces/native/implementation/`

**Contents**: Native C++ implementation files for component modifiers and accessors. Files follow naming conventions:
- `{component}_modifier.cpp` - Modifier implementations (e.g., `button_modifier.cpp`)
- `{component}_ops_accessor.cpp` - Operation accessors (e.g., `text_input_ops_accessor.cpp`)
- `{component}_extender_accessor.cpp` - Extender accessors (e.g., `list_extender_accessor.cpp`)
- `{component}_accessor.cpp` - General accessors (e.g., `alert_dialog_accessor.cpp`)
- Base files: `common_method`, `base_event`, `base_gesture_event` (excluded)

**Framework role**: Provides the native C++ API layer that bridges ArkTS/JavaScript components to the underlying C++ implementation. These files handle attribute conversion, native method calls, and parameter marshaling.

**Selector handling**: **HIGH PRIORITY - PRIMARY SIGNAL SOURCE**
- **Signal extraction method**: Path-based regex matching on filename patterns
  - `{name}_modifier.cpp` → `{name}`
  - `{name}_ops_accessor.cpp` → `{name}`
  - `{name}_extender_accessor.cpp` → `{name}`
- **Signal types generated**:
  - `project_hints`: Component name
  - `family_tokens`: Component name
  - `type_hints`: Component class names via pattern_alias
  - `symbols`: Component and modifier symbols
- **Priority/confidence**: High - deterministic filename-based resolution
- **Known gaps or issues**: Excludes common base files which may affect multiple components

**Examples**:
- `frameworks/core/interfaces/native/implementation/button_modifier.cpp`
- `frameworks/core/interfaces/native/implementation/text_input_ops_accessor.cpp`
- `frameworks/core/interfaces/native/implementation/list_extender_accessor.cpp`

---

### `frameworks/core/interfaces/native/utility/`

**Contents**: Shared utility files used across multiple components. Key files include:
- `converter.h` / `converter.cpp` - Type conversion utilities (ArkTS ↔ C++)
- `converter_enums.cpp` - Enum conversions
- `converter_union.h` - Union type handling
- `accessor_utils.h` / `accessor_utils.cpp` - Accessor helper functions
- `callback_helper.h` / `callback_helper.cpp` - Callback management
- `ace_engine_types.h` - Common type definitions
- `peer_utils.cpp` - Peer node utilities

**Framework role**: Provides shared infrastructure for type conversion, callback handling, and API bridging. These utilities are used by virtually all component implementations.

**Selector handling**: **HIGH PRIORITY - REVERSE TRACING**
- **Signal extraction method**: Tree-sitter C++ AST parsing + reverse call tracing
- **Signal types generated**:
  - `project_hints`: Component names derived from tracing (via `trace_shared_file_to_components`)
  - `family_tokens`: Component names
  - `method_hints`: SDK method names from traced SetXxxImpl functions
  - `member_hints`: Exact attribute paths (e.g., `CheckboxAttribute.selectedColor`)
  - `method_hint_required`: Set to true when methods are traced
- **Priority/confidence**: High for traced components, but depends on tree-sitter availability
- **Known gaps or issues**:
  - Requires tree-sitter C++ parser to be installed
  - Only traces if changed_ranges are provided or file is a converter
  - Performance overhead for large files
  - May miss indirect dependencies

**Examples**:
- `frameworks/core/interfaces/native/utility/converter.h`
- `frameworks/core/interfaces/native/utility/callback_helper.h`
- `frameworks/core/interfaces/native/utility/ace_engine_types.h`

---

### `frameworks/core/interfaces/native/common/`

**Contents**: Common native API implementations shared across components. Contains base classes and common functionality for the native API layer.

**Framework role**: Provides foundational native API infrastructure used by multiple components.

**Selector handling**: **HIGH PRIORITY - REVERSE TRACING**
- **Signal extraction method**: Same as utility/ - tree-sitter C++ AST parsing + reverse call tracing
- **Signal types generated**: Same as utility/ via `trace_shared_file_to_components`
- **Priority/confidence**: Same as utility/
- **Known gaps or issues**: Same as utility/

**Examples**:
- `frameworks/core/interfaces/native/common/node_api.cpp`
- `frameworks/core/interfaces/native/common/native_module.cpp`

---

## Bridge / Frontend Directories

### `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/`

**Contents**: Auto-generated TypeScript component files from the Arkoala code generation system. Each file contains:
- Component class definition (e.g., `ArkButtonComponent`)
- Peer class (e.g., `ArkButtonPeer`)
- Attribute setter methods (e.g., `setBackgroundColorAttribute`)
- Serialization/deserialization logic
- Integration with theme system

Files are generated and should NOT be manually edited (header comment: "WARNING! THIS FILE IS AUTO-GENERATED, DO NOT MAKE CHANGES, THEY WILL BE LOST ON NEXT GENERATION!")

**Framework role**: These files provide the TypeScript API surface for ArkUI components in the ArkTS frontend. They implement the bridge between ArkTS code and native C++ implementations via serialization and peer nodes.

**Selector handling**: **HIGH PRIORITY - METHOD-LEVEL TRACING**
- **Signal extraction method**: Tree-sitter TypeScript AST parsing for method-level analysis
- **Signal types generated**:
  - `project_hints`: Component name from path (e.g., `button` from `button.ets`)
  - `family_tokens`: Component name
  - `type_hints`: Component class names via pattern_alias
  - `method_hints`: SDK method names extracted from changed methods
  - `member_hints`: Exact attribute paths (e.g., `ButtonAttribute.backgroundColor`)
  - `method_hint_required`: Set to true when methods are traced
- **Priority/confidence**: Very high for method-level changes
- **Known gaps or issues**:
  - Requires tree-sitter TypeScript parser
  - Only processes files matching `/generated/component/*.ets` pattern
  - Excludes internal methods (setXxxAttribute, constructor, etc.)
  - Performance overhead for large generated files

**Examples**:
- `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/button.ets`
- `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/text.ets`
- `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/list.ets`

---

### `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/component/`

**Contents**: Core hand-written TypeScript component files that complement the generated files. Contains base component classes and utilities.

**Framework role**: Provides handwritten TypeScript logic for components that cannot be auto-generated, including custom behaviors, special cases, and utility functions.

**Selector handling**: **LOW PRIORITY - GENERIC TOKENS**
- **Signal extraction method**: Path tokenization only
- **Signal types generated**:
  - `raw_tokens`: Path tokens ≥ 4 characters
  - `family_tokens`: Compact path tokens (excluding generic tokens)
- **Priority/confidence**: Low - produces only generic path-based signals
- **Known gaps or issues**: No component-specific resolution

**Examples**:
- `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/component/ComponentBase.ts`
- `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/component/PeerNode.ts`

---

### `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/stateManagement/`

**Contents**: State management infrastructure for ArkTS, including:
- `decorator.ts` - State decorator definitions (@State, @Prop, @Link, etc.)
- `remember.ts` - Remember utility
- `index.ts` - Public API exports
- `base/` - Base state management classes
- `decoratorImpl/` - Decorator implementations
- `runtime/` - Runtime state management
- `storage/` - Storage implementations (LocalStorage, etc.)

**Framework role**: Implements ArkUI's reactive state management system that enables declarative UI updates when state changes.

**Selector handling**: **BROAD COVERAGE - GENERIC TOKENS**
- **Signal extraction method**: Path tokenization + special handling for "statemanagement" token
- **Signal types generated**:
  - `raw_tokens`: Path tokens including "statemanagement"
  - `family_tokens`: Compact tokens (e.g., "statemanagement", "decorator", "runtime")
  - `weak_modules`: May add generic state management modules
- **Priority/confidence**: Medium for broad state management changes
- **Known gaps or issues**:
  - No component-specific resolution
  - Broad coverage may include unrelated tests
  - State management changes can affect any component, making precise selection difficult

**Examples**:
- `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/stateManagement/decorator.ts`
- `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/stateManagement/remember.ts`
- `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/stateManagement/runtime/observe.ts`

---

### `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/typedNode/`

**Contents**: Typed node definitions for the ArkTS type system. Contains type definitions and interfaces for typed component nodes.

**Framework role**: Provides type safety and type information for ArkTS components, enabling compile-time type checking.

**Selector handling**: **LOW PRIORITY - GENERIC TOKENS**
- **Signal extraction method**: Path tokenization only
- **Signal types generated**:
  - `raw_tokens`: Path tokens
  - `family_tokens`: Compact tokens (e.g., "typednode")
- **Priority/confidence**: Low - produces only generic path-based signals
- **Known gaps or issues**: No component-specific resolution

**Examples**:
- `frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/typedNode/TypedNode.ts`

---

### `frameworks/bridge/declarative_frontend/ark_component/src/`

**Contents**: Declarative frontend ArkTS component wrapper files (Ark*.ts pattern). Each file implements a component class:
- `ArkButton.ts` - Button component
- `ArkText.ts` - Text component
- `ArkList.ts` - List component
- `ArkNavigation.ts` - Navigation component
- `ArkCommon.ts` - Common utilities
- `ArkComponent.ts` - Base component class
- `ArkClassDefine.ts` - Class definitions

**Framework role**: These files provide the declarative ArkTS API for components used in the declarative frontend (the "old" ArkTS syntax before ArkTS/Arkoala).

**Selector handling**: **HIGH PRIORITY - PRIMARY SIGNAL SOURCE**
- **Signal extraction method**: Path-based regex matching: `ark_component/src/Ark{Component}.ts`
- **Signal types generated**:
  - `project_hints`: Component name (PascalCase → snake_case: ArkButton → button)
  - `family_tokens`: Component name
  - `type_hints`: Component class names via pattern_alias
  - `symbols`: Component and modifier symbols
- **Priority/confidence**: High - deterministic filename-based resolution
- **Known gaps or issues**:
  - Excludes common files (common, classdefine, classmock, component, commonshape)
  - Covers only declarative frontend, not ArkTS/Arkoala frontend

**Examples**:
- `frameworks/bridge/declarative_frontend/ark_component/src/ArkButton.ts`
- `frameworks/bridge/declarative_frontend/ark_component/src/ArkText.ts`
- `frameworks/bridge/declarative_frontend/ark_component/src/ArkList.ts`

---

### `frameworks/bridge/declarative_frontend/ark_direct_component/src/`

**Contents**: Direct component wrapper files (ark{component}.ts pattern - lowercase). Contains simpler, more direct component implementations:
- `arkcounter.ts` - Counter component
- `arkdatapanel.ts` - DataPanel component
- `arkgauge.ts` - Gauge component
- `arkpatternlock.ts` - PatternLock component
- `arkqrcode.ts` - QRCode component
- `arktextclock.ts` - TextClock component

**Framework role**: Provides direct, lightweight component implementations for specific components that don't need the full ArkComponent infrastructure.

**Selector handling**: **HIGH PRIORITY - PRIMARY SIGNAL SOURCE**
- **Signal extraction method**: Path-based regex matching: `ark_direct_component/src/ark{component}.ts`
- **Signal types generated**:
  - `project_hints`: Component name (already lowercase)
  - `family_tokens`: Component name
  - `type_hints`: Component class names via pattern_alias
  - `symbols`: Component and modifier symbols
- **Priority/confidence**: High - deterministic filename-based resolution
- **Known gaps or issues**:
  - Excludes common files
  - Limited to a small set of components
  - These components may have different behavior than ArkComponent-based ones

**Examples**:
- `frameworks/bridge/declarative_frontend/ark_direct_component/src/arkcounter.ts`
- `frameworks/bridge/declarative_frontend/ark_direct_component/src/arkdatapanel.ts`
- `frameworks/bridge/declarative_frontend/ark_direct_component/src/arkgauge.ts`

---

### `frameworks/bridge/declarative_frontend/ark_node/src/`

**Contents**: Node adapter files that bridge declarative components to the underlying NG node system.

**Framework role**: Provides the node layer that connects declarative frontend components to the NG rendering pipeline.

**Selector handling**: **LOW PRIORITY - GENERIC TOKENS**
- **Signal extraction method**: Path tokenization only
- **Signal types generated**:
  - `raw_tokens`: Path tokens
  - `family_tokens`: Compact tokens (e.g., "arknode")
- **Priority/confidence**: Low - produces only generic path-based signals
- **Known gaps or issues**: No component-specific resolution

**Examples**:
- `frameworks/bridge/declarative_frontend/ark_node/src/ark_node.ts`

---

### `frameworks/bridge/declarative_frontend/state_mgmt/src/lib/`

**Contents**: State management implementation for the declarative frontend. Subdirectories include:
- `common/` - Common utilities
- `full_update/` - Full update mechanism
- `partial_update/` - Partial update mechanism (PU/V2)
- `sdk/` - SDK exports
- `v2/` - V2 implementation

**Framework role**: Implements the state management system for the declarative frontend, handling reactive updates and component lifecycle.

**Selector handling**: **MEDIUM PRIORITY - BROAD COVERAGE**
- **Signal extraction method**: Path tokenization
- **Signal types generated**:
  - `raw_tokens`: Path tokens including "statemgmt", "state_mgmt"
  - `family_tokens`: Compact tokens (e.g., "statemgmt", "update", "sdk")
- **Priority/confidence**: Medium for state management changes
- **Known gaps or issues**:
  - No component-specific resolution
  - Broad coverage may include unrelated tests
  - Similar to ArkTS stateManagement but for declarative frontend

**Examples**:
- `frameworks/bridge/declarative_frontend/state_mgmt/src/lib/common/observe.ts`
- `frameworks/bridge/declarative_frontend/state_mgmt/src/lib/partial_update/pu_subscriber.ts`

---

## Advanced Component Directories

### `advanced_ui_component/`

**Contents**: Advanced UI components that are not part of the core component set. Each subdirectory contains a complete advanced component implementation:
- `chip/` - Chip component
- `chipgroup/` - ChipGroup component
- `dialog/` - Dialog component
- `popup/` - Popup component
- `counter/` - Counter component
- `segmentbutton/` - SegmentButton component
- `downloadfilebutton/` - DownloadFileButton component
- `multinavigation/` - MultiNavigation component
- And many more...

**Framework role**: Provides advanced and specialized UI components for specific use cases that go beyond the basic component set.

**Selector handling**: **LOW PRIORITY - GENERIC TOKENS**
- **Signal extraction method**: Path tokenization only
- **Signal types generated**:
  - `raw_tokens`: Path tokens
  - `family_tokens`: Compact tokens from directory names
- **Priority/confidence**: Low to Medium - produces generic tokens, but directory names are often component-specific
- **Known gaps or issues**:
  - No dedicated pattern matching for advanced components
  - May not map correctly to XTS test projects
  - Some advanced components may have different naming in XTS

**Examples**:
- `advanced_ui_component/chip/`
- `advanced_ui_component/dialog/`
- `advanced_ui_component/segmentbutton/`

---

### `advanced_ui_component_static/`

**Contents**: Static API versions of advanced components. Contains static method implementations and type definitions for advanced components.

**Framework role**: Provides static API interfaces for advanced components, enabling type-safe static method calls.

**Selector handling**: **LOW PRIORITY - GENERIC TOKENS**
- **Signal extraction method**: Path tokenization only
- **Signal types generated**:
  - `raw_tokens`: Path tokens
  - `family_tokens`: Compact tokens
- **Priority/confidence**: Low - produces only generic path-based signals
- **Known gaps or issues**: No component-specific resolution

**Examples**:
- `advanced_ui_component_static/chip/`
- `advanced_ui_component_static/dialog/`

---

## Interface / SDK Directories

### `interfaces/ets/ani/`

**Contents**: TypeScript/ETS SDK API declarations for the ArkUI framework. Each subdirectory contains API definitions for a specific module:
- `animator/` - Animation APIs
- `componentSnapshot/` - Component snapshot APIs
- `componentUtils/` - Component utility APIs
- `curves/` - Animation curve APIs
- `displaySync/` - Display sync APIs
- `focuscontroller/` - Focus management APIs
- `imagecache/` - Image caching APIs
- `inspector/` - Inspector APIs
- `mediaquery/` - Media query APIs
- `observer/` - Observer APIs
- `ohosprompt/` - Prompt APIs (showToast, showDialog, etc.)
- `overlayManager/` - Overlay management APIs
- `promptaction/` - Prompt action APIs
- `shape/` - Shape APIs
- `smartgesturecontroller/` - Gesture APIs
- `systemprompt/` - System prompt APIs
- `test/` - Test utilities
- `utils/` - Utility functions

**Framework role**: Defines the public SDK API surface for ArkUI applications. These are the interfaces that developers use when writing ArkTS apps.

**Selector handling**: **MEDIUM PRIORITY - MODULE MAPPING**
- **Signal extraction method**: Path tokenization + special_path_rules mapping
- **Signal types generated**:
  - `raw_tokens`: Path tokens
  - `family_tokens`: Compact tokens
  - `modules`: From special_path_rules (e.g., `@ohos.prompt` for ohosprompt/)
  - `symbols`: From special_path_rules (e.g., `prompt`, `Prompt` for ohosprompt/)
- **Priority/confidence**: Medium for mapped modules, low for unmapped
- **Known gaps or issues**:
  - Only some directories have explicit mappings in special_path_rules
  - Unmapped directories produce only generic tokens
  - API changes here may affect many components broadly

**Examples**:
- `interfaces/ets/ani/ohosprompt/ets/@ohos.prompt.ets`
- `interfaces/ets/ani/animator/@ohos.animator.ets`
- `interfaces/ets/ani/overlayManager/@ohos.overlayManager.ets`

---

## Infrastructure Directories

### `frameworks/core/common/`

**Contents**: Core common utilities and infrastructure shared across the framework:
- `ace_engine.cpp/h` - Engine initialization
- `ace_engine_ext.cpp/h` - Engine extensions
- `asset_manager_impl.cpp/h` - Asset management
- `backend.h` - Backend interfaces
- Various utility and helper files

**Framework role**: Provides foundational infrastructure for the ArkUI engine including initialization, asset management, and common utilities.

**Selector handling**: **LOW PRIORITY - GENERIC TOKENS**
- **Signal extraction method**: Path tokenization only
- **Signal types generated**:
  - `raw_tokens`: Path tokens
  - `family_tokens`: Compact tokens (e.g., "common")
- **Priority/confidence**: Low - produces only generic path-based signals
- **Known gaps or issues**:
  - No component-specific resolution
  - Changes here can affect the entire framework broadly
  - May require broad test coverage

**Examples**:
- `frameworks/core/common/ace_engine.cpp`
- `frameworks/core/common/asset_manager_impl.cpp`
- `frameworks/core/common/backend.h`

---

### `frameworks/core/pipeline/`

**Contents**: Rendering pipeline implementation:
- `base/` - Base pipeline classes
- `layers/` - Layer implementations
- NG rendering pipeline code

**Framework role**: Implements the rendering pipeline that draws UI components to the screen.

**Selector handling**: **LOW PRIORITY - GENERIC TOKENS**
- **Signal extraction method**: Path tokenization only
- **Signal types generated**:
  - `raw_tokens`: Path tokens
  - `family_tokens`: Compact tokens (e.g., "pipeline", "layers")
- **Priority/confidence**: Low - produces only generic path-based signals
- **Known gaps or issues**:
  - No component-specific resolution
  - Rendering changes can affect visual output of all components

**Examples**:
- `frameworks/core/pipeline/base/pipeline_base.h`
- `frameworks/core/pipeline/layers/render_layer.h`

---

### `frameworks/core/components/`

**Contents**: Legacy component implementations (pre-NG architecture):
- `declaration/` - Declarative component implementations
- `positioned/` - Positioned components
- `proxy/` - Proxy components
- And other legacy component code

**Framework role**: Contains legacy component code from the old architecture, still used in some contexts.

**Selector handling**: **LOW PRIORITY - GENERIC TOKENS**
- **Signal extraction method**: Path tokenization only
- **Signal types generated**:
  - `raw_tokens`: Path tokens
  - `family_tokens`: Compact tokens
- **Priority/confidence**: Low - produces only generic path-based signals
- **Known gaps or issues**:
  - Legacy code, may not map cleanly to current XTS tests
  - No component-specific resolution

**Examples**:
- `frameworks/core/components/declaration/button/`
- `frameworks/core/components/declaration/text/`

---

## Build and Test Directories

### `examples/`

**Contents**: Example applications demonstrating ArkUI usage:
- `Accessibility/` - Accessibility examples
- `Animation/` - Animation examples
- `Image/` - Image component examples
- `components/` - Component usage examples
- `Dialog_C/` - C API dialog examples
- `Draw/` - Drawing examples
- And many more...

**Framework role**: Provides sample applications and code examples for developers.

**Selector handling**: **NOT HANDLED - EXCLUDED**
- **Signal extraction method**: None
- **Signal types generated**: None
- **Priority/confidence**: N/A - examples are not tested by XTS
- **Known gaps or issues**: Intentionally excluded as examples are not part of the production codebase

**Examples**:
- `examples/Animation/`
- `examples/Image/`
- `examples/components/`

---

### `test/`

**Contents**: Test infrastructure and unit tests:
- `unittest/` - Unit tests
- `component_test/` - Component tests
- `benchmark/` - Benchmark tests
- `mock/` - Mock objects for testing
- `tools/` - Testing tools

**Framework role**: Contains test code for the framework itself.

**Selector handling**: **NOT HANDLED - EXCLUDED**
- **Signal extraction method**: None
- **Signal types generated**: None
- **Priority/confidence**: N/A - test files are not source code changes
- **Known gaps or issues**: Intentionally excluded as test files don't affect production behavior

**Examples**:
- `test/unittest/`
- `test/component_test/`
- `test/benchmark/`

---

## Summary of Selector Coverage

### Well-Covered Directories (High Confidence)
1. **`frameworks/core/components_ng/pattern/`** - Primary signal source, deterministic path matching
2. **`frameworks/core/interfaces/native/implementation/`** - Primary signal source, filename-based matching
3. **`frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/`** - Method-level tracing via tree-sitter
4. **`frameworks/bridge/declarative_frontend/ark_component/src/`** - Primary signal source, filename-based matching
5. **`frameworks/bridge/declarative_frontend/ark_direct_component/src/`** - Primary signal source, filename-based matching

### Medium Coverage (Broad Signals)
1. **`frameworks/core/interfaces/native/utility/`** - Reverse tracing via tree-sitter
2. **`frameworks/core/interfaces/native/common/`** - Reverse tracing via tree-sitter
3. **`interfaces/ets/ani/`** - Module mapping for some directories
4. **`frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/stateManagement/`** - Broad state management coverage

### Low Coverage (Generic Tokens Only)
1. **`advanced_ui_component/`** - Generic path tokens
2. **`frameworks/core/common/`** - Generic path tokens
3. **`frameworks/core/pipeline/`** - Generic path tokens
4. **`frameworks/core/components/`** (legacy) - Generic path tokens
5. **`frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/component/`** - Generic path tokens
6. **`frameworks/bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/typedNode/`** - Generic path tokens
7. **`frameworks/bridge/declarative_frontend/ark_node/src/`** - Generic path tokens

### Not Handled (Intentionally Excluded)
1. **`examples/`** - Example apps, not production code
2. **`test/`** - Test code, not production code

### Known Gaps and Issues

1. **Advanced Components**: No dedicated pattern matching for `advanced_ui_component/` components
2. **State Management**: Broad coverage may produce too many false positives for state management changes
3. **Infrastructure Changes**: Core infrastructure changes (`common/`, `pipeline/`) have broad impact but only generate generic tokens
4. **Tree-sitter Dependency**: Utility and common directory tracing requires tree-sitter parsers
5. **Legacy Code**: Old architecture components (`frameworks/core/components/`) may not map cleanly to XTS tests
6. **API Changes**: SDK interface changes (`interfaces/ets/ani/`) can affect many components but only have partial mapping

### Recommendations for Improvement

1. **Add Advanced Component Mapping**: Create pattern rules for common advanced components
2. **Improve State Management Precision**: Add component-specific state management tracking
3. **Infrastructure Impact Analysis**: Add rules for common infrastructure files that have known broad impact
4. **Complete API Module Mapping**: Add missing mappings for `interfaces/ets/ani/` directories
5. **Legacy Component Mapping**: Add rules for legacy components that are still in use
6. **Tree-sitter Fallback**: Provide alternative signal extraction when tree-sitter is unavailable
