"""Locate or fetch the googletest source tree (compiled together with the tests)."""
from __future__ import annotations

import io
import shutil
import ssl
import urllib.request
import zipfile
from pathlib import Path

from ..frameworks import GTEST_VERSION
from . import proc


class GTestSourceError(RuntimeError):
    pass


def _valid(path: Path) -> bool:
    return (path / "googletest" / "src" / "gtest-all.cc").is_file()


def _download_zip(url: str, dest: Path, ca_bundle: str | None) -> None:
    ctx = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=120, context=ctx) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        top = zf.namelist()[0].split("/")[0]
        tmp = dest.parent / (dest.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        zf.extractall(tmp)
    shutil.move(str(tmp / top), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)


def _git_clone(dest: Path) -> proc.ProcResult:
    return proc.run(["git", "clone", "--depth", "1", "--branch", f"v{GTEST_VERSION}",
                     "https://github.com/google/googletest.git", dest], timeout=300)


def ensure_gtest(source_dir: str | None, cache_dir: Path, url: str, ca_bundle: str | None = None) -> Path:
    """Return the googletest root (the dir containing googletest/ and CMakeLists.txt)."""
    if source_dir:
        path = Path(source_dir).expanduser().resolve()
        if not _valid(path):
            raise GTestSourceError(f"build.gtest_source_dir is not a googletest checkout: {path}")
        return path

    dest = cache_dir.expanduser().resolve() / f"googletest-{GTEST_VERSION}"
    if _valid(dest):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(dest, ignore_errors=True)

    errors = []
    try:
        _download_zip(url, dest, ca_bundle)
        if _valid(dest):
            return dest
        errors.append("zip did not contain googletest/src/gtest-all.cc")
    except Exception as e:  # network/proxy/zip problems: fall back to git
        errors.append(f"download {url}: {e}")
    shutil.rmtree(dest, ignore_errors=True)
    res = _git_clone(dest)
    if res.ok and _valid(dest):
        return dest
    errors.append(f"git clone: {res.output.strip()[-500:]}")
    raise GTestSourceError(
        "Could not obtain googletest. Download "
        f"googletest v{GTEST_VERSION} manually and set build.gtest_source_dir.\n" + "\n".join(errors)
    )
