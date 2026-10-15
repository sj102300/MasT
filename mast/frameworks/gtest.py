from __future__ import annotations

from .base import TestFramework

GTEST_VERSION = "1.17.0"


class GTestFramework(TestFramework):
    name = "gtest"

    def writer_rules(self) -> str:
        return """\
Framework: GoogleTest {version} (C++17). The test binary links gtest_main, so do NOT write main().
- Start with `#include <gtest/gtest.h>` followed by the product headers given to you.
- One TEST()/TEST_F() per test case. Use the suite and test names from the plan exactly.
- Put a comment `// <TC id>: <short description>` above each test.
- Use EXPECT_* (not ASSERT_*) unless continuing would crash (e.g. null pointer, empty container index).
- Floating point: EXPECT_DOUBLE_EQ / EXPECT_FLOAT_EQ, or EXPECT_NEAR with an explicit tolerance.
- Exceptions: EXPECT_THROW(stmt, ExactType), EXPECT_NO_THROW(stmt).
- Strings: EXPECT_EQ with std::string; C strings: EXPECT_STREQ.
- Use a fixture (TEST_F with a class deriving ::testing::Test) only when several tests share setup.
- Code must compile with both MSVC 2019 (v142) and GCC: no compiler-specific extensions,
  no designated initializers, no <bits/...> headers, include every standard header you use.
- Mocking frameworks (gmock) are not available. Do not use them.""".format(version=GTEST_VERSION)

    def file_header(self, includes: list[str]) -> str:
        lines = ["#include <gtest/gtest.h>", ""]
        lines += [f'#include "{inc}"' for inc in includes]
        return "\n".join(lines) + "\n"


def get_framework(name: str) -> TestFramework:
    if name == "gtest":
        return GTestFramework()
    raise ValueError(f"Unknown test framework: {name}")
