"""Small-file IO that a concurrent reader can never catch half-done (nw#243, nw#260).

nw's stores (the shared media store's registry, the host media catalog's rows)
keep small JSON/text files that a writer replaces while readers poll them.
Three helpers, all through :mod:`dol.atomic`:

- :func:`write_text_atomic`: temp file, then ``os.replace``, so a reader sees
  the old text or the new, never a truncated file;
- :func:`replace_retrying`: ``os.replace`` alone (a copied blob moved into place);
- :func:`read_text_retrying`: a read.

Each retries a Windows sharing violation (a reader or writer holding the file
for an instant), the policy ``retry=`` (keyword-only; default
:data:`dol.atomic.DFLT_RETRY`, which retries nothing off Windows, where the
same error means a real permission problem). A missing file is never retried.
Stdlib and dol only, so any module can use it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from dol.atomic import DFLT_RETRY, atomic_write

__all__ = ["read_text_retrying", "replace_retrying", "write_text_atomic"]


def write_text_atomic(path, text: str, *, retry: Optional[Callable] = None) -> None:
    """``text`` (UTF-8) to ``path`` atomically; parent folders are created."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, text.encode("utf-8"), retry=retry or DFLT_RETRY)


def replace_retrying(src, dst, *, retry: Optional[Callable] = None) -> None:
    """``os.replace(src, dst)``, retried on a sharing violation."""
    (retry or DFLT_RETRY)(os.replace, src, dst)


def read_text_retrying(path, *, retry: Optional[Callable] = None) -> str:
    """``path``'s UTF-8 text, retried on a sharing violation."""
    return (retry or DFLT_RETRY)(Path.read_text, Path(path), "utf-8")
