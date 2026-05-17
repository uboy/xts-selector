"""Tests for *Impl suffix stripping in canonical resolution."""

from __future__ import annotations

from arkui_xts_selector.indexing.source_to_api import _strip_impl_suffix


def test_basic_strip():
    assert _strip_impl_suffix("fontVariationsImpl") == "fontVariations"


def test_image_options_impl():
    assert _strip_impl_suffix("imageOptionsImpl") == "imageOptions"


def test_no_impl_suffix():
    assert _strip_impl_suffix("fontVariations") is None


def test_empty_after_strip():
    assert _strip_impl_suffix("Impl") is None


def test_uppercase_start_after_strip():
    """If stripping Impl yields a capital-start name, skip it."""
    assert _strip_impl_suffix("SetImpl") is None


def test_compound_camelcase():
    assert _strip_impl_suffix("animationOptionsImpl") == "animationOptions"
