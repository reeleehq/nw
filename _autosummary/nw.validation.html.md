# nw.validation

Pluggable validation of finished work — the seam, not the checks.

**What this is for.** A render that finishes without raising is not a render
that is *right*. A one-minute short shipped with a burnt-in lower third reading
`1981 · Centr…`; a ten-minute cut shipped two-thirds encoded with a container
duration taken from its audio stream, so every duration check passed; a Ken
Burns move jumped a whole pixel mid-panel for months. Each was found by a human
watching the finished file, which is the most expensive detector we have and the
only one that gets tired.

**What this module owns, and what it deliberately does not.** It owns the
*seam*: how a check is declared, how the menu of available checks is assembled,
how dependencies between them are resolved, in what order and with how much
concurrency they run, and what a run of them reports. It owns no domain
knowledge whatsoever — every actual check is a plugin, registered from wherever
the knowledge lives (nw ships the two that [`nw.inspect`](nw.inspect.html.md#module-nw.inspect) already knew how to
do; a check about on-screen type belongs next to `tituli`, one about camera
motion next to `burns`).

**Where it goes in a pipeline.** Nowhere, by default. Validation is a thing you
*place*, and where to place it is a judgement about cost and consequence:

* before showing a result to a human, if the checks are cheap;
* before an irreversible or outward-facing step — a publish, an upload, a send —
  where the checks earn their cost whatever they cost;
* both, with a cheaper selection at the first point than the second.

So the surface is one function, [`validate()`](#nw.validation.validate), and callers place it. Nothing
in nw calls it for you; a gate you did not ask for is a gate that fires at the
wrong moment.

**Declaring a check**:

```default
from nw.validation import Check, checks

@checks.register_decorator("video.has_both_streams")
def _has_both_streams():
    return Check(
        name="video.has_both_streams",
        summary="the file actually contains a video and an audio stream",
        run=lambda target, ctx: (...),
        example_requests=("is the video ok", "did the render work"),
    )
```

`example_requests` is not decoration. A menu of forty checks is unusable by a
human and unselectable by a model; the phrases a person actually says are what
lets [`suggest()`](#nw.validation.suggest) turn “make sure the captions look right” into a selection,
which is how this reaches an MCP tool surface without a forty-item enum.

### Examples

```pycon
>>> report = validate("some.mp4", checks=())   # nothing selected, nothing run
>>> report.ok, list(report.findings)
(True, [])
```

### Module Attributes

| [`checks`](#nw.validation.checks)      | The menu.     |
|--------------------------------------------------------------|---------------|
| [`CHEAP_COSTS`](#nw.validation.CHEAP_COSTS) | never `paid`. |

### Functions

| [`register_check`](#nw.validation.register_check)([check])                          | Add a check to the menu, as a call or as a decorator.                                                                                                                                                                                                                                                           |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`resolve_checks`](#nw.validation.resolve_checks)(selection)                        | Selection plus everything it requires, with names resolved to Checks.                                                                                                                                                                                                                                           |
| [`plan_checks`](#nw.validation.plan_checks)(selection)                           | Order the selection into waves that may each run concurrently.                                                                                                                                                                                                                                                  |
| [`validate`](#nw.validation.validate)(target, \*[, checks, max_workers, ...]) | Run `checks` against `target` and report.                                                                                                                                                                                                                                                                       |
| [`suggest`](#nw.validation.suggest)(request, \*[, include_paid])             | Checks whose `example_requests` look like what the user just asked for.                                                                                                                                                                                                                                         |
| [`menu`](#nw.validation.menu)(\*[, cost])                                 | Every registered check, name-ordered — what a user chooses from.                                                                                                                                                                                                                                                |
| [`package_profiles`](#nw.validation.package_profiles)()                               | The profiles derived from the menu, never written by hand: `cheap` is every check whose cost is in [`CHEAP_COSTS`](#nw.validation.CHEAP_COSTS) (so never a `paid` one).                                                                                                                        |
| [`expand_selection`](#nw.validation.expand_selection)(names[, profiles])              | `names` (checks or profiles) as check names, profiles expanded, each once, in order.                                                                                                                                                                                                                            |
| [`select`](#nw.validation.select)(placement, \*[, checks, settings, ...])   | The check names that run at `placement`, profiles expanded; `()`: none.                                                                                                                                                                                                                                         |
| [`checked_settings`](#nw.validation.checked_settings)(raw, \*[, placements])          | `raw` (anything [`select()`](#nw.validation.select) takes) as a [`ValidationSettings`](#nw.validation.ValidationSettings) whose every name is a check or a profile, no profile named like a check (it would silently win), and every placement one of `placements`, when given. |
| [`menu_rows`](#nw.validation.menu_rows)()                                      | The menu as rows a model reads, derived from the registry: each check's `name`, `summary`, `cost` (a `paid` one runs only when named), `example_requests` and `requires`; then each package profile as a row with its `profile` list.                                                                           |
| [`unreachable_row`](#nw.validation.unreachable_row)(target, names, why)              | The row ([`ValidationReport.row()`](#nw.validation.ValidationReport.row)'s shape) for a target nothing could look at (its bytes could not be reached): every selected check `could_not_run`, never a pass and never a fail.                                                                             |
| [`veto_message`](#nw.validation.veto_message)(rows, \*[, where])                  | A gate's refusal for report rows ([`ValidationReport.row()`](#nw.validation.ValidationReport.row), [`unreachable_row()`](#nw.validation.unreachable_row)), or `None` when every row is ok.                                                                                                 |
| [`env_var`](#nw.validation.env_var)(placement, \*[, env_prefix])             | The environment variable that selects checks for `placement`: the prefix, then the placement upper-cased with anything a shell cannot name made `_`.                                                                                                                                                            |

### Classes

| [`Finding`](#nw.validation.Finding)(check, severity, message[, where, ...])   | One thing a check noticed.                                                             |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|
| [`CheckResult`](#nw.validation.CheckResult)(name[, findings, skipped, ...])       | What one check produced, including the case where it could not run.                    |
| [`ValidationReport`](#nw.validation.ValidationReport)(target[, results, elapsed_s])    | Everything a [`validate()`](#nw.validation.validate) run produced. |
| [`Check`](#nw.validation.Check)(name, summary, run[, requires, ...])        | One validation, and everything a scheduler and a menu need to know.                    |
| [`ValidationSettings`](#nw.validation.ValidationSettings)(\*[, profiles, placements])    | What a host persists: named profiles, and which names each placement runs.             |

### Exceptions

| [`ValidationError`](#nw.validation.ValidationError)(report)   | Raised by [`ValidationReport.raise_if_failed()`](#nw.validation.ValidationReport.raise_if_failed).   |
|----------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|

### nw.validation.CHEAP_COSTS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('free', 'cheap')*

never `paid`.

* **Type:**
  The cost classes the package profile `cheap` draws from

### *class* nw.validation.Check(name, summary, run, requires=(), parallel_safe=True, cost='cheap', example_requests=(), requires_binaries=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One validation, and everything a scheduler and a menu need to know.

#### name

dotted and stable — it is what a user selects and what a
`requires` refers to.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### summary

one line, for the menu.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### run

`(target, context) -> findings`. May also return a
`(findings, produced)` pair when other checks depend on it.

* **Type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Any`](https://docs.python.org/3/library/typing.html#typing.Any), [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]], [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Finding`](#nw.validation.Finding)]]

#### requires

names of checks that must run first, whose `produced`
values arrive in `context`. Cycles raise at plan time.

* **Type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

#### parallel_safe

whether it may run alongside its independent peers.
`False` for anything that is not thread-safe or that saturates
the machine on its own (a full decode).

* **Type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### cost

rough wall-clock class — `"free"` (no subprocess),
`"cheap"` (seconds), `"dear"` (a full pass over the media), or
`"paid"` (spends money, e.g. a hosted OCR or transcription).
`"paid"` is never selected by [`suggest()`](#nw.validation.suggest); it must be asked
for by name.

* **Type:**
  [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'free'`, `'cheap'`, `'dear'`, `'paid'`]

#### example_requests

things a person actually says that mean they want
this check. What lets a menu of forty be navigated, and what an
MCP surface matches against instead of exposing an enum.

* **Type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

#### requires_binaries

external programs it shells out to. A missing one
makes the check *skip with a reason*, never silently pass.

* **Type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### *class* nw.validation.CheckResult(name, findings=(), skipped='', error='', elapsed_s=0.0, produced=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one check produced, including the case where it could not run.

`skipped` and `error` are kept distinct from “found nothing”, because
conflating them is how a validation suite comes to report all-clear on a
machine where half of it never ran. A missing binary is not a pass.

#### *property* ok *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Ran, and found nothing at or above `FAILING_SEVERITY`.

### *class* nw.validation.Finding(check, severity, message, where='', remedy=None, evidence=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One thing a check noticed.

A finding is never a bare boolean. Whoever reads it — a human deciding
whether to publish, or a model deciding what to fix — needs to know *where*
in the work it is and *what* would make it go away, and a check that cannot
say those two things has not finished its job.

#### check

the name of the check that produced it.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### severity

`"info"`, `"warn"` or `"error"`; only `"error"`
makes a report not `ok`.

* **Type:**
  [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'info'`, `'warn'`, `'error'`]

#### message

what is wrong, in one sentence a human can act on.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### where

where in the work — a timestamp, a frame index, a shot id, a
path. Free-form because the checks are, but never empty for
anything above `"info"`.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### remedy

what would fix it, when the check knows. `None` when it
honestly does not.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### evidence

anything a reader would want to look at — an extracted
frame’s path, the numbers behind the verdict.

* **Type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### *exception* nw.validation.ValidationError(report)

Bases: [`AssertionError`](https://docs.python.org/3/builtins/exceptions.html#AssertionError)

Raised by [`ValidationReport.raise_if_failed()`](#nw.validation.ValidationReport.raise_if_failed).

### *class* nw.validation.ValidationReport(target, results=(), elapsed_s=0.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Everything a [`validate()`](#nw.validation.validate) run produced.

#### target

what was validated.

* **Type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

#### results

one per check that was selected, in the order they were run.

* **Type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`CheckResult`](#nw.validation.CheckResult), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

#### elapsed_s

wall-clock for the whole run.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### *property* clean *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

No failing finding and no error among what ran; skips are ignored.

#### *property* complete *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Every selected check actually ran (none skipped, none errored).

#### *property* ok *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Every selected check ran and found nothing failing.

A check that was skipped (a missing binary) or that raised is not a
pass, so a gate on this gets the conservative answer. Use
[`clean`](#nw.validation.ValidationReport.clean) for “no failures among the checks that ran”.

#### raise_if_failed()

Return self, or raise [`ValidationError`](#nw.validation.ValidationError) — for a hard gate.

* **Return type:**
  [`ValidationReport`](#nw.validation.ValidationReport)

#### row(target=None)

This report as one row a host shows or gates on (nw#285): `ok` only
when every check RAN and passed; `failed`, and apart from it the two
ways not to run, which say nothing about the media: `could_not_run`
(skipped: a missing binary, an unreadable file) and `errored` (the
check raised); `reasons` for each, `remedies` from the failed
checks’ findings, and the [`summary()`](#nw.validation.ValidationReport.summary). `target` names it (default:
the report’s own target).

```pycon
>>> ValidationReport("a.mp4", (CheckResult("x", skipped="no ffprobe"),)).row()["could_not_run"]
['x']
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### summary()

A few lines a human can read without unpacking the object.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* nw.validation.ValidationSettings(\*, profiles=<factory>, placements=<factory>)

Bases: `BaseModel`

What a host persists: named profiles, and which names each placement runs.

`profiles` maps a name to a list of check names; `placements` maps a
placement (the host’s string) to names, each a profile or a check. Empty,
the default: nothing runs anywhere (validation is never implicit).

```pycon
>>> ValidationSettings(placements={"before_publish": ["cheap"]}).placements
{'before_publish': ('cheap',)}
```

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### nw.validation.checked_settings(raw, , placements=None)

`raw` (anything [`select()`](#nw.validation.select) takes) as a [`ValidationSettings`](#nw.validation.ValidationSettings)
whose every name is a check or a profile, no profile named like a check (it
would silently win), and every placement one of `placements`, when given.
Raises a plain `ValueError` with a readable message otherwise, on write
rather than at the next run.

* **Return type:**
  [`ValidationSettings`](#nw.validation.ValidationSettings)

### nw.validation.checks *: Registry* *= <Registry nw.validation.checks>*

The menu. `on_conflict="error"` so a plugin that shadows a built-in fails
loudly rather than quietly changing what “validated” means.

### nw.validation.env_var(placement, , env_prefix='NW_VALIDATE_')

The environment variable that selects checks for `placement`: the
prefix, then the placement upper-cased with anything a shell cannot name
made `_`.

```pycon
>>> env_var("before-publish")
'NW_VALIDATE_BEFORE_PUBLISH'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### nw.validation.expand_selection(names, profiles=None)

`names` (checks or profiles) as check names, profiles expanded, each once,
in order. Raises `ValueError` for a name that is neither: a typo must not
quietly validate nothing.

```pycon
>>> expand_selection([], {})
()
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### nw.validation.menu(, cost=None)

Every registered check, name-ordered — what a user chooses from.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Check`](#nw.validation.Check), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### nw.validation.menu_rows()

The menu as rows a model reads, derived from the registry: each check’s
`name`, `summary`, `cost` (a `paid` one runs only when named),
`example_requests` and `requires`; then each package profile as a row
with its `profile` list.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### nw.validation.package_profiles()

The profiles derived from the menu, never written by hand: `cheap` is
every check whose cost is in [`CHEAP_COSTS`](#nw.validation.CHEAP_COSTS) (so never a `paid` one).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]]

### nw.validation.plan_checks(selection)

Order the selection into waves that may each run concurrently.

Every check in a wave has all its requirements satisfied by earlier waves,
so the waves are the schedule: run each in turn, in parallel within it.
A check that is not `parallel_safe` gets a wave to itself.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – on a dependency cycle, or a requirement that is not
      registered — both at plan time, before anything has been spent.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Check`](#nw.validation.Check), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)], [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### Examples

```pycon
>>> plan_checks(())
()
```

### nw.validation.register_check(check=None, \*\*kwargs)

Add a check to the menu, as a call or as a decorator.

As a call:

```default
register_check(Check(name="video.duration", summary="...", run=...))
```

As a decorator on the run function, with the rest as keywords:

```default
@register_check(name="video.duration", summary="...", cost="cheap")
def _duration(target, ctx): ...
```

### nw.validation.resolve_checks(selection)

Selection plus everything it requires, with names resolved to Checks.

A user picks what they care about; what those checks *need* is not their
problem. Raises `KeyError` for an unknown name — a silently dropped check
is the failure this whole module exists to prevent.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Check`](#nw.validation.Check), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### nw.validation.select(placement, , checks=None, settings=None, environ=None, env_prefix='NW_VALIDATE_', placements=None)

The check names that run at `placement`, profiles expanded; `()`: none.

First match wins: an explicit `checks=` (a name or names; `[]` selects
nothing); the environment variable [`env_var()`](#nw.validation.env_var) names, when it holds at
least one name (a blank or comma-only value counts as unset); the
`settings`’ placement (a [`ValidationSettings`](#nw.validation.ValidationSettings), its dict, or a
host’s own settings object); nothing. Never implicit. Only the chosen names
are checked, so a stale name saved for another placement, or overridden
here, does not stop this one; [`checked_settings()`](#nw.validation.checked_settings) checks the whole
object on write. `placements`, when given, are the host’s known
placements, and another one raises `ValueError`; so does an unknown name.

```pycon
>>> select("before_publish", environ={})
()
>>> select("before_publish", environ={}, placements=["before_present"])
Traceback (most recent call last):
...
ValueError: unknown placement 'before_publish'; known: ['before_present']
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### nw.validation.suggest(request, , include_paid=False)

Checks whose `example_requests` look like what the user just asked for.

Deliberately crude — a word-overlap score, not a model call — because this
runs on every request and its job is to narrow forty items to a handful
that a human or a model then confirms. `"paid"` checks are never
suggested: money is asked for by name.

### Examples

```pycon
>>> suggest("")
()
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Check`](#nw.validation.Check), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### nw.validation.unreachable_row(target, names, why)

The row ([`ValidationReport.row()`](#nw.validation.ValidationReport.row)’s shape) for a target nothing could
look at (its bytes could not be reached): every selected check
`could_not_run`, never a pass and never a fail.

```pycon
>>> unreachable_row("clip.mp4", ["video.duration"], "not fetched")["ok"]
False
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### nw.validation.validate(target, , checks=(), max_workers=4, on_error='report')

Run `checks` against `target` and report.

* **Parameters:**
  * **target** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – whatever the checks understand — a path to a rendered file, a
    `Project`, a `(video, annotations)` pair. This module does not
    care; it is the checks that agree with their caller.
  * **checks** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Check`](#nw.validation.Check)]) – names or [`Check`](#nw.validation.Check) objects. Requirements are pulled in
    automatically. Empty means empty: validation is placed, never
    assumed.
  * **max_workers** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – concurrency within a wave.
  * **on_error** ([`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'report'`, `'raise'`]) – `"report"` records a raising check as an errored
    [`CheckResult`](#nw.validation.CheckResult) and carries on, so one broken plugin cannot
    hide the findings of the other nine. `"raise"` is for developing
    a check.
* **Return type:**
  [`ValidationReport`](#nw.validation.ValidationReport)
* **Returns:**
  A [`ValidationReport`](#nw.validation.ValidationReport). Note that `report.ok` is `False` when
  a check *errored*, not only when one failed: a suite that could not run
  has not said the work is good.

### Examples

```pycon
>>> validate("x.mp4").ok
True
```

### nw.validation.veto_message(rows, , where='validation')

A gate’s refusal for report rows ([`ValidationReport.row()`](#nw.validation.ValidationReport.row),
[`unreachable_row()`](#nw.validation.unreachable_row)), or `None` when every row is ok. Names each
check that failed, errored or could not run, on which target, and what to
do: a failed check, its own remedy (or re-render, or drop the check); one
that errored or could not run, fix it or drop it, since neither is a pass.

```pycon
>>> veto_message([unreachable_row("a.mp4", ["video.duration"], "no bytes")])
'validation: video.duration could not run on a.mp4 (no bytes): fix that, or drop the check; it is not a pass'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
