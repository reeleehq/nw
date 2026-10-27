"""Offline tests for :mod:`nw.batches` — one handle over many :mod:`nw.jobs`."""

import threading
import time

import pytest

import nw.batches as batches
import nw.jobs as jobs
from nw import Project


@pytest.fixture(autouse=True)
def _fresh_runtimes():
    jobs._reset_runtimes()
    yield
    jobs._reset_runtimes()


@pytest.fixture
def project(tmp_path):
    return Project.init(tmp_path / "proj", title="Batch Test")


def _stub(release: threading.Event, *, fail_on=()):
    def run(project, params, *, should_cancel):
        release.wait(timeout=5)
        if params["n"] in fail_on:
            raise RuntimeError(f"boom {params['n']}")
        return {"n": params["n"], "cost_usd_actual": 0.5}

    return run


def _items(n):
    return [{"params": {"n": i, "estimated_usd": 0.1}} for i in range(n)]


def test_roundtrip_partial_failure_keeps_successes(project):
    release = threading.Event()
    d = {"x": _stub(release, fail_on={1})}
    b = batches.enqueue_batch(project, _items(3), kind="x", dispatch=d)
    assert len(b.job_ids) == 3
    release.set()
    st = batches.wait(project, b.batch_id, 5)
    assert st["done"] and not st["timed_out"]
    assert st["counts"] == {"succeeded": 2, "failed": 1}
    assert st["cost"]["actual_usd"] == pytest.approx(1.0)
    out = batches.output(project, b.batch_id)
    assert [r["result"]["n"] for r in out["succeeded"]] == [0, 2]
    assert len(out["failed"]) == 1 and "boom" in out["failed"][0]["error"]
    assert out["cancelled"] == [] and out["pending"] == []


def test_wait_times_out_with_current_aggregate(project):
    release = threading.Event()
    b = batches.enqueue_batch(
        project, _items(2), kind="x", dispatch={"x": _stub(release)}
    )
    t0 = time.monotonic()
    st = batches.wait(project, b.batch_id, 0.2, poll_s=0.05)
    assert st["timed_out"] and not st["done"]
    assert time.monotonic() - t0 < 2
    assert len(batches.output(project, b.batch_id)["pending"]) == 2
    release.set()
    assert batches.wait(project, b.batch_id, 5)["done"]


def test_resubmission_is_the_same_batch(project):
    release = threading.Event()
    d = {"x": _stub(release)}
    a = batches.enqueue_batch(project, _items(2), kind="x", dispatch=d)
    b = batches.enqueue_batch(project, _items(2), kind="x", dispatch=d)
    assert a == b
    release.set()
    batches.wait(project, a.batch_id, 5)


def test_resubmitting_a_finished_batch_does_not_rerun(project):
    calls = []

    def run(project, params):
        calls.append(params["n"])
        return {"n": params["n"]}

    d = {"x": run}
    a = batches.enqueue_batch(project, _items(3), kind="x", dispatch=d)
    assert batches.wait(project, a.batch_id, 5)["done"]
    time.sleep(0.2)  # let worker threads exit
    b = batches.enqueue_batch(project, _items(3), kind="x", dispatch=d)
    assert a == b and sorted(calls) == [0, 1, 2]


def test_bad_item_launches_nothing(project):
    calls = []
    d = {"x": lambda project, params: calls.append(1)}
    for bad in ({"kind": "nope", "params": {"n": 9}}, {"parms": {}}):
        with pytest.raises((KeyError, ValueError)):
            batches.enqueue_batch(
                project, [*_items(2), bad], kind="x", dispatch=d
            )
    time.sleep(0.2)
    assert calls == [] and jobs.list_jobs(project) == []


def test_missing_member_never_reads_as_exact_cost(project):
    release = threading.Event()
    release.set()
    b = batches.enqueue_batch(
        project, _items(2), kind="x", dispatch={"x": _stub(release)}
    )
    batches.wait(project, b.batch_id, 5)
    rt = jobs._runtime(project)
    # Under the lock: ``wait`` wakes on the notifier, before the worker's
    # end-of-job announcement read-modify-writes the record (nw#151); an
    # unlocked delete can land inside it and be written back.
    with rt.lock:
        del rt.index[b.job_ids[1]]
    st = batches.status(project, b.batch_id)
    assert st["counts"] == {"succeeded": 1, "missing": 1} and st["done"]
    assert st["cost"]["actual_is_lower_bound"] is True
    assert st["cost"]["estimated_usd"] is None
    assert batches.output(project, b.batch_id)["failed"][0]["error_kind"] == "missing"


def test_wait_wakes_on_notification_not_just_poll(project):
    release = threading.Event()
    b = batches.enqueue_batch(
        project, _items(1), kind="x", dispatch={"x": _stub(release)}
    )
    threading.Timer(0.1, release.set).start()
    t0 = time.monotonic()
    st = batches.wait(project, b.batch_id, 5, poll_s=30)
    assert st["done"] and time.monotonic() - t0 < 2


def test_wait_rejects_bad_timeout(project):
    b = batches.enqueue_batch(
        project, _items(1), kind="x", dispatch={"x": lambda project, params: 1}
    )
    for bad in (None, -1):
        with pytest.raises((ValueError, TypeError)):
            batches.wait(project, b.batch_id, bad)


def test_cancel_batch_cancels_nonterminal_members(project):
    release = threading.Event()
    b = batches.enqueue_batch(
        project, _items(2), kind="x", dispatch={"x": _stub(release)}
    )
    batches.cancel_batch(project, b.batch_id)
    # Cancel is cooperative: a job whose worker is still alive reads
    # ``cancelling`` until that thread exits, so let the workers go first.
    release.set()
    st = batches.wait(project, b.batch_id, 5)
    assert st["done"] and st["counts"] == {"cancelled": 2}
    assert len(batches.output(project, b.batch_id)["cancelled"]) == 2


def test_unknown_batch_is_none(project):
    for fn in (batches.status, batches.output, batches.cancel_batch, batches.get_batch):
        assert fn(project, "batch-nope") is None
    assert batches.wait(project, "batch-nope", 0.1) is None


def test_estimate_batch_sums_and_unknown_forces_approval(project):
    est = batches.estimate_batch(project, _items(3), kind="x")
    assert est["estimated_usd"] == pytest.approx(0.3)
    assert not est["requires_approval"]
    big = batches.estimate_batch(
        project, [{"params": {"estimated_usd": 0.6}}] * 2, kind="x"
    )
    assert big["requires_approval"]  # 1.2 >= threshold
    unknown = batches.estimate_batch(project, [{"params": {"n": 1}}], kind="x")
    assert unknown["estimated_usd"] is None and unknown["requires_approval"]


def test_bad_items_are_refused(project):
    with pytest.raises(ValueError):
        batches.enqueue_batch(project, [], kind="x")
    with pytest.raises(ValueError):
        batches.enqueue_batch(project, [{"params": {}}])  # no kind


def test_notifier_is_per_project_and_wakes_promptly(tmp_path):
    a = Project.init(tmp_path / "a", title="A")
    b = Project.init(tmp_path / "b", title="B")
    release = threading.Event()
    job = jobs.enqueue(a, "x", {"n": 1}, dispatch={"x": _stub(release)})
    na, nb = jobs.job_notifier(a), jobs.job_notifier(b)
    seen_a, seen_b = na.count(), nb.count()
    threading.Timer(0.1, release.set).start()
    t0 = time.monotonic()
    na.wait(seen_a, 5)
    assert na.count() > seen_a and time.monotonic() - t0 < 2  # woken, not timed out
    # the waiter can re-enqueue the key at once: the worker is no longer "running"
    assert not jobs._runtime(a).middleware.is_running(job.job_id)
    assert jobs.get_job(a, job.job_id).status in jobs.TERMINAL_STATUSES
    assert nb.count() == seen_b  # another project's notifier never moved


def test_cancel_wakes_a_waiting_batch(project):
    release = threading.Event()
    b = batches.enqueue_batch(
        project, _items(1), kind="x", dispatch={"x": _stub(release)}
    )
    def cancel_then_let_the_worker_exit():
        batches.cancel_batch(project, b.batch_id)
        release.set()  # cancel is cooperative: the job reads cancelling until the worker exits

    threading.Timer(0.1, cancel_then_let_the_worker_exit).start()
    t0 = time.monotonic()
    st = batches.wait(project, b.batch_id, 5, poll_s=30)
    assert st["done"] and time.monotonic() - t0 < 2


def test_a_host_enqueue_door_is_used_for_every_member(project):
    """The ``enqueue=`` seam: a host routes members through its own single-job door."""
    release = threading.Event()
    release.set()
    d = {"x": _stub(release)}
    calls = []

    def door(project, **kwargs):
        calls.append(kwargs["params"]["n"])
        return jobs.enqueue(project, **kwargs)

    b = batches.enqueue_batch(project, _items(3), kind="x", dispatch=d, enqueue=door)
    assert calls == [0, 1, 2]
    assert batches.wait(project, b.batch_id, 5)["counts"] == {"succeeded": 3}


def test_an_enqueue_that_changes_the_job_is_refused(project):
    release = threading.Event()
    release.set()
    d = {"x": _stub(release)}

    def rewriting_door(project, *, params, **kwargs):
        return jobs.enqueue(project, params={**params, "n": params["n"] + 100}, **kwargs)

    with pytest.raises(ValueError, match="must not change the job"):
        batches.enqueue_batch(project, _items(1), kind="x", dispatch=d, enqueue=rewriting_door)
    # the record would point at the wrong job, so none is written
    assert list(batches._store(project.root, jobs.DEFAULT_CONFIG)) == []
