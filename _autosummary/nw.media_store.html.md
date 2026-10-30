# nw.media_store

One content-addressed blob store per user, shared by every genre and host (nw#95).

Before this, each genre kept its own copy of a project’s media (`~/.local/share/
{muvid,braidio,reelee*}`) and each host instance (staging, dev) held a full copy of
the same project. This module is the one place the bytes live.

Decisions (owner-confirmed on reeleehq/nw#104; recommendations in nw#95):

1. **Layout** — `<root>/<tenant>/<lifecycle_class>/<sha256>`, with `root` =
   `~/.local/share/nw/media` (nw owns the writer, so nw owns the data home).
   `tenant` is `local` on a workstation and a caller’s hashed id when hosted.
2. **Blobs are keyed by content; rows are not.** Five renders with identical bytes
   are one blob and five rows, each with its own name, project and provenance.
   Nothing a user sees collapses; only the disk copy does. (This is the amendment to
   reelee’s `docs/adr_asset_surfaces.md` §6.)
3. **Hosts share blobs, keep a catalog each.** A host opts in by naming the store
   (`HostArtifactCatalog(..., store=...)`). The host keeps reading its own
   `blobs/<sha256>`; that entry is a hardlink to the store’s blob, so nothing is
   copied and the host is unchanged.

**Garbage collection** ([`SharedMediaStore.sweep()`](#nw.media_store.SharedMediaStore.sweep)) marks from *every* catalog
registered with the store, never one host’s. It is two-phase: a blob with no live row
anywhere is first *marked* (a timestamp), and only removed by a later sweep once it
has stayed unreferenced for `grace_s`; a row appearing in the meantime clears the
mark. It is a dry run unless `apply=True`. It refuses to run if a registered
catalog’s rows directory is missing or unreadable, because an unreadable catalog
cannot vouch for its blobs (`unregister_catalog` is the explicit way to retire one).
Reference count = the number of live rows naming a blob (`references()`).

```pycon
>>> import tempfile, pathlib
>>> with tempfile.TemporaryDirectory() as d:
...     store = SharedMediaStore(pathlib.Path(d, "store"))
...     src = pathlib.Path(d, "a.bin"); _ = src.write_bytes(b"abc")
...     aid = store.put(src)
...     store.has(aid), store.blob_path(aid).parent.parts[-2:]
(True, ('local', 'project'))
```

### Module Attributes

| [`DEFAULT_STORE_ROOT`](#nw.media_store.DEFAULT_STORE_ROOT)   | The store's data home, under nw's (not any genre's).                            |
|-----------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`DEFAULT_GRACE_S`](#nw.media_store.DEFAULT_GRACE_S)      | Seconds a blob must stay unreferenced, across two sweeps, before it is removed. |

### Classes

| [`SharedMediaStore`](#nw.media_store.SharedMediaStore)([root, tenant, ...])     | The blob store at `root` for one `tenant` and `lifecycle_class`.   |
|--------------------------------------------------------------------------------------------|--------------------------------------------------------------------|
| [`SweepReport`](#nw.media_store.SweepReport)([applied, live, marked, ...]) | What a sweep saw and (if applied) did.                             |

### Exceptions

| [`StoreCatalogUnreadable`](#nw.media_store.StoreCatalogUnreadable)   | A registered catalog cannot be read, so a sweep cannot know what it holds.   |
|---------------------------------------------------------------------------|------------------------------------------------------------------------------|

### nw.media_store.DEFAULT_GRACE_S *= 604800.0*

Seconds a blob must stay unreferenced, across two sweeps, before it is removed.

### nw.media_store.DEFAULT_STORE_ROOT *= PosixPath('~/.local/share/nw/media')*

The store’s data home, under nw’s (not any genre’s).

### *class* nw.media_store.SharedMediaStore(root=PosixPath('~/.local/share/nw/media'), , tenant='local', lifecycle_class='project', allow_cross_device_copy=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The blob store at `root` for one `tenant` and `lifecycle_class`.

#### blob_path(artifact_id)

Where `artifact_id`’s bytes are, or `None` if not stored.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

#### clear_mark(aid)

Forget that `aid` was unreferenced (a host just used it).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### put(path, , artifact_id=None)

Store `path`’s bytes; return the digest. Idempotent.

Hardlinks when it can (the media is already on this filesystem), refuses
a cross-device store unless `allow_cross_device_copy`. A blob already
there is size-checked, not re-hashed.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### references()

`{sha256: live rows naming it}` across every registered catalog.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

#### register_catalog(rows_dir)

Record that the catalog whose rows live in `rows_dir` references this store.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### sweep(, apply=False, grace_s=604800.0, now=None)

Mark unreferenced blobs; remove those unreferenced for `grace_s`.

Dry run unless `apply`. See the module docstring for the guarantees.

* **Return type:**
  [`SweepReport`](#nw.media_store.SweepReport)

#### unregister_catalog(rows_dir)

Retire a catalog (e.g. its project was deleted). Its blobs become sweepable.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### *exception* nw.media_store.StoreCatalogUnreadable

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

A registered catalog cannot be read, so a sweep cannot know what it holds.

### *class* nw.media_store.SweepReport(applied=False, live=0, marked=list(), still_in_grace=list(), removed=list(), unmarked=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a sweep saw and (if applied) did.
