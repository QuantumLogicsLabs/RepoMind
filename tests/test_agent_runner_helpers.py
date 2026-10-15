"""Unit tests for the pure helpers in tools/agent_runner.py."""

from tools.agent_runner import _line_retention, _normalise_changes


def test_normalise_changes_accepts_list_of_dicts():
    changes = [{"filename": "a.py", "updated_content": "x"}]
    assert _normalise_changes(changes) == changes


def test_normalise_changes_wraps_single_dict():
    change = {"filename": "a.py", "updated_content": "x"}
    assert _normalise_changes(change) == [change]


def test_normalise_changes_parses_json_strings():
    raw = ['{"filename": "a.py", "updated_content": "x"}', "not json"]
    assert _normalise_changes(raw) == [{"filename": "a.py", "updated_content": "x"}]


def test_normalise_changes_drops_garbage():
    assert _normalise_changes(None) == []
    assert _normalise_changes(42) == []
    assert _normalise_changes([1, None]) == []


def test_line_retention_full_when_content_kept():
    old = "# Title\n\nSome description\n"
    assert _line_retention(old, old + "\n## New section\n") == 1.0


def test_line_retention_zero_when_content_replaced():
    old = "# PolyLearningFoundation-Test\nSandbox for testing\n"
    assert _line_retention(old, "# Project Title\nA brief description\n") == 0.0


def test_line_retention_empty_old_file_is_fully_retained():
    assert _line_retention("", "anything") == 1.0
    assert _line_retention("\n  \n", "anything") == 1.0
