# nw.testing

Test helpers nw ships for its consumers (hosts, genres, plugins).

Nothing here is imported by `import nw`; a consumer imports the module it
needs from its own tests or conftest: `nw.testing.postgres` (a per-test
Postgres graph backend) and [`nw.testing.transforms`](nw.testing.transforms.html.md#module-nw.testing.transforms) (does a Transform’s
result say truthfully what it wrote). Each module may need test-only
dependencies (`pytest`, and for `nw.testing.postgres` the
`pytest-postgresql` / `psycopg` pair plus a Postgres binary), and skips
cleanly where they are missing.

### Modules

| [`transforms`](nw.testing.transforms.html.md#module-nw.testing.transforms)   | Conformance check: a Transform's result says truthfully what it wrote (nw#234).   |
|--------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
