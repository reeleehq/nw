# nw.batches

nw.batches — many jobs, one handle: submit / status / wait / output / cancel.

An agent driving a 200-shot fan-out should not burn a turn per poll and track
N job ids (reelee#261 B). A **batch** is a small durable record beside the job
records (`<jobs_dirname>/batches/<batch_id>.json`: `batch_id`, the ordered
`job_ids`, a `label`, `created_at`). Everything else is \*computed from the
member jobs on read\* and never stored, so a batch cannot drift from its jobs:

- [`enqueue_batch()`](#nw.batches.enqueue_batch) enqueues each item through [`nw.jobs.enqueue()`](nw.jobs.html.md#nw.jobs.enqueue), so
  idempotency, ETA, cost, heartbeat and the reaper stay per-job and unchanged.
  The `batch_id` is a pure function of the ordered job ids, so re-submitting
  the same batch returns the same batch (and, per job, the same live jobs).
- [`status()`](#nw.batches.status) — counts per job status, summed cost, `done`.
- [`wait()`](#nw.batches.wait) — blocks until every member is terminal or `timeout` elapses,
  then returns the current aggregate with `timed_out`. Distinct from
  [`status()`](#nw.batches.status), which never blocks. Woken by the project’s [`nw.jobs.JobNotifier`](nw.jobs.html.md#nw.jobs.JobNotifier)
  > (job finish / cancel) and re-checking at `poll_s` regardless, because the
  > reaper and cross-process workers change a job without notifying anyone here.
- [`output()`](#nw.batches.output) — a partially failed batch yields its successes *and* its
  failures, never an all-or-nothing error.
- [`estimate_batch()`](#nw.batches.estimate_batch) — the cost gate: the sum of per-item
  [`nw.jobs.estimate()`](nw.jobs.html.md#nw.jobs.estimate); an unknown item makes the whole batch unknown and
  > therefore approval-requiring (`None` is never free).
- [`cancel_batch()`](#nw.batches.cancel_batch) — cancels every non-terminal member (job cancel is
  idempotent and a no-op on a finished job).

Items are mappings `{"kind": ..., "params": {...}}` (optionally `label`,
`idempotency_key`, and `estimated_usd` — a host’s own price for that
member, kept out of its job id, nw#144); a batch-level `kind=` is the default for items that omit
one. Item identity should be semantic (see `nw.transforms.fanout`’s
`mapping_key`): the default idempotency key hashes `params`.

Cost gating of the *spender* (a per-caller cap) belongs to the host’s
`enqueue` door, exactly as for a single job; this module adds only the dry-run.

### Module Attributes

| [`BATCHES_DIRNAME`](#nw.batches.BATCHES_DIRNAME)   | Sub-directory of `config.jobs_dirname` holding batch records.                                                    |
|--------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| [`DEFAULT_POLL_S`](#nw.batches.DEFAULT_POLL_S)    | How often [`wait()`](#nw.batches.wait) re-reads the members when nothing notifies it. |
| [`MISSING`](#nw.batches.MISSING)           | Status key for a member whose job record is gone (it will never finish).                                         |
| [`ITEM_KEYS`](#nw.batches.ITEM_KEYS)         | [`nw.jobs.enqueue()`](nw.jobs.html.md#nw.jobs.enqueue)'s per-job arguments.          |

### Functions

| [`cancel_batch`](#nw.batches.cancel_batch)(project, batch_id, \*[, config])      | Cancel every non-terminal member, then return [`status()`](#nw.batches.status).   |
|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|
| [`enqueue_batch`](#nw.batches.enqueue_batch)(project, items, \*[, kind, ...])     | Enqueue every item as a job and record the batch.                                                          |
| [`estimate_batch`](#nw.batches.estimate_batch)(project, items, \*[, kind, config]) | Dry-run gate for a whole batch, without enqueueing anything.                                               |
| [`get_batch`](#nw.batches.get_batch)(project, batch_id, \*[, config])         | The stored batch record, or `None` if unknown.                                                             |
| [`output`](#nw.batches.output)(project, batch_id, \*[, config])            | Per-outcome results, in batch order within each bucket.                                                    |
| [`status`](#nw.batches.status)(project, batch_id, \*[, config])            | Aggregate of the member jobs, computed now.                                                                |
| [`wait`](#nw.batches.wait)(project, batch_id, timeout, \*[, ...])        | Block until the batch is done or `timeout` seconds pass (a hard cap).                                      |

### Classes

| [`BatchRecord`](#nw.batches.BatchRecord)(batch_id, job_ids, label, created_at)   | The durable part of a batch.   |
|------------------------------------------------------------------------------------------------------|--------------------------------|

### nw.batches.BATCHES_DIRNAME *= 'batches'*

Sub-directory of `config.jobs_dirname` holding batch records.

### *class* nw.batches.BatchRecord(batch_id, job_ids, label, created_at)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The durable part of a batch. Everything else is derived from the jobs.

### nw.batches.DEFAULT_POLL_S *= 0.25*

How often [`wait()`](#nw.batches.wait) re-reads the members when nothing notifies it.

### nw.batches.ITEM_KEYS *= frozenset({'estimated_usd', 'idempotency_key', 'kind', 'label', 'params'})*

[`nw.jobs.enqueue()`](nw.jobs.html.md#nw.jobs.enqueue)’s per-job arguments.

* **Type:**
  A batch item’s keys

### nw.batches.MISSING *= 'missing'*

Status key for a member whose job record is gone (it will never finish).

### nw.batches.cancel_batch(project, batch_id, , config=JobsConfig(n_min=3, sample_window_k=20, pct_ceil=99, overrun_factor=1.5, cache_hit_floor_s=0.5, dur_buckets_s=(4.0, 8.0, 12.0), prior_total_s={'image': 12.0, 'video': 90.0, 'audio': 15.0}, default_prior_total_s=30.0, stale_running_s=900.0, heartbeat_interval_s=20.0, heartbeat_stale_s=120.0, terminal_hook_attempts=3, terminal_hook_lease_s=300.0, approval_threshold_usd=1.0, index_retention_s=2592000.0, index_sweep_interval_s=3600.0, jobs_dirname='.nw/jobs'))

Cancel every non-terminal member, then return [`status()`](#nw.batches.status). Idempotent.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### nw.batches.enqueue_batch(project, items, , kind=None, label=None, config=JobsConfig(n_min=3, sample_window_k=20, pct_ceil=99, overrun_factor=1.5, cache_hit_floor_s=0.5, dur_buckets_s=(4.0, 8.0, 12.0), prior_total_s={'image': 12.0, 'video': 90.0, 'audio': 15.0}, default_prior_total_s=30.0, stale_running_s=900.0, heartbeat_interval_s=20.0, heartbeat_stale_s=120.0, terminal_hook_attempts=3, terminal_hook_lease_s=300.0, approval_threshold_usd=1.0, index_retention_s=2592000.0, index_sweep_interval_s=3600.0, jobs_dirname='.nw/jobs'), enqueue=None, \*\*enqueue_kwargs)

Enqueue every item as a job and record the batch. Never blocks.

`enqueue_kwargs` (`dispatch`, `on_event`, `secrets`,
`capture_context`, `backend`) go to each `enqueue` call unchanged.
Every item is validated (keys, `kind` in `dispatch`, `units`) before
the first one launches, so a bad item leaves nothing running. Re-submitting
a batch that exists returns it without enqueueing.

`enqueue` (default [`nw.jobs.enqueue()`](nw.jobs.html.md#nw.jobs.enqueue), called with the same
arguments) is the seam for a host’s own single-job door, so a batch member
is enqueued exactly as a lone job would be. It must enqueue the job
the item names (it may add server-side params only if they do not change
the job id): a returned job whose id differs from the item’s raises
`ValueError` and no batch is recorded, because the record would point at
the wrong job. That is a host bug, so it is raised loudly, not repaired:
the members enqueued before it keep running, and a retry may relaunch the
ones that have finished (and bill them again). With a custom `enqueue`
and no `dispatch`, the up-front `kind`-in-`dispatch` check is
skipped: the door owns its dispatch, so it owns that check.

Items resolving to the same job collapse to one member (first position wins).
An `enqueue_kwargs` key that is also an item key ([`ITEM_KEYS`](#nw.batches.ITEM_KEYS)), or
an item `estimated_usd` that a custom `enqueue` does not accept, raises
`TypeError` before anything launches, rather than on a later member
after the first ones are running.

* **Return type:**
  [`BatchRecord`](#nw.batches.BatchRecord)

### nw.batches.estimate_batch(project, items, , kind=None, config=JobsConfig(n_min=3, sample_window_k=20, pct_ceil=99, overrun_factor=1.5, cache_hit_floor_s=0.5, dur_buckets_s=(4.0, 8.0, 12.0), prior_total_s={'image': 12.0, 'video': 90.0, 'audio': 15.0}, default_prior_total_s=30.0, stale_running_s=900.0, heartbeat_interval_s=20.0, heartbeat_stale_s=120.0, terminal_hook_attempts=3, terminal_hook_lease_s=300.0, approval_threshold_usd=1.0, index_retention_s=2592000.0, index_sweep_interval_s=3600.0, jobs_dirname='.nw/jobs'))

Dry-run gate for a whole batch, without enqueueing anything.

`{estimated_usd, has_unknown_costs, approval_threshold_usd,
requires_approval, n_items, items}`. `estimated_usd` is the sum of the
known per-item estimates and is `None` as soon as any item is unknown;
unknown forces approval. The threshold applies to the *batch* total, and a
single item that alone requires approval does too.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### nw.batches.get_batch(project, batch_id, , config=JobsConfig(n_min=3, sample_window_k=20, pct_ceil=99, overrun_factor=1.5, cache_hit_floor_s=0.5, dur_buckets_s=(4.0, 8.0, 12.0), prior_total_s={'image': 12.0, 'video': 90.0, 'audio': 15.0}, default_prior_total_s=30.0, stale_running_s=900.0, heartbeat_interval_s=20.0, heartbeat_stale_s=120.0, terminal_hook_attempts=3, terminal_hook_lease_s=300.0, approval_threshold_usd=1.0, index_retention_s=2592000.0, index_sweep_interval_s=3600.0, jobs_dirname='.nw/jobs'))

The stored batch record, or `None` if unknown.

* **Return type:**
  [`BatchRecord`](#nw.batches.BatchRecord) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### nw.batches.output(project, batch_id, , config=JobsConfig(n_min=3, sample_window_k=20, pct_ceil=99, overrun_factor=1.5, cache_hit_floor_s=0.5, dur_buckets_s=(4.0, 8.0, 12.0), prior_total_s={'image': 12.0, 'video': 90.0, 'audio': 15.0}, default_prior_total_s=30.0, stale_running_s=900.0, heartbeat_interval_s=20.0, heartbeat_stale_s=120.0, terminal_hook_attempts=3, terminal_hook_lease_s=300.0, approval_threshold_usd=1.0, index_retention_s=2592000.0, index_sweep_interval_s=3600.0, jobs_dirname='.nw/jobs'))

Per-outcome results, in batch order within each bucket.

`{succeeded: [{job_id, result}], failed: [{job_id, error, error_kind}],
cancelled: [{job_id}], pending: [{job_id, status}]}`; a vanished member is
listed under `failed` with `error_kind="missing"`. `None` if unknown.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### nw.batches.status(project, batch_id, , config=JobsConfig(n_min=3, sample_window_k=20, pct_ceil=99, overrun_factor=1.5, cache_hit_floor_s=0.5, dur_buckets_s=(4.0, 8.0, 12.0), prior_total_s={'image': 12.0, 'video': 90.0, 'audio': 15.0}, default_prior_total_s=30.0, stale_running_s=900.0, heartbeat_interval_s=20.0, heartbeat_stale_s=120.0, terminal_hook_attempts=3, terminal_hook_lease_s=300.0, approval_threshold_usd=1.0, index_retention_s=2592000.0, index_sweep_interval_s=3600.0, jobs_dirname='.nw/jobs'))

Aggregate of the member jobs, computed now. `None` if the batch is unknown.

`{batch_id, label, total, counts, done, cost, timed_out: False}`. `counts`
has one entry per status present (plus [`MISSING`](#nw.batches.MISSING)); `done` is True when
no member is queued/running/cancelling. `cost` carries the sums with their
honesty flags: `estimated_usd` is `None` if any member’s is unknown, and
`actual_is_lower_bound` is True if any member’s is.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### nw.batches.wait(project, batch_id, timeout, , poll_s=0.25, config=JobsConfig(n_min=3, sample_window_k=20, pct_ceil=99, overrun_factor=1.5, cache_hit_floor_s=0.5, dur_buckets_s=(4.0, 8.0, 12.0), prior_total_s={'image': 12.0, 'video': 90.0, 'audio': 15.0}, default_prior_total_s=30.0, stale_running_s=900.0, heartbeat_interval_s=20.0, heartbeat_stale_s=120.0, terminal_hook_attempts=3, terminal_hook_lease_s=300.0, approval_threshold_usd=1.0, index_retention_s=2592000.0, index_sweep_interval_s=3600.0, jobs_dirname='.nw/jobs'))

Block until the batch is done or `timeout` seconds pass (a hard cap).

`timeout` must be >= 0. Wakes on job finish/cancel via the project’s [`nw.jobs.JobNotifier`](nw.jobs.html.md#nw.jobs.JobNotifier) (managed
backend only; a custom `backend=` falls back to the `poll_s` re-read).

Returns the [`status()`](#nw.batches.status) aggregate with `timed_out` True when the cap hit
first, so a caller can loop on it. `None` if the batch is unknown.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
