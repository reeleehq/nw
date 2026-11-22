"""Placing validation (nw#285): settings, selection precedence, profiles, rows and vetoes."""

from __future__ import annotations

import pytest

from nw.validation import (
    CheckResult,
    Finding,
    ValidationReport,
    ValidationSettings,
    checked_settings,
    menu,
    menu_rows,
    package_profiles,
    select,
    unreachable_row,
    veto_message,
)

PLACES = ("before_present", "before_publish")


def _two_checks():
    names = [c.name for c in menu()]
    assert len(names) >= 2, "the built-in checks are registered"
    return names[0], names[1]


def test_nothing_is_selected_unless_someone_asked():
    assert select("before_publish", environ={}) == ()
    assert select("before_publish", environ={}, settings=ValidationSettings()) == ()


def test_selection_precedence_explicit_then_environment_then_settings():
    a, b = _two_checks()
    settings = {"placements": {"before_publish": [b]}}
    env = {"NW_VALIDATE_BEFORE_PUBLISH": f" {a} ,"}
    assert select("before_publish", checks=[b], settings=settings, environ=env) == (b,)
    assert select("before_publish", settings=settings, environ=env) == (a,)
    assert select("before_publish", settings=settings, environ={}) == (b,)
    # a host names its own variables
    assert select("before_publish", environ={"REELEE_VALIDATE_BEFORE_PUBLISH": a},
                  env_prefix="REELEE_VALIDATE_") == (a,)  # fmt: skip


def test_profiles_expand_once_each_and_cheap_never_holds_a_paid_check():
    a, b = _two_checks()
    settings = {"profiles": {"mine": [a, b]}, "placements": {"before_present": ["mine", a]}}
    assert select("before_present", settings=settings, environ={}) == (a, b)
    cheap = package_profiles()["cheap"]
    costs = {c.name: c.cost for c in menu()}
    assert cheap and all(costs[n] in ("free", "cheap") for n in cheap)


def test_a_typo_or_an_unknown_placement_is_refused_not_ignored():
    with pytest.raises(ValueError, match="no validation check or profile"):
        select("before_publish", checks=["media.typo"], environ={})
    with pytest.raises(ValueError, match="unknown placement"):
        select("after_lunch", environ={}, placements=PLACES)
    with pytest.raises(ValueError, match="unknown placement"):
        checked_settings({"placements": {"after_lunch": ["cheap"]}}, placements=PLACES)
    with pytest.raises(ValueError, match="settings refused"):
        checked_settings({"placement": {}})
    with pytest.raises(ValueError, match="must be an object"):
        checked_settings(["cheap"])


def test_menu_rows_carry_what_a_model_matches_and_the_package_profiles():
    rows = menu_rows()
    by_name = {r["name"]: r for r in rows}
    for c in menu():
        assert by_name[c.name]["cost"] == c.cost
        assert by_name[c.name]["example_requests"] == list(c.example_requests)
    assert by_name["cheap"]["profile"] == list(package_profiles()["cheap"])


def test_a_report_row_never_counts_a_check_that_did_not_run_as_a_pass_and_the_veto_says_why():
    report = ValidationReport(
        "cut.mp4",
        (
            CheckResult("media.encode_complete", (Finding("media.encode_complete", "error",
                        "half encoded", remedy="re-encode it"),)),  # fmt: skip
            CheckResult("media.no_long_freeze", skipped="ffmpeg not found"),
            CheckResult("media.streams_present", error="boom"),
        ),
    )
    row = report.row()
    assert row["ok"] is False
    assert row["failed"] == ["media.encode_complete"]
    assert row["could_not_run"] == ["media.no_long_freeze"]
    assert row["errored"] == ["media.streams_present"]
    assert row["remedies"] == ["re-encode it"]
    msg = veto_message([row, unreachable_row("b.mp4", ["media.encode_complete"], "not fetched")],
                       where="validation before publish")  # fmt: skip
    assert msg.startswith("validation before publish: media.encode_complete failed on cut.mp4: re-encode it")
    assert "media.no_long_freeze could not run on cut.mp4 (ffmpeg not found)" in msg
    assert "media.streams_present errored on cut.mp4 (boom)" in msg
    assert "on b.mp4 (not fetched)" in msg
    assert veto_message([ValidationReport("ok.mp4", (CheckResult("x"),)).row()]) is None
