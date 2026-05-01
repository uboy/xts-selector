"""Import boundary tests for architectural layer isolation.

This test skeleton verifies that new packages (model, graph) do not import
forbidden modules.  It passes now and will catch future violations.

Packages that do not exist yet are skipped.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _module_exists(name: str) -> bool:
    """Check whether a top-level module or package exists."""
    try:
        spec = importlib.util.find_spec(name)
        return spec is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _collect_submodules(package_name: str) -> list[str]:
    """Collect all submodules of a package."""
    try:
        package = importlib.import_module(package_name)
    except ImportError:
        return []
    if not hasattr(package, "__path__"):
        return [package_name]
    result = [package_name]
    for _importer, modname, _ispkg in pkgutil.walk_packages(
        package.__path__, prefix=package_name + "."
    ):
        result.append(modname)
    return result


def _get_imports(module_name: str) -> set[str]:
    """Get the set of top-level imports made by a module (without importing it).

    This inspects the AST to find import statements without executing the module.
    """
    import ast

    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        return set()

    try:
        source = Path(spec.origin).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return imports


# ---------------------------------------------------------------------------
# Forbidden import patterns per package
# ---------------------------------------------------------------------------

_FORBIDDEN_FOR_MODEL = {
    "cli", "report_human", "report_json", "report_build",
    "report_next_steps", "execution", "project_index", "signal_inference",
    "signal_scoring", "scoring", "coverage_planner", "coverage_keys",
    "ranking_rules", "graph", "source_profile", "changed_files",
    "git_host", "progress", "utility_modes", "benchmark",
    "consumer_semantics", "api_lineage", "api_surface",
    "tree_sitter_parsers", "symbol_tracing", "mapping_config",
}

_FORBIDDEN_FOR_GRAPH = {
    "cli", "report_human", "report_json", "report_build",
    "report_next_steps", "execution", "project_index", "signal_inference",
    "signal_scoring", "scoring", "coverage_planner", "coverage_keys",
    "ranking_rules", "source_profile", "changed_files",
    "git_host", "progress", "utility_modes", "benchmark",
    "consumer_semantics", "api_lineage", "api_surface",
    "tree_sitter_parsers", "symbol_tracing", "mapping_config",
}

_FORBIDDEN_FOR_RANKING = {"cli"}

_FORBIDDEN_FOR_REPORTING = {
    "signal_inference", "signal_scoring", "scoring",
    "project_index", "coverage_planner", "changed_files",
    "git_host", "ranking_rules", "source_profile",
}


class ImportBoundaryTests(unittest.TestCase):
    """Verify architectural import boundaries are respected."""

    def _check_package(self, package_name: str, forbidden: set[str]) -> None:
        if not _module_exists(package_name):
            self.skipTest(f"Package {package_name} does not exist yet")
        submodules = _collect_submodules(package_name)
        violations: list[str] = []
        for modname in submodules:
            imports = _get_imports(modname)
            # Only check imports from arkui_xts_selector internal modules
            internal = {
                imp.split(".")[-1] if imp.startswith("arkui_xts_selector") else None
                for imp in imports
                if imp.startswith("arkui_xts_selector")
            }
            internal.discard(None)
            bad = internal & forbidden
            if bad:
                violations.append(f"{modname} imports forbidden: {sorted(bad)}")
        if violations:
            self.fail(
                f"{package_name} import boundary violations:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )

    def test_model_does_not_import_forbidden(self) -> None:
        """model must not import cli/reporting/execution/indexing/resolving/graph/ranking."""
        self._check_package("arkui_xts_selector.model", _FORBIDDEN_FOR_MODEL)

    def test_graph_does_not_import_forbidden(self) -> None:
        """graph must not import cli/reporting/execution/indexing/resolving."""
        self._check_package("arkui_xts_selector.graph", _FORBIDDEN_FOR_GRAPH)

    def test_ranking_does_not_import_cli(self) -> None:
        """ranking must not import cli, if ranking package exists."""
        self._check_package("arkui_xts_selector.ranking_rules", _FORBIDDEN_FOR_RANKING)

    def test_reporting_does_not_import_indexing_or_resolving(self) -> None:
        """reporting must not import indexing or resolving internals, if reporting package exists."""
        self._check_package("arkui_xts_selector.report_human", _FORBIDDEN_FOR_REPORTING)

    def test_model_imports_only_standard_lib(self) -> None:
        """model modules should only import stdlib + model sibling modules."""
        if not _module_exists("arkui_xts_selector.model"):
            self.skipTest("model package does not exist yet")
        submodules = _collect_submodules("arkui_xts_selector.model")
        for modname in submodules:
            imports = _get_imports(modname)
            # Check that non-stdlib imports are only to model/ sibling modules
            for imp in imports:
                if imp.startswith("arkui_xts_selector"):
                    suffix = imp[len("arkui_xts_selector"):].lstrip(".")
                    # Allow: model.api, model.evidence, model.usage, etc.
                    # Also allow 'model' itself (import from . import X)
                    parts = suffix.split(".") if suffix else []
                    if parts and parts[0] not in ("model",):
                        self.fail(
                            f"{modname} imports non-model package module: {imp}"
                        )


if __name__ == "__main__":
    unittest.main()
