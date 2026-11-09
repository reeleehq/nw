"""Tests for nw.experiment — clone_project + apply_to_projects."""

from __future__ import annotations

from pathlib import Path

import pytest

import nw

from nw import (
    MappingStorage,
    Project,
    register_project_storage,
    ShotSpec,
    apply_to_projects,
    clone_project,
    summarize_all,
)


def _seed_project(root: Path, *, title: str) -> Project:
    proj = Project.init(root, title=title)
    proj.add_character("thor", description="narrator")
    proj.upsert_shot(ShotSpec(id="s01", start_s=0, end_s=5))
    # Pretend the song was set:
    (proj.root / "song" / "song.wav").write_bytes(b"WAV")
    # Pretend a render happened:
    (proj.shot_dir("s01") / "output.mp4").write_bytes(b"mp4")
    # Pretend a script exists:
    (proj.root / "script" / "script.md").write_text("# script")
    return proj


def test_clone_preserves_song_and_characters_resets_outputs(tmp_path):
    src = tmp_path / "src"
    _seed_project(src, title="Original")

    dst = tmp_path / "dst_v1"
    summary = clone_project(src, dst, title="V1")

    # Title was set to V1 on the clone.
    assert summary.title == "V1"
    # Song carries over.
    assert (dst / "song" / "song.wav").exists()
    # Characters carry over (preserve default).
    assert (dst / "characters" / "thor").is_dir()
    # Shots are reset to empty.
    assert (dst / "shots").is_dir()
    assert list((dst / "shots").iterdir()) == []
    # Output was reset.
    assert list((dst / "output").iterdir()) == []
    # Script subtree was reset (default).
    assert list((dst / "script").iterdir()) == []
    # Source unchanged.
    assert (src / "shots" / "s01" / "output.mp4").exists()


def test_clone_default_title_uses_dst_folder_name(tmp_path):
    src = tmp_path / "src"
    _seed_project(src, title="Original")

    dst = tmp_path / "the_bells_v1_lipsync"
    summary = clone_project(src, dst)
    assert summary.title == "the_bells_v1_lipsync"


def test_clone_refuses_existing_dst(tmp_path):
    src = tmp_path / "src"
    _seed_project(src, title="o")
    dst = tmp_path / "dst"
    clone_project(src, dst)
    with pytest.raises(FileExistsError):
        clone_project(src, dst)


def test_clone_force_overwrites(tmp_path):
    src = tmp_path / "src"
    _seed_project(src, title="o")
    dst = tmp_path / "dst"
    clone_project(src, dst, title="first")
    clone_project(src, dst, title="second", force=True)
    assert Project(dst).read_spec().title == "second"


def test_clone_custom_preserve_and_reset(tmp_path):
    src = tmp_path / "src"
    _seed_project(src, title="o")

    dst = tmp_path / "dst"
    # Preserve the script too; reset only output.
    clone_project(src, dst, preserve=("song", "characters", "script"), reset=("output",))
    assert (dst / "script" / "script.md").exists()  # preserved
    assert list((dst / "output").iterdir()) == []   # reset
    # Shots were NOT in the reset set, so they aren't present at all
    # (because they weren't preserved either) — directory may not exist.


def test_clone_logs_decision(tmp_path):
    src = tmp_path / "src"
    _seed_project(src, title="o")
    dst = tmp_path / "dst"
    clone_project(src, dst)
    decisions_file = dst / ".nw" / "decisions.jsonl"
    assert decisions_file.exists()
    text = decisions_file.read_text()
    assert "clone_project" in text
    assert str(src) in text


# --- apply_to_projects -------------------------------------------------------


def test_apply_to_projects_sequential(tmp_path):
    roots = []
    for i, t in enumerate(["A", "B", "C"]):
        root = tmp_path / f"p{i}"
        _seed_project(root, title=t)
        roots.append(root)

    titles = apply_to_projects(roots, lambda p: p.read_spec().title)
    assert titles == ["A", "B", "C"]


def test_apply_to_projects_parallel(tmp_path):
    roots = []
    for i in range(4):
        root = tmp_path / f"p{i}"
        _seed_project(root, title=f"P{i}")
        roots.append(root)

    titles = apply_to_projects(roots, lambda p: p.read_spec().title, parallel=True)
    # Order is preserved even with parallel=True (matches roots iteration order).
    assert titles == ["P0", "P1", "P2", "P3"]


def test_summarize_all_returns_summaries(tmp_path):
    roots = []
    for i in range(2):
        root = tmp_path / f"p{i}"
        _seed_project(root, title=f"P{i}")
        roots.append(root)

    summaries = summarize_all(roots)
    assert len(summaries) == 2
    assert summaries[0].title == "P0"
    assert summaries[1].title == "P1"
    assert all(s.character_count == 1 for s in summaries)
    assert all(s.rendered_shot_count == 1 for s in summaries)


def test_clone_refuses_a_folder_that_is_not_a_project(tmp_path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(FileNotFoundError, match="not an nw project"):
        clone_project(tmp_path / "plain", tmp_path / "dst")


def test_clone_refuses_a_genre_storage_project_by_name(tmp_path):
    """nw#236: a project whose documents live in a genre's storage cannot be
    cloned by copying folders; say so instead of 'no project.json'."""
    from lacing.store import MemoryStore

    from nw.storage import project_storages

    root = tmp_path / "genre_proj"
    stores: dict = {}
    storage = MappingStorage(
        root=root, graph={}, docs={},
        store_factory=lambda m: stores.setdefault(id(m), MemoryStore()),
    )
    Project.init(root, storage=storage)
    register_project_storage("test_clone", lambda r: storage if r == root.resolve() else None)
    try:
        with pytest.raises(ValueError, match="folder layout"):
            clone_project(root, tmp_path / "dst")
    finally:
        del project_storages["test_clone"]


def test_a_clone_is_its_own_tenant_and_is_not_re_migrated(tmp_path, monkeypatch):
    """nw#251: a copied tenant id would share the source's rows on a shared
    graph backend; a dropped sentinel would re-run the pre-graph migration."""
    import nw.project as project_module
    from nw.storage import TENANT_KEY, FolderStorage

    src = tmp_path / "src"
    _seed_project(src, title="Original")
    src_tenant = FolderStorage(src).docs["project.json"][TENANT_KEY]

    migrations = []
    real = project_module.migrate_to_graph
    monkeypatch.setattr(
        project_module, "migrate_to_graph", lambda root, **k: migrations.append(root) or real(root, **k)
    )
    clone_project(src, tmp_path / "dst")
    dst_tenant = FolderStorage(tmp_path / "dst").docs["project.json"][TENANT_KEY]
    assert dst_tenant and dst_tenant != src_tenant
    assert migrations == []
    assert (tmp_path / "dst" / ".nw" / "migrated_to_graph").is_file()
    assert FolderStorage(src).docs["project.json"][TENANT_KEY] == src_tenant  # source untouched


def test_a_clone_of_a_legacy_project_with_a_song_gets_its_own_tenant(tmp_path):
    """A project without a minted tenant falls back to its song's hash, which a
    preserved song/ shares: the clone must still not alias the source."""
    import json

    from nw.migrate import project_tenant_id
    from nw.storage import TENANT_KEY, FolderStorage

    src = tmp_path / "legacy"
    (src / "song").mkdir(parents=True)
    (src / "song" / "song.wav").write_bytes(b"RIFF-legacy")
    (src / "project.json").write_text(json.dumps({
        "schema_version": 1, "title": "legacy",
        "song": {"audio_path": "song/song.wav", "duration_s": 1.0},
    }))
    clone_project(src, tmp_path / "dst")
    assert FolderStorage(tmp_path / "dst").docs["project.json"][TENANT_KEY]
    assert project_tenant_id(tmp_path / "dst") != project_tenant_id(src)


def test_a_graph_native_clone_warns_of_the_entities_it_leaves_behind(tmp_path):
    """nw#258 (until a clone carries them): a preserved characters/ folder whose
    refs live only in the source's graph is copied without them; say so."""
    import warnings

    from nw.experiment import CloneDropsGraphEntities

    src = tmp_path / "src"
    _seed_project(src, title="Original")  # adds character "thor"
    with pytest.warns(CloneDropsGraphEntities, match="character-ref"):
        clone_project(src, tmp_path / "dst")

    with warnings.catch_warnings():
        warnings.simplefilter("error", CloneDropsGraphEntities)
        clone_project(src, tmp_path / "dst2", preserve=("song",))  # nothing implied
