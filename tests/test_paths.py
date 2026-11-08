"""nw.paths.safe_path_segment: an editable id never names a file outside its dir (nw#220)."""

from __future__ import annotations

import pytest

from nw.paths import MAX_NAME_BYTES, safe_path_segment

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


def test_a_mapped_name_never_equals_a_kept_one():
    mapped = safe_path_segment("../x")
    assert "." in mapped
    assert safe_path_segment(mapped) != mapped  # a kept id never contains "."


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
