"""PX-07: Native typed targets.

Verifies that native interface files with known families produce
actual XTS targets when target_families mapping is provided.
"""


def test_native_resolver_returns_targets_with_mapping():
    """resolve_native_interface_targets returns targets when target_families provided."""
    from arkui_xts_selector.indexing.native_interface_resolver import (
        resolve_native_interface_targets,
    )

    targets = resolve_native_interface_targets(
        "frameworks/core/interfaces/native/implementation/button_modifier.cpp",
        target_families={"button": ["ace_ets_module_ui/ace_ets_module_button_static"]},
    )
    assert len(targets) == 1
    assert "button_static" in targets[0]


def test_native_resolver_returns_empty_without_mapping():
    """resolve_native_interface_targets returns empty list without target_families."""
    from arkui_xts_selector.indexing.native_interface_resolver import (
        resolve_native_interface_targets,
    )

    targets = resolve_native_interface_targets(
        "frameworks/core/interfaces/native/implementation/button_modifier.cpp",
    )
    assert targets == []


def test_native_resolver_unrelated_file():
    """Unrelated files return empty targets."""
    from arkui_xts_selector.indexing.native_interface_resolver import (
        resolve_native_interface_targets,
    )

    targets = resolve_native_interface_targets(
        "some/random/file.cpp",
        target_families={"button": ["ace_ets_module_ui/ace_ets_module_button_static"]},
    )
    assert targets == []


def test_native_resolver_accessor_pattern():
    """Native accessor files resolve to correct family targets."""
    from arkui_xts_selector.indexing.native_interface_resolver import (
        resolve_native_interface_targets,
    )

    targets = resolve_native_interface_targets(
        "frameworks/core/interfaces/native/implementation/text_accessor.cpp",
        target_families={"text": ["ace_ets_module_ui/ace_ets_module_text"]},
    )
    assert len(targets) == 1


def test_native_resolver_family_alias():
    """Family aliases (e.g. indexer->AlphabetIndexer) resolve correctly."""
    from arkui_xts_selector.indexing.native_interface_resolver import (
        resolve_native_interface_targets,
    )

    targets = resolve_native_interface_targets(
        "frameworks/core/interfaces/native/implementation/indexer_modifier.cpp",
        target_families={"indexer": ["ace_ets_module_ui/ace_ets_module_indexer"]},
    )
    assert len(targets) == 1
