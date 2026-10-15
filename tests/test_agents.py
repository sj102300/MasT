import copy
import json
from pathlib import Path

import pytest

from fake_responses import PLAN, TEST_CODE, code_reply, plan_reply
from mast.agents import Planner, TestPlan, Writer
from mast.agents.base import extract_code_block, load_prompt
from mast.analyzer import analyze_target
from mast.config import AppConfig
from mast.frameworks import GTestFramework
from mast.llm import FakeLLM, LLMError
from mast.orchestrator import Pipeline, RunRequest

ROOT = Path(__file__).resolve().parent.parent
CALC = ROOT / "examples" / "calculator"


@pytest.fixture
def analysis():
    return analyze_target(CALC / "src" / "calculator.cpp", CALC)


def test_prompts_load_and_substitute():
    assert "Korean" in load_prompt("planner", language="Korean")
    writer = Writer(FakeLLM(), framework=GTestFramework()).system_prompt()
    assert "{framework_rules}" not in writer and "gtest_main" in writer


def test_extract_code_block():
    assert extract_code_block(code_reply()) == TEST_CODE
    with pytest.raises(LLMError):
        extract_code_block("sorry, no code")


def test_planner_filters_unknown_functions_and_renumbers(analysis):
    fns = [f for f in analysis.testable_functions() if f.name in ("add", "divide", "factorial")]
    plan = copy.deepcopy(PLAN)
    plan["test_cases"].append({"id": "X", "function": "nope::other", "suite": "S", "name": "N"})
    plan["test_cases"].append(dict(plan["test_cases"][0], id="TC099"))  # duplicate name
    fake = FakeLLM([json.dumps(plan)])
    result = Planner(fake).plan(analysis, fns)
    assert [tc.id for tc in result.test_cases] == ["TC001", "TC002", "TC003", "TC004", "TC005"]
    names = [tc.full_name for tc in result.test_cases]
    assert len(set(names)) == len(names)
    # prompt contained the source files and the function list
    user = fake.calls[0][1][0].content
    assert "calc::Calculator::factorial" in user and "include/calculator.h" in user


def test_planner_retries_on_bad_json(analysis):
    fns = analysis.testable_functions()[:1]
    fake = FakeLLM(["not json at all", plan_reply()])
    plan = Planner(fake).plan(analysis, fns)
    assert len(fake.calls) == 2
    assert "could not be used" in fake.calls[1][1][-1].content
    assert all(tc.function == fns[0].qualified_name for tc in plan.test_cases)


def test_testcase_name_sanitized():
    plan = TestPlan.model_validate(
        {"test_cases": [{"id": "1", "function": "f", "suite": "My Suite", "name": "add_two-values", "category": "Edge"}]}
    )
    tc = plan.test_cases[0]
    assert tc.suite == "MySuite" and tc.name == "addtwovalues" and tc.category == "normal"


def test_writer_returns_code(analysis):
    fake = FakeLLM([code_reply()])
    plan = TestPlan.model_validate(PLAN)
    out = Writer(fake, framework=GTestFramework()).write(
        analysis, analysis.testable_functions(), plan, ["calculator.h"], "calculator_test.cpp", "x")
    assert out.content == TEST_CODE
    assert '#include "calculator.h"' in fake.calls[0][1][0].content


def test_pipeline_end_to_end_with_fake_llm(tmp_path):
    replies = {"planner": FakeLLM([plan_reply()]), "writer": FakeLLM([code_reply()])}
    cfg = AppConfig.model_validate({"run": {"output_dir": str(tmp_path)}})
    events = []
    pipe = Pipeline(cfg, events.append, llm_factory=lambda agent: replies[agent])
    state = pipe.run(RunRequest(project_root=CALC, target=CALC / "src" / "calculator.cpp"))
    assert (state.run_dir / "tests" / "calculator_test.cpp").read_text(encoding="utf-8") == TEST_CODE
    for name in ("analysis.json", "plan.json", "usage.json", "llm_calls.jsonl"):
        assert (state.run_dir / name).is_file()
    assert [e.stage for e in events][:2] == ["analyze", "analyze"]
    assert len(state.plan.test_cases) == 4
