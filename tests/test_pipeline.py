"""End-to-end pipeline with scripted LLM replies and a real CMake build (skipped without toolchain)."""
import json
import os
import shutil
from pathlib import Path

import pytest

from fake_responses import TEST_CODE, code_reply, plan_reply
from mast.build.gtest_source import GTestSourceError, ensure_gtest
from mast.config import AppConfig, BuildConfig
from mast.llm import FakeLLM
from mast.orchestrator import Pipeline, RunRequest

ROOT = Path(__file__).resolve().parent.parent
CALC = ROOT / "examples" / "calculator"

pytestmark = pytest.mark.skipif(
    shutil.which("cmake") is None or (os.name != "nt" and shutil.which("c++") is None),
    reason="cmake / C++ compiler not installed",
)


@pytest.fixture(scope="module")
def gtest_dir():
    cache = Path(os.environ.get("MAST_CACHE_DIR", "~/.mast/cache")).expanduser()
    try:
        return ensure_gtest(os.environ.get("MAST_GTEST_DIR"), cache, BuildConfig().gtest_url)
    except GTestSourceError as e:
        pytest.skip(f"googletest unavailable: {e}")


def judge(*items):
    return json.dumps({"judgments": [
        {"test": t, "verdict": v, "reason": "r", "fix_instruction": "fix it" if v == "test_bug" else "",
         "product_fix": {"file": "src/calculator.cpp", "line": 25, "description": "0! must be 1"}
         if v == "product_bug" else None}
        for t, v in items
    ]})


def run_pipeline(tmp_path, gtest_dir, replies, max_fix=3):
    cfg = AppConfig.model_validate({
        "run": {"output_dir": str(tmp_path), "max_fix_iterations": max_fix},
        "build": {"system": "cmake", "gtest_source_dir": str(gtest_dir)},
    })
    llms = {name: FakeLLM(r) for name, r in replies.items()}
    events = []
    state = Pipeline(cfg, events.append, llm_factory=lambda a: llms[a]).run(
        RunRequest(project_root=CALC, target=CALC / "src" / "calculator.cpp"))
    return state, llms, events


def test_planted_bug_reported_as_product_bug(tmp_path, gtest_dir):
    state, llms, _ = run_pipeline(tmp_path, gtest_dir, {
        "planner": [plan_reply()],
        "writer": [code_reply()],
        "fixer": [judge(("CalculatorTest.FactorialOfZeroIsOne", "product_bug"))],
    })
    res = state.result
    assert res.outcome == "product_bugs"
    assert len(res.iterations) == 1 and res.passed == 3 and res.total == 4
    j = res.judgments["CalculatorTest.FactorialOfZeroIsOne"]
    assert j.verdict == "product_bug" and j.product_fix.line == 25
    judged_user = llms["fixer"].calls[0][1][0].content
    assert "Which is: 0" in judged_user  # gtest failure output reached the judge
    assert (state.run_dir / "result.json").is_file() and (state.run_dir / "build.log").is_file()


def test_compile_error_fixed_then_product_bug(tmp_path, gtest_dir):
    broken = TEST_CODE.replace("c.add(2, 3)", "c.addd(2, 3)")
    state, llms, events = run_pipeline(tmp_path, gtest_dir, {
        "planner": [plan_reply()],
        "writer": [code_reply(broken)],
        "fixer": [code_reply(), judge(("CalculatorTest.FactorialOfZeroIsOne", "product_bug"))],
    })
    res = state.result
    assert [it.verdict.kind for it in res.iterations] == ["build_error_test", "test_failures"]
    assert [it.action for it in res.iterations] == ["write", "fix_build"]
    assert res.outcome == "product_bugs"
    fix_prompt = llms["fixer"].calls[0][1][0].content
    assert "addd" in fix_prompt
    assert (state.run_dir / "history" / "calculator_test.v0.cpp").is_file()
    assert (state.run_dir / "history" / "calculator_test.v1.cpp").is_file()
    assert any(e.stage == "fix" for e in events)


def test_test_bug_fixed_then_all_pass(tmp_path, gtest_dir):
    # drop the planted-bug test so the run can end green
    no_bug = TEST_CODE.split("// TC003")[0] + "// TC004" + TEST_CODE.split("// TC004")[1]
    wrong = no_bug.replace("EXPECT_EQ(c.add(2, 3), 5)", "EXPECT_EQ(c.add(2, 3), 6)")
    state, llms, _ = run_pipeline(tmp_path, gtest_dir, {
        "planner": [plan_reply()],
        "writer": [code_reply(wrong)],
        "fixer": [judge(("CalculatorTest.AddPositive", "test_bug")), code_reply(no_bug)],
    })
    res = state.result
    assert [it.verdict.kind for it in res.iterations] == ["test_failures", "pass"]
    assert res.outcome == "pass" and res.passed == res.total == 3
    assert '"instruction": "fix it"' in llms["fixer"].calls[1][1][0].content


def test_stops_when_fix_does_not_change_anything(tmp_path, gtest_dir):
    broken = TEST_CODE.replace("c.add(2, 3)", "c.addd(2, 3)")
    state, llms, _ = run_pipeline(tmp_path, gtest_dir, {
        "planner": [plan_reply()],
        "writer": [code_reply(broken)],
        "fixer": [code_reply(broken), code_reply(broken), code_reply(broken)],
    })
    res = state.result
    assert res.outcome == "unresolved"
    assert len(res.iterations) == 2  # second identical failure stops the loop
    assert "반복" in res.message


def test_missing_header_in_test_goes_to_fixer(tmp_path, gtest_dir):
    code = TEST_CODE.replace('#include "calculator.h"', '#include "calculator.h"\n#include "nowhere/missing.h"')
    # error is inside the test file, so the fixer gets a chance; make it give up identically
    state, _, _ = run_pipeline(tmp_path, gtest_dir, {
        "planner": [plan_reply()],
        "writer": [code_reply(code)],
        "fixer": [code_reply(code)],
    }, max_fix=1)
    assert state.result.outcome == "unresolved"
    assert state.result.iterations[0].verdict.kind == "build_error_test"
