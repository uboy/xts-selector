"""Data models: error types, config, and index dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .daily_prebuilt import (
    DEFAULT_DAILY_COMPONENT,
    DEFAULT_FIRMWARE_COMPONENT,
    DEFAULT_SDK_COMPONENT,
    PreparedDailyPrebuilt,
)


class XtsUserError(RuntimeError):
    """User-facing error with an optional recovery hint."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint or ""

    def __str__(self) -> str:
        base = super().__str__()
        if not self.hint:
            return base
        return f"{base}\n  Hint: {self.hint}"


@dataclass(frozen=True)
class XtsWorkspaceSnapshot:
    signature: str
    newest_mtime_ns: int


@dataclass
class SdkIndex:
    component_names: set[str] = field(default_factory=set)
    modifier_names: set[str] = field(default_factory=set)
    top_level_modules: set[str] = field(default_factory=set)
    component_file_bases: dict[str, str] = field(default_factory=dict)
    modifier_file_bases: dict[str, str] = field(default_factory=dict)


@dataclass
class ContentModifierIndex:
    families: set[str] = field(default_factory=set)
    family_to_symbols: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class MappingConfig:
    special_path_rules: dict[str, dict] = field(default_factory=dict)
    pattern_alias: dict[str, list[str]] = field(default_factory=dict)
    composite_mappings: dict[str, dict] = field(default_factory=dict)


@dataclass
class ChangedFileExclusionConfig:
    path_prefixes: list[str] = field(default_factory=list)
    rules: list[dict[str, object]] = field(default_factory=list)


@dataclass
class AppConfig:
    repo_root: Path
    xts_root: Path
    sdk_api_root: Path
    cache_file: Path | None
    git_repo_root: Path
    git_remote: str
    git_base_branch: str
    git_host_kind: str = "auto"
    git_host_api_url: str | None = None
    git_host_token: str | None = None
    git_host_config_path: Path | None = None
    server_host: str | None = None
    server_user: str | None = None
    device: str | None = None
    devices: list[str] = field(default_factory=list)
    gitcode_api_url: str | None = None
    gitcode_token: str | None = None
    acts_out_root: Path | None = None
    path_rules_file: Path | None = None
    composite_mappings_file: Path | None = None
    ranking_rules_file: Path | None = None
    changed_file_exclusions_file: Path | None = None
    product_name: str | None = None
    system_size: str = "standard"
    xts_suitetype: str | None = None
    selector_repo_root: Path | None = None
    run_label: str | None = None
    run_store_root: Path | None = None
    runtime_state_root: Path | None = None
    shard_mode: str = "mirror"
    device_lock_timeout: float = 30.0
    daily_build_tag: str | None = None
    daily_component: str = DEFAULT_DAILY_COMPONENT
    daily_branch: str = "master"
    daily_date: str | None = None
    daily_cache_root: Path | None = None
    daily_prebuilt: PreparedDailyPrebuilt | None = None
    daily_prebuilt_ready: bool = False
    daily_prebuilt_note: str = ""
    quick_mode: bool = False
    sdk_build_tag: str | None = None
    sdk_component: str = DEFAULT_SDK_COMPONENT
    sdk_branch: str = "master"
    sdk_date: str | None = None
    sdk_cache_root: Path | None = None
    firmware_build_tag: str | None = None
    firmware_component: str = DEFAULT_FIRMWARE_COMPONENT
    firmware_branch: str = "master"
    firmware_date: str | None = None
    firmware_cache_root: Path | None = None
    flash_firmware_path: Path | None = None
    flash_py_path: Path | None = None
    hdc_path: Path | None = None
    hdc_endpoint: str | None = None


@dataclass
class TestFileIndex:
    relative_path: str
    surface: str = "utility"
    imports: set[str] = field(default_factory=set)
    imported_symbols: set[str] = field(default_factory=set)
    identifier_calls: set[str] = field(default_factory=set)
    member_calls: set[str] = field(default_factory=set)
    type_member_calls: set[str] = field(default_factory=set)
    typed_field_accesses: set[str] = field(default_factory=set)
    typed_modifier_bases: set[str] = field(default_factory=set)
    words: set[str] = field(default_factory=set)
    # Phase 5: evidence kind tracking
    evidence_kinds: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "relative_path": self.relative_path,
            "surface": self.surface,
            "imports": sorted(self.imports),
            "imported_symbols": sorted(self.imported_symbols),
            "identifier_calls": sorted(self.identifier_calls),
            "member_calls": sorted(self.member_calls),
            "type_member_calls": sorted(self.type_member_calls),
            "typed_field_accesses": sorted(self.typed_field_accesses),
            "typed_modifier_bases": sorted(self.typed_modifier_bases),
            "words": sorted(self.words),
            "evidence_kinds": dict(self.evidence_kinds),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestFileIndex":
        return cls(
            relative_path=data["relative_path"],
            surface=data.get("surface", "utility"),
            imports=set(data["imports"]),
            imported_symbols=set(data["imported_symbols"]),
            identifier_calls=set(data["identifier_calls"]),
            member_calls=set(data["member_calls"]),
            type_member_calls=set(data.get("type_member_calls", [])),
            typed_field_accesses=set(data.get("typed_field_accesses", [])),
            typed_modifier_bases=set(data.get("typed_modifier_bases", [])),
            words=set(data["words"]),
            evidence_kinds=data.get("evidence_kinds", {}),
        )


@dataclass
class TestProjectIndex:
    relative_root: str
    test_json: str
    bundle_name: str | None
    files: list[TestFileIndex] = field(default_factory=list)
    path_key: str = ""
    variant: str = "unknown"
    surface: str = "unknown"
    supported_surfaces: set[str] = field(default_factory=set)
    search_summary_ready: bool = False
    search_imports: set[str] = field(default_factory=set)
    search_imported_symbols: set[str] = field(default_factory=set)
    search_imported_symbol_tokens: set[str] = field(default_factory=set)
    search_identifier_calls: set[str] = field(default_factory=set)
    search_identifier_call_tokens: set[str] = field(default_factory=set)
    search_member_call_tokens: set[str] = field(default_factory=set)
    search_type_owner_tokens: set[str] = field(default_factory=set)
    search_typed_field_types: set[str] = field(default_factory=set)
    search_exact_member_keys: set[str] = field(default_factory=set)
    search_typed_modifier_bases: set[str] = field(default_factory=set)
    search_words: set[str] = field(default_factory=set)
    search_path_tokens: set[str] = field(default_factory=set)
    search_project_path_compact: str = ""
    search_file_path_compacts: list[str] = field(default_factory=list)
    search_evidence_kinds: dict[str, str] = field(default_factory=dict)
    _serialized_files: list[dict] | None = field(
        default=None, repr=False, compare=False
    )

    def to_dict(self) -> dict:
        payload = {
            "relative_root": self.relative_root,
            "test_json": self.test_json,
            "bundle_name": self.bundle_name,
            "path_key": self.path_key,
            "variant": self.variant,
            "surface": self.surface,
            "supported_surfaces": sorted(self.supported_surfaces),
            "files": self._serialized_files
            if self._serialized_files is not None
            else [item.to_dict() for item in self.files],
        }
        if self.search_summary_ready:
            payload["search_summary"] = {
                "imports": sorted(self.search_imports),
                "imported_symbols": sorted(self.search_imported_symbols),
                "imported_symbol_tokens": sorted(self.search_imported_symbol_tokens),
                "identifier_calls": sorted(self.search_identifier_calls),
                "identifier_call_tokens": sorted(self.search_identifier_call_tokens),
                "member_call_tokens": sorted(self.search_member_call_tokens),
                "type_owner_tokens": sorted(self.search_type_owner_tokens),
                "typed_field_types": sorted(self.search_typed_field_types),
                "exact_member_keys": sorted(self.search_exact_member_keys),
                "typed_modifier_bases": sorted(self.search_typed_modifier_bases),
                "words": sorted(self.search_words),
                "path_tokens": sorted(self.search_path_tokens),
                "project_path_compact": self.search_project_path_compact,
                "file_path_compacts": list(self.search_file_path_compacts),
                "evidence_kinds": dict(self.search_evidence_kinds),
            }
        return payload

    @classmethod
    def from_dict(cls, data: dict, *, lazy_files: bool = False) -> "TestProjectIndex":
        summary = data.get("search_summary")
        raw_files = data.get("files", [])
        serialized_files = None
        files: list[TestFileIndex]
        if lazy_files and isinstance(summary, dict) and isinstance(raw_files, list):
            files = []
            serialized_files = raw_files
        else:
            files = [TestFileIndex.from_dict(item) for item in raw_files]
        project = cls(
            relative_root=data["relative_root"],
            test_json=data["test_json"],
            bundle_name=data.get("bundle_name"),
            path_key=data["path_key"],
            variant=data.get("variant", "unknown"),
            surface=data.get("surface", data.get("variant", "unknown")),
            supported_surfaces=set(data.get("supported_surfaces", [])),
            files=files,
            _serialized_files=serialized_files,
        )
        if isinstance(summary, dict):
            project.search_summary_ready = True
            project.search_imports = set(summary.get("imports", []))
            project.search_imported_symbols = set(summary.get("imported_symbols", []))
            project.search_imported_symbol_tokens = set(
                summary.get("imported_symbol_tokens", [])
            )
            project.search_identifier_calls = set(summary.get("identifier_calls", []))
            project.search_identifier_call_tokens = set(
                summary.get("identifier_call_tokens", [])
            )
            project.search_member_call_tokens = set(
                summary.get("member_call_tokens", [])
            )
            project.search_type_owner_tokens = set(summary.get("type_owner_tokens", []))
            project.search_typed_field_types = set(summary.get("typed_field_types", []))
            project.search_exact_member_keys = set(summary.get("exact_member_keys", []))
            project.search_typed_modifier_bases = set(
                summary.get("typed_modifier_bases", [])
            )
            project.search_words = set(summary.get("words", []))
            project.search_path_tokens = set(summary.get("path_tokens", []))
            project.search_project_path_compact = str(
                summary.get("project_path_compact", "")
            )
            project.search_file_path_compacts = [
                str(item) for item in summary.get("file_path_compacts", [])
            ]
            project.search_evidence_kinds = dict(summary.get("evidence_kinds", {}))
        return project
