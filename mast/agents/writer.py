from __future__ import annotations

import json

from ..analyzer import AnalysisResult, FunctionInfo
from ..frameworks import TestFramework
from .base import Agent, load_prompt
from .context import render_sources, source_files_for
from .models import GeneratedTest, TestPlan


class Writer(Agent):
    name = "writer"

    def __init__(self, *args, framework: TestFramework, **kwargs):
        super().__init__(*args, **kwargs)
        self.framework = framework

    def system_prompt(self) -> str:
        return load_prompt("writer", framework_rules=self.framework.writer_rules())

    def write(self, analysis: AnalysisResult, functions: list[FunctionInfo], plan: TestPlan,
              includes: list[str], path: str, target: str) -> GeneratedTest:
        sources = render_sources(analysis, source_files_for(analysis, functions))
        plan_json = json.dumps(plan.model_dump()["test_cases"], ensure_ascii=False, indent=1)
        user = (
            "## Headers to include\n" + "\n".join(f'#include "{h}"' for h in includes) + "\n\n"
            "## Source files\n" + sources + "\n"
            "## Test plan\n```json\n" + plan_json + "\n```\n\n"
            f"Write the complete test file `{path}`."
        )
        code = self.ask_code(self.system_prompt(), user)
        return GeneratedTest(path=path, content=code, target=target, includes=includes)
