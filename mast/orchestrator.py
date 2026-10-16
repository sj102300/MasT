"""Pipeline: Analyzer -> Planner -> Writer (-> Builder -> Verifier -> Fixer, later milestones)."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .agents.base import CallLog
from .agents.context import header_files
from .agents.models import GeneratedTest, TestPlan
from .agents.planner import Planner
from .agents.writer import Writer
from .analyzer import AnalysisResult, FunctionInfo, analyze_target
from .config import AppConfig
from .frameworks import get_framework
from .llm import LLMClient, create_client


@dataclass
class Event:
    stage: str
    message: str
    data: dict = field(default_factory=dict)


EventSink = Callable[[Event], None]


@dataclass
class RunRequest:
    project_root: Path
    target: Path
    functions: list[str] = field(default_factory=list)  # qualified names; empty = all testable
    search_dirs: list[Path] = field(default_factory=list)


@dataclass
class RunState:
    run_dir: Path
    analysis: AnalysisResult | None = None
    functions: list[FunctionInfo] = field(default_factory=list)
    plan: TestPlan | None = None
    test: GeneratedTest | None = None
    usage: dict = field(default_factory=dict)


def new_run_dir(base: Path, target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = base / f"{stamp}-{target.stem}"
    n = 1
    while path.exists():
        n += 1
        path = base / f"{stamp}-{target.stem}-{n}"
    path.mkdir(parents=True)
    return path


class Pipeline:
    def __init__(self, cfg: AppConfig, on_event: EventSink | None = None,
                 llm_factory: Callable[[str], LLMClient] | None = None):
        self.cfg = cfg
        self.on_event = on_event or (lambda e: None)
        self.llm_factory = llm_factory or (lambda agent: create_client(cfg.llm_for(agent)))
        self.framework = get_framework(cfg.run.framework)

    def emit(self, stage: str, message: str, **data) -> None:
        self.on_event(Event(stage, message, data))

    def _save(self, state: RunState, name: str, payload) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
        (state.run_dir / name).write_text(text, encoding="utf-8")

    def run(self, req: RunRequest, run_dir: Path | None = None) -> RunState:
        run_dir = run_dir or new_run_dir(Path(self.cfg.run.output_dir), req.target)
        state = RunState(run_dir=run_dir)
        log = CallLog(run_dir / "llm_calls.jsonl")

        self.emit("analyze", f"Analyzing {req.target}")
        state.analysis = analyze_target(req.target, req.project_root, req.search_dirs)
        self._save(state, "analysis.json", state.analysis.model_dump())
        fns = state.analysis.testable_functions()
        if req.functions:
            wanted = set(req.functions)
            fns = [f for f in fns if f.qualified_name in wanted or f.name in wanted]
        if not fns:
            raise ValueError(f"No testable functions found in {req.target}")
        state.functions = fns
        self.emit("analyze", f"{len(fns)} testable functions", functions=[f.qualified_name for f in fns])

        planner = Planner(self.llm_factory("planner"), log, language=self.cfg.run.language)
        self.emit("plan", "Designing test cases")
        state.plan = planner.plan(state.analysis, fns)
        self._save(state, "plan.json", state.plan.model_dump())
        self.emit("plan", f"{len(state.plan.test_cases)} test cases", count=len(state.plan.test_cases))

        writer = Writer(self.llm_factory("writer"), log, framework=self.framework)
        includes = [Path(h).name for h in header_files(state.analysis, fns)]
        test_name = f"{req.target.stem}_test.cpp"
        self.emit("write", f"Writing {test_name}")
        state.test = writer.write(state.analysis, fns, state.plan, includes, test_name, str(req.target))
        tests_dir = run_dir / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / test_name).write_text(state.test.content, encoding="utf-8")
        self.emit("write", f"Wrote tests/{test_name}", path=str(tests_dir / test_name))

        state.usage = _sum_usage(planner, writer)
        self._save(state, "usage.json", state.usage)
        return state


def _sum_usage(*agents) -> dict:
    total = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    for a in agents:
        for k in total:
            total[k] += a.usage[k]
    return total
