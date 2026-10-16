// MasT selftest: hand-written tests for examples/calculator (no LLM).
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
