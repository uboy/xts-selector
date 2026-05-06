"""Tests for PR API response cache (pr_cache.py)."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from arkui_xts_selector.pr_cache import (
    CacheSchemaMismatchError,
    MissingPrCacheError,
    PrApiCache,
    PrCacheEntry,
    SCHEMA_VERSION,
)


def _make_entry(pr_number: int = 123, pr_url: str = "") -> PrCacheEntry:
    if not pr_url:
        pr_url = f"https://gitcode.com/openharmony/ace_engine/pull/{pr_number}"
    return PrCacheEntry(
        pr_url=pr_url,
        host_kind="gitcode",
        owner="openharmony",
        repo="ace_engine",
        pr_number=pr_number,
        changed_files=["foo/bar.cpp", "baz/qux.h"],
        normalized_ranges={"foo/bar.cpp": [(1, 10), (20, 30)]},
        fetch_status="ok",
        fetched_at="2026-05-06T00:00:00+00:00",
    )


class TestPrCacheEntry(unittest.TestCase):
    def test_round_trip(self) -> None:
        entry = _make_entry()
        d = entry.to_dict()
        restored = PrCacheEntry.from_dict(d)
        self.assertEqual(restored.pr_number, entry.pr_number)
        self.assertEqual(restored.changed_files, entry.changed_files)
        self.assertEqual(restored.normalized_ranges["foo/bar.cpp"], [(1, 10), (20, 30)])

    def test_schema_version_written(self) -> None:
        entry = _make_entry()
        d = entry.to_dict()
        self.assertEqual(d["schema_version"], SCHEMA_VERSION)

    def test_schema_mismatch_raises(self) -> None:
        d = _make_entry().to_dict()
        d["schema_version"] = "pr-api-cache-v999"
        with self.assertRaises(CacheSchemaMismatchError):
            PrCacheEntry.from_dict(d)

    def test_missing_schema_ok(self) -> None:
        d = _make_entry().to_dict()
        del d["schema_version"]
        restored = PrCacheEntry.from_dict(d)
        self.assertEqual(restored.pr_number, 123)

    def test_no_tokens_in_dict(self) -> None:
        entry = _make_entry()
        d = entry.to_dict()
        self.assertNotIn("token", d)
        self.assertNotIn("api_token", d)


class TestPrApiCacheReadWrite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(__file__).parent / "__test_pr_cache_tmp__"
        self.cache = PrApiCache(self.tmp, mode="read-write")

    def tearDown(self) -> None:
        import shutil
        if self.tmp.exists():
            shutil.rmtree(self.tmp)

    def test_put_and_get(self) -> None:
        entry = _make_entry(100)
        self.cache.put(entry)
        got = self.cache.get(entry.pr_url)
        self.assertIsNotNone(got)
        self.assertEqual(got.pr_number, 100)
        self.assertEqual(got.changed_files, ["foo/bar.cpp", "baz/qux.h"])

    def test_get_missing_returns_none(self) -> None:
        got = self.cache.get("https://gitcode.com/x/y/pull/999")
        self.assertIsNone(got)

    def test_has(self) -> None:
        entry = _make_entry(200)
        self.assertFalse(self.cache.has(entry.pr_url))
        self.cache.put(entry)
        self.assertTrue(self.cache.has(entry.pr_url))

    def test_cache_path_structure(self) -> None:
        entry = _make_entry(300)
        self.cache.put(entry)
        path = self.cache._entry_path(entry.pr_url)
        self.assertTrue(str(path).endswith("PR_300.json"))
        self.assertIn("gitcode_com", str(path))
        self.assertIn("openharmony", str(path))
        self.assertIn("ace_engine", str(path))

    def test_corrupt_json_returns_none(self) -> None:
        entry = _make_entry(400)
        self.cache.put(entry)
        path = self.cache._entry_path(entry.pr_url)
        path.write_text("NOT JSON", encoding="utf-8")
        got = self.cache.get(entry.pr_url)
        self.assertIsNone(got)


class TestPrApiCacheReadOnly(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(__file__).parent / "__test_pr_cache_ro_tmp__"
        self.cache = PrApiCache(self.tmp, mode="read-write")
        self.cache_ro = PrApiCache(self.tmp, mode="read-only")

    def tearDown(self) -> None:
        import shutil
        if self.tmp.exists():
            shutil.rmtree(self.tmp)

    def test_read_existing(self) -> None:
        entry = _make_entry(500)
        self.cache.put(entry)
        got = self.cache_ro.get(entry.pr_url)
        self.assertIsNotNone(got)
        self.assertEqual(got.pr_number, 500)

    def test_missing_raises(self) -> None:
        with self.assertRaises(MissingPrCacheError):
            self.cache_ro.get("https://gitcode.com/x/y/pull/999")

    def test_corrupt_raises(self) -> None:
        entry = _make_entry(501)
        self.cache.put(entry)
        path = self.cache._entry_path(entry.pr_url)
        path.write_text("BAD", encoding="utf-8")
        with self.assertRaises(MissingPrCacheError):
            self.cache_ro.get(entry.pr_url)

    def test_put_is_noop(self) -> None:
        entry = _make_entry(502)
        self.cache_ro.put(entry)
        self.assertFalse(self.cache_ro.has(entry.pr_url))


class TestPrApiCacheRefresh(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(__file__).parent / "__test_pr_cache_refresh_tmp__"
        self.cache = PrApiCache(self.tmp, mode="read-write")
        self.cache_refresh = PrApiCache(self.tmp, mode="refresh")

    def tearDown(self) -> None:
        import shutil
        if self.tmp.exists():
            shutil.rmtree(self.tmp)

    def test_refresh_overwrites(self) -> None:
        entry1 = _make_entry(600)
        entry1.changed_files = ["old.cpp"]
        self.cache.put(entry1)

        entry2 = _make_entry(600)
        entry2.changed_files = ["new.cpp"]
        self.cache_refresh.put(entry2)

        got = self.cache.get(entry1.pr_url)
        self.assertEqual(got.changed_files, ["new.cpp"])


class TestProxyCleanup(unittest.TestCase):
    def test_all_proxy_vars_in_list(self) -> None:
        expected = {
            "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
            "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY",
        }
        from arkui_xts_selector.batch_validate import cmd_validate_batch
        import inspect
        source = inspect.getsource(cmd_validate_batch)
        for var in expected:
            self.assertIn(f'"{var}"', source, f"Proxy var {var} not found in cleanup list")


if __name__ == "__main__":
    unittest.main()
