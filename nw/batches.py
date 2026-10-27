"""nw.batches — many jobs, one handle: submit / status / wait / output / cancel.

An agent driving a 200-shot fan-out should not burn a turn per poll and track
N job ids (reelee#261 B). A **batch** is a small durable record beside the job
records (``<jobs_dirname>/batches/<batch_id>.json``: ``batch_id``, the ordered
``job_ids``, a ``label``, ``created_at``). Everything else is *computed from the
member jobs on read* and never stored, so a batch cannot drift from its jobs:

- :func:`enqueue_batch` enqueues each item through :func:`nw.jobs.enqueue`, so
  idempotency, ETA, cost, heartbeat and the reaper stay per-job and unchanged.
  The ``batch_id`` is a pure function of the ordered job ids, so re-submitting
  the same batch returns the same batch (and, per job, the same live jobs).
- :func:`status` — counts per job status, summed cost, ``done``.
- :func:`wait` — blocks until every member is terminal or ``timeout`` elapses,
  then returns the current aggregate with ``timed_out``. Distinct from
  :func:`status`, which never blocks. Woken by the project's :class:`nw.jobs.JobNotifier`
  (job finish / cancel) and re-checking at ``poll_s`` regardless, because the
  reaper and cross-process workers change a job without notifying anyone here.
- :func:`output` — a partially failed batch yields its successes *and* its
  failures, never an all-or-nothing error.
- :func:`estimate_batch` — the cost gate: the sum of per-item
  :func:`nw.jobs.estimate`; an unknown item makes the whole batch unknown and
  therefore approval-requiring (``None`` is never free).
- :func:`cancel_batch` — cancels every non-terminal member (job cancel is
  idempotent and a no-op on a finished job).

Items are mappings ``{"kind": ..., "params": {...}}`` (optionally ``label``,
``idempotency_key``, and ``estimated_usd`` — a host's own price for that
member, kept out of its job id, nw#144); a batch-level ``kind=`` is the default for items that omit
one. Item identity should be semantic (see :mod:`nw.transforms.fanout`'s
``mapping_key``): the default idempotency key hashes ``params``.

Cost gating of the *spender* (a per-caller cap) belongs to the host's
``enqueue`` door, exactly as for a single job; this module adds only the dry-run.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from nw import jobs as _jobs
from nw.jobs import DEFAULT_CONFIG, JobsConfig

BATCHES_DIRNAME = "batches"
"""Sub-directory of ``config.jobs_dirname`` holding batch records."""

DEFAULT_POLL_S = 0.25
"""How often :func:`wait` re-reads the members when nothing notifies it."""

MISSING = "missing"
"""Status key for a member whose job record is gone (it will never finish)."""

_BATCH_ID_PREFIX = "batch-"
_BATCH_ID_HEX_LEN = 16


@dataclass(frozen=True)
class BatchRecord:
    """The durable part of a batch. Everything else is derived from the jobs."""

    batch_id: str
    job_ids: tuple[str, ...]
    label: str
    created_at: str

    def to_dict(self) -> dict:
        return {**asdict(self), "job_ids": list(self.job_ids)}


# ---------------------------------------------------------------------------
# Submit / estimate
# ---------------------------------------------------------------------------


def enqueue_batch(
    project,
    items: Iterable[Mapping[str, Any]],
    *,
    kind: str | None = None,
    label: str | None = None,
    config: JobsConfig = DEFAULT_CONFIG,
    enqueue: Callable[..., _jobs.Job] | None = None,
    **enqueue_kwargs,
) -> BatchRecord:
    """Enqueue every item as a job and record the batch. Never blocks.

    ``enqueue_kwargs`` (``dispatch``, ``on_event``, ``secrets``,
    ``capture_context``, ``backend``) go to each ``enqueue`` call unchanged.
    Every item is validated (keys, ``kind`` in ``dispatch``, ``units``) before
    the first one launches, so a bad item leaves nothing running. Re-submitting
    a batch that exists returns it without enqueueing.

    ``enqueue`` (default :func:`nw.jobs.enqueue`, called with the same
    arguments) is the seam for a host's own single-job door, so a batch member
    is enqueued exactly as a lone job would be. It must enqueue the job
    the item names (it may add server-side params only if they do not change
    the job id): a returned job whose id differs from the item's raises
    ``ValueError`` and no batch is recorded, because the record would point at
    the wrong job. That is a host bug, so it is raised loudly, not repaired:
    the members enqueued before it keep running, and a retry may relaunch the
    ones that have finished (and bill them again). With a custom ``enqueue``
    and no ``dispatch``, the up-front ``kind``-in-``dispatch`` check is
    skipped: the door owns its dispatch, so it owns that check.

    Items resolving to the same job collapse to one member (first position wins).
    """
    specs = _item_specs(items, kind, dispatch=enqueue_kwargs.get("dispatch"))
    spec_ids = _spec_job_ids(project, specs)
    # ordered set: items resolving to one job collapse
    ids = tuple(dict.fromkeys(spec_ids))
    batch_id = _batch_id(ids)
    store = _store(project.root, config, create=True)
    if batch_id in store:
        # Re-submission returns the batch; it does NOT re-enqueue, because
        # ``enqueue`` re-launches a key whose job has finished and that would
        # bill the whole batch again.
        return _record_from(store[batch_id])
    door = enqueue or _jobs.enqueue
    for spec, expected in zip(specs, spec_ids):
        job = door(project, config=config, **spec, **enqueue_kwargs)
        if job.job_id != expected:
            raise ValueError(
                f"enqueue returned job {job.job_id!r} for a batch item that names "
                f"{expected!r}: a batch's enqueue must not change the job's params"
            )
    record = BatchRecord(
        batch_id=batch_id,
        job_ids=ids,
        label=label or f"batch of {len(ids)}",
        created_at=_jobs.now_iso(),
    )
    store[batch_id] = record.to_dict()
    return record


def estimate_batch(
    project,
    items: Iterable[Mapping[str, Any]],
    *,
    kind: str | None = None,
    config: JobsConfig = DEFAULT_CONFIG,
) -> dict:
    """Dry-run gate for a whole batch, without enqueueing anything.

    ``{estimated_usd, has_unknown_costs, approval_threshold_usd,
    requires_approval, n_items, items}``. ``estimated_usd`` is the sum of the
    known per-item estimates and is ``None`` as soon as any item is unknown;
    unknown forces approval. The threshold applies to the *batch* total, and a
    single item that alone requires approval does too.
    """
    per_item = [
        _jobs.estimate(
            project,
            spec["kind"],
            spec["params"],
            config=config,
            **{k: spec[k] for k in ("estimated_usd",) if k in spec},
        )
        for spec in _item_specs(items, kind)
    ]
    has_unknown = any(e["has_unknown_costs"] for e in per_item)
    total = None if has_unknown else sum(e["estimated_usd"] for e in per_item)
    threshold = config.approval_threshold_usd
    return {
        "estimated_usd": total,
        "has_unknown_costs": has_unknown,
        "approval_threshold_usd": threshold,
        # Non-negative costs: an item at/over the threshold puts the total there too.
        "requires_approval": has_unknown or (total is not None and total >= threshold),
        "n_items": len(per_item),
        "items": per_item,
    }


# ---------------------------------------------------------------------------
# Read: record / status / wait / output / cancel
# ---------------------------------------------------------------------------


def get_batch(
    project, batch_id: str, *, config: JobsConfig = DEFAULT_CONFIG
) -> BatchRecord | None:
    """The stored batch record, or ``None`` if unknown."""
    data = _store(project.root, config).get(batch_id)
    return _record_from(data) if data else None


def status(
    project, batch_id: str, *, config: JobsConfig = DEFAULT_CONFIG
) -> dict | None:
    """Aggregate of the member jobs, computed now. ``None`` if the batch is unknown.

    ``{batch_id, label, total, counts, done, cost, timed_out: False}``. ``counts``
    has one entry per status present (plus :data:`MISSING`); ``done`` is True when
    no member is queued/running/cancelling. ``cost`` carries the sums with their
    honesty flags: ``estimated_usd`` is ``None`` if any member's is unknown, and
    ``actual_is_lower_bound`` is True if any member's is.
    """
    record = get_batch(project, batch_id, config=config)
    if record is None:
        return None
    return _aggregate(record, _members(project, record, config))


def wait(
    project,
    batch_id: str,
    timeout: float,
    *,
    poll_s: float = DEFAULT_POLL_S,
    config: JobsConfig = DEFAULT_CONFIG,
) -> dict | None:
    """Block until the batch is done or ``timeout`` seconds pass (a hard cap).

    ``timeout`` must be >= 0. Wakes on job finish/cancel via the project's :class:`nw.jobs.JobNotifier` (managed
    backend only; a custom ``backend=`` falls back to the ``poll_s`` re-read).

    Returns the :func:`status` aggregate with ``timed_out`` True when the cap hit
    first, so a caller can loop on it. ``None`` if the batch is unknown.
    """
    if not timeout >= 0:
        raise ValueError(f"timeout must be a non-negative number, got {timeout!r}")
    record = get_batch(project, batch_id, config=config)
    if record is None:
        return None
    notifier = _jobs.job_notifier(project, config=config)
    deadline = time.monotonic() + timeout
    members: dict[str, Any] = {}  # job_id -> job (None = missing)
    while True:
        seen = notifier.count()
        for job_id in record.job_ids:  # settled jobs are never re-read
            if job_id not in members or not _is_settled(members[job_id]):
                members[job_id] = _jobs.get_job(project, job_id, config=config)
        agg = _aggregate(record, [members[j] for j in record.job_ids])
        if agg["done"]:
            return agg
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {**agg, "timed_out": True}
        notifier.wait(seen, min(poll_s, remaining))


def output(
    project, batch_id: str, *, config: JobsConfig = DEFAULT_CONFIG
) -> dict | None:
    """Per-outcome results, in batch order within each bucket.

    ``{succeeded: [{job_id, result}], failed: [{job_id, error, error_kind}],
    cancelled: [{job_id}], pending: [{job_id, status}]}``; a vanished member is
    listed under ``failed`` with ``error_kind="missing"``. ``None`` if unknown.
    """
    record = get_batch(project, batch_id, config=config)
    if record is None:
        return None
    out: dict[str, list] = {
        "succeeded": [],
        "failed": [],
        "cancelled": [],
        "pending": [],
    }
    for job_id, job in zip(record.job_ids, _members(project, record, config)):
        if job is None:
            out["failed"].append(
                {"job_id": job_id, "error": "job record missing", "error_kind": MISSING}
            )
        elif job.status == _jobs.SUCCEEDED:
            out["succeeded"].append({"job_id": job_id, "result": job.result})
        elif job.status == _jobs.FAILED:
            out["failed"].append(
                {"job_id": job_id, "error": job.error, "error_kind": job.error_kind}
            )
        elif job.status == _jobs.CANCELLED:
            out["cancelled"].append({"job_id": job_id})
        else:
            out["pending"].append({"job_id": job_id, "status": job.status})
    return out


def cancel_batch(
    project, batch_id: str, *, config: JobsConfig = DEFAULT_CONFIG
) -> dict | None:
    """Cancel every non-terminal member, then return :func:`status`. Idempotent."""
    record = get_batch(project, batch_id, config=config)
    if record is None:
        return None
    for job_id in record.job_ids:
        _jobs.cancel_job(project, job_id, config=config)  # no-op once finished
    return status(project, batch_id, config=config)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


ITEM_KEYS = frozenset({"kind", "params", "label", "idempotency_key", "estimated_usd"})
"""A batch item's keys: :func:`nw.jobs.enqueue`'s per-job arguments."""


def _item_specs(
    items: Iterable[Mapping[str, Any]],
    default_kind: str | None,
    *,
    dispatch: Mapping | None = None,
) -> list[dict]:
    """Normalize and validate items as ``enqueue`` keyword dicts, all up front."""
    specs = []
    for i, item in enumerate(items):
        unknown = set(item) - ITEM_KEYS
        if unknown:
            raise ValueError(f"batch item {i} has unknown keys {sorted(unknown)}")
        spec = {"kind": default_kind, **item}
        if not spec["kind"] or "params" not in spec:
            raise ValueError(
                f"batch item {i} needs a 'kind' (or a batch-level kind=) and 'params'"
            )
        if dispatch is not None and spec["kind"] not in dispatch:
            raise KeyError(f"batch item {i}: kind {spec['kind']!r} is not in dispatch")
        _jobs.check_job_spec(spec["params"])
        specs.append(spec)
    if not specs:
        raise ValueError("a batch needs at least one item")
    return specs


def _spec_job_ids(project, specs: list[dict]) -> list[str]:
    """The job id each spec resolves to, in order."""
    return [
        _jobs.job_id_for(
            project,
            spec["kind"],
            spec["params"],
            idempotency_key=spec.get("idempotency_key"),
        )
        for spec in specs
    ]


def _batch_id(job_ids: tuple[str, ...]) -> str:
    digest = hashlib.sha256(json.dumps(job_ids).encode()).hexdigest()
    return _BATCH_ID_PREFIX + digest[:_BATCH_ID_HEX_LEN]


def _store(project_root, config: JobsConfig, *, create: bool = False):
    base = Path(project_root) / config.jobs_dirname / BATCHES_DIRNAME
    if create:
        base.mkdir(parents=True, exist_ok=True)
    return _jobs.AtomicJsonFiles(base)


def _record_from(data: Mapping) -> BatchRecord:
    return BatchRecord(**{**data, "job_ids": tuple(data["job_ids"])})


def _members(project, record: BatchRecord, config: JobsConfig) -> list:
    return [_jobs.get_job(project, j, config=config) for j in record.job_ids]


def _is_settled(job) -> bool:
    return job is None or job.status in _jobs.TERMINAL_STATUSES


def _aggregate(record: BatchRecord, members: list) -> dict:
    counts: dict[str, int] = {}
    for job in members:
        key = MISSING if job is None else job.status
        counts[key] = counts.get(key, 0) + 1
    settled = _jobs.TERMINAL_STATUSES | {MISSING}
    present = [j for j in members if j is not None]
    estimates = [j.cost.estimated_usd for j in present]
    actuals = [j.cost.actual_usd for j in present if j.cost.actual_usd is not None]
    bounds = [j.cost.actual_is_lower_bound for j in present]
    return {
        "batch_id": record.batch_id,
        "label": record.label,
        "total": len(members),
        "counts": counts,
        "done": all(k in settled for k in counts),
        "timed_out": False,
        "cost": {
            "estimated_usd": (
                None
                if len(present) < len(members) or any(e is None for e in estimates)
                else sum(estimates)
            ),
            "actual_usd": sum(actuals) if actuals else None,
            "actual_is_lower_bound": (
                True
                if any(b is True for b in bounds) or len(present) < len(members)
                else False
                if bounds and all(b is False for b in bounds)
                else None
            ),
        },
    }
