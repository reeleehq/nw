"""Tests for nw.plugins: a plugin's keywords checked against the installed nw (nw#164)."""

from dataclasses import dataclass

import pytest

import nw
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


def test_it_asks_the_class_not_a_version(monkeypatch):
    """An editable checkout records a stale version: the check must not care."""
    monkeypatch.setattr(nw, "__version__", "0.0.1", raising=False)
    require_fields(GenreOp, ["invalidates"])


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
