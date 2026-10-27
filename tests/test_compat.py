"""Tests for nw.compat: a plugin's keywords checked against the installed nw (nw#164)."""

from dataclasses import dataclass

import pytest

from nw import GenreOp, NwTooOldError, require_fields


def test_fields_the_class_takes_pass():
    require_fields(GenreOp, ["name", "fn", "invalidates"])
    require_fields(GenreOp, {"name": "x", "fn": print})  # a mapping's keys
    require_fields(GenreOp, [])


def test_a_missing_keyword_names_nw_the_class_the_keyword_and_the_fix():
    with pytest.raises(NwTooOldError) as err:
        require_fields(GenreOp, {"name": "x", "teleport": 1, "warp": 2})
    message = str(err.value)
    assert "nw's GenreOp" in message and "'teleport', 'warp'" in message
    assert message.endswith("upgrade nw")
    assert isinstance(err.value, ImportError)  # raised at a plugin's import time


def test_the_remedy_is_the_callers_to_name():
    with pytest.raises(NwTooOldError, match="install muvid's 'mcp' extra$"):
        require_fields(GenreOp, ["teleport"], remedy="install muvid's 'mcp' extra")


def test_one_string_is_a_caller_mistake_not_an_old_nw():
    with pytest.raises(TypeError, match="not one string"):
        require_fields(GenreOp, "invalidates")


def test_a_positional_only_parameter_is_not_a_keyword():
    class C:
        def __init__(self, a, /, b):
            pass

    require_fields(C, ["b"])
    with pytest.raises(NwTooOldError, match="takes no keyword 'a'"):
        require_fields(C, ["a"])


def test_a_constructor_taking_any_keyword_accepts_everything():
    class Open:
        def __init__(self, **kwargs):
            pass

    @dataclass
    class Closed:
        a: int = 0

    require_fields(Open, ["anything"])
    with pytest.raises(NwTooOldError, match="Closed takes no keyword 'b'"):
        require_fields(Closed, ["a", "b"])
