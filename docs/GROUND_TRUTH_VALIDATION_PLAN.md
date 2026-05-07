# Ground Truth Validation — оракул «что API реально изменилось»

Дата: 2026-05-07

Связанные документы:
- `docs/COVERAGE_TEST_FRAMEWORK_PLAN.md` — coverage tests, использует этот оракул для T1 авто-разметки.
- `docs/ACCURACY_IMPROVEMENT_ROADMAP.md` — направления улучшений по итогам.
- `docs/API_XTS_QUALITY_RUN_300PR.md` — данные первого реального прогона.

## Зачем нужен оракул

Селектор сейчас отвечает на вопрос «какие API изменились в этом PR» через цепочку:
```
changed file → file role → method extraction → SDK lookup → canonical API
```

Но мы не можем проверить, **корректен ли ответ**. Нужна независимая truth-функция: «вот API, которые точно/вероятно изменились в этом diff».

Цель оракула:
1. **Auto-extract** expected APIs из git diff любого PR без ручной работы.
2. **Cross-check** с тем, что вернул селектор → точные precision/recall.
3. **Bootstrap** для golden fixtures (Doc 1, Phase CV.3).

Оракул не претендует на 100% accuracy — это инструмент для оценки селектора, а не замена ему.

## Архитектура

Three sources of truth, ranked by authority (используем 1 + 2; 3 — отдельный backlog B.1):

| Source | Confidence | Cost | Where applied |
|---|---|---|---|
| **AST-diff oracle** (this doc) | medium-high | автоматически | все 300 PR без manual labels |
| Manual labels (Doc 1 curated_30) | high | 5 часов human time | golden fixtures |
| Coverage replay (B.1) | very high | требует CI integration | post-implementation |

AST-diff oracle покрывает:
- C++ source (`.cpp`, `.h`, `.hpp`, `.c`) — основной язык ACE engine.
- TypeScript declarations (`.d.ts`) — SDK API surface.
- IDL (`.idl`) — generated bridge contracts.
- ETS (`.ets`, `.ts`) — ArkTS bridge / consumer files (limited).

## Принцип работы AST-diff oracle

Для каждого PR:
1. Получаем `base_sha` и `head_sha` из PR API.
2. Для каждого changed file:
   - `git show <base_sha>:<path>` — pre-content.
   - `git show <head_sha>:<path>` — post-content.
   - Парсим оба через tree-sitter (тот же parser, что в селекторе).
   - Извлекаем method/function-level символы.
   - Сравниваем pre/post: добавлено / удалено / signature_modified / body_modified.
3. Маппим `(class, method)` в `ApiEntityId` через SDK + ACE индексы.
4. Возвращаем `expected_apis: dict[confidence, list[api_id]]`.

### Confidence-уровни оракула

| Уровень | Critique |
|---|---|
| `signature_modified` | Сигнатура поменялась (return type / params / qualifiers). Высокая вероятность behavior change. → **high** |
| `added_method` | Новый метод. Если public surface — точно ground truth. → **high** |
| `removed_method` | Удалён метод. Если был public — точно ground truth. → **high** |
| `body_modified` | Тело метода изменилось (после strip whitespace/comments). → **medium** |
| `body_modified_trivial` | Только comment/whitespace. → **low** (фильтруется) |
| `unmapped` | Метод не сматчился с SDK API. → **unmapped** (не в expected, но в diagnostic) |

## Scope этого документа

1. **Module spec**: `validation/ast_oracle.py` — extract method changes.
2. **Mapping**: `validation/api_mapper.py` — (file, class, method) → ApiEntityId.
3. **Validation**: `validation/oracle_validator.py` — sanity check oracle output.
4. **PR cache extension**: добавление `base_sha`/`head_sha` в `PrApiCache`.
5. **CLI**: `python3 -m arkui_xts_selector.cli oracle-extract --pr <num>`.
6. **End-to-end usage** для bootstrap golden fixtures.
7. **Phase breakdown** с детализацией задач.

## 1. Module: `validation/ast_oracle.py`

### Контракт

```python
"""AST-based ground-truth oracle for changed APIs.

Extracts method-level changes from a git diff using tree-sitter.
Independent of selector logic — provides authoritative comparison source.
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ChangeKind = Literal[
    "added_method",
    "removed_method",
    "signature_modified",
    "body_modified",
    "body_modified_trivial",
]


@dataclass(frozen=True)
class MethodSnapshot:
    """A single method/function snapshot at one revision."""
    file_path: str
    parent_class: str | None  # None for free functions
    method_name: str
    qualified_name: str       # e.g. "ButtonModelStatic::SetRole"
    signature: str            # normalized: return_type + name + (params)
    body_hash: str            # SHA256 of body bytes (whitespace/comments stripped)
    line_start: int
    line_end: int


@dataclass(frozen=True)
class MethodChange:
    """Method-level change derived from pre/post snapshots."""
    file_path: str
    parent_class: str | None
    method_name: str
    qualified_name: str
    change_kind: ChangeKind
    pre: MethodSnapshot | None
    post: MethodSnapshot | None


def extract_method_changes(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    changed_files: list[str],
) -> list[MethodChange]:
    """Extract method-level diff for each changed file.

    Args:
        repo_root: git repo root (must be the OHOS workspace).
        base_sha: base commit SHA (PR's base).
        head_sha: head commit SHA (PR's tip).
        changed_files: relative paths from PR API response.

    Returns:
        Flat list of MethodChange entries.
    """
    changes: list[MethodChange] = []
    for cf in changed_files:
        if not _is_supported(cf):
            continue
        pre = _git_show(repo_root, base_sha, cf)
        post = _git_show(repo_root, head_sha, cf)
        # If file is added (pre missing) or deleted (post missing) — trivial cases:
        if pre is None and post is None:
            continue
        if cf.endswith((".cpp", ".h", ".hpp", ".c", ".cc")):
            changes.extend(_diff_cpp(cf, pre, post))
        elif cf.endswith((".d.ts",)):
            changes.extend(_diff_dts(cf, pre, post))
        elif cf.endswith((".idl",)):
            changes.extend(_diff_idl(cf, pre, post))
        elif cf.endswith((".ets", ".ts")):
            changes.extend(_diff_ets(cf, pre, post))
    return changes


def _is_supported(file_path: str) -> bool:
    return file_path.endswith((".cpp", ".h", ".hpp", ".c", ".cc",
                                ".d.ts", ".idl", ".ets", ".ts"))


def _git_show(repo_root: Path, sha: str, path: str) -> bytes | None:
    """Return file content at given SHA, or None if file didn't exist."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{sha}:{path}"],
            capture_output=True, check=True, timeout=30,
        )
        return out.stdout
    except subprocess.CalledProcessError:
        return None
    except subprocess.TimeoutExpired:
        return None


def _diff_cpp(
    file_path: str, pre: bytes | None, post: bytes | None,
) -> list[MethodChange]:
    """Parse pre/post C++ via tree-sitter; return method-level diffs."""
    pre_methods  = _parse_cpp_methods(pre, file_path)  if pre  else []
    post_methods = _parse_cpp_methods(post, file_path) if post else []

    pre_by_qname  = {m.qualified_name: m for m in pre_methods}
    post_by_qname = {m.qualified_name: m for m in post_methods}

    changes: list[MethodChange] = []

    # added
    for qname in post_by_qname.keys() - pre_by_qname.keys():
        m = post_by_qname[qname]
        changes.append(MethodChange(
            file_path=file_path, parent_class=m.parent_class, method_name=m.method_name,
            qualified_name=qname, change_kind="added_method",
            pre=None, post=m,
        ))

    # removed
    for qname in pre_by_qname.keys() - post_by_qname.keys():
        m = pre_by_qname[qname]
        changes.append(MethodChange(
            file_path=file_path, parent_class=m.parent_class, method_name=m.method_name,
            qualified_name=qname, change_kind="removed_method",
            pre=m, post=None,
        ))

    # modified
    for qname in pre_by_qname.keys() & post_by_qname.keys():
        pre_m, post_m = pre_by_qname[qname], post_by_qname[qname]
        if pre_m.signature != post_m.signature:
            kind = "signature_modified"
        elif pre_m.body_hash != post_m.body_hash:
            kind = "body_modified"
        else:
            continue  # nothing to report
        changes.append(MethodChange(
            file_path=file_path, parent_class=pre_m.parent_class,
            method_name=pre_m.method_name, qualified_name=qname,
            change_kind=kind, pre=pre_m, post=post_m,
        ))

    return changes


def _parse_cpp_methods(content: bytes, file_path: str) -> list[MethodSnapshot]:
    """Use tree-sitter C++ parser (existing in selector) to extract methods."""
    from arkui_xts_selector.tree_sitter_parsers import _get_ts_cpp_parser
    parser, lang = _get_ts_cpp_parser()
    tree = parser.parse(content)

    methods: list[MethodSnapshot] = []
    # Walk AST, collect function_definition nodes with their enclosing class.
    _walk_cpp(tree.root_node, content, "", methods, file_path)
    return methods


def _walk_cpp(node, content: bytes, current_class: str, out: list, file_path: str):
    """Recursive walker that tracks class scope."""
    # If we're at a class_specifier, push current_class
    new_class = current_class
    if node.type in ("class_specifier", "struct_specifier"):
        name_node = node.child_by_field_name("name")
        if name_node:
            new_class = name_node.text.decode("utf-8", errors="replace")

    if node.type == "function_definition":
        decl = node.child_by_field_name("declarator")
        if decl:
            method_name, qualified_name, parent_class = _extract_cpp_name(
                decl, new_class
            )
            if method_name:
                signature = _normalize_cpp_signature(node, content)
                body_node = node.child_by_field_name("body")
                body_hash = _hash_body(body_node, content) if body_node else ""
                out.append(MethodSnapshot(
                    file_path=file_path,
                    parent_class=parent_class,
                    method_name=method_name,
                    qualified_name=qualified_name,
                    signature=signature,
                    body_hash=body_hash,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))

    for child in node.children:
        _walk_cpp(child, content, new_class, out, file_path)


def _extract_cpp_name(decl_node, current_class: str) -> tuple[str, str, str | None]:
    """From a function declarator extract (method_name, qualified_name, parent_class).

    Handles:
      - free function:        void Foo() {}
      - class method:         void Bar::Foo() {}
      - inline method in class: class Bar { void Foo() {} };
    """
    text = decl_node.text.decode("utf-8", errors="replace")
    # Look for qualified_identifier child (e.g., Bar::Foo)
    for child in decl_node.children:
        if child.type == "qualified_identifier":
            # qualified_identifier: scope::name
            scope_node = child.child_by_field_name("scope")
            name_node = child.child_by_field_name("name")
            if scope_node and name_node:
                parent = scope_node.text.decode("utf-8", errors="replace")
                method = name_node.text.decode("utf-8", errors="replace")
                return method, f"{parent}::{method}", parent
        if child.type == "field_identifier":
            method = child.text.decode("utf-8", errors="replace")
            qname = f"{current_class}::{method}" if current_class else method
            return method, qname, current_class or None
        if child.type == "identifier":
            method = child.text.decode("utf-8", errors="replace")
            return method, method, None
    return "", "", None


def _normalize_cpp_signature(node, content: bytes) -> str:
    """Extract canonical signature: return_type + name + (params), no body."""
    # Take node text from start to body_node start.
    body_node = node.child_by_field_name("body")
    if body_node:
        sig_bytes = content[node.start_byte:body_node.start_byte]
    else:
        sig_bytes = content[node.start_byte:node.end_byte]
    # Normalize whitespace
    sig = sig_bytes.decode("utf-8", errors="replace")
    sig = " ".join(sig.split())
    return sig


def _hash_body(body_node, content: bytes) -> str:
    """Hash body bytes after stripping comments and whitespace."""
    if body_node is None:
        return ""
    body_bytes = content[body_node.start_byte:body_node.end_byte]
    # Strip line and block comments (regex-based, best-effort)
    import re
    text = body_bytes.decode("utf-8", errors="replace")
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = "".join(text.split())  # remove all whitespace
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

### Контракты `_diff_dts`, `_diff_idl`, `_diff_ets`

Следуют аналогичной структуре:
- `.d.ts`: использовать `ts-tree-sitter`. Извлекать `interface declarations`, `class declarations`, `method signatures`. Отслеживать added/removed/signature_modified.
- `.idl`: использовать `idl_parser` (уже существует, см. `src/arkui_xts_selector/indexing/idl_parser.py`). Сравнивать `IdlMethod` объекты pre/post.
- `.ets`: то же что `.d.ts` (TypeScript-совместимый AST).

Для каждого — отдельная реализация в том же модуле, ~80-120 строк каждая.

### Тесты

Файл: `tests/test_ast_oracle.py`. Минимум 25 кейсов:

```python
def test_added_cpp_method():
    """New SetRole method appears in post → added_method."""
    pre = b"class ButtonModel { void SetWidth(); };"
    post = b"class ButtonModel { void SetWidth(); void SetRole(int); };"
    changes = _diff_cpp("button.h", pre, post)
    assert len(changes) == 1
    assert changes[0].change_kind == "added_method"
    assert changes[0].method_name == "SetRole"

def test_removed_cpp_method():
    ...

def test_signature_modified_return_type():
    pre = b"class M { int Foo() { return 1; } };"
    post = b"class M { void Foo() { } };"
    changes = _diff_cpp("m.h", pre, post)
    assert any(c.change_kind == "signature_modified" for c in changes)

def test_signature_modified_params():
    pre = b"void Foo(int x);"
    post = b"void Foo(int x, int y);"
    changes = _diff_cpp("m.h", pre, post)
    assert any(c.change_kind == "signature_modified" for c in changes)

def test_body_modified():
    pre = b"void Foo() { return 1; }"
    post = b"void Foo() { return 2; }"
    changes = _diff_cpp("m.cpp", pre, post)
    assert any(c.change_kind == "body_modified" for c in changes)

def test_body_modified_trivial_comment_only():
    pre = b"void Foo() { return 1; }"
    post = b"void Foo() { /* added comment */ return 1; }"
    changes = _diff_cpp("m.cpp", pre, post)
    # Body hash should be equal (comments stripped)
    assert all(c.change_kind != "body_modified" for c in changes)

def test_qualified_name_extraction():
    src = b"void ButtonModelStatic::SetRole(int x) {}"
    methods = _parse_cpp_methods(src, "x.cpp")
    assert methods[0].qualified_name == "ButtonModelStatic::SetRole"
    assert methods[0].parent_class == "ButtonModelStatic"
    assert methods[0].method_name == "SetRole"

def test_inline_class_method():
    src = b"class B { void Foo() { } };"
    methods = _parse_cpp_methods(src, "x.h")
    assert methods[0].qualified_name == "B::Foo"

def test_free_function():
    src = b"void GlobalFunc() { }"
    methods = _parse_cpp_methods(src, "x.cpp")
    assert methods[0].qualified_name == "GlobalFunc"
    assert methods[0].parent_class is None

def test_unsupported_extension_skipped():
    changes = extract_method_changes(Path("/tmp"), "a", "b", ["foo.txt"])
    assert changes == []

# .d.ts
def test_added_dts_interface_member():
    pre = b"declare interface I { foo(): void; }"
    post = b"declare interface I { foo(): void; bar(): number; }"
    changes = _diff_dts("api.d.ts", pre, post)
    assert any(c.change_kind == "added_method" and c.method_name == "bar" for c in changes)

# .idl
def test_added_idl_method():
    pre = b'interface I { void foo(); }'
    post = b'interface I { void foo(); void bar(int); }'
    changes = _diff_idl("api.idl", pre, post)
    assert any(c.method_name == "bar" for c in changes)

# Integration with git
def test_extract_method_changes_with_git(tmp_repo):
    """tmp_repo fixture creates a real git repo with 2 commits."""
    changes = extract_method_changes(
        tmp_repo, "HEAD~1", "HEAD",
        ["button_modifier.cpp"],
    )
    assert len(changes) > 0

def test_git_show_missing_returns_none():
    """File didn't exist at base SHA → pre=None → all post methods are 'added'."""
    ...
```

## 2. Module: `validation/api_mapper.py`

### Контракт

```python
"""Map MethodChange to ApiEntityId using selector indices."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from arkui_xts_selector.indexing.sdk_indexer import SdkIndexResult
from arkui_xts_selector.indexing.ace_indexer import AceIndexResult
from arkui_xts_selector.indexing.file_role import classify
from arkui_xts_selector.indexing.source_to_api import _make_canonical_suffix


Confidence = Literal["high", "medium", "low", "unmapped"]


@dataclass(frozen=True)
class MappedApi:
    canonical_id: str | None  # api:v1:* or None
    public_name: str
    parent: str | None
    confidence: Confidence
    rationale: str
    method_change: "MethodChange"  # back-reference for diagnostics


def map_changes_to_apis(
    changes: list["MethodChange"],
    sdk_index: SdkIndexResult,
    ace_index: AceIndexResult,
) -> list[MappedApi]:
    """Map each MethodChange to ApiEntityId via SDK + role-based heuristics.

    Strategy:
      1. Classify file role (model_static, native_modifier, ...) via file_role.classify.
      2. Apply role-specific transform: SetXxx → xxx, GetXxx → xxx, JsXxx → xxx.
      3. Look up in SDK with parent context (find_attribute_member / find_common_member).
      4. If found → high (signature_modified), medium (body_modified).
      5. If not found → unmapped, kept for diagnostics.
    """
    out: list[MappedApi] = []
    for change in changes:
        role, family = classify(change.file_path)
        api_name = _derive_api_name(change.method_name, role)
        if api_name is None:
            out.append(MappedApi(
                canonical_id=None, public_name="", parent=None,
                confidence="unmapped",
                rationale=f"role={role} method={change.method_name}: no transform rule",
                method_change=change,
            ))
            continue

        # SDK lookup with parent context
        canonical, parent = _sdk_lookup(api_name, family, sdk_index)
        confidence = _confidence_for(change.change_kind, canonical is not None)
        out.append(MappedApi(
            canonical_id=canonical, public_name=api_name, parent=parent,
            confidence=confidence,
            rationale=f"role={role}, family={family}, change={change.change_kind}",
            method_change=change,
        ))
    return out


def _derive_api_name(method_name: str, role: str) -> str | None:
    """Apply role-specific transform from C++ method to API public name."""
    if role == "model_static":
        return _make_canonical_suffix(method_name, "Set")
    if role == "model_ng":
        return _make_canonical_suffix(method_name, "Set")
    if role == "native_modifier":
        return (_make_canonical_suffix(method_name, "Set") or
                _make_canonical_suffix(method_name, "Reset"))
    if role == "native_node_accessor":
        return (_make_canonical_suffix(method_name, "Get") or
                _make_canonical_suffix(method_name, "Set"))
    if role == "jsview_dynamic":
        if method_name == "Create":
            return "create"
        return _make_canonical_suffix(method_name, "Js")
    if role == "pattern":
        return method_name  # weak — pattern internal
    return None


def _sdk_lookup(
    api_name: str, family: str | None, sdk_index: SdkIndexResult,
) -> tuple[str | None, str | None]:
    """Reuse find_attribute_member / find_common_member when implemented (Phase 4).

    Until Phase 4 lands, falls back to bare-name find().
    """
    if hasattr(sdk_index, "find_attribute_member") and family:
        entry = sdk_index.find_attribute_member(family, api_name)
        if entry:
            return entry.api_id.canonical(), entry.api_id.member_of
    if hasattr(sdk_index, "find_common_member"):
        entry = sdk_index.find_common_member(api_name)
        if entry:
            return entry.api_id.canonical(), entry.api_id.member_of
    # Fallback: bare lookup
    entry = sdk_index.find(api_name)
    if entry:
        return entry.api_id.canonical(), entry.api_id.member_of
    return None, None


def _confidence_for(change_kind: str, sdk_confirmed: bool) -> Confidence:
    if not sdk_confirmed:
        return "unmapped"
    if change_kind in ("added_method", "removed_method", "signature_modified"):
        return "high"
    if change_kind == "body_modified":
        return "medium"
    return "low"
```

### Тесты

`tests/test_api_mapper.py`:

```python
def test_model_static_set_role_mapped():
    ...

def test_native_modifier_set_resolved_via_family():
    ...

def test_method_without_canonical_marked_unmapped():
    ...

def test_signature_modified_high_confidence():
    ...

def test_body_modified_medium_confidence():
    ...
```

## 3. Module: `validation/oracle_validator.py`

После реализации oracle нужно проверить, что он сам корректен. Сравнить с manual labels на 5 PR:

```python
"""Validate AST oracle output against manual ground truth.

Checks:
  - oracle.high ⊆ manual.high ∪ manual.medium  (no false positives in high)
  - oracle.high ⊇ manual.high (oracle catches all real changes)  *aspirational*
  - oracle.medium ∪ oracle.low contains all manual.medium
"""

@dataclass(frozen=True)
class OracleValidation:
    pr_number: int
    oracle_high: set
    oracle_medium: set
    manual_high: set
    manual_medium: set
    high_precision: float       # oracle.high ∩ manual.all / oracle.high
    high_recall: float          # oracle.high ∩ manual.high / manual.high
    false_positives: list[str]  # oracle.high - manual.all
    false_negatives: list[str]  # manual.high - oracle.high

def validate_oracle(
    oracle_results: dict,
    manual_golden: dict,
) -> list[OracleValidation]:
    ...
```

Ожидаемый bar для oracle:
- high_precision ≥ 0.8 (мало false positives в high — критично).
- high_recall ≥ 0.7 (oracle ловит большинство ручных high — желательно, но допустимо ниже).

Если oracle систематически дает false positives — refine `_diff_cpp` (например, фильтровать trivial body changes).

## 4. PR cache extension: base_sha / head_sha

### Что не хватает

`PrCacheEntry` сейчас не хранит `base_sha`/`head_sha`:
```python
# src/arkui_xts_selector/pr_cache.py
@dataclass(frozen=True)
class PrCacheEntry:
    pr_url: str
    host_kind: str
    owner: str
    repo: str
    pr_number: int
    fetched_at: str
    changed_files: tuple[str, ...]
    changed_ranges: dict
    raw_patch_hunks: dict
    api_status: str
```

### Что добавить

```python
@dataclass(frozen=True)
class PrCacheEntry:
    ...
    base_sha: str | None = None
    head_sha: str | None = None
    base_ref: str | None = None    # e.g. "master"
    head_ref: str | None = None    # e.g. "feature/xxx"
```

### Где заполнять

Файл: `src/arkui_xts_selector/git_host.py`. Функция `fetch_pr_metadata_via_api` уже возвращает PR JSON от GitCode API, который содержит:
```json
{
  "head": {"sha": "...", "ref": "feature/xxx"},
  "base": {"sha": "...", "ref": "master"},
  ...
}
```

Расширить `PrApiCache.put` чтобы извлекать эти поля:
```python
def put(self, ..., metadata: dict):
    base_sha = (metadata.get("base", {}) or {}).get("sha")
    head_sha = (metadata.get("head", {}) or {}).get("sha")
    base_ref = (metadata.get("base", {}) or {}).get("ref")
    head_ref = (metadata.get("head", {}) or {}).get("ref")
    entry = PrCacheEntry(..., base_sha=base_sha, head_sha=head_sha,
                          base_ref=base_ref, head_ref=head_ref)
```

### Обратная совместимость

Существующий cache (300 PR) не имеет этих полей. Решение:
1. Schema bump: `cache_schema_version = 2`.
2. Старые entries: load с `base_sha=None`. AST oracle skip-ает PR без SHA с явным reason.
3. Re-fetch метадаты: `python3 scripts/refresh_pr_metadata.py --pr-list-file local/pr_lists/ace_engine_300.txt` — обновляет только metadata fields, не changed_files.

`scripts/refresh_pr_metadata.py` (~50 строк) — отдельный скрипт.

### Тесты

```python
def test_pr_cache_v2_includes_base_head_sha():
    ...

def test_pr_cache_v1_loads_with_none_sha_and_warns():
    ...
```

## 5. CLI: `oracle-extract`

```python
oe = subparsers.add_parser("oracle-extract",
    help="Extract expected APIs from a PR via AST diff oracle.")
oe.add_argument("--pr-number", type=int, required=True)
oe.add_argument("--owner", default="openharmony")
oe.add_argument("--repo", default="arkui_ace_engine")
oe.add_argument("--repo-root", type=Path, required=True)
oe.add_argument("--pr-api-cache-dir", type=Path, default=Path("local/pr_api_cache"))
oe.add_argument("--sdk-api-root", type=Path, required=True)
oe.add_argument("--output", type=Path, required=True,
    help="JSON output: {high: [...], medium: [...], unmapped: [...]}")
oe.add_argument("--debug", action="store_true",
    help="Include MethodChange details for diagnostics")
```

Использование:
```bash
PYTHONPATH=src python3 -m arkui_xts_selector.cli oracle-extract \
    --pr-number 84186 \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --output /tmp/oracle_84186.json \
    --debug
```

Output:
```json
{
  "pr_number": 84186,
  "high": [
    {"canonical_id": "api:v1:#DataPanelAttribute%23values", "rationale": "data_panel_modifier.cpp signature_modified for SetValues"}
  ],
  "medium": [...],
  "unmapped": [...],
  "method_changes_total": 47,
  "files_processed": 12,
  "files_unsupported": 1
}
```

## 6. End-to-end usage

### Bootstrap golden fixture (Phase CV.3 в Doc 1)

```bash
PR_NUMBERS=$(jq -r '.[]' tests/fixtures/golden/curated_30_pr_numbers.json)
for pr in $PR_NUMBERS; do
    PYTHONPATH=src python3 -m arkui_xts_selector.cli oracle-extract \
        --pr-number $pr \
        --repo-root /data/home/dmazur/proj/ohos_master \
        --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
        --output local/oracle_results/pr_${pr}.json
done

# Aggregate into draft golden fixture
python3 scripts/aggregate_oracle_to_draft.py \
    --oracle-dir local/oracle_results/ \
    --pr-numbers tests/fixtures/golden/curated_30_pr_numbers.json \
    --batch-results local/quality_runs/20260506_2257_300pr/batch_results.json \
    --out tests/fixtures/golden/curated_30_draft.json
```

### Auto-eval всех 300 PR (без manual labels)

```bash
PYTHONPATH=src python3 -m arkui_xts_selector.cli coverage-eval \
    --batch-results local/quality_runs/20260506_2257_300pr/batch_results.json \
    --use-ast-oracle \
    --repo-root /data/home/dmazur/proj/ohos_master \
    --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api \
    --output local/quality_runs/20260506_2257_300pr/coverage_eval_oracle.json \
    --report-md local/quality_runs/20260506_2257_300pr/coverage_eval_oracle.md
```

Это даст первые **scaled** numbers по 300 PR без 5 часов ручной работы.

## 7. Phase breakdown

### Phase O.1: PR cache base_sha/head_sha (1 день)
- File: `src/arkui_xts_selector/pr_cache.py` (+30 строк, +schema_version)
- File: `src/arkui_xts_selector/git_host.py` (+20 строк)
- File: `scripts/refresh_pr_metadata.py` (~50 строк)
- Tests: `tests/test_pr_cache_v2.py` (4-5 кейсов)
- Acceptance: existing 300 PR cache имеет base_sha/head_sha после refresh.

### Phase O.2: ast_oracle.py — C++ diff (3 дня)
- File: `src/arkui_xts_selector/validation/__init__.py`
- File: `src/arkui_xts_selector/validation/ast_oracle.py` (~400 строк)
- Tests: `tests/test_ast_oracle_cpp.py` (≥ 15 кейсов)
- Acceptance: `_diff_cpp` корректно классифицирует added/removed/signature/body на 15 unit-кейсах.

### Phase O.3: ast_oracle.py — d.ts / idl / ets (2 дня)
- Расширение `ast_oracle.py` (+200 строк).
- Tests: `tests/test_ast_oracle_dts.py`, `test_ast_oracle_idl.py` (≥ 10 кейсов каждый).
- Acceptance: 4 формата работают на synthetic fixtures.

### Phase O.4: api_mapper.py (1 день)
- File: `src/arkui_xts_selector/validation/api_mapper.py` (~150 строк)
- Tests: `tests/test_api_mapper.py` (≥ 8 кейсов)
- Acceptance: маппинг работает для всех 6 file_role типов.

### Phase O.5: CLI oracle-extract (0.5 дня)
- File: `src/arkui_xts_selector/cli.py` (+30 строк)
- Tests: `tests/test_cli_oracle_extract.py` (smoke)
- Acceptance: CLI выдаёт JSON output на 5 ручных PR.

### Phase O.6: validator + tuning (1 день)
- File: `src/arkui_xts_selector/validation/oracle_validator.py` (~120 строк)
- Применить к 5 manually-labeled PR.
- Acceptance: high_precision ≥ 0.7 на validation set.

### Phase O.7: integration с coverage-eval (0.5 дня)
- File: `src/arkui_xts_selector/coverage_eval.py` (+30 строк, branch для use_ast_oracle).
- Tests: `tests/test_coverage_eval_with_oracle.py`.
- Acceptance: `--use-ast-oracle` работает без `--golden`.

**Суммарный бюджет:** ~9 дней для production-ready oracle.

## 8. Известные ограничения

1. **C++ tree-sitter не парсит макросы.** Если метод определён через `DEFINE_ATTRIBUTE_*`, oracle его пропустит. Решение — расширить `cpp_macro_patterns.json` (A.4 уже частично).

2. **Inheritance не учитывается.** Если `BaseAttribute.x` изменился, oracle не пропагирует на наследников. Phase A.2 (inheritance graph) решит для маппинга.

3. **`.ets` parsing неполон.** Tree-sitter TypeScript есть, но ArkTS-specific конструкции (`@State`, `@Prop`) могут парситься некорректно. Допустимо — для bridge files diff обычно не трогает декораторы.

4. **No semantic equivalence detection.** Если переименовали local var в body — body_hash изменится, classification = `body_modified`. Это OK для нашей задачи — мы хотим знать, что метод трогали.

5. **Generated files.** Файлы под `arkoala_generator/out/`, `koala_projects/.../generated/` могут быть помечены как `body_modified` массово. Решение: фильтровать `file_category = generated` (Phase 2 backlog).

6. **Performance.** На 300 PR × ~10 файлов × 2 git show + tree-sitter parse ≈ 6000 ops. Каждый ~50 ms → ~5 минут. Допустимо. Параллелизация per-PR через ProcessPool — опционально.

## 9. Метрики качества oracle

После Phase O.6 ожидаемые значения на 5 validation PR:

| Metric | Минимум | Желаемо |
|---|---:|---:|
| high_precision (oracle.high ⊆ manual.all) | 0.7 | 0.85 |
| high_recall (oracle.high ⊇ manual.high) | 0.6 | 0.8 |
| unmapped_rate (oracle items без canonical) | < 0.6 | < 0.4 |

`unmapped_rate > 0.6` означает что mapping слабый — большинство changes не сматчилось с SDK. Это ожидаемо до Phase 4 (find_member with parent context). После Phase 4 — должно упасть до < 0.4.

## 10. Что даёт oracle

После реализации:

1. **Auto-evaluation** на любом PR без ручной разметки.
2. **Bootstrap** golden fixtures (Doc 1 Phase CV.3).
3. **Continuous regression check** при каждом изменении селектора.
4. **Ground truth для Phase 4 / Phase 5 / Phase 6** — численно показать, насколько они улучшают canonical recall.
5. **Trace-by-trace diagnostics** для каждой PR, какие метод-change были видны селектору.

Без oracle мы фактически работаем вслепую: видим только output селектора, не видим ground truth.
