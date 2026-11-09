# nw.paths

Turning a caller-editable id into a file name that cannot leave its directory.

Two modes, one module: [`safe_path_segment()`](#nw.paths.safe_path_segment) **maps** any id to a safe
name (never refuses), and [`check_path_segment()`](#nw.paths.check_path_segment) **validates** a name a
caller chose and refuses one that is not a single direct child (nw#227).

An id that came out of a body a caller can edit (a storyboard panel’s
`panel_id`, a clip’s id, a take’s key) is *data*, and joining data onto a
directory as `dir / f"{id}.png"` lets `../../x` write anywhere the process
can. [`safe_path_segment()`](#nw.paths.safe_path_segment) is the one mapping from such an id to a single
path segment, shared by every genre that names files after ids (nw#220; reelee
fixed the same pattern for its Ken Burns clips in reelee#930).

The mapping, and why each part is there:

- **An id that is already a safe slug is kept as is**, so the file of a panel
  that has always rendered to `storyboard/<panel_id>.png` keeps that name and
  a re-render still overwrites it.
- \*\*Anything else becomes its slug, a `.` and a short digest of the id.\*\* The
  digest keeps two odd ids that slug alike (`a/b`, `a\b`) apart, and the
  `.` is never in a kept id, so a mapped name cannot equal a kept one.
- **The name fits a file name’s byte limit**, suffix included, and never spells
  a Windows device name (`CON`, `NUL`, `COM1` …), which Windows refuses
  whatever the extension.

Not handled: two kept ids differing only in case (`Panel1`, `panel1`) share
a file on a case-insensitive filesystem, so editing an id to `P0A1` beside
`p0a1` overwrites that file — inside the directory, never outside it. Folding
case would rename every existing mixed-case file, and the ids artful mints
(`new_panel_id`) are lowercase.

No dependency beyond the standard library.

### Module Attributes

| [`MAX_NAME_BYTES`](#nw.paths.MAX_NAME_BYTES)   | The longest file name, in bytes, the filesystems nw runs on accept.   |
|-------------------------------------------------------------------|-----------------------------------------------------------------------|

### Functions

| [`check_path_segment`](#nw.paths.check_path_segment)(value, \*[, what, pattern])    | `value`, refused unless it names a direct child of the directory it is joined to: not empty, not `.` or `..`, no `/`, `\`, NUL, or `:` (on Windows `D:x` joins to another drive) (nw#227).   |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`is_kept`](#nw.paths.is_kept)(name)                                     | Whether [`safe_path_segment()`](#nw.paths.safe_path_segment) keeps `name` verbatim (its stem).                                                                               |
| [`safe_path_segment`](#nw.paths.safe_path_segment)(value, \*[, suffix, max_bytes]) | A single file name for `value` (plus `suffix`) that is always a direct child of the directory it is joined to.                                                                               |

### nw.paths.MAX_NAME_BYTES *= 255*

The longest file name, in bytes, the filesystems nw runs on accept.

### nw.paths.check_path_segment(value, , what='path segment', pattern=None)

`value`, refused unless it names a direct child of the directory it is
joined to: not empty, not `.` or `..`, no `/`, `\`, NUL, or
`:` (on Windows `D:x` joins to another drive) (nw#227). Returns it
unchanged.

`pattern` is a stricter policy a caller adds (`fullmatch`), e.g. a
store whose names must be slugs. `what` names the value in the error.

```pycon
>>> check_path_segment("ep_01", what="project_id")
'ep_01'
>>> check_path_segment("../escape", what="project_id")
Traceback (most recent call last):
    ...
ValueError: invalid project_id: '../escape' is not a single path segment
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### nw.paths.is_kept(name)

Whether [`safe_path_segment()`](#nw.paths.safe_path_segment) keeps `name` verbatim (its stem).

```pycon
>>> is_kept("p0a1"), is_kept("x.9cdf6a50"), is_kept("nul")
(True, False, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### nw.paths.safe_path_segment(value, , suffix='', max_bytes=255)

A single file name for `value` (plus `suffix`) that is always a direct
child of the directory it is joined to.

```pycon
>>> safe_path_segment("p0a1", suffix=".png")
'p0a1.png'
>>> safe_path_segment("../../x", suffix=".png")
'x.9cdf6a50.png'
>>> safe_path_segment("..")
'_.5ec1f7e7'
>>> safe_path_segment("con", suffix=".png")
'_con.1143da2b.png'
```

Deterministic, so the same id always lands on the same file. `suffix` is
appended verbatim and is the caller’s (a literal like `".png"`, never
data). Raises `ValueError` when `suffix` leaves no room for a name
within `max_bytes`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
