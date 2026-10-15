#pragma once

#include <cstdint>
#include <vector>

namespace calc {

/// Basic integer/floating-point calculator.
class Calculator {
public:
    Calculator() = default;

    /// Returns a + b.
    int add(int a, int b) const;

    /// Returns a - b.
    int subtract(int a, int b) const;

    /// Returns a / b. Throws std::invalid_argument when b == 0.
    double divide(double a, double b) const;

    /// Returns n! for 0 <= n <= 20. Throws std::out_of_range otherwise.
    static std::uint64_t factorial(int n);

    /// Returns true if n is a prime number. Values below 2 are not prime.
    static bool isPrime(int n);

    /// Arithmetic mean of the values. Throws std::invalid_argument on empty input.
    static double mean(const std::vector<double>& values);

    /// Stores a value into memory.
    void store(double value);

    /// Returns the stored value (0.0 if nothing stored).
    double recall() const;

    /// Clears the memory to 0.0.
    void clear();

private:
    double memory_ = 0.0;
};

}  // namespace calc
