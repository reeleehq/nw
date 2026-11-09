"""No new raw f-string path join of a caller's id outside ``nw.paths`` (nw#253).

``directory / f"{panel_id}.png"`` lets an id edited to ``../../x`` write
anywhere the process can (nw#220). An id that came from a caller goes through
:func:`nw.paths.safe_path_segment` (map) or :func:`nw.paths.check_path_segment`
(validate). This test finds every ``<path> / f"..."`` with an interpolated
value in ``nw/`` and fails on any not in :data:`ALLOWED`, each of which names
why its value cannot be a caller's.
"""

from __future__ import annotations

import ast
from pathlib import Path

import nw

NW_DIR = Path(nw.__file__).parent

ALLOWED: dict[str, str] = {
    "media_store.py: f'{key}.json'": "key is a sha256 prefix of the resolved rows dir",
    "media_store.py: f'{aid}.json'": "aid is a content digest (is_content_digest checked)",
    "media_catalog.py: f'{artifact_id}.json'": "artifact_id is checked by is_content_digest first",
    "media_catalog.py: f'{aid}.json'": "aid is a content digest (_check_digest)",
}
"""``"<file>: <f-string source>"`` → why it is safe. Add an entry only with a
reason a reviewer can check; otherwise route the id through ``nw.paths``."""


def _raw_joins() -> set[str]:
    found = set()
    for path in sorted(NW_DIR.rglob("*.py")):
        if path.name == "paths.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Div)
                and isinstance(node.right, ast.JoinedStr)
                and any(isinstance(v, ast.FormattedValue) for v in node.right.values)
            ):
                rel = path.relative_to(NW_DIR).as_posix()
                found.add(f"{rel}: {ast.unparse(node.right)}")
    return found


def test_every_raw_f_string_path_join_is_known_safe():
    unexplained = _raw_joins() - set(ALLOWED)
    assert not unexplained, (
        "A path joined from an f-string with an interpolated value; if any part "
        "can come from a caller, route it through nw.paths.safe_path_segment / "
        "check_path_segment, else add it to ALLOWED with the reason:\n  "
        + "\n  ".join(sorted(unexplained))
    )


def test_the_allow_list_has_no_stale_entries():
    """An entry whose code is gone would quietly allow its next reappearance."""
    stale = set(ALLOWED) - _raw_joins()
    assert not stale, f"ALLOWED entries no longer in the code: {sorted(stale)}"
