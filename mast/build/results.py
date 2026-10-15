"""Parse googletest results (XML report, with stdout fallback for crashes)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["passed", "failed", "skipped", "crashed", "not_run"]

_RUN_RE = re.compile(r"^\[ RUN      \] (\S+)", re.M)
_END_RE = re.compile(r"^\[ +(OK|FAILED|SKIPPED) +\] (\S+?)(?: \(\d+ ms\))?$", re.M)


class CaseResult(BaseModel):
    suite: str
    name: str
    status: Status
    message: str = ""
    seconds: float = 0.0

    @property
    def full_name(self) -> str:
        return f"{self.suite}.{self.name}"


class TestRunResult(BaseModel):
    __test__ = False

    exit_code: int = 0
    timed_out: bool = False
    output: str = ""
    cases: list[CaseResult] = Field(default_factory=list)
    xml_found: bool = False

    @property
    def crashed(self) -> bool:
        return any(c.status == "crashed" for c in self.cases) or (
            not self.xml_found and not self.timed_out and self.exit_code not in (0, 1)
        )

    def count(self, status: Status) -> int:
        return sum(1 for c in self.cases if c.status == status)

    @property
    def all_passed(self) -> bool:
        return bool(self.cases) and all(c.status in ("passed", "skipped") for c in self.cases) and not self.timed_out


def parse_xml(path: Path) -> list[CaseResult]:
    root = ET.parse(path).getroot()
    cases = []
    for tc in root.iter("testcase"):
        failures = [f for f in tc if f.tag in ("failure", "error")]
        skipped = any(f.tag == "skipped" for f in tc) or tc.get("result") == "skipped"
        if tc.get("status") == "notrun":
            status: Status = "not_run"
        elif failures:
            status = "failed"
        elif skipped:
            status = "skipped"
        else:
            status = "passed"
        message = "\n".join((f.text or f.get("message", "")).strip() for f in failures)
        cases.append(CaseResult(suite=tc.get("classname", ""), name=tc.get("name", ""), status=status,
                                message=message, seconds=float(tc.get("time", "0") or 0)))
    return cases


def parse_stdout(output: str) -> list[CaseResult]:
    """Recover results from console output when the XML report is missing (crash/timeout)."""
    finished = {m.group(2): m.group(1) for m in _END_RE.finditer(output)}
    cases = []
    for m in _RUN_RE.finditer(output):
        full = m.group(1)
        suite, _, name = full.partition(".")
        verdict = finished.get(full)
        status: Status = {"OK": "passed", "FAILED": "failed", "SKIPPED": "skipped"}.get(verdict or "", "crashed")
        message = ""
        if status != "passed":
            start = m.end()
            nxt = _RUN_RE.search(output, start)
            message = output[start : nxt.start() if nxt else len(output)].strip()[-4000:]
        cases.append(CaseResult(suite=suite, name=name, status=status, message=message))
    return cases


def merge_results(xml_cases: list[CaseResult], stdout_cases: list[CaseResult]) -> list[CaseResult]:
    if xml_cases:
        return xml_cases
    return stdout_cases
