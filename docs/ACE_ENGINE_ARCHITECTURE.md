# ACE Engine Architecture: Source-to-Test Dependency Chain

This document describes the real dependency chain from C++ source files in the
ACE engine framework through to the XTS ETS test suites. Understanding this
chain is essential for the XTS test selector because **no direct build-time
dependency exists between C++ source and ETS tests** — they are linked only
through the SDK API surface.

## Dependency Chain

```
source.cpp  (frameworks/core/components_ng/pattern/<component>/xxx_pattern.cpp)
    ↓ compiled into
libace_compatible.so / libace.z.so  (framework shared libraries)
    ↓ exposes via abstract interface
XxxModel::GetInstance() → XxxModelNG  (model singletons)
    ↓ called from bridge layer
declarative_frontend/jsview/js_xxx.cpp           (JS bridge)
arkts_frontend/koala_projects/.../xxx.ets         (Arkoala bridge)
    ↓ defines API surface
@internal/component/ets/xxx.d.ts  (SDK type declarations)
    ↓ consumed by
ace_ets_module_ui/ace_ets_module_<group>/ace_ets_module_<component>*/  (XTS ETS tests)
```

### Key Insight

XTS tests are **ETS applications** that import components through the SDK API
surface. They do **not** link against or directly reference C++ source files.
The selector must bridge this gap through naming conventions and API mapping.

## Source Layer

The ACE engine framework lives under `foundation/arkui/ace_engine/`:

```
frameworks/core/
├── components_ng/
│   ├── pattern/          ← 119 component directories, 625 .cpp files
│   │   ├── button/       (button_pattern.cpp, button_modifier.cpp, ...)
│   │   ├── rich_editor/  (rich_editor_pattern.cpp, rich_editor_layout_algorithm.cpp, ...)
│   │   └── ...
│   └── ...
└── ...
```

**Key metrics:**
- 2934 `.cpp` files in `frameworks/core/`
- 1503 `.cpp` files in `components_ng/`
- 119 component directories in `pattern/`
- 625 `.cpp` entries in `pattern/BUILD.gn` (single source set `pattern_ng`)

### Component File Naming Patterns

C++ source files follow naming conventions that encode the component name:

| Pattern | Example | Component |
|---------|---------|-----------|
| `<comp>_pattern.cpp` | `button_pattern.cpp` | button |
| `<comp>_modifier.cpp` | `rich_editor_modifier.cpp` | rich_editor |
| `<comp>_layout_algorithm.cpp` | `grid_layout_algorithm.cpp` | grid |
| `<comp>_event_hub.cpp` | `slider_event_hub.cpp` | slider |
| `<comp>_model.cpp` | `image_model.cpp` | image |
| `<comp>_model_ng.cpp` | `text_model_ng.cpp` | text |
| `<comp>_paint_method.cpp` | `canvas_paint_method.cpp` | canvas |
| `<comp>_accessibility_property.cpp` | `list_accessibility_property.cpp` | list |

The selector's `cpp_naming_resolver` module extracts component names from these
patterns as a fast-path resolution that bypasses the full API pipeline.

## Bridge Layer

Two parallel bridges connect C++ framework to the declarative UI surface:

### JS Bridge (declarative frontend)

```
frameworks/bridge/declarative_frontend/jsview/js_xxx.cpp
```

Each component has a `JsXxx` class that translates JS/ETS calls into C++
framework calls through the model singleton pattern:
`XxxModel::GetInstance()->Create(...)`.

### Arkoala Bridge (ArkTS frontend)

```
frameworks/bridge/arkts_frontend/koala_projects/...
    .../generated/component/xxx.ets
```

Generated ETS wrappers that call into the native framework via the ArkTS
interop layer.

## SDK API Layer

The public API surface is defined in the SDK type declarations:

```
api/@internal/component/ets/xxx.d.ts
```

These `.d.ts` files declare the component constructors, attributes, and events
that ETS application code (including XTS tests) can use.

## Test Layer (XTS ETS)

XTS test structure is **not flat** — it uses a 3-level nested hierarchy:

```
ace_ets_module_ui/                                    ← level 1: group
  ace_ets_module_layout/                              ← level 2: subgroup
    ace_ets_module_layout_gridrow_gridcol/             ← level 3: specific test
    ace_ets_module_layout_Grid_static/
  ace_ets_module_imageText/
    ace_ets_module_imageText_common/
    ace_ets_module_imageText_api16_static/
  ace_ets_module_dialog/
    ace_ets_module_dialog_button/
    ace_ets_module_dialog_button_static/
```

**Key metrics:**
- 819 test directories in `ace_ets_module_ui/`
- Depth: up to 4 levels from `ace_ets_module_ui/`
- Test directories are named with the `ace_ets_module_` prefix
- Some test names use camelCase (`imageText`), others use snake_case (`layout_grid`)

### Implications for the Selector

1. **Recursive search required**: `iterdir()` on the XTS root only finds ~10
   top-level directories. The selector must use `os.walk` with depth limit 4
   to find all 819 test directories.

2. **Fuzzy name matching**: Component names in C++ (`rich_editor`) may appear
   in test directory names as either snake_case (`rich_editor`) or camelCase
   (`richEditor`).

3. **No build dependency**: There is no GN/BUILD file dependency between C++
   source and ETS tests. The only link is through the SDK API surface or
   naming conventions.

4. **Family grouping**: Tests are grouped by component families. Changing
   `grid_pattern.cpp` should select all tests in `ace_ets_module_layout_grid*`.

## Selector Resolution Paths

The selector uses two parallel resolution strategies:

| Strategy | Path | Confidence |
|----------|------|------------|
| **Naming convention** | `source.cpp` → component name → XTS dir name match | medium |
| **SDK API mapping** | `source.cpp` → API entity → inverted index → consumer tests | strong/weak |
| **Broad infra** | File path pattern match → all XTS tests | critical risk flag |

The naming convention path (`cpp_naming_resolver`) is a fast heuristic that
catches cases where the full API pipeline has gaps. The SDK API path is more
precise but requires complete indexing of the SDK type declarations.

## References

- `src/arkui_xts_selector/indexing/pr_resolver.py` — main resolver, fallback policy
- `src/arkui_xts_selector/indexing/cpp_naming_resolver.py` — naming convention resolution
- `src/arkui_xts_selector/indexing/inverted_index.py` — API → consumer mapping
- `src/arkui_xts_selector/indexing/ets_indexer.py` — ETS test indexer
- `src/arkui_xts_selector/indexing/broad_infra.py` — broad infrastructure file matching
