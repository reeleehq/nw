# nw.atomic_io

Small-file IO that a concurrent reader can never catch half-done (nw#243, nw#260).

nw’s stores (the shared media store’s registry, the host media catalog’s rows)
keep small JSON/text files that a writer replaces while readers poll them.
Three helpers, all through `dol.atomic`:

- [`write_text_atomic()`](#nw.atomic_io.write_text_atomic): temp file, then `os.replace`, so a reader sees
  the old text or the new, never a truncated file;
- [`copy_file_atomic()`](#nw.atomic_io.copy_file_atomic): a whole file copied into place the same way (a
  blob copied across filesystems), on dol’s uniquely named `O_EXCL` temp, so
  two copies of one blob at once never share a temp file;
- [`replace_retrying()`](#nw.atomic_io.replace_retrying): `os.replace` alone;
- [`read_text_retrying()`](#nw.atomic_io.read_text_retrying): a read.

Each retries a Windows sharing violation (a reader or writer holding the file
for an instant), the policy `retry=` (keyword-only; default
`dol.atomic.DFLT_RETRY`, which retries nothing off Windows, where the
same error means a real permission problem). A missing file is never retried.
Stdlib and dol only, so any module can use it.

### Functions

| [`copy_file_atomic`](#nw.atomic_io.copy_file_atomic)(src, dst, \*[, retry, ...])   | Copy `src` to `dst` atomically: a copy that fails half-way never leaves a short `dst`, and a reader holding `dst` is outlasted.   |
|-------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| [`read_text_retrying`](#nw.atomic_io.read_text_retrying)(path, \*[, retry])          | `path`'s UTF-8 text, retried on a sharing violation.                                                                              |
| [`replace_retrying`](#nw.atomic_io.replace_retrying)(src, dst, \*[, retry])        | `os.replace(src, dst)`, retried on a sharing violation.                                                                           |
| [`write_text_atomic`](#nw.atomic_io.write_text_atomic)(path, text, \*[, retry])     | `text` (UTF-8) to `path` atomically; parent folders are created.                                                                  |

### nw.atomic_io.copy_file_atomic(src, dst, , retry=None, chunk_bytes=1048576)

Copy `src` to `dst` atomically: a copy that fails half-way never
leaves a short `dst`, and a reader holding `dst` is outlasted. Times and
mode are copied after (best effort), as `shutil.copy2` would.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### nw.atomic_io.read_text_retrying(path, , retry=None)

`path`’s UTF-8 text, retried on a sharing violation.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### nw.atomic_io.replace_retrying(src, dst, , retry=None)

`os.replace(src, dst)`, retried on a sharing violation.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### nw.atomic_io.write_text_atomic(path, text, , retry=None)

`text` (UTF-8) to `path` atomically; parent folders are created.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
