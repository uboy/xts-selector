"""Validation lane smoke tests — check tooling is correctly configured (Phase G)."""
import pathlib
import subprocess

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
MAKEFILE = PROJECT_ROOT / "Makefile"
GITIGNORE = PROJECT_ROOT / ".gitignore"
AGENT_RULES = PROJECT_ROOT / "docs" / "AGENT-RULES.md"
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def makefile_text():
    return MAKEFILE.read_text()


def gitignore_text():
    return GITIGNORE.read_text() if GITIGNORE.exists() else ""


def test_makefile_has_validate_universal_impact():
    assert "validate-universal-impact" in makefile_text()


def test_makefile_has_validate_pr_benchmark():
    assert "validate-pr-benchmark" in makefile_text()


def test_makefile_has_validate_all_local():
    assert "validate-all-local" in makefile_text()


def test_makefile_has_validate_real_env():
    assert "validate-real-env" in makefile_text()


def test_makefile_has_validate_nightly():
    assert "validate-nightly" in makefile_text()


def test_gitignore_excludes_nightly_reports():
    gi = gitignore_text()
    assert "reports/nightly" in gi or "reports/" in gi


def test_gitignore_excludes_pytest_cache():
    assert ".pytest_cache" in gitignore_text()


def test_gitignore_excludes_selected_tests():
    assert "selected_tests.json" in gitignore_text()


def test_agent_rules_exists():
    assert AGENT_RULES.exists()


def test_ci_workflow_exists():
    assert CI_WORKFLOW.exists(), "Expected .github/workflows/ci.yml to exist"


def test_validate_fast_passes():
    result = subprocess.run(
        ["make", "validate-fast"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"validate-fast failed:\n{result.stdout}\n{result.stderr}"
    )


def test_validate_graph_passes():
    result = subprocess.run(
        ["make", "validate-graph"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"validate-graph failed:\n{result.stdout}\n{result.stderr}"
    )
