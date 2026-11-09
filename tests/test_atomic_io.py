"""nw.atomic_io: small-file IO a concurrent reader can never catch half-done (nw#260)."""

from __future__ import annotations

import os
from pathlib import Path

import dol.atomic
import pytest

from nw import atomic_io

RETRY_ON_WINDOWS_ERRORS = dol.atomic.Retry(on=(PermissionError,), backoff_s=0)


def _flaky(real, failures=1):
    calls = []

    def op(*a, **k):
        calls.append(a)
        if len(calls) <= failures:
            raise PermissionError("in use")
        return real(*a, **k)

    return op


def test_copy_file_atomic_copies_bytes_and_times(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(os.urandom(3 * 1024 + 7))
    os.utime(src, (1_000_000, 1_000_000))
    atomic_io.copy_file_atomic(src, tmp_path / "dst.bin", chunk_bytes=1024)
    assert (tmp_path / "dst.bin").read_bytes() == src.read_bytes()
    assert int((tmp_path / "dst.bin").stat().st_mtime) == 1_000_000


def test_a_copy_that_fails_half_way_leaves_no_short_file(tmp_path, monkeypatch):
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 5000)
    real_open = open

    class Dies:
        def __init__(self, f):
            self.f, self.n = f, 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()

        def read(self, size):
            self.n += 1
            if self.n == 2:
                raise OSError("source vanished mid-copy")
            return self.f.read(size)

    monkeypatch.setattr(
        "builtins.open",
        lambda p, *a, **k: Dies(real_open(p, *a, **k)) if str(p) == str(src) else real_open(p, *a, **k),
    )
    with pytest.raises(OSError, match="mid-copy"):
        atomic_io.copy_file_atomic(src, tmp_path / "dst.bin", chunk_bytes=1000)
    monkeypatch.undo()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["src.bin"]  # no dst, no temp


def test_reads_writes_and_copies_outlast_a_sharing_violation(tmp_path, monkeypatch):
    monkeypatch.setattr(atomic_io, "DFLT_RETRY", RETRY_ON_WINDOWS_ERRORS)
    monkeypatch.setattr(os, "replace", _flaky(os.replace))
    atomic_io.write_text_atomic(tmp_path / "a" / "t.txt", "hi")
    monkeypatch.undo()
    monkeypatch.setattr(atomic_io, "DFLT_RETRY", RETRY_ON_WINDOWS_ERRORS)
    monkeypatch.setattr(os, "replace", _flaky(os.replace))
    atomic_io.copy_file_atomic(tmp_path / "a" / "t.txt", tmp_path / "copy.txt")
    monkeypatch.setattr(Path, "read_text", _flaky(Path.read_text))
    assert atomic_io.read_text_retrying(tmp_path / "copy.txt") == "hi"


def test_an_explicit_retry_policy_wins(tmp_path, monkeypatch):
    p = tmp_path / "f"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", _flaky(Path.read_text))
    with pytest.raises(PermissionError):
        atomic_io.read_text_retrying(p, retry=dol.atomic.Retry(on=(), backoff_s=0))
