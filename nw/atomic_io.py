"""Small-file IO that a concurrent reader can never catch half-done (nw#243, nw#260).

nw's stores (the shared media store's registry, the host media catalog's rows)
keep small JSON/text files that a writer replaces while readers poll them.
Three helpers, all through :mod:`dol.atomic`:

- :func:`write_text_atomic`: temp file, then ``os.replace``, so a reader sees
  the old text or the new, never a truncated file;
- :func:`copy_file_atomic`: a whole file copied into place the same way (a
  blob copied across filesystems), on dol's uniquely named ``O_EXCL`` temp, so
  two copies of one blob at once never share a temp file;
- :func:`replace_retrying`: ``os.replace`` alone;
- :func:`read_text_retrying`: a read.

Each retries a Windows sharing violation (a reader or writer holding the file
for an instant), the policy ``retry=`` (keyword-only; default
:data:`dol.atomic.DFLT_RETRY`, which retries nothing off Windows, where the
same error means a real permission problem). A missing file is never retried.
Stdlib and dol only, so any module can use it.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, Optional

from dol.atomic import DFLT_RETRY, atomic_write

__all__ = [
    "copy_file_atomic",
    "read_text_retrying",
    "replace_retrying",
    "write_text_atomic",
]

COPY_CHUNK_BYTES = 1 << 20
"""Bytes read per chunk by :func:`copy_file_atomic`."""


def _policy(retry: Optional[Callable]) -> Callable:
    """``retry``, else dol's default, looked up at call time (so it can be swapped)."""
    return retry if retry is not None else DFLT_RETRY


def copy_file_atomic(
    src, dst, *, retry: Optional[Callable] = None, chunk_bytes: int = COPY_CHUNK_BYTES
) -> None:
    """Copy ``src`` to ``dst`` atomically: a copy that fails half-way never
    leaves a short ``dst``, and a reader holding ``dst`` is outlasted. Times and
    mode are copied after (best effort), as ``shutil.copy2`` would."""

    def chunks():
        with open(src, "rb") as f:
            while chunk := f.read(chunk_bytes):
                yield chunk

    atomic_write(dst, chunks(), retry=_policy(retry))
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass


def write_text_atomic(path, text: str, *, retry: Optional[Callable] = None) -> None:
    """``text`` (UTF-8) to ``path`` atomically; parent folders are created."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, text.encode("utf-8"), retry=_policy(retry))


def replace_retrying(src, dst, *, retry: Optional[Callable] = None) -> None:
    """``os.replace(src, dst)``, retried on a sharing violation."""
    _policy(retry)(os.replace, src, dst)


def read_text_retrying(path, *, retry: Optional[Callable] = None) -> str:
    """``path``'s UTF-8 text, retried on a sharing violation."""
    return _policy(retry)(Path.read_text, Path(path), "utf-8")
