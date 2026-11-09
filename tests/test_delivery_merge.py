"""nw.delivery.drop_guest_placed_duplicates: one row per placed project (nw#231)."""

from __future__ import annotations

from nw.delivery import PLACED_META_KEY, ProjectSummary, drop_guest_placed_duplicates

OWNERS = {"music_video": "muvid", "commentary_weave": "braidio"}


def _merge(rows, genres):
    calls = []

    def genre_of(pid):
        calls.append(pid)
        return genres.get(pid)

    out = drop_guest_placed_duplicates(
        rows, host="reelee", genre_of=genre_of, owner_of=OWNERS.get
    )
    return [(r.project_id, r.genre) for r in out], calls


def test_a_host_row_the_guest_also_listed_is_dropped():
    rows = [ProjectSummary("mv1", genre="reelee"), ProjectSummary("mv1", genre="muvid")]
    out, calls = _merge(rows, {"mv1": "music_video"})
    assert out == [("mv1", "muvid")] and calls == ["mv1"]


def test_a_host_project_that_merely_shares_an_id_is_kept():
    rows = [ProjectSummary("x", genre="reelee"), ProjectSummary("x", genre="muvid")]
    out, _ = _merge(rows, {"x": "reelee_story"})  # recorded genre is not muvid's
    assert out == [("x", "reelee"), ("x", "muvid")]


def test_a_guest_that_lists_no_placed_projects_collides_with_nothing():
    rows = [ProjectSummary("mv1", genre="reelee"), ProjectSummary("other", genre="muvid")]
    out, calls = _merge(rows, {"mv1": "music_video"})
    assert out == [("mv1", "reelee"), ("other", "muvid")] and calls == []


def test_a_placed_marker_decides_without_a_genre_read():
    rows = [
        ProjectSummary("mv1", genre="reelee"),
        ProjectSummary("mv1", genre="muvid", meta={PLACED_META_KEY: True}),
    ]
    out, calls = _merge(rows, {})
    assert out == [("mv1", "muvid")] and calls == []


def test_only_host_rows_are_ever_dropped_and_order_is_kept():
    rows = [
        ProjectSummary("a", genre="muvid"),
        ProjectSummary("b", genre="reelee"),
        ProjectSummary("a", genre="braidio"),
        ProjectSummary("c", genre="reelee"),
    ]
    out, _ = _merge(rows, {})
    assert out == [("a", "muvid"), ("b", "reelee"), ("a", "braidio"), ("c", "reelee")]


def test_an_unknown_genre_keeps_the_host_row():
    rows = [ProjectSummary("mv1", genre="reelee"), ProjectSummary("mv1", genre="muvid")]
    out, _ = _merge(rows, {"mv1": None})
    assert out == [("mv1", "reelee"), ("mv1", "muvid")]


def test_with_two_guests_on_one_id_only_the_owner_counts():
    rows = [
        ProjectSummary("mv1", genre="reelee"),
        ProjectSummary("mv1", genre="braidio"),
        ProjectSummary("mv1", genre="muvid"),
    ]
    out, _ = _merge(rows, {"mv1": "music_video"})  # muvid's genre
    assert out == [("mv1", "braidio"), ("mv1", "muvid")]
    out, _ = _merge(rows, {"mv1": "reelee_story"})  # neither guest's
    assert out == [("mv1", "reelee"), ("mv1", "braidio"), ("mv1", "muvid")]
