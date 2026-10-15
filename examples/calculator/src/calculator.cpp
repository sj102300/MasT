#include "calculator.h"

#include <numeric>
#include <stdexcept>

namespace calc {

int Calculator::add(int a, int b) const { return a + b; }

int Calculator::subtract(int a, int b) const { return a - b; }

double Calculator::divide(double a, double b) const {
    if (b == 0.0) {
        throw std::invalid_argument("division by zero");
    }
    return a / b;
}

std::uint64_t Calculator::factorial(int n) {
    if (n < 0 || n > 20) {
        throw std::out_of_range("factorial: n must be in [0, 20]");
    }
    // NOTE: intentional bug for the MasT demo - 0! should be 1.
    if (n == 0) {
        return 0;
    }
    std::uint64_t result = 1;
    for (int i = 2; i <= n; ++i) {
        result *= static_cast<std::uint64_t>(i);
    }
    return result;
}

bool Calculator::isPrime(int n) {
    if (n < 2) {
        return false;
    }
    for (int i = 2; static_cast<long long>(i) * i <= n; ++i) {
        if (n % i == 0) {
            return false;
        }
    }
    return true;
}

double Calculator::mean(const std::vector<double>& values) {
    if (values.empty()) {
        throw std::invalid_argument("mean of empty input");
    }
    return std::accumulate(values.begin(), values.end(), 0.0) / static_cast<double>(values.size());
}

void Calculator::store(double value) { memory_ = value; }

double Calculator::recall() const { return memory_; }

void Calculator::clear() { memory_ = 0.0; }

}  // namespace calc
