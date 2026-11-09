"""A per-test Postgres for nw's graph backend: ``pg_env`` and its skip rule (nw#242).

Three packages hand-rolled the same harness (nw's own Postgres tests, lacing's
conftest, reelee's project-meta tests). It lives here once::

    # a consumer's conftest.py
    pytest_plugins = ["nw.testing.postgres"]

    # a test
    def test_on_postgres(pg_env, tmp_path):
        proj = nw.Project.init(tmp_path / "p")  # its graph is in Postgres

``pg_env`` points ``NW_GRAPH_BACKEND`` / ``NW_GRAPH_DB_URL`` at
pytest-postgresql's per-test ``postgresql`` database and closes lacing's
pooled connections afterwards, so a connection to a torn-down database never
leaks into the next test. Where ``pytest-postgresql``, ``psycopg`` or a
Postgres binary is missing, a test using it **skips** (it never errors), so
hosted CI without Postgres stays green. For a module that is Postgres-only,
:func:`skip_module_unless_postgres` skips it whole at import.
"""

from __future__ import annotations

import importlib.util
import shutil
from typing import Iterator, Optional

import pytest

__all__ = ["conninfo", "pg_env", "postgres_unavailable", "skip_module_unless_postgres"]

POSTGRES_BINARIES = ("pg_ctl", "postgres")
"""Executables any one of which on ``PATH`` means a local Postgres can start."""

BACKEND_ENV = {"backend": "NW_GRAPH_BACKEND", "url": "NW_GRAPH_DB_URL"}
"""The environment variables :mod:`nw.graph_backend` reads."""


def postgres_unavailable() -> Optional[str]:
    """Why a per-test Postgres cannot run here, or ``None`` when it can."""
    for module in ("pytest_postgresql", "psycopg"):
        if importlib.util.find_spec(module) is None:
            return f"needs {module} (nw's Postgres tests: pip install pytest-postgresql 'psycopg[binary]')"
    if not any(shutil.which(name) for name in POSTGRES_BINARIES):
        return "needs a Postgres binary (pg_ctl) on PATH"
    return None


def skip_module_unless_postgres() -> None:
    """Skip the calling test module, at import, when Postgres is unavailable."""
    reason = postgres_unavailable()
    if reason is not None:
        pytest.skip(reason, allow_module_level=True)


def conninfo(postgresql) -> str:
    """A libpq connection string for pytest-postgresql's ``postgresql`` fixture."""
    import psycopg

    info = postgresql.info
    return psycopg.conninfo.make_conninfo(
        host=info.host,
        port=info.port,
        user=info.user,
        password=info.password or "",
        dbname=info.dbname,
    )


@pytest.fixture
def pg_env(request, monkeypatch) -> Iterator[str]:
    """Point nw's graph backend at a per-test Postgres database; yield its URL.

    Skips (never errors) where :func:`postgres_unavailable` says why.
    """
    reason = postgres_unavailable()
    if reason is not None:
        pytest.skip(reason)
    url = conninfo(request.getfixturevalue("postgresql"))
    monkeypatch.setenv(BACKEND_ENV["backend"], "postgres")
    monkeypatch.setenv(BACKEND_ENV["url"], url)
    from lacing.store import close_all_pools

    try:
        yield url
    finally:
        close_all_pools()
