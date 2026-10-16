from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")


def _ident(value: str) -> str:
    value = _IDENT_RE.sub("", value.replace(" ", "_"))
    return value if value and not value[0].isdigit() else f"T{value}"


class TestCase(BaseModel):
    __test__ = False  # not a pytest class

    id: str
    function: str
    suite: str
    name: str
    category: Literal["normal", "boundary", "error"] = "normal"
    description: str = ""
    input: str = ""
    expected: str = ""
    notes: str = ""

    @field_validator("suite", "name")
    @classmethod
    def _valid_identifier(cls, v: str) -> str:
        # gtest names: identifiers without underscores are safest
        return _ident(v).replace("_", "")

    @field_validator("category", mode="before")
    @classmethod
    def _norm_category(cls, v: str) -> str:
        v = str(v).strip().lower()
        return v if v in ("normal", "boundary", "error") else "normal"

    @property
    def full_name(self) -> str:
        return f"{self.suite}.{self.name}"


class TestPlan(BaseModel):
    __test__ = False

    test_cases: list[TestCase] = Field(default_factory=list)

    def dedupe(self) -> TestPlan:
        """Make suite.name unique (LLMs occasionally repeat a name)."""
        seen: dict[str, int] = {}
        cases = []
        for tc in self.test_cases:
            key = tc.full_name
            if key in seen:
                seen[key] += 1
                tc = tc.model_copy(update={"name": f"{tc.name}{seen[key]}"})
            else:
                seen[key] = 1
            cases.append(tc)
        return TestPlan(test_cases=cases)


class GeneratedTest(BaseModel):
    path: str  # relative to the run's tests/ dir
    content: str
    target: str  # source file this test covers
    includes: list[str] = Field(default_factory=list)
