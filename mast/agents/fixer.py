from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..analyzer import AnalysisResult, FunctionInfo
from ..build import CaseResult
from ..frameworks import TestFramework
from ..verify import Diagnostic
from .base import Agent, load_prompt
from .context import render_sources, source_files_for
from .models import TestPlan

MAX_DIAGNOSTICS = 30
MAX_MESSAGE = 3000


class ProductFix(BaseModel):
    file: str = ""
    line: int = 0
    description: str = ""
    patch: str = ""

    @field_validator("line", mode="before")
    @classmethod
    def _int(cls, v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0


class Judgment(BaseModel):
    test: str
    verdict: Literal["test_bug", "product_bug", "unclear"]
    reason: str = ""
    fix_instruction: str = ""
    product_fix: ProductFix | None = None

    @field_validator("verdict", mode="before")
    @classmethod
    def _norm(cls, v: str) -> str:
        v = str(v).strip().lower().replace("-", "_").replace(" ", "_")
        return v if v in ("test_bug", "product_bug", "unclear") else "unclear"


class JudgeResult(BaseModel):
    judgments: list[Judgment] = Field(default_factory=list)


def _numbered(code: str) -> str:
    return "\n".join(f"{i:4d}| {line}" for i, line in enumerate(code.splitlines(), 1))


class Fixer(Agent):
    name = "fixer"

    def __init__(self, *args, framework: TestFramework, language: str = "Korean", **kwargs):
        super().__init__(*args, **kwargs)
        self.framework = framework
        self.language = language

    def _context(self, analysis: AnalysisResult, functions: list[FunctionInfo], includes: list[str]) -> str:
        return (
            "## Headers to include\n" + "\n".join(f'#include "{h}"' for h in includes) + "\n\n"
            "## Product source files\n" + render_sources(analysis, source_files_for(analysis, functions)) + "\n"
        )

    def fix_build(self, analysis: AnalysisResult, functions: list[FunctionInfo], includes: list[str],
                  test_name: str, code: str, diagnostics: list[Diagnostic], log_excerpt: str) -> str:
        system = load_prompt("fixer_build", framework_rules=self.framework.writer_rules())
        diag_text = "\n".join(d.short() for d in diagnostics[:MAX_DIAGNOSTICS])
        user = (
            self._context(analysis, functions, includes)
            + f"## Test file `{test_name}` (line numbers added for reference)\n```\n{_numbered(code)}\n```\n\n"
            + f"## Compiler errors\n```\n{diag_text}\n```\n\n"
            + f"## Compiler output excerpt\n```\n{log_excerpt[-6000:]}\n```\n\n"
            + "Return the whole corrected file without line numbers."
        )
        return self.ask_code(system, user)

    def judge(self, analysis: AnalysisResult, functions: list[FunctionInfo], plan: TestPlan, code: str,
              failures: list[CaseResult]) -> list[Judgment]:
        system = load_prompt("fixer_judge", language=self.language)
        by_name = {tc.full_name: tc for tc in plan.test_cases}
        items = []
        for f in failures:
            tc = by_name.get(f.full_name)
            items.append({
                "test": f.full_name,
                "status": f.status,
                "planned": tc.model_dump(include={"id", "function", "description", "input", "expected", "notes"})
                if tc else None,
                "failure_output": f.message[-MAX_MESSAGE:],
            })
        user = (
            self._context(analysis, functions, [])
            + f"## Test file\n```cpp\n{code}\n```\n\n"
            + "## Failed tests\n```json\n" + json.dumps(items, ensure_ascii=False, indent=1) + "\n```\n\n"
            + "Judge every failed test listed above."
        )
        result = self.ask_json(system, user, JudgeResult)
        wanted = {f.full_name for f in failures}
        judged = {j.test: j for j in result.judgments if j.test in wanted}
        # A failure the model skipped stays unresolved rather than silently passing as fixed.
        for name in wanted - judged.keys():
            judged[name] = Judgment(test=name, verdict="unclear", reason="(판정 누락)")
        return [judged[f.full_name] for f in failures]

    def fix_tests(self, analysis: AnalysisResult, functions: list[FunctionInfo], includes: list[str],
                  code: str, judgments: list[Judgment]) -> str:
        system = load_prompt("fixer_tests", framework_rules=self.framework.writer_rules())
        fixes = [{"test": j.test, "reason": j.reason, "instruction": j.fix_instruction}
                 for j in judgments if j.verdict == "test_bug"]
        user = (
            self._context(analysis, functions, includes)
            + f"## Current test file\n```cpp\n{code}\n```\n\n"
            + "## Fixes to apply\n```json\n" + json.dumps(fixes, ensure_ascii=False, indent=1) + "\n```\n"
        )
        return self.ask_code(system, user)
