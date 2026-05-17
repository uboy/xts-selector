"""Tests for target_ranking bucket model."""

from __future__ import annotations

from arkui_xts_selector.target_ranking import (
    BUCKET_CAPS,
    rank_targets,
    _classify_bucket,
)


def _entry(
    consumer_projects: tuple[str, ...] = ("proj_a",),
    canonical_apis: tuple[str, ...] = (),
    reasons: tuple[dict, ...] = (),
    impact_candidates: tuple[dict, ...] = (),
    changed_file: str = "test.cpp",
) -> dict:
    return {
        "consumer_projects": consumer_projects,
        "affected_apis": canonical_apis or (),
        "canonical_affected_apis": canonical_apis,
        "selection_reasons": reasons,
        "impact_candidates": impact_candidates,
        "changed_file": changed_file,
    }


class TestClassifyBucket:
    def test_canonical_direct_sdk_is_must_run(self):
        assert _classify_bucket(True, True, True) == "must_run"

    def test_no_signals_is_fallback(self):
        assert _classify_bucket(False, False, False) == "fallback"

    def test_canonical_only_is_recommended(self):
        assert _classify_bucket(True, False, False) == "recommended"

    def test_direct_only_is_recommended(self):
        assert _classify_bucket(False, True, False) == "recommended"

    def test_sdk_only_is_recommended(self):
        assert _classify_bucket(False, False, True) == "recommended"


class TestRankTargets:
    def test_empty_entries(self):
        result = rank_targets([])
        assert result.must_run == []
        assert result.recommended == []
        assert result.fallback == []

    def test_single_must_run(self):
        entries = [
            _entry(canonical_apis=("Button/role",), reasons=({"confidence": "strong"},))
        ]
        result = rank_targets(entries)
        assert len(result.must_run) == 1
        assert result.must_run[0].project_id == "proj_a"

    def test_single_fallback(self):
        entries = [_entry(reasons=({"confidence": "weak"},))]
        result = rank_targets(entries)
        assert len(result.fallback) == 1

    def test_multiple_targets_different_buckets(self):
        entries = [
            _entry(
                consumer_projects=("proj_must",),
                canonical_apis=("Api",),
                reasons=({"confidence": "strong"},),
            ),
            _entry(
                consumer_projects=("proj_rec",), reasons=({"confidence": "strong"},)
            ),
            _entry(consumer_projects=("proj_fall",), reasons=()),
        ]
        result = rank_targets(entries)
        assert len(result.must_run) == 1
        assert len(result.recommended) >= 1
        assert len(result.fallback) >= 1

    def test_bucket_cap_applied(self):
        entries = [
            _entry(consumer_projects=(f"proj_{i}",), reasons=({"confidence": "weak"},))
            for i in range(50)
        ]
        result = rank_targets(entries)
        assert len(result.fallback) <= BUCKET_CAPS["fallback"]
        assert result.dropped_count > 0

    def test_must_run_no_cap(self):
        entries = [
            _entry(
                consumer_projects=(f"proj_{i}",),
                canonical_apis=(f"Api{i}",),
                reasons=({"confidence": "strong"},),
            )
            for i in range(50)
        ]
        result = rank_targets(entries)
        assert len(result.must_run) == 50

    def test_duplicate_project_takes_best_bucket(self):
        entries = [
            _entry(consumer_projects=("proj_a",), reasons=({"confidence": "weak"},)),
            _entry(
                consumer_projects=("proj_a",),
                canonical_apis=("Api",),
                reasons=({"confidence": "strong"},),
            ),
        ]
        result = rank_targets(entries)
        assert len(result.must_run) == 1
        assert result.must_run[0].project_id == "proj_a"

    def test_source_files_tracked(self):
        entries = [_entry(consumer_projects=("proj_a",), changed_file="button.cpp")]
        result = rank_targets(entries)
        assert result.all_targets[0].source_files == ("button.cpp",)

    def test_to_dict(self):
        entries = [_entry(canonical_apis=("Api",), reasons=({"confidence": "strong"},))]
        d = rank_targets(entries).to_dict()
        assert "must_run" in d
        assert "dropped_count" in d
        assert d["total"] == 1

    def test_scoring_sorts_descending(self):
        entries = [
            _entry(consumer_projects=("proj_1",), reasons=({"confidence": "weak"},)),
            _entry(
                consumer_projects=("proj_2",),
                canonical_apis=("Api1", "Api2"),
                reasons=({"confidence": "strong"},),
            ),
        ]
        result = rank_targets(entries)
        assert result.must_run[0].project_id == "proj_2"

    def test_all_targets_property(self):
        entries = [
            _entry(
                consumer_projects=("must_p",),
                canonical_apis=("A",),
                reasons=({"confidence": "strong"},),
            ),
            _entry(consumer_projects=("fall_p",), reasons=()),
        ]
        result = rank_targets(entries)
        assert len(result.all_targets) == 2


class TestDroppedTargets:
    def test_dropped_targets_populated(self):
        entries = [
            {
                "changed_file": "x.cpp",
                "consumer_projects": [f"target_{i}" for i in range(50)],
                "affected_apis": ["api"],
                "canonical_affected_apis": [],
                "selection_reasons": [],
                "impact_candidates": [],
            }
        ]
        result = rank_targets(entries)
        # 50 targets, all fallback (no canonical) → fallback cap=30, so 20 dropped
        assert result.dropped_count == 20
        assert len(result.dropped) == 20

    def test_dropped_to_dict_includes_metadata(self):
        entries = [
            {
                "changed_file": "x.cpp",
                "consumer_projects": [f"t{i}" for i in range(45)],
                "affected_apis": [],
                "canonical_affected_apis": [],
                "selection_reasons": [],
                "impact_candidates": [],
            }
        ]
        d = rank_targets(entries).to_dict()
        assert "dropped" in d
        assert isinstance(d["dropped"], list)
        assert all("project_id" in item for item in d["dropped"])

    def test_no_drops_under_cap(self):
        entries = [
            {
                "changed_file": "x.cpp",
                "consumer_projects": ["t1", "t2"],
                "affected_apis": [],
                "canonical_affected_apis": [],
                "selection_reasons": [],
                "impact_candidates": [],
            }
        ]
        result = rank_targets(entries)
        assert result.dropped_count == 0
        assert len(result.dropped) == 0
