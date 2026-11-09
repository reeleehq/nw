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


def test_pg_env_skips_instead_of_erroring_without_postgres(pytester):
    pytester.makeconftest('pytest_plugins = ["nw.testing.postgres"]')
    pytester.makepyfile(
        """
        import nw.testing.postgres as pgt

        def test_x(pg_env, monkeypatch):
            raise AssertionError("ran without postgres")
        """
    )
    pytester.makepyfile(
        sitecustomize=""  # placeholder: no-op
    )
    result = pytester.runpytest_inprocess(
        "-p", "no:cacheprovider", "-o", "addopts=",
        "--override-ini", "python_files=test_*.py",
    )
    # With postgres available it runs (and our test body fails on purpose);
    # without, it must skip. Either way it never *errors* on a missing fixture.
    outcomes = result.parseoutcomes()
    assert "error" not in outcomes and "errors" not in outcomes


def test_pg_env_points_nws_backend_at_postgres(pg_env):
    import os

    assert os.environ["NW_GRAPH_BACKEND"] == "postgres"
    assert os.environ["NW_GRAPH_DB_URL"] == pg_env
