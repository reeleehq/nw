"""``Project.lock(name)``: exclusive across two opens of one project (nw#113).

SQLite contention is tested here; the cross-connection Postgres case lives in
``test_graph_backend_postgres.py`` (env-gated on a local Postgres).
"""

from __future__ import annotations

import threading

import nw


def _project(tmp_path):
    return nw.Project.init(tmp_path / "p", title="locked")


def test_lock_excludes_a_second_open_of_the_same_project(tmp_path):
    first = _project(tmp_path)
    second = nw.Project(first.root)
    inside, attempting, acquired = (threading.Event() for _ in range(3))
    order: list[str] = []

    def contender():
        inside.wait(5)
        attempting.set()
        with second.lock("meta"):
            order.append("second")
            acquired.set()

    t = threading.Thread(target=contender, daemon=True)
    t.start()
    with first.lock("meta"):
        inside.set()
        assert attempting.wait(5)
        # The contender is blocked while we hold the lock.
        assert not acquired.wait(0.5)
        order.append("first")
    t.join(5)
    assert not t.is_alive() and acquired.is_set()
    assert order == ["first", "second"]


def test_different_names_do_not_exclude_each_other(tmp_path):
    first = _project(tmp_path)
    second = nw.Project(first.root)
    done = threading.Event()

    def take_b():
        with second.lock("b"):
            done.set()

    with first.lock("a"):
        threading.Thread(target=take_b, daemon=True).start()
        assert done.wait(5)


def test_lock_is_released_when_the_block_raises(tmp_path):
    proj = _project(tmp_path)
    try:
        with proj.lock("meta"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with nw.Project(proj.root).lock("meta"):
        pass
