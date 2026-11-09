"""Test helpers nw ships for its consumers (hosts, genres, plugins).

Nothing here is imported by ``import nw``; a consumer imports the module it
needs from its own tests or conftest: :mod:`nw.testing.postgres` (a per-test
Postgres graph backend) and :mod:`nw.testing.transforms` (does a Transform's
result say truthfully what it wrote). Each module may need test-only
dependencies (``pytest``, and for :mod:`nw.testing.postgres` the
``pytest-postgresql`` / ``psycopg`` pair plus a Postgres binary), and skips
cleanly where they are missing.
"""
