import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "mast" / "webui" / "app.py"


def _write_run(base: Path) -> None:
    run = base / "20260101-000000-calculator"
    (run / "tests").mkdir(parents=True)
    (run / "tests" / "calculator_test.cpp").write_text("#include <gtest/gtest.h>\n", encoding="utf-8-sig")
    (run / "plan.json").write_text(json.dumps({"test_cases": [
        {"id": "TC001", "function": "calc::Calculator::add", "suite": "CalculatorTest", "name": "Add",
         "category": "normal", "description": "덧셈", "input": "add(1,2)", "expected": "3", "notes": ""}]}),
        encoding="utf-8")
    (run / "result.json").write_text(json.dumps({
        "outcome": "pass", "message": "전체 통과 1/1", "passed": 1, "total": 1, "backend": "cmake",
        "iterations": [], "judgments": {},
        "cases": [{"suite": "CalculatorTest", "name": "Add", "status": "passed", "message": "", "seconds": 0}]}),
        encoding="utf-8")
    (run / "llm_calls.jsonl").write_text(json.dumps({
        "agent": "planner", "seconds": 1.0, "model": "m", "input_tokens": 1, "output_tokens": 2,
        "system": "s", "messages": [{"role": "user", "content": "u"}], "response": "r", "error": None}) + "\n",
        encoding="utf-8")


def test_app_renders_new_run_and_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_run(tmp_path / "runs")
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    target = at.selectbox[0]
    assert "src/calculator.cpp" in target.options
    assert "calc::Calculator::add" in at.multiselect[0].value
    # history tab picked up the run and rendered its report
    assert any("전체 통과" in m.value for m in at.markdown)
    assert any(df.value["테스트"].tolist() == ["CalculatorTest.Add"] for df in at.dataframe)
