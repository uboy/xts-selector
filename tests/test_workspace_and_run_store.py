from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.cli import resolve_selector_report_input, run_session_from_report
from arkui_xts_selector.run_store import create_run_session, resolve_labeled_run, resolve_latest_run
from arkui_xts_selector.workspace import discover_repo_root


def _create_ohos_tree(root: Path) -> None:
    (root / "foundation/arkui/ace_engine").mkdir(parents=True, exist_ok=True)
    (root / "interface/sdk-js/api").mkdir(parents=True, exist_ok=True)
    (root / "test/xts/acts/arkui").mkdir(parents=True, exist_ok=True)


class WorkspaceDiscoveryTests(unittest.TestCase):
    def test_discover_repo_root_finds_sibling_ohos_master(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            selector_root = base / "arkui-xts-selector"
            selector_root.mkdir()
            ohos_root = base / "ohos_master"
            _create_ohos_tree(ohos_root)

            discovered = discover_repo_root(
                search_roots=[selector_root],
                selector_repo_root=selector_root,
            )

        self.assertEqual(discovered, ohos_root.resolve())

    def test_discover_repo_root_skips_inaccessible_sibling(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            selector_root = base / "arkui-xts-selector"
            selector_root.mkdir()
            blocked_root = base / "admin1"
            blocked_root.mkdir()
            ohos_root = base / "ohos_master"
            _create_ohos_tree(ohos_root)

            blocked_root.chmod(0)
            try:
                discovered = discover_repo_root(
                    search_roots=[selector_root],
                    selector_repo_root=selector_root,
                )
            finally:
                blocked_root.chmod(0o755)

        self.assertEqual(discovered, ohos_root.resolve())


class RunStoreResolutionTests(unittest.TestCase):
    def test_resolve_labeled_run_prefers_latest_comparable_completed_manifest(self) -> None:
        with TemporaryDirectory() as tmpdir:
            run_store_root = Path(tmpdir) / ".runs"
            comparable_dir = Path(tmpdir) / "baseline-result"
            comparable_dir.mkdir(parents=True)

            completed = create_run_session(
                "baseline",
                run_store_root=run_store_root,
                timestamp="20260403T100000Z",
            )
            completed.manifest_path.write_text(
                json.dumps(
                    {
                        "label": "baseline",
                        "label_key": "baseline",
                        "timestamp": "20260403T100000Z",
                        "status": "completed",
                        "run_dir": str(completed.run_dir),
                        "comparable_result_paths": [str(comparable_dir)],
                    }
                ),
                encoding="utf-8",
            )

            failed = create_run_session(
                "baseline",
                run_store_root=run_store_root,
                timestamp="20260403T110000Z",
            )
            failed.manifest_path.write_text(
                json.dumps(
                    {
                        "label": "baseline",
                        "label_key": "baseline",
                        "timestamp": "20260403T110000Z",
                        "status": "failed_preflight",
                        "run_dir": str(failed.run_dir),
                        "comparable_result_paths": [],
                    }
                ),
                encoding="utf-8",
            )

            resolved = resolve_labeled_run(run_store_root, "baseline")

        self.assertEqual(Path(resolved["_manifest_path"]), completed.manifest_path.resolve())
        self.assertEqual(resolved["_resolved_result_paths"], [str(comparable_dir.resolve())])

    def test_resolve_latest_run_returns_newest_manifest(self) -> None:
        with TemporaryDirectory() as tmpdir:
            run_store_root = Path(tmpdir) / ".runs"
            first = create_run_session(
                "report",
                run_store_root=run_store_root,
                timestamp="20260403T100000Z",
            )
            first.manifest_path.write_text(
                json.dumps(
                    {
                        "label": "report",
                        "label_key": "report",
                        "timestamp": "20260403T100000Z",
                        "status": "planned",
                        "run_dir": str(first.run_dir),
                        "selector_report_path": str(first.selector_report_path),
                    }
                ),
                encoding="utf-8",
            )
            second = create_run_session(
                "report",
                run_store_root=run_store_root,
                timestamp="20260403T120000Z",
            )
            second.manifest_path.write_text(
                json.dumps(
                    {
                        "label": "report",
                        "label_key": "report",
                        "timestamp": "20260403T120000Z",
                        "status": "planned",
                        "run_dir": str(second.run_dir),
                        "selector_report_path": str(second.selector_report_path),
                    }
                ),
                encoding="utf-8",
            )

            resolved = resolve_latest_run(run_store_root, label="report")

        self.assertEqual(Path(resolved["_manifest_path"]), second.manifest_path.resolve())

    def test_resolve_selector_report_input_uses_latest_manifest_report_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            run_store_root = Path(tmpdir) / ".runs"
            session = create_run_session(
                "report",
                run_store_root=run_store_root,
                timestamp="20260403T120000Z",
            )
            session.selector_report_path.write_text("{}", encoding="utf-8")
            session.manifest_path.write_text(
                json.dumps(
                    {
                        "label": "report",
                        "label_key": "report",
                        "timestamp": "20260403T120000Z",
                        "status": "planned",
                        "run_dir": str(session.run_dir),
                        "selector_report_path": str(session.selector_report_path),
                    }
                ),
                encoding="utf-8",
            )

            resolved = resolve_selector_report_input(None, True, run_store_root)

        self.assertEqual(resolved, session.selector_report_path.resolve())

    def test_run_session_from_report_reuses_existing_paths(self) -> None:
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "selector_report.json"
            manifest_path = Path(tmpdir) / "run_manifest.json"
            report = {
                "selector_run": {
                    "label": "baseline",
                    "label_key": "baseline",
                    "timestamp": "20260403T120000Z",
                    "run_dir": str(Path(tmpdir)),
                    "selector_report_path": str(report_path),
                    "manifest_path": str(manifest_path),
                }
            }

            session = run_session_from_report(report, report_path)

        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.label, "baseline")
        self.assertEqual(session.selector_report_path, report_path.resolve())
        self.assertEqual(session.manifest_path, manifest_path.resolve())


if __name__ == "__main__":
    unittest.main()
