"""Canned LLM replies for the calculator example (used by pipeline tests)."""
import json

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

TEST_CODE = """\
#include <gtest/gtest.h>

#include <stdexcept>

#include "calculator.h"

// TC001: 양수 덧셈
TEST(CalculatorTest, AddPositive) {
    calc::Calculator c;
    EXPECT_EQ(c.add(2, 3), 5);
}

// TC002: 0으로 나누기
TEST(CalculatorTest, DivideByZeroThrows) {
    calc::Calculator c;
    EXPECT_THROW(c.divide(1.0, 0.0), std::invalid_argument);
}

// TC003: 0! = 1
TEST(CalculatorTest, FactorialOfZeroIsOne) {
    EXPECT_EQ(calc::Calculator::factorial(0), 1u);
}

// TC004: 5! = 120
TEST(CalculatorTest, FactorialOfFive) {
    EXPECT_EQ(calc::Calculator::factorial(5), 120u);
}
"""


def plan_reply() -> str:
    return "```json\n" + json.dumps(PLAN, ensure_ascii=False) + "\n```"


def code_reply(code: str = TEST_CODE) -> str:
    return "Here is the file:\n```cpp\n" + code + "```\n"
