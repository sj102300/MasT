"""Canned LLM replies for the calculator example (used by pipeline tests)."""
import json
from pathlib import Path

PLAN = {
    "test_cases": [
        {"id": "TC001", "function": "calc::Calculator::add", "suite": "CalculatorTest",
         "name": "AddPositive", "category": "normal", "description": "양수 덧셈",
         "input": "add(2, 3)", "expected": "5"},
        {"id": "TC002", "function": "calc::Calculator::divide", "suite": "CalculatorTest",
         "name": "DivideByZeroThrows", "category": "error", "description": "0으로 나누기",
         "input": "divide(1, 0)", "expected": "throws std::invalid_argument"},
        {"id": "TC003", "function": "calc::Calculator::factorial", "suite": "CalculatorTest",
         "name": "FactorialOfZeroIsOne", "category": "boundary", "description": "0! = 1",
         "input": "factorial(0)", "expected": "1", "notes": "implementation returns 0"},
        {"id": "TC004", "function": "calc::Calculator::factorial", "suite": "CalculatorTest",
         "name": "FactorialOfFive", "category": "normal", "description": "5! = 120",
         "input": "factorial(5)", "expected": "120"},
    ]
}

TEST_CODE = (Path(__file__).resolve().parent.parent / "mast" / "selftest" / "calculator_selftest.cpp").read_text(
    encoding="utf-8")


def plan_reply() -> str:
    return "```json\n" + json.dumps(PLAN, ensure_ascii=False) + "\n```"


def code_reply(code: str = TEST_CODE) -> str:
    return "Here is the file:\n```cpp\n" + code + "```\n"
