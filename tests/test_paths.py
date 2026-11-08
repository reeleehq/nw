"""nw.paths.safe_path_segment: an editable id never names a file outside its dir (nw#220)."""

from __future__ import annotations

import pytest

from nw.paths import MAX_NAME_BYTES, is_kept, safe_path_segment

HOSTILE = [
    "../../x",
    "..",
    ".",
    "",
    "/etc/passwd",
    "a\\..\\b",
    "a/b",
    "x\x00y",
    ".hidden",
    "-leading",
    "é/ü",
    "CON",
    "nul",
    "com1",
    "x" * 400,
]


@pytest.mark.parametrize("value", HOSTILE)
def test_a_hostile_id_stays_a_direct_child(tmp_path, value):
    name = safe_path_segment(value, suffix=".png")
    assert (tmp_path / name).resolve().parent == tmp_path.resolve()
    assert "/" not in name and "\\" not in name and "\x00" not in name
    assert not name.startswith(".")
    assert len(name.encode("utf-8")) <= MAX_NAME_BYTES
    assert name.split(".")[0].upper() not in {"CON", "PRN", "AUX", "NUL", "COM1"}


@pytest.mark.parametrize("value", ["p0a1", "panel_7", "A-b_9", "p3f7c1"])
def test_a_safe_slug_keeps_its_historical_name(value):
    assert safe_path_segment(value, suffix=".png") == f"{value}.png"


def test_ids_that_slug_alike_do_not_share_a_file():
    names = {safe_path_segment(v) for v in ["a/b", "a\\b", "a b", "a-b"]}
    assert len(names) == 4  # "a-b" is kept; the other three carry distinct digests


@pytest.mark.parametrize("value", HOSTILE)
def test_a_mapped_name_is_never_a_kept_one(value):
    """So no kept id can ever name the file a hostile id was mapped to."""
    assert not is_kept(safe_path_segment(value))


def test_deterministic():
    assert safe_path_segment("../../x") == safe_path_segment("../../x")


def test_the_byte_limit_counts_the_suffix_and_is_configurable():
    name = safe_path_segment("x" * 300, suffix=".png", max_bytes=40)
    assert len(name.encode()) <= 40 and name.endswith(".png")
    assert safe_path_segment("x" * 36, suffix=".png", max_bytes=40) == "x" * 36 + ".png"


def test_a_suffix_leaving_no_room_is_refused():
    with pytest.raises(ValueError, match="no room"):
        safe_path_segment("../x", suffix="." + "p" * 250)


def test_a_non_string_is_refused():
    with pytest.raises(TypeError):
        safe_path_segment(None)  # type: ignore[arg-type]


# --- the validating half: check_path_segment (nw#227) ------------------------

import re  # noqa: E402

from nw.paths import check_path_segment  # noqa: E402


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "../x", "a\\b", "x\x00y"])
def test_check_path_segment_refuses_anything_but_one_child(bad):
    with pytest.raises(ValueError, match="invalid name"):
        check_path_segment(bad, what="name")


def test_check_path_segment_returns_a_good_name_unchanged():
    assert check_path_segment("ep_01") == "ep_01"
    assert check_path_segment(" padded ") == " padded "  # no silent rewrite


def test_a_stricter_pattern_is_the_callers_policy():
    slug = re.compile(r"[a-z0-9-]+")
    assert check_path_segment("ok-1", pattern=slug) == "ok-1"
    with pytest.raises(ValueError):
        check_path_segment("Not A Slug", pattern=slug)


def test_a_non_string_is_refused_by_the_validator_too():
    with pytest.raises(ValueError):
        check_path_segment(None)  # type: ignore[arg-type]


def test_character_and_environment_names_cannot_leave_the_project(tmp_path):
    import nw

    proj = nw.Project.init(tmp_path / "p")
    with pytest.raises(ValueError, match="character name"):
        proj.add_character("../../escape")
    with pytest.raises(ValueError, match="environment name"):
        proj.add_environment("../escape")
    assert not (tmp_path / "escape").exists()
    proj.add_character("thor")  # an ordinary name still works
    assert (tmp_path / "p" / "characters" / "thor").is_dir()
