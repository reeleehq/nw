"""A project's shared-backend tenant is minted at ``Project.init`` (nw#109).

Under Postgres a project's graph lives in a tenant keyed on an id. Keyed on
root + title (or the song's hash), a project folder removed and created again
with the same name and title reused the old tenant and the old graph — including
its ``project-meta`` row and stable id — came back with the new project.

No Postgres is needed: a stand-in ``PostgresStore`` keeps one in-memory store
per ``project_id``, which is exactly the persistence a real tenant has.
"""

from __future__ import annotations

import json
import shutil

import pytest
from lacing import MemoryStore, TimeInterval
import lacing.store

import nw
from nw.migrate import project_asset_id, project_tenant_id
from nw.storage import TENANT_KEY, tenant_id_of

_TENANTS: dict[str, MemoryStore] = {}


class _FakePostgresStore:
    """Delegates to one shared ``MemoryStore`` per ``project_id``."""

    def __init__(self, db_url, *, rate, owner_id, project_id):
        self._project_id = project_id
        self._inner = _TENANTS.setdefault(project_id, MemoryStore())

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):  # the tenant outlives the connection
        pass


@pytest.fixture
def pg(monkeypatch):
    _TENANTS.clear()
    monkeypatch.setenv("NW_GRAPH_BACKEND", "postgres")
    monkeypatch.setenv("NW_GRAPH_DB_URL", "postgresql://stand-in")
    monkeypatch.setattr(lacing.store, "PostgresStore", _FakePostgresStore)
    yield _TENANTS
    _TENANTS.clear()


def _graph_size(project: nw.Project) -> int:
    return len(list(nw.iter_all_annotations(project.root)))


def test_init_mints_a_tenant_id_that_survives_write_spec(tmp_path):
    project = nw.Project.init(tmp_path / "p", title="t")
    minted = json.loads((project.root / "project.json").read_text())[TENANT_KEY]
    assert minted
    project.write_spec(project.read_spec())
    assert json.loads((project.root / "project.json").read_text())[TENANT_KEY] == minted
    assert project.storage.tenant_id == minted


def test_two_projects_get_distinct_tenant_ids(tmp_path):
    a = nw.Project.init(tmp_path / "a", title="same")
    b = nw.Project.init(tmp_path / "b", title="same")
    assert a.storage.tenant_id != b.storage.tenant_id


def test_a_project_that_predates_the_mint_keeps_its_tenant(tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    spec = {"schema_version": 1, "title": "old"}
    (root / "project.json").write_text(json.dumps(spec))
    assert tenant_id_of(root, spec) == project_asset_id(root)
    assert project_tenant_id(root) == project_asset_id(root)


def test_recreated_project_does_not_inherit_the_old_graph(tmp_path, pg):
    root = tmp_path / "p"
    first = nw.Project.init(root, title="t")
    first.graph.upsert_shot(_shot_body(), TimeInterval.from_seconds(0, 4))
    assert _graph_size(first) == 1
    old_tenants = set(pg)

    shutil.rmtree(root)
    second = nw.Project.init(root, title="t")
    assert _graph_size(second) == 0
    assert set(pg) - old_tenants, "the new project got a tenant of its own"
    # The old tenant is untouched.
    assert set(old_tenants) <= set(pg)


def test_storyboard_and_graph_follow_the_same_minted_tenant(tmp_path, pg):
    project = nw.Project.init(tmp_path / "p", title="t")
    project.graph.upsert_shot(_shot_body(), TimeInterval.from_seconds(0, 4))
    assert all(project.storage.tenant_id in pid for pid in pg)


def _shot_body():
    from nw.bodies import ShotBodyV1

    return ShotBodyV1(shot_id="s01")


# --- adopting a legacy project's historical tenant (nw#112) -----------------


def _legacy(tmp_path, name="old"):
    root = tmp_path / name
    root.mkdir()
    (root / "project.json").write_text(
        json.dumps({"schema_version": 1, "title": "old"})
    )
    return root


def test_adopt_pins_the_historical_tenant_without_changing_it(tmp_path):
    root = _legacy(tmp_path)
    before = project_tenant_id(root)
    assert nw.adopt_tenant_id(root) == before
    assert json.loads((root / "project.json").read_text())[TENANT_KEY] == before
    assert project_tenant_id(root) == before


def test_adopt_is_idempotent_and_leaves_a_minted_tenant_alone(tmp_path):
    root = _legacy(tmp_path)
    first = nw.adopt_tenant_id(root)
    assert nw.adopt_tenant_id(root) == first
    minted = nw.Project.init(tmp_path / "new", title="t")
    mid = minted.storage.tenant_id
    assert nw.adopt_tenant_id(minted) == mid
    assert minted.storage.tenant_id == mid


def test_adopt_dry_run_writes_nothing(tmp_path):
    root = _legacy(tmp_path)
    assert nw.adopt_tenant_id(root, dry_run=True) == project_asset_id(root)
    assert TENANT_KEY not in json.loads((root / "project.json").read_text())


def test_adopt_makes_the_key_independent_of_root_and_title(tmp_path, pg):
    root = _legacy(tmp_path)
    old = project_tenant_id(root)
    nw.adopt_tenant_id(root)
    # Retitled / moved: the adopted project keeps its tenant (and data).
    spec = json.loads((root / "project.json").read_text())
    spec["title"] = "renamed"
    (root / "project.json").write_text(json.dumps(spec))
    assert project_tenant_id(root) == old
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    assert project_tenant_id(moved) == old


def test_adopt_returns_none_for_a_folder_that_is_not_a_project(tmp_path):
    (tmp_path / "empty").mkdir()
    assert nw.adopt_tenant_id(tmp_path / "empty") is None
