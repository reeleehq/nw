# nw.genres

### nw.genres *= <Registry nw.genres>*

A typed dict-backed plugin registry.

* **Parameters:**
  * **name** – Optional name; appears in error messages and `repr`.
  * **on_conflict** – `'error'` (default) raises `RegistryConflict` when registering
    a key that already exists. `'replace'` silently overwrites.
    `'keep'` silently keeps the original.
  * **strict_setitem** – Opt-in (default `False`). By default `reg[k] = v` is an explicit
    assignment that replaces whatever is there, bypassing `on_conflict`.
    With `strict_setitem=True` it follows the `on_conflict` policy exactly
    like `register()` (so `MutableMapping.update` and `setdefault`
    do too; note `update` is not atomic: entries before the first conflict stay).
  * **(****reading** (*Keys that are aliases resolve to their canonical key everywhere*)

:param :
:param `reg[k] = v`:
:param `register()`:
:param `register_lazy()`):
:param so the `on_conflict`:
:param policy always applies to the canonical entry.:
:param Implements `MutableMapping` so anything that takes a mapping (`dict(...)`:
:param :
:param iteration:
:param length checks:
:param `in` lookups:
:param `.items()`) just works.:
