# Playbook: точное прослеживание «изменённый файл → API»

Дата создания: 2026-05-03
Аудитория: разработчик начального уровня (junior).
Цель: довести точность селектора с 1.6 % файлов до ≥ 90 % через
typed AST-парсинг каждого слоя ArkUI ace_engine.

---

## §0 Прочитай это первым

> **Этот playbook — единственный документ, по которому ты работаешь.**
> Все остальные документы — справочные. Список того, что когда читать,
> в §2.

Что **уже сделано** (не повторяй):
- Shadow-модули `model/`, `graph/`, `ranking/`, `indexing/` — созданы.
- Канонический `ApiEntityId`, `Evidence`, `ApiUsageSignature`,
  `BucketGatePolicy` — реализованы (R1, R2, R3, R13 закрыты, см.
  `docs/PROJECT_FOLLOWUP_BACKLOG.md`).
- Адаптер `build_button_modifier_static_graph` работает на
  fixture-уровне.
- `tree-sitter-cpp` и `tree-sitter-typescript` уже установлены и
  доступны через `src/arkui_xts_selector/tree_sitter_parsers.py`.

Что **тебе предстоит**:
- 5 фаз, каждая ≈ 1 неделя при средней скорости (плюс-минус).
- Каждая фаза превращает 10-30 % файлов из «селектор не понимает» в
  «корректный typed evidence».
- В конце пользователь сможет спросить «какие API затронула моя
  правка?» и получить точную цепочку.

Принцип: **никаких новых архитектурных изобретений** — ты доводишь
до production существующий шадоу. Все типы и слои уже спроектированы,
ты их подключаешь.

---

## §1 Phase status overview

> **Junior: обновляй эту таблицу после каждой завершённой фазы.**
> Меняй `[ ]` на `[X]`, ставь дату, ссылку на PR.

| Phase | Статус | Закрыта | PR / коммит |
|-------|--------|---------|-------------|
| Phase 0 — doc cleanup & prereqs | `[X] done` | 2026-05-03 | — |
| Phase 1 — L0 SDK registry | `[ ] not started` | — | — |
| Phase 2 — L1-L4 C++ ace_indexer | `[ ] not started` | — | — |
| Phase 3 — L5/L6 ArkTS ets_indexer | `[ ] not started` | — | — |
| Phase 4 — broad infrastructure rules | `[ ] not started` | — | — |
| Phase 5 — hunk resolution + CLI explain | `[ ] not started` | — | — |

Когда все 6 строк — `[X]`, закрывай этот playbook коммитом и
«передавай эстафету» senior'у на review acceptance метрик из §10.

---

## §2 Phase 0: doc cleanup & prereqs

> **Status:** `[X] done` (2026-05-03)

Цель Phase 0 — почистить рабочее окружение, чтобы старые документы
не сбивали тебя с толку. После Phase 0 в `docs/` остаются только
**активные** документы.

### 2.1 Карта документов

**Активные (читай их по необходимости):**

| Файл | Когда читать |
|------|--------------|
| `README.md` | первое знакомство |
| `docs/REQUIREMENTS.md` | назначение проекта (актуально с STATE-AS-OF шапкой) |
| `docs/DESIGN.md` | feature set и hardcode policy |
| `docs/CLI_REFERENCE.md` | флаги CLI |
| `docs/TARGET_ARCHITECTURE.md` | **главный** референс по типам / слоям / dependency direction |
| `docs/API_LINEAGE_GRAPH.md` | схема graph узлов и рёбер |
| `docs/IMPLEMENTATION_PLAN.md` | EPICs / Tasks / Gates |
| `docs/REFACTORING_PLAN.md` | фазы миграции legacy → graph |
| `docs/BENCHMARK_STRATEGY.md` | как валидировать качество |
| `docs/PERFORMANCE_STRATEGY.md` | бюджеты времени, кеши |
| `docs/BACKLOG.md` | legacy ROI-список (живой) |
| `docs/PROJECT_PRECISE_TRACING_DESIGN.md` | технический дизайн, на котором стоит этот playbook |
| `docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md` | baseline качества (1.6 % files, 53 % timeouts) |
| `docs/PROJECT_FOLLOWUP_BACKLOG.md` | список открытых R-items |
| `docs/PROJECT_PRECISE_TRACING_PLAYBOOK.md` | **этот документ** |
| `docs/ARCHITECTURE_V1.md` | historical baseline (читать только для контекста) |

**Reviews / archive (не читай для работы, в архив):**

| Файл | Действие |
|------|----------|
| `docs/PROJECT_FIXES_AND_CLEANUP.md` | → `docs/archive/` (на 95 % выполнен) |
| `docs/PROJECT_DOCS_AND_IMPL_REVIEW.md` | → `docs/archive/` (review закрытых R1-R3, R13) |
| `docs/PROJECT_FIXES_REVIEW.md` | → `docs/archive/` (review закрытых R1-R3, R13) |

`docs/archive/` уже существует, в нём лежат:
`API_IMPACT_SELECTION_DESIGN.md`, `API_IMPACT_SELECTION_PLAN.md`,
`ARCHITECTURE_CRITICAL_REVIEW.md`, `ARCHITECTURE_REVIEW.md`,
`BENCHMARK.md`, `PROJECT_CHANGE_RECOMMENDATIONS.md`,
`PROJECT_CRITICAL_ANALYSIS.md`, `PROJECT_IMPLEMENTATION_PLAYBOOK.md`,
`README.md`. Не правь их.

### 2.2 Шаги Phase 0

```bash
git checkout fix/property-symbol-method-mapping
git pull
git checkout -b docs/phase0-cleanup
```

Перенеси три устаревших review-документа в archive:

```bash
mv docs/PROJECT_FIXES_AND_CLEANUP.md      docs/archive/
mv docs/PROJECT_DOCS_AND_IMPL_REVIEW.md   docs/archive/
mv docs/PROJECT_FIXES_REVIEW.md           docs/archive/
git add docs/archive/PROJECT_FIXES_AND_CLEANUP.md
git add docs/archive/PROJECT_DOCS_AND_IMPL_REVIEW.md
git add docs/archive/PROJECT_FIXES_REVIEW.md
```

Обнови `docs/archive/README.md`. Открой файл и в таблицу
«Index» добавь три строки:

```markdown
| PROJECT_FIXES_AND_CLEANUP.md | 2026-05-01 | superseded by PROJECT_PRECISE_TRACING_PLAYBOOK.md |
| PROJECT_DOCS_AND_IMPL_REVIEW.md | 2026-05-01 | review of closed R1-R3, R13 |
| PROJECT_FIXES_REVIEW.md | 2026-05-01 | review of closed R1-R3, R13 |
```

Обнови `README.md`. Найди раздел «## Documentation» и убедись, что
ссылки указывают на:

- `TARGET_ARCHITECTURE.md`
- `IMPLEMENTATION_PLAN.md`
- `API_LINEAGE_GRAPH.md`
- `REFACTORING_PLAN.md`
- `PROJECT_PRECISE_TRACING_DESIGN.md` ← добавить
- `PROJECT_PRECISE_TRACING_PLAYBOOK.md` ← добавить (этот файл)
- `PROJECT_REAL_PR_QUALITY_ANALYSIS.md`
- `PROJECT_FOLLOWUP_BACKLOG.md`
- `docs/archive/`

Удали ссылки на файлы, которые ушли в архив.

### 2.3 Проверка

```bash
ls docs/PROJECT_FIXES*.md docs/PROJECT_DOCS_*.md 2>&1
# должно вернуть "No such file or directory" — все три перенесены

ls docs/archive/PROJECT_FIXES_*.md docs/archive/PROJECT_DOCS_*.md
# должны быть в архиве

python3 -m pytest --collect-only -q | tail -5
# тесты не должны падать на сборе
```

### 2.4 Prereqs (проверь среду)

```bash
python3 --version              # ожидается >= 3.10
python3 -m pip install -e .
python3 -m pip install pytest

python3 -c "import tree_sitter; print('tree_sitter OK')"
python3 -c "import tree_sitter_cpp; print('tree_sitter_cpp OK')"
python3 -c "import tree_sitter_typescript; print('tree_sitter_typescript OK')"
```

Если какая-либо библиотека не найдена:

```bash
python3 -m pip install tree-sitter tree-sitter-cpp tree-sitter-typescript
```

Финальный sanity:

```bash
python3 -m pytest --tb=line -q 2>&1 | tail -5
# ожидается: 5 failed, ~1042 passed (5 пред-существующих failures
# в test_daily_prebuilt/test_download_hints/test_file_type_coverage —
# не трогай, это pre-existing)
```

### 2.5 Commit

```bash
git add README.md
git add docs/archive/README.md

git commit -m "$(cat <<'EOF'
docs(phase0): archive completed review documents and refresh links

PROJECT_FIXES_AND_CLEANUP.md, PROJECT_DOCS_AND_IMPL_REVIEW.md, and
PROJECT_FIXES_REVIEW.md describe work that has been completed
(R1-R3, R13 plus doc archive moves). Move them under docs/archive/
to keep docs/ focused on what remains to be done. Update README
links to point at the active playbook.

Behavior changed: no
Rollback path: revert this commit
EOF
)"
```

### 2.6 DoD для Phase 0

- [ ] Три review-документа перенесены в `docs/archive/`.
- [ ] `docs/archive/README.md` обновлён.
- [ ] `README.md` ссылается на актуальные документы.
- [ ] tree-sitter / tree-sitter-cpp / tree-sitter-typescript доступны.
- [ ] `python3 -m pytest --tb=line -q` показывает «1042+ passed»
  (плюс известные 5 failed — не трогать).
- [ ] **Обновлена таблица в §1 этого файла**: Phase 0 → `[X] done`,
  дата, PR ссылка.

---

## §3 Workflow conventions (для всех фаз)

### 3.1 Ветки

Одна фаза = одна ветка = один PR (в крайнем случае — один большой PR
с двумя коммитами «implementation» и «tests»).

| Фаза | Имя ветки |
|------|-----------|
| Phase 0 | `docs/phase0-cleanup` |
| Phase 1 | `feature/sdk-registry-tree-sitter` |
| Phase 2 | `feature/ace-indexer-cpp` |
| Phase 3 | `feature/ets-indexer-arkts` |
| Phase 4 | `feature/broad-infrastructure-rules` |
| Phase 5 | `feature/hunk-resolution-and-explain` |

### 3.2 Commit message

```
<scope>: <short imperative summary, ≤ 70 chars>

<тело: что делает и почему, 2-4 параграфа>

Verification:
- python3 -m pytest <ключевой тест> -v
- python3 -m pytest

Behavior changed: no  (Phase 0-3) / yes (Phase 4-5, controlled flag)
CLI output changed: no
JSON schema changed: no
Cache schema changed: no  (Phase 0-3) / yes (Phase 4-5)
Rollback path: revert this commit
Closes phase: <Phase N from PROJECT_PRECISE_TRACING_PLAYBOOK.md>
```

`<scope>` — `docs`, `model`, `indexing`, `graph`, `ranking`, `cli`,
`tests`. Никаких эмодзи.

### 3.3 Правила безопасности

- **Не используй `git add .`** — только по конкретному имени файла.
- **Не делай `git pull --rebase`** в случае конфликта без senior'а.
- **После каждого шага запускай pytest** — не накапливай 5 шагов и
  потом удивляйся, что не зелёное.
- **Если падает тест, который не упомянут в данной фазе** —
  останови, спроси. Это сигнал скрытой зависимости.

### 3.4 Что не трогать

В этом playbook **не правь** следующие файлы (они принадлежат
production legacy-пути, который мы не ломаем):

- `src/arkui_xts_selector/cli.py`
- `src/arkui_xts_selector/scoring.py`
- `src/arkui_xts_selector/signal_inference.py`
- `src/arkui_xts_selector/coverage_planner.py`
- `src/arkui_xts_selector/report_human.py`
- `src/arkui_xts_selector/report_json.py`
- `src/arkui_xts_selector/project_index.py`
- `src/arkui_xts_selector/execution.py`
- `tests/test_cli_design_v1.py`

Все правки идут в новые модули или в shadow-модули
(`model/`, `graph/`, `ranking/`, `indexing/`).

---

## §4 Phase 1 — L0 SDK registry

> **Status:** `[ ] not started`

### 4.1 Зачем

`interface/sdk-js/api/` содержит публичные API ArkUI как
TypeScript-декларации (.d.ts). Сейчас селектор парсит их регексами и
получает неполный набор API entity. Цель Phase 1 — построить
**полный реестр** через tree-sitter-typescript.

После Phase 1 у нас есть авторитетный список
`Set[ApiEntityId]` с `ApiDeclarationRef` (file_path, line, span,
since_api). Phase 2-5 опираются на этот реестр.

### 4.2 Что создаём

```
src/arkui_xts_selector/indexing/sdk_indexer.py     (заменяем содержимое)
src/arkui_xts_selector/indexing/sdk_parser.py      (новый)
tests/test_sdk_indexer.py                           (новый)
tests/fixtures/sdk_registry/                        (новый каталог)
   button.d.ts                                     (мини-fixture)
   slider.d.ts                                     (мини-fixture)
   menu_item.d.ts                                  (мини-fixture)
   navigation.d.ts                                 (мини-fixture)
```

### 4.3 Шаг 1: API мини-fixtures

Создай `tests/fixtures/sdk_registry/button.d.ts`:

```typescript
declare class ButtonAttribute extends CommonMethod<ButtonAttribute> {
  type(value: ButtonType): ButtonAttribute;
  buttonStyle(value: ButtonStyleMode): ButtonAttribute;
  controlSize(value: ControlSize): ButtonAttribute;
  role(value: ButtonRole): ButtonAttribute;
  contentModifier(modifier: ContentModifier<ButtonConfiguration>): ButtonAttribute;
  onClick(event: (event: ClickEvent) => void): ButtonAttribute;
}

declare class ButtonModifier implements AttributeModifier<ButtonAttribute> {
  applyNormalAttribute(instance: ButtonAttribute): void;
  applyPressedAttribute?(instance: ButtonAttribute): void;
}

interface ButtonInterface {
  (): ButtonAttribute;
  (options: ButtonOptions): ButtonAttribute;
}

declare const Button: ButtonInterface;
```

Аналогичные мини-файлы для slider, menu_item, navigation (по 5-7
member-ов в каждом). Не копируй полные SDK файлы — нам нужен
deterministic fixture.

### 4.4 Шаг 2: парсер `sdk_parser.py`

Создай новый файл `src/arkui_xts_selector/indexing/sdk_parser.py`:

```python
"""tree-sitter-typescript based parser for SDK .d.ts declarations.

Extracts:
- declare class / interface / function / const X
- members of class/interface (methods, properties)
- inheritance and modifier markers

Output is a list of SymbolDiscovery objects ready to be promoted to
ApiEntityId by the indexer layer.

Import boundary: standard library + tree_sitter_parsers + model only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .parser_contracts import ParserResult, SymbolDiscovery
from ..tree_sitter_parsers import _get_ts_ts_parser


@dataclass(frozen=True)
class SdkSymbol:
    """A single symbol discovered in a .d.ts file."""
    kind: str                # "component" | "attribute" | "modifier" | "interface" | "method" | "property" | "function" | "const"
    name: str                # e.g. "Button", "ButtonAttribute", "ButtonAttribute.role"
    parent: str | None       # e.g. "ButtonAttribute" for the .role member
    member_name: str | None  # e.g. "role"
    line: int                # 1-based start
    end_line: int            # inclusive end
    span: tuple[int, int]    # byte offsets
    since_api: str | None = None
    deprecated_since: str | None = None


def parse_dts_file(path: Path) -> ParserResult:
    """Parse a .d.ts file and return a ParserResult with discovered symbols."""
    parser, lang = _get_ts_ts_parser()
    text = path.read_text(encoding="utf-8")
    tree = parser.parse(text.encode("utf-8"))

    symbols: list[SymbolDiscovery] = []
    _walk(tree.root_node, text.encode("utf-8"), str(path), symbols)

    return ParserResult(
        file_path=str(path),
        language="TS",
        parser_name="tree-sitter-typescript",
        parser_level=3,
        discovered_symbols=tuple(symbols),
        limitations=(),
    )


def _walk(node, source: bytes, file_path: str, out: list[SymbolDiscovery]) -> None:
    """Recursively walk the AST and emit SymbolDiscovery objects."""
    # Top-level declarations
    if node.type == "ambient_declaration":
        # `declare class ...`, `declare interface ...`, `declare function ...`, `declare const ...`
        for child in node.children:
            _walk(child, source, file_path, out)
        return

    if node.type == "class_declaration":
        _emit_class(node, source, file_path, out)
        return

    if node.type == "interface_declaration":
        _emit_interface(node, source, file_path, out)
        return

    if node.type == "function_declaration":
        _emit_function(node, source, file_path, out)
        return

    if node.type == "lexical_declaration":
        # const Button: ButtonInterface;
        _emit_const(node, source, file_path, out)
        return

    # Recurse into containers we care about
    if node.type in ("program", "module", "internal_module", "ambient_declaration"):
        for child in node.children:
            _walk(child, source, file_path, out)


def _emit_class(node, source: bytes, file_path: str, out: list[SymbolDiscovery]) -> None:
    """Emit a class declaration and its members."""
    name_node = _child_named(node, "type_identifier")
    if name_node is None:
        return
    class_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")

    out.append(SymbolDiscovery(
        symbol=class_name,
        kind=_classify_class(class_name),
        file_path=file_path,
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        confidence_level="strong",
    ))

    # Walk class body for members
    body = _child_named(node, "class_body")
    if body is None:
        return
    for child in body.children:
        if child.type in ("method_definition", "method_signature"):
            _emit_method(child, source, file_path, class_name, out)
        elif child.type in ("public_field_definition", "property_signature"):
            _emit_property(child, source, file_path, class_name, out)


def _emit_interface(node, source: bytes, file_path: str, out: list[SymbolDiscovery]) -> None:
    """Same shape as _emit_class but for `interface X { ... }`."""
    # TODO: implement symmetrically with _emit_class
    ...


def _emit_function(node, source: bytes, file_path: str, out: list[SymbolDiscovery]) -> None:
    """Emit a top-level function declaration."""
    # TODO: identify function name and emit
    ...


def _emit_const(node, source: bytes, file_path: str, out: list[SymbolDiscovery]) -> None:
    """Emit `declare const X: Y` as a component when Y matches XInterface."""
    # TODO: extract identifier and type, classify as component if pattern matches
    ...


def _emit_method(node, source: bytes, file_path: str, class_name: str,
                 out: list[SymbolDiscovery]) -> None:
    """Emit a method as `<class>.<method>` member symbol."""
    # TODO: extract method name, line, span
    ...


def _emit_property(node, source: bytes, file_path: str, class_name: str,
                   out: list[SymbolDiscovery]) -> None:
    """Emit a property as `<class>.<prop>` member symbol."""
    # TODO
    ...


def _classify_class(name: str) -> str:
    """Heuristic: by suffix decide what kind of API this class is."""
    if name.endswith("Modifier"):
        return "modifier"
    if name.endswith("Attribute"):
        return "attribute"
    if name.endswith("Interface"):
        return "interface_helper"
    if name.endswith("Configuration"):
        return "configuration"
    if name.endswith("Controller"):
        return "controller"
    return "component"


def _child_named(node, type_name: str):
    for c in node.children:
        if c.type == type_name:
            return c
    return None
```

> **Note for junior**. Места `# TODO` — это куски, которые ты дописываешь
> по образцу `_emit_class`. Старайся переиспользовать `_child_named`,
> читать из source через `node.start_byte:node.end_byte`. Параметры
> SymbolDiscovery бери из `indexing/parser_contracts.py`.

### 4.5 Шаг 3: индексатор `sdk_indexer.py`

Замени содержимое `src/arkui_xts_selector/indexing/sdk_indexer.py`:

```python
"""SDK declaration indexer.

Builds a registry of public API entities by parsing all .d.ts files
under interface/sdk-js/api/.

Import boundary: standard library + arkui_xts_selector.model + .sdk_parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..model.api import ApiDeclarationRef, ApiEntity, ApiEntityId
from .parser_contracts import ParserResult, SymbolDiscovery
from .sdk_parser import parse_dts_file, SdkSymbol


@dataclass
class SdkIndexEntry:
    """One public API entity in the SDK registry."""
    api_id: ApiEntityId
    declaration: ApiDeclarationRef
    parent_api_id: ApiEntityId | None = None
    member_name: str | None = None


@dataclass
class SdkIndexResult:
    """Output of build_sdk_index."""
    entries: tuple[SdkIndexEntry, ...] = ()
    parse_errors: tuple[str, ...] = ()
    files_scanned: int = 0

    def find(self, public_name: str) -> SdkIndexEntry | None:
        for e in self.entries:
            if e.api_id.public_name == public_name:
                return e
        return None


def build_sdk_index(
    sdk_root: Path,
    namespace: str = "arkui",
    surface: str = "static",
) -> SdkIndexResult:
    """Walk sdk_root for .d.ts files and return an SdkIndexResult.

    sdk_root is typically `interface/sdk-js/api/` from the OHOS workspace.
    For tests use a tiny fixture directory.
    """
    entries: list[SdkIndexEntry] = []
    errors: list[str] = []
    files = 0

    for path in sorted(sdk_root.rglob("*.d.ts")):
        files += 1
        try:
            result: ParserResult = parse_dts_file(path)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            continue
        for sym in result.discovered_symbols:
            entry = _symbol_to_entry(sym, namespace, surface, path)
            if entry is not None:
                entries.append(entry)

    return SdkIndexResult(
        entries=tuple(entries),
        parse_errors=tuple(errors),
        files_scanned=files,
    )


def _symbol_to_entry(
    sym: SymbolDiscovery,
    namespace: str,
    surface: str,
    path: Path,
) -> SdkIndexEntry | None:
    """Turn a SymbolDiscovery into an SdkIndexEntry. Returns None if the
    symbol kind is internal-only (e.g., helper interfaces)."""
    # Build canonical id
    if "." in sym.symbol:
        # member, e.g. "ButtonAttribute.role"
        owner, member = sym.symbol.split(".", 1)
        api_id = ApiEntityId.from_parts(
            namespace=namespace,
            surface=surface,
            kind="event_or_method",  # refined later by caller if needed
            module=_module_from_path(path),
            public_name=sym.symbol,
            member_of=owner,
            member_name=member,
        )
    else:
        api_id = ApiEntityId.from_parts(
            namespace=namespace,
            surface=surface,
            kind=sym.kind,
            module=_module_from_path(path),
            public_name=sym.symbol,
        )

    decl = ApiDeclarationRef(
        declaration_id=f"{path}#{sym.symbol}",
        file_path=str(path),
        export_name=sym.symbol,
        line=sym.line,
        span=(sym.line, sym.end_line),
        parser_level=3,
    )
    return SdkIndexEntry(api_id=api_id, declaration=decl,
                         member_name=getattr(sym, "member_name", None))


def _module_from_path(path: Path) -> str:
    """Derive a synthetic module name from a path.

    For interface/sdk-js/api/@internal/component/ets/button.d.ts,
    return @ohos.arkui.component.Button. Real implementation reads
    the @ohos. import declarations inside the file."""
    stem = path.stem  # "button" / "@ohos.arkui.component"
    if stem.startswith("@"):
        return stem
    return f"@ohos.arkui.component.{stem.capitalize()}"
```

### 4.6 Шаг 4: тесты

Создай `tests/test_sdk_indexer.py`:

```python
"""Unit tests for indexing/sdk_indexer with a tiny fixture."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.indexing.sdk_indexer import build_sdk_index, SdkIndexEntry


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "sdk_registry"


class SdkIndexButtonTests(unittest.TestCase):
    """Phase 1 acceptance: parse mini button.d.ts and find expected entities."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = build_sdk_index(FIXTURE_DIR)

    def test_no_parse_errors(self) -> None:
        self.assertEqual(self.result.parse_errors, ())

    def test_button_class_is_component(self) -> None:
        entry = self.result.find("Button")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.api_id.kind, "component")

    def test_button_attribute_is_attribute_kind(self) -> None:
        entry = self.result.find("ButtonAttribute")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.api_id.kind, "attribute")

    def test_button_modifier_is_modifier_kind(self) -> None:
        entry = self.result.find("ButtonModifier")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.api_id.kind, "modifier")

    def test_button_attribute_role_member_present(self) -> None:
        entry = self.result.find("ButtonAttribute.role")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.api_id.member_of, "ButtonAttribute")
        self.assertEqual(entry.api_id.member_name, "role")

    def test_button_attribute_button_style_member_present(self) -> None:
        entry = self.result.find("ButtonAttribute.buttonStyle")
        self.assertIsNotNone(entry)

    def test_button_modifier_apply_normal_attribute_method(self) -> None:
        entry = self.result.find("ButtonModifier.applyNormalAttribute")
        self.assertIsNotNone(entry)

    def test_distinct_canonical_ids(self) -> None:
        ids = {e.api_id.canonical() for e in self.result.entries}
        # All entries have distinct canonical strings
        self.assertEqual(len(ids), len(self.result.entries))


class SdkIndexSliderTests(unittest.TestCase):
    """Same shape for slider fixture."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = build_sdk_index(FIXTURE_DIR)

    def test_slider_attribute_present(self) -> None:
        self.assertIsNotNone(self.result.find("SliderAttribute"))


if __name__ == "__main__":
    unittest.main()
```

Дополнительно создай real-fixture тест, который запускает индексер на
**настоящей** sdk-js/api директории, **только** если она доступна:

```python
import os, pytest

@pytest.mark.skipif(
    not os.environ.get("OHOS_SDK_API_ROOT"),
    reason="set OHOS_SDK_API_ROOT to a real interface/sdk-js/api/ to run",
)
class SdkIndexRealRootTests(unittest.TestCase):
    def test_finds_button(self) -> None:
        root = Path(os.environ["OHOS_SDK_API_ROOT"])
        result = build_sdk_index(root)
        self.assertIsNotNone(result.find("Button"))
        self.assertGreater(len(result.entries), 100)
```

### 4.7 Шаг 5: verification

```bash
python3 -m pytest tests/test_sdk_indexer.py -v
```

Ожидание: все тесты SdkIndexButtonTests, SdkIndexSliderTests зелёные.
Real-root тест либо зелёный (если `OHOS_SDK_API_ROOT` задан), либо
skipped.

```bash
python3 -m pytest tests/test_import_boundaries.py -v
```

Не должно быть violations: `indexing/sdk_indexer.py` и
`indexing/sdk_parser.py` не импортируют `cli/`, `graph/`, `ranking/`.

```bash
python3 -m pytest
```

Полный прогон. 5 pre-existing failures + новые тесты зелёные.

### 4.8 Common failure modes

| Симптом | Причина | Что делать |
|---------|---------|------------|
| `tree_sitter_typescript not found` | пакет не установлен | `pip install tree-sitter-typescript` |
| Парсер вернул `parser_level=0` | не дошли до tree-sitter ветки | проверь, что `parse_dts_file` вызывает `_get_ts_ts_parser()` и не падает в except |
| `ButtonAttribute.role` не найден | `_emit_method` не реализован полностью | вернись к §4.4 Шагу 2, заполни TODO |
| Дубль canonical id | в `_module_from_path` все файлы дают одинаковый module | вычитай реальный @ohos. import из файла, либо используй имя файла как часть id |
| `test_distinct_canonical_ids` упал | то же самое | то же |

### 4.9 DoD для Phase 1

- [ ] `src/arkui_xts_selector/indexing/sdk_parser.py` создан и
      работает на fixture button.d.ts.
- [ ] `src/arkui_xts_selector/indexing/sdk_indexer.py::build_sdk_index`
      возвращает `SdkIndexResult` с непустым `entries`.
- [ ] `tests/fixtures/sdk_registry/` содержит 4 мини-fixtures (button,
      slider, menu_item, navigation).
- [ ] `tests/test_sdk_indexer.py` содержит ≥ 8 тестов, все зелёные.
- [ ] `python3 -m pytest tests/test_import_boundaries.py` зелёный.
- [ ] `python3 -m pytest` — не появляются новые red тесты.
- [ ] Commit по шаблону, prefix `indexing`.
- [ ] **Phase 1 → `[X] done` в §1**, дата, PR ссылка.

---

## §5 Phase 2 — L1-L4 C++ ace_indexer

> **Status:** `[ ] not started`

### 5.1 Зачем

После Phase 1 у нас есть реестр API. Теперь нужно для каждого C++
файла в `frameworks/core/components_ng/pattern/`,
`frameworks/core/interfaces/native/{implementation,node}/`,
`frameworks/bridge/declarative_frontend/jsview/` извлечь:

- классы и методы с line/end_line/span;
- сопоставить методы с API entity из реестра Phase 1.

После Phase 2 для **любого** PR, меняющего C++ файл в этих
директориях, селектор сможет назвать конкретные затронутые API.

### 5.2 Что создаём

```
src/arkui_xts_selector/indexing/cpp_parser.py        (новый)
src/arkui_xts_selector/indexing/ace_indexer.py       (заменить boilerplate)
src/arkui_xts_selector/indexing/file_role.py         (новый: классификация file_role)
src/arkui_xts_selector/indexing/source_to_api.py     (новый: правила mapping)
tests/test_cpp_parser.py                              (новый)
tests/test_ace_indexer.py                             (новый)
tests/test_file_role.py                               (новый)
tests/test_source_to_api.py                           (новый)
tests/fixtures/ace_engine/                           (новый каталог с fixtures)
   pattern/button/button_pattern.cpp
   pattern/button/button_pattern.h
   pattern/button/button_model_static.cpp
   interfaces/native/implementation/button_modifier.cpp
   interfaces/native/node/button_modifier.cpp
   bridge/declarative_frontend/jsview/js_button.cpp
```

### 5.3 Шаг 1: file_role classification

Создай `src/arkui_xts_selector/indexing/file_role.py`:

```python
"""Classify an ace_engine source file by its role.

The role determines which mapping rules apply to extracted symbols.
"""

from __future__ import annotations

import re
from typing import Literal

FileRole = Literal[
    "pattern",                  # pattern/<x>/<x>_pattern.{cpp,h}
    "model_static",             # pattern/<x>/<x>_model_static.{cpp,h}
    "model_ng",                 # pattern/<x>/<x>_model_ng.{cpp,h}
    "model_other",              # pattern/<x>/*_model.{cpp,h}
    "native_modifier",          # interfaces/native/implementation/<x>_modifier.{cpp,h}
    "native_node_accessor",     # interfaces/native/node/<x>_modifier.{cpp,h}
    "jsview_dynamic",           # bridge/declarative_frontend/jsview/js_<x>.{cpp,h}
    "infrastructure",           # frame_node, pipeline_context, etc.
    "unknown",
]


_PATTERN_RX = re.compile(
    r"frameworks/core/components_ng/pattern/(?P<family>[^/]+)/(?P<file>[^/]+)\.(?:cpp|h|hpp)$"
)
_NATIVE_IMPL_RX = re.compile(
    r"frameworks/core/interfaces/native/implementation/(?P<family>[a-z0-9_]+)_modifier\.(?:cpp|h)$"
)
_NATIVE_NODE_RX = re.compile(
    r"frameworks/core/interfaces/native/node/(?P<family>[a-z0-9_]+)(?:_node)?_modifier\.(?:cpp|h)$"
)
_JSVIEW_RX = re.compile(
    r"frameworks/bridge/declarative_frontend/jsview/js_(?P<family>[a-z0-9_]+)\.(?:cpp|h)$"
)
_INFRA_PATHS = (
    "frameworks/core/components_ng/base/frame_node",
    "frameworks/core/pipeline_ng/pipeline_context",
    "frameworks/core/pipeline_ng/pipeline_base",
    "frameworks/core/pipeline/pipeline_context",
    "frameworks/core/components_ng/manager/",
)


def classify(rel_path: str) -> tuple[FileRole, str | None]:
    """Return (role, family). family is component name when known."""
    m = _PATTERN_RX.search(rel_path)
    if m:
        family = m.group("family")
        file = m.group("file")
        if file.endswith("_model_static"):
            return ("model_static", family)
        if file.endswith("_model_ng"):
            return ("model_ng", family)
        if file.endswith("_model"):
            return ("model_other", family)
        if file.endswith("_pattern"):
            return ("pattern", family)
        return ("pattern", family)  # default within pattern/<x>/

    m = _NATIVE_IMPL_RX.search(rel_path)
    if m:
        return ("native_modifier", m.group("family"))

    m = _NATIVE_NODE_RX.search(rel_path)
    if m:
        return ("native_node_accessor", m.group("family"))

    m = _JSVIEW_RX.search(rel_path)
    if m:
        return ("jsview_dynamic", m.group("family"))

    for p in _INFRA_PATHS:
        if p in rel_path:
            return ("infrastructure", None)

    return ("unknown", None)
```

Тесты `tests/test_file_role.py`:

```python
import unittest
from arkui_xts_selector.indexing.file_role import classify


class FileRoleTests(unittest.TestCase):
    def test_pattern_button(self) -> None:
        role, fam = classify("foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/button/button_pattern.cpp")
        self.assertEqual(role, "pattern")
        self.assertEqual(fam, "button")

    def test_model_static(self) -> None:
        role, fam = classify(".../pattern/button/button_model_static.cpp")
        self.assertEqual(role, "model_static")
        self.assertEqual(fam, "button")

    def test_native_modifier(self) -> None:
        role, fam = classify(".../interfaces/native/implementation/button_modifier.cpp")
        self.assertEqual(role, "native_modifier")
        self.assertEqual(fam, "button")

    def test_native_node_accessor(self) -> None:
        role, fam = classify(".../interfaces/native/node/button_modifier.cpp")
        self.assertEqual(role, "native_node_accessor")
        self.assertEqual(fam, "button")

    def test_jsview_dynamic(self) -> None:
        role, fam = classify(".../bridge/declarative_frontend/jsview/js_button.cpp")
        self.assertEqual(role, "jsview_dynamic")
        self.assertEqual(fam, "button")

    def test_frame_node_is_infrastructure(self) -> None:
        role, fam = classify(".../components_ng/base/frame_node.cpp")
        self.assertEqual(role, "infrastructure")
        self.assertIsNone(fam)

    def test_unknown(self) -> None:
        role, fam = classify("path/not/recognized.cpp")
        self.assertEqual(role, "unknown")
```

### 5.4 Шаг 2: cpp_parser.py

Создай `src/arkui_xts_selector/indexing/cpp_parser.py`. Использует
`tree-sitter-cpp`:

```python
"""tree-sitter-cpp parser for ace_engine source files.

Extracts:
- class definitions (with base class)
- method definitions inside class with full body span
- top-level function definitions
- include directives (for fan-out tracing)

Output is a CppParseResult with all symbols and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..tree_sitter_parsers import _get_ts_cpp_parser


@dataclass(frozen=True)
class CppMethod:
    name: str                # bare method name e.g. "SetRole"
    parent_class: str | None # e.g. "ButtonModelStatic"
    qualified: str           # "ButtonModelStatic::SetRole"
    line: int                # 1-based start of definition
    end_line: int            # 1-based end of body
    body_span: tuple[int, int]  # byte offsets


@dataclass(frozen=True)
class CppClass:
    name: str
    base_class: str | None
    line: int
    end_line: int
    methods: tuple[CppMethod, ...] = ()


@dataclass(frozen=True)
class CppParseResult:
    file_path: str
    parser_level: int = 3
    classes: tuple[CppClass, ...] = ()
    free_functions: tuple[CppMethod, ...] = ()
    includes: tuple[str, ...] = ()


def parse_cpp_file(path: Path) -> CppParseResult:
    """Parse a C++ file and return discovered classes/methods."""
    parser, lang = _get_ts_cpp_parser()
    text = path.read_text(encoding="utf-8", errors="replace")
    tree = parser.parse(text.encode("utf-8"))

    classes: list[CppClass] = []
    free: list[CppMethod] = []
    includes: list[str] = []

    _walk(tree.root_node, text.encode("utf-8"), classes, free, includes)

    return CppParseResult(
        file_path=str(path),
        classes=tuple(classes),
        free_functions=tuple(free),
        includes=tuple(includes),
    )


def _walk(node, source: bytes, classes, free, includes) -> None:
    if node.type == "preproc_include":
        text = source[node.start_byte:node.end_byte].decode("utf-8", "replace")
        includes.append(text.strip())
        return

    if node.type == "class_specifier":
        cls = _build_class(node, source)
        if cls is not None:
            classes.append(cls)
        return

    if node.type == "function_definition":
        # top-level function (not inside a class)
        m = _build_method(node, source, parent_class=None)
        if m is not None:
            free.append(m)
        return

    for c in node.children:
        _walk(c, source, classes, free, includes)


def _build_class(node, source: bytes) -> CppClass | None:
    name_node = _child_first(node, "type_identifier")
    if name_node is None:
        return None
    name = source[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace")
    base_class = _extract_base_class(node, source)
    body = _child_first(node, "field_declaration_list")
    methods: list[CppMethod] = []
    if body is not None:
        for child in body.children:
            if child.type == "function_definition":
                m = _build_method(child, source, parent_class=name)
                if m is not None:
                    methods.append(m)
    return CppClass(
        name=name,
        base_class=base_class,
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        methods=tuple(methods),
    )


def _build_method(node, source: bytes, parent_class: str | None) -> CppMethod | None:
    decl = _child_first(node, "function_declarator")
    if decl is None:
        return None
    name_node = _child_first(decl, "field_identifier") or _child_first(decl, "identifier") or _child_first(decl, "qualified_identifier")
    if name_node is None:
        return None
    name = source[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace")
    qualified = f"{parent_class}::{name}" if parent_class else name
    body_node = _child_first(node, "compound_statement")
    body_span = (body_node.start_byte, body_node.end_byte) if body_node else (node.start_byte, node.end_byte)
    return CppMethod(
        name=name,
        parent_class=parent_class,
        qualified=qualified,
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        body_span=body_span,
    )


def _extract_base_class(class_node, source: bytes) -> str | None:
    # tree-sitter-cpp puts base classes in `base_class_clause`
    bcc = _child_first(class_node, "base_class_clause")
    if bcc is None:
        return None
    type_node = _child_first(bcc, "type_identifier")
    if type_node is None:
        return None
    return source[type_node.start_byte:type_node.end_byte].decode("utf-8", "replace")


def _child_first(node, type_name: str):
    for c in node.children:
        if c.type == type_name:
            return c
    return None
```

Тесты `tests/test_cpp_parser.py`:

```python
import unittest
from pathlib import Path

from arkui_xts_selector.indexing.cpp_parser import parse_cpp_file


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ace_engine"


class CppParserTests(unittest.TestCase):
    def test_button_pattern_classes(self) -> None:
        result = parse_cpp_file(FIXTURE / "pattern" / "button" / "button_pattern.cpp")
        names = [c.name for c in result.classes]
        self.assertIn("ButtonPattern", names)

    def test_method_qualified_name(self) -> None:
        result = parse_cpp_file(FIXTURE / "pattern" / "button" / "button_pattern.cpp")
        cls = next(c for c in result.classes if c.name == "ButtonPattern")
        methods = {m.qualified for m in cls.methods}
        self.assertIn("ButtonPattern::OnClick", methods)

    def test_method_span_recorded(self) -> None:
        result = parse_cpp_file(FIXTURE / "pattern" / "button" / "button_model_static.cpp")
        cls = next(c for c in result.classes if c.name == "ButtonModelStatic")
        for m in cls.methods:
            self.assertGreater(m.end_line, m.line)
            self.assertEqual(len(m.body_span), 2)

    def test_includes_collected(self) -> None:
        result = parse_cpp_file(FIXTURE / "interfaces" / "native" / "implementation" / "button_modifier.cpp")
        self.assertTrue(any("button" in inc.lower() for inc in result.includes))
```

Используй mini-fixtures:

```cpp
// tests/fixtures/ace_engine/pattern/button/button_pattern.cpp
#include "core/components_ng/pattern/button/button_pattern.h"

namespace OHOS::Ace::NG {

class ButtonPattern : public Pattern {
public:
    void OnClick(const ClickEventInfo& info) {
        // ...
    }
    void OnAttachToFrameNode() override {
        // ...
    }
};

}  // namespace OHOS::Ace::NG
```

Аналогичные mini-fixtures для button_model_static, button_modifier и пр.
**Не копируй настоящие файлы из OHOS** — нам нужны deterministic
fixtures.

### 5.5 Шаг 3: source_to_api.py

Это правила «file_role + class/method → ApiEntityId».

Создай `src/arkui_xts_selector/indexing/source_to_api.py`:

```python
"""Map (file_role, family, parsed C++ symbols) → public API entities.

Rules per file_role:
  pattern:              <X>Pattern::<m> → API event Button.on<m>
                        <X>Pattern::Set<P> → API attribute member <X>Attribute.<p>
  model_static:         <X>ModelStatic::Set<P> → ButtonAttribute.<p>
  native_modifier:      <X>ModifierAccessor::<m> → method on ButtonModifier
  native_node_accessor: GetButton<X>Accessor → ButtonModifier surface
  jsview_dynamic:       JSButton::<m> → dynamic surface of Button
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.api import ApiEntityId
from ..model.evidence import ConfidenceLevel
from .cpp_parser import CppClass, CppMethod, CppParseResult
from .file_role import FileRole
from .sdk_indexer import SdkIndexResult


@dataclass(frozen=True)
class ResolvedApiEdge:
    """One source-to-API edge with provenance and confidence."""
    api_id: ApiEntityId
    edge_kind: str              # "implements" | "provides_static_modifier" | "bridges_dynamic" | "backs_component"
    source_method: str          # e.g. "ButtonModelStatic::SetRole"
    source_line: int
    source_end_line: int
    confidence: ConfidenceLevel
    parser_level: int


def resolve_edges(
    parse_result: CppParseResult,
    role: FileRole,
    family: str | None,
    sdk: SdkIndexResult,
) -> list[ResolvedApiEdge]:
    """Apply per-role rules and return ResolvedApiEdge list."""
    edges: list[ResolvedApiEdge] = []
    if role == "pattern":
        edges.extend(_resolve_pattern(parse_result, family, sdk))
    elif role == "model_static":
        edges.extend(_resolve_model_static(parse_result, family, sdk))
    elif role == "native_modifier":
        edges.extend(_resolve_native_modifier(parse_result, family, sdk))
    elif role == "native_node_accessor":
        edges.extend(_resolve_node_accessor(parse_result, family, sdk))
    elif role == "jsview_dynamic":
        edges.extend(_resolve_jsview(parse_result, family, sdk))
    # infrastructure & unknown handled elsewhere
    return edges


def _resolve_model_static(parse_result, family, sdk) -> list[ResolvedApiEdge]:
    """For each ButtonModelStatic::Set<Prop> method, map to
    ButtonAttribute.<prop> if such API entity exists in SDK."""
    edges: list[ResolvedApiEdge] = []
    family_pascal = (family or "").capitalize()  # "Button"
    expected_class = f"{family_pascal}ModelStatic"
    for cls in parse_result.classes:
        if cls.name != expected_class:
            continue
        for m in cls.methods:
            if not m.name.startswith("Set"):
                continue
            prop_pascal = m.name[3:]            # "Role"
            prop_camel = prop_pascal[0].lower() + prop_pascal[1:]  # "role"
            target = f"{family_pascal}Attribute.{prop_camel}"
            entry = sdk.find(target)
            if entry is None:
                continue        # no public API to attribute this method to
            edges.append(ResolvedApiEdge(
                api_id=entry.api_id,
                edge_kind="implements",
                source_method=m.qualified,
                source_line=m.line,
                source_end_line=m.end_line,
                confidence="strong",
                parser_level=3,
            ))
    return edges


def _resolve_native_modifier(parse_result, family, sdk) -> list[ResolvedApiEdge]:
    """For native_modifier files: <X>Modifier API entity itself is
    the target. Each method inside is provides_static_modifier edge."""
    family_pascal = (family or "").capitalize()
    target = f"{family_pascal}Modifier"
    entry = sdk.find(target)
    if entry is None:
        return []
    edges: list[ResolvedApiEdge] = []
    # File-level edge: any change to this file affects ButtonModifier.
    # Method-level we attach to first method in main class for span.
    for cls in parse_result.classes:
        if not cls.name.endswith("Accessor") and cls.name != target:
            continue
        for m in cls.methods:
            edges.append(ResolvedApiEdge(
                api_id=entry.api_id,
                edge_kind="provides_static_modifier",
                source_method=m.qualified,
                source_line=m.line,
                source_end_line=m.end_line,
                confidence="strong",
                parser_level=3,
            ))
    return edges


def _resolve_pattern(parse_result, family, sdk) -> list[ResolvedApiEdge]:
    """TODO: ButtonPattern::OnClick → Button.onClick event."""
    return []


def _resolve_node_accessor(parse_result, family, sdk) -> list[ResolvedApiEdge]:
    """TODO: native node accessor → bridges_native edge."""
    return []


def _resolve_jsview(parse_result, family, sdk) -> list[ResolvedApiEdge]:
    """TODO: JSButton dynamic class → bridges_dynamic edges."""
    return []
```

> **Note for junior**. Реализуй `_resolve_pattern`, `_resolve_node_accessor`,
> `_resolve_jsview` по аналогии. Главное правило: всегда проверяй
> `sdk.find(target)` — если public API entity нет в реестре, не
> создавай ребро (это означает internal/helper class).

### 5.6 Шаг 4: ace_indexer.py

Замени текущий boilerplate `indexing/ace_indexer.py`:

```python
"""AceEngine source indexer: walks ace_engine source roots, parses
each file via cpp_parser, classifies it via file_role, and resolves
edges via source_to_api.

Output is an AceIndexResult listing ResolvedApiEdge across all files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .cpp_parser import parse_cpp_file
from .file_role import classify
from .sdk_indexer import SdkIndexResult
from .source_to_api import ResolvedApiEdge, resolve_edges


@dataclass
class AceFileEntry:
    rel_path: str
    role: str
    family: str | None
    edges: tuple[ResolvedApiEdge, ...]


@dataclass
class AceIndexResult:
    entries: tuple[AceFileEntry, ...] = ()
    files_scanned: int = 0
    parse_errors: tuple[str, ...] = ()


_DEFAULT_ROOTS = (
    "frameworks/core/components_ng/pattern",
    "frameworks/core/interfaces/native/implementation",
    "frameworks/core/interfaces/native/node",
    "frameworks/bridge/declarative_frontend/jsview",
)


def build_ace_index(
    repo_root: Path,
    sdk: SdkIndexResult,
    roots: tuple[str, ...] = _DEFAULT_ROOTS,
) -> AceIndexResult:
    entries: list[AceFileEntry] = []
    errors: list[str] = []
    scanned = 0
    for root in roots:
        full = repo_root / root
        if not full.exists():
            continue
        for path in sorted(full.rglob("*.cpp")):
            scanned += 1
            try:
                parsed = parse_cpp_file(path)
            except Exception as exc:
                errors.append(f"{path}: {exc}")
                continue
            rel = str(path.relative_to(repo_root))
            role, family = classify(rel)
            edges = resolve_edges(parsed, role, family, sdk)
            entries.append(AceFileEntry(
                rel_path=rel,
                role=role,
                family=family,
                edges=tuple(edges),
            ))
    return AceIndexResult(
        entries=tuple(entries),
        files_scanned=scanned,
        parse_errors=tuple(errors),
    )
```

### 5.7 Шаг 5: тесты ace_indexer + source_to_api

Создай `tests/test_ace_indexer.py` и `tests/test_source_to_api.py` по
шаблону Phase 1. Проверяй на mini-fixtures под
`tests/fixtures/ace_engine/`:

- `button_model_static.cpp::ButtonModelStatic::SetRole` →
  `ResolvedApiEdge(api_id=ButtonAttribute.role, edge_kind=implements)`.
- `button_modifier.cpp::ButtonModifierAccessor::SetButtonStyle` →
  `provides_static_modifier`.
- `js_button.cpp::JSButton::JSBind` (если реализуешь _resolve_jsview)
  → `bridges_dynamic`.
- Файл, который не нашёл соответствия в SDK — `edges == ()`.
- `unknown` role → `edges == ()`.

### 5.8 DoD для Phase 2

- [ ] `cpp_parser.py`, `file_role.py`, `source_to_api.py`, `ace_indexer.py`
      созданы/обновлены.
- [ ] `tests/fixtures/ace_engine/` содержит ≥ 6 mini C++ fixture-файлов.
- [ ] `tests/test_cpp_parser.py`, `test_file_role.py`,
      `test_source_to_api.py`, `test_ace_indexer.py` — каждый ≥ 5
      тестов, все зелёные.
- [ ] Опциональный real-root тест (под env var `OHOS_REPO_ROOT`)
      собирает `AceIndexResult` без parse_errors на настоящем
      `frameworks/core/components_ng/pattern/button/`.
- [ ] `python3 -m pytest tests/test_import_boundaries.py` зелёный
      (новые модули в `indexing/` не импортируют `cli`/`graph`/`ranking`).
- [ ] **Phase 2 → `[X] done` в §1**, дата, PR ссылка.

---

## §6 Phase 3 — L5/L6 ArkTS ets_indexer

> **Status:** `[ ] not started`

### 6.1 Зачем

После Phase 2 мы покрываем C++ слой. Теперь нужно покрыть ArkTS-слой:

- L5 generated: `bridge/arkts_frontend/.../arkoala-arkts/arkui-ohos/generated/component/*.ets`
- L6 authored:  `bridge/arkts_frontend/.../arkoala-arkts/arkui-ohos/src/component/*.ets`

И отдельно — XTS consumer-файлы (`test/xts/acts/arkui/.../*.ets`) для
извлечения `ApiUsageSignature`.

### 6.2 Что создаём

```
src/arkui_xts_selector/indexing/ets_parser.py        (новый)
src/arkui_xts_selector/indexing/ets_indexer.py       (новый)
src/arkui_xts_selector/indexing/usage_extractor.py   (новый — для consumer-файлов)
tests/test_ets_parser.py
tests/test_ets_indexer.py
tests/test_usage_extractor.py
tests/fixtures/ets/
   generated/component/button.ets
   src/component/button.ets
   xts/button_role_test.ets
```

### 6.3 Шаг 1: ets_parser.py

Аналогично `cpp_parser.py`, использует `_get_ts_ts_parser()` из
`tree_sitter_parsers.py`. Извлекает:

- `export class X` / `export interface X`
- `export function X(...)`
- `export const X: T`
- methods/properties внутри классов/интерфейсов
- import-statements

Структуры аналогичны `CppClass`/`CppMethod`. Не копируй, делай
параллельные `EtsClass`, `EtsInterface`, `EtsMethod`, `EtsImport`.

### 6.4 Шаг 2: ets_indexer.py

Walk:
- `bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/generated/component/`
- `bridge/arkts_frontend/koala_projects/arkoala-arkts/arkui-ohos/src/component/`

Per-file role:
- `generated_arkts_bridge` (path `generated/component/`)
- `authored_arkts_bridge` (path `src/component/`)

Для каждого файла находить exports и сопоставлять с SDK registry:
- export `class Button` → API entity `Button` (component, surface=static, language_binding=arkts)
- export `class ButtonAttribute` → API entity `ButtonAttribute`
- members → member API entities

### 6.5 Шаг 3: usage_extractor.py

Это **самостоятельный, отдельный** модуль — он работает на
consumer-файлах (XTS-тестах), не на bridge-коде.

Вход: `tests/fixtures/ets/xts/button_role_test.ets`:
```typescript
import { Button, ButtonAttribute, ButtonRole } from '@ohos.arkui.component';

@Entry
@Component
struct ButtonRoleTest {
  build() {
    Button() { Text('Click') }.role(ButtonRole.Normal).onClick(() => {});
  }
}
```

Выход: список `ApiUsageSignature`:
```python
[
  ApiUsageSignature(
    api_entity_id=<Button>,
    usage_kind="component_instantiation",
    argument_shape="no_args",
    line=5,
    project_id="...",
    parser_provenance="tree-sitter-typescript",
    parser_level=3,
    confidence="strong",
  ),
  ApiUsageSignature(
    api_entity_id=<ButtonAttribute.role>,
    usage_kind="chained_modifier",
    argument_shape="enum",
    receiver_type="ButtonAttribute",
    line=5,
    parser_level=3,
    confidence="strong",
  ),
  ApiUsageSignature(
    api_entity_id=<Button.onClick>,  # or ButtonAttribute.onClick
    usage_kind="event_handler",
    argument_shape="lambda",
    line=5,
    parser_level=3,
    confidence="strong",
  ),
]
```

### 6.6 Тесты

`tests/test_ets_indexer.py`:

```python
def test_generated_button_exports_button(self) -> None:
    result = build_ets_index(FIXTURE_DIR, sdk_registry)
    button_files = [e for e in result.entries
                    if e.rel_path.endswith("generated/component/button.ets")]
    self.assertEqual(len(button_files), 1)
    edges = button_files[0].edges
    apis = [e.api_id.public_name for e in edges]
    self.assertIn("Button", apis)
    self.assertIn("ButtonAttribute", apis)
    self.assertIn("ButtonModifier", apis)
```

`tests/test_usage_extractor.py`:

```python
def test_chained_modifier_role_extracted(self) -> None:
    sigs = extract_usage_signatures(FIXTURE_DIR / "xts/button_role_test.ets", sdk)
    role_sig = next(s for s in sigs if s.api_entity_id.public_name == "ButtonAttribute.role")
    self.assertEqual(role_sig.usage_kind, "chained_modifier")
    self.assertEqual(role_sig.argument_shape, "enum")
```

### 6.7 DoD для Phase 3

- [ ] `ets_parser.py`, `ets_indexer.py`, `usage_extractor.py` созданы.
- [ ] `tests/fixtures/ets/` содержит generated + authored + xts fixtures.
- [ ] Все три тестовых файла ≥ 5 тестов каждый, зелёные.
- [ ] Опциональный real-root тест на `arkoala-arkts/.../generated/component/`
      без parse_errors.
- [ ] `python3 -m pytest tests/test_import_boundaries.py` зелёный.
- [ ] **Phase 3 → `[X] done` в §1**, дата, PR ссылка.

---

## §7 Phase 4 — Broad infrastructure rules

> **Status:** `[ ] not started`

### 7.1 Зачем

Файлы вроде `frame_node.cpp`, `pipeline_context.cpp`,
`idlize/*.tgz`, `koala-wrapper/*.cpp` затрагивают **много** API. Нельзя
их «узко резолвить» — селектор должен явно сказать «high/critical risk
of false negative; consider running broader test set».

### 7.2 Что создаём

```
config/broad_infrastructure_files.json   (новый config)
src/arkui_xts_selector/indexing/broad_infra.py   (новый)
tests/test_broad_infra.py
```

### 7.3 Шаг 1: config

Создай `config/broad_infrastructure_files.json`:

```json
{
  "schema_version": "v1",
  "rules": [
    {
      "id": "frame_node_core",
      "match_paths": [
        "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.cpp",
        "foundation/arkui/ace_engine/frameworks/core/components_ng/base/frame_node.h"
      ],
      "fan_out_target": "all_pattern_components",
      "false_negative_risk": "critical",
      "rationale": "FrameNode is the base class for every UI element. Any change can affect layout, paint, event, or focus behavior of every component."
    },
    {
      "id": "pipeline_context",
      "match_paths": [
        "foundation/arkui/ace_engine/frameworks/core/pipeline_ng/pipeline_context.cpp",
        "foundation/arkui/ace_engine/frameworks/core/pipeline/pipeline_base.cpp"
      ],
      "fan_out_target": "all_components",
      "false_negative_risk": "high"
    },
    {
      "id": "idlize_generator",
      "match_paths": [
        "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/arkui_idlize/.*\\.tgz"
      ],
      "match_kind": "regex",
      "fan_out_target": "all_arkts_generated_bridges",
      "false_negative_risk": "critical",
      "rationale": "Generator package change re-generates all ArkTS bridge files; effective surface change is enormous."
    },
    {
      "id": "koala_wrapper",
      "match_paths": [
        "foundation/arkui/ace_engine/frameworks/bridge/arkts_frontend/koala_projects/.*/koala-wrapper/.*\\.cpp"
      ],
      "match_kind": "regex",
      "fan_out_target": "all_arkts_runtime_consumers",
      "false_negative_risk": "high"
    }
  ]
}
```

### 7.4 Шаг 2: broad_infra.py

```python
"""Match changed files against broad infrastructure rules."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..model.risk import FalseNegativeRisk


@dataclass(frozen=True)
class BroadInfraMatch:
    rule_id: str
    rationale: str
    fan_out_target: str
    false_negative_risk: FalseNegativeRisk


def load_rules(path: Path) -> list[dict]:
    return json.loads(path.read_text())["rules"]


def match_changed_file(rel_path: str, rules: list[dict]) -> BroadInfraMatch | None:
    for rule in rules:
        kind = rule.get("match_kind", "exact")
        for pattern in rule["match_paths"]:
            if kind == "regex":
                if re.search(pattern, rel_path):
                    return _to_match(rule)
            else:
                if rel_path == pattern or rel_path.endswith(pattern):
                    return _to_match(rule)
    return None


def _to_match(rule: dict) -> BroadInfraMatch:
    return BroadInfraMatch(
        rule_id=rule["id"],
        rationale=rule.get("rationale", ""),
        fan_out_target=rule["fan_out_target"],
        false_negative_risk=rule["false_negative_risk"],
    )
```

### 7.5 Шаг 3: интеграция в shadow output

В `graph/resolver.py` (или в новом модуле, если хочешь сохранить
изоляцию) добавь функцию:

```python
def resolve_with_broad_infra(
    changed_files: list[str],
    rules_path: Path,
) -> tuple[list[BroadInfraMatch], FalseNegativeRisk]:
    """Return matches + overall risk for the input set."""
    rules = load_rules(rules_path)
    matches = []
    overall = "low"
    for f in changed_files:
        m = match_changed_file(f, rules)
        if m is None:
            continue
        matches.append(m)
        overall = _max_risk(overall, m.false_negative_risk)
    return matches, overall


def _max_risk(a: FalseNegativeRisk, b: FalseNegativeRisk) -> FalseNegativeRisk:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return a if order[a] >= order[b] else b
```

### 7.6 DoD для Phase 4

- [ ] `config/broad_infrastructure_files.json` создан и валидируется
      JSON-парсером.
- [ ] `indexing/broad_infra.py::match_changed_file` ловит каждое из
      4 правил.
- [ ] `tests/test_broad_infra.py` ≥ 8 тестов:
      - `frame_node.cpp` → critical;
      - `frame_node.h` → critical;
      - `pipeline_context.cpp` → high;
      - `idlize/foo-2.1.tgz` (regex) → critical;
      - `koala-wrapper/foo.cpp` (regex) → high;
      - `not_infrastructure.cpp` → None;
      - max-risk merge для нескольких файлов;
      - JSON-схема валидируется.
- [ ] `python3 -m pytest tests/test_broad_infra.py` зелёный.
- [ ] **Phase 4 → `[X] done` в §1**, дата, PR ссылка.

---

## §8 Phase 5 — Hunk resolution + CLI explain

> **Status:** `[ ] not started`

### 8.1 Зачем

Это последняя фаза — она доводит резолюцию до member-level точности
и даёт пользователю CLI-флаг для отслеживания цепочки.

### 8.2 Что создаём

```
src/arkui_xts_selector/indexing/symbol_span_index.py   (новый)
src/arkui_xts_selector/cli/trace.py                    (новый — отдельный submodule)
src/arkui_xts_selector/cli/explain.py                  (новый)
tests/test_symbol_span_index.py
tests/test_cli_trace.py
tests/test_cli_explain.py
```

### 8.3 Шаг 1: symbol_span_index.py

```python
"""Build a per-file symbol-span index: file_path → [(symbol, line, end_line, parent_class)].

Used to resolve `--changed-range` to enclosing function/class.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ace_indexer import AceFileEntry, AceIndexResult
from .ets_indexer import EtsFileEntry, EtsIndexResult


@dataclass(frozen=True)
class SymbolSpan:
    symbol: str
    parent_class: str | None
    line: int
    end_line: int


def build_symbol_span_index(
    ace_index: AceIndexResult,
    ets_index: "EtsIndexResult | None" = None,
) -> dict[str, list[SymbolSpan]]:
    out: dict[str, list[SymbolSpan]] = {}
    for entry in ace_index.entries:
        spans: list[SymbolSpan] = []
        # iterate entry.edges? we need raw classes/methods, not edges.
        # better: re-parse the file or carry classes alongside edges.
        # decision: extend AceFileEntry with `classes: tuple[CppClass, ...]`
        # and use them here.
        ...
        out[entry.rel_path] = spans
    if ets_index:
        ...  # similar for ETS
    return out


def symbols_in_range(
    spans: list[SymbolSpan],
    ranges: list[tuple[int, int]],
) -> set[str]:
    """Return qualified symbols (parent::name) that overlap any range."""
    hits: set[str] = set()
    for s in spans:
        for r1, r2 in ranges:
            if max(s.line, r1) <= min(s.end_line, r2):
                if s.parent_class:
                    hits.add(f"{s.parent_class}::{s.symbol}")
                else:
                    hits.add(s.symbol)
                break
    return hits
```

### 8.4 Шаг 2: cli/trace.py и cli/explain.py

Новый CLI submodule с двумя командами:

```python
# src/arkui_xts_selector/cli/trace.py
"""--trace <file>:<symbol> — show the full chain from a source symbol
to consumer tests."""

import argparse
import json
import sys
from pathlib import Path

from ..indexing.ace_indexer import build_ace_index
from ..indexing.sdk_indexer import build_sdk_index
from ..indexing.ets_indexer import build_ets_index


def cmd_trace(args: argparse.Namespace) -> int:
    file_path, _, symbol = args.target.partition(":")
    sdk = build_sdk_index(args.sdk_root)
    ace = build_ace_index(args.repo_root, sdk)
    # find file in index
    entry = next((e for e in ace.entries if e.rel_path.endswith(file_path)), None)
    if entry is None:
        print(f"File {file_path} not found in ace_index", file=sys.stderr)
        return 1
    edges = [e for e in entry.edges
             if not symbol or e.source_method.endswith(symbol)]
    if not edges:
        print(f"No edges for {file_path}:{symbol}", file=sys.stderr)
        return 1
    # render chain
    for edge in edges:
        print(f"{file_path}:{edge.source_line}")
        print(f"  └─ method {edge.source_method} [span {edge.source_line}-{edge.source_end_line}]")
        print(f"     └─ {edge.edge_kind} → {edge.api_id.canonical()}")
    return 0
```

```python
# src/arkui_xts_selector/cli/explain.py
"""--explain <api_canonical_id> — list consumer tests using this API."""

# Implementation: scan XTS index for usage signatures matching api_id,
# render consumer files + projects + run targets.
```

### 8.5 Шаг 3: интеграция в существующий CLI

В `cli.py` добавить **новые опциональные подкоманды**, не ломая
существующий путь:

```python
# В parse_args:
sub = parser.add_subparsers(dest="cmd", required=False)
trace_p = sub.add_parser("trace", help="Trace file:symbol → API → tests")
trace_p.add_argument("target")
trace_p.add_argument("--repo-root", default=".")
trace_p.add_argument("--sdk-root")
trace_p.set_defaults(func=cmd_trace)

explain_p = sub.add_parser("explain", help="Explain why a test was selected")
explain_p.add_argument("test_project")
explain_p.set_defaults(func=cmd_explain)

# В main:
args = parser.parse_args()
if args.cmd:
    return args.func(args)
# else continue with the existing default flow
```

### 8.6 Тесты

`tests/test_symbol_span_index.py`:
- `symbols_in_range` returns enclosing methods correctly.
- Range that doesn't overlap any symbol returns empty set.
- Multiple ranges merge correctly.

`tests/test_cli_trace.py` / `test_cli_explain.py`:
- Запуск через subprocess или through `main_entry()`-style invocation.
- Проверить, что trace выводит правильную цепочку для fixture.

### 8.7 DoD для Phase 5

- [ ] `symbol_span_index.py` собирает spans из `ace_indexer.py` /
      `ets_indexer.py` результатов.
- [ ] `cli/trace.py`, `cli/explain.py` — новые подкоманды.
- [ ] `arkui-xts-selector trace pattern/button/button_model_static.cpp:SetRole`
      выдаёт цепочку с API entity и хотя бы одним consumer-тестом.
- [ ] `arkui-xts-selector explain test/.../button_role_static`
      выдаёт «список API, которые этот тест покрывает».
- [ ] Тесты ≥ 5 на каждый submodule, зелёные.
- [ ] Default CLI-выход (`arkui-xts-selector --pr-url ...`)
      **не изменился** — verify через сравнение с baseline.
- [ ] **Phase 5 → `[X] done` в §1**, дата, PR ссылка.

---

## §9 Глобальная DoD: после всех 5 фаз

Прогон скрипта валидации на 300 PR для сравнения с baseline:

```bash
python3 scripts/validate_pr_batch.py
python3 -c "
import json
data = json.load(open('local/pr_validation_summary.json'))
ok = [r for r in data if r.get('status') == 'ok']
total_files = sum(len(r.get('changed_files', [])) for r in ok)
# Need to extend extract_summary in validate_pr_batch.py first
# to count files_with_aae - this is part of R20 fix.
print('OK PRs:', len(ok))
print('Total changed_files:', total_files)
"
```

Цели:

| Метрика | До (baseline) | После Phase 5 (цель) | Достигнуто? |
|---------|--------------:|---------------------:|:-----------:|
| Файлы с populated `affected_api_entities` | 1.6 % | ≥ 90 % | `[ ]` |
| Median required count | 17 | 5-15 | `[ ]` |
| Median optional count | 292 | ≤ 100 | `[ ]` |
| Optional/required ratio | 17:1 | ≤ 5:1 | `[ ]` |
| Timeout PRs (120s) | 53 % | ≤ 20 % | `[ ]` |
| Trace chain available для PR | 0 % | 100 % через `--trace` | `[ ]` |

Перед галочкой junior должен:

1. Прогнать `scripts/validate_pr_batch.py` с расширенной
   extract_summary (см. R20 в backlog — может потребоваться отдельный
   небольшой PR).
2. Сравнить с baseline в
   `docs/PROJECT_REAL_PR_QUALITY_ANALYSIS.md::§7`.
3. Если метрики не достигнуты — определить, какая фаза недоработана,
   и вернуться к ней. **Не переходить к "done" без цифр.**

---

## §10 Куда дальше

После закрытия всех 5 фаз остаются **production-wiring** задачи (это
уже не junior, senior-ревью):

- Подключить ace_indexer + ets_indexer к `cli.format_report` так,
  чтобы они **заменили** legacy `signal_inference` / `api_lineage` для
  графовых случаев (R7 из backlog: evidence-class-first ranker).
- Удалить дубль `_assign_bucket` / `_determine_coverage_equivalence`
  (R8) и переключить `coverage_relation.py` на `model.buckets`.
- Декомпозировать `cli.py` (R9) и мигрировать `test_cli_design_v1.py`
  (R10).
- Удалить копии `pattern_alias` из cli (R4).

Эти items уже есть в `docs/PROJECT_FOLLOWUP_BACKLOG.md`. После Phase
5 они получают актуальную базу evidence из shadow и могут быть
безопасно сделаны.

---

## §11 Если что-то идёт не так

- **Тест падает на чём-то, что не упомянуто в текущей фазе** → стоп,
  спроси.
- **Working tree содержит чужие изменения** (untracked файлы вне
  твоего PR) → не коммить их, не удаляй.
- **Тесты пред-существующих red (5 в `test_daily_prebuilt`,
  `test_download_hints`, `test_file_type_coverage`)** → не трогай,
  они отслеживаются отдельно (R11/triage в backlog).
- **Ты обнаружил, что фаза реально требует production-кода** →
  спроси, возможно нужен дополнительный shadow-mode wrapper.
- **Не уверен, как реализовать TODO в коде-скелете** → не выдумывай,
  спроси. Пишу скелет = ты дописываешь по аналогии с уже-готовыми
  кусками.

---

## §12 Финал

Когда все 6 строк в §1 имеют `[X]`:

1. Финальный коммит:
   ```bash
   git checkout main  # или подходящая базовая ветка
   git merge feature/hunk-resolution-and-explain
   ```
2. Обнови `docs/PROJECT_FOLLOWUP_BACKLOG.md` — пометь R6, R14-R20
   связанными с этим playbook как closed (см. §10 для тех, что
   остаются).
3. Перенеси этот playbook в `docs/archive/` через
   `git mv docs/PROJECT_PRECISE_TRACING_PLAYBOOK.md docs/archive/`,
   обновив `docs/archive/README.md`.
4. Пиши senior'у с цифрами из §9 — это и будет proof, что задача
   выполнена.

Удачи. Не торопись, проверяй после каждого шага, спрашивай при
сомнениях.
