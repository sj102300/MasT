from __future__ import annotations

from ..analyzer import AnalysisResult, FunctionInfo
from .base import Agent, load_prompt
from .context import render_functions, render_sources, source_files_for
from .models import TestPlan

CHUNK_SIZE = 12


class Planner(Agent):
    name = "planner"

    def __init__(self, *args, language: str = "Korean", **kwargs):
        super().__init__(*args, **kwargs)
        self.language = language

    def plan(self, analysis: AnalysisResult, functions: list[FunctionInfo]) -> TestPlan:
        system = load_prompt("planner", language=self.language)
        sources = render_sources(analysis, source_files_for(analysis, functions))
        cases = []
        for start in range(0, len(functions), CHUNK_SIZE):
            chunk = functions[start : start + CHUNK_SIZE]
            user = (
                "## Functions to test\n" + render_functions(chunk) + "\n\n"
                "## Source files\n" + sources + "\n"
                f"Design the test cases. Number ids starting at TC{len(cases) + 1:03d}."
            )
            plan = self.ask_json(system, user, TestPlan)
            wanted = {fn.qualified_name for fn in chunk}
            cases += [tc for tc in plan.test_cases if tc.function in wanted]
        # Renumber so ids are stable and sequential across chunks.
        renumbered = [tc.model_copy(update={"id": f"TC{i:03d}"}) for i, tc in enumerate(cases, 1)]
        return TestPlan(test_cases=renumbered).dedupe()
