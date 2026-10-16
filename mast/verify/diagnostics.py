"""Parse compiler / linker / build-system diagnostics from MSVC, GCC/Clang and CMake output."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Kind = Literal["compile", "link", "build_system"]
Location = Literal["test", "product", "gtest", "other"]

# C:\x\a.cpp(12,5): error C2065: 'x': undeclared identifier [C:\b\mast_tests.vcxproj]
_MSVC_RE = re.compile(
    r"^\s*(?P<file>\S.*?)\((?P<line>\d+)(?:,(?P<col>\d+))?\)\s*:\s*"
    r"(?P<sev>fatal error|error|warning)\s+(?P<code>(?!MSB)[A-Z]+\d+)\s*:\s*(?P<msg>.*?)(?:\s+\[[^\]]*\])?\s*$"
)
# a.obj : error LNK2019: unresolved external symbol ... [proj]
_MSVC_LINK_RE = re.compile(
    r"^\s*(?P<file>[^:]+?(?:\.obj|\.exe|\.lib|LINK))\s*:\s*(?P<sev>fatal error|error)\s+"
    r"(?P<code>LNK\d+)\s*:\s*(?P<msg>.*?)(?:\s+\[[^\]]*\])?\s*$"
)
# C:\...\Microsoft.Cpp.Platform.targets(67,5): error MSB8020: ...
_MSB_RE = re.compile(r"^\s*(?P<file>.*?)(?:\(\d+,\d+\))?\s*:\s*error\s+(?P<code>MSB\d+)\s*:\s*(?P<msg>.*?)(?:\s+\[[^\]]*\])?\s*$")
# a.cpp:12:5: error: ...   /  a.cpp:12: error: ...
_GCC_RE = re.compile(
    r"^(?P<file>(?:[A-Za-z]:)?[^:\n]+?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
    r"(?P<sev>fatal error|error|warning):\s*(?P<msg>.*)$"
)
# x.cpp:(.text+0x2d): undefined reference to `f(int)'
_GCC_UNDEF_RE = re.compile(r"^(?P<file>[^:\n]+?):\(.*?\):\s*(?P<msg>undefined reference to .*)$")
_LD_RE = re.compile(r"^(?:/usr/bin/)?(?:ld|collect2)(?:\.exe)?:\s*(?:error:\s*)?(?P<msg>.*)$")
_CMAKE_RE = re.compile(r"^CMake Error(?: at (?P<file>[^:]+):(?P<line>\d+))?.*?:?\s*(?P<msg>.*)$")


class Diagnostic(BaseModel):
    kind: Kind
    severity: str
    file: str = ""
    line: int = 0
    column: int = 0
    code: str = ""
    message: str
    location: Location = "other"
    raw: str = ""

    def short(self) -> str:
        where = f"{Path(self.file).name}:{self.line}" if self.file and self.line else (Path(self.file).name or "-")
        code = f" {self.code}" if self.code else ""
        return f"{where}: {self.severity}{code}: {self.message}"


def _norm(p: str) -> str:
    return p.replace("\\", "/").lower().rstrip("/")


class Locator:
    def __init__(self, tests_dir: Path, product_dir: Path, gtest_dir: Path | None, test_stems: list[str],
                 build_dir: Path | None = None):
        self.tests = _norm(str(tests_dir.resolve()))
        self.product = _norm(str(product_dir.resolve()))
        self.gtest = _norm(str(gtest_dir.resolve())) if gtest_dir else None
        self.build = build_dir.resolve() if build_dir else None
        self.test_stems = {s.lower() for s in test_stems}

    def locate(self, file: str) -> Location:
        if not file:
            return "other"
        path = Path(file)
        if not path.is_absolute() and not re.match(r"^[A-Za-z]:[\\/]", file) and self.build is not None:
            path = self.build / path
        f = _norm(str(path))
        name = Path(f).stem
        if f.startswith(self.tests + "/") or (name in self.test_stems and "/" not in file.replace("\\", "/")):
            return "test"
        if self.gtest and f.startswith(self.gtest + "/"):
            return "gtest"
        if f.startswith(self.product + "/"):
            return "product"
        return "other"


def parse_diagnostics(log: str, locator: Locator, include_warnings: bool = False) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    seen: set[tuple] = set()

    def add(d: Diagnostic) -> None:
        key = (d.kind, d.file.lower(), d.line, d.code, d.message)
        if key in seen:
            return
        if d.severity == "warning" and not include_warnings:
            return
        seen.add(key)
        diags.append(d)

    for raw in log.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if m := _MSVC_LINK_RE.match(line):
            obj = m.group("file").strip()
            add(Diagnostic(kind="link", severity=m.group("sev"), file=obj, code=m.group("code"),
                           message=m.group("msg"), location=locator.locate(obj), raw=line))
        elif m := _MSVC_RE.match(line):
            f = m.group("file").strip()
            add(Diagnostic(kind="compile", severity=m.group("sev"), file=f, line=int(m.group("line")),
                           column=int(m.group("col") or 0), code=m.group("code"), message=m.group("msg"),
                           location=locator.locate(f), raw=line))
        elif m := _MSB_RE.match(line):
            add(Diagnostic(kind="build_system", severity="error", file=m.group("file").strip(),
                           code=m.group("code"), message=m.group("msg"), raw=line))
        elif m := _GCC_UNDEF_RE.match(line):
            f = m.group("file").strip()
            add(Diagnostic(kind="link", severity="error", file=f, message=m.group("msg"),
                           location=locator.locate(f), raw=line))
        elif m := _GCC_RE.match(line):
            f = m.group("file").strip()
            add(Diagnostic(kind="compile", severity=m.group("sev"), file=f, line=int(m.group("line")),
                           column=int(m.group("col") or 0), message=m.group("msg"),
                           location=locator.locate(f), raw=line))
        elif line.startswith("CMake Error") and (m := _CMAKE_RE.match(line)):
            add(Diagnostic(kind="build_system", severity="error", file=m.group("file") or "",
                           line=int(m.group("line") or 0), message=m.group("msg") or line, raw=line))
        elif (m := _LD_RE.match(line)) and "ld returned" not in line and "in function" not in line:
            add(Diagnostic(kind="link", severity="error", message=m.group("msg"), raw=line))
    return diags


def context_lines(log: str, diag: Diagnostic, after: int = 3) -> str:
    """The diagnostic line plus a few following lines (gcc prints the offending code and notes there)."""
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if line.rstrip() == diag.raw:
            return "\n".join(lines[i : i + 1 + after])
    return diag.raw
