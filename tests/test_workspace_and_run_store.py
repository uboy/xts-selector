from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.run_store import create_run_session, resolve_labeled_run
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


if __name__ == "__main__":
    unittest.main()
