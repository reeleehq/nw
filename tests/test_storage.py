"""The project-storage seam (nw#101): a project's graph and documents can live
in mappings its genre owns, and every nw surface follows them there.

The pair that matters: a project on a :class:`nw.MappingStorage` writes nothing
of nw's under its folder, *and* still gets nw's whole behaviour (graph,
freshness, reopening by path through a registered resolver). The default
folder layout is pinned unchanged alongside.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

import nw
from lacing import (
    Annotation,
    MediaRef,
    MemoryStore,
    Provenance,
    RationalTime,
    TimeInterval,
)
from nw.bodies import SectionBodyV1
from nw.storage import project_storages


def _memory_factory():
    """A store factory over ``MemoryStore`` that persists per mapping object.

    Stands in for ``lacing.store.MappingStore`` (which persists *into* the
    mapping) so this suite pins nw's side of the seam on any lacing.
    """
    stores: dict[int, MemoryStore] = {}

    def factory(mapping):
        return stores.setdefault(id(mapping), MemoryStore())

    return factory


def _mapping_storage(root: Path, **kw) -> nw.MappingStorage:
    return nw.MappingStorage(
        root=root, graph={}, docs={}, store_factory=_memory_factory(), **kw
    )


def _iv(a: float, b: float) -> TimeInterval:
    return TimeInterval.from_seconds(a, b)


def _derived(proj, parent_id) -> Annotation:
    ann = Annotation(
        id=uuid4(),
        tier="render-result",
        reference=MediaRef(asset_id=proj.graph.asset_id, interval=_iv(0, 0)),
        body={"url": "x"},
        body_schema_uri="annot://schema/render-result/v1",
        provenance=Provenance(
            was_generated_by="transform:test@1",
            was_attributed_to="agent:test",
            was_derived_from=[parent_id],
            generated_at_time=RationalTime.now(),
            activity="derive",
        ),
    )
    proj.graph.add_annotation(ann)
    return ann


def test_mapping_storage_project_writes_nothing_of_nws_into_its_folder(tmp_path):
    (tmp_path / "an.toml").write_text("# the owning app's own file\n")
    storage = _mapping_storage(tmp_path)

    proj = nw.Project.init(tmp_path, title="t", storage=storage)
    proj.graph.upsert_section(
        SectionBodyV1(section_id="a", label="A"), interval=_iv(0, 1)
    )

    assert sorted(p.name for p in tmp_path.iterdir()) == ["an.toml"]
    assert storage.docs["project.json"]["title"] == "t"
    assert [s.body.section_id for s in proj.graph.sections()] == ["a"]


def test_freshness_follows_the_storage(tmp_path):
    storage = _mapping_storage(tmp_path)
    proj = nw.Project.init(tmp_path, storage=storage)
    sec = proj.graph.upsert_section(
        SectionBodyV1(section_id="a", label="A"), interval=_iv(0, 1)
    )
    child = _derived(proj, sec)

    assert [
        v.annotation.id for v in nw.stale_verdicts(storage, sec) if v.is_stale
    ] == []
    proj.graph.upsert_section(
        SectionBodyV1(section_id="a", label="edited"), interval=_iv(0, 1)
    )
    assert [a.id for a in nw.stale_after(storage, sec)] == [child.id]
    assert [a.id for a in nw.stale_after(proj, sec)] == [child.id]


def test_a_registered_resolver_makes_a_path_open_the_genres_storage(tmp_path):
    storage = _mapping_storage(tmp_path)
    nw.Project.init(tmp_path, title="by path", storage=storage)

    def resolver(root: Path):
        return storage if root == tmp_path.resolve() else None

    nw.register_project_storage("test_resolver", resolver)
    try:
        proj = nw.Project(tmp_path)
        assert proj.storage is storage
        assert proj.read_spec().title == "by path"
        assert nw.as_project_storage(str(tmp_path)) is storage
    finally:
        del project_storages["test_resolver"]
    assert isinstance(nw.as_project_storage(tmp_path), nw.FolderStorage)


def test_mapping_storage_may_share_a_non_empty_folder_but_not_an_nw_project(tmp_path):
    (tmp_path / "scene.md").write_text("x")
    storage = _mapping_storage(tmp_path)
    nw.Project.init(tmp_path, storage=storage)
    with pytest.raises(FileExistsError):
        nw.Project.init(tmp_path, storage=storage)
    with pytest.raises(FileExistsError):  # the folder layout still owns its folder
        nw.Project.init(tmp_path)


def test_readonly_open_of_an_empty_mapping_storage_is_no_graph_yet(tmp_path):
    storage = _mapping_storage(tmp_path)
    with pytest.raises(FileNotFoundError):
        storage.open_graph_readonly()
    nw.Project.init(tmp_path, storage=storage)
    assert nw.Project(tmp_path, storage=storage).graph.sections() == []


def test_init_folders_are_the_storages(tmp_path):
    nw.Project.init(
        tmp_path / "a", storage=_mapping_storage(tmp_path / "a", init_folders=("out",))
    )
    assert sorted(p.name for p in (tmp_path / "a").iterdir()) == ["out"]


def test_folder_storage_is_the_historical_layout(tmp_path):
    proj = nw.Project.init(tmp_path / "p")
    proj.graph.upsert_section(SectionBodyV1(section_id="a"), interval=_iv(0, 1))
    root = tmp_path / "p"
    assert isinstance(proj.storage, nw.FolderStorage)
    assert (root / "project.json").exists()
    assert (root / "project.annot.sqlite").exists()
    assert (root / "shots").is_dir() and (root / "song").is_dir()


def test_as_project_storage_refuses_what_is_not_a_project():
    with pytest.raises(TypeError):
        nw.as_project_storage(42)


def test_upsert_entity_keeps_its_id_so_derivatives_go_stale(tmp_path):
    storage = _mapping_storage(tmp_path)
    proj = nw.Project.init(tmp_path, storage=storage)
    kw = dict(tier="scene-doc", body_schema_uri="annot://schema/test-scene/v1")
    sid = proj.graph.upsert_entity(**kw, body={"sha256": "a"})
    child = _derived(proj, sid)
    assert proj.graph.upsert_entity(**kw, body={"sha256": "a"}) == sid  # no-op
    assert nw.stale_after(storage, sid) == []
    assert proj.graph.upsert_entity(**kw, body={"sha256": "b"}) == sid
    assert [a.id for a in nw.stale_after(storage, sid)] == [child.id]
    with pytest.raises(KeyError):
        proj.graph.upsert_entity(**kw, body={"sha256": "c"}, identity_key="name")


def test_mapping_storage_persists_into_the_mapping_across_reopens(tmp_path):
    """With lacing's own MappingStore (the default), a fresh storage over the same
    mappings sees everything: nothing lives only in a process."""
    graph, docs = {}, {}
    proj = nw.Project.init(
        tmp_path,
        title="t",
        storage=nw.MappingStorage(root=tmp_path, graph=graph, docs=docs),
    )
    proj.graph.upsert_section(SectionBodyV1(section_id="a"), interval=_iv(0, 1))
    assert graph  # written through, not held in memory

    again = nw.Project(
        tmp_path, storage=nw.MappingStorage(root=tmp_path, graph=graph, docs=docs)
    )
    assert [s.body.section_id for s in again.graph.sections()] == ["a"]


def test_json_docs_delete_removes_the_file_without_the_trash(tmp_path, monkeypatch):
    """dol ``Files`` defaults to sending deletes to the OS trash (or warning
    when it cannot); a project's docs are deleted outright."""
    import warnings

    import dol.trash

    from nw.storage import json_docs

    def _no_trash(_):
        raise AssertionError("json_docs delete went through dol's trash default")

    monkeypatch.setattr(dol.trash, "default_delete_func", _no_trash)
    docs = json_docs(tmp_path)
    docs["a/b.json"] = {"x": 1}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        del docs["a/b.json"]
    assert not (tmp_path / "a" / "b.json").exists()


# --- json_docs writes are atomic (nw#244) ------------------------------------


def test_a_failed_document_write_leaves_the_old_document_whole(tmp_path, monkeypatch):
    """A write that fails at the swap (or a reader racing it) must find the old
    document, never a truncated one: the write is temp-file + os.replace."""
    import os

    import pytest

    from nw.storage import json_docs

    docs = json_docs(tmp_path)
    docs["project.json"] = {"title": "old"}

    def refuse(*a, **k):
        raise OSError("swap refused")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError):
        docs["project.json"] = {"title": "new", "big": "x" * 10_000}
    monkeypatch.undo()
    assert docs["project.json"] == {"title": "old"}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["project.json"]  # no temp left


def test_documents_still_round_trip_nested_keys_and_delete(tmp_path):
    from nw.storage import json_docs

    docs = json_docs(tmp_path)
    docs["characters/thor/card.json"] = {"a": 1}
    assert docs["characters/thor/card.json"] == {"a": 1}
    assert "characters/thor/card.json" in list(docs)
    del docs["characters/thor/card.json"]
    assert "characters/thor/card.json" not in docs


def test_a_document_key_cannot_leave_the_root(tmp_path):
    """The atomic write must keep dol's key guard: a key built from a caller's
    name (``characters/../../x``) never lands outside the project."""
    import pytest

    from nw.storage import json_docs

    root = tmp_path / "p"
    root.mkdir()
    docs = json_docs(root)
    for key in ("../escape.json", "a/../../escape.json"):
        with pytest.raises(KeyError):
            docs[key] = {"x": 1}
        with pytest.raises(KeyError):
            docs[key]
    assert not (tmp_path / "escape.json").exists()


def test_a_document_read_outlasts_a_writer_swapping_it(tmp_path, monkeypatch):
    """On Windows a read landing in os.replace's instant is refused; it is
    retried, not reported as a missing document (nw#244)."""
    import dol.atomic

    from nw.storage import json_docs

    docs = json_docs(tmp_path)
    docs["project.json"] = {"title": "t"}
    calls = []
    real_open = open

    def flaky_open(path, *a, **k):
        if str(path).endswith("project.json") and not calls:
            calls.append(path)
            raise PermissionError("being replaced")
        return real_open(path, *a, **k)

    import nw.storage as storage_module

    monkeypatch.setattr(storage_module, "DFLT_RETRY", dol.atomic.Retry(on=(PermissionError,), backoff_s=0))
    monkeypatch.setattr("builtins.open", flaky_open)
    assert docs["project.json"] == {"title": "t"}
    assert calls
