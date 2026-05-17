"""R6 regression: consumers_for_canonical is strict, member-name lookup is separate."""

from arkui_xts_selector.indexing.inverted_index import InvertedIndex, ConsumerEntry


def _make_consumer(project: str = "test_proj", line: int = 1) -> ConsumerEntry:
    return ConsumerEntry(
        project_path=project,
        file_path=f"/path/to/{project}.ets",
        line=line,
        usage_kind="component_construction",
        confidence="medium",
    )


def test_consumers_for_canonical_strict_exact_only():
    """consumers_for_canonical does NOT do substring/suffix fallback."""
    idx = InvertedIndex(
        by_api={
            "ButtonAttribute.role": [_make_consumer("buttonproj")],
            "CheckboxAttribute.role": [_make_consumer("checkproj")],
        }
    )
    # Exact key → returns matching consumers
    assert len(idx.consumers_for_canonical("ButtonAttribute.role")) == 1
    # Non-exact key (e.g. just "role") → returns nothing (no substring fallback)
    assert idx.consumers_for_canonical("role") == []
    assert idx.consumers_for_canonical("Attribute.role") == []


def test_consumers_for_member_name_returns_all_parents():
    """consumers_for_member_name without parent filter returns all matching members."""
    idx = InvertedIndex(
        by_api={
            "ButtonAttribute.role": [_make_consumer("buttonproj")],
            "CheckboxAttribute.role": [_make_consumer("checkproj")],
            "RadioAttribute.role": [_make_consumer("radioproj")],
        }
    )
    consumers = idx.consumers_for_member_name("role")
    projects = sorted(c.project_path for c in consumers)
    assert projects == ["buttonproj", "checkproj", "radioproj"]


def test_consumers_for_member_name_with_parent_filter():
    """parent_filter limits results to that parent's member."""
    idx = InvertedIndex(
        by_api={
            "ButtonAttribute.role": [_make_consumer("buttonproj")],
            "CheckboxAttribute.role": [_make_consumer("checkproj")],
        }
    )
    consumers = idx.consumers_for_member_name("role", parent_filter="ButtonAttribute")
    assert len(consumers) == 1
    assert consumers[0].project_path == "buttonproj"


def test_consumers_for_member_name_canonical_url_encoded_keys():
    """Works with canonical url-encoded keys: api:v1:...#Parent%23member."""
    idx = InvertedIndex(
        by_api={
            "api:v1:arkui:event_or_method:common#ButtonAttribute%23role": [
                _make_consumer("buttonproj")
            ],
            "api:v1:arkui:event_or_method:common#CheckboxAttribute%23role": [
                _make_consumer("checkproj")
            ],
        }
    )
    consumers = idx.consumers_for_member_name("role")
    assert len(consumers) == 2
    consumers_filtered = idx.consumers_for_member_name(
        "role", parent_filter="ButtonAttribute"
    )
    assert len(consumers_filtered) == 1
    assert consumers_filtered[0].project_path == "buttonproj"


def test_consumers_for_member_name_empty_when_no_match():
    idx = InvertedIndex(
        by_api={
            "ButtonAttribute.role": [_make_consumer()],
        }
    )
    assert idx.consumers_for_member_name("nonexistent") == []
    assert idx.consumers_for_member_name("role", parent_filter="UnknownAttribute") == []


def test_member_index_built_lazily():
    """_by_member_name is None initially, populated on first call."""
    idx = InvertedIndex(by_api={"X.foo": [_make_consumer()]})
    assert idx._by_member_name is None
    _ = idx.consumers_for_member_name("foo")
    assert idx._by_member_name is not None
