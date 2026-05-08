"""PX-04: Parent-filtered member lookup in consumer resolution.

Verifies that when an API name exists in multiple families, the parent filter
narrows consumer lookup to the correct family.
"""
import pytest


def test_consumers_for_member_name_uses_parent_filter():
    """consumers_for_member_name with parent_filter narrows results."""
    from arkui_xts_selector.indexing.inverted_index import InvertedIndex, ConsumerEntry

    idx = InvertedIndex(by_api={
        "api:v1:arkui.static:attribute:button#ButtonAttribute%23backgroundColor": [
            ConsumerEntry("arkui/button_test", "test.ets", 10, "chained_modifier", "strong"),
        ],
        "api:v1:arkui.static:attribute:text#TextAttribute%23backgroundColor": [
            ConsumerEntry("arkui/text_test", "test.ets", 10, "chained_modifier", "strong"),
        ],
    })

    # Without parent filter — should return both
    all_consumers = idx.consumers_for_member_name("backgroundColor")
    assert len(all_consumers) == 2

    # With parent filter for Button — should return only button consumer
    button_consumers = idx.consumers_for_member_name("backgroundColor", parent_filter="ButtonAttribute")
    assert len(button_consumers) == 1
    assert button_consumers[0].project_path == "arkui/button_test"

    # With parent filter for Text — should return only text consumer
    text_consumers = idx.consumers_for_member_name("backgroundColor", parent_filter="TextAttribute")
    assert len(text_consumers) == 1
    assert text_consumers[0].project_path == "arkui/text_test"


def test_provenance_set_correctly_per_lookup_level():
    """Verify provenance is set correctly per consumer lookup level."""
    # This tests the pr_resolver behavior indirectly through the provenance
    # tracking added in PX-01.
    # The main assertion is in test_precision_contract_canonical_gate.py
    # Here we just verify the inverted index behavior.
    from arkui_xts_selector.indexing.inverted_index import InvertedIndex, ConsumerEntry

    idx = InvertedIndex(by_api={
        "api:v1:arkui.static:attribute:button#ButtonAttribute%23role": [
            ConsumerEntry("arkui/button_role_test", "test.ets", 10, "attribute_method", "strong"),
        ],
    })

    # Exact canonical hit
    exact = idx.consumers_for_canonical("api:v1:arkui.static:attribute:button#ButtonAttribute%23role")
    assert len(exact) == 1

    # Member name hit with parent
    member = idx.consumers_for_member_name("role", parent_filter="ButtonAttribute")
    assert len(member) == 1

    # No hit for wrong parent
    wrong = idx.consumers_for_member_name("role", parent_filter="TextAttribute")
    assert len(wrong) == 0
