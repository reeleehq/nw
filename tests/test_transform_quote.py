"""``BaseTransform.quote``: what ``execute`` spends outside the Plan (nw#284)."""

from __future__ import annotations

from nw.transforms import BaseTransform


def test_a_transform_spends_nothing_outside_its_plan_by_default():
    assert BaseTransform().quote(()) == 0.0


def test_a_transform_can_declare_unknown_outside_spend():
    class Pays(BaseTransform):
        def quote(self, skeletons):
            return None  # unknown, never free

    assert Pays().quote(()) is None
