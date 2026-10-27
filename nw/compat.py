"""What a plugin built against a newer nw checks before it registers (nw#164).

A genre plugin passes keywords to nw's types (``GenreOp(invalidates=...)``,
nw#161). When the installed nw predates one of them, a missing *name* fails
``import nw`` loudly, but a missing *keyword* fails as ``TypeError: ...
unexpected keyword argument``, which names neither nw nor the fix. A plugin
often gets nw through a host that pins an older floor than the plugin's own
extra, so this happens in practice.

:func:`require_fields` asks the class, never a version number: an editable
checkout records a stale version, so a version compare would refuse a working
source tree. Call it before registering anything, so a refusal leaves no
half-registered genre behind::

    >>> from nw import GenreOp
    >>> require_fields(GenreOp, ["name", "fn", "invalidates"])
    >>> require_fields(GenreOp, {"name": "x", "teleport": True})
    Traceback (most recent call last):
      ...
    nw.compat.NwTooOldError: the installed nw's GenreOp takes no keyword 'teleport'; upgrade nw

``require_fields`` itself is new, so a plugin that may meet an nw from before
it guards the import too; past that, the plugin's nw floor only needs to
cover the nw that added ``require_fields``::

    try:
        from nw import require_fields
    except ImportError as e:  # an nw from before nw#164
        raise ImportError("myplugin needs a newer nw; install myplugin[nw]") from e
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable

DFLT_REMEDY = "upgrade nw"


class NwTooOldError(ImportError):
    """The installed nw lacks something a plugin needs. An ``ImportError``
    because it is raised while the plugin is being imported and registered,
    where an environment that cannot provide a dependency is reported."""


def require_fields(
    cls: type, fields: Iterable[str], *, remedy: str = DFLT_REMEDY
) -> None:
    """Raise :class:`NwTooOldError` unless ``cls`` accepts every keyword in
    ``fields`` (names, or a mapping whose keys are the names).

    The error names nw, the class, each missing keyword and ``remedy`` (say
    which extra or floor carries the right nw). A class whose constructor
    takes ``**kwargs`` accepts everything; a positional-only parameter is not
    a keyword, so it does not count. A bare ``str`` is refused with
    ``TypeError``: iterated, it would blame nw for lacking each letter.
    """
    if isinstance(fields, str):
        raise TypeError(f"fields must be names, not one string: {fields!r}")
    params = inspect.signature(cls).parameters.values()
    if any(p.kind is p.VAR_KEYWORD for p in params):
        return
    keywords = {p.name for p in params if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    missing = sorted(set(fields) - keywords)
    if missing:
        names = ", ".join(repr(m) for m in missing)
        plural = "s" if len(missing) > 1 else ""
        raise NwTooOldError(
            f"the installed nw's {cls.__qualname__} takes no keyword{plural} "
            f"{names}; {remedy}"
        )
