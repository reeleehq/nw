"""Turning a caller-editable id into a file name that cannot leave its directory.

An id that came out of a body a caller can edit (a storyboard panel's
``panel_id``, a clip's id, a take's key) is *data*, and joining data onto a
directory as ``dir / f"{id}.png"`` lets ``../../x`` write anywhere the process
can. :func:`safe_path_segment` is the one mapping from such an id to a single
path segment, shared by every genre that names files after ids (nw#220; reelee
fixed the same pattern for its Ken Burns clips in reelee#930).

The mapping, and why each part is there:

- **An id that is already a safe slug is kept as is**, so the file of a panel
  that has always rendered to ``storyboard/<panel_id>.png`` keeps that name and
  a re-render still overwrites it.
- **Anything else becomes its slug, a ``.`` and a short digest of the id.** The
  digest keeps two odd ids that slug alike (``a/b``, ``a\\b``) apart, and the
  ``.`` is never in a kept id, so a mapped name cannot equal a kept one.
- **The name fits a file name's byte limit**, suffix included, and never spells
  a Windows device name (``CON``, ``NUL``, ``COM1`` …), which Windows refuses
  whatever the extension.

Not handled: two kept ids differing only in case (``Panel1``, ``panel1``) share
a file on a case-insensitive filesystem, so editing an id to ``P0A1`` beside
``p0a1`` overwrites that file — inside the directory, never outside it. Folding
case would rename every existing mixed-case file, and the ids artful mints
(``new_panel_id``) are lowercase.

No dependency beyond the standard library.
"""

from __future__ import annotations

import hashlib
import re

__all__ = ["MAX_NAME_BYTES", "is_kept", "safe_path_segment"]

MAX_NAME_BYTES = 255
"""The longest file name, in bytes, the filesystems nw runs on accept."""

_DIGEST_LEN = 8
"""Hex characters of the id's SHA-256 a mapped name carries. Part of every
mapped file's identity: changing it renames those files, so it is not a knob."""

_KEPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
"""An id kept verbatim: ASCII letters, digits, ``_`` and ``-``, not led by a
punctuation mark. No ``.``, which is what keeps mapped names disjoint."""

_UNSAFE_RUN = re.compile(r"[^A-Za-z0-9_-]+")
_WINDOWS_DEVICE = re.compile(r"(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])", re.IGNORECASE)


def is_kept(name: str) -> bool:
    """Whether :func:`safe_path_segment` keeps ``name`` verbatim (its stem).

    >>> is_kept("p0a1"), is_kept("x.9cdf6a50"), is_kept("nul")
    (True, False, False)
    """
    return bool(_KEPT.fullmatch(name)) and not _WINDOWS_DEVICE.fullmatch(name)


def safe_path_segment(
    value: str,
    *,
    suffix: str = "",
    max_bytes: int = MAX_NAME_BYTES,
) -> str:
    """A single file name for ``value`` (plus ``suffix``) that is always a direct
    child of the directory it is joined to.

    >>> safe_path_segment("p0a1", suffix=".png")
    'p0a1.png'
    >>> safe_path_segment("../../x", suffix=".png")
    'x.9cdf6a50.png'
    >>> safe_path_segment("..")
    '_.5ec1f7e7'
    >>> safe_path_segment("con", suffix=".png")
    '_con.1143da2b.png'

    Deterministic, so the same id always lands on the same file. ``suffix`` is
    appended verbatim and is the caller's (a literal like ``".png"``, never
    data). Raises ``ValueError`` when ``suffix`` leaves no room for a name
    within ``max_bytes``.
    """
    if not isinstance(value, str):
        raise TypeError(f"safe_path_segment: value must be a str, got {type(value)}")
    room = max_bytes - len(suffix.encode("utf-8"))
    if is_kept(value) and len(value) <= room:
        return value + suffix
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:_DIGEST_LEN]
    slug_room = room - len(".") - len(digest)
    if slug_room < 1:
        raise ValueError(
            f"safe_path_segment: suffix {suffix!r} leaves no room for a name "
            f"within {max_bytes} bytes"
        )
    slug = _UNSAFE_RUN.sub("-", value).strip("-_")[:slug_room]
    if not slug or _WINDOWS_DEVICE.fullmatch(slug):
        slug = ("_" + slug)[:slug_room]
    return f"{slug}.{digest}{suffix}"
