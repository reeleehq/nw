"""nw.is_project / Project.open_or_init: hosts never name project.json (nw#217)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from lacing.store import MemoryStore

import nw
from nw.storage import project_storages


def _mapping_storage(root: Path) -> nw.MappingStorage:
    stores: dict[int, MemoryStore] = {}
    return nw.MappingStorage(
        root=root,
        graph={},
        docs={},
        store_factory=lambda m: stores.setdefault(id(m), MemoryStore()),
    )


def test_is_project_never_writes(tmp_path):
    missing = tmp_path / "a" / "b"
    assert nw.is_project(missing) is False
    assert not (tmp_path / "a").exists()
    (tmp_path / "plain").mkdir()
    assert nw.is_project(tmp_path / "plain") is False
    assert list((tmp_path / "plain").iterdir()) == []


def test_a_file_or_a_directory_named_like_the_marker_is_not_a_project(tmp_path):
    (tmp_path / "f").write_text("x")
    assert nw.is_project(tmp_path / "f") is False
    (tmp_path / "d" / nw.storage.PROJECT_FILE_NAME).mkdir(parents=True)
    assert nw.is_project(tmp_path / "d") is False


def test_is_project_accepts_a_path_a_storage_or_a_project(tmp_path):
    proj = nw.Project.init(tmp_path / "p")
    assert nw.is_project(proj.root) and nw.is_project(str(proj.root))
    assert nw.is_project(proj.storage) and nw.is_project(proj)


def test_open_or_init_creates_then_opens_and_keeps_the_first_title(tmp_path):
    root = tmp_path / "ep_01"
    made = nw.Project.open_or_init(root, title="Episode 1")
    again = nw.Project.open_or_init(root, title="ignored")
    assert again.root == made.root
    assert again.read_spec().title == "Episode 1"


def test_open_or_init_accepts_an_existing_empty_folder(tmp_path):
    (tmp_path / "empty").mkdir()
    assert nw.Project.open_or_init(tmp_path / "empty").read_spec().title == "empty"


def test_a_folder_holding_something_else_is_refused_never_overwritten(tmp_path):
    root = tmp_path / "busy"
    root.mkdir()
    (root / "notes.md").write_text("mine")
    with pytest.raises(FileExistsError):
        nw.Project.open_or_init(root)
    assert [p.name for p in root.iterdir()] == ["notes.md"]


def test_a_genres_storage_is_used_for_the_check_and_the_create(tmp_path):
    """A resolver's layout is respected: the project is created in the genre's
    storage (no project.json on disk), and found there again by path."""
    storage = _mapping_storage(tmp_path)

    def resolver(root: Path):
        return storage if root == tmp_path.resolve() else None

    nw.register_project_storage("test_open_or_init", resolver)
    try:
        made = nw.Project.open_or_init(tmp_path, title="genre")
        assert made.storage is storage
        assert not (tmp_path / nw.storage.PROJECT_FILE_NAME).exists()
        assert nw.is_project(tmp_path)
        assert nw.Project.open_or_init(tmp_path).read_spec().title == "genre"
    finally:
        del project_storages["test_open_or_init"]


def test_an_explicit_storage_is_honoured(tmp_path):
    storage = _mapping_storage(tmp_path)
    made = nw.Project.open_or_init(tmp_path, title="explicit", storage=storage)
    assert made.storage is storage
    assert nw.Project.open_or_init(tmp_path, storage=storage).read_spec().title == "explicit"


def test_an_explicit_storage_elsewhere_creates_the_project_where_it_lives(tmp_path):
    """With an explicit storage whose root differs from ``root``, the project is
    made at ``storage.root`` (what the lock covers and what Project opens),
    never half-made at ``root``."""
    app_root = tmp_path / "app_root"
    storage = _mapping_storage(app_root)
    made = nw.Project.open_or_init(tmp_path / "other_root", title="t", storage=storage)
    assert made.root == storage.root and app_root.is_dir()
    assert not (tmp_path / "other_root").exists()
    again = nw.Project.open_or_init(tmp_path / "other_root", storage=storage)
    assert again.read_spec().title == "t"


def test_two_callers_racing_to_create_both_get_the_project(tmp_path, monkeypatch):
    """Both callers pass the first ``is_project`` check before either creates,
    so without the creation lock the loser's ``init`` meets a half-made folder
    (no project.json yet) and raises; with it, the loser opens the winner's."""
    import nw.project as project_module

    root = tmp_path / "race"
    real_is_project = project_module.is_project
    barrier = threading.Barrier(2)
    first_check_done = threading.local()

    def is_project_after_both_checked(storage):
        answer = real_is_project(storage)
        if not getattr(first_check_done, "v", False):
            first_check_done.v = True
            barrier.wait(timeout=5)
        return answer

    monkeypatch.setattr(project_module, "is_project", is_project_after_both_checked)
    results, errors = [], []

    def go():
        try:
            results.append(nw.Project.open_or_init(root, title="race"))
        except Exception as e:  # pragma: no cover - the failure being guarded
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == [] and len(results) == 2
    assert {p.root for p in results} == {root.resolve()}
    assert {p.read_spec().title for p in results} == {"race"}


def test_init_refuses_a_root_that_is_not_the_storages(tmp_path):
    """nw#236: init would make ``root`` while the project lives at
    ``storage.root`` — a half-made project every retry fails on."""
    storage = _mapping_storage(tmp_path / "app_root")
    with pytest.raises(ValueError, match="not the storage's root"):
        nw.Project.init(tmp_path / "other_root", storage=storage)
    assert not (tmp_path / "other_root").exists()
