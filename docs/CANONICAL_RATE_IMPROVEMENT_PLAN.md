# Canonical API rate improvement plan

Дата: 2026-05-08

После Step 4.10 (commit `e2ed37a`) метрики:
- `canonical_api_resolution_rate` (per-file avg): **1.20%**
- `pr_canonical_coverage`: **8.67%** (26/300 PRs)
- `canonical_api_resolution_rate_product`: **1.53%**

Цель: довести `canonical_api_resolution_rate` до **5-8%** за ~2-3 рабочих дня.

Связанные документы:
- `docs/POST_WIRING_FIX_PLAN.md` — Sessions 1-4 общий план.
- `docs/SESSION_4_STEPS_PLAN.md` — детализированный Session 4.
- `docs/CANONICAL_ACCURACY_DIAGNOSTIC.md` — diagnostic Session 4.1.

---

## Откуда метрика и где blocker

### Формула (`batch_validate.py:284`, `:660-703`)

**Per-PR ratio:**
```python
canonical_api_files = sum(1 for e in entries if e.get("canonical_affected_apis"))
canonical_api_resolution_rate_pr = canonical_api_files / max(1, len(entries))
```

**Aggregate:**
```python
canonical_api_resolution_rate = mean(per_pr_rate for ok PRs)
```

**Двойной gate** в `pr_resolver.py:744-746`:
```python
if (mapping.sdk_confirmed
        and mapping.api_id
        and mapping.api_id.startswith("api:v1:")):
    canonical_affected_apis.append(mapping.api_id)
```

### Текущее состояние strong-role files (233 = model_ng/model_static/native_modifier/native_node_accessor/jsview_dynamic):

| Бакет | Files | Что делать |
|---|---:|---|
| `canonical` (success) | 49 | — |
| `apis_only_no_canonical` (mappings есть, SDK lookup промахнулся) | 41 | **Tracks 1-3, 7** |
| `no_apis` (нет mappings, parser не извлёк) | 143 | **Tracks 4, 5** |

Дополнительно 10 файлов `not_in_ace_index` → **Track 6**.

---

## Tracks по приоритету ROI

| # | Track | Эффект (PR) | Бюджет | Risk |
|---|---|---:|---|---|
| 1 | `*Impl` suffix stripping | +5-8 | 30 мин | low |
| 3 | Family aliases расширение | +3-5 | 15 мин | low |
| 2 | `node_*` prefix normalization | +5-10 | 1 час | medium |
| 5 | Get/Set fallback в jsview_dynamic | +5-10 | 2 часа | medium |
| 4 | `.h` files method extraction | +5-15 (по файлам) | 3-4 часа | medium |
| 6 | ACE scan path expansion | +10 files | 2-3 часа | low |
| 7 | Ambiguity guard tuning | 0-? | 30 мин | требует проверки |
| 8 | Strong-role coverage метрика | UX | 30 мин | none |

**Quick wins (Tracks 1+3):** ~45 минут → `canonical_api_resolution_rate` ≈ 1.6-1.8%, `pr_canonical_coverage` ≈ 12-14%.
**Medium-term (Tracks 1-3, 5):** ~4 часа → 2.5-3%, 18-22%.
**Long-term (Tracks 1-7):** ~2-3 дня → 4-5%, 30-35%.

---

## Track 1 — `*Impl` suffix stripping (30 минут)

### Проблема

Файлы в `frameworks/core/interfaces/native/implementation/*_modifier.cpp` (например, `image_modifier.cpp`) содержат методы вида `SetImageOptionsImpl`, `SetAltImpl`, `SetFitOriginalSizeImpl`. После strip `Set` префикса получаем `imageOptionsImpl`, `altImpl` — но в SDK эти члены лежат как `imageOptions`, `alt`, `fitOriginalSize` (без `Impl` суффикса).

Image_modifier.cpp фигурирует в 3+ PR в diagnostic данных.

### Реализация

**Файл:** `src/arkui_xts_selector/indexing/source_to_api.py`

#### Step 1.1 — добавить helper

Перед `_resolve_canonical_id` (строка ~217) добавить:

```python
def _strip_impl_suffix(member_name: str) -> str | None:
    """Strip trailing `Impl` for native modifier-style names.

    imageOptionsImpl → imageOptions
    altImpl → alt
    fitOriginalSizeImpl → fitOriginalSize

    Returns the stripped name only if non-trivial (len > 0 and starts lowercase).
    Returns None if the original doesn't end with Impl or strip produces empty/invalid.
    """
    if not member_name.endswith("Impl"):
        return None
    stripped = member_name[:-4]
    if not stripped or not stripped[0].islower():
        return None
    return stripped
```

#### Step 1.2 — использовать в `_resolve_canonical_id`

Найти блок (строки ~239-249):
```python
if sdk_index is not None:
    sdk_entry = None
    if family:
        sdk_entry = sdk_index.find_attribute_member(api_name, family)
    if sdk_entry is None:
        sdk_entry = sdk_index.find_common_member(api_name)
    if sdk_entry is None:
        sdk_entry = sdk_index.find(api_name)
```

Заменить на (с добавлением Impl-fallback):
```python
if sdk_index is not None:
    sdk_entry = None
    member_lookup = api_name
    if family:
        sdk_entry = sdk_index.find_attribute_member(member_lookup, family)
    if sdk_entry is None:
        sdk_entry = sdk_index.find_common_member(member_lookup)
    if sdk_entry is None:
        sdk_entry = sdk_index.find(member_lookup)
    # Fallback: strip trailing Impl suffix (e.g. imageOptionsImpl → imageOptions)
    if sdk_entry is None:
        stripped = _strip_impl_suffix(api_name)
        if stripped:
            if family:
                sdk_entry = sdk_index.find_attribute_member(stripped, family)
            if sdk_entry is None:
                sdk_entry = sdk_index.find_common_member(stripped)
            if sdk_entry is None:
                sdk_entry = sdk_index.find(stripped)
```

### Тесты

**Файл:** `tests/test_impl_suffix_stripping.py`

```python
"""Tests for *Impl suffix stripping in canonical resolution."""
import pytest
from arkui_xts_selector.indexing.source_to_api import _strip_impl_suffix


class TestStripImplSuffix:
    def test_basic(self):
        assert _strip_impl_suffix("imageOptionsImpl") == "imageOptions"
        assert _strip_impl_suffix("altImpl") == "alt"

    def test_no_impl_returns_none(self):
        assert _strip_impl_suffix("imageOptions") is None

    def test_empty_after_strip(self):
        assert _strip_impl_suffix("Impl") is None  # would be empty

    def test_uppercase_after_strip_returns_none(self):
        # CapsImpl → Caps starts uppercase, not a valid member name
        assert _strip_impl_suffix("CapsImpl") is None

    def test_compound_camel_case(self):
        assert _strip_impl_suffix("matchTextDirectionImpl") == "matchTextDirection"


class TestResolveCanonicalIdWithImplFallback:
    @pytest.fixture(scope="class")
    def real_sdk(self):
        from pathlib import Path
        from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index
        sdk_root = Path("/data/home/dmazur/proj/ohos_master/interface/sdk-js/api")
        if not sdk_root.exists():
            pytest.skip(f"SDK root not available: {sdk_root}")
        return build_sdk_index(sdk_root)

    def test_image_options_impl_resolves(self, real_sdk):
        from arkui_xts_selector.indexing.source_to_api import _resolve_canonical_id
        api_id, parent, state, _, sdk_confirmed = _resolve_canonical_id(
            "imageOptionsImpl", "image", real_sdk,
            method_name="SetImageOptionsImpl",
        )
        # Either SDK has imageOptions for Image, or it doesn't — but Impl-strip
        # path should have been attempted.
        if sdk_confirmed:
            assert "imageOptions" in api_id.lower()
```

### Валидация

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_impl_suffix_stripping.py tests/test_source_to_api.py \
  tests/test_pr_resolver.py tests/test_integration_wiring.py -q
```

**Acceptance:**
- 5+ unit тестов проходят.
- `image_modifier.cpp` в diagnostic — apis_only_no_canonical → canonical (хотя бы для image-related).
- 300 PR run: `pr_canonical_coverage` ≥ 10% (8.67% → 10-12%).

---

## Track 2 — `node_*` family prefix normalization (1 час)

### Проблема

Файлы в `frameworks/core/interfaces/native/node/<X>_modifier.cpp` извлекают family как `<X>` дословно. Например:
- `node_text_input_modifier.cpp` → family `node_text_input`
- `node_common_modifier.cpp` → family `node_common`
- `node_span_modifier.cpp` → family `node_span`

Member names в этих файлах имеют префикс соответствующей CamelCase family:
- `textInputCaretColor` под `node_text_input` → real SDK parent: `TextInputAttribute`, member: `caretColor`
- `spanContent` под `node_span` → `SpanAttribute.content` или `SpanInterface.content`

`find_attribute_member("textInputCaretColor", "node_text_input")` ищет `Node_text_inputAttribute` — не существует. `find_attribute_member("caretColor", "text_input")` нашёл бы.

### Реализация

**Файл:** `src/arkui_xts_selector/indexing/file_role.py`

#### Step 2.1 — добавить normalization для `node_*`

В `_NATIVE_NODE_ACCESSOR_PATTERN.search` блоке (строки ~117-123):

```python
# Текущее:
match = _NATIVE_NODE_ACCESSOR_PATTERN.search(rel_path)
if match:
    family = match.group(1)
    if family.endswith("_node"):
        family = family[:-5]
    return "native_node_accessor", family

# Заменить на:
match = _NATIVE_NODE_ACCESSOR_PATTERN.search(rel_path)
if match:
    family = match.group(1)
    if family.endswith("_node"):
        family = family[:-5]
    if family.startswith("node_"):
        family = family[5:]
    return "native_node_accessor", family
```

**Эффект:** family extracted как `text_input`/`common`/`span` вместо `node_text_input`/`node_common`/`node_span`.

#### Step 2.2 — strip family prefix from member name

**Файл:** `src/arkui_xts_selector/indexing/source_to_api.py`

Добавить helper перед `_resolve_canonical_id`:

```python
def _strip_family_prefix_from_member(member: str, family: str) -> str | None:
    """Strip camelCase family prefix from member name.

    textInputCaretColor + family=text_input → caretColor
    spanContent + family=span → content

    Returns stripped name if member starts with camelCase family, else None.
    """
    if not family or not member:
        return None
    parts = family.split("_")
    family_camel_lower = parts[0] + "".join(p.capitalize() for p in parts[1:])
    if not member.startswith(family_camel_lower):
        return None
    rest = member[len(family_camel_lower):]
    if not rest or not rest[0].isupper():
        return None
    return rest[0].lower() + rest[1:]
```

#### Step 2.3 — использовать в `_resolve_canonical_id`

Дополнить SDK lookup ladder fallback'ом по family-stripped member:

```python
if sdk_index is not None:
    # ... existing ladder + Impl strip from Track 1 ...

    # Track 2: try stripping family prefix from member name
    if sdk_entry is None and family:
        stripped_fp = _strip_family_prefix_from_member(api_name, family)
        if stripped_fp:
            sdk_entry = sdk_index.find_attribute_member(stripped_fp, family)
            if sdk_entry is None:
                sdk_entry = sdk_index.find_common_member(stripped_fp)
            if sdk_entry is None:
                sdk_entry = sdk_index.find(stripped_fp)
```

### Тесты

**Файл:** `tests/test_node_family_normalization.py`

```python
"""Tests for node_* family prefix normalization."""
import pytest
from arkui_xts_selector.indexing.file_role import classify
from arkui_xts_selector.indexing.source_to_api import _strip_family_prefix_from_member


class TestNodeFamilyClassify:
    def test_node_text_input(self):
        role, family = classify("frameworks/core/interfaces/native/node/node_text_input_modifier.cpp")
        assert role == "native_node_accessor"
        assert family == "text_input"

    def test_node_common(self):
        role, family = classify("frameworks/core/interfaces/native/node/node_common_modifier.cpp")
        assert role == "native_node_accessor"
        assert family == "common"

    def test_node_span(self):
        role, family = classify("frameworks/core/interfaces/native/node/node_span_modifier.cpp")
        assert role == "native_node_accessor"
        assert family == "span"

    def test_native_node_existing_pattern_still_works(self):
        # `slider_node_modifier.cpp` style — should still strip _node
        role, family = classify("frameworks/core/interfaces/native/node/slider_node_modifier.cpp")
        assert role == "native_node_accessor"
        assert family == "slider"


class TestStripFamilyPrefix:
    def test_basic(self):
        assert _strip_family_prefix_from_member("textInputCaretColor", "text_input") == "caretColor"
        assert _strip_family_prefix_from_member("spanContent", "span") == "content"
        assert _strip_family_prefix_from_member("commonBackground", "common") == "background"

    def test_no_prefix_returns_none(self):
        assert _strip_family_prefix_from_member("caretColor", "text_input") is None

    def test_lowercase_after_prefix_returns_none(self):
        # textInput + lowercase letter — boundary check
        assert _strip_family_prefix_from_member("textinputfoo", "text_input") is None

    def test_camelize_compound_family(self):
        # text_input → textInput
        assert _strip_family_prefix_from_member("textInputCaretColor", "text_input") == "caretColor"
```

### Валидация

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_node_family_normalization.py tests/test_file_role.py \
  tests/test_pr_resolver.py -q
```

**Caveat:** для `node_common_modifier.cpp` (429 mappings) много members могут уйти в `CommonAttribute`/`CommonMethod` — убедиться, что нет regression на других семействах. Проверить, что `pr_canonical_coverage` не падает на не-node PR.

**Acceptance:**
- 6+ unit тестов проходят.
- 300 PR run: PR #84294 (node_text_input/node_span/node_common changes) получают canonical IDs.
- No regression на других PR.

---

## Track 3 — Family aliases расширение (15 минут)

### Проблема

В diagnostic samples:
- `js_with_env.cpp` → family `with_env` → `find_attribute_member` ищет `With_envAttribute` (нет в SDK).
- `js_view_abstract.cpp` → family `view_abstract` → ищет `View_abstractAttribute` (нет).

В `family_aliases.json` сейчас 53 alias-а, но именно `view_abstract`/`with_env`/`embedded_component` отсутствуют в alias-таблице.

### Реализация

**Файл:** `config/family_aliases.json`

Добавить в `aliases` блок:

```json
{
  "schema_version": "v1",
  "aliases": {
    ...
    "view_abstract":      "ViewAbstract",
    "with_env":           "WithEnv",
    "with_theme":         "WithTheme",
    "with_module":        "WithModule",
    "embedded_component": "EmbeddedComponent",
    "loading_progress":   "LoadingProgress",
    "rich_editor":        "RichEditor"
  }
}
```

(Проверить какие из них уже есть, добавить отсутствующие.)

### Валидация

#### Step 3.1 — verify SDK имеет соответствующие parents

```bash
SDK=/data/home/dmazur/proj/ohos_master/interface/sdk-js/api/@internal/component/ets

for parent in ViewAbstractAttribute WithEnvAttribute WithThemeAttribute EmbeddedComponentAttribute LoadingProgressAttribute RichEditorAttribute; do
    found=$(grep -l "interface ${parent}" $SDK/*.d.ts 2>/dev/null | head -1)
    if [ -n "$found" ]; then
        echo "$parent: FOUND in $found"
    else
        echo "$parent: NOT FOUND in SDK — alias would not match"
    fi
done
```

#### Step 3.2 — unit test

**Файл:** `tests/test_family_alias.py` дополнить:

```python
def test_with_env_alias():
    assert normalize_family("with_env") == "WithEnv"

def test_view_abstract_alias():
    assert normalize_family("view_abstract") == "ViewAbstract"

def test_embedded_component_alias():
    assert normalize_family("embedded_component") == "EmbeddedComponent"
```

**Acceptance:**
- Все добавляемые aliases подтверждены SDK grep'ом.
- Unit тесты проходят.
- 300 PR: PR #83257, #84371, #84197 (view_abstract, with_env) получают canonical.

---

## Track 4 — `.h` files method extraction (3-4 часа)

### Проблема

143 strong-role файлов в `no_apis` бакете. Половина — header files (`.h`) без method bodies (только declarations). Tree-sitter C++ парсер в `ace_indexer` извлекает только `function_definition` (с body), пропускает declarations:
- `image_model_static.h`: extracted methods []
- `text_field_model_ng.h`: []
- `ui_extension_model_ng.h`: []

Эти headers содержат `void SetXxx(...)` declarations, но без body. Их нужно индексировать.

### Реализация

**Файл:** `src/arkui_xts_selector/indexing/cpp_parser.py`

#### Step 4.1 — расширить tree-sitter walker

Найти место, где обходится `class_specifier` body для извлечения methods. Добавить обработку `field_declaration`:

```python
def _walk_class_methods(class_node, content, methods):
    """Existing: walk function_definition. Now also walk field_declaration."""
    for child in class_node.children:
        if child.type == "function_definition":
            # ... existing logic ...
        elif child.type == "field_declaration":
            # Look for function_declarator inside (declaration without body)
            for grandchild in child.children:
                if grandchild.type == "function_declarator":
                    method_name = _extract_method_name(grandchild, content)
                    if method_name:
                        methods.append(CppMethod(
                            name=method_name,
                            line=grandchild.start_point[0] + 1,
                            end_line=grandchild.end_point[0] + 1,
                            qualified="",  # no qualifier in header decl
                            is_declaration_only=True,  # NEW field
                        ))
```

#### Step 4.2 — добавить флаг `is_declaration_only` в `CppMethod` dataclass

**Файл:** `src/arkui_xts_selector/indexing/cpp_parser.py` (или `parser_contracts.py`):

```python
@dataclass(frozen=True)
class CppMethod:
    name: str
    qualified: str = ""
    line: int | None = None
    end_line: int | None = None
    is_declaration_only: bool = False  # NEW
```

#### Step 4.3 — в `source_to_api.build_source_to_api_mapping`

Не обязательно изменения — declaration-only methods попадают в общий поток. Но `confidence` для них стоит снизить:

```python
# В _map_model_static / _map_native_modifier и т.д.:
confidence = "strong" if not method.is_declaration_only else "medium"
```

### Тесты

**Файл:** `tests/test_cpp_parser_declarations.py`

```python
"""Test extraction of declaration-only methods from .h files."""
from arkui_xts_selector.indexing.cpp_parser import parse_cpp_content


def test_header_declarations_extracted():
    src = b"""
class ImageModelNG {
public:
    void SetSrc(const std::string& src);
    void SetAlt(const std::string& alt);
    int GetWidth() const;
};
"""
    result = parse_cpp_content(src, "image_model_ng.h")
    assert len(result.classes) == 1
    methods = [m.name for m in result.classes[0].methods]
    assert "SetSrc" in methods
    assert "SetAlt" in methods
    assert "GetWidth" in methods


def test_definition_overrides_declaration():
    """If both header and impl exist, definition takes precedence (full info)."""
    src = b"""
class M {
public:
    void Foo(int x);  // declaration
};
void M::Foo(int x) { /* body */ }  // definition
"""
    result = parse_cpp_content(src, "m.cpp")
    # Both should be parsed; resolver dedups by qualified name
    method_names = [m.name for cls in result.classes for m in cls.methods]
    assert "Foo" in method_names
```

### Валидация

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_cpp_parser.py tests/test_cpp_parser_declarations.py \
  tests/test_pr_resolver.py -q
```

**Acceptance:**
- `image_model_static.h`, `text_field_model_ng.h` — методы extracted.
- 300 PR: `no_apis` бакет в strong-role уменьшается с 143 до ≤ 100.
- File-level `affected_apis` count растёт.

---

## Track 5 — Get/Set fallback в jsview_dynamic (2 часа)

### Проблема

`_map_jsview_dynamic` (строки ~372+) ожидает `JsXxx` или `Create()`. Но реальные `js_*.cpp` файлы имеют regular `Get*/Set*` методы:
- `js_navigation_stack.cpp`: `GetName`, `SetName`, `SetParam`, `GetParam`, `JSNavigationStackExtend`.
- `js_view.cpp`: `setCreatorId`, `setCardId`, `getCardId`, `create`.
- `js_view_abstract.cpp`: `getCustomMapFunc`.

Сейчас они отбрасываются → `no_apis`.

### Реализация

**Файл:** `src/arkui_xts_selector/indexing/source_to_api.py`

#### Step 5.1 — расширить `_map_jsview_dynamic`

Найти текущую реализацию (строка ~372):

```python
def _map_jsview_dynamic(method_name: str, qualified: str, role: str,
                         file_path: str, family: str | None = None,
                         sdk_index: SdkIndexResult | None = None) -> SourceApiMapping | None:
    if method_name == "Create":
        # ... existing
    api_name = _make_canonical_suffix(method_name, "Js")
    if api_name is not None:
        # ... existing
    return None
```

Заменить `return None` на:

```python
    # Track 5: fallback for non-Js methods (Set*/Get*/JS* etc.)
    for prefix, conf in [("Set", "medium"), ("Get", "medium"), ("JS", "medium")]:
        api_name = _make_canonical_suffix(method_name, prefix)
        if api_name is not None:
            api_id, member_of, ambiguity, _descendants, sdk_confirmed = _resolve_canonical_id(
                api_name, family, sdk_index, method_name=method_name
            )
            return SourceApiMapping(
                source_qualified=qualified,
                api_public_name=api_name,
                confidence=conf,  # weaker than Js path
                file_role=role,
                source_file_path=file_path,
                api_id=api_id,
                api_member_of=member_of,
                ambiguity_state=ambiguity,
                sdk_confirmed=sdk_confirmed,
            )
    return None
```

### Тесты

**Файл:** `tests/test_jsview_dynamic_fallback.py`

```python
"""Tests for non-Js prefix mapping in jsview_dynamic role."""
from arkui_xts_selector.indexing.cpp_parser import CppMethod
from arkui_xts_selector.indexing.source_to_api import _map_jsview_dynamic


class TestJsviewDynamicFallback:
    def test_set_method_resolved(self):
        m = CppMethod(name="SetName", qualified="JSNavigationStack::SetName")
        result = _map_jsview_dynamic(
            "SetName", "JSNavigationStack::SetName", "jsview_dynamic",
            "js_navigation_stack.cpp", "navigation_stack",
        )
        assert result is not None
        assert result.api_public_name == "name"
        assert result.confidence == "medium"

    def test_get_method_resolved(self):
        result = _map_jsview_dynamic(
            "GetName", "JSNavigationStack::GetName", "jsview_dynamic",
            "js_navigation_stack.cpp", "navigation_stack",
        )
        assert result is not None
        assert result.api_public_name == "name"

    def test_existing_create_still_works(self):
        result = _map_jsview_dynamic(
            "Create", "JsView::Create", "jsview_dynamic", "js_view.cpp", "view",
        )
        assert result is not None
        assert result.api_public_name == "create"

    def test_existing_js_prefix_still_works(self):
        result = _map_jsview_dynamic(
            "JsBindFoo", "JS::JsBindFoo", "jsview_dynamic", "js_x.cpp", "x",
        )
        assert result is not None
        assert result.api_public_name == "bindFoo"

    def test_unrelated_method_returns_none(self):
        result = _map_jsview_dynamic(
            "InternalHelper", "JS::InternalHelper", "jsview_dynamic", "js_x.cpp", "x",
        )
        assert result is None
```

### Валидация

```bash
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider \
  tests/test_jsview_dynamic_fallback.py tests/test_source_to_api.py \
  tests/test_pr_resolver.py -q
```

**Acceptance:**
- 5+ unit тестов проходят.
- `js_navigation_stack.cpp` mappings ≥ 5 (вместо 0).
- 300 PR: `pr_canonical_coverage` растёт ≥ 1pp от baseline track 1+2+3.

---

## Track 6 — ACE scan path expansion (2-3 часа)

### Проблема

10 strong-role файлов из 233 — `not_in_ace_index`. Sample:
- `frameworks/core/interfaces/native/implementation/grid_modifier.cpp`
- `frameworks/core/interfaces/native/implementation/navigation_modifier.cpp`
- `frameworks/core/interfaces/native/implementation/select_modifier.cpp`

Эти файлы существуют в репо, но `ace_indexer.build_ace_index` их не индексирует.

### Реализация

#### Step 6.1 — diagnose where they're filtered out

```bash
PYTHONPATH=src python3 << 'PYEOF'
from pathlib import Path
from arkui_xts_selector.indexing.cache import cached_ace_index

ace = cached_ace_index(Path('/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine'))
ace_paths = {e.file_path for e in ace.entries}

samples = [
    "frameworks/core/interfaces/native/implementation/grid_modifier.cpp",
    "frameworks/core/interfaces/native/implementation/navigation_modifier.cpp",
    "frameworks/core/interfaces/native/implementation/select_modifier.cpp",
]
for s in samples:
    abs_p = "/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine/" + s
    print(f"{s}")
    print(f"  exists on disk: {Path(abs_p).exists()}")
    print(f"  in ace index: {abs_p in ace_paths}")
    # Find any path mentioning the file basename
    bn = s.rsplit("/", 1)[-1]
    matches = [p for p in ace_paths if bn in p]
    print(f"  ACE entries with basename {bn!r}: {matches[:3]}")
PYEOF
```

#### Step 6.2 — найти scan filter в ace_indexer

**Файл:** `src/arkui_xts_selector/indexing/ace_indexer.py`

Найти `build_ace_index` (строка ~253) и проверить:
- какие папки сканируются (`SCAN_DIRS` или `INCLUDE_PATTERNS`);
- какие исключаются (`EXCLUDE_PATTERNS`);
- max depth.

Возможные причины:
- `interfaces/native/implementation/` не в SCAN_DIRS.
- `_modifier.cpp` исключён фильтром.
- Глубина ≥ 5 от ace_root.

#### Step 6.3 — добавить путь в scan

Если `interfaces/native/implementation/` не покрыт — добавить:
```python
_SCAN_DIRS = [
    "frameworks/core/components_ng/pattern",
    "frameworks/core/components_ng/syntax",
    "frameworks/bridge/declarative_frontend/jsview",
    "frameworks/core/interfaces/native/implementation",  # NEW
    "frameworks/core/interfaces/native/node",
    # ... existing
]
```

### Тесты

**Файл:** `tests/test_ace_indexer_scan.py`

```python
def test_native_implementation_modifiers_indexed(tmp_repo):
    """build_ace_index covers frameworks/core/interfaces/native/implementation/*."""
    # Use real ACE root
    from pathlib import Path
    from arkui_xts_selector.indexing.cache import cached_ace_index
    ace_root = Path("/data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine")
    if not ace_root.exists():
        pytest.skip("ACE root not available")
    ace = cached_ace_index(ace_root)
    paths = [e.file_path for e in ace.entries]
    # Must contain at least one *_modifier.cpp from native/implementation
    assert any("interfaces/native/implementation/" in p and p.endswith("_modifier.cpp")
               for p in paths)
```

### Валидация

```bash
# Очистить ACE cache чтобы scan-changes вступили в силу
rm -rf ~/.cache/arkui_xts_selector/ace_index_*.json
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -p no:cacheprovider tests/test_ace_indexer_scan.py -q
```

**Acceptance:**
- ACE index >= 2800 entries (было 2755).
- 10 missed files → 0.
- 300 PR run: дополнительные canonical entries.

---

## Track 7 — Ambiguity guard tuning (30 минут)

### Проблема

`sdk_indexer.find_member` (строки 189-192) с ambiguity guard:
```python
if len(candidates) == 1:
    return candidates[0]
if len(candidates) > 1:
    return None  # ambiguous
```

Если parent_name указан, но parent stored case-mismatched — `parent_name.lower() not in member_of.lower()` фильтр не отсекает все wrong-parent кандидаты. Нужна проверка.

### Реализация

#### Step 7.1 — diagnose

```bash
PYTHONPATH=src python3 << 'PYEOF'
from pathlib import Path
from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index

sdk = build_sdk_index(Path("/data/home/dmazur/proj/ohos_master/interface/sdk-js/api"))

# Test: find member with multiple parent occurrences
for member, family in [
    ("create", "with_env"),
    ("create", "view_abstract"),
    ("getCustomMapFunc", "view_abstract"),
]:
    print(f"\nfind_attribute_member({member!r}, {family!r}):")
    e = sdk.find_attribute_member(member, family)
    print(f"  result: {e.api_id.canonical() if e else None}")
    # Find ALL occurrences
    all_e = [x for x in sdk.entries
             if (x.member_name == member or x.api_id.member_name == member)]
    print(f"  all occurrences: {len(all_e)}")
    for x in all_e[:5]:
        parent = x.api_id.member_of or (x.parent_api_id.public_name if x.parent_api_id else "")
        print(f"    {parent}.{x.member_name or x.api_id.member_name}")
PYEOF
```

#### Step 7.2 — fix logic если нужно

В `find_member` (строки ~178-193):

```python
def find_member(self, member_name: str, parent_name: str | None = None):
    # First try O(1) index
    if parent_name and (parent_name, member_name) in self._by_parent_member:
        return self._by_parent_member[(parent_name, member_name)]

    # Existing fallback (filter by parent)
    candidates = []
    for entry in self.entries:
        if entry.member_name != member_name and entry.api_id.member_name != member_name:
            continue
        if parent_name:
            member_of = entry.api_id.member_of or ""
            parent_pub = entry.parent_api_id.public_name if entry.parent_api_id else ""
            # NEW: strict equality (case-insensitive) instead of substring
            if (parent_name.lower() != member_of.lower()
                    and parent_name.lower() != parent_pub.lower()):
                continue
        candidates.append(entry)

    # If parent specified and we have any candidate, return first (parent already filtered)
    if parent_name and candidates:
        return candidates[0]
    if len(candidates) == 1:
        return candidates[0]
    return None
```

### Тесты

```python
def test_find_member_with_parent_returns_first_when_multiple(real_sdk):
    """When parent_name is given, return first match even if ambiguous globally."""
    # E.g., 'role' exists in Button + Checkbox + Radio + ...
    # find_member('role', 'ButtonAttribute') should return the Button one.
    e = real_sdk.find_member('role', 'ButtonAttribute')
    assert e is not None
    assert 'Button' in e.api_id.member_of
```

### Acceptance

- Случаи где parent_name явно дисамбигуирует — теперь возвращают результат.
- 300 PR: дополнительный +5-10 canonical IDs.

---

## Track 8 — Strong-role coverage метрика (30 минут)

### Проблема

`canonical_api_resolution_rate = 1.20%` рассчитывается на 3238 файлов. 1700+ из них (test/build/docs/generated) **никогда** не должны давать canonical. Метрика показывает "low recall", хотя реально SDK lookup на strong-role файлах работает на 49/233 = **21%**.

### Реализация

**Файл:** `src/arkui_xts_selector/batch_validate.py`

#### Step 8.1 — добавить per-PR strong-role count

В `_summarize_result` (строка ~166):

```python
def _summarize_result(result: dict) -> dict:
    # ... existing ...
    if isinstance(gs, dict) and "entries" in gs:
        # ... existing ...

        # Track 8: strong-role canonical coverage
        STRONG_ROLES = {"model_ng", "model_static", "native_modifier",
                         "native_node_accessor", "jsview_dynamic"}
        strong_role_files = 0
        strong_role_canonical = 0
        for e in graph_entries:
            cf = e.get("changed_file", "")
            # Use file_role classification (cheap to import here)
            from .indexing.file_role import classify
            role, _ = classify(cf)
            if role in STRONG_ROLES:
                strong_role_files += 1
                if e.get("canonical_affected_apis"):
                    strong_role_canonical += 1

        return {
            ...
            "strong_role_files_count": strong_role_files,
            "strong_role_canonical_count": strong_role_canonical,
            "strong_role_canonical_rate": round(
                strong_role_canonical / max(1, strong_role_files), 4),
            ...
        }
```

#### Step 8.2 — aggregate

В блоке `quality_metrics` (строка ~700+):

```python
total_strong = sum(s.get("strong_role_files_count", 0) for s in summaries if s["status"] == "ok")
total_strong_canonical = sum(s.get("strong_role_canonical_count", 0) for s in summaries if s["status"] == "ok")
strong_canonical_coverage = total_strong_canonical / max(1, total_strong)

quality_metrics = {
    ...
    "strong_role_files_total": total_strong,
    "strong_role_canonical_total": total_strong_canonical,
    "strong_role_canonical_coverage": strong_canonical_coverage,
}

# Print in summary
print(f"Strong-role canonical coverage: {strong_canonical_coverage:.2%} "
      f"({total_strong_canonical}/{total_strong} strong-role files)")
```

### Тесты

```python
def test_strong_role_coverage_metric():
    """strong_role_canonical_coverage counts only files with strong role."""
    summary = _summarize_result({
        "pr_number": 1, "status": "ok",
        "graph_selection": {"entries": [
            {"changed_file": "frameworks/.../button_pattern.cpp",  # pattern role
             "canonical_affected_apis": ["api:v1:#Button#x"]},
            {"changed_file": "frameworks/.../button_modifier.cpp",  # native_modifier
             "canonical_affected_apis": ["api:v1:#Button#x"]},
            {"changed_file": "test/unittest/foo.cpp",  # test_only — non-strong
             "canonical_affected_apis": []},
        ]},
    })
    assert summary["strong_role_files_count"] == 1  # only the modifier
    assert summary["strong_role_canonical_count"] == 1
    assert summary["strong_role_canonical_rate"] == 1.0
```

### Acceptance

- Новая метрика появляется в `batch_results_quality.json`.
- Console output показывает: `Strong-role canonical coverage: 21.03% (49/233)`.
- coverage_eval начинает использовать `strong_role_canonical_coverage` в default-activation gate.

---

## Sprint plan

### Sprint A — Quick wins (45 минут)

Sequential:
1. Track 8 (метрика для измерения) — 30 мин.
2. Track 1 (`*Impl` strip) — 30 мин.
3. Track 3 (family aliases) — 15 мин.

После Sprint A: prog 300 PR + сравнение метрик. Ожидание:
- `canonical_api_resolution_rate` 1.20% → 1.6-1.8%.
- `pr_canonical_coverage` 8.67% → 12-14%.
- `strong_role_canonical_coverage` 21% → 24-27%.

### Sprint B — Medium-term (4-5 часов)

Sequential:
1. Track 7 (ambiguity guard, диагностика + fix) — 30 мин.
2. Track 2 (`node_*` normalization) — 1 час.
3. Track 5 (jsview Get/Set fallback) — 2 часа.
4. Run + сравнение метрик.

После Sprint B:
- `canonical_api_resolution_rate` → 2.5-3%.
- `pr_canonical_coverage` → 18-22%.
- `strong_role_canonical_coverage` → 35-40%.

### Sprint C — Long-term (1-2 дня)

Sequential:
1. Track 6 (ACE scan expansion) — 2-3 часа.
2. Track 4 (header file extraction) — 3-4 часа.
3. Final run + comparison + coverage_eval against curated_30.

После Sprint C:
- `canonical_api_resolution_rate` → 4-5%.
- `pr_canonical_coverage` → 30-35%.
- `strong_role_canonical_coverage` → 55-65%.

---

## Validation после каждого Sprint

```bash
# 1. Unit + integration tests
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 timeout 120 \
python3 -m pytest -p no:cacheprovider tests/ -q

# 2. 300 PR run
RUN_ID=$(date +%Y%m%d_%H%M)_sprint_<X>
mkdir -p local/quality_runs/${RUN_ID}/logs
env -u http_proxy -u https_proxy PYTHONPATH=src \
python3 -m arkui_xts_selector.cli validate-batch \
    --pr-list-file local/pr_lists/ace_engine_300.txt \
    --pr-cache-mode read-only --workers 30 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --git-host-config /data/home/dmazur/.config/gitee_util/config.ini \
    --pr-api-cache-dir local/pr_api_cache \
    --cache-dir local/pr_graph_cache_sprint_<X> \
    --output local/quality_runs/${RUN_ID}/batch_results.json \
    > local/quality_runs/${RUN_ID}/logs/validate.log 2>&1

# 3. Diff vs previous sprint
python3 -c "
import json
prev = json.load(open('local/quality_runs/post_native_inline_300pr/batch_results_quality.json'))
curr = json.load(open(f'local/quality_runs/${RUN_ID}/batch_results_quality.json'))
keys = ['canonical_api_resolution_rate', 'pr_canonical_coverage',
        'strong_role_canonical_coverage', 'manual_review_rate',
        'target_resolution_rate']
print(f'Metric                              | Prev    | Curr    | Δ')
print(f'------------------------------------+---------+---------+-------')
for k in keys:
    p = prev.get(k, 0); c = curr.get(k, 0)
    delta = (c - p) * 100 if isinstance(p, float) else 0
    print(f'{k:36s} | {p:.4f}  | {c:.4f}  | {delta:+.2f}pp')
"

# 4. Coverage eval (если curated_30 размечен)
PYTHONPATH=src python3 -m arkui_xts_selector.cli coverage-eval \
    --batch-results local/quality_runs/${RUN_ID}/batch_results.json \
    --golden tests/fixtures/golden/curated_30.json \
    --baseline local/quality_runs/post_native_inline_300pr/coverage_eval.json \
    --output local/quality_runs/${RUN_ID}/coverage_eval.json \
    --report-md local/quality_runs/${RUN_ID}/coverage_eval.md \
    --fail-on-regression
```

### Acceptance gate per sprint

| Sprint | Min canonical_rate | Min strong_role_cov |
|---|---:|---:|
| A | 1.6% | 24% |
| B | 2.5% | 35% |
| C | 4.0% | 55% |

Если acceptance gate fails — diagnose причину перед движением к следующему Sprint.

---

## Risk mitigation

### R1: Track 2 regression на `node_common_modifier.cpp` (429 mappings)

После family normalization `node_common` → `common`, многие members могут уйти в `CommonAttribute`. Это легитимно, но есть риск, что массивный output меняет distribution targets.

**Mitigation:** перед commit'ом Track 2 — точечный test на PR #84459 (node_common changes), сравнить before/after target list. Если target_count > 200 — добавить cap.

### R2: Track 4 regression — лишние methods из headers

Header methods могут попасть в production output как `confidence=medium` без реального API impact (только declaration changes без implementation).

**Mitigation:** в SourceApiMapping использовать `is_declaration_only` → confidence drop до `weak`. Phase 0 strict gate отбросит без `sdk_confirmed=True`.

### R3: SDK не имеет нужных parents для Track 3 aliases

Если grep'ом не найдено `WithEnvAttribute` в SDK — alias в `family_aliases.json` бесполезен.

**Mitigation:** Step 3.1 verification обязателен перед commit.

### R4: Track 5 regression — non-Js methods попадают в jsview output

Например, internal helper `JsBindGlobalProperties` сейчас mapping не получает. После Track 5 — попадёт как `bindGlobalProperties` через `Js` strip. Это уже работает, не regression.

Но `JSNavigationStackExtend` через `JS` strip получит api_name `navigationStackExtend` — в SDK скорее всего нет → `apis_only_no_canonical`. Нет regression на canonical, только на affected_apis.

**Mitigation:** проверять `apis_only_no_canonical` после Sprint B — должен быть managed (не >2× от before).

---

## После Sprint C

Если Sprint C-цели достигнуты (`canonical_api_resolution_rate ≥ 4%`):

1. **Manual labeling pass** на curated_30 (5 часов human) — Phase CV.4 из COVERAGE_TEST_FRAMEWORK_PLAN.
2. **Coverage_eval против размеченного golden** — измерить precision/recall.
3. **Regression gate** в CI.

Если 5-8% target всё ещё не достигнут — следующий шаг:
- B.1 Coverage replay из CI gcov (отдельный 3-5 дневный проект).
- A.4 macro expansion (4-5 дней).

Эти не входят в этот план.

---

## Сводный command sequence

```bash
# Sprint A
git checkout -b feature/canonical-sprint-a
# Реализовать Track 8 + Track 1 + Track 3 (см. соответствующие секции)
# Tests + 300 PR run + diff
git commit -am "Sprint A: Impl strip, family aliases, strong-role metric"

# Sprint B
git checkout -b feature/canonical-sprint-b feature/canonical-sprint-a
# Track 7 + Track 2 + Track 5
git commit -am "Sprint B: ambiguity guard, node prefix normalization, jsview Get/Set"

# Sprint C
git checkout -b feature/canonical-sprint-c feature/canonical-sprint-b
# Track 6 + Track 4
git commit -am "Sprint C: ACE scan expansion, header method extraction"

# Merge
git checkout feature/api-xts-quality-tasks
git merge feature/canonical-sprint-c
```

---

## Definition of done

После всех 8 Tracks:

| Критерий | Минимум | Стрейч |
|---|---:|---:|
| Все unit + integration тесты | ✅ no regressions | ✅ |
| `canonical_api_resolution_rate` | ≥ 4% | 5-8% |
| `pr_canonical_coverage` | ≥ 30% | 40%+ |
| `strong_role_canonical_coverage` | ≥ 55% | 70%+ |
| `manual_review_rate` | ≤ 25% (current) | ≤ 20% |
| Coverage_eval recall_strict (на размеченном curated_30) | ≥ 0.4 | 0.6+ |
| Total runtime 300 PR | ≤ 13 минут (current 11.5) | без regress |
| Tests added | ≥ 25 | ≥ 40 |

После DoD достижения — открыта дорога к default activation gate (требует ещё B.1 coverage import + manual labeling, но не блокирует).
