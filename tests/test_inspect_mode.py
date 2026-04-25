"""
Tests for Phase 6 P6-002: run_inspect_mode.

Verifies that the inspect mode correctly queries the persisted lineage map
for api-entity, source-file, and consumer-project lookups.

Run:
    python3 -m unittest tests.test_inspect_mode -v
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.api_lineage import (
    ApiLineageMap,
    write_api_lineage_map,
    default_api_lineage_map_file,
)
from arkui_xts_selector.cli import AppConfig, run_inspect_mode


def _make_app_config(runtime_state_root: Path, tmpdir: Path) -> AppConfig:
    xts_root = tmpdir / "test/xts"
    xts_root.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        repo_root=tmpdir,
        xts_root=xts_root,
        sdk_api_root=tmpdir / "interface/sdk-js/api",
        cache_file=None,
        git_repo_root=tmpdir,
        git_remote="origin",
        git_base_branch="master",
        runtime_state_root=runtime_state_root,
    )


def _make_args(**kwargs) -> argparse.Namespace:
    defaults = {
        "inspect_api_entity": None,
        "inspect_source_file": None,
        "inspect_consumer_project": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _write_fixture_map(runtime_state_root: Path) -> ApiLineageMap:
    """Write a minimal lineage map for testing."""
    m = ApiLineageMap()
    m.source_to_apis["frameworks/core/components_ng/pattern/button/button_model.cpp"] = {
        "ButtonAttribute.role"
    }
    m.api_to_sources["ButtonAttribute.role"] = {
        "frameworks/core/components_ng/pattern/button/button_model.cpp"
    }
    m.api_to_families["ButtonAttribute.role"] = {"button"}
    m.api_to_surfaces["ButtonAttribute.role"] = {"static"}
    m.api_to_consumer_files["ButtonAttribute.role"] = {
        "test/xts/acts/arkui/button_static/src/ButtonRoleTest.ts"
    }
    m.api_to_consumer_projects["ButtonAttribute.role"] = {
        "test/xts/acts/arkui/button_static"
    }
    m.consumer_project_to_apis["test/xts/acts/arkui/button_static"] = {
        "ButtonAttribute.role"
    }
    target_path = default_api_lineage_map_file(runtime_state_root)
    write_api_lineage_map(target_path, m)
    return m


class InspectMissingMapTests(unittest.TestCase):
    """Test behaviour when no lineage map file exists."""

    def test_returns_exit_code_2_when_map_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            runtime_state_root.mkdir()
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args()

            with self.assertLogs("root", level="WARNING") if False else self._capture_stderr() as _:
                exit_code = run_inspect_mode(args, app_config)

        self.assertEqual(exit_code, 2)

    def _capture_stderr(self):
        """Null context manager to avoid polluting test output with expected stderr."""
        import contextlib
        return contextlib.redirect_stderr(io.StringIO())


class InspectApiEntityTests(unittest.TestCase):
    """Test --inspect --api-entity mode."""

    def test_api_entity_returns_source_files(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args(inspect_api_entity="ButtonAttribute.role")

            buf = io.StringIO()
            with _redirect_stdout(buf):
                exit_code = run_inspect_mode(args, app_config)

        self.assertEqual(exit_code, 0)
        result = json.loads(buf.getvalue())
        self.assertEqual(result["api_entity"], "ButtonAttribute.role")
        self.assertIn(
            "frameworks/core/components_ng/pattern/button/button_model.cpp",
            result["source_files"],
        )

    def test_api_entity_returns_families(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args(inspect_api_entity="ButtonAttribute.role")

            buf = io.StringIO()
            with _redirect_stdout(buf):
                run_inspect_mode(args, app_config)

        result = json.loads(buf.getvalue())
        self.assertIn("button", result["families"])

    def test_api_entity_returns_consumer_projects(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args(inspect_api_entity="ButtonAttribute.role")

            buf = io.StringIO()
            with _redirect_stdout(buf):
                run_inspect_mode(args, app_config)

        result = json.loads(buf.getvalue())
        self.assertIn("test/xts/acts/arkui/button_static", result["consumer_projects"])

    def test_api_entity_unknown_returns_empty_lists(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args(inspect_api_entity="UnknownEntity.method")

            buf = io.StringIO()
            with _redirect_stdout(buf):
                exit_code = run_inspect_mode(args, app_config)

        self.assertEqual(exit_code, 0)
        result = json.loads(buf.getvalue())
        self.assertEqual(result["source_files"], [])
        self.assertEqual(result["consumer_projects"], [])


class InspectSourceFileTests(unittest.TestCase):
    """Test --inspect --source-file mode."""

    def test_source_file_returns_api_entities(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            source = "frameworks/core/components_ng/pattern/button/button_model.cpp"
            args = _make_args(inspect_source_file=source)

            buf = io.StringIO()
            with _redirect_stdout(buf):
                exit_code = run_inspect_mode(args, app_config)

        self.assertEqual(exit_code, 0)
        result = json.loads(buf.getvalue())
        self.assertEqual(result["source_file"], source)
        self.assertIn("ButtonAttribute.role", result["api_entities"])

    def test_source_file_returns_consumer_projects(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            source = "frameworks/core/components_ng/pattern/button/button_model.cpp"
            args = _make_args(inspect_source_file=source)

            buf = io.StringIO()
            with _redirect_stdout(buf):
                run_inspect_mode(args, app_config)

        result = json.loads(buf.getvalue())
        self.assertIn("test/xts/acts/arkui/button_static", result["consumer_projects"])

    def test_source_file_unknown_returns_empty(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args(inspect_source_file="frameworks/unknown/file.cpp")

            buf = io.StringIO()
            with _redirect_stdout(buf):
                exit_code = run_inspect_mode(args, app_config)

        self.assertEqual(exit_code, 0)
        result = json.loads(buf.getvalue())
        self.assertEqual(result["api_entities"], [])
        self.assertEqual(result["consumer_projects"], [])


class InspectConsumerProjectTests(unittest.TestCase):
    """Test --inspect --consumer-project mode."""

    def test_consumer_project_returns_api_entities(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args(inspect_consumer_project="test/xts/acts/arkui/button_static")

            buf = io.StringIO()
            with _redirect_stdout(buf):
                exit_code = run_inspect_mode(args, app_config)

        self.assertEqual(exit_code, 0)
        result = json.loads(buf.getvalue())
        self.assertEqual(result["consumer_project"], "test/xts/acts/arkui/button_static")
        self.assertIn("ButtonAttribute.role", result["api_entities"])

    def test_consumer_project_returns_source_files(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args(inspect_consumer_project="test/xts/acts/arkui/button_static")

            buf = io.StringIO()
            with _redirect_stdout(buf):
                run_inspect_mode(args, app_config)

        result = json.loads(buf.getvalue())
        self.assertIn(
            "frameworks/core/components_ng/pattern/button/button_model.cpp",
            result["source_files"],
        )

    def test_consumer_project_unknown_returns_empty(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args(inspect_consumer_project="test/xts/acts/unknown_project")

            buf = io.StringIO()
            with _redirect_stdout(buf):
                exit_code = run_inspect_mode(args, app_config)

        self.assertEqual(exit_code, 0)
        result = json.loads(buf.getvalue())
        self.assertEqual(result["api_entities"], [])
        self.assertEqual(result["source_files"], [])


class InspectSummaryTests(unittest.TestCase):
    """Test --inspect without a specific query (summary mode)."""

    def test_summary_returns_schema_version(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args()

            buf = io.StringIO()
            with _redirect_stdout(buf):
                exit_code = run_inspect_mode(args, app_config)

        self.assertEqual(exit_code, 0)
        result = json.loads(buf.getvalue())
        self.assertIn("schema_version", result)
        self.assertIn("source_to_api_count", result)
        self.assertIn("consumer_project_count", result)

    def test_summary_reflects_map_counts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            runtime_state_root = Path(tmpdir) / ".runtime"
            _write_fixture_map(runtime_state_root)
            app_config = _make_app_config(runtime_state_root, Path(tmpdir))
            args = _make_args()

            buf = io.StringIO()
            with _redirect_stdout(buf):
                run_inspect_mode(args, app_config)

        result = json.loads(buf.getvalue())
        self.assertEqual(result["source_to_api_count"], 1)
        self.assertEqual(result["api_to_source_count"], 1)
        self.assertEqual(result["consumer_project_count"], 1)


import contextlib


def _redirect_stdout(buf: io.StringIO):
    return contextlib.redirect_stdout(buf)


if __name__ == "__main__":
    unittest.main(verbosity=2)
