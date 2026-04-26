"""
Validate all canonical corpus fixtures in tests/fixtures/canonical_corpus/.

These are unit tests that do NOT require a workspace — they only check
that the JSON fixtures are structurally correct and internally consistent.

Run:
    python3 -m unittest tests.test_benchmark_corpus_validation -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CORPUS_DIR = FIXTURES / "canonical_corpus"

REQUIRED_FIELDS = {
    "family",
    "input_changed_files",
    "expected_surface",
    "expected_abstention",
    "precision_budget",
}

PRECISION_BUDGET_FIELDS = {
    "max_required_count",
    "max_top5_unrelated_noise",
}


def _load_fixture(name: str) -> dict:
    path = CORPUS_DIR / name
    self = unittest.TestCase()
    self.assertTrue(path.exists(), f"Fixture {name!r} does not exist at {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


class CorpusFixtureValidationTests(unittest.TestCase):
    """Structural validation of all canonical corpus JSON fixtures."""

    def _load_all(self) -> list[tuple[str, dict]]:
        results: list[tuple[str, dict]] = []
        for path in sorted(CORPUS_DIR.glob("*.json")):
            with path.open(encoding="utf-8") as fh:
                results.append((path.stem, json.load(fh)))
        return results

    def test_at_least_five_fixture_files(self) -> None:
        """We should have fixtures for all 5 canonical families + negatives."""
        fixtures = self._load_all()
        names = {stem for stem, _ in fixtures}
        self.assertGreaterEqual(
            len(fixtures),
            5,
            f"Expected >= 5 fixtures, found {len(fixtures)}: {sorted(names)}",
        )

    def test_button_fixture_present(self) -> None:
        data = _load_fixture("button_changed_file.json")
        self.assertEqual(data["family"], "button")

    def test_menu_item_fixture_present(self) -> None:
        data = _load_fixture("menu_item_changed_file.json")
        self.assertEqual(data["family"], "menu")

    def test_slider_fixture_present(self) -> None:
        data = _load_fixture("slider_changed_file.json")
        self.assertEqual(data["family"], "slider")

    def test_navigation_fixture_present(self) -> None:
        data = _load_fixture("navigation_changed_file.json")
        self.assertEqual(data["family"], "navigation")

    def test_content_modifier_fixture_present(self) -> None:
        data = _load_fixture("content_modifier_changed_file.json")
        self.assertEqual(data["family"], "content_modifier")

    def test_negative_fixture_present(self) -> None:
        data = _load_fixture("negative_broad_token.json")
        self.assertEqual(data["family"], "negative_broad")

    def test_pr83683_fixture_present(self) -> None:
        data = _load_fixture("pr83683_reference.json")
        self.assertEqual(data["family"], "pr83683")

    def test_all_fixtures_have_required_fields(self) -> None:
        """Every fixture must have the core schema fields."""
        for stem, data in self._load_all():
            for field in REQUIRED_FIELDS:
                self.assertIn(
                    field,
                    data,
                    f"{stem}: missing required field {field!r}",
                )

    def test_all_fixtures_have_input_changed_files_as_list(self) -> None:
        for stem, data in self._load_all():
            files = data["input_changed_files"]
            self.assertIsInstance(
                files,
                list,
                f"{stem}: input_changed_files must be a list",
            )
            self.assertGreaterEqual(
                len(files),
                1,
                f"{stem}: input_changed_files must not be empty",
            )

    def test_all_fixtures_have_precision_budget(self) -> None:
        for stem, data in self._load_all():
            budget = data["precision_budget"]
            self.assertIsInstance(
                budget,
                dict,
                f"{stem}: precision_budget must be a dict",
            )
            for field in PRECISION_BUDGET_FIELDS:
                self.assertIn(
                    field,
                    budget,
                    f"{stem}: precision_budget missing {field!r}",
                )
                self.assertIsInstance(
                    budget[field],
                    int,
                    f"{stem}: precision_budget.{field} must be an int",
                )
                self.assertGreaterEqual(
                    budget[field],
                    0,
                    f"{stem}: precision_budget.{field} must be >= 0",
                )

    def test_button_precision_budget_reasonable(self) -> None:
        data = _load_fixture("button_changed_file.json")
        budget = data["precision_budget"]
        self.assertLessEqual(
            budget["max_required_count"],
            200,
            "Button budget too loose",
        )
        self.assertEqual(
            budget["max_top5_unrelated_noise"],
            0,
            "Button must not have noise in top-5",
        )

    def test_negative_fixture_abstention_expected(self) -> None:
        data = _load_fixture("negative_broad_token.json")
        self.assertTrue(
            data["expected_abstention"],
            "Negative broad token fixture must expect abstention",
        )

    def test_all_fixtures_have_expected_surface(self) -> None:
        for stem, data in self._load_all():
            surface = data.get("expected_surface")
            # surface can be None for negative cases
            if surface is not None:
                self.assertIn(
                    surface,
                    {"static", "dynamic", "common"},
                    f"{stem}: invalid expected_surface {surface!r}",
                )

    def test_must_have_sources_exist(self) -> None:
        """must_have_source references must point to existing files."""
        positive_fixtures = [
            name for name, data in self._load_all()
            if data.get("expected_abstention") is not True
        ]
        for stem in positive_fixtures:
            data = _load_fixture(f"{stem}.json")
            source = data.get("must_have_source")
            if source:
                # must_have_source is a relative path from project root
                path = Path(__file__).resolve().parents[1] / source
                self.assertTrue(
                    path.exists(),
                    f"{stem}: must_have_source {source!r} not found at {path}",
                )


class LineageNotesValidationTests(unittest.TestCase):
    """Validate docs/canonical_lineage_notes.md if it exists."""

    def test_lineage_notes_file_exists(self) -> None:
        notes_path = Path(__file__).resolve().parents[1] / "docs" / "canonical_lineage_notes.md"
        if not notes_path.exists():
            self.skipTest("canonical_lineage_notes.md does not exist yet")
        content = notes_path.read_text(encoding="utf-8")
        self.assertGreater(
            len(content),
            100,
            "canonical_lineage_notes.md seems too short to contain useful data",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
