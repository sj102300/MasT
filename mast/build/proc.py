"""Subprocess helpers: timeouts, output decoding (MSVC on Korean Windows prints cp949)."""
from __future__ import annotations

import locale
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcResult:
    args: list[str]
    returncode: int
    output: str
    seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def decode(data: bytes) -> str:
    for enc in ("utf-8", locale.getpreferredencoding(False), "cp949"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def run(args: list[str | Path], cwd: Path | None = None, timeout: float | None = None,
        env: dict[str, str] | None = None) -> ProcResult:
    argv = [str(a) for a in args]
    full_env = dict(os.environ)
    full_env.update(env or {})
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv, cwd=cwd, env=full_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as e:
        out = decode(e.stdout or b"")
        return ProcResult(argv, -1, out + f"\n[mast] timed out after {timeout}s", time.monotonic() - start, True)
    except FileNotFoundError as e:
        return ProcResult(argv, -1, f"[mast] command not found: {argv[0]} ({e})", time.monotonic() - start)
    return ProcResult(argv, proc.returncode, decode(proc.stdout), time.monotonic() - start)
