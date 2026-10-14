"""The shipped ``nw`` skill (nw#102) exists, is spec-clean, and names only real API.

A session discovers nw through this skill's ``description``, so the checks pin the
parts discovery depends on: location (one canonical, non-hidden place that also
ships in the wheel), ``name`` == folder, the 1024-character description limit, the
trigger phrases the issue asks for, and that every ``nw.<name>`` it cites resolves.
"""

import re
from pathlib import Path

import pytest

import nw

_REPO = Path(__file__).resolve().parents[1]
_SKILLS = Path(nw.__file__).parent / "data" / "skills"
_SKILL = _SKILLS / "nw" / "SKILL.md"
_TRIGGERS = (
    "AV project folder",
    "narrative workflow",
    "prepare → plan → execute",
    "what is stale",
    "genre",
    "render this project",
    "which shots need re-rendering",
)


def _frontmatter(text: str) -> dict:
    block = re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)
    name = re.search(r"^name:\s*(\S+)", block, re.M).group(1)
    desc = re.search(r"^description:\s*>-\n((?:  .*\n?)+)", block, re.M).group(1)
    return {"name": name, "description": " ".join(desc.split())}


def test_skill_is_the_only_real_skill_and_lives_inside_the_package():
    found = [
        p
        for p in _REPO.rglob("SKILL.md")
        if ".git" not in p.parts and not any(q.is_symlink() for q in p.parents)
    ]
    assert found == [_SKILL]


def test_frontmatter_is_spec_clean():
    fm = _frontmatter(_SKILL.read_text())
    assert fm["name"] == _SKILL.parent.name == "nw"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fm["name"])
    assert len(fm["description"]) <= 1024


def test_description_carries_the_discovery_triggers():
    desc = _frontmatter(_SKILL.read_text())["description"].lower()
    missing = [t for t in _TRIGGERS if t.lower() not in desc]
    assert not missing, missing


def test_claude_bridge_is_a_relative_symlink_to_the_canonical_skill():
    link = _REPO / ".claude" / "skills" / "nw"
    assert link.is_symlink() and not Path(link.readlink()).is_absolute()
    assert link.resolve() == _SKILL.parent.resolve()


@pytest.mark.parametrize(
    "ref",
    sorted(set(re.findall(r"`nw\.([A-Za-z_][\w.]*)", _SKILL.read_text()))),
)
def test_cited_api_exists(ref):
    obj = nw
    for part in ref.split("."):
        obj = getattr(obj, part)
