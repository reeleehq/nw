"""nw.testing.transforms: a result's written/reused_ids are checked against the graph (nw#234)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from nw.testing.transforms import recording_writes
from tests.test_fresh_equivalents import (  # noqa: F401 — `fal` is a fixture
    _Reusing,
    _plan,
    _project,
    _skeleton,
    fal,
)


def test_the_default_execute_is_honest_when_writing_and_when_reusing(tmp_path, fal):
    proj, (shot,) = _project(tmp_path)
    with recording_writes(proj) as writes:
        first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    writes.check(first)
    assert first.written and not first.reused_ids

    with recording_writes(proj) as writes:
        second = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    writes.check(second)
    assert second.reused_ids and not second.written


def test_an_override_returning_an_existing_node_as_written_is_caught(tmp_path, fal):
    """The case nw#215 made an obligation: an existing node returned without
    being reported in reused_ids reads as written, and the check says so."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    with recording_writes(proj) as writes:
        lying = replace(first, reused_ids=frozenset())  # returned again, unreported
    with pytest.raises(AssertionError, match="reported written, not written"):
        writes.check(lying)


def test_claiming_reuse_of_a_node_written_in_the_call_is_caught(tmp_path, fal):
    proj, (shot,) = _project(tmp_path)
    with recording_writes(proj) as writes:
        result = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    lying = replace(result, reused_ids=frozenset(a.id for a in result.annotations))
    with pytest.raises(AssertionError, match="reported reused, but written"):
        writes.check(lying)


def test_a_reused_id_must_be_among_the_annotations(tmp_path, fal):
    from uuid import uuid4

    proj, (shot,) = _project(tmp_path)
    with recording_writes(proj) as writes:
        result = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    with pytest.raises(AssertionError, match="not among result.annotations"):
        writes.check(replace(result, reused_ids=frozenset({uuid4()})))
