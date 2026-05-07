"""Tests for oracle_validator module."""
from __future__ import annotations

from arkui_xts_selector.validation.oracle_validator import (
    OracleValidationResult,
    validate_oracle_output,
)


class TestOracleValidator:
    def test_passes_with_high_precision(self):
        mappings = [{"confidence": "high"}] * 8 + [{"confidence": "medium"}] * 2
        result = validate_oracle_output(mappings)
        assert result.passes
        assert result.high_precision == 0.8
        assert result.total_changes == 10

    def test_fails_with_low_precision(self):
        mappings = [{"confidence": "high"}] * 5 + [{"confidence": "unmapped"}] * 5
        result = validate_oracle_output(mappings)
        assert not result.passes
        assert result.high_precision == 0.5

    def test_fails_with_empty_input(self):
        result = validate_oracle_output([])
        assert not result.passes
        assert result.total_changes == 0

    def test_all_high(self):
        mappings = [{"confidence": "high"}] * 10
        result = validate_oracle_output(mappings)
        assert result.passes
        assert result.high_precision == 1.0

    def test_all_unmapped(self):
        mappings = [{"confidence": "unmapped"}] * 10
        result = validate_oracle_output(mappings)
        assert not result.passes
        assert result.high_precision == 0.0

    def test_counts_by_confidence(self):
        mappings = [
            {"confidence": "high"},
            {"confidence": "high"},
            {"confidence": "medium"},
            {"confidence": "unmapped"},
        ]
        result = validate_oracle_output(mappings)
        assert result.high_count == 2
        assert result.medium_count == 1
        assert result.unmapped_count == 1
