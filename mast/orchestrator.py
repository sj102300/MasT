"""Pipeline: Analyzer -> Planner -> Writer -> [Builder -> Verifier -> Fixer]* -> result."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .agents.base import CallLog
from .agents.context import header_files
from .agents.fixer import Fixer, Judgment
from .agents.models import GeneratedTest, TestPlan
from .agents.planner import Planner
from .agents.writer import Writer
from .analyzer import AnalysisResult, FunctionInfo, analyze_target
from .build import Builder, BuildSetupError, header_dirs_for, run_tests
from .config import AppConfig
from .frameworks import get_framework
from .llm import LLMClient, LLMError, create_client
from .verify import Locator, Verdict, verify

Outcome = Literal["pass", "product_bugs", "env_error", "unresolved", "generated_only", "error"]


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
    functions: list[str] = field(default_factory=list)  # qualified or short names; empty = all testable
    search_dirs: list[Path] = field(default_factory=list)
    project: Path | None = None  # .vcxproj / CMake dir used for building; default project_root
    build: bool = True


class Iteration(BaseModel):
    index: int
    action: str  # what produced the test file built in this iteration
    verdict: Verdict
    test_file: str
    build_seconds: float = 0.0
    judgments: list[Judgment] = Field(default_factory=list)


class RunResult(BaseModel):
    outcome: Outcome
    message: str = ""
    iterations: list[Iteration] = Field(default_factory=list)
    judgments: dict[str, Judgment] = Field(default_factory=dict)  # latest judgment per failing test
    backend: str = ""
    passed: int = 0
    total: int = 0


@dataclass
class RunState:
    run_dir: Path
    analysis: AnalysisResult | None = None
    functions: list[FunctionInfo] = field(default_factory=list)
    plan: TestPlan | None = None
    test: GeneratedTest | None = None
    result: RunResult | None = None
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


def _signature(v: Verdict) -> str:
    if v.kind in ("build_error_test", "build_error_env"):
        return v.kind + "|" + "|".join(sorted(d.short() for d in v.diagnostics))
    return v.kind + "|" + "|".join(sorted(f"{f.full_name}:{f.message[:300]}" for f in v.failures))


class Pipeline:
    def __init__(self, cfg: AppConfig, on_event: EventSink | None = None,
                 llm_factory: Callable[[str], LLMClient] | None = None):
        self.cfg = cfg
        self.on_event = on_event or (lambda e: None)
        self.llm_factory = llm_factory or (lambda agent: create_client(cfg.llm_for(agent)))
        self.framework = get_framework(cfg.run.framework)
        self.agents: list = []

    def emit(self, stage: str, message: str, **data) -> None:
        self.on_event(Event(stage, message, data))

    def _save(self, state: RunState, name: str, payload) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
        (state.run_dir / name).write_text(text, encoding="utf-8")

    def _agent(self, cls, log: CallLog, **kwargs):
        agent = cls(self.llm_factory(cls.name), log, **kwargs)
        self.agents.append(agent)
        return agent

    def run(self, req: RunRequest, run_dir: Path | None = None) -> RunState:
        run_dir = run_dir or new_run_dir(Path(self.cfg.run.output_dir), req.target)
        state = RunState(run_dir=run_dir)
        log = CallLog(run_dir / "llm_calls.jsonl")
        self.agents = []
        try:
            self._generate(req, state, log)
            if req.build:
                state.result = self._build_loop(req, state, log)
            else:
                state.result = RunResult(outcome="generated_only", message="빌드 생략 (--no-build)")
        finally:
            state.usage = _sum_usage(self.agents)
            self._save(state, "usage.json", state.usage)
            if state.result is not None:
                self._save(state, "result.json", state.result.model_dump())
        self.emit("done", f"{state.result.outcome}: {state.result.message}", outcome=state.result.outcome)
        return state

    # -- generation --------------------------------------------------------
    def _generate(self, req: RunRequest, state: RunState, log: CallLog) -> None:
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

        planner = self._agent(Planner, log, language=self.cfg.run.language)
        self.emit("plan", "Designing test cases")
        state.plan = planner.plan(state.analysis, fns)
        self._save(state, "plan.json", state.plan.model_dump())
        self.emit("plan", f"{len(state.plan.test_cases)} test cases", count=len(state.plan.test_cases))

        writer = self._agent(Writer, log, framework=self.framework)
        includes = [Path(h).name for h in header_files(state.analysis, fns)]
        test_name = f"{req.target.stem}_test.cpp"
        self.emit("write", f"Writing {test_name}")
        state.test = writer.write(state.analysis, fns, state.plan, includes, test_name, str(req.target))
        self._write_test(state, state.test.content, version=0)
        self.emit("write", f"Wrote tests/{test_name}", path=str(self._test_path(state)))

    def _test_path(self, state: RunState) -> Path:
        assert state.test is not None
        return state.run_dir / "tests" / state.test.path

    def _write_test(self, state: RunState, content: str, version: int) -> Path:
        assert state.test is not None
        state.test.content = content
        path = self._test_path(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        # BOM: MSVC on Korean Windows otherwise reads UTF-8 comments as cp949
        path.write_text(content, encoding="utf-8-sig")
        history = state.run_dir / "history"
        history.mkdir(exist_ok=True)
        (history / f"{path.stem}.v{version}{path.suffix}").write_text(content, encoding="utf-8-sig")
        return path

    # -- build / verify / fix ----------------------------------------------
    def _build_loop(self, req: RunRequest, state: RunState, log: CallLog) -> RunResult:
        assert state.analysis and state.test and state.plan
        build_dir = state.run_dir / "build"
        result = RunResult(outcome="unresolved")
        try:
            builder = Builder(self.cfg.build, req.project or req.project_root,
                              header_dirs_for([f.decl_file for f in state.functions], req.project_root))
        except BuildSetupError as e:
            result.outcome, result.message = "env_error", str(e)
            return result
        result.backend = builder.backend
        fixer = self._agent(Fixer, log, framework=self.framework, language=self.cfg.run.language)
        locator: Locator | None = None
        action = "write"
        prev_sig = None
        max_iter = self.cfg.run.max_fix_iterations

        for index in range(max_iter + 1):
            test_path = self._test_path(state)
            self.emit("build", f"[{index}] Building ({builder.backend})", iteration=index)
            try:
                builder.prepare(build_dir, [test_path])
                build = builder.build(build_dir, self.cfg.run.build_timeout_sec)
            except BuildSetupError as e:
                result.outcome, result.message = "env_error", str(e)
                return result
            if locator is None:
                locator = Locator(test_path.parent, builder.project_dir, builder.gtest_root, [test_path.stem],
                                  build_dir)
            run = None
            if build.ok:
                self.emit("test", f"[{index}] Running tests", iteration=index)
                run = run_tests(build.exe, build_dir, self.cfg.run.test_timeout_sec)
            verdict = verify(build, run, locator)
            it = Iteration(index=index, action=action, verdict=verdict, test_file=str(test_path),
                           build_seconds=build.seconds)
            result.iterations.append(it)
            result.passed, result.total = verdict.passed, verdict.total
            self._save(state, "build.log", build.log)
            if run is not None:
                self._save(state, "test_output.log", run.output)
            self.emit("verify", f"[{index}] {verdict.summary}", kind=verdict.kind, iteration=index)

            if verdict.kind == "pass":
                result.outcome, result.message = "pass", verdict.summary
                result.judgments = {}
                return result
            if verdict.kind in ("build_error_env", "run_error", "no_tests"):
                result.outcome = "env_error" if verdict.kind != "no_tests" else "unresolved"
                result.message = verdict.summary
                return result

            sig = _signature(verdict)
            if sig == prev_sig:
                result.message = "수정 후에도 같은 결과가 반복되어 중단"
                break
            prev_sig = sig

            if verdict.kind == "test_failures":
                failing = {f.full_name for f in verdict.failures}
                # keep judgments only for tests that still fail
                result.judgments = {k: v for k, v in result.judgments.items() if k in failing}
                to_judge = [f for f in verdict.failures if f.full_name not in result.judgments
                            or result.judgments[f.full_name].verdict == "test_bug"]
                if to_judge:
                    self.emit("fix", f"[{index}] Judging {len(to_judge)} failed tests", iteration=index)
                    try:
                        judged = fixer.judge(state.analysis, state.functions, state.plan, state.test.content,
                                             to_judge)
                    except LLMError as e:
                        result.message = f"Fixer 판정 실패: {e}"
                        break
                    it.judgments = judged
                    result.judgments.update({j.test: j for j in judged})
                test_bugs = [j for j in result.judgments.values() if j.verdict == "test_bug"]
                if not test_bugs:
                    kinds = {j.verdict for j in result.judgments.values()}
                    result.outcome = "product_bugs" if kinds == {"product_bug"} else "unresolved"
                    result.message = verdict.summary + " — 남은 실패는 제품 코드 문제 또는 판단 필요"
                    return result
                if index == max_iter:
                    break
                self.emit("fix", f"[{index}] Fixing {len(test_bugs)} test bugs", iteration=index)
                try:
                    code = fixer.fix_tests(state.analysis, state.functions, state.test.includes,
                                           state.test.content, test_bugs)
                except LLMError as e:
                    result.message = f"Fixer 수정 실패: {e}"
                    break
                action = "fix_tests"
            else:  # build_error_test
                if index == max_iter:
                    break
                self.emit("fix", f"[{index}] Fixing {len(verdict.diagnostics)} compile errors", iteration=index)
                try:
                    code = fixer.fix_build(state.analysis, state.functions, state.test.includes,
                                           state.test.path, state.test.content, verdict.diagnostics,
                                           verdict.log_excerpt)
                except LLMError as e:
                    result.message = f"Fixer 수정 실패: {e}"
                    break
                action = "fix_build"
            self._write_test(state, code, version=index + 1)

        result.outcome = "unresolved"
        if not result.message:
            result.message = f"최대 수정 횟수({max_iter}) 도달: {result.iterations[-1].verdict.summary}"
        return result


def _sum_usage(agents) -> dict:
    total = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    for a in agents:
        for k in total:
            total[k] += a.usage[k]
    return total
