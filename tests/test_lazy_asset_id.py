"""Opening a SQLite-backed project must not hash its song file (nw#108).

``asset_id`` is the Postgres tenant anchor and the media reference of new
annotations; deriving it SHA-256s the whole song. A host that opens a project's
stores on a hot path (reelee reads ``project-meta`` rows on every call that
targets a shared project) must not pay that on a backend that never uses it.
"""

from __future__ import annotations

import pytest

import lacing
import nw
from nw.graph import ProjectGraph, iter_all_annotations
from nw.graph_backend import iter_scope_stores, open_graph_store


@pytest.fixture
def project_with_song(tmp_path, monkeypatch):
    monkeypatch.delenv("NW_GRAPH_BACKEND", raising=False)
    song = tmp_path / "song.wav"
    song.write_bytes(b"not really audio" * 100)
    project = nw.Project.init(tmp_path / "p", title="t", song=song)
    project.storage.open_graph().close()  # the graph exists before hashing is forbidden
    return project


@pytest.fixture
def forbid_song_hash(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the song file was hashed")

    monkeypatch.setattr(lacing, "hash_file", boom)


def test_opening_stores_does_not_hash_the_song(project_with_song, forbid_song_hash):
    storage = project_with_song.storage
    with storage.open_stores() as stores:
        assert len(list(stores)) >= 1
    assert list(iter_all_annotations(storage.root)) is not None
    storage.open_graph().close()
    storage.open_graph_readonly().close()


def test_constructing_a_graph_does_not_hash_the_song(
    project_with_song, forbid_song_hash
):
    graph = ProjectGraph(project_with_song.root)
    list(graph.shots())


def test_asset_id_is_still_the_song_hash_when_asked(project_with_song):
    graph = ProjectGraph(project_with_song.root)
    assert graph.asset_id == lacing.hash_file(project_with_song.song_path())


def test_callable_asset_id_is_never_called_under_sqlite(tmp_path):
    def boom():
        raise AssertionError("called")

    store = open_graph_store(
        tmp_path / "project.annot.sqlite", asset_id=boom, env={}
    )
    store.close()
    (tmp_path / "project.annot.sqlite").exists()
    with iter_scope_stores(
        {"graph": tmp_path / "project.annot.sqlite"}, asset_id=boom, env={}
    ) as stores:
        assert len(list(stores)) == 1
