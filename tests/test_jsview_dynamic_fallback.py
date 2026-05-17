"""Tests for jsview_dynamic Get/Set/JS prefix fallback."""

from __future__ import annotations

from arkui_xts_selector.indexing.cpp_parser import CppMethod
from arkui_xts_selector.indexing.source_to_api import _map_jsview_dynamic


def _map(method_name: str, family: str = "button") -> dict | None:
    method = CppMethod(name=method_name)
    result = _map_jsview_dynamic(
        method_name,
        f"{family}::{method_name}",
        "jsview_dynamic",
        f"view/{family}.cpp",
        family,
    )
    if result is None:
        return None
    return {
        "api_public_name": result.api_public_name,
        "confidence": result.confidence,
        "file_role": result.file_role,
    }


def test_create_still_works():
    r = _map("Create")
    assert r is not None
    assert r["api_public_name"] == "create"
    assert r["confidence"] == "strong"


def test_js_prefix_still_works():
    r = _map("JsEnabled")
    assert r is not None
    assert r["api_public_name"] == "enabled"
    assert r["confidence"] == "strong"


def test_set_prefix_fallback():
    r = _map("SetMaxLines")
    assert r is not None
    assert r["api_public_name"] == "maxLines"
    assert r["confidence"] == "medium"


def test_get_prefix_fallback():
    r = _map("GetOptions")
    assert r is not None
    assert r["api_public_name"] == "options"
    assert r["confidence"] == "medium"


def test_js_uppercase_prefix_fallback():
    r = _map("JSSpecialMode")
    assert r is not None
    assert r["api_public_name"] == "specialMode"
    assert r["confidence"] == "medium"


def test_unrelated_returns_none():
    r = _map("Initialize")
    assert r is None
