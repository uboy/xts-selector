"""Tests for C++ macro expansion pattern config.

Tests macro pattern loading, matching, and synthetic method generation.
"""

from __future__ import annotations

import json
from pathlib import Path

from arkui_xts_selector.indexing.cpp_macro_patterns import (
    MacroPattern,
    generate_synthetic_method_name,
    load_macro_patterns,
    match_macro_in_source,
)


def _write_config(tmp: Path, patterns: list[dict]) -> Path:
    """Helper to write a temporary config file."""
    p = tmp / "macro_patterns.json"
    p.write_text(
        json.dumps({"schema_version": "v1", "patterns": patterns}), encoding="utf-8"
    )
    return p


class TestLoadMacroPatterns:
    """Test config file loading."""

    def test_loads_valid_config(self, tmp_path: Path) -> None:
        p = _write_config(
            tmp_path,
            [
                {
                    "macro": "ACE_DEFINE_PROPERTY",
                    "synthetic_method_pattern": "Set{1}",
                    "confidence": "medium",
                },
            ],
        )
        patterns = load_macro_patterns(p)
        assert len(patterns) == 1
        assert patterns[0].macro == "ACE_DEFINE_PROPERTY"
        assert patterns[0].synthetic_method_pattern == "Set{1}"
        assert patterns[0].confidence == "medium"

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        assert load_macro_patterns(tmp_path / "nonexistent.json") == []

    def test_empty_config_returns_empty_list(self, tmp_path: Path) -> None:
        p = _write_config(tmp_path, [])
        assert load_macro_patterns(p) == []

    def test_defaults_confidence_to_medium(self, tmp_path: Path) -> None:
        p = _write_config(
            tmp_path,
            [
                {"macro": "SOME_MACRO", "synthetic_method_pattern": None},
            ],
        )
        patterns = load_macro_patterns(p)
        assert len(patterns) == 1
        assert patterns[0].confidence == "medium"

    def test_handles_null_synthetic_method_pattern(self, tmp_path: Path) -> None:
        p = _write_config(
            tmp_path,
            [
                {
                    "macro": "NO_METHOD_MACRO",
                    "synthetic_method_pattern": None,
                    "confidence": "weak",
                },
            ],
        )
        patterns = load_macro_patterns(p)
        assert len(patterns) == 1
        assert patterns[0].synthetic_method_pattern is None
        assert patterns[0].confidence == "weak"


class TestMatchMacroInSource:
    """Test macro invocation matching in source code."""

    def test_matches_simple_macro(self) -> None:
        patterns = [
            MacroPattern(
                macro="ACE_DEFINE_PROPERTY",
                synthetic_method_pattern="Set{1}",
                confidence="medium",
            )
        ]
        source = "ACE_DEFINE_PROPERTY(Button, role)"
        match = match_macro_in_source(source, patterns)
        assert match is not None
        assert match[0] == patterns[0]
        assert match[1] == "role"

    def test_matches_macro_with_multiple_args(self) -> None:
        patterns = [
            MacroPattern(
                macro="ACE_DEFINE_PROPERTY",
                synthetic_method_pattern="Set{1}",
                confidence="medium",
            )
        ]
        source = "ACE_DEFINE_PROPERTY(button_model, enabled, false)"
        match = match_macro_in_source(source, patterns)
        assert match is not None
        assert match[0] == patterns[0]
        assert match[1] == "enabled"

    def test_case_insensitive_matching(self) -> None:
        patterns = [
            MacroPattern(
                macro="ACE_DEFINE_PROPERTY",
                synthetic_method_pattern="Set{1}",
                confidence="medium",
            )
        ]
        assert (
            match_macro_in_source("ace_define_property(Button, role)", patterns)
            is not None
        )
        assert (
            match_macro_in_source("Ace_Define_Property(Button, role)", patterns)
            is not None
        )

    def test_no_match_returns_none(self) -> None:
        patterns = [
            MacroPattern(
                macro="ACE_DEFINE_PROPERTY",
                synthetic_method_pattern="Set{1}",
                confidence="medium",
            )
        ]
        assert match_macro_in_source("SOME_OTHER_MACRO(Button, role)", patterns) is None

    def test_matches_multiline_macro(self) -> None:
        patterns = [
            MacroPattern(
                macro="ACE_DEFINE_PROPERTY",
                synthetic_method_pattern="Set{1}",
                confidence="medium",
            )
        ]
        source = """ACE_DEFINE_PROPERTY(
            Button,
            role
        )"""
        match = match_macro_in_source(source, patterns)
        assert match is not None
        assert match[0] == patterns[0]

    def test_multiple_patterns(self) -> None:
        patterns = [
            MacroPattern(
                macro="ACE_DEFINE_PROPERTY",
                synthetic_method_pattern="Set{1}",
                confidence="medium",
            ),
            MacroPattern(
                macro="ACE_EXPORT_MODULE",
                synthetic_method_pattern=None,
                confidence="weak",
            ),
        ]
        source = "ACE_DEFINE_PROPERTY(Button, role)"
        match = match_macro_in_source(source, patterns)
        assert match is not None
        assert match[0].macro == "ACE_DEFINE_PROPERTY"


class TestGenerateSyntheticMethodName:
    """Test synthetic method name generation."""

    def test_simple_placeholder(self) -> None:
        pattern = "Set{1}"
        args = ["role"]
        result = generate_synthetic_method_name(pattern, args)
        assert result == "SetRole"

    def test_multiple_placeholders(self) -> None:
        pattern = "{1}_{2}"
        args = ["get", "Role"]
        result = generate_synthetic_method_name(pattern, args)
        assert result == "get_Role"

    def test_missing_arg_returns_none(self) -> None:
        pattern = "Set{2}"
        args = ["role"]
        result = generate_synthetic_method_name(pattern, args)
        assert result is None

    def test_null_pattern_returns_none(self) -> None:
        pattern = None
        args = ["role"]
        result = generate_synthetic_method_name(pattern, args)
        assert result is None

    def test_capitalizes_first_letter(self) -> None:
        pattern = "{1}"
        args = ["role"]
        result = generate_synthetic_method_name(pattern, args)
        assert result == "Role"

    def test_preserves_existing_capitalization(self) -> None:
        pattern = "{1}"
        args = ["Role"]
        result = generate_synthetic_method_name(pattern, args)
        assert result == "Role"

    def test_empty_pattern_returns_none(self) -> None:
        pattern = ""
        args = ["role"]
        result = generate_synthetic_method_name(pattern, args)
        assert result is None


class TestMacroPatternDataclass:
    """Test MacroPattern dataclass."""

    def test_frozen_dataclass(self) -> None:
        pattern = MacroPattern(
            macro="TEST_MACRO", synthetic_method_pattern="Set{1}", confidence="medium"
        )
        assert pattern.macro == "TEST_MACRO"
        assert pattern.synthetic_method_pattern == "Set{1}"
        assert pattern.confidence == "medium"

    def test_to_dict(self) -> None:
        pattern = MacroPattern(
            macro="TEST_MACRO", synthetic_method_pattern="Set{1}", confidence="medium"
        )
        d = pattern.to_dict()
        assert d["macro"] == "TEST_MACRO"
        assert d["synthetic_method_pattern"] == "Set{1}"
        assert d["confidence"] == "medium"

    def test_from_dict(self) -> None:
        d = {
            "macro": "TEST_MACRO",
            "synthetic_method_pattern": "Set{1}",
            "confidence": "medium",
        }
        pattern = MacroPattern.from_dict(d)
        assert pattern.macro == "TEST_MACRO"
        assert pattern.synthetic_method_pattern == "Set{1}"
        assert pattern.confidence == "medium"

    def test_from_dict_defaults(self) -> None:
        d = {"macro": "TEST_MACRO", "synthetic_method_pattern": None}
        pattern = MacroPattern.from_dict(d)
        assert pattern.macro == "TEST_MACRO"
        assert pattern.synthetic_method_pattern is None
        assert pattern.confidence == "medium"  # default

    def test_roundtrip(self) -> None:
        original = MacroPattern(
            macro="TEST_MACRO", synthetic_method_pattern="Set{1}", confidence="weak"
        )
        d = original.to_dict()
        restored = MacroPattern.from_dict(d)
        assert restored.macro == original.macro
        assert restored.synthetic_method_pattern == original.synthetic_method_pattern
        assert restored.confidence == original.confidence
