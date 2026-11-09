"""nw.testing.postgres: the shipped pg_env fixture and its skip rule (nw#242)."""

from __future__ import annotations

import pytest

from nw.testing import postgres as pgt
from nw.testing.postgres import pg_env  # noqa: F401 — a fixture


def test_unavailable_names_what_is_missing(monkeypatch):
    monkeypatch.setattr(pgt.importlib.util, "find_spec", lambda name: None)
    assert "pytest_postgresql" in pgt.postgres_unavailable()
    monkeypatch.undo()
    monkeypatch.setattr(pgt.shutil, "which", lambda name: None)
    if pgt.importlib.util.find_spec("pytest_postgresql") and pgt.importlib.util.find_spec("psycopg"):
        assert "pg_ctl" in pgt.postgres_unavailable()


def test_pg_env_skips_instead_of_erroring_without_postgres(request, monkeypatch):
    """Where Postgres is missing, a test using pg_env skips: it never errors on
    the absent ``postgresql`` fixture (it does not ask for it first)."""
    monkeypatch.setattr(pgt, "postgres_unavailable", lambda: "needs pg_ctl on PATH")
    with pytest.raises(pytest.skip.Exception, match="needs pg_ctl"):
        request.getfixturevalue("pg_env")


def test_pg_env_points_nws_backend_at_postgres(pg_env):
    import os

    assert os.environ["NW_GRAPH_BACKEND"] == "postgres"
    assert os.environ["NW_GRAPH_DB_URL"] == pg_env
