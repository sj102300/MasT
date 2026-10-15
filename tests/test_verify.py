from pathlib import Path

from mast.build import BuildResult, CaseResult, TestRunResult
from mast.verify import Locator, parse_diagnostics, verify

RUN = Path("/work/run")
PRODUCT = Path("/work/product")
GTEST = Path("/cache/googletest-1.17.0")


def _loc():
    return Locator(RUN / "tests", PRODUCT, GTEST, ["calculator_test"], RUN / "build")


MSVC_LOG = r"""
  calculator_test.cpp
/work/run/tests/calculator_test.cpp(12,20): error C2039: 'addd': is not a member of 'calc::Calculator' [/work/run/build/mast_tests.vcxproj]
/work/run/tests/calculator_test.cpp(12,20): error C2039: 'addd': is not a member of 'calc::Calculator' [/work/run/build/mast_tests.vcxproj]
/work/product/src/calculator.cpp(3,10): fatal error C1083: Cannot open include file: 'foo.h': No such file or directory [/work/run/build/mast_tests.vcxproj]
C:\Program Files (x86)\Windows Kits\10\Include\ucrt\stdio.h(10,1): error C2059: syntax error [/work/run/build/mast_tests.vcxproj]
/work/product/src/calculator.cpp(9,1): warning C4244: conversion from 'double' to 'int' [/work/run/build/mast_tests.vcxproj]
calculator_test.obj : error LNK2019: unresolved external symbol "int __cdecl helper(int)" (?helper@@YAHH@Z) referenced in function "private: virtual void __cdecl A_B_Test::TestBody(void)" [/work/run/build/mast_tests.vcxproj]
/work/run/build/bin/mast_tests.exe : fatal error LNK1120: 1 unresolved externals [/work/run/build/mast_tests.vcxproj]
C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\MSBuild\Microsoft\VC\v160\Microsoft.CppBuild.targets(439,5): error MSB8020: The build tools for v143 (Platform Toolset = 'v143') cannot be found. [/work/run/build/mast_tests.vcxproj]
"""

GCC_LOG = """
In file included from /cache/googletest-1.17.0/googletest/include/gtest/gtest.h:71,
                 from /work/run/tests/calculator_test.cpp:1:
/work/run/tests/calculator_test.cpp: In member function 'virtual void A_B_Test::TestBody()':
/work/run/tests/calculator_test.cpp:3:46: error: 'class calc::Calculator' has no member named 'addd'; did you mean 'add'?
    3 | TEST(A, B) { calc::Calculator c; EXPECT_EQ(c.addd(1, 2), 3); }
      |                                              ^~~~
/work/product/src/x.cpp:3:10: fatal error: missing.h: No such file or directory
/usr/bin/ld: /tmp/ccM4DIy6.o: in function `L_B_Test::TestBody()':
link_test.cpp:(.text+0x2d): undefined reference to `notDefined(int)'
collect2: error: ld returned 1 exit status
"""


def test_parse_msvc_log():
    diags = parse_diagnostics(MSVC_LOG, _loc())
    summary = [(d.kind, d.code, d.location) for d in diags]
    assert summary == [
        ("compile", "C2039", "test"),
        ("compile", "C1083", "product"),
        ("compile", "C2059", "other"),
        ("link", "LNK2019", "test"),
        ("link", "LNK1120", "other"),
        ("build_system", "MSB8020", "other"),
    ]
    assert diags[0].line == 12 and diags[0].column == 20
    assert "[/work" not in diags[0].message


def test_parse_gcc_log():
    diags = parse_diagnostics(GCC_LOG, _loc())
    summary = [(d.kind, d.location, d.message[:20]) for d in diags]
    assert summary == [
        ("compile", "test", "'class calc::Calcula"),
        ("compile", "product", "missing.h: No such f"),
        ("link", "other", "undefined reference "),
    ]


def test_verify_build_error_in_test_goes_to_fixer():
    v = verify(BuildResult(False, "cmake", "build", GCC_LOG), None, _loc())
    assert v.kind == "build_error_test"
    assert len(v.diagnostics) == 1 and "addd" in v.log_excerpt


def test_verify_env_error_with_hints():
    log = MSVC_LOG.replace("/work/run/tests/calculator_test.cpp(12,20): error C2039", "/x/y.cpp(1,1): error C2039")
    v = verify(BuildResult(False, "vcxproj", "build", log), None, _loc())
    assert v.kind == "build_error_env"
    assert any("build.toolset" in h for h in v.hints)
    assert any("build.include_dirs" in h for h in v.hints)


def _run(*cases, **kw):
    return TestRunResult(cases=list(cases), xml_found=True, **kw)


def test_verify_test_results():
    ok = BuildResult(True, "cmake", "build", "")
    p = CaseResult(suite="S", name="A", status="passed")
    f = CaseResult(suite="S", name="B", status="failed", message="boom")
    assert verify(ok, _run(p), _loc()).kind == "pass"
    v = verify(ok, _run(p, f), _loc())
    assert v.kind == "test_failures" and v.passed == 1 and v.total == 2 and v.failures[0].name == "B"
    assert verify(ok, _run(), _loc()).kind == "no_tests"
    assert verify(ok, TestRunResult(exit_code=-11), _loc()).kind == "run_error"


def test_locator_windows_paths():
    loc = Locator(Path("C:/run/tests"), Path("C:/proj"), None, ["calculator_test"])
    if Path("C:/run").is_absolute():  # only meaningful on Windows
        assert loc.locate(r"C:\run\tests\calculator_test.cpp") == "test"
        assert loc.locate(r"c:\proj\src\a.cpp") == "product"
    assert loc.locate("calculator_test.obj") == "test"
