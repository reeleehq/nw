"""The shared media store (nw#95): layout, host sharing, two-phase GC."""

from __future__ import annotations

import os

import pytest

from nw.media_catalog import BACKEND_ENV_KEY, HostArtifactCatalog
from nw.media_store import SharedMediaStore, StoreCatalogUnreadable


@pytest.fixture(autouse=True)
def _local(monkeypatch):
    monkeypatch.delenv(BACKEND_ENV_KEY, raising=False)


def _project(tmp_path, name, data=b"RIFFdata"):
    root = tmp_path / name
    (root / "media").mkdir(parents=True)
    f = root / "media" / "a.wav"
    f.write_bytes(data)
    return root, f


def test_layout_is_tenant_class_sha(tmp_path):
    store = SharedMediaStore(tmp_path / "s", tenant="t1", lifecycle_class="project")
    f = tmp_path / "x"
    f.write_bytes(b"abc")
    aid = store.put(f)
    assert store.blob_path(aid) == tmp_path / "s" / "t1" / "project" / aid


@pytest.mark.parametrize("bad", ["", "..", "a/b", "_nw", ".x"])
def test_unsafe_segments_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        SharedMediaStore(tmp_path, tenant=bad)


def test_two_hosts_share_one_inode_with_own_catalogs(tmp_path):
    store = SharedMediaStore(tmp_path / "s")
    (p1, f1), (p2, f2) = _project(tmp_path, "staging"), _project(tmp_path, "dev")
    c1 = HostArtifactCatalog(p1, store=store)
    c2 = HostArtifactCatalog(p2, store=store)
    a1, a2 = c1.register(f1, kind="audio"), c2.register(f2, kind="audio")
    assert a1 == a2
    assert c1.has(a1) and c2.has(a2)
    inode = store.blob_path(a1).stat().st_ino
    assert c1.blob_path(a1).stat().st_ino == c2.blob_path(a2).stat().st_ino == inode
    assert store.references() == {a1: 2}  # two rows, one blob


def test_default_catalog_unchanged_without_store(tmp_path):
    p, f = _project(tmp_path, "p")
    c = HostArtifactCatalog(p)
    aid = c.register(f, kind="audio")
    assert c.has(aid)
    assert not (tmp_path / "s").exists()


def test_sweep_is_two_phase_and_marks_from_every_catalog(tmp_path):
    store = SharedMediaStore(tmp_path / "s")
    (p1, f1), (p2, f2) = _project(tmp_path, "a"), _project(tmp_path, "b")
    c1, c2 = HostArtifactCatalog(p1, store=store), HostArtifactCatalog(p2, store=store)
    aid = c1.register(f1, kind="audio")
    c2.register(f2, kind="audio")
    # host 1 drops its row; host 2 still references the blob
    (c1.rows_dir / f"{aid}.json").unlink()
    assert store.sweep(apply=True, grace_s=0).removed == []
    assert store.has(aid)
    (c2.rows_dir / f"{aid}.json").unlink()
    first = store.sweep(apply=True, grace_s=100, now=1000.0)
    assert first.marked == [aid] and store.has(aid)  # marking never deletes
    mid = store.sweep(apply=True, grace_s=100, now=1050.0)
    assert mid.still_in_grace == [aid] and store.has(aid)
    dry = store.sweep(apply=False, grace_s=100, now=1200.0)
    assert dry.removed == [aid] and store.has(aid)  # dry run removes nothing
    done = store.sweep(apply=True, grace_s=100, now=1200.0)
    assert done.removed == [aid] and not store.has(aid)


def test_row_returning_clears_the_mark(tmp_path):
    store = SharedMediaStore(tmp_path / "s")
    p, f = _project(tmp_path, "a")
    c = HostArtifactCatalog(p, store=store)
    aid = c.register(f, kind="audio")
    row = c.rows_dir / f"{aid}.json"
    saved = row.read_text()
    row.unlink()
    store.sweep(apply=True, grace_s=10, now=0.0)
    row.write_text(saved)
    assert store.sweep(apply=True, grace_s=10, now=1.0).unmarked == [aid]
    assert store.sweep(apply=True, grace_s=10, now=100.0).removed == []


def test_sweep_refuses_when_a_catalog_is_missing(tmp_path):
    store = SharedMediaStore(tmp_path / "s")
    p, f = _project(tmp_path, "a")
    c = HostArtifactCatalog(p, store=store)
    aid = c.register(f, kind="audio")
    import shutil

    shutil.rmtree(c.rows_dir)
    with pytest.raises(StoreCatalogUnreadable):
        store.sweep(apply=True, grace_s=0)
    assert store.has(aid)
    assert store.unregister_catalog(c.rows_dir)
    store.sweep(apply=True, grace_s=0, now=0.0)
    assert store.sweep(apply=True, grace_s=0, now=1.0).removed == [aid]
