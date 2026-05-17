"""Tests for PrCacheEntry v2 with SHA/reference fields."""

from __future__ import annotations

from datetime import datetime, timezone
import json


from arkui_xts_selector.pr_cache import PrCacheEntry, PrApiCache


class TestPrCacheEntryShaFields:
    """Test new SHA and reference fields in PrCacheEntry."""

    def test_new_fields_default_to_none(self):
        """New SHA fields default to None when not provided."""
        entry = PrCacheEntry(
            pr_url="https://gitcode.com/owner/repo/merge_requests/1",
            host_kind="gitcode",
            owner="owner",
            repo="repo",
            pr_number=1,
        )
        assert entry.base_sha is None
        assert entry.head_sha is None
        assert entry.base_ref is None
        assert entry.head_ref is None

    def test_serialization_roundtrip_with_sha_fields(self):
        """Serialization and deserialization roundtrip preserves SHA fields."""
        entry = PrCacheEntry(
            pr_url="https://gitcode.com/owner/repo/merge_requests/1",
            host_kind="gitcode",
            owner="owner",
            repo="repo",
            pr_number=1,
            base_sha="abc123def456",
            head_sha="789ghi012jkl",
            base_ref="master",
            head_ref="feature/test",
        )
        d = entry.to_dict()
        restored = PrCacheEntry.from_dict(d)
        assert restored.base_sha == "abc123def456"
        assert restored.head_sha == "789ghi012jkl"
        assert restored.base_ref == "master"
        assert restored.head_ref == "feature/test"

    def test_deserialization_v1_cache_defaults_shas_to_none(self):
        """Deserializing v1 cache (no SHA fields) defaults all SHA fields to None."""
        v1_data = {
            "pr_url": "https://gitcode.com/owner/repo/merge_requests/1",
            "host_kind": "gitcode",
            "owner": "owner",
            "repo": "repo",
            "pr_number": 1,
            "changed_files": ["file.ts"],
            "raw_files": [],
            "raw_patch_hunks": {},
            "normalized_ranges": {},
            "fetch_status": "ok",
            "api_error": "",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "pr-api-cache-v1",
        }
        entry = PrCacheEntry.from_dict(v1_data)
        assert entry.base_sha is None
        assert entry.head_sha is None
        assert entry.base_ref is None
        assert entry.head_ref is None

    def test_existing_code_works_with_missing_fields(self):
        """Existing code paths work when SHA fields are missing."""
        entry = PrCacheEntry(
            pr_url="https://gitcode.com/owner/repo/merge_requests/1",
            host_kind="gitcode",
            owner="owner",
            repo="repo",
            pr_number=1,
            changed_files=["file1.ts", "file2.ts"],
        )
        assert entry.changed_files == ["file1.ts", "file2.ts"]
        assert entry.fetch_status == "ok"
        assert entry.pr_number == 1

    def test_partial_sha_fields_allowed(self):
        """Partial SHA fields are allowed (some None, some set)."""
        entry = PrCacheEntry(
            pr_url="https://gitcode.com/owner/repo/merge_requests/1",
            host_kind="gitcode",
            owner="owner",
            repo="repo",
            pr_number=1,
            base_sha="abc123",
            head_ref="feature/test",
        )
        assert entry.base_sha == "abc123"
        assert entry.head_sha is None
        assert entry.base_ref is None
        assert entry.head_ref == "feature/test"

    def test_to_dict_includes_all_sha_fields(self):
        """to_dict includes all SHA fields, even if None."""
        entry = PrCacheEntry(
            pr_url="https://gitcode.com/owner/repo/merge_requests/1",
            host_kind="gitcode",
            owner="owner",
            repo="repo",
            pr_number=1,
            base_sha="abc123",
        )
        d = entry.to_dict()
        assert "base_sha" in d
        assert "head_sha" in d
        assert "base_ref" in d
        assert "head_ref" in d
        assert d["base_sha"] == "abc123"
        assert d["head_sha"] is None

    def test_from_dict_ignores_unknown_fields(self):
        """from_dict ignores fields not in dataclass."""
        data = {
            "pr_url": "https://gitcode.com/owner/repo/merge_requests/1",
            "host_kind": "gitcode",
            "owner": "owner",
            "repo": "repo",
            "pr_number": 1,
            "unknown_field": "should_be_ignored",
            "base_sha": "abc123",
        }
        entry = PrCacheEntry.from_dict(data)
        assert entry.base_sha == "abc123"
        assert not hasattr(entry, "unknown_field")


class TestPrCacheFilePersistence:
    """Test file persistence with SHA fields."""

    def test_write_and_read_cache_with_shas(self, tmp_path):
        """Write and read cache entry with SHA fields."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        entry = PrCacheEntry(
            pr_url="https://gitcode.com/owner/repo/merge_requests/123",
            host_kind="gitcode",
            owner="owner",
            repo="repo",
            pr_number=123,
            base_sha="abc123",
            head_sha="def456",
            base_ref="master",
            head_ref="feature/test",
        )

        cache = PrApiCache(cache_dir, mode="read-write")
        cache.put(entry)

        restored = cache.get(entry.pr_url)
        assert restored is not None
        assert restored.base_sha == "abc123"
        assert restored.head_sha == "def456"
        assert restored.base_ref == "master"
        assert restored.head_ref == "feature/test"

    def test_read_v1_cache_without_shas(self, tmp_path):
        """Read v1 cache file (without SHA fields) and verify default None values."""
        cache_dir = tmp_path / "cache"
        host_dir = cache_dir / "gitcode_com" / "owner" / "repo"
        host_dir.mkdir(parents=True)

        v1_entry = {
            "pr_url": "https://gitcode.com/owner/repo/merge_requests/456",
            "host_kind": "gitcode",
            "owner": "owner",
            "repo": "repo",
            "pr_number": 456,
            "changed_files": ["oldfile.ts"],
            "raw_files": [],
            "raw_patch_hunks": {},
            "normalized_ranges": {},
            "fetch_status": "ok",
            "api_error": "",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "pr-api-cache-v1",
        }

        cache_file = host_dir / "PR_456.json"
        cache_file.write_text(json.dumps(v1_entry, ensure_ascii=False, indent=2))

        cache = PrApiCache(cache_dir, mode="read-only")
        entry = cache.get(v1_entry["pr_url"])
        assert entry is not None
        assert entry.base_sha is None
        assert entry.head_sha is None
        assert entry.base_ref is None
        assert entry.head_ref is None
        assert entry.changed_files == ["oldfile.ts"]


class TestRefreshPrMetadataScript:
    """Test refresh_pr_metadata.py functionality."""

    def test_extract_pr_shas_from_gitcode_response(self):
        """Test SHA extraction from GitCode API response."""
        from arkui_xts_selector.git_host import extract_pr_shas_from_api_response

        response = {
            "base": {
                "sha": "abc123def456",
                "ref": "master",
                "label": "ace:master",
            },
            "head": {
                "sha": "789ghi012jkl",
                "ref": "feature/test",
                "label": "ace:feature/test",
            },
            "merge_commit_sha": "merged123",
        }

        base_sha, head_sha, base_ref, head_ref = extract_pr_shas_from_api_response(
            "gitcode", response
        )
        assert base_sha == "abc123def456"
        assert head_sha == "789ghi012jkl"
        assert base_ref == "master"
        assert head_ref == "feature/test"

    def test_extract_pr_shas_from_codehub_response(self):
        """Test SHA extraction from CodeHub API response."""
        from arkui_xts_selector.git_host import extract_pr_shas_from_api_response

        response = {
            "target_branch": "master",
            "target_branch_sha": "abc123",
            "source_branch": "feature/test",
            "source_branch_sha": "def456",
            "diff_refs": {
                "base_sha": "ghi789",
                "head_sha": "jkl012",
            },
        }

        base_sha, head_sha, base_ref, head_ref = extract_pr_shas_from_api_response(
            "codehub", response
        )
        assert base_sha == "ghi789"
        assert head_sha == "jkl012"
        assert base_ref == "master"
        assert head_ref == "feature/test"

    def test_extract_pr_shas_missing_data(self):
        """Test SHA extraction returns None for missing data."""
        from arkui_xts_selector.git_host import extract_pr_shas_from_api_response

        response = {}
        base_sha, head_sha, base_ref, head_ref = extract_pr_shas_from_api_response(
            "gitcode", response
        )
        assert base_sha is None
        assert head_sha is None
        assert base_ref is None
        assert head_ref is None

    def test_extract_pr_shas_invalid_response(self):
        """Test SHA extraction handles non-dict responses."""
        from arkui_xts_selector.git_host import extract_pr_shas_from_api_response

        result = extract_pr_shas_from_api_response("gitcode", None)
        assert result == (None, None, None, None)

        result = extract_pr_shas_from_api_response("gitcode", [])
        assert result == (None, None, None, None)
