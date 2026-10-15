#include <iostream>

#include "calculator.h"
#include "string_utils.h"

int main() {
    calc::Calculator c;
    std::cout << "2 + 3 = " << c.add(2, 3) << "\n";
    std::cout << "5! = " << calc::Calculator::factorial(5) << "\n";
    std::cout << "[" << strutil::trim("  hello  ") << "]\n";
    return 0;
}
