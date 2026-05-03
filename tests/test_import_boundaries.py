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
    """Get the set of full dotted import paths made by a module.

    This inspects the AST to find import statements without executing the module.
    Returns full dotted paths (e.g. ``"arkui_xts_selector.ranking.buckets"``)
    so callers can extract any segment they need.
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
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def _get_imports_from_path(filepath: str | Path) -> set[str]:
    """Same as _get_imports but takes a file path instead of module name."""
    import ast

    try:
        source = Path(filepath).read_text(encoding="utf-8")
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
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


_PREFIX = "arkui_xts_selector."


def _project_top_segments(imports: set[str]) -> set[str]:
    """Extract the first segment after ``arkui_xts_selector.`` from each import."""
    segments: set[str] = set()
    for imp in imports:
        if imp.startswith(_PREFIX):
            tail = imp[len(_PREFIX):]
            top = tail.split(".")[0]
            if top:
                segments.add(top)
    return segments


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
    "ranking", "ranking_rules", "source_profile", "changed_files",
    "git_host", "progress", "utility_modes", "benchmark",
    "consumer_semantics", "api_lineage", "api_surface",
    "tree_sitter_parsers", "symbol_tracing", "mapping_config",
}

_FORBIDDEN_FOR_RANKING = {
    "cli", "graph", "report_human", "report_json", "execution",
    "project_index", "scoring", "signal_inference",
}

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
            bad = _project_top_segments(imports) & forbidden
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

    def test_ranking_package_does_not_import_cli(self) -> None:
        """ranking package must not import cli or graph internals."""
        self._check_package("arkui_xts_selector.ranking", _FORBIDDEN_FOR_RANKING)

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
            segments = _project_top_segments(imports)
            non_model = segments - {"model"}
            if non_model:
                self.fail(
                    f"{modname} imports non-model package modules: {sorted(non_model)}"
                )

    def test_framework_catches_known_violation(self) -> None:
        """Sanity: feed the framework a synthetic violation and prove it
        detects it. Without this test we can't trust the boundary tests."""
        import tempfile
        import textwrap

        # Simulate a file that imports from cli (which is forbidden for
        # both model and graph).
        src = textwrap.dedent("""\
            from arkui_xts_selector.cli import main_entry
        """)
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False,
        ) as f:
            f.write(src)
            path = f.name

        try:
            imports = _get_imports_from_path(path)
            segments = _project_top_segments(imports)
            self.assertIn(
                "cli", segments,
                f"Framework failed to detect 'cli' import; got segments: {segments}",
            )
            # Also verify the violation would be caught by _check_package
            bad = segments & _FORBIDDEN_FOR_MODEL
            self.assertIn(
                "cli", bad,
                f"Framework failed to flag 'cli' as forbidden for model; "
                f"intersection: {bad}",
            )
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
