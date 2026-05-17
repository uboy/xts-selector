"""
Project index functions for ArkUI XTS test selector.

This module contains functions for discovering, indexing, and caching
test projects in the XTS workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .api_surface import classify_xts_project_surface
from .file_indexing import (
    extract_member_hint_keys,
    normalize_member_hint,
    parse_test_file,
)
from .file_io import (
    load_json_file,
    read_text,
)
from .git_host import resolve_path
from .models import (
    SdkIndex,
    ContentModifierIndex,
    MappingConfig,
    TestFileIndex,
    TestProjectIndex,
    XtsWorkspaceSnapshot,
)
from .tokens import (
    compact_token,
    snake_to_pascal,
    tokenize_path_parts,
    path_component_tokens,
)

if TYPE_CHECKING:
    pass

# NOTE: REPO_ROOT is expected to be set by the importing module
# This module provides get_repo_root() for lazy initialization
_REPO_ROOT: Path | None = None


def _get_repo_root() -> Path:
    """Get the repository root, lazily initialized."""
    global _REPO_ROOT
    if _REPO_ROOT is None:
        from .workspace import discover_repo_root

        _REPO_ROOT = discover_repo_root()
    return _REPO_ROOT


def repo_rel(path: Path) -> str:
    """Convert a path to a relative path from the repo root."""
    try:
        return str(path.resolve().relative_to(_get_repo_root()))
    except ValueError:
        return str(path)


# Module-level generic path tokens - initialized lazily
GENERIC_PATH_TOKENS: set[str] = set()


def initialize_generic_path_tokens(tokens: set[str]) -> None:
    """Initialize the generic path tokens set."""
    global GENERIC_PATH_TOKENS
    GENERIC_PATH_TOKENS = tokens


def get_generic_path_tokens() -> set[str]:
    """Get the generic path tokens set."""
    return GENERIC_PATH_TOKENS


# ============================================================================
# Cache and Path Functions
# ============================================================================


def default_cache_path(xts_root: Path) -> Path:
    """Generate workspace-specific cache path to avoid race conditions."""
    workspace_hash = hashlib.sha256(str(xts_root.resolve()).encode()).hexdigest()[:12]
    return Path(f"/tmp/arkui_xts_selector_cache_{workspace_hash}.json")


def default_cache_meta_path(cache_file: Path) -> Path:
    """Return the cache metadata path for a given cache file."""
    return cache_file.with_name(cache_file.name + ".meta.json")


# ============================================================================
# Test JSON Parsing Functions
# ============================================================================


def parse_bundle_name(test_json: Path) -> str | None:
    """Parse bundle name from a Test.json file."""
    text = read_text(test_json)
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data.get("driver", {}).get("bundle-name")


def parse_test_file_names_from_test_json(test_json: Path) -> list[str]:
    """Extract test file names from a Test.json file."""
    text = read_text(test_json)
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    result: list[str] = []
    for kit in data.get("kits", []):
        if not isinstance(kit, dict):
            continue
        names = kit.get("test-file-name", [])
        if isinstance(names, list):
            result.extend([item for item in names if isinstance(item, str)])
    return result


def _classify_project_variant_from_names(
    relative_root: str, test_file_names: list[str]
) -> str:
    """Classify project variant based on directory and test file names."""
    markers: set[str] = set()
    root_lower = relative_root.lower()
    if "static" in root_lower:
        markers.add("static")
    if "dynamic" in root_lower:
        markers.add("dynamic")
    for item in test_file_names:
        lower = item.lower()
        if "statictest" in lower or "hap_static" in lower or "_static" in lower:
            markers.add("static")
        if "dynamictest" in lower or "hap_dynamic" in lower or "_dynamic" in lower:
            markers.add("dynamic")
    if markers == {"static", "dynamic"}:
        return "both"
    if "static" in markers:
        return "static"
    if "dynamic" in markers:
        return "dynamic"
    return "unknown"


def classify_project_variant(
    relative_root: str,
    test_file_names: list[str],
    files: list[TestFileIndex] | None = None,
) -> str:
    """Classify project variant using semantic analysis or name-based fallback."""
    if files is not None:
        semantic = classify_xts_project_surface(
            file_index.surface for file_index in files
        )
        if semantic.variant != "unknown":
            return semantic.variant
    return _classify_project_variant_from_names(relative_root, test_file_names)


def parse_test_json(path_value: str, repo_root: Path | None = None) -> dict:
    """Parse a Test.json file and return its contents as a dict.

    NOTE: When repo_root is None, this function tries to import REPO_ROOT from
    the calling module. If that fails, it falls back to lazy initialization.
    """
    if repo_root is None:
        # Try to get REPO_ROOT from calling module's globals
        import sys

        frame = sys._getframe(1)
        try:
            repo_root = frame.f_globals.get("REPO_ROOT")
            if repo_root is None:
                repo_root = _get_repo_root()
        finally:
            del frame
    return load_json_file(resolve_path(path_value, repo_root, repo_root))


def parse_test_file_names(
    test_json_path: str, repo_root: Path | None = None
) -> list[str]:
    """Parse test file names from a Test.json file path."""
    data = parse_test_json(test_json_path, repo_root=repo_root)
    result: list[str] = []
    for kit in data.get("kits", []):
        if not isinstance(kit, dict):
            continue
        names = kit.get("test-file-name", [])
        if isinstance(names, list):
            for item in names:
                if isinstance(item, str):
                    result.append(item)
    return result


def infer_xdevice_module_name(
    test_json_path: str, repo_root: Path | None = None
) -> str | None:
    """Infer the xdevice module name from a Test.json file."""
    for name in parse_test_file_names(test_json_path, repo_root=repo_root):
        if name.endswith(".hap"):
            stem = Path(name).stem
            if stem:
                return stem
    return None


def guess_build_target(project_root: str) -> str:
    """Guess the build target from the project root directory name."""
    return Path(project_root).name


# ============================================================================
# Source File Discovery Functions
# ============================================================================


def xts_source_files(xts_root: Path) -> list[Path]:
    """Discover all source files in the XTS workspace."""
    skip_dirs = {".git", ".ohpm", "node_modules", "oh_modules", "out"}
    paths: set[Path] = set()
    if not xts_root.exists():
        return []
    for dirpath, dirnames, filenames in os.walk(
        xts_root, topdown=True, onerror=lambda _exc: None
    ):
        dirnames[:] = [name for name in dirnames if name not in skip_dirs]
        base = Path(dirpath)
        for filename in filenames:
            if filename == "Test.json" or filename.endswith((".ets", ".ts", ".js")):
                paths.add((base / filename).resolve())
    return sorted(paths)


def build_manifest_hash(paths: list[Path]) -> str:
    """Build a hash from manifest file metadata."""
    digest = hashlib.sha256()
    for path in paths:
        stat = path.stat()
        digest.update(repo_rel(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


# ============================================================================
# Project Discovery and Indexing Functions
# ============================================================================


def discover_projects(xts_root: Path) -> list[TestProjectIndex]:
    """Discover all test projects in the XTS workspace."""
    projects: list[TestProjectIndex] = []
    skip_dirs = {".git", ".ohpm", "node_modules", "oh_modules", "out"}
    for test_json in sorted(xts_root.rglob("Test.json")):
        if any(part in skip_dirs for part in test_json.parts):
            continue
        root = test_json.parent
        files: list[TestFileIndex] = []
        for dirpath, dirnames, filenames in os.walk(
            root, topdown=True, onerror=lambda _exc: None
        ):
            dirnames[:] = [name for name in dirnames if name not in skip_dirs]
            base = Path(dirpath)
            for filename in filenames:
                if not filename.endswith((".ets", ".ts", ".js")):
                    continue
                source = (base / filename).resolve()
                files.append(parse_test_file(source))
        relative_root = repo_rel(root)
        test_json_rel = repo_rel(test_json)
        test_file_names = parse_test_file_names_from_test_json(test_json)
        surface_profile = classify_xts_project_surface(
            file_index.surface for file_index in files
        )
        projects.append(
            TestProjectIndex(
                relative_root=relative_root,
                test_json=test_json_rel,
                bundle_name=parse_bundle_name(test_json),
                files=files,
                path_key=str(root.relative_to(xts_root)).replace(os.sep, "/").lower(),
                variant=classify_project_variant(
                    relative_root, test_file_names, files=files
                ),
                surface=surface_profile.surface,
                supported_surfaces=set(surface_profile.supported_surfaces),
            )
        )
    return projects


def _build_xts_workspace_signature(xts_root: Path) -> str:
    """Build a signature for the XTS workspace."""
    return _capture_xts_workspace_snapshot(xts_root).signature


def _capture_xts_workspace_snapshot(xts_root: Path) -> XtsWorkspaceSnapshot:
    """Capture a snapshot of the XTS workspace state."""
    skip_dirs = {".git", ".ohpm", "node_modules", "oh_modules", "out"}
    h = hashlib.sha256()
    file_count = 0
    newest_mtime_ns = 0
    for dirpath, dirnames, filenames in os.walk(
        xts_root, topdown=True, onerror=lambda _exc: None
    ):
        dirnames[:] = sorted(name for name in dirnames if name not in skip_dirs)
        try:
            newest_mtime_ns = max(
                newest_mtime_ns, int(Path(dirpath).stat().st_mtime_ns)
            )
        except OSError:
            pass
        base = Path(dirpath)
        for filename in sorted(filenames):
            if filename != "Test.json" and not filename.endswith(
                (".ets", ".ts", ".js")
            ):
                continue
            path = base / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = str(path.relative_to(xts_root)).replace(os.sep, "/")
            h.update(f"{rel}:{stat.st_mtime_ns}:{stat.st_size}\n".encode())
            file_count += 1
            newest_mtime_ns = max(newest_mtime_ns, int(stat.st_mtime_ns))
    return XtsWorkspaceSnapshot(
        signature=f"{file_count}:{h.hexdigest()}",
        newest_mtime_ns=newest_mtime_ns,
    )


def _build_project_hash(project_root: Path, skip_dirs: set[str]) -> str:
    """Compute hash for a single project based on its relevant source files."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(
        project_root, topdown=True, onerror=lambda _exc: None
    ):
        dirnames[:] = sorted(name for name in dirnames if name not in skip_dirs)
        base = Path(dirpath)
        for filename in sorted(filenames):
            if filename != "Test.json" and not filename.endswith(
                (".ets", ".ts", ".js")
            ):
                continue
            path = base / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = str(path.relative_to(project_root)).replace(os.sep, "/")
            h.update(f"{rel}:{stat.st_mtime_ns}:{stat.st_size}\n".encode())
    return h.hexdigest()


def _build_single_project(
    test_json: Path,
    root: Path,
    xts_root: Path,
) -> TestProjectIndex:
    """Build index for a single project directory."""
    skip_dirs = {".git", ".ohpm", "node_modules", "oh_modules", "out"}
    files: list[TestFileIndex] = []
    for dirpath, dirnames, filenames in os.walk(
        root, topdown=True, onerror=lambda _exc: None
    ):
        dirnames[:] = [name for name in dirnames if name not in skip_dirs]
        base = Path(dirpath)
        for filename in filenames:
            if not filename.endswith((".ets", ".ts", ".js")):
                continue
            source = (base / filename).resolve()
            files.append(parse_test_file(source))
    relative_root = repo_rel(root)
    test_json_rel = repo_rel(test_json)
    test_file_names = parse_test_file_names_from_test_json(test_json)
    surface_profile = classify_xts_project_surface(
        file_index.surface for file_index in files
    )
    return TestProjectIndex(
        relative_root=relative_root,
        test_json=test_json_rel,
        bundle_name=parse_bundle_name(test_json),
        files=files,
        path_key=str(root.relative_to(xts_root)).replace(os.sep, "/").lower(),
        variant=classify_project_variant(relative_root, test_file_names, files=files),
        surface=surface_profile.surface,
        supported_surfaces=set(surface_profile.supported_surfaces),
    )


def _projects_from_cache_payload(
    cache_data: dict[str, object], *, lazy_files: bool
) -> list[TestProjectIndex]:
    """Deserialize projects from cache data."""
    return [
        TestProjectIndex.from_dict(item["data"], lazy_files=lazy_files)
        for _key, item in sorted((cache_data.get("projects", {}) or {}).items())
        if isinstance(item, dict) and isinstance(item.get("data"), dict)
    ]


def load_or_build_projects(
    xts_root: Path, cache_file: Path | None
) -> tuple[list[TestProjectIndex], bool]:
    """Load projects from cache or build them from scratch."""
    CACHE_VERSION = 5

    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_meta_file = default_cache_meta_path(cache_file) if cache_file else None

    # Fast path: validate the workspace against a tiny sidecar metadata file.
    if (
        cache_file
        and cache_file.exists()
        and cache_meta_file
        and cache_meta_file.exists()
    ):
        try:
            meta_payload = json.loads(read_text(cache_meta_file))
            if meta_payload.get("version") == CACHE_VERSION:
                workspace_snapshot = _capture_xts_workspace_snapshot(xts_root)
                if (
                    meta_payload.get("workspace_signature")
                    == workspace_snapshot.signature
                ):
                    cache_data = json.loads(read_text(cache_file))
                    if cache_data.get("version") == CACHE_VERSION:
                        projects = _projects_from_cache_payload(
                            cache_data, lazy_files=True
                        )
                        for project in projects:
                            if not project.search_summary_ready:
                                ensure_project_search_summary(project)
                        return projects, len(projects) > 0
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            pass

    # Compatibility fast path: older caches may not have a sidecar yet.
    # If the workspace-specific cache file is newer than every relevant source
    # file and directory in the workspace, the cache cannot be stale for this
    # workspace snapshot, so we can safely restore it and backfill the sidecar.
    if (
        cache_file
        and cache_file.exists()
        and cache_meta_file
        and not cache_meta_file.exists()
    ):
        try:
            workspace_snapshot = _capture_xts_workspace_snapshot(xts_root)
            cache_stat = cache_file.stat()
            cache_data = json.loads(read_text(cache_file))
            if (
                cache_data.get("version") == CACHE_VERSION
                and int(cache_stat.st_mtime_ns) >= workspace_snapshot.newest_mtime_ns
            ):
                projects = _projects_from_cache_payload(cache_data, lazy_files=True)
                for project in projects:
                    if not project.search_summary_ready:
                        ensure_project_search_summary(project)
                cache_meta_file.write_text(
                    json.dumps(
                        {
                            "version": CACHE_VERSION,
                            "workspace_signature": workspace_snapshot.signature,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return projects, len(projects) > 0
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            pass

    # Discover all project directories
    skip_dirs = {".git", ".ohpm", "node_modules", "oh_modules", "out"}
    project_dirs: list[tuple[Path, Path]] = []  # (test_json, root)
    for test_json in sorted(xts_root.rglob("Test.json")):
        if any(part in skip_dirs for part in test_json.parts):
            continue
        project_dirs.append((test_json, test_json.parent))

    # Load old cache
    old_cache: dict[str, dict] = {}
    if cache_file and cache_file.exists():
        try:
            cache_data = json.loads(read_text(cache_file))
            if cache_data.get("version") == CACHE_VERSION:
                old_cache = cache_data.get("projects", {})
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Build incrementally
    new_cache: dict[str, dict] = {}
    projects: list[TestProjectIndex] = []
    cache_hits = 0
    cache_changed = False

    for test_json, root in project_dirs:
        proj_hash = _build_project_hash(root, skip_dirs)
        rel_key = str(root.relative_to(xts_root)).replace(os.sep, "/")

        if rel_key in old_cache and old_cache[rel_key].get("hash") == proj_hash:
            # Cache hit
            try:
                project = TestProjectIndex.from_dict(old_cache[rel_key]["data"])
                if not project.search_summary_ready:
                    ensure_project_search_summary(project)
                projects.append(project)
                new_cache[rel_key] = old_cache[rel_key]
                cache_hits += 1
                continue
            except (KeyError, TypeError):
                pass

        # Cache miss — rebuild
        project = _build_single_project(test_json, root, xts_root)
        ensure_project_search_summary(project)
        projects.append(project)
        new_cache[rel_key] = {"hash": proj_hash, "data": project.to_dict()}
        cache_changed = True

    # Save updated cache
    if len(old_cache) != len(new_cache):
        cache_changed = True
    if cache_file and cache_changed:
        cache_payload = {
            "version": CACHE_VERSION,
            "projects": new_cache,
        }
        cache_file.write_text(
            json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8"
        )
    if (
        cache_file
        and cache_meta_file
        and (cache_changed or not cache_meta_file.exists())
    ):
        workspace_signature = _build_xts_workspace_signature(xts_root)
        cache_meta_file.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "workspace_signature": workspace_signature,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    cache_used = cache_hits == len(project_dirs) and len(project_dirs) > 0
    return projects, cache_used


# ============================================================================
# SDK Index Functions
# ============================================================================


def load_sdk_index(sdk_api_root: Path) -> SdkIndex:
    """Load SDK API index from the SDK API root directory."""
    index = SdkIndex()
    sdk_component_root = sdk_api_root / "arkui/component"
    sdk_arkui_root = sdk_api_root / "arkui"

    for path in sorted(sdk_component_root.glob("*.static.d.ets")):
        base = path.name[: -len(".static.d.ets")]
        symbol = snake_to_pascal(base)
        if base not in {"common", "builder", "enums", "units", "resources"}:
            index.component_names.add(symbol)
            index.component_file_bases[compact_token(base)] = symbol

    for path in sorted(sdk_arkui_root.glob("*Modifier.d.ts")) + sorted(
        sdk_arkui_root.glob("*Modifier.static.d.ets")
    ):
        base = path.name
        if base.endswith(".d.ts"):
            symbol = base[: -len(".d.ts")]
        else:
            symbol = base[: -len(".static.d.ets")]
        index.modifier_names.add(symbol)
        index.modifier_file_bases[compact_token(symbol.replace("Modifier", ""))] = (
            symbol
        )

    for path in sorted(sdk_api_root.glob("@ohos.*")):
        name = path.name
        for suffix in (".d.ts", ".d.ets", ".static.d.ets"):
            if name.endswith(suffix):
                index.top_level_modules.add(name[: -len(suffix)])
                break

    return index


def normalize_ohos_module(module: str, sdk_modules: set[str]) -> str | None:
    """Normalize an OHOS module name to match SDK modules."""
    if module in sdk_modules:
        return module
    prefixes = [
        candidate for candidate in sdk_modules if module.startswith(candidate + ".")
    ]
    if prefixes:
        return max(prefixes, key=len)
    return None


# ============================================================================
# Token and Symbol Functions
# ============================================================================


def family_tokens_from_path(rel: str, sdk_index: SdkIndex) -> set[str]:
    """Extract family tokens from a file path."""
    rel_lower = rel.lower()
    parts = tokenize_path_parts(rel_lower)
    generic_tokens = get_generic_path_tokens()
    families = {
        compact_token(part)
        for part in parts
        if len(part) >= 3 and compact_token(part) not in generic_tokens
    }
    families.update(
        token
        for token in path_component_tokens(rel_lower)
        if token and token not in generic_tokens
    )

    pattern_match = re.search(r"components_ng/pattern/([^/]+)/", rel)
    if pattern_match:
        families.add(compact_token(pattern_match.group(1)))

    for part in parts:
        compact = compact_token(part)
        if compact in sdk_index.component_file_bases:
            families.add(compact)
        if compact in sdk_index.modifier_file_bases:
            families.add(compact)
    return {item for item in families if item}


def dynamic_module_symbols(
    module_name: str,
    sdk_index: SdkIndex,
    content_index: ContentModifierIndex,
    mapping_config: MappingConfig,
) -> set[str]:
    """Extract dynamic module symbols for a given module name."""
    family = compact_token(module_name)
    symbols: set[str] = {module_name}
    if family in sdk_index.component_file_bases:
        symbols.add(sdk_index.component_file_bases[family])
    if family in sdk_index.modifier_file_bases:
        symbols.add(sdk_index.modifier_file_bases[family])
    symbols.add(f"{module_name}Modifier")
    symbols.update(mapping_config.pattern_alias.get(module_name.lower(), []))
    symbols.update(content_index.family_to_symbols.get(family, set()))
    return {item for item in symbols if item}


# ============================================================================
# Project Search and Matching Functions
# ============================================================================


def ensure_project_search_summary(project: TestProjectIndex) -> TestProjectIndex:
    """Ensure project has search summary populated."""
    if project.search_summary_ready:
        return project

    project_path_compact = compact_token(project.path_key)
    path_tokens = {
        compact_token(part)
        for part in tokenize_path_parts(project.path_key.lower())
        if compact_token(part)
    }
    path_tokens.update(path_component_tokens(project.path_key.lower()))

    file_path_compacts: list[str] = []
    for file_index in project.files:
        file_path_compact = compact_token(file_index.relative_path)
        if file_path_compact:
            file_path_compacts.append(file_path_compact)
        lower_relative_path = file_index.relative_path.lower()
        path_tokens.update(
            compact_token(part)
            for part in tokenize_path_parts(lower_relative_path)
            if compact_token(part)
        )
        path_tokens.update(path_component_tokens(lower_relative_path))
        project.search_imports.update(file_index.imports)
        project.search_imported_symbols.update(file_index.imported_symbols)
        project.search_identifier_calls.update(file_index.identifier_calls)
        project.search_imported_symbol_tokens.update(
            compact_token(symbol)
            for symbol in file_index.imported_symbols
            if compact_token(symbol)
        )
        project.search_identifier_call_tokens.update(
            compact_token(identifier)
            for identifier in file_index.identifier_calls
            if compact_token(identifier)
        )
        project.search_member_call_tokens.update(
            compact_token(member)
            for member in file_index.member_calls
            if compact_token(member)
        )
        for entry in file_index.type_member_calls:
            owner, _separator, _member = entry.partition(".")
            owner_token = compact_token(owner)
            if owner_token:
                project.search_type_owner_tokens.add(owner_token)
            normalized = normalize_member_hint(entry)
            if normalized:
                project.search_exact_member_keys.add(normalized)
        for entry in file_index.typed_field_accesses:
            owner, _separator, _field = entry.partition(".")
            owner_token = compact_token(owner)
            if owner_token:
                project.search_typed_field_types.add(owner_token)
            normalized = normalize_member_hint(entry)
            if normalized:
                project.search_exact_member_keys.add(normalized)
        project.search_typed_modifier_bases.update(file_index.typed_modifier_bases)
        project.search_words.update(
            compact_token(word) for word in file_index.words if compact_token(word)
        )
        project.search_evidence_kinds.update(file_index.evidence_kinds)

    project.search_path_tokens = {token for token in path_tokens if token}
    project.search_project_path_compact = project_path_compact
    project.search_file_path_compacts = file_path_compacts
    project.search_summary_ready = True
    return project


def ensure_project_files_loaded(project: TestProjectIndex) -> TestProjectIndex:
    """Ensure project files are loaded from serialization."""
    if project.files or not project._serialized_files:
        return project
    project.files = [
        TestFileIndex.from_dict(item)
        for item in project._serialized_files
        if isinstance(item, dict)
    ]
    return project


def project_matches_exact_api_prefilter(
    project: TestProjectIndex, signals: dict[str, set[str]]
) -> bool:
    """Check if project matches exact API prefilter entities."""
    ensure_project_search_summary(project)
    exact_api_entities = {
        str(item)
        for item in signals.get("exact_api_prefilter_entities", set())
        if "." in str(item)
    }
    exact_member_hints = extract_member_hint_keys(signals.get("member_hints", set()))
    if not exact_api_entities and not exact_member_hints:
        return False

    exact_member_keys = set(project.search_exact_member_keys)
    for member_hint in sorted(exact_member_hints):
        if member_hint in exact_member_keys:
            return True
    for api_entity in sorted(exact_api_entities):
        normalized = normalize_member_hint(api_entity)
        if normalized and normalized in exact_member_keys:
            return True

    type_tokens = (
        set(project.search_type_owner_tokens)
        | set(project.search_imported_symbol_tokens)
        | set(project.search_identifier_call_tokens)
    )
    member_tokens = set(project.search_member_call_tokens)
    for api_entity in sorted(exact_api_entities):
        owner, separator, method = api_entity.partition(".")
        if not separator or not owner or not method:
            continue
        owner_token = compact_token(owner)
        method_token = compact_token(method)
        if (
            owner_token
            and method_token
            and owner_token in type_tokens
            and method_token in member_tokens
        ):
            return True
    return False


def project_might_match(
    project: TestProjectIndex,
    signals: dict[str, set[str]],
    *,
    exact_api_prefilter_mode: bool | None = None,
) -> bool:
    """Check if a project might match the given signals."""
    ensure_project_search_summary(project)
    exact_api_prefilter = (
        (
            bool(signals.get("exact_api_prefilter_entities"))
            or bool(extract_member_hint_keys(signals.get("member_hints", set())))
            or any("." in item for item in signals.get("symbols", set()))
        )
        if exact_api_prefilter_mode is None
        else bool(exact_api_prefilter_mode)
    )

    if exact_api_prefilter:
        return project_matches_exact_api_prefilter(project, signals)

    if signals["modules"] & project.search_imports:
        return True

    for token in signals.get("project_hints", set()):
        if not token:
            continue
        if token in project.search_path_tokens or token in project.search_words:
            return True
        if token in project.search_project_path_compact:
            return True
        if any(token in file_path for file_path in project.search_file_path_compacts):
            return True

    for method in signals.get("method_hints", set()):
        method_token = compact_token(method)
        if method_token and method_token in project.search_member_call_tokens:
            return True

    for hint in signals.get("type_hints", set()):
        hint_token = compact_token(hint)
        if not hint_token:
            continue
        if (
            hint_token in project.search_type_owner_tokens
            or hint_token in project.search_imported_symbol_tokens
            or hint_token in project.search_identifier_call_tokens
            or hint_token in project.search_typed_field_types
        ):
            return True

    for symbol in signals.get("symbols", set()):
        symbol_token = compact_token(symbol)
        if (
            symbol in project.search_imported_symbols
            or symbol in project.search_identifier_calls
        ):
            return True
        if symbol_token and (
            symbol_token in project.search_imported_symbol_tokens
            or symbol_token in project.search_identifier_call_tokens
            or symbol_token in project.search_member_call_tokens
            or symbol_token in project.search_type_owner_tokens
            or symbol_token in project.search_typed_field_types
            or symbol_token in project.search_words
        ):
            return True
        if symbol.endswith("Modifier"):
            base_token = compact_token(symbol[:-8])
            if base_token and base_token in project.search_typed_modifier_bases:
                return True

    # Weak symbol fallback — only check if no strong match yet
    weak_symbols = signals.get("weak_symbols", set())
    if weak_symbols:
        project_identifier_calls = project.search_identifier_calls
        if weak_symbols & project_identifier_calls:
            return True

    return False


def variant_matches(project_variant: str, variants_mode: str) -> bool:
    """Check if a project variant matches the requested variants mode."""
    if variants_mode in {"auto", "both"}:
        return True
    if project_variant == "both":
        return True
    if project_variant == "unknown":
        return False
    return project_variant == variants_mode


def select_candidate_projects(
    projects: list[TestProjectIndex],
    signals: dict[str, set[str]],
    variants_mode: str,
) -> tuple[list[TestProjectIndex], list[TestProjectIndex]]:
    """Select candidate projects based on signals and variants mode."""
    variant_projects = [
        project
        for project in projects
        if variant_matches(project.variant, variants_mode)
    ]
    exact_shortlisted: list[TestProjectIndex] = []
    if signals.get("exact_api_prefilter_entities"):
        exact_shortlisted = [
            project
            for project in variant_projects
            if project_might_match(project, signals, exact_api_prefilter_mode=True)
        ]
        if exact_shortlisted:
            return variant_projects, exact_shortlisted

    shortlisted = [
        project
        for project in variant_projects
        if project_might_match(project, signals, exact_api_prefilter_mode=False)
    ]
    if not shortlisted:
        return variant_projects, variant_projects
    return variant_projects, shortlisted
