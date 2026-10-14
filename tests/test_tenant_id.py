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
