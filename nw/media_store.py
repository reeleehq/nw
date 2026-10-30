"""One content-addressed blob store per user, shared by every genre and host (nw#95).

Before this, each genre kept its own copy of a project's media (``~/.local/share/
{muvid,braidio,reelee*}``) and each host instance (staging, dev) held a full copy of
the same project. This module is the one place the bytes live.

Decisions (owner-confirmed on reeleehq/nw#104; recommendations in nw#95):

1. **Layout** — ``<root>/<tenant>/<lifecycle_class>/<sha256>``, with ``root`` =
   ``~/.local/share/nw/media`` (nw owns the writer, so nw owns the data home).
   ``tenant`` is ``local`` on a workstation and a caller's hashed id when hosted.
2. **Blobs are keyed by content; rows are not.** Five renders with identical bytes
   are one blob and five rows, each with its own name, project and provenance.
   Nothing a user sees collapses; only the disk copy does. (This is the amendment to
   reelee's ``docs/adr_asset_surfaces.md`` §6.)
3. **Hosts share blobs, keep a catalog each.** A host opts in by naming the store
   (``HostArtifactCatalog(..., store=...)``). The host keeps reading its own
   ``blobs/<sha256>``; that entry is a hardlink to the store's blob, so nothing is
   copied and the host is unchanged.

**Garbage collection** (:meth:`SharedMediaStore.sweep`) marks from *every* catalog
registered with the store, never one host's. It is two-phase: a blob with no live row
anywhere is first *marked* (a timestamp), and only removed by a later sweep once it
has stayed unreferenced for ``grace_s``; a row appearing in the meantime clears the
mark. It is a dry run unless ``apply=True``. It refuses to run if a registered
catalog's rows directory is missing or unreadable, because an unreadable catalog
cannot vouch for its blobs (``unregister_catalog`` is the explicit way to retire one).
Reference count = the number of live rows naming a blob (:meth:`references`).

>>> import tempfile, pathlib
>>> with tempfile.TemporaryDirectory() as d:
...     store = SharedMediaStore(pathlib.Path(d, "store"))
...     src = pathlib.Path(d, "a.bin"); _ = src.write_bytes(b"abc")
...     aid = store.put(src)
...     store.has(aid), store.blob_path(aid).parent.parts[-2:]
(True, ('local', 'project'))
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import KW_ONLY, dataclass, field
from pathlib import Path
from typing import Optional

#: The store's data home, under nw's (not any genre's).
DEFAULT_STORE_ROOT = Path("~/.local/share/nw/media")
DEFAULT_TENANT = "local"
DEFAULT_LIFECYCLE_CLASS = "project"
#: Seconds a blob must stay unreferenced, across two sweeps, before it is removed.
DEFAULT_GRACE_S = 7 * 24 * 3600.0

_IS_DIGEST = re.compile(r"[0-9a-f]{64}")
#: Tenant / class names are path segments: no separators, no dots-only, no reserved.
_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_META_DIR = "_nw"  # per-tenant bookkeeping, beside the lifecycle-class dirs
_LINK_REFUSALS = (errno.EXDEV, errno.EMLINK, errno.EPERM)


class StoreCatalogUnreadable(RuntimeError):
    """A registered catalog cannot be read, so a sweep cannot know what it holds."""


def _segment(name: str, what: str) -> str:
    if not _SEGMENT.fullmatch(name or "") or name == _META_DIR or ".." in name:
        raise ValueError(f"{what} {name!r} is not a safe single path segment")
    return name


def _hash_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@dataclass
class SweepReport:
    """What a sweep saw and (if applied) did."""

    applied: bool = False
    live: int = 0
    marked: list[str] = field(default_factory=list)
    still_in_grace: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unmarked: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SharedMediaStore:
    """The blob store at ``root`` for one ``tenant`` and ``lifecycle_class``."""

    root: Path = DEFAULT_STORE_ROOT
    _: KW_ONLY
    tenant: str = DEFAULT_TENANT
    lifecycle_class: str = DEFAULT_LIFECYCLE_CLASS
    allow_cross_device_copy: bool = False

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root).expanduser())
        _segment(self.tenant, "tenant")
        _segment(self.lifecycle_class, "lifecycle_class")

    # -- layout ---------------------------------------------------------------

    @property
    def blobs_dir(self) -> Path:
        return self.root / self.tenant / self.lifecycle_class

    @property
    def _meta(self) -> Path:
        return self.root / self.tenant / _META_DIR

    @property
    def _catalogs_dir(self) -> Path:
        return self._meta / "catalogs"

    @property
    def _marks_dir(self) -> Path:
        return self._meta / "gc-marks" / self.lifecycle_class

    def blob_path(self, artifact_id: str) -> Optional[Path]:
        """Where ``artifact_id``'s bytes are, or ``None`` if not stored."""
        if not _IS_DIGEST.fullmatch(artifact_id or ""):
            return None
        p = self.blobs_dir / artifact_id
        return p if p.is_file() else None

    def has(self, artifact_id: str) -> bool:
        return self.blob_path(artifact_id) is not None

    # -- writing --------------------------------------------------------------

    def put(self, path, *, artifact_id: Optional[str] = None) -> str:
        """Store ``path``'s bytes; return the digest. Idempotent.

        Hardlinks when it can (the media is already on this filesystem), refuses
        a cross-device store unless ``allow_cross_device_copy``. A blob already
        there is size-checked, not re-hashed.
        """
        src = Path(path)
        aid = artifact_id if artifact_id is not None else _hash_file(src)
        if not _IS_DIGEST.fullmatch(aid or ""):
            raise ValueError(f"artifact_id {aid!r} is not a 64-char lowercase hex digest")
        blob = self.blobs_dir / aid
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        if blob.exists():
            if blob.stat().st_size != src.stat().st_size:
                raise RuntimeError(
                    f"store blob {aid} is {blob.stat().st_size} bytes but {src} is "
                    f"{src.stat().st_size}: remove the blob and put again."
                )
            self._clear_mark(aid)
            return aid
        try:
            os.link(src, blob)
        except FileExistsError:
            pass
        except OSError as exc:
            if exc.errno not in _LINK_REFUSALS:
                raise
            if not self.allow_cross_device_copy:
                raise OSError(
                    exc.errno,
                    f"cannot hardlink {src.name} into the shared store at "
                    f"{self.blobs_dir}: another filesystem. Keep the store on the "
                    "media's filesystem or pass allow_cross_device_copy=True.",
                ) from exc
            tmp = blob.with_name(f".{aid}.{os.getpid()}.tmp")
            try:
                shutil.copy2(src, tmp)
                os.replace(tmp, blob)
            finally:
                tmp.unlink(missing_ok=True)
        self._clear_mark(aid)
        return aid

    # -- catalog registry (what GC marks from) --------------------------------

    def register_catalog(self, rows_dir) -> None:
        """Record that the catalog whose rows live in ``rows_dir`` references this store."""
        rows_dir = Path(rows_dir).resolve()
        key = hashlib.sha256(str(rows_dir).encode()).hexdigest()[:24]
        _atomic_write(
            self._catalogs_dir / f"{key}.json", json.dumps({"rows_dir": str(rows_dir)})
        )

    def unregister_catalog(self, rows_dir) -> bool:
        """Retire a catalog (e.g. its project was deleted). Its blobs become sweepable."""
        rows_dir = Path(rows_dir).resolve()
        key = hashlib.sha256(str(rows_dir).encode()).hexdigest()[:24]
        p = self._catalogs_dir / f"{key}.json"
        existed = p.exists()
        p.unlink(missing_ok=True)
        return existed

    def registered_catalogs(self) -> list[Path]:
        if not self._catalogs_dir.is_dir():
            return []
        out = []
        for p in sorted(self._catalogs_dir.glob("*.json")):
            out.append(Path(json.loads(p.read_text(encoding="utf-8"))["rows_dir"]))
        return out

    def references(self) -> dict[str, int]:
        """``{sha256: live rows naming it}`` across every registered catalog."""
        counts: dict[str, int] = {}
        for rows_dir in self.registered_catalogs():
            if not rows_dir.is_dir():
                raise StoreCatalogUnreadable(
                    f"registered catalog {rows_dir} is missing; a sweep cannot tell "
                    "what it references. Restore it or unregister_catalog() it."
                )
            for p in rows_dir.glob("*.json"):
                if _IS_DIGEST.fullmatch(p.stem):
                    counts[p.stem] = counts.get(p.stem, 0) + 1
        return counts

    # -- GC -------------------------------------------------------------------

    def sweep(
        self,
        *,
        apply: bool = False,
        grace_s: float = DEFAULT_GRACE_S,
        now: Optional[float] = None,
    ) -> SweepReport:
        """Mark unreferenced blobs; remove those unreferenced for ``grace_s``.

        Dry run unless ``apply``. See the module docstring for the guarantees.
        """
        now = time.time() if now is None else now
        refs = self.references()  # raises before anything is touched
        rep = SweepReport(applied=apply)
        if not self.blobs_dir.is_dir():
            return rep
        for blob in sorted(self.blobs_dir.iterdir()):
            aid = blob.name
            if not (blob.is_file() and _IS_DIGEST.fullmatch(aid)):
                continue
            mark = self._marks_dir / aid
            if refs.get(aid, 0) > 0:
                rep.live += 1
                if mark.exists():
                    rep.unmarked.append(aid)
                    if apply:
                        mark.unlink(missing_ok=True)
                continue
            since = None
            try:
                since = float(mark.read_text())
            except (OSError, ValueError):
                pass
            if since is None:
                rep.marked.append(aid)
                if apply:
                    _atomic_write(mark, repr(now))
            elif now - since >= grace_s:
                rep.removed.append(aid)
                if apply:
                    blob.unlink(missing_ok=True)
                    mark.unlink(missing_ok=True)
            else:
                rep.still_in_grace.append(aid)
        return rep

    def _clear_mark(self, aid: str) -> None:
        (self._marks_dir / aid).unlink(missing_ok=True)


__all__ = [
    "DEFAULT_GRACE_S",
    "DEFAULT_LIFECYCLE_CLASS",
    "DEFAULT_STORE_ROOT",
    "DEFAULT_TENANT",
    "SharedMediaStore",
    "StoreCatalogUnreadable",
    "SweepReport",
]
