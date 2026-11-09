"""No new raw path join of an interpolated string outside ``nw.paths`` (nw#253).

``directory / f"{panel_id}.png"`` lets an id edited to ``../../x`` write
anywhere the process can (nw#220). An id that came from a caller goes through
:func:`nw.paths.safe_path_segment` (map) or :func:`nw.paths.check_path_segment`
(validate). This test finds every path join in ``nw/`` whose new segment is an
f-string with an interpolated value (or built with ``+``, ``%`` or
``.format``) — as ``d / s``, ``d /= s``, ``d.joinpath(s)`` or
``os.path.join(d, s)`` — and fails on any not in :data:`ALLOWED`. Entries are
keyed by the enclosing function, so a new copy of an allowed expression
elsewhere is not allowed by it.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import nw

NW_DIR = Path(nw.__file__).parent
EXEMPT = {"paths.py"}  # the module whose job this is

ALLOWED: dict[str, str] = {
    "media_store.py:SharedMediaStore.register_catalog: f'{key}.json'":
        "key is a 24-hex sha256 prefix of the resolved rows dir",
    "media_store.py:SharedMediaStore.unregister_catalog: f'{key}.json'":
        "key is a 24-hex sha256 prefix of the resolved rows dir",
    "media_store.py:SharedMediaStore._referenced_now: f'{aid}.json'":
        "aid comes from sweep, which lists only is_content_digest blob names",
    "media_catalog.py:HostArtifactCatalog.has: f'{artifact_id}.json'":
        "the `and` short-circuits on blob_path, which checks is_content_digest",
    "media_catalog.py:HostArtifactCatalog.register: f'{aid}.json'":
        "aid is checked by _check_digest just before",
}
"""``"<file>:<function>: <segment source>"`` → why it is safe. Add an entry only
with a reason a reviewer can check; otherwise route the id through nw.paths."""


def _interpolated(node) -> bool:
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    )


def _segments(node):
    """The joined-in segment(s) of a path join, or nothing."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        yield node.right
    elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Div):
        yield node.value
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "joinpath":
            yield from node.args
        elif node.func.attr == "join" and ast.unparse(node.func.value) == "os.path":
            yield from node.args[1:]


def _raw_joins() -> Counter:
    found: Counter = Counter()
    for path in sorted(NW_DIR.rglob("*.py")):
        rel = path.relative_to(NW_DIR).as_posix()
        if rel in EXEMPT:
            continue

        def visit(node, scope):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = f"{scope}.{node.name}" if scope else node.name
            for seg in _segments(node):
                if _interpolated(seg):
                    found[f"{rel}:{scope}: {ast.unparse(seg)}"] += 1
            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(ast.parse(path.read_text(encoding="utf-8")), "")
    return found


def test_every_raw_path_join_is_known_safe():
    found = _raw_joins()
    unexplained = sorted(k for k in found if k not in ALLOWED)
    repeated = sorted(k for k, n in found.items() if k in ALLOWED and n > 1)
    assert not unexplained and not repeated, (
        "A path joined from an interpolated string; if any part can come from a "
        "caller, route it through nw.paths.safe_path_segment / check_path_segment, "
        "else add it to ALLOWED with the reason (one site per entry):\n  "
        + "\n  ".join(unexplained + [f"{k} (x{found[k]})" for k in repeated])
    )


def test_the_allow_list_has_no_stale_entries():
    """An entry whose code is gone would quietly allow its next reappearance."""
    stale = set(ALLOWED) - set(_raw_joins())
    assert not stale, f"ALLOWED entries no longer in the code: {sorted(stale)}"


def test_clear_mark_refuses_a_raw_id(tmp_path):
    import pytest

    from nw.media_store import SharedMediaStore

    store = SharedMediaStore(tmp_path / "store")
    (tmp_path / "victim").write_text("x")
    with pytest.raises(ValueError, match="content digest"):
        store.clear_mark("../../../victim")
    assert (tmp_path / "victim").exists()
    store.clear_mark("ab" * 32)  # a digest with no mark: a no-op
